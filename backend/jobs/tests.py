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
        self.assertIsNone(job.output_file_path)
        self.assertIsNone(job.preview_file_path)
        self.assertEqual(str(job), f"ProcessingJob {job.id} (QUEUED) - Progress: 0.0%")

    def test_update_processing_job_fields(self):
        job = ProcessingJob.objects.create(
            dataset=self.dataset,
            status="SUCCESS",
            progress=100.0,
            task_id="celery-123",
            output_file_path="uploads_storage/processed_1.csv",
            preview_file_path="uploads_storage/preview_1.json"
        )
        self.assertEqual(job.status, "SUCCESS")
        self.assertEqual(job.progress, 100.0)
        self.assertEqual(job.task_id, "celery-123")
        self.assertEqual(job.output_file_path, "uploads_storage/processed_1.csv")
        self.assertEqual(job.preview_file_path, "uploads_storage/preview_1.json")
        self.assertEqual(str(job), f"ProcessingJob {job.id} (SUCCESS) - Progress: 100.0%")
