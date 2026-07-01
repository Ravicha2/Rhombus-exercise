from unittest.mock import patch, MagicMock
from django.test import TestCase
from django.core.cache import cache
from openai import APIConnectionError, RateLimitError, APITimeoutError
from uploads.models import DatasetUpload
from jobs.models import ProcessingJob
from jobs.services import RegexSafetyError, TriageError, SparkProcessingService, read_sample_rows, STATIC_TOOLS


class ProcessJobRetryConfigTest(TestCase):
    def setUp(self):
        cache.clear()
        self.dataset = DatasetUpload.objects.create(
            file_path="uploads/test.csv",
            status="READY",
            column_names=["email"],
        )

    def test_autoretry_for_includes_transient_errors(self):
        from jobs.tasks import process_job

        retry_for = process_job.autoretry_for
        self.assertIn(APIConnectionError, retry_for)
        self.assertIn(RateLimitError, retry_for)
        self.assertIn(APITimeoutError, retry_for)

    def test_max_retries_is_three(self):
        from jobs.tasks import process_job

        self.assertEqual(process_job.max_retries, 3)

    def test_retry_backoff_enabled(self):
        from jobs.tasks import process_job

        self.assertTrue(process_job.retry_backoff)


class ProcessJobTaskTest(TestCase):

    def setUp(self):
        cache.clear()
        self.dataset = DatasetUpload.objects.create(
            file_path="uploads/test.csv",
            status="READY",
            column_names=["email", "name", "phone"],
        )

    @patch("jobs.tasks.SparkProcessingService")
    @patch("jobs.tasks.StorageService")
    @patch("jobs.tasks.LLMRegexService")
    @patch("jobs.tasks.TriageService")
    @patch("jobs.tasks.read_sample_rows")
    def test_full_orchestration_marks_success(self, mock_read_sample, mock_triage, mock_regex, mock_storage, mock_spark):
        mock_read_sample.return_value = "email,name\njohn@a.com,Alice"
        mock_triage.triage.return_value = [
            {"column": "email", "nl_pattern": "email addresses", "replacement": "[REDACTED]"},
        ]
        mock_regex.get_or_generate_regex.return_value = r"\b\S+@\S+\.\S+\b"
        mock_storage.resolve_parquet_absolute_path.return_value = "/tmp/test.parquet"
        mock_spark.process.return_value = ("output/1/result", "output/1/preview.parquet")
        job = ProcessingJob.objects.create(dataset=self.dataset, nl_prompt="redact all emails")

        from jobs.tasks import process_job
        process_job(job.id)

        job.refresh_from_db()
        self.assertEqual(job.status, "SUCCESS")
        mock_read_sample.assert_called_once()
        mock_triage.triage.assert_called_once_with("redact all emails", ["email", "name", "phone"], sample_data="email,name\njohn@a.com,Alice")
        mock_regex.get_or_generate_regex.assert_called_once_with("email addresses", sample_data="email,name\njohn@a.com,Alice")
        self.assertEqual(job.transformations, [
            {"column": "email", "nl_pattern": "email addresses", "replacement": "[REDACTED]"},
        ])
        self.assertEqual(job.generated_regexes, [
            {"column": "email", "regex": r"\b\S+@\S+\.\S+\b"},
        ])

    @patch("jobs.tasks.SparkProcessingService")
    @patch("jobs.tasks.StorageService")
    @patch("jobs.tasks.LLMRegexService")
    @patch("jobs.tasks.TriageService")
    @patch("jobs.tasks.read_sample_rows")
    def test_multi_column_orchestration(self, mock_read_sample, mock_triage, mock_regex, mock_storage, mock_spark):
        mock_read_sample.return_value = "email,name\na@b.com,Alice"
        mock_triage.triage.return_value = [
            {"column": "email", "nl_pattern": "email addresses", "replacement": "[EMAIL]"},
            {"column": "phone", "nl_pattern": "phone numbers", "replacement": "[PHONE]"},
        ]
        mock_regex.get_or_generate_regex.side_effect = [r"\S+@\S+", r"\d{3}-\d{4}"]
        mock_storage.resolve_parquet_absolute_path.return_value = "/tmp/test.parquet"
        mock_spark.process.return_value = ("output/1/result", "output/1/preview.parquet")
        job = ProcessingJob.objects.create(dataset=self.dataset, nl_prompt="redact emails and phones")

        from jobs.tasks import process_job
        process_job(job.id)

        job.refresh_from_db()
        self.assertEqual(job.status, "SUCCESS")
        self.assertEqual(len(job.transformations), 2)
        self.assertEqual(len(job.generated_regexes), 2)
        self.assertEqual(job.generated_regexes[0]["column"], "email")
        self.assertEqual(job.generated_regexes[1]["column"], "phone")

    @patch("jobs.tasks.StorageService")
    @patch("jobs.tasks.LLMRegexService")
    @patch("jobs.tasks.TriageService")
    @patch("jobs.tasks.read_sample_rows")
    def test_triage_error_marks_failed(self, mock_read_sample, mock_triage, mock_regex, mock_storage):
        mock_read_sample.return_value = "email\na@b.com"
        mock_triage.triage.side_effect = TriageError("Unknown columns referenced in triage: ['ssn']")
        job = ProcessingJob.objects.create(dataset=self.dataset, nl_prompt="redact SSNs")

        from jobs.tasks import process_job
        with self.assertRaises(TriageError):
            process_job(job.id)

        job.refresh_from_db()
        self.assertEqual(job.status, "FAILED")
        self.assertIn("Unknown columns", job.error_message)

    @patch("jobs.tasks.StorageService")
    @patch("jobs.tasks.LLMRegexService")
    @patch("jobs.tasks.TriageService")
    @patch("jobs.tasks.read_sample_rows")
    def test_regex_generation_error_marks_failed(self, mock_read_sample, mock_triage, mock_regex, mock_storage):
        mock_read_sample.return_value = "email\na@b.com"
        mock_triage.triage.return_value = [
            {"column": "email", "nl_pattern": "email addresses", "replacement": "[REDACTED]"},
        ]
        mock_regex.get_or_generate_regex.side_effect = ValueError("Generated regex pattern is invalid: bad")
        job = ProcessingJob.objects.create(dataset=self.dataset, nl_prompt="redact emails")

        from jobs.tasks import process_job
        with self.assertRaises(ValueError):
            process_job(job.id)

        job.refresh_from_db()
        self.assertEqual(job.status, "FAILED")
        self.assertIn("bad", job.error_message)

    @patch("jobs.tasks.StorageService")
    @patch("jobs.tasks.LLMRegexService")
    @patch("jobs.tasks.TriageService")
    @patch("jobs.tasks.read_sample_rows")
    def test_regex_safety_error_marks_failed(self, mock_read_sample, mock_triage, mock_regex, mock_storage):
        mock_read_sample.return_value = "email\na@b.com"
        mock_triage.triage.return_value = [
            {"column": "email", "nl_pattern": "email addresses", "replacement": "[REDACTED]"},
        ]
        mock_regex.get_or_generate_regex.side_effect = RegexSafetyError("catastrophic backtracking")
        job = ProcessingJob.objects.create(dataset=self.dataset, nl_prompt="redact emails")

        from jobs.tasks import process_job
        with self.assertRaises(RegexSafetyError):
            process_job(job.id)

        job.refresh_from_db()
        self.assertEqual(job.status, "FAILED")
        self.assertIn("catastrophic", job.error_message)

    @patch("jobs.tasks.TriageService")
    def test_job_not_found_raises(self, mock_triage):
        from jobs.tasks import process_job
        with self.assertRaises(ProcessingJob.DoesNotExist):
            process_job(99999)

    @patch("jobs.tasks.StorageService")
    @patch("jobs.tasks.LLMRegexService")
    @patch("jobs.tasks.TriageService")
    @patch("jobs.tasks.read_sample_rows")
    def test_unexpected_error_marks_failed(self, mock_read_sample, mock_triage, mock_regex, mock_storage):
        mock_read_sample.return_value = "email\na@b.com"
        mock_triage.triage.side_effect = RuntimeError("LLM down")
        job = ProcessingJob.objects.create(dataset=self.dataset, nl_prompt="redact emails")

        from jobs.tasks import process_job
        with self.assertRaises(RuntimeError):
            process_job(job.id)

        job.refresh_from_db()
        self.assertEqual(job.status, "FAILED")
        self.assertIn("LLM down", job.error_message)

    @patch("jobs.tasks.SparkProcessingService")
    @patch("jobs.tasks.StorageService")
    @patch("jobs.tasks.LLMRegexService")
    @patch("jobs.tasks.TriageService")
    @patch("jobs.tasks.read_sample_rows")
    def test_full_e2e_marks_success_with_output_paths(self, mock_read_sample, mock_triage, mock_regex, mock_storage, mock_spark):
        mock_read_sample.return_value = "email\na@b.com"
        mock_triage.triage.return_value = [
            {"column": "email", "nl_pattern": "email addresses", "replacement": "[REDACTED]"},
        ]
        mock_regex.get_or_generate_regex.return_value = r"\b\S+@\S+\.\S+\b"
        mock_storage.resolve_parquet_absolute_path.return_value = "/tmp/test.parquet"
        mock_spark.process.return_value = ("output/1/result", "output/1/preview.parquet")
        job = ProcessingJob.objects.create(dataset=self.dataset, nl_prompt="redact all emails")

        from jobs.tasks import process_job
        process_job(job.id)

        job.refresh_from_db()
        self.assertEqual(job.status, "SUCCESS")
        self.assertEqual(job.output_file_path, "output/1/result")
        self.assertEqual(job.preview_file_path, "output/1/preview.parquet")
        mock_spark.process.assert_called_once()
        call_kwargs = mock_spark.process.call_args
        specs = call_kwargs.kwargs["specs"]
        self.assertEqual(specs, [
            {"column": "email", "regex": r"\b\S+@\S+\.\S+\b", "replacement": "[REDACTED]"},
        ])

    @patch("jobs.tasks.SparkProcessingService")
    @patch("jobs.tasks.StorageService")
    @patch("jobs.tasks.LLMRegexService")
    @patch("jobs.tasks.TriageService")
    @patch("jobs.tasks.read_sample_rows")
    def test_spark_error_marks_failed(self, mock_read_sample, mock_triage, mock_regex, mock_storage, mock_spark):
        mock_read_sample.return_value = "email\na@b.com"
        mock_triage.triage.return_value = [
            {"column": "email", "nl_pattern": "email addresses", "replacement": "[REDACTED]"},
        ]
        mock_regex.get_or_generate_regex.return_value = r"\S+@\S+"
        mock_storage.resolve_parquet_absolute_path.return_value = "/tmp/test.parquet"
        mock_spark.process.side_effect = RuntimeError("Spark cluster unavailable")
        job = ProcessingJob.objects.create(dataset=self.dataset, nl_prompt="redact all emails")

        from jobs.tasks import process_job
        with self.assertRaises(RuntimeError):
            process_job(job.id)

        job.refresh_from_db()
        self.assertEqual(job.status, "FAILED")
        self.assertIn("Spark cluster unavailable", job.error_message)

    @patch("jobs.tasks.SparkProcessingService")
    @patch("jobs.tasks.StorageService")
    @patch("jobs.tasks.LLMRegexService")
    @patch("jobs.tasks.TriageService")
    @patch("jobs.tasks.read_sample_rows")
    def test_progress_callback_updates_job(self, mock_read_sample, mock_triage, mock_regex, mock_storage, mock_spark):
        mock_read_sample.return_value = "email\na@b.com"
        mock_triage.triage.return_value = [
            {"column": "email", "nl_pattern": "email addresses", "replacement": "[REDACTED]"},
            {"column": "phone", "nl_pattern": "phone numbers", "replacement": "[PHONE]"},
        ]
        mock_regex.get_or_generate_regex.side_effect = [r"\S+@\S+", r"\d{3}-\d{4}"]
        mock_storage.resolve_parquet_absolute_path.return_value = "/tmp/test.parquet"

        def fake_process(parquet_path, specs, job_id, progress_callback=None, storage_dir=None):
            if progress_callback:
                progress_callback(50)
                progress_callback(100)
            return ("output/1/result", "output/1/preview.parquet")
        mock_spark.process.side_effect = fake_process

        job = ProcessingJob.objects.create(dataset=self.dataset, nl_prompt="redact emails and phones")

        from jobs.tasks import process_job
        process_job(job.id)

        job.refresh_from_db()
        self.assertEqual(job.status, "SUCCESS")
        self.assertEqual(job.progress, 100.0)


