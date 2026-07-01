from django.test import TestCase, Client
from uploads.models import DatasetUpload


class UploadListViewTest(TestCase):

    def setUp(self):
        self.client = Client()

    def test_list_uploads_returns_empty_list(self):
        response = self.client.get("/api/uploads/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 0)

    def test_list_uploads_returns_all_uploads(self):
        DatasetUpload.objects.create(
            file_path="uploads_storage/a.csv",
            status="READY",
            parquet_file_path="uploads_storage/a.parquet",
            column_names=["ID", "Name"],
        )
        DatasetUpload.objects.create(
            file_path="uploads_storage/b.csv",
            status="UPLOADING",
        )
        response = self.client.get("/api/uploads/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 2)

    def test_list_uploads_response_shape(self):
        DatasetUpload.objects.create(
            file_path="uploads_storage/a.csv",
            status="READY",
            parquet_file_path="uploads_storage/a.parquet",
            column_names=["ID", "Name"],
        )
        response = self.client.get("/api/uploads/")
        data = response.json()
        upload = data[0]
        self.assertIn("id", upload)
        self.assertIn("file_path", upload)
        self.assertIn("status", upload)
        self.assertIn("column_names", upload)
        self.assertIn("uploaded_at", upload)
        self.assertEqual(upload["status"], "READY")
        self.assertEqual(upload["column_names"], ["ID", "Name"])

    def test_list_uploads_orders_by_uploaded_at_desc(self):
        first = DatasetUpload.objects.create(file_path="uploads_storage/first.csv")
        second = DatasetUpload.objects.create(file_path="uploads_storage/second.csv")
        response = self.client.get("/api/uploads/")
        data = response.json()
        self.assertEqual(data[0]["id"], second.id)
        self.assertEqual(data[1]["id"], first.id)