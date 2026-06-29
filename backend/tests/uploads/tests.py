import os
import shutil
from unittest.mock import patch
from django.test import TestCase, Client
from django.core.files.uploadedfile import SimpleUploadedFile
from uploads.models import DatasetUpload
from django.conf import settings


class DatasetUploadViewTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.storage_dir = os.path.join(settings.BASE_DIR, 'uploads_storage')
        if not os.path.exists(self.storage_dir):
            os.makedirs(self.storage_dir)

    def tearDown(self):
        if os.path.exists(self.storage_dir):
            shutil.rmtree(self.storage_dir)

    def test_create_dataset_upload_model(self):
        dataset = DatasetUpload.objects.create(file_path="uploads_storage/test_file.csv")
        self.assertEqual(dataset.file_path, "uploads_storage/test_file.csv")
        self.assertIsNotNone(dataset.uploaded_at)
        self.assertEqual(str(dataset), f"DatasetUpload {dataset.id}: uploads_storage/test_file.csv")

    @patch("uploads.views.normalize_upload.delay")
    def test_upload_view_success_csv(self, mock_delay):
        csv_content = b"ID,Name,Email\n1,John Doe,john@example.com\n"
        upload_file = SimpleUploadedFile("test_upload.csv", csv_content, content_type="text/csv")
        response = self.client.post("/api/uploads/", {"file": upload_file})
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertIn("upload_id", data)
        self.assertIn("file_path", data)
        self.assertTrue(data["file_path"].startswith("uploads_storage/"))
        mock_delay.assert_called_once()

        # Verify file exists on disk
        full_path = os.path.join(settings.BASE_DIR, data["file_path"])
        self.assertTrue(os.path.exists(full_path))
        with open(full_path, "rb") as f:
            self.assertEqual(f.read(), csv_content)

    def test_upload_view_invalid_extension(self):
        exe_content = b"MZ\x90\x00\x03\x00\x00\x00"
        upload_file = SimpleUploadedFile("app.exe", exe_content, content_type="application/x-msdownload")
        response = self.client.post("/api/uploads/", {"file": upload_file})
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())
