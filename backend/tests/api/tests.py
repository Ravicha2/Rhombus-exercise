import os
import shutil
from django.test import TestCase, Client
from django.core.files.uploadedfile import SimpleUploadedFile
from uploads.models import DatasetUpload
from api.views import UploadView
from django.conf import settings


class ApiUploadViewTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.storage_dir = os.path.join(settings.BASE_DIR, "uploads_storage")
        if not os.path.exists(self.storage_dir):
            os.makedirs(self.storage_dir)

    def tearDown(self):
        if os.path.exists(self.storage_dir):
            shutil.rmtree(self.storage_dir)

    def test_upload_view_exists_in_api_app(self):
        self.assertTrue(callable(UploadView))

    def test_upload_csv_returns_201(self):
        csv_content = b"ID,Name,Email\n1,John Doe,john@example.com\n"
        upload_file = SimpleUploadedFile(
            "test_upload.csv", csv_content, content_type="text/csv"
        )
        response = self.client.post("/api/uploads/", {"file": upload_file})
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertIn("upload_id", data)
        self.assertIn("file_path", data)
        self.assertTrue(data["file_path"].startswith("uploads_storage/"))
        self.assertIn("column_names", data)
        self.assertIn("preview", data)

        full_path = os.path.join(settings.BASE_DIR, data["file_path"])
        self.assertTrue(os.path.exists(full_path))
        with open(full_path, "rb") as f:
            self.assertEqual(f.read(), csv_content)

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
        data = response.json()
        self.assertIn("error", data)