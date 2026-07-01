from django.test import TestCase, Client
from unittest.mock import patch, MagicMock
from uploads.models import DatasetUpload
from jobs.models import ProcessingJob


class JobCancelViewTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.upload = DatasetUpload.objects.create(
            file_path="uploads_storage/test.parquet",
            status="READY",
            parquet_file_path="uploads_storage/test.parquet",
            column_names=["ID", "Name"],
        )

    @patch("api.views.current_app")
    def test_cancel_queued_job_returns_200(self, mock_app):
        mock_app.control.revoke = MagicMock()
        job = ProcessingJob.objects.create(
            dataset=self.upload,
            nl_prompt="Clean emails",
            status="QUEUED",
            task_id="task-queued-123",
        )
        response = self.client.post(f"/api/jobs/{job.id}/cancel/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "CANCELLED")
        self.assertEqual(data["error_message"], "Cancelled by user")
        self.assertEqual(data["id"], job.id)
        self.assertIn("created_at", data)
        self.assertIn("updated_at", data)
        job.refresh_from_db()
        self.assertEqual(job.status, "CANCELLED")
        mock_app.control.revoke.assert_called_once_with("task-queued-123", terminate=True)

    @patch("api.views.current_app")
    def test_cancel_running_job_returns_200(self, mock_app):
        mock_app.control.revoke = MagicMock()
        job = ProcessingJob.objects.create(
            dataset=self.upload,
            nl_prompt="Clean emails",
            status="RUNNING",
            task_id="task-running-456",
        )
        response = self.client.post(f"/api/jobs/{job.id}/cancel/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "CANCELLED")
        mock_app.control.revoke.assert_called_once_with("task-running-456", terminate=True)

    def test_cancel_nonexistent_job_returns_404(self):
        response = self.client.post("/api/jobs/99999/cancel/")
        self.assertEqual(response.status_code, 404)
        data = response.json()
        self.assertIn("error", data)

    def test_cancel_succeeded_job_returns_error(self):
        job = ProcessingJob.objects.create(
            dataset=self.upload,
            nl_prompt="Clean emails",
            status="SUCCESS",
            progress=100.0,
        )
        response = self.client.post(f"/api/jobs/{job.id}/cancel/")
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertIn("error", data)

    def test_cancel_failed_job_returns_error(self):
        job = ProcessingJob.objects.create(
            dataset=self.upload,
            nl_prompt="Clean emails",
            status="FAILED",
            error_message="LLM timeout",
        )
        response = self.client.post(f"/api/jobs/{job.id}/cancel/")
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertIn("error", data)

    def test_cancel_already_cancelled_job_returns_error(self):
        job = ProcessingJob.objects.create(
            dataset=self.upload,
            nl_prompt="Clean emails",
            status="CANCELLED",
            error_message="Cancelled by user",
        )
        response = self.client.post(f"/api/jobs/{job.id}/cancel/")
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertIn("error", data)

    @patch("api.views.current_app")
    def test_cancel_sets_status_before_revoke(self, mock_app):
        """Status is CANCELLED in DB before revoke is called."""
        job = ProcessingJob.objects.create(
            dataset=self.upload,
            nl_prompt="Clean emails",
            status="RUNNING",
            task_id="task-order-789",
        )

        def check_db_state(task_id, **kwargs):
            job.refresh_from_db()
            self.assertEqual(job.status, "CANCELLED")

        mock_app.control.revoke = MagicMock(side_effect=check_db_state)
        response = self.client.post(f"/api/jobs/{job.id}/cancel/")
        self.assertEqual(response.status_code, 200)