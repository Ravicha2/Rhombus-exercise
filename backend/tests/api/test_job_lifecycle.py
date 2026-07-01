"""E2e tests for ProcessingJob lifecycle: start, status, results, cancel.

These tests exercise all four job endpoints in sequence to validate
cross-endpoint behaviors that unit tests can't catch.
"""
import json
from unittest.mock import MagicMock, patch
from django.test import TestCase, Client
from uploads.models import DatasetUpload
from jobs.models import ProcessingJob


class HappyPathTest(TestCase):
    """Start a job, poll status, retrieve results: full lifecycle."""

    def setUp(self):
        self.client = Client()
        self.upload = DatasetUpload.objects.create(
            file_path="uploads_storage/test.parquet",
            status="READY",
            parquet_file_path="uploads_storage/test.parquet",
            column_names=["ID", "Name", "Email"],
        )

    @patch("api.views.process_job.delay")
    def test_start_then_status_then_results(self, mock_delay):
        mock_delay.return_value.id = "task-happy-1"

        # 1. Start
        resp = self.client.post(
            "/api/jobs/start/",
            data=json.dumps({"upload_id": self.upload.id, "nl_prompt": "Clean emails"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        job_id = resp.json()["id"]
        self.assertEqual(resp.json()["status"], "QUEUED")

        # Verify task_id stored
        job = ProcessingJob.objects.get(id=job_id)
        self.assertEqual(job.task_id, "task-happy-1")

        # 2. Poll status (QUEUED)
        resp = self.client.get(f"/api/jobs/{job_id}/status/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "QUEUED")

        # Simulate task progress
        job.mark_running()
        job.update_progress(50.0)

        # 3. Poll status (RUNNING with progress)
        resp = self.client.get(f"/api/jobs/{job_id}/status/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "RUNNING")
        self.assertEqual(data["progress"], 50.0)

        # Results endpoint rejects non-SUCCESS
        resp = self.client.get(f"/api/jobs/{job_id}/results/")
        self.assertEqual(resp.status_code, 400)

        # Complete the job
        job.mark_success(
            output_file_path="output/1/result",
            preview_file_path="output/1/preview.parquet",
        )
        job.refresh_from_db()
        job.transformations = [{"column": "Email", "nl_pattern": "email pattern", "type": "literal", "value": "REDACTED"}]
        job.generated_regexes = [{"column": "Email", "regex": r"\S+@\S+\.\S+"}]
        job.save()

        # 4. Poll status (SUCCESS)
        resp = self.client.get(f"/api/jobs/{job_id}/status/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "SUCCESS")

    @patch("api.views.paginate_result")
    @patch("api.views.process_job.delay")
    def test_results_returns_all_fields_for_success_job(self, mock_delay, mock_paginate):
        mock_delay.return_value.id = "task-happy-2"
        mock_paginate.return_value = {
            "rows": [{"ID": 1, "Name": "Alice"}],
            "page": 1,
            "total_pages": 1,
            "total_rows": 1,
        }

        # Start and complete a job
        resp = self.client.post(
            "/api/jobs/start/",
            data=json.dumps({"upload_id": self.upload.id, "nl_prompt": "Clean emails"}),
            content_type="application/json",
        )
        job_id = resp.json()["id"]
        job = ProcessingJob.objects.get(id=job_id)
        job.status = "SUCCESS"
        job.progress = 100.0
        job.transformations = [{"column": "Email", "nl_pattern": "email pattern", "type": "literal", "value": "REDACTED"}]
        job.generated_regexes = [{"column": "Email", "regex": r"\S+@\S+\.\S+"}]
        job.output_file_path = "output/2/result"
        job.save()

        # Fetch results
        resp = self.client.get(f"/api/jobs/{job_id}/results/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["id"], job_id)
        self.assertEqual(data["status"], "SUCCESS")
        self.assertEqual(data["column_names"], ["ID", "Name", "Email"])
        self.assertEqual(data["transformations"], [{"column": "Email", "nl_pattern": "email pattern", "type": "literal", "value": "REDACTED"}])
        self.assertEqual(data["generated_regexes"], [{"column": "Email", "regex": r"\S+@\S+\.\S+"}])
        self.assertEqual(data["rows"], [{"ID": 1, "Name": "Alice"}])
        self.assertEqual(data["page"], 1)
        self.assertEqual(data["total_rows"], 1)


class CancelPathTest(TestCase):
    """Start a job, cancel it, confirm CANCELLED status, confirm results rejected."""

    def setUp(self):
        self.client = Client()
        self.upload = DatasetUpload.objects.create(
            file_path="uploads_storage/test.parquet",
            status="READY",
            parquet_file_path="uploads_storage/test.parquet",
            column_names=["ID", "Name"],
        )

    @patch("api.views.process_job.delay")
    def test_start_queued_then_cancel(self, mock_delay):
        mock_delay.return_value.id = "task-cancel-queued"

        # 1. Start
        resp = self.client.post(
            "/api/jobs/start/",
            data=json.dumps({"upload_id": self.upload.id, "nl_prompt": "Clean names"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        job_id = resp.json()["id"]

        # 2. Status is QUEUED
        resp = self.client.get(f"/api/jobs/{job_id}/status/")
        self.assertEqual(resp.json()["status"], "QUEUED")

        # 3. Cancel
        with patch("api.views.current_app") as mock_app:
            mock_app.control.revoke = lambda *a, **kw: None
            resp = self.client.post(f"/api/jobs/{job_id}/cancel/")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json()["status"], "CANCELLED")
            self.assertEqual(resp.json()["error_message"], "Cancelled by user")

        # 4. Status confirms CANCELLED
        resp = self.client.get(f"/api/jobs/{job_id}/status/")
        self.assertEqual(resp.json()["status"], "CANCELLED")
        self.assertEqual(resp.json()["error_message"], "Cancelled by user")

        # 5. Results rejected
        resp = self.client.get(f"/api/jobs/{job_id}/results/")
        self.assertEqual(resp.status_code, 400)

    @patch("api.views.process_job.delay")
    def test_start_running_then_cancel(self, mock_delay):
        mock_delay.return_value.id = "task-cancel-running"

        # 1. Start
        resp = self.client.post(
            "/api/jobs/start/",
            data=json.dumps({"upload_id": self.upload.id, "nl_prompt": "Clean names"}),
            content_type="application/json",
        )
        job_id = resp.json()["id"]

        # Simulate RUNNING
        job = ProcessingJob.objects.get(id=job_id)
        job.mark_running()

        # 2. Cancel while RUNNING
        with patch("api.views.current_app") as mock_app:
            mock_app.control.revoke = lambda *a, **kw: None
            resp = self.client.post(f"/api/jobs/{job_id}/cancel/")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json()["status"], "CANCELLED")

        # 3. Results rejected for CANCELLED
        resp = self.client.get(f"/api/jobs/{job_id}/results/")
        self.assertEqual(resp.status_code, 400)

    @patch("api.views.current_app")
    @patch("api.views.process_job.delay")
    def test_cancel_revokes_task_with_correct_id(self, mock_delay, mock_app):
        mock_delay.return_value.id = "task-revoke-check"
        mock_app.control.revoke = MagicMock()

        # Start stores task_id from delay result
        resp = self.client.post(
            "/api/jobs/start/",
            data=json.dumps({"upload_id": self.upload.id, "nl_prompt": "Clean names"}),
            content_type="application/json",
        )
        job_id = resp.json()["id"]

        # Cancel should revoke with the stored task_id
        resp = self.client.post(f"/api/jobs/{job_id}/cancel/")
        self.assertEqual(resp.status_code, 200)
        mock_app.control.revoke.assert_called_once_with("task-revoke-check", terminate=True)


class ErrorPathTest(TestCase):
    """Start with invalid inputs, verify correct error responses."""

    def setUp(self):
        self.client = Client()

    def test_start_with_nonexistent_upload(self):
        resp = self.client.post(
            "/api/jobs/start/",
            data=json.dumps({"upload_id": 99999, "nl_prompt": "Clean emails"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 404)
        self.assertIn("error", resp.json())

    def test_start_with_non_ready_upload(self):
        upload = DatasetUpload.objects.create(
            file_path="uploads_storage/uploading.parquet",
            status="UPLOADING",
        )
        resp = self.client.post(
            "/api/jobs/start/",
            data=json.dumps({"upload_id": upload.id, "nl_prompt": "Clean emails"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("error", resp.json())
        self.assertIn("UPLOADING", resp.json()["error"])

    def test_start_with_empty_prompt(self):
        upload = DatasetUpload.objects.create(
            file_path="uploads_storage/ready.parquet",
            status="READY",
            parquet_file_path="uploads_storage/ready.parquet",
            column_names=["ID"],
        )
        resp = self.client.post(
            "/api/jobs/start/",
            data=json.dumps({"upload_id": upload.id, "nl_prompt": ""}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_start_with_missing_prompt(self):
        upload = DatasetUpload.objects.create(
            file_path="uploads_storage/ready.parquet",
            status="READY",
            parquet_file_path="uploads_storage/ready.parquet",
            column_names=["ID"],
        )
        resp = self.client.post(
            "/api/jobs/start/",
            data=json.dumps({"upload_id": upload.id}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_start_with_missing_upload_id(self):
        resp = self.client.post(
            "/api/jobs/start/",
            data=json.dumps({"nl_prompt": "Clean emails"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_status_for_nonexistent_job(self):
        resp = self.client.get("/api/jobs/99999/status/")
        self.assertEqual(resp.status_code, 404)

    def test_results_for_nonexistent_job(self):
        resp = self.client.get("/api/jobs/99999/results/")
        self.assertEqual(resp.status_code, 404)

    def test_cancel_nonexistent_job(self):
        resp = self.client.post("/api/jobs/99999/cancel/")
        self.assertEqual(resp.status_code, 404)


class CancelTerminalJobTest(TestCase):
    """Cancel of already-terminal job returns appropriate error."""

    def setUp(self):
        self.client = Client()
        self.upload = DatasetUpload.objects.create(
            file_path="uploads_storage/test.parquet",
            status="READY",
            parquet_file_path="uploads_storage/test.parquet",
            column_names=["ID"],
        )

    def test_cancel_succeeded_job(self):
        job = ProcessingJob.objects.create(
            dataset=self.upload, nl_prompt="Clean", status="SUCCESS", progress=100.0
        )
        resp = self.client.post(f"/api/jobs/{job.id}/cancel/")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("error", resp.json())

    def test_cancel_failed_job(self):
        job = ProcessingJob.objects.create(
            dataset=self.upload, nl_prompt="Clean", status="FAILED", error_message="boom"
        )
        resp = self.client.post(f"/api/jobs/{job.id}/cancel/")
        self.assertEqual(resp.status_code, 400)

    def test_cancel_already_cancelled_job(self):
        job = ProcessingJob.objects.create(
            dataset=self.upload, nl_prompt="Clean", status="CANCELLED",
            error_message="Cancelled by user",
        )
        resp = self.client.post(f"/api/jobs/{job.id}/cancel/")
        self.assertEqual(resp.status_code, 400)

    def test_results_rejects_all_non_success_statuses(self):
        for status in ["QUEUED", "RUNNING", "FAILED", "CANCELLED"]:
            with self.subTest(status=status):
                job = ProcessingJob.objects.create(
                    dataset=self.upload, nl_prompt="Clean", status=status
                )
                resp = self.client.get(f"/api/jobs/{job.id}/results/")
                self.assertEqual(resp.status_code, 400)


class CrossEndpointBehaviorTest(TestCase):
    """Start stores task_id, cancel prevents results, status reflects progress."""

    def setUp(self):
        self.client = Client()
        self.upload = DatasetUpload.objects.create(
            file_path="uploads_storage/test.parquet",
            status="READY",
            parquet_file_path="uploads_storage/test.parquet",
            column_names=["ID", "Name"],
        )

    @patch("api.views.process_job.delay")
    def test_start_stores_task_id_from_delay_result(self, mock_delay):
        mock_delay.return_value.id = "stored-task-id-xyz"

        resp = self.client.post(
            "/api/jobs/start/",
            data=json.dumps({"upload_id": self.upload.id, "nl_prompt": "Clean"}),
            content_type="application/json",
        )
        job_id = resp.json()["id"]
        job = ProcessingJob.objects.get(id=job_id)
        self.assertEqual(job.task_id, "stored-task-id-xyz")

    def test_status_excludes_heavy_fields_across_all_statuses(self):
        """Status endpoint never leaks transformations, regexes, or file paths."""
        for status in ["QUEUED", "RUNNING", "FAILED", "CANCELLED"]:
            with self.subTest(status=status):
                job = ProcessingJob.objects.create(
                    dataset=self.upload,
                    nl_prompt="Clean",
                    status=status,
                    transformations=[{"column": "Name", "nl_pattern": "x", "type": "literal", "value": "y"}],
                    generated_regexes=[{"column": "Name", "regex": ".*"}],
                    output_file_path="/data/out.parquet",
                    preview_file_path="/data/prev.parquet",
                )
                resp = self.client.get(f"/api/jobs/{job.id}/status/")
                data = resp.json()
                self.assertNotIn("transformations", data)
                self.assertNotIn("generated_regexes", data)
                self.assertNotIn("output_file_path", data)
                self.assertNotIn("preview_file_path", data)

    def test_failed_job_status_includes_error_message(self):
        job = ProcessingJob.objects.create(
            dataset=self.upload,
            nl_prompt="Clean",
            status="FAILED",
            error_message="LLM timeout",
        )
        resp = self.client.get(f"/api/jobs/{job.id}/status/")
        self.assertEqual(resp.json()["error_message"], "LLM timeout")