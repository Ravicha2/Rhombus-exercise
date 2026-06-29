import os
import shutil
import tempfile
from unittest.mock import patch
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from uploads.models import DatasetUpload


class DatasetUploadStatusTest(TestCase):

    def test_default_status_is_uploading(self):
        dataset = DatasetUpload.objects.create(file_path="uploads_storage/test.csv")
        self.assertEqual(dataset.status, "UPLOADING")

    def test_mark_converting(self):
        dataset = DatasetUpload.objects.create(file_path="uploads_storage/test.csv")
        dataset.mark_converting()
        dataset.refresh_from_db()
        self.assertEqual(dataset.status, "CONVERTING")

    def test_mark_ready(self):
        dataset = DatasetUpload.objects.create(file_path="uploads_storage/test.csv")
        dataset.mark_converting()
        dataset.mark_ready(parquet_file_path="uploads_storage/test.parquet", column_names=["a", "b"])
        dataset.refresh_from_db()
        self.assertEqual(dataset.status, "READY")
        self.assertEqual(dataset.parquet_file_path, "uploads_storage/test.parquet")
        self.assertEqual(dataset.column_names, ["a", "b"])

    def test_mark_failed(self):
        dataset = DatasetUpload.objects.create(file_path="uploads_storage/test.csv")
        dataset.mark_failed("corrupt file")
        dataset.refresh_from_db()
        self.assertEqual(dataset.status, "FAILED")
        self.assertEqual(dataset.error_message, "corrupt file")

    def test_cannot_transition_from_ready_to_converting(self):
        dataset = DatasetUpload.objects.create(file_path="uploads_storage/test.csv")
        dataset.mark_converting()
        dataset.mark_ready(parquet_file_path="p", column_names=[])
        with self.assertRaises(ValidationError):
            dataset.mark_converting()

    def test_cannot_transition_from_failed_to_ready(self):
        dataset = DatasetUpload.objects.create(file_path="uploads_storage/test.csv")
        dataset.mark_failed("error")
        with self.assertRaises(ValidationError):
            dataset.mark_ready(parquet_file_path="p", column_names=[])

    def test_uploading_can_transition_to_failed(self):
        dataset = DatasetUpload.objects.create(file_path="uploads_storage/test.csv")
        dataset.mark_failed("immediate failure")
        dataset.refresh_from_db()
        self.assertEqual(dataset.status, "FAILED")


class NormalizationServiceTest(TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp_dir)

    def _write_csv(self, filename="test.csv", content="ID,Name\n1,Alice\n2,Bob\n"):
        path = os.path.join(self.tmp_dir, filename)
        with open(path, "w") as f:
            f.write(content)
        return path

    def _write_xlsx(self, filename="test.xlsx"):
        import pandas as pd
        df = pd.DataFrame({"ID": [1, 2], "Name": ["Alice", "Bob"]})
        path = os.path.join(self.tmp_dir, filename)
        df.to_excel(path, index=False, engine="openpyxl")
        return path

    @patch("uploads.services.StorageService.resolve_absolute_path")
    def test_normalize_csv(self, mock_resolve):
        csv_path = self._write_csv()
        mock_resolve.return_value = csv_path
        from uploads.services import NormalizationService
        dataset = DatasetUpload.objects.create(file_path="uploads_storage/test.csv")

        parquet_rel_path, columns = NormalizationService.normalize(dataset)

        # Parquet is written at the absolute path; check it exists there
        expected_abs_path = os.path.splitext(csv_path)[0] + ".parquet"
        self.assertTrue(os.path.exists(expected_abs_path))
        self.assertTrue(parquet_rel_path.endswith(".parquet"))
        self.assertEqual(columns, ["ID", "Name"])

    @patch("uploads.services.StorageService.resolve_absolute_path")
    def test_normalize_xlsx(self, mock_resolve):
        xlsx_path = self._write_xlsx()
        mock_resolve.return_value = xlsx_path
        from uploads.services import NormalizationService
        dataset = DatasetUpload.objects.create(file_path="uploads_storage/test.xlsx")

        parquet_rel_path, columns = NormalizationService.normalize(dataset)

        expected_abs_path = os.path.splitext(xlsx_path)[0] + ".parquet"
        self.assertTrue(os.path.exists(expected_abs_path))
        self.assertEqual(columns, ["ID", "Name"])

    @patch("uploads.services.StorageService.resolve_absolute_path")
    def test_normalize_empty_file_raises(self, mock_resolve):
        csv_path = self._write_csv(content="ID,Name\n")
        mock_resolve.return_value = csv_path
        from uploads.services import NormalizationService
        dataset = DatasetUpload.objects.create(file_path="uploads_storage/empty.csv")

        with self.assertRaises(ValueError):
            NormalizationService.normalize(dataset)

    def test_normalize_missing_file_raises(self):
        from uploads.services import NormalizationService
        dataset = DatasetUpload.objects.create(file_path="uploads_storage/nonexistent.csv")

        with self.assertRaises(FileNotFoundError):
            NormalizationService.normalize(dataset)


class NormalizeUploadTaskTest(TestCase):

    @patch("uploads.tasks.NormalizationService")
    def test_task_success_lifecycle(self, mock_service):
        mock_service.normalize.return_value = ("uploads_storage/test.parquet", ["ID", "Name"])
        dataset = DatasetUpload.objects.create(file_path="uploads_storage/test.csv")

        from uploads.tasks import normalize_upload
        normalize_upload(dataset.id)

        dataset.refresh_from_db()
        self.assertEqual(dataset.status, "READY")
        self.assertEqual(dataset.parquet_file_path, "uploads_storage/test.parquet")
        self.assertEqual(dataset.column_names, ["ID", "Name"])

    @patch("uploads.tasks.NormalizationService")
    def test_task_failure_lifecycle(self, mock_service):
        mock_service.normalize.side_effect = ValueError("corrupt file")
        dataset = DatasetUpload.objects.create(file_path="uploads_storage/test.csv")

        from uploads.tasks import normalize_upload
        with self.assertRaises(ValueError):
            normalize_upload(dataset.id)

        dataset.refresh_from_db()
        self.assertEqual(dataset.status, "FAILED")
        self.assertIn("corrupt file", dataset.error_message)