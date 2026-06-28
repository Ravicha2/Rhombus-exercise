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
        self.assertEqual(str(job), f"ProcessingJob {job.id} (QUEUED) - Progress: 0.0%")

    def test_update_processing_job_status(self):
        job = ProcessingJob.objects.create(dataset=self.dataset, status="RUNNING", progress=50.5, task_id="celery-123")
        self.assertEqual(job.status, "RUNNING")
        self.assertEqual(job.progress, 50.5)
        self.assertEqual(job.task_id, "celery-123")
        self.assertEqual(str(job), f"ProcessingJob {job.id} (RUNNING) - Progress: 50.5%")
