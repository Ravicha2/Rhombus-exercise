import os
import shutil
from unittest.mock import patch
from django.test import TestCase, Client
from django.core.files.uploadedfile import SimpleUploadedFile
from django.conf import settings
from uploads.models import DatasetUpload


class SyncUploadViewTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.storage_dir = os.path.join(settings.BASE_DIR, "uploads_storage")

    def tearDown(self):
        if os.path.exists(self.storage_dir):
            shutil.rmtree(self.storage_dir)

    def test_upload_csv_returns_201_with_column_names_and_preview(self):
        csv_content = b"ID,Name,Email\n1,Alice,alice@example.com\n2,Bob,bob@example.com\n"
        upload_file = SimpleUploadedFile("test.csv", csv_content, content_type="text/csv")
        response = self.client.post("/api/uploads/", {"file": upload_file})
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertIn("upload_id", data)
        self.assertIn("file_path", data)
        self.assertIn("uploaded_at", data)
        self.assertIn("column_names", data)
        self.assertIn("preview", data)
        self.assertEqual(data["column_names"], ["ID", "Name", "Email"])
        self.assertIsInstance(data["preview"], list)
        self.assertEqual(len(data["preview"]), 2)
        self.assertEqual(data["preview"][0]["ID"], 1)
        self.assertEqual(data["preview"][0]["Name"], "Alice")

    def test_upload_normalizes_synchronously_status_ready(self):
        csv_content = b"ID,Name\n1,Alice\n"
        upload_file = SimpleUploadedFile("sync.csv", csv_content, content_type="text/csv")
        response = self.client.post("/api/uploads/", {"file": upload_file})
        self.assertEqual(response.status_code, 201)
        data = response.json()
        dataset = DatasetUpload.objects.get(id=data["upload_id"])
        self.assertEqual(dataset.status, "READY")
        self.assertIsNotNone(dataset.parquet_file_path)
        self.assertIsNotNone(dataset.column_names)

    def test_upload_invalid_extension_returns_400(self):
        upload_file = SimpleUploadedFile(
            "app.exe", b"MZ\x90\x00", content_type="application/x-msdownload"
        )
        response = self.client.post("/api/uploads/", {"file": upload_file})
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())

    def test_upload_no_file_returns_400(self):
        response = self.client.post("/api/uploads/")
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())

    def test_upload_empty_file_returns_400(self):
        upload_file = SimpleUploadedFile("empty.csv", b"", content_type="text/csv")
        response = self.client.post("/api/uploads/", {"file": upload_file})
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())

    @patch("api.views.NormalizationService.normalize")
    def test_upload_normalization_failure_returns_500(self, mock_normalize):
        mock_normalize.side_effect = ValueError("corrupt file")
        csv_content = b"ID,Name\n1,Alice\n"
        upload_file = SimpleUploadedFile("bad.csv", csv_content, content_type="text/csv")
        response = self.client.post("/api/uploads/", {"file": upload_file})
        self.assertEqual(response.status_code, 500)
        data = response.json()
        self.assertIn("error", data)