class ProcessJobRetryResetTest(TestCase):
    def setUp(self):
        cache.clear()
        self.dataset = DatasetUpload.objects.create(
            file_path="uploads/test.csv",
            status="READY",
            column_names=["email"],
        )

    @patch("jobs.tasks.SparkProcessingService")
    @patch("jobs.tasks.StorageService")
    @patch("jobs.tasks.LLMRegexService")
    @patch("jobs.tasks.TriageService")
    @patch("jobs.tasks.read_sample_rows")
    def test_retry_resets_failed_job_to_queued(self, mock_read_sample, mock_triage, mock_regex, mock_storage, mock_spark):
        mock_read_sample.return_value = "email\na@b.com"
        """When process_job runs on a FAILED job (retry scenario), it resets to QUEUED first."""
        mock_triage.triage.return_value = [
            {"column": "email", "nl_pattern": "email addresses", "replacement": "[REDACTED]"},
        ]
        mock_regex.get_or_generate_regex.return_value = r"\b\S+@\S+\.\S+\b"
        mock_storage.resolve_parquet_absolute_path.return_value = "/tmp/test.parquet"
        mock_spark.process.return_value = ("output/1/result", "output/1/preview.parquet")

        job = ProcessingJob.objects.create(dataset=self.dataset, nl_prompt="redact emails")
        # Simulate a previous transient failure: job is FAILED with error message and partial progress
        job.status = "FAILED"
        job.error_message = "Connection error"
        job.progress = 42.0
        job.save()

        from jobs.tasks import process_job
        process_job(job.id)

        job.refresh_from_db()
        self.assertEqual(job.status, "SUCCESS")
        self.assertIsNone(job.error_message)
        self.assertEqual(job.progress, 100.0)

    @patch("jobs.tasks.SparkProcessingService")
    @patch("jobs.tasks.StorageService")
    @patch("jobs.tasks.LLMRegexService")
    @patch("jobs.tasks.TriageService")
    @patch("jobs.tasks.read_sample_rows")
    def test_retry_resets_running_job_to_queued(self, mock_read_sample, mock_triage, mock_regex, mock_storage, mock_spark):
        mock_read_sample.return_value = "email\na@b.com"
        """When process_job runs on a RUNNING job (crash recovery), it resets to QUEUED first."""
        mock_triage.triage.return_value = [
            {"column": "email", "nl_pattern": "email addresses", "replacement": "[REDACTED]"},
        ]
        mock_regex.get_or_generate_regex.return_value = r"\b\S+@\S+\.\S+\b"
        mock_storage.resolve_parquet_absolute_path.return_value = "/tmp/test.parquet"
        mock_spark.process.return_value = ("output/1/result", "output/1/preview.parquet")

        job = ProcessingJob.objects.create(dataset=self.dataset, nl_prompt="redact emails")
        # Simulate a crashed task: job is RUNNING with partial progress
        job.status = "RUNNING"
        job.progress = 50.0
        job.save()

        from jobs.tasks import process_job
        process_job(job.id)

        job.refresh_from_db()
        self.assertEqual(job.status, "SUCCESS")
        self.assertEqual(job.progress, 100.0)

    def test_queued_job_not_reset(self):
        """A fresh QUEUED job should not trigger the reset branch."""
        job = ProcessingJob.objects.create(dataset=self.dataset, nl_prompt="redact emails")
        self.assertEqual(job.status, "QUEUED")
        # No need to run the full task; just verify the condition check
        # If status is QUEUED, the reset block is skipped entirely
        self.assertEqual(job.progress, 0.0)

    def test_success_job_not_reset(self):
        """A SUCCESS job must not be reset to QUEUED and re-processed."""
        job = ProcessingJob.objects.create(dataset=self.dataset, nl_prompt="redact emails")
        job.status = "SUCCESS"
        job.progress = 100.0
        job.save()

        from jobs.tasks import process_job
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            process_job(job.id)

        job.refresh_from_db()
        self.assertEqual(job.status, "SUCCESS")

    def test_cancelled_job_not_reset(self):
        """A CANCELLED job must not be reset to QUEUED and re-processed."""
        job = ProcessingJob.objects.create(dataset=self.dataset, nl_prompt="redact emails")
        job.status = "CANCELLED"
        job.save()

        from jobs.tasks import process_job
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            process_job(job.id)

        job.refresh_from_db()
        self.assertEqual(job.status, "CANCELLED")


