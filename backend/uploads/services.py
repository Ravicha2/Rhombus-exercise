import os
import pandas as pd
from uploads.models import DatasetUpload
from jobs.services import StorageService


class NormalizationService:
    SUPPORTED_EXTENSIONS = {".csv", ".xlsx", ".xls"}

    @classmethod
    def normalize(cls, dataset: DatasetUpload) -> tuple[str, list[str]]:
        """Validate, convert to Parquet, return (parquet_rel_path, column_names)."""
        abs_path = StorageService.resolve_absolute_path(dataset)
        if not os.path.exists(abs_path):
            raise FileNotFoundError(f"File not found: {abs_path}")

        ext = os.path.splitext(dataset.file_path)[1].lower()
        if ext == ".csv":
            df = pd.read_csv(abs_path)
        elif ext in (".xlsx", ".xls"):
            df = pd.read_excel(abs_path, engine="openpyxl")
        else:
            raise ValueError(f"Unsupported file extension: {ext}")

        if df.empty:
            raise ValueError("File contains no data rows")

        column_names = list(df.columns)
        parquet_path = os.path.splitext(abs_path)[0] + ".parquet"
        df.to_parquet(parquet_path, engine="pyarrow")

        # ponytail: derive relative path by swapping extension, not reconstructing from parts
        parquet_rel_path = os.path.splitext(dataset.file_path)[0] + ".parquet"
        return parquet_rel_path, column_names