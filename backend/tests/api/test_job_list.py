from django.test import TestCase, Client
from uploads.models import DatasetUpload
from jobs.models import ProcessingJob


class JobListViewTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.upload = DatasetUpload.objects.create(
            file_path="uploads_storage/test.parquet",
            status="READY",
            parquet_file_path="uploads_storage/test.parquet",
            column_names=["ID", "Name"],
        )

    def test_returns_empty_list_when_no_jobs(self):
        response = self.client.get("/api/jobs/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_returns_jobs_ordered_by_created_at_desc(self):
        j1 = ProcessingJob.objects.create(dataset=self.upload, nl_prompt="First")
        j2 = ProcessingJob.objects.create(dataset=self.upload, nl_prompt="Second")
        response = self.client.get("/api/jobs/")
        data = response.json()
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]["id"], j2.id)
        self.assertEqual(data[1]["id"], j1.id)

    def test_includes_all_required_fields(self):
        job = ProcessingJob.objects.create(
            dataset=self.upload,
            nl_prompt="Clean emails",
            status="RUNNING",
            progress=42.5,
            error_message=None,
        )
        response = self.client.get("/api/jobs/")
        data = response.json()
        self.assertEqual(len(data), 1)
        obj = data[0]
        self.assertEqual(obj["id"], job.id)
        self.assertEqual(obj["status"], "RUNNING")
        self.assertEqual(obj["progress"], 42.5)
        self.assertEqual(obj["nl_prompt"], "Clean emails")
        self.assertEqual(obj["error_message"], None)
        self.assertIn("created_at", obj)
        self.assertIn("updated_at", obj)
        self.assertEqual(obj["file_path"], self.upload.file_path)

    def test_failed_job_includes_error_message(self):
        ProcessingJob.objects.create(
            dataset=self.upload,
            nl_prompt="Bad job",
            status="FAILED",
            error_message="LLM timeout",
        )
        response = self.client.get("/api/jobs/")
        data = response.json()
        self.assertEqual(data[0]["error_message"], "LLM timeout")