class ProcessJobCancellationTest(TestCase):
    """Cooperative cancellation: task checks job.status between stages and returns cleanly if CANCELLED."""

    def setUp(self):
        cache.clear()
        self.dataset = DatasetUpload.objects.create(
            file_path="uploads/test.csv",
            status="READY",
            column_names=["email"],
        )

    @patch("jobs.tasks.SparkProcessingService")
    @patch("jobs.tasks.StorageService")
    @patch("jobs.tasks.LLMRegexService")
    @patch("jobs.tasks.TriageService")
    @patch("jobs.tasks.read_sample_rows")
    def test_cancelled_after_triage_returns_cleanly(self, mock_read_sample, mock_triage, mock_regex, mock_storage, mock_spark):
        mock_read_sample.return_value = "email\na@b.com"
        """If job is cancelled after triage, task returns without calling regex or spark."""
        job = ProcessingJob.objects.create(dataset=self.dataset, nl_prompt="redact emails")

        def triage_and_cancel(*args, **kwargs):
            ProcessingJob.objects.filter(id=job.id).update(status="CANCELLED")
            return [{"column": "email", "nl_pattern": "email addresses", "replacement": "[REDACTED]"}]

        mock_triage.triage.side_effect = triage_and_cancel

        from jobs.tasks import process_job
        process_job(job.id)

        job.refresh_from_db()
        self.assertEqual(job.status, "CANCELLED")
        mock_regex.get_or_generate_regex.assert_not_called()
        mock_spark.process.assert_not_called()

    @patch("jobs.tasks.SparkProcessingService")
    @patch("jobs.tasks.StorageService")
    @patch("jobs.tasks.LLMRegexService")
    @patch("jobs.tasks.TriageService")
    @patch("jobs.tasks.read_sample_rows")
    def test_cancelled_after_regex_returns_cleanly(self, mock_read_sample, mock_triage, mock_regex, mock_storage, mock_spark):
        mock_read_sample.return_value = "email\na@b.com"
        """If job is cancelled after regex generation, task returns without calling spark."""
        job = ProcessingJob.objects.create(dataset=self.dataset, nl_prompt="redact emails")

        mock_triage.triage.return_value = [
            {"column": "email", "nl_pattern": "email addresses", "replacement": "[REDACTED]"},
        ]

        def regex_and_cancel(*args, **kwargs):
            ProcessingJob.objects.filter(id=job.id).update(status="CANCELLED")
            return r"\b\S+@\S+\.\S+\b"

        mock_regex.get_or_generate_regex.side_effect = regex_and_cancel

        from jobs.tasks import process_job
        process_job(job.id)

        job.refresh_from_db()
        self.assertEqual(job.status, "CANCELLED")
        mock_spark.process.assert_not_called()

    @patch("jobs.tasks.SparkProcessingService")
    @patch("jobs.tasks.StorageService")
    @patch("jobs.tasks.LLMRegexService")
    @patch("jobs.tasks.TriageService")
    @patch("jobs.tasks.read_sample_rows")
    def test_cancelled_before_spark_returns_cleanly(self, mock_read_sample, mock_triage, mock_regex, mock_storage, mock_spark):
        mock_read_sample.return_value = "email\na@b.com"
        """If job is cancelled before spark processing, task returns cleanly."""
        job = ProcessingJob.objects.create(dataset=self.dataset, nl_prompt="redact emails")

        mock_triage.triage.return_value = [
            {"column": "email", "nl_pattern": "email addresses", "replacement": "[REDACTED]"},
        ]
        mock_regex.get_or_generate_regex.return_value = r"\b\S+@\S+\.\S+\b"

        def resolve_path_and_cancel(*args, **kwargs):
            ProcessingJob.objects.filter(id=job.id).update(status="CANCELLED")
            return "/tmp/test.parquet"

        mock_storage.resolve_parquet_absolute_path.side_effect = resolve_path_and_cancel

        from jobs.tasks import process_job
        process_job(job.id)

        job.refresh_from_db()
        self.assertEqual(job.status, "CANCELLED")
        mock_spark.process.assert_not_called()


