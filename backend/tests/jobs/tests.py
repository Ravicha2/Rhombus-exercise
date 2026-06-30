from django.core.exceptions import ValidationError
from django.test import TestCase
from uploads.models import DatasetUpload
from jobs.models import ProcessingJob


class ProcessingJobModelTest(TestCase):

    def setUp(self):
        self.dataset = DatasetUpload.objects.create(file_path="uploads/test.csv")

    def test_create_processing_job_defaults(self):
        job = ProcessingJob.objects.create(dataset=self.dataset)
        self.assertEqual(job.status, "QUEUED")
        self.assertEqual(job.progress, 0.0)
        self.assertIsNone(job.task_id)
        self.assertIsNone(job.error_message)

    def test_mark_running(self):
        job = ProcessingJob.objects.create(dataset=self.dataset)
        job.mark_running(task_id="celery-123")
        job.refresh_from_db()
        self.assertEqual(job.status, "RUNNING")
        self.assertEqual(job.task_id, "celery-123")

    def test_mark_running_without_task_id(self):
        job = ProcessingJob.objects.create(dataset=self.dataset)
        job.mark_running()
        job.refresh_from_db()
        self.assertEqual(job.status, "RUNNING")

    def test_update_progress(self):
        job = ProcessingJob.objects.create(dataset=self.dataset)
        job.mark_running()
        job.update_progress(42.5)
        job.refresh_from_db()
        self.assertEqual(job.progress, 42.5)

    def test_update_progress_clamps_to_range(self):
        job = ProcessingJob.objects.create(dataset=self.dataset)
        job.mark_running()
        job.update_progress(150.0)
        self.assertEqual(job.progress, 100.0)
        job.update_progress(-5.0)
        self.assertEqual(job.progress, 0.0)

    def test_update_progress_fails_when_not_running(self):
        job = ProcessingJob.objects.create(dataset=self.dataset)
        with self.assertRaises(ValidationError):
            job.update_progress(50.0)

    def test_mark_success(self):
        job = ProcessingJob.objects.create(dataset=self.dataset)
        job.mark_running()
        job.mark_success(output_file_path="out.csv", preview_file_path="prev.json")
        job.refresh_from_db()
        self.assertEqual(job.status, "SUCCESS")
        self.assertEqual(job.progress, 100.0)
        self.assertEqual(job.output_file_path, "out.csv")
        self.assertEqual(job.preview_file_path, "prev.json")

    def test_mark_success_without_optional_paths(self):
        job = ProcessingJob.objects.create(dataset=self.dataset)
        job.mark_running()
        job.mark_success()
        job.refresh_from_db()
        self.assertEqual(job.status, "SUCCESS")
        self.assertEqual(job.progress, 100.0)
        self.assertIsNone(job.output_file_path)

    def test_mark_failed(self):
        job = ProcessingJob.objects.create(dataset=self.dataset)
        job.mark_running()
        job.mark_failed("LLM timeout")
        job.refresh_from_db()
        self.assertEqual(job.status, "FAILED")
        self.assertEqual(job.error_message, "LLM timeout")

    def test_cannot_transition_from_queued_to_success(self):
        job = ProcessingJob.objects.create(dataset=self.dataset)
        with self.assertRaises(ValidationError):
            job.mark_success()

    def test_cannot_transition_from_success_to_running(self):
        job = ProcessingJob.objects.create(dataset=self.dataset)
        job.mark_running()
        job.mark_success()
        with self.assertRaises(ValidationError):
            job.mark_running()

    def test_queued_can_transition_to_failed(self):
        job = ProcessingJob.objects.create(dataset=self.dataset)
        job.mark_failed("Queue error")
        job.refresh_from_db()
        self.assertEqual(job.status, "FAILED")

    def test_mark_cancelled_from_queued(self):
        job = ProcessingJob.objects.create(dataset=self.dataset)
        job.mark_cancelled()
        job.refresh_from_db()
        self.assertEqual(job.status, "CANCELLED")
        self.assertEqual(job.error_message, "Cancelled by user")

    def test_mark_cancelled_from_running(self):
        job = ProcessingJob.objects.create(dataset=self.dataset)
        job.mark_running()
        job.mark_cancelled()
        job.refresh_from_db()
        self.assertEqual(job.status, "CANCELLED")
        self.assertEqual(job.error_message, "Cancelled by user")

    def test_cancelled_is_terminal(self):
        job = ProcessingJob.objects.create(dataset=self.dataset)
        job.mark_cancelled()
        with self.assertRaises(ValidationError):
            job.mark_running()

    def test_cannot_transition_from_success_to_cancelled(self):
        job = ProcessingJob.objects.create(dataset=self.dataset)
        job.mark_running()
        job.mark_success()
        with self.assertRaises(ValidationError):
            job.mark_cancelled()