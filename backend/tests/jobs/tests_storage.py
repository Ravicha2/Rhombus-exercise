import os
from django.test import TestCase, override_settings
from django.conf import settings
from uploads.models import DatasetUpload
from jobs.services import StorageService


class StorageServiceTest(TestCase):

    def test_resolve_absolute_path(self):
        dataset = DatasetUpload.objects.create(file_path="uploads_storage/test_file.csv")
        resolved = StorageService.resolve_absolute_path(dataset)
        expected = os.path.join(str(settings.BASE_DIR), "uploads_storage", "test_file.csv")
        self.assertEqual(resolved, expected)

    @override_settings(BASE_DIR="/mnt/shared")
    def test_resolve_under_docker_volume(self):
        dataset = DatasetUpload.objects.create(file_path="uploads_storage/data_abc123.csv")
        resolved = StorageService.resolve_absolute_path(dataset)
        self.assertEqual(resolved, "/mnt/shared/uploads_storage/data_abc123.csv")

    def test_resolve_strips_directory_traversal(self):
        dataset = DatasetUpload.objects.create(file_path="uploads_storage/../../etc/passwd")
        resolved = StorageService.resolve_absolute_path(dataset)
        self.assertNotIn("..", resolved)
        self.assertTrue(resolved.endswith("passwd"))

    def test_resolve_parquet_absolute_path(self):
        dataset = DatasetUpload.objects.create(
            file_path="uploads_storage/test_file.csv",
            parquet_file_path="uploads_storage/test_file.csv.parquet",
            status="READY",
        )
        resolved = StorageService.resolve_parquet_absolute_path(dataset)
        expected = os.path.join(str(settings.BASE_DIR), "uploads_storage", "test_file.csv.parquet")
        self.assertEqual(resolved, expected)