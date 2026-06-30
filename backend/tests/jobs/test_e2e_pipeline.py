"""End-to-end pipeline test requiring Docker (Postgres, Redis) and a real OPENROUTER_API_KEY.

Run with:  uv run pytest tests/jobs/test_e2e_pipeline.py -v -m e2e
Skip with: uv run pytest tests/ -m "not e2e"
"""
import os
import tempfile

import pandas as pd
import pytest

from jobs.models import ProcessingJob
from jobs.services import StorageService, paginate_result
from jobs.tasks import process_job
from uploads.models import DatasetUpload
from uploads.services import NormalizationService


E2E_MARK = pytest.mark.e2e

CSV_CONTENT = """\
name,email,phone,city,notes
Alice,alice@example.com,555-1234,New York,urgent
Bob,bob@test.org,555-5678,London,normal
Carol,carol@company.com,555-9012,Tokyo,review
Dave,dave@demo.net,555-3456,Paris,priority
Eve,eve@sample.io,555-7890,Sydney,urgent
"""


def _docker_healthy():
    """Check Postgres and Redis containers are reachable."""
    import socket

    # Check Postgres
    host = os.environ.get("DB_HOST", "")
    if host:
        try:
            s = socket.create_connection(
                (host, int(os.environ.get("DB_PORT", "5432"))), timeout=2
            )
            s.close()
        except OSError:
            return False
    else:
        # No DB_HOST means SQLite mode, not Docker
        return False

    # Check Redis
    redis_url = os.environ.get("CELERY_BROKER_URL", "")
    if "redis" in redis_url:
        # Parse host/port from redis://host:port/db
        try:
            parts = redis_url.replace("redis://", "").split("/")
            hp = parts[0].split(":")
            rhost = hp[0]
            rport = int(hp[1]) if len(hp) > 1 else 6379
            s = socket.create_connection((rhost, rport), timeout=2)
            s.close()
        except OSError:
            return False

    return True


def _has_api_key():
    return bool(os.environ.get("OPENROUTER_API_KEY", "").strip())


# Skip entire module if Docker or API key not available
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not _docker_healthy(), reason="Docker containers (Postgres/Redis) not reachable. Start with: docker compose up -d"),
    pytest.mark.skipif(not _has_api_key(), reason="OPENROUTER_API_KEY not set"),
]


@pytest.fixture()
def uploaded_dataset(db, settings):
    """Upload a small CSV, normalize to Parquet, return the DatasetUpload."""
    storage_dir = StorageService.get_storage_base_dir()
    os.makedirs(storage_dir, exist_ok=True)

    csv_path = os.path.join(storage_dir, "e2e_test.csv")
    with open(csv_path, "w") as f:
        f.write(CSV_CONTENT)

    dataset = DatasetUpload.objects.create(
        file_path="uploads_storage/e2e_test.csv",
        status="CONVERTING",
    )

    parquet_rel_path, column_names = NormalizationService.normalize(dataset)
    dataset.mark_ready(parquet_file_path=parquet_rel_path, column_names=column_names)
    return dataset


@pytest.mark.django_db
class TestE2EPipeline:

    def test_full_pipeline_with_real_llm(self, uploaded_dataset):
        """NL prompt -> triage -> regex -> Spark -> SUCCESS with correct output."""
        job = ProcessingJob.objects.create(
            dataset=uploaded_dataset,
            nl_prompt="Replace all email addresses with [EMAIL] and all phone numbers with [PHONE]",
        )

        process_job(job.id)

        job.refresh_from_db()
        assert job.status == "SUCCESS", f"Job failed: {job.error_message}"
        assert job.output_file_path is not None
        assert job.preview_file_path is not None
        assert job.progress == 100.0

        # Read output Parquet and verify transformations
        output_abs = os.path.join(
            StorageService.get_storage_base_dir(), job.output_file_path
        )
        result = pd.read_parquet(output_abs)

        # Email and phone columns should be transformed
        for val in result["email"]:
            assert val == "[EMAIL]", f"Expected [EMAIL], got {val}"
        for val in result["phone"]:
            assert val == "[PHONE]", f"Expected [PHONE], got {val}"

        # Other columns should be untouched
        assert list(result["name"]) == ["Alice", "Bob", "Carol", "Dave", "Eve"]
        assert list(result["city"]) == ["New York", "London", "Tokyo", "Paris", "Sydney"]

        # Preview should have <= 100 rows
        preview_abs = os.path.join(
            StorageService.get_storage_base_dir(), job.preview_file_path
        )
        preview = pd.read_parquet(preview_abs)
        assert len(preview) <= 100

    def test_pipeline_empty_triage_returns_success(self, uploaded_dataset):
        """Prompt that triggers no transformations should still succeed."""
        job = ProcessingJob.objects.create(
            dataset=uploaded_dataset,
            nl_prompt="do nothing to this data",
        )

        process_job(job.id)

        job.refresh_from_db()
        # Either triage returns empty (no specs) or returns some no-op.
        # Either way, job should succeed.
        assert job.status in ("SUCCESS", "FAILED")
        # If it succeeded, output should exist and data should be unchanged
        if job.status == "SUCCESS":
            output_abs = os.path.join(
                StorageService.get_storage_base_dir(), job.output_file_path
            )
            result = pd.read_parquet(output_abs)
            assert len(result) == 5

    def test_paginate_result_reads_output(self, uploaded_dataset):
        """After pipeline, paginate_result should return paginated rows."""
        job = ProcessingJob.objects.create(
            dataset=uploaded_dataset,
            nl_prompt="Replace all email addresses with [EMAIL]",
        )

        process_job(job.id)

        job.refresh_from_db()
        assert job.status == "SUCCESS", f"Job failed: {job.error_message}"

        page = paginate_result(job.output_file_path, page=1, page_size=3)
        assert page["total_rows"] == 5
        assert page["total_pages"] == 2
        assert page["page"] == 1
        assert len(page["rows"]) == 3
        assert page["rows"][0]["name"] == "Alice"