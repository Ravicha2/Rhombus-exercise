import os
import tempfile
from unittest.mock import patch
import pandas as pd
from django.test import TestCase
from jobs.services import paginate_result


class PaginateResultTest(TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def _write_parquet(self, df, rel_path):
        abs_dir = os.path.join(self.tmpdir, os.path.dirname(rel_path))
        os.makedirs(abs_dir, exist_ok=True)
        abs_path = os.path.join(self.tmpdir, rel_path)
        df.to_parquet(abs_path, engine="pyarrow")
        return rel_path

    @patch("jobs.services.StorageService.get_storage_base_dir")
    def test_first_page(self, mock_base):
        mock_base.return_value = self.tmpdir
        df = pd.DataFrame({"email": [f"user_{i}@test.com" for i in range(120)]})
        rel_path = self._write_parquet(df, "output/1/result")
        result = paginate_result(rel_path, page=1, page_size=50)
        self.assertEqual(len(result["rows"]), 50)
        self.assertEqual(result["page"], 1)
        self.assertEqual(result["total_pages"], 3)
        self.assertEqual(result["total_rows"], 120)

    @patch("jobs.services.StorageService.get_storage_base_dir")
    def test_last_page_partial(self, mock_base):
        mock_base.return_value = self.tmpdir
        df = pd.DataFrame({"email": [f"user_{i}@test.com" for i in range(120)]})
        rel_path = self._write_parquet(df, "output/1/result")
        result = paginate_result(rel_path, page=3, page_size=50)
        self.assertEqual(len(result["rows"]), 20)
        self.assertEqual(result["page"], 3)

    @patch("jobs.services.StorageService.get_storage_base_dir")
    def test_page_clamp_beyond_range(self, mock_base):
        mock_base.return_value = self.tmpdir
        df = pd.DataFrame({"email": [f"user_{i}@test.com" for i in range(10)]})
        rel_path = self._write_parquet(df, "output/1/result")
        result = paginate_result(rel_path, page=99, page_size=50)
        self.assertEqual(result["page"], 1)
        self.assertEqual(len(result["rows"]), 10)

    @patch("jobs.services.StorageService.get_storage_base_dir")
    def test_empty_dataset(self, mock_base):
        mock_base.return_value = self.tmpdir
        df = pd.DataFrame({"email": pd.Series([], dtype=str)})
        rel_path = self._write_parquet(df, "output/1/result")
        result = paginate_result(rel_path, page=1, page_size=50)
        self.assertEqual(result["total_rows"], 0)
        self.assertEqual(result["total_pages"], 1)
        self.assertEqual(result["rows"], [])