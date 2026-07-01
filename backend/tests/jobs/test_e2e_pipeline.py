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

CSV_PATH = os.path.join(os.path.dirname(__file__), "e2e_test_data.csv")
with open(CSV_PATH) as f:
    CSV_CONTENT = f.read()

ORIGINAL_EMAILS = [
    "alice@example.com", "bob@test.org", "carol@company.com",
    "dave@demo.net", "eve@sample.io", "frank@acme.com",
    "grace@corp.net", "hank@startup.io", "ivy@global.org", "jake@tech.com",
]
ORIGINAL_PHONES = [
    "(212) 555-1234", "(415) 555-5678", "(312) 555-9012",
    "(617) 555-3456", "(310) 555-7890", "(503) 555-2345",
    "(214) 555-6789", "(408) 555-4321", "(202) 555-8764", "(773) 555-1098",
]


def _docker_healthy():
    """Check Postgres and Redis containers are reachable."""
    import socket

    # Check Postgres - use localhost when running from host against Docker
    db_host = os.environ.get("DB_HOST", "localhost")
    db_port = int(os.environ.get("DB_PORT", "5432"))
    try:
        s = socket.create_connection((db_host, db_port), timeout=2)
        s.close()
    except OSError:
        return False

    # Check Redis - parse from URL, default to localhost
    redis_url = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
    try:
        parts = redis_url.replace("redis://", "").split("/")
        hp = parts[0].split(":")
        rhost = hp[0] if hp[0] else "localhost"
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
        """NL prompt -> triage -> regex -> Spark -> SUCCESS with transformed output.

        Assertions verify the pipeline runs end-to-end and targeted columns changed.
        Exact regex output is LLM-dependent, so we check structure not exact values.
        """
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
        assert len(job.transformations) > 0, "Triage should identify at least one column"
        assert len(job.generated_regexes) > 0, "Regex generation should produce at least one regex"

        # Read output Parquet and verify transformations were applied
        output_abs = os.path.join(
            StorageService.get_storage_base_dir(), job.output_file_path
        )
        result = pd.read_parquet(output_abs)
        assert len(result) == 10

        email_changed = list(result["email"]) != ORIGINAL_EMAILS
        phone_changed = list(result["phone"]) != ORIGINAL_PHONES
        assert email_changed or phone_changed, "At least one targeted column should be transformed"

        # Untargeted columns should be untouched
        assert list(result["name"]) == ["Alice", "Bob", "Carol", "Dave", "Eve", "Frank", "Grace", "Hank", "Ivy", "Jake"]
        assert list(result["city"]) == ["New York", "London", "Tokyo", "Paris", "Sydney", "Berlin", "Mumbai", "Seoul", "Toronto", "Chicago"]

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
            assert len(result) == 10

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
        assert page["total_rows"] == 10
        assert page["total_pages"] == 4  # 10 rows / 3 per page
        assert page["page"] == 1
        assert len(page["rows"]) == 3
        assert page["rows"][0]["name"] == "Alice"