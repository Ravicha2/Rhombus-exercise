import json
from unittest.mock import patch
from django.test import TestCase, Client
from uploads.models import DatasetUpload
from jobs.models import ProcessingJob


class JobStartViewTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.ready_upload = DatasetUpload.objects.create(
            file_path="uploads_storage/test.parquet",
            status="READY",
            parquet_file_path="uploads_storage/test.parquet",
            column_names=["ID", "Name", "Email"],
        )
        self.uploading_upload = DatasetUpload.objects.create(
            file_path="uploads_storage/uploading.parquet",
            status="UPLOADING",
        )

    @patch("api.views.process_job.delay")
    def test_start_job_returns_201(self, mock_delay):
        mock_delay.return_value.id = "fake-task-id-123"
        response = self.client.post(
            "/api/jobs/start/",
            data=json.dumps({"upload_id": self.ready_upload.id, "nl_prompt": "Clean up emails"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertIn("id", data)
        self.assertEqual(data["status"], "QUEUED")

        job = ProcessingJob.objects.get(id=data["id"])
        self.assertEqual(job.dataset_id, self.ready_upload.id)
        self.assertEqual(job.nl_prompt, "Clean up emails")
        self.assertEqual(job.task_id, "fake-task-id-123")
        mock_delay.assert_called_once_with(job.id)

    def test_start_job_nonexistent_upload_returns_404(self):
        response = self.client.post(
            "/api/jobs/start/",
            data=json.dumps({"upload_id": 99999, "nl_prompt": "Clean up emails"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)
        data = response.json()
        self.assertIn("error", data)

    def test_start_job_upload_not_ready_returns_400(self):
        response = self.client.post(
            "/api/jobs/start/",
            data=json.dumps({"upload_id": self.uploading_upload.id, "nl_prompt": "Clean up emails"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertIn("error", data)

    def test_start_job_empty_nl_prompt_returns_400(self):
        response = self.client.post(
            "/api/jobs/start/",
            data=json.dumps({"upload_id": self.ready_upload.id, "nl_prompt": ""}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertIn("error", data)

    def test_start_job_missing_nl_prompt_returns_400(self):
        response = self.client.post(
            "/api/jobs/start/",
            data=json.dumps({"upload_id": self.ready_upload.id}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertIn("error", data)

    def test_start_job_missing_upload_id_returns_400(self):
        response = self.client.post(
            "/api/jobs/start/",
            data=json.dumps({"nl_prompt": "Clean up emails"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertIn("error", data)