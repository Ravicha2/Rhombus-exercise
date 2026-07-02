import os
import tempfile
from unittest.mock import MagicMock
import pandas as pd
from django.test import TestCase
from jobs.spark import get_spark_session
from jobs.services import SparkProcessingService, StorageService


class SparkProcessingServiceTest(TestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.spark = get_spark_session()

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.job_id = 999

    def _write_parquet(self, df: pd.DataFrame, name: str = "input.parquet") -> str:
        path = os.path.join(self.tmpdir, name)
        df.to_parquet(path, engine="pyarrow")
        return path

    def _output_dir(self) -> str:
        return os.path.join(self.tmpdir, "uploads_storage", "output", str(self.job_id))

    def _make_specs(self, specs: list[tuple[str, str, str]]) -> list[dict]:
        return [{"column": c, "regex": r, "replacement": rep} for c, r, rep in specs]

    def test_single_column_transformation(self):
        df = pd.DataFrame({"email": ["alice@example.com", "bob@test.org"], "name": ["Alice", "Bob"]})
        parquet_path = self._write_parquet(df)
        specs = self._make_specs([("email", r"[\w.]+@", "[REDACTED]")])

        out_path, preview_path = SparkProcessingService.process(
            parquet_path, specs, self.job_id, storage_dir=self.tmpdir
        )

        result = pd.read_parquet(os.path.join(self.tmpdir, out_path))
        self.assertIn("[REDACTED]", result["email"].iloc[0])
        self.assertEqual(result["name"].iloc[0], "Alice")

    def test_multiple_columns_transformation(self):
        df = pd.DataFrame({
            "email": ["alice@example.com"],
            "phone": ["555-1234"],
        })
        parquet_path = self._write_parquet(df)
        specs = self._make_specs([
            ("email", r"[\w.]+@", "[EMAIL]"),
            ("phone", r"\d{3}-\d{4}", "[PHONE]"),
        ])

        out_path, _ = SparkProcessingService.process(
            parquet_path, specs, self.job_id, storage_dir=self.tmpdir
        )

        result = pd.read_parquet(os.path.join(self.tmpdir, out_path))
        self.assertEqual(result["email"].iloc[0], "[EMAIL]example.com")
        self.assertEqual(result["phone"].iloc[0], "[PHONE]")

    def test_no_regex_matches(self):
        df = pd.DataFrame({"name": ["Alice", "Bob"]})
        parquet_path = self._write_parquet(df)
        specs = self._make_specs([("name", r"\d+", "DIGIT")])

        out_path, _ = SparkProcessingService.process(
            parquet_path, specs, self.job_id, storage_dir=self.tmpdir
        )

        result = pd.read_parquet(os.path.join(self.tmpdir, out_path))
        self.assertEqual(result["name"].tolist(), ["Alice", "Bob"])

    def test_empty_dataset(self):
        df = pd.DataFrame({"name": pd.Series([], dtype=str)})
        parquet_path = self._write_parquet(df)
        specs = self._make_specs([("name", r"X", "Y")])

        out_path, preview_path = SparkProcessingService.process(
            parquet_path, specs, self.job_id, storage_dir=self.tmpdir
        )

        result = pd.read_parquet(os.path.join(self.tmpdir, out_path))
        self.assertEqual(len(result), 0)

    def test_preview_contains_100_rows(self):
        rows = {"name": [f"user_{i}" for i in range(200)]}
        df = pd.DataFrame(rows)
        parquet_path = self._write_parquet(df)
        specs = self._make_specs([("name", r"^user_", "person_")])

        _, preview_path = SparkProcessingService.process(
            parquet_path, specs, self.job_id, storage_dir=self.tmpdir
        )

        preview = pd.read_parquet(os.path.join(self.tmpdir, preview_path))
        self.assertEqual(len(preview), 100)

    def test_regex_no_double_replacement(self):
        """Capturing groups in regexp_replace must not cause duplicate replacements."""
        df = pd.DataFrame({"email": ["alice@example.com"]})
        parquet_path = self._write_parquet(df)
        # Full-email regex; if capturing groups are used, regexp_replace doubles the replacement
        specs = self._make_specs([("email", r"[\w.+-]+@[\w.-]+\.[\w]+", "[REDACTED]")])

        out_path, _ = SparkProcessingService.process(
            parquet_path, specs, self.job_id, storage_dir=self.tmpdir
        )

        result = pd.read_parquet(os.path.join(self.tmpdir, out_path))
        self.assertEqual(result["email"].iloc[0], "[REDACTED]")
        self.assertNotIn("[REDACTED][REDACTED]", result["email"].iloc[0])

    def test_progress_callback_called(self):
        df = pd.DataFrame({"email": ["a@b.com", "c@d.org"], "phone": ["555-0000", "555-1111"]})
        parquet_path = self._write_parquet(df)
        specs = self._make_specs([
            ("email", r"@", " [AT] "),
            ("phone", r"555", "XXX"),
        ])
        callback = MagicMock()

        SparkProcessingService.process(
            parquet_path, specs, self.job_id,
            progress_callback=callback, storage_dir=self.tmpdir,
        )

        self.assertGreaterEqual(callback.call_count, 2)
        first_pct = callback.call_args_list[0][0][0]
        self.assertGreater(first_pct, 0)
        last_pct = callback.call_args_list[-1][0][0]
        self.assertEqual(last_pct, 100)