import os
import shutil
from django.test import TestCase, Client
from django.core.files.uploadedfile import SimpleUploadedFile
from django.conf import settings
from uploads.models import DatasetUpload


class UploadDetailViewTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.storage_dir = os.path.join(settings.BASE_DIR, "uploads_storage")

    def tearDown(self):
        if os.path.exists(self.storage_dir):
            shutil.rmtree(self.storage_dir)

    def test_detail_returns_200_with_preview(self):
        csv_content = b"ID,Name\n1,Alice\n2,Bob\n"
        upload_file = SimpleUploadedFile("test.csv", csv_content, content_type="text/csv")
        post_resp = self.client.post("/api/uploads/", {"file": upload_file})
        self.assertEqual(post_resp.status_code, 201)
        upload_id = post_resp.json()["upload_id"]

        response = self.client.get(f"/api/uploads/{upload_id}/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("id", data)
        self.assertIn("file_path", data)
        self.assertIn("status", data)
        self.assertIn("column_names", data)
        self.assertIn("preview", data)
        self.assertEqual(data["status"], "READY")
        self.assertEqual(len(data["preview"]), 2)
        self.assertEqual(data["preview"][0]["Name"], "Alice")

    def test_detail_returns_404_for_nonexistent_upload(self):
        response = self.client.get("/api/uploads/999/")
        self.assertEqual(response.status_code, 404)
        self.assertIn("error", response.json())