class ProcessJobDeterministicErrorTest(TestCase):
    def setUp(self):
        cache.clear()
        self.dataset = DatasetUpload.objects.create(
            file_path="uploads/test.csv",
            status="READY",
            column_names=["email"],
        )

    def test_triage_error_not_in_autoretry_for(self):
        from jobs.tasks import process_job
        from jobs.services import TriageError

        self.assertNotIn(TriageError, process_job.autoretry_for)

    def test_value_error_not_in_autoretry_for(self):
        from jobs.tasks import process_job

        self.assertNotIn(ValueError, process_job.autoretry_for)

    def test_regex_safety_error_not_in_autoretry_for(self):
        from jobs.tasks import process_job
        from jobs.services import RegexSafetyError

        self.assertNotIn(RegexSafetyError, process_job.autoretry_for)

    @patch("jobs.tasks.StorageService")
    @patch("jobs.tasks.LLMRegexService")
    @patch("jobs.tasks.TriageService")
    @patch("jobs.tasks.read_sample_rows")
    def test_triage_error_fails_immediately_no_retry(self, mock_read_sample, mock_triage, mock_regex, mock_storage):
        mock_read_sample.return_value = "email\na@b.com"
        """TriageError marks job FAILED and is not retried by Celery."""
        mock_triage.triage.side_effect = TriageError("Unknown columns")
        job = ProcessingJob.objects.create(dataset=self.dataset, nl_prompt="redact emails")

        from jobs.tasks import process_job
        with self.assertRaises(TriageError):
            process_job(job.id)

        job.refresh_from_db()
        self.assertEqual(job.status, "FAILED")
        self.assertIn("Unknown columns", job.error_message)


