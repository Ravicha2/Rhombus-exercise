from unittest.mock import patch, MagicMock
from django.test import TestCase
from django.core.cache import cache
from uploads.models import DatasetUpload
from jobs.models import ProcessingJob
from jobs.services import RegexSafetyError, TriageError


class ProcessJobTaskTest(TestCase):

    def setUp(self):
        cache.clear()
        self.dataset = DatasetUpload.objects.create(
            file_path="uploads/test.csv",
            status="READY",
            column_names=["email", "name", "phone"],
        )

    @patch("jobs.tasks.LLMRegexService")
    @patch("jobs.tasks.TriageService")
    def test_full_orchestration_marks_success(self, mock_triage, mock_regex):
        mock_triage.triage.return_value = [
            {"column": "email", "nl_pattern": "email addresses", "replacement": "[REDACTED]"},
        ]
        mock_regex.get_or_generate_regex.return_value = r"\b\S+@\S+\.\S+\b"
        job = ProcessingJob.objects.create(dataset=self.dataset, nl_prompt="redact all emails")

        from jobs.tasks import process_job
        process_job(job.id)

        job.refresh_from_db()
        self.assertEqual(job.status, "SUCCESS")
        mock_triage.triage.assert_called_once_with("redact all emails", ["email", "name", "phone"])
        mock_regex.get_or_generate_regex.assert_called_once_with("email addresses")
        self.assertEqual(job.transformations, [
            {"column": "email", "nl_pattern": "email addresses", "replacement": "[REDACTED]"},
        ])
        self.assertEqual(job.generated_regexes, [
            {"column": "email", "regex": r"\b\S+@\S+\.\S+\b"},
        ])

    @patch("jobs.tasks.LLMRegexService")
    @patch("jobs.tasks.TriageService")
    def test_multi_column_orchestration(self, mock_triage, mock_regex):
        mock_triage.triage.return_value = [
            {"column": "email", "nl_pattern": "email addresses", "replacement": "[EMAIL]"},
            {"column": "phone", "nl_pattern": "phone numbers", "replacement": "[PHONE]"},
        ]
        mock_regex.get_or_generate_regex.side_effect = [r"\S+@\S+", r"\d{3}-\d{4}"]
        job = ProcessingJob.objects.create(dataset=self.dataset, nl_prompt="redact emails and phones")

        from jobs.tasks import process_job
        process_job(job.id)

        job.refresh_from_db()
        self.assertEqual(job.status, "SUCCESS")
        self.assertEqual(len(job.transformations), 2)
        self.assertEqual(len(job.generated_regexes), 2)
        self.assertEqual(job.generated_regexes[0]["column"], "email")
        self.assertEqual(job.generated_regexes[1]["column"], "phone")

    @patch("jobs.tasks.LLMRegexService")
    @patch("jobs.tasks.TriageService")
    def test_triage_error_marks_failed(self, mock_triage, mock_regex):
        mock_triage.triage.side_effect = TriageError("Unknown columns referenced in triage: ['ssn']")
        job = ProcessingJob.objects.create(dataset=self.dataset, nl_prompt="redact SSNs")

        from jobs.tasks import process_job
        with self.assertRaises(TriageError):
            process_job(job.id)

        job.refresh_from_db()
        self.assertEqual(job.status, "FAILED")
        self.assertIn("Unknown columns", job.error_message)

    @patch("jobs.tasks.LLMRegexService")
    @patch("jobs.tasks.TriageService")
    def test_regex_generation_error_marks_failed(self, mock_triage, mock_regex):
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

    @patch("jobs.tasks.LLMRegexService")
    @patch("jobs.tasks.TriageService")
    def test_regex_safety_error_marks_failed(self, mock_triage, mock_regex):
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

    @patch("jobs.tasks.LLMRegexService")
    @patch("jobs.tasks.TriageService")
    def test_unexpected_error_marks_failed(self, mock_triage, mock_regex):
        mock_triage.triage.side_effect = RuntimeError("LLM down")
        job = ProcessingJob.objects.create(dataset=self.dataset, nl_prompt="redact emails")

        from jobs.tasks import process_job
        with self.assertRaises(RuntimeError):
            process_job(job.id)

        job.refresh_from_db()
        self.assertEqual(job.status, "FAILED")
        self.assertIn("LLM down", job.error_message)

