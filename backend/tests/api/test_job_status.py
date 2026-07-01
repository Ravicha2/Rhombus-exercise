import json
from django.test import TestCase, Client
from uploads.models import DatasetUpload
from jobs.models import ProcessingJob


class JobStatusViewTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.upload = DatasetUpload.objects.create(
            file_path="uploads_storage/test.parquet",
            status="READY",
            parquet_file_path="uploads_storage/test.parquet",
            column_names=["ID", "Name"],
        )

    def test_status_returns_200_for_existing_job(self):
        job = ProcessingJob.objects.create(
            dataset=self.upload,
            nl_prompt="Clean emails",
            status="RUNNING",
            progress=42.5,
        )
        response = self.client.get(f"/api/jobs/{job.id}/status/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["id"], job.id)
        self.assertEqual(data["status"], "RUNNING")
        self.assertEqual(data["progress"], 42.5)
        self.assertIsNone(data["error_message"])
        self.assertIn("created_at", data)
        self.assertIn("updated_at", data)

    def test_status_returns_404_for_nonexistent_job(self):
        response = self.client.get("/api/jobs/99999/status/")
        self.assertEqual(response.status_code, 404)
        data = response.json()
        self.assertIn("error", data)

    def test_status_excludes_heavy_fields(self):
        job = ProcessingJob.objects.create(
            dataset=self.upload,
            nl_prompt="Clean emails",
            status="SUCCESS",
            progress=100.0,
            transformations=[{"column": "Name", "nl_pattern": "trim", "replacement": ""}],
            generated_regexes=[{"column": "Name", "regex": r"^\s+"}],
            output_file_path="/data/output.parquet",
            preview_file_path="/data/preview.parquet",
        )
        response = self.client.get(f"/api/jobs/{job.id}/status/")
        data = response.json()
        self.assertNotIn("transformations", data)
        self.assertNotIn("generated_regexes", data)
        self.assertNotIn("output_file_path", data)
        self.assertNotIn("preview_file_path", data)

    def test_status_for_failed_job_includes_error(self):
        job = ProcessingJob.objects.create(
            dataset=self.upload,
            nl_prompt="Clean emails",
            status="FAILED",
            error_message="LLM timeout",
        )
        response = self.client.get(f"/api/jobs/{job.id}/status/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["error_message"], "LLM timeout")