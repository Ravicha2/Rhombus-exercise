from unittest.mock import patch, MagicMock
from django.test import TestCase
from django.core.cache import cache
from uploads.models import DatasetUpload
from jobs.models import ProcessingJob
from jobs.services import RegexSafetyError


class GenerateRegexTaskTest(TestCase):

    def setUp(self):
        cache.clear()
        self.dataset = DatasetUpload.objects.create(file_path="uploads/test.csv")

    @patch('jobs.tasks.LLMRegexService')
    def test_task_marks_job_running_then_success(self, mock_service):
        mock_service.get_or_generate_regex.return_value = r"\b\d+\b"
        job = ProcessingJob.objects.create(dataset=self.dataset)

        from jobs.tasks import generate_regex
        generate_regex(job.id, "find numbers")

        job.refresh_from_db()
        self.assertEqual(job.status, "SUCCESS")
        mock_service.get_or_generate_regex.assert_called_once_with("find numbers")

    @patch('jobs.tasks.LLMRegexService')
    def test_task_marks_job_failed_on_value_error(self, mock_service):
        mock_service.get_or_generate_regex.side_effect = ValueError("bad regex")
        job = ProcessingJob.objects.create(dataset=self.dataset)

        from jobs.tasks import generate_regex
        with self.assertRaises(ValueError):
            generate_regex(job.id, "bad prompt")

        job.refresh_from_db()
        self.assertEqual(job.status, "FAILED")
        self.assertIn("bad regex", job.error_message)

    @patch('jobs.tasks.LLMRegexService')
    def test_task_marks_job_failed_on_unexpected_exception(self, mock_service):
        mock_service.get_or_generate_regex.side_effect = RuntimeError("LLM down")
        job = ProcessingJob.objects.create(dataset=self.dataset)

        from jobs.tasks import generate_regex
        with self.assertRaises(RuntimeError):
            generate_regex(job.id, "any prompt")

        job.refresh_from_db()
        self.assertEqual(job.status, "FAILED")
        self.assertIn("LLM down", job.error_message)

    @patch('jobs.tasks.LLMRegexService')
    def test_task_marks_job_failed_on_backtracking_timeout(self, mock_service):
        mock_service.get_or_generate_regex.side_effect = RegexSafetyError("timeout")
        job = ProcessingJob.objects.create(dataset=self.dataset)

        from jobs.tasks import generate_regex
        with self.assertRaises(RegexSafetyError):
            generate_regex(job.id, "pathological pattern")

        job.refresh_from_db()
        self.assertEqual(job.status, "FAILED")
        self.assertIn("timeout", job.error_message)