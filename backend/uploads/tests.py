from django.test import TestCase
from uploads.models import DatasetUpload


class DatasetUploadModelTest(TestCase):

    def test_create_dataset_upload(self):
        dataset = DatasetUpload.objects.create(file_path="uploads/test_file.csv")
        self.assertEqual(dataset.file_path, "uploads/test_file.csv")
        self.assertIsNotNone(dataset.uploaded_at)
        self.assertEqual(str(dataset), f"DatasetUpload {dataset.id}: uploads/test_file.csv")
