from django.test import TestCase, Client
from unittest.mock import patch
from uploads.models import DatasetUpload
from jobs.models import ProcessingJob


class JobResultsViewTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.upload = DatasetUpload.objects.create(
            file_path="uploads_storage/test.parquet",
            status="READY",
            parquet_file_path="uploads_storage/test.parquet",
            column_names=["ID", "Name", "Email"],
        )

    def test_results_returns_404_for_nonexistent_job(self):
        response = self.client.get("/api/jobs/99999/results/")
        self.assertEqual(response.status_code, 404)
        data = response.json()
        self.assertIn("error", data)

    def test_results_returns_400_for_non_success_job(self):
        for status in ["QUEUED", "RUNNING", "FAILED", "CANCELLED"]:
            with self.subTest(status=status):
                job = ProcessingJob.objects.create(
                    dataset=self.upload,
                    nl_prompt="Clean emails",
                    status=status,
                )
                response = self.client.get(f"/api/jobs/{job.id}/results/")
                self.assertEqual(response.status_code, 400)
                data = response.json()
                self.assertIn("error", data)

    @patch("api.views.paginate_result")
    def test_results_returns_200_for_success_job(self, mock_paginate):
        mock_paginate.return_value = {
            "rows": [{"ID": 1, "Name": "Alice"}],
            "page": 1,
            "total_pages": 1,
            "total_rows": 1,
        }
        job = ProcessingJob.objects.create(
            dataset=self.upload,
            nl_prompt="Clean emails",
            status="SUCCESS",
            transformations=[{"column": "Name", "nl_pattern": "trim", "replacement": ""}],
            generated_regexes=[{"column": "Name", "regex": r"^\s+"}],
            output_file_path="outputs/result.parquet",
            preview_file_path="outputs/preview.parquet",
        )
        response = self.client.get(f"/api/jobs/{job.id}/results/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["id"], job.id)
        self.assertEqual(data["status"], "SUCCESS")
        self.assertEqual(data["column_names"], ["ID", "Name", "Email"])
        self.assertEqual(data["transformations"], [{"column": "Name", "nl_pattern": "trim", "replacement": ""}])
        self.assertEqual(data["generated_regexes"], [{"column": "Name", "regex": r"^\s+"}])
        self.assertEqual(data["rows"], [{"ID": 1, "Name": "Alice"}])
        self.assertEqual(data["page"], 1)
        self.assertEqual(data["total_pages"], 1)
        self.assertEqual(data["total_rows"], 1)
        mock_paginate.assert_called_once_with(job.output_file_path, 1, 50)

    @patch("api.views.paginate_result")
    def test_results_passes_page_and_page_size_params(self, mock_paginate):
        mock_paginate.return_value = {
            "rows": [],
            "page": 3,
            "total_pages": 5,
            "total_rows": 200,
        }
        job = ProcessingJob.objects.create(
            dataset=self.upload,
            nl_prompt="Clean emails",
            status="SUCCESS",
            output_file_path="outputs/result.parquet",
        )
        response = self.client.get(f"/api/jobs/{job.id}/results/?page=3&page_size=50")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["page"], 3)
        self.assertEqual(data["total_pages"], 5)
        self.assertEqual(data["total_rows"], 200)
        mock_paginate.assert_called_once_with(job.output_file_path, 3, 50)