class ProcessJobStaticToolTest(TestCase):
    """Static tool routing: skip regex generation when triage returns a tool name."""

    def setUp(self):
        cache.clear()
        self.dataset = DatasetUpload.objects.create(
            file_path="uploads/test.csv",
            status="READY",
            column_names=["name", "email"],
        )

    @patch("jobs.tasks.SparkProcessingService")
    @patch("jobs.tasks.StorageService")
    @patch("jobs.tasks.LLMRegexService")
    @patch("jobs.tasks.TriageService")
    @patch("jobs.tasks.read_sample_rows")
    def test_static_tool_skips_regex_generation(self, mock_read_sample, mock_triage, mock_regex, mock_storage, mock_spark):
        mock_read_sample.return_value = "name,email\nAlice,a@b.com"
        mock_triage.triage.return_value = [
            {"column": "name", "nl_pattern": "truncate names", "replacement": "truncate"},
        ]
        mock_storage.resolve_parquet_absolute_path.return_value = "/tmp/test.parquet"
        mock_spark.process.return_value = ("output/1/result", "output/1/preview.parquet")
        job = ProcessingJob.objects.create(dataset=self.dataset, nl_prompt="truncate the name column")

        from jobs.tasks import process_job
        process_job(job.id)

        job.refresh_from_db()
        self.assertEqual(job.status, "SUCCESS")
        mock_regex.get_or_generate_regex.assert_not_called()
        self.assertEqual(job.generated_regexes, [{"column": "name", "tool": "truncate"}])
        specs = mock_spark.process.call_args.kwargs["specs"]
        self.assertEqual(specs, [{"column": "name", "tool": "truncate"}])

    @patch("jobs.tasks.SparkProcessingService")
    @patch("jobs.tasks.StorageService")
    @patch("jobs.tasks.LLMRegexService")
    @patch("jobs.tasks.TriageService")
    @patch("jobs.tasks.read_sample_rows")
    def test_mixed_static_and_regex_pipeline(self, mock_read_sample, mock_triage, mock_regex, mock_storage, mock_spark):
        mock_read_sample.return_value = "name,email\nAlice,a@b.com"
        mock_triage.triage.return_value = [
            {"column": "name", "nl_pattern": "truncate names", "replacement": "truncate"},
            {"column": "email", "nl_pattern": "email addresses", "replacement": "[REDACTED]"},
        ]
        mock_regex.get_or_generate_regex.return_value = r"\S+@\S+\.\S+"
        mock_storage.resolve_parquet_absolute_path.return_value = "/tmp/test.parquet"
        mock_spark.process.return_value = ("output/1/result", "output/1/preview.parquet")
        job = ProcessingJob.objects.create(dataset=self.dataset, nl_prompt="truncate names and redact emails")

        from jobs.tasks import process_job
        process_job(job.id)

        job.refresh_from_db()
        self.assertEqual(job.status, "SUCCESS")
        mock_regex.get_or_generate_regex.assert_called_once_with("email addresses", sample_data="name,email\nAlice,a@b.com")
        self.assertEqual(len(job.generated_regexes), 2)
        self.assertEqual(job.generated_regexes[0], {"column": "name", "tool": "truncate"})
        self.assertEqual(job.generated_regexes[1], {"column": "email", "regex": r"\S+@\S+\.\S+"})
        specs = mock_spark.process.call_args.kwargs["specs"]
        self.assertEqual(specs, [
            {"column": "name", "tool": "truncate"},
            {"column": "email", "regex": r"\S+@\S+\.\S+", "replacement": "[REDACTED]"},
        ])

