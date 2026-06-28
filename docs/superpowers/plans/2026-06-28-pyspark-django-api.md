# Distributed NL-to-Regex Data Processing & Django REST API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the PySpark distributed data processing engine, OpenRouter LLM regex service, and Django REST API endpoints for asynchronous upload, job creation, polling with in-memory preview pagination, and full dataset export.

**Architecture:** The project maintains strict separation between PostgreSQL for metadata concurrency and a shared Docker volume (`/app/uploads_storage/`) for large dataset ingestion and dual-file export (`processed_<job_id>.csv` and `preview_<job_id>.json`). Celery manages asynchronous background execution using Redis as a message broker and cache layer, while OpenRouter provides LLM capabilities via the `openai` Python client.

**Tech Stack:** Python 3.10+, Django 4.2.11, Django REST Framework 3.15.1, Celery 5.3.6, Redis 5.0.3, PySpark 3.5.1, OpenAI Python Client 1.14.3.

## Global Constraints

- Python version floor: `>=3.10`
- Django version: `4.2.11`
- Shared filesystem path storage for `DatasetUpload` and `ProcessingJob` (per ADR 0001)
- OpenAI client library for OpenRouter LLM integration (`https://openrouter.ai/api/v1`)
- Dual-file export in PySpark: full CSV/Excel export and 1,000-row `preview_head.json`
- In-memory pagination of `preview_head.json` in Django API (`page`, `size` query params)

---

### Task 1: Add `openai` dependency, configure OpenRouter environment variables, and update `ProcessingJob` model

**Files:**
- Modify: `backend/pyproject.toml:6-17`
- Modify: `docker-compose.yml:105-148`
- Modify: `.env.example:13-15`
- Modify: `backend/jobs/models.py:1-25`
- Modify: `backend/jobs/tests.py:1-25`

**Interfaces:**
- Consumes: Environment variable `OPENROUTER_API_KEY`.
- Produces: `openai` dependency, `jobs.models.ProcessingJob` with `output_file_path` and `preview_file_path` fields.

- [ ] **Step 1: Write failing test in `backend/jobs/tests.py` verifying new model fields**

Modify `backend/jobs/tests.py`:
```python
from django.test import TestCase
from uploads.models import DatasetUpload
from jobs.models import ProcessingJob


class ProcessingJobModelTest(TestCase):

    def setUp(self):
        self.dataset = DatasetUpload.objects.create(file_path="uploads/test.csv")

    def test_create_processing_job_defaults(self):
        job = ProcessingJob.objects.create(dataset=self.dataset)
        self.assertEqual(job.status, "QUEUED")
        self.assertEqual(job.progress, 0.0)
        self.assertIsNone(job.task_id)
        self.assertIsNone(job.error_message)
        self.assertIsNone(job.output_file_path)
        self.assertIsNone(job.preview_file_path)
        self.assertEqual(str(job), f"ProcessingJob {job.id} (QUEUED) - Progress: 0.0%")

    def test_update_processing_job_fields(self):
        job = ProcessingJob.objects.create(
            dataset=self.dataset,
            status="SUCCESS",
            progress=100.0,
            task_id="celery-123",
            output_file_path="uploads_storage/processed_1.csv",
            preview_file_path="uploads_storage/preview_1.json"
        )
        self.assertEqual(job.status, "SUCCESS")
        self.assertEqual(job.progress, 100.0)
        self.assertEqual(job.task_id, "celery-123")
        self.assertEqual(job.output_file_path, "uploads_storage/processed_1.csv")
        self.assertEqual(job.preview_file_path, "uploads_storage/preview_1.json")
        self.assertEqual(str(job), f"ProcessingJob {job.id} (SUCCESS) - Progress: 100.0%")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test jobs` (from `backend` directory)
Expected: FAIL with `TypeError: ProcessingJob() got an unexpected keyword argument 'output_file_path'`

- [ ] **Step 3: Update `pyproject.toml`, `docker-compose.yml`, `.env.example`, and implement model fields in `backend/jobs/models.py`**

Modify `backend/pyproject.toml`:
```toml
[project]
name = "rhombus-backend"
version = "0.1.0"
description = "Rhombus AI – Take-Home Exercise Backend"
requires-python = ">=3.10"
dependencies = [
    "django==4.2.11",
    "djangorestframework==3.15.1",
    "django-cors-headers==4.3.1",
    "celery==5.3.6",
    "redis==5.0.3",
    "pyspark==3.5.1",
    "pandas==2.2.1",
    "openpyxl==3.1.2",
    "google-genai==0.2.0",
    "psycopg2-binary==2.9.9",
    "openai==1.14.3",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

Modify `docker-compose.yml` environment blocks for `web` and `celery`:
```yaml
    environment:
      - CELERY_BROKER_URL=redis://redis:6379/0
      - CELERY_RESULT_BACKEND=redis://redis:6379/1
      - CACHE_URL=redis://redis:6379/2
      - DB_NAME=rhombus
      - DB_USER=postgres
      - DB_PASSWORD=postgres
      - DB_HOST=db
      - DB_PORT=5432
      - GEMINI_API_KEY=${GEMINI_API_KEY:-mock_key}
      - OPENROUTER_API_KEY=${OPENROUTER_API_KEY:-mock_key}
```
(Apply to both `web` and `celery` service definitions in `docker-compose.yml`).

Modify `.env.example`:
```
# LLM Integration
GEMINI_API_KEY=your_gemini_api_key_here
OPENROUTER_API_KEY=your_openrouter_api_key_here
```

Modify `backend/jobs/models.py`:
```python
from django.db import models
from uploads.models import DatasetUpload


class ProcessingJob(models.Model):
    STATUS_CHOICES = [
        ("QUEUED", "QUEUED"),
        ("RUNNING", "RUNNING"),
        ("SUCCESS", "SUCCESS"),
        ("FAILED", "FAILED"),
    ]

    dataset = models.ForeignKey(DatasetUpload, on_delete=models.CASCADE, related_name="jobs")
    task_id = models.CharField(max_length=255, blank=True, null=True)
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default="QUEUED")
    progress = models.FloatField(default=0.0)
    error_message = models.TextField(blank=True, null=True)
    output_file_path = models.CharField(max_length=1024, blank=True, null=True)
    preview_file_path = models.CharField(max_length=1024, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"ProcessingJob {self.id} ({self.status}) - Progress: {self.progress}%"
```

Run: `python manage.py makemigrations jobs` (from `backend` directory)
Expected: `Migrations for 'jobs': backend/jobs/migrations/0002_processingjob_output_file_path_processingjob_preview_file_path.py`

- [ ] **Step 4: Run test to verify it passes**

Run: `python manage.py test jobs` (from `backend` directory)
Expected: PASS (`OK`)

- [ ] **Step 5: Commit changes**

```bash
git add backend/pyproject.toml docker-compose.yml .env.example backend/jobs
git commit -m "feat(jobs): add output and preview file path fields and configure OpenRouter dependency"
```

---

### Task 2: Implement `UploadView` in `uploads` app to stream file chunks to shared volume

**Files:**
- Create: `backend/uploads/views.py`
- Create: `backend/uploads/urls.py`
- Modify: `backend/core/urls.py:17-23`
- Modify: `backend/uploads/tests.py:1-25`

**Interfaces:**
- Consumes: Multipart form data with `file`.
- Produces: `POST /api/uploads/` endpoint returning `{"upload_id": 1, "file_path": "uploads_storage/...", "uploaded_at": "..."}`.

- [ ] **Step 1: Write failing test in `backend/uploads/tests.py` testing `UploadView`**

Modify `backend/uploads/tests.py`:
```python
import os
import shutil
from django.test import TestCase, Client
from django.core.files.uploadedfile import SimpleUploadedFile
from uploads.models import DatasetUpload
from django.conf import settings


class DatasetUploadViewTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.storage_dir = os.path.join(settings.BASE_DIR, 'uploads_storage')
        if not os.path.exists(self.storage_dir):
            os.makedirs(self.storage_dir)

    def tearDown(self):
        if os.path.exists(self.storage_dir):
            shutil.rmtree(self.storage_dir)

    def test_create_dataset_upload_model(self):
        dataset = DatasetUpload.objects.create(file_path="uploads_storage/test_file.csv")
        self.assertEqual(dataset.file_path, "uploads_storage/test_file.csv")
        self.assertIsNotNone(dataset.uploaded_at)
        self.assertEqual(str(dataset), f"DatasetUpload {dataset.id}: uploads_storage/test_file.csv")

    def test_upload_view_success_csv(self):
        csv_content = b"ID,Name,Email\n1,John Doe,john@example.com\n"
        upload_file = SimpleUploadedFile("test_upload.csv", csv_content, content_type="text/csv")
        response = self.client.post("/api/uploads/", {"file": upload_file})
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertIn("upload_id", data)
        self.assertIn("file_path", data)
        self.assertTrue(data["file_path"].startswith("uploads_storage/"))
        
        # Verify file exists on disk
        full_path = os.path.join(settings.BASE_DIR, data["file_path"])
        self.assertTrue(os.path.exists(full_path))
        with open(full_path, "rb") as f:
            self.assertEqual(f.read(), csv_content)

    def test_upload_view_invalid_extension(self):
        exe_content = b"MZ\x90\x00\x03\x00\x00\x00"
        upload_file = SimpleUploadedFile("app.exe", exe_content, content_type="application/x-msdownload")
        response = self.client.post("/api/uploads/", {"file": upload_file})
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test uploads` (from `backend` directory)
Expected: FAIL with `404 != 201` (URL `/api/uploads/` not found)

- [ ] **Step 3: Implement `UploadView`, configure `uploads/urls.py`, and register in `core/urls.py`**

Create `backend/uploads/views.py`:
```python
import os
import uuid
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from uploads.models import DatasetUpload


class UploadView(APIView):
    def post(self, request):
        uploaded_file = request.FILES.get('file')
        if not uploaded_file:
            return Response({"error": "No file provided."}, status=status.HTTP_400_BAD_REQUEST)

        ext = os.path.splitext(uploaded_file.name)[1].lower()
        if ext not in ['.csv', '.xlsx', '.xls']:
            return Response({"error": f"Unsupported file extension: {ext}. Permitted extensions are .csv, .xlsx, .xls"}, status=status.HTTP_400_BAD_REQUEST)

        storage_dir = os.path.join(settings.BASE_DIR, 'uploads_storage')
        if not os.path.exists(storage_dir):
            os.makedirs(storage_dir, exist_ok=True)

        filename = f"{uuid.uuid4().hex}_{uploaded_file.name}"
        save_path = os.path.join(storage_dir, filename)

        # Stream chunks directly to shared volume
        with open(save_path, 'wb+') as destination:
            for chunk in uploaded_file.chunks():
                destination.write(chunk)

        rel_path = f"uploads_storage/{filename}"
        dataset = DatasetUpload.objects.create(file_path=rel_path)

        return Response({
            "upload_id": dataset.id,
            "file_path": dataset.file_path,
            "uploaded_at": dataset.uploaded_at
        }, status=status.HTTP_201_CREATED)
```

Create `backend/uploads/urls.py`:
```python
from django.urls import path
from uploads.views import UploadView

urlpatterns = [
    path('', UploadView.as_view(), name='upload-dataset'),
]
```

Modify `backend/core/urls.py`:
```python
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/uploads/', include('uploads.urls')),
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python manage.py test uploads` (from `backend` directory)
Expected: PASS (`OK`)

- [ ] **Step 5: Commit changes**

```bash
git add backend/core/urls.py backend/uploads
git commit -m "feat(uploads): implement UploadView to stream large files to shared volume"
```

---

### Task 3: Implement `LLMRegexService` in `jobs` app with OpenRouter integration and Redis caching

**Files:**
- Create: `backend/jobs/services.py`
- Create: `backend/jobs/tests_service.py`

**Interfaces:**
- Consumes: `OPENROUTER_API_KEY`, `django.core.cache.cache`.
- Produces: `LLMRegexService.get_or_generate_regex(natural_language_prompt)`.

- [ ] **Step 1: Write failing test in `backend/jobs/tests_service.py` testing `LLMRegexService`**

Create `backend/jobs/tests_service.py`:
```python
from unittest.mock import patch, MagicMock
from django.test import TestCase
from django.core.cache import cache
from jobs.services import LLMRegexService


class LLMRegexServiceTest(TestCase):

    def setUp(self):
        cache.clear()

    @patch('jobs.services.OpenAI')
    def test_get_or_generate_regex_cached(self, mock_openai_class):
        prompt = "find email addresses"
        expected_regex = r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,7}\b"
        
        # Setup mock OpenAI client response
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content=expected_regex))]
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai_class.return_value = mock_client

        # First call should call LLM and cache
        result1 = LLMRegexService.get_or_generate_regex(prompt)
        self.assertEqual(result1, expected_regex)
        mock_client.chat.completions.create.assert_called_once()

        # Second call should fetch from cache without calling LLM again
        result2 = LLMRegexService.get_or_generate_regex(prompt)
        self.assertEqual(result2, expected_regex)
        self.assertEqual(mock_client.chat.completions.create.call_count, 1)

    @patch('jobs.services.OpenAI')
    def test_regex_sanitization_and_validation(self, mock_openai_class):
        prompt = "find ip addresses"
        raw_llm_output = "```regex\n\\b(?:[0-9]{1,3}\\.){3}[0-9]{1,3}\\b\n```"
        expected_regex = r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b"

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content=raw_llm_output))]
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai_class.return_value = mock_client

        result = LLMRegexService.get_or_generate_regex(prompt)
        self.assertEqual(result, expected_regex)

    @patch('jobs.services.OpenAI')
    def test_invalid_regex_raises_error(self, mock_openai_class):
        prompt = "invalid prompt"
        invalid_regex = r"([A-Z" # Unclosed parenthesis

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content=invalid_regex))]
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai_class.return_value = mock_client

        with self.assertRaises(ValueError) as context:
            LLMRegexService.get_or_generate_regex(prompt)
        self.assertIn("Generated regex pattern is invalid", str(context.exception))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test jobs.tests_service` (from `backend` directory)
Expected: FAIL with `ModuleNotFoundError: No module named 'jobs.services'`

- [ ] **Step 3: Implement `LLMRegexService` in `backend/jobs/services.py`**

Create `backend/jobs/services.py`:
```python
import os
import re
from django.core.cache import cache
from openai import OpenAI


class LLMRegexService:
    CACHE_PREFIX = "regex_prompt:"
    CACHE_TTL = 60 * 60 * 24 * 30  # 30 days

    @classmethod
    def get_or_generate_regex(cls, natural_language_prompt: str) -> str:
        cache_key = f"{cls.CACHE_PREFIX}{natural_language_prompt}"
        cached_regex = cache.get(cache_key)
        if cached_regex:
            return cached_regex

        api_key = os.environ.get('OPENROUTER_API_KEY', 'mock_key')
        client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key
        )

        system_prompt = (
            "You are an expert regular expression generator for PySpark data transformations. "
            "Convert the user's natural language pattern description into a precise, highly optimized, "
            "and valid Python/Java compatible regular expression. "
            "Output ONLY the raw regex string. Do not include markdown code blocks, backticks, explanations, or quotes."
        )

        response = client.chat.completions.create(
            model="meta-llama/llama-3-8b-instruct:free",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": natural_language_prompt}
            ],
            temperature=0.1,
        )

        raw_content = response.choices[0].message.content.strip()

        # Sanitize markdown wrapper if present
        pattern = raw_content
        if pattern.startswith("```"):
            lines = pattern.split("\n")
            if len(lines) >= 2:
                pattern = "\n".join(lines[1:-1]).strip()
            else:
                pattern = pattern.replace("```regex", "").replace("```", "").strip()

        # Validate regex compilation
        try:
            re.compile(pattern)
        except re.error as e:
            raise ValueError(f"Generated regex pattern is invalid: {e}. Pattern was: {pattern}")

        cache.set(cache_key, pattern, cls.CACHE_TTL)
        return pattern
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python manage.py test jobs.tests_service` (from `backend` directory)
Expected: PASS (`OK`)

- [ ] **Step 5: Commit changes**

```bash
git add backend/jobs/services.py backend/jobs/tests_service.py
git commit -m "feat(jobs): implement LLMRegexService using OpenRouter with Redis caching and regex sanitization"
```

---

### Task 4: Implement `run_pyspark_job` Celery task in `jobs` app for distributed regex replacement and dual-file export

**Files:**
- Create: `backend/jobs/tasks.py`
- Create: `backend/jobs/tests_tasks.py`

**Interfaces:**
- Consumes: `ProcessingJob`, `DatasetUpload`.
- Produces: `run_pyspark_job` Celery task writing `processed_<job_id>.csv` and `preview_<job_id>.json`.

- [ ] **Step 1: Write failing test in `backend/jobs/tests_tasks.py` testing `run_pyspark_job`**

Create `backend/jobs/tests_tasks.py`:
```python
import os
import shutil
from django.test import TestCase, override_settings
from django.conf import settings
from uploads.models import DatasetUpload
from jobs.models import ProcessingJob
from jobs.tasks import run_pyspark_job


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class PySparkEngineTaskTest(TestCase):

    def setUp(self):
        self.storage_dir = os.path.join(settings.BASE_DIR, 'uploads_storage')
        if not os.path.exists(self.storage_dir):
            os.makedirs(self.storage_dir)

        self.sample_csv = os.path.join(self.storage_dir, 'test_input.csv')
        with open(self.sample_csv, 'w') as f:
            f.write("ID,Name,Email\n1,John Doe,john.doe@example.com\n2,Jane Smith,jane_smith@domain.com\n")

        self.dataset = DatasetUpload.objects.create(file_path="uploads_storage/test_input.csv")
        self.job = ProcessingJob.objects.create(dataset=self.dataset, status="QUEUED")

    def tearDown(self):
        if os.path.exists(self.storage_dir):
            shutil.rmtree(self.storage_dir)

    def test_run_pyspark_job_success(self):
        regex_pattern = r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,7}\b"
        
        # Execute task synchronously
        run_pyspark_job(self.job.id, regex_pattern, "Email", "REDACTED")

        # Refresh job from DB
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, "SUCCESS")
        self.assertEqual(self.job.progress, 100.0)
        self.assertIsNotNone(self.job.output_file_path)
        self.assertIsNotNone(self.job.preview_file_path)

        # Verify full export exists
        full_output_path = os.path.join(settings.BASE_DIR, self.job.output_file_path)
        self.assertTrue(os.path.exists(full_output_path))
        with open(full_output_path, 'r') as f:
            content = f.read()
            self.assertIn("REDACTED", content)
            self.assertNotIn("john.doe@example.com", content)

        # Verify preview json exists
        full_preview_path = os.path.join(settings.BASE_DIR, self.job.preview_file_path)
        self.assertTrue(os.path.exists(full_preview_path))
        with open(full_preview_path, 'r') as f:
            json_content = f.read()
            self.assertIn("REDACTED", json_content)

    def test_run_pyspark_job_invalid_column(self):
        regex_pattern = r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,7}\b"
        
        # Non-existent column name
        run_pyspark_job(self.job.id, regex_pattern, "NonExistentCol", "REDACTED")

        self.job.refresh_from_db()
        self.assertEqual(self.job.status, "FAILED")
        self.assertIsNotNone(self.job.error_message)
        self.assertIn("NonExistentCol", self.job.error_message)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test jobs.tests_tasks` (from `backend` directory)
Expected: FAIL with `ImportError: cannot import name 'run_pyspark_job' from 'jobs.tasks'`

- [ ] **Step 3: Implement `run_pyspark_job` in `backend/jobs/tasks.py` using PySpark**

Create `backend/jobs/tasks.py`:
```python
import os
import traceback
import pandas as pd
from django.conf import settings
from celery import shared_task
from pyspark.sql import SparkSession
from pyspark.sql.functions import col, regexp_replace
from jobs.models import ProcessingJob


@shared_task(bind=True, autoretry_for=(Exception,), max_retries=2, countdown=5)
def run_pyspark_job(self, job_id: int, regex_pattern: str, target_column: str, replacement_value: str):
    try:
        job = ProcessingJob.objects.get(id=job_id)
    except ProcessingJob.DoesNotExist:
        return

    job.status = "RUNNING"
    job.task_id = self.request.id
    job.progress = 10.0
    job.save()

    try:
        # Resolve absolute input path
        input_path = os.path.join(settings.BASE_DIR, job.dataset.file_path)
        if not os.path.exists(input_path):
            raise FileNotFoundError(f"Dataset file not found at {input_path}")

        master = os.environ.get('SPARK_MASTER', 'local[*]')
        spark = SparkSession.builder \
            .master(master) \
            .appName(f"RhombusWorker_Job_{job_id}") \
            .getOrCreate()

        job.progress = 25.0
        job.save()

        ext = os.path.splitext(input_path)[1].lower()
        if ext == '.csv':
            df = spark.read.csv(input_path, header=True, inferSchema=True)
        else:
            # Excel fallback using pandas to feed spark
            pdf = pd.read_excel(input_path)
            df = spark.createDataFrame(pdf)

        if target_column not in df.columns:
            raise ValueError(f"Target column '{target_column}' does not exist in dataset. Available columns: {df.columns}")

        job.progress = 50.0
        job.save()

        # Apply distributed regex replacement
        df_clean = df.withColumn(target_column, regexp_replace(col(target_column), regex_pattern, replacement_value))

        job.progress = 75.0
        job.save()

        # Prepare output paths
        storage_dir = os.path.join(settings.BASE_DIR, 'uploads_storage')
        output_filename = f"processed_{job_id}.csv"
        output_path = os.path.join(storage_dir, output_filename)
        
        preview_filename = f"preview_{job_id}.json"
        preview_path = os.path.join(storage_dir, preview_filename)

        # PySpark write single CSV file via Pandas to ensure clean attachment structure without part-files
        df_clean.toPandas().to_csv(output_path, index=False)

        # Write lightweight preview head (1000 rows)
        df_clean.limit(1000).toPandas().to_json(preview_path, orient="records")

        job.status = "SUCCESS"
        job.progress = 100.0
        job.output_file_path = f"uploads_storage/{output_filename}"
        job.preview_file_path = f"uploads_storage/{preview_filename}"
        job.save()

    except Exception as e:
        job.status = "FAILED"
        job.error_message = f"{str(e)}\n{traceback.format_exc()}"
        job.save()
        raise e
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python manage.py test jobs.tests_tasks` (from `backend` directory)
Expected: PASS (`OK`)

- [ ] **Step 5: Commit changes**

```bash
git add backend/jobs/tasks.py backend/jobs/tests_tasks.py
git commit -m "feat(jobs): implement run_pyspark_job Celery task with distributed regex replacement and dual-file export"
```

---

### Task 5: Implement `JobCreateView`, `JobStatusView`, and `JobDownloadView` in `jobs` app with pagination

**Files:**
- Create: `backend/jobs/views.py`
- Create: `backend/jobs/urls.py`
- Modify: `backend/core/urls.py:20-25`
- Create: `backend/jobs/tests_views.py`

**Interfaces:**
- Consumes: `LLMRegexService`, `run_pyspark_job`, `ProcessingJob`.
- Produces: `POST /api/jobs/create/`, `GET /api/jobs/<job_id>/status/?page=1&size=50`, `GET /api/jobs/<job_id>/download/`.

- [ ] **Step 1: Write failing test in `backend/jobs/tests_views.py` testing job API endpoints**

Create `backend/jobs/tests_views.py`:
```python
import os
import json
import shutil
from unittest.mock import patch, MagicMock
from django.test import TestCase, Client
from django.conf import settings
from uploads.models import DatasetUpload
from jobs.models import ProcessingJob


class ProcessingJobViewsTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.storage_dir = os.path.join(settings.BASE_DIR, 'uploads_storage')
        if not os.path.exists(self.storage_dir):
            os.makedirs(self.storage_dir)

        self.dataset = DatasetUpload.objects.create(file_path="uploads_storage/test.csv")
        
        # Setup dummy preview and output files
        self.preview_path = os.path.join(self.storage_dir, 'preview_100.json')
        self.output_path = os.path.join(self.storage_dir, 'processed_100.csv')
        
        sample_preview = [{"ID": 1, "Email": "REDACTED"}, {"ID": 2, "Email": "REDACTED"}]
        with open(self.preview_path, 'w') as f:
            json.dump(sample_preview, f)
            
        with open(self.output_path, 'w') as f:
            f.write("ID,Email\n1,REDACTED\n2,REDACTED\n")

        self.job_success = ProcessingJob.objects.create(
            id=100,
            dataset=self.dataset,
            status="SUCCESS",
            progress=100.0,
            output_file_path="uploads_storage/processed_100.csv",
            preview_file_path="uploads_storage/preview_100.json"
        )

    def tearDown(self):
        if os.path.exists(self.storage_dir):
            shutil.rmtree(self.storage_dir)

    @patch('jobs.services.LLMRegexService.get_or_generate_regex')
    @patch('jobs.tasks.run_pyspark_job.delay')
    def test_job_create_view(self, mock_delay, mock_regex_service):
        mock_regex_service.return_value = r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,7}\b"
        mock_delay.return_value = MagicMock(id="celery-task-123")

        payload = {
            "upload_id": self.dataset.id,
            "natural_language_prompt": "find email addresses",
            "target_column": "Email",
            "replacement_value": "REDACTED"
        }

        response = self.client.post("/api/jobs/create/", payload, content_type="application/json")
        self.assertEqual(response.status_code, 202)
        data = response.json()
        self.assertIn("job_id", data)
        self.assertEqual(data["status"], "QUEUED")
        self.assertEqual(data["regex_pattern"], mock_regex_service.return_value)
        mock_delay.assert_called_once()

    def test_job_status_view_success_pagination(self):
        # Request page 1, size 1
        response = self.client.get(f"/api/jobs/{self.job_success.id}/status/?page=1&size=1")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "SUCCESS")
        self.assertEqual(data["progress"], 100.0)
        self.assertEqual(data["total_preview_rows"], 2)
        self.assertEqual(len(data["preview_data"]), 1)
        self.assertEqual(data["preview_data"][0]["ID"], 1)

        # Request page 2, size 1
        response2 = self.client.get(f"/api/jobs/{self.job_success.id}/status/?page=2&size=1")
        self.assertEqual(response2.status_code, 200)
        data2 = response2.json()
        self.assertEqual(len(data2["preview_data"]), 1)
        self.assertEqual(data2["preview_data"][0]["ID"], 2)

    def test_job_download_view(self):
        response = self.client.get(f"/api/jobs/{self.job_success.id}/download/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Content-Disposition"], f'attachment; filename="processed_{self.job_success.id}.csv"')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test jobs.tests_views` (from `backend` directory)
Expected: FAIL with `404 != 202` (URL `/api/jobs/create/` not found)

- [ ] **Step 3: Implement `JobCreateView`, `JobStatusView`, `JobDownloadView` in `backend/jobs/views.py` and configure routing**

Create `backend/jobs/views.py`:
```python
import os
import json
from django.conf import settings
from django.http import FileResponse
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from uploads.models import DatasetUpload
from jobs.models import ProcessingJob
from jobs.services import LLMRegexService
from jobs.tasks import run_pyspark_job


class JobCreateView(APIView):
    def post(self, request):
        upload_id = request.data.get('upload_id')
        prompt = request.data.get('natural_language_prompt')
        target_column = request.data.get('target_column')
        replacement_value = request.data.get('replacement_value', '')

        if not all([upload_id, prompt, target_column]):
            return Response({"error": "upload_id, natural_language_prompt, and target_column are required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            dataset = DatasetUpload.objects.get(id=upload_id)
        except DatasetUpload.DoesNotExist:
            return Response({"error": f"DatasetUpload with id {upload_id} does not exist."}, status=status.HTTP_404_NOT_FOUND)

        try:
            regex_pattern = LLMRegexService.get_or_generate_regex(prompt)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        job = ProcessingJob.objects.create(dataset=dataset, status="QUEUED", progress=0.0)

        # Dispatch Celery task
        task = run_pyspark_job.delay(job.id, regex_pattern, target_column, replacement_value)
        job.task_id = task.id
        job.save()

        return Response({
            "job_id": job.id,
            "status": job.status,
            "regex_pattern": regex_pattern
        }, status=status.HTTP_202_ACCEPTED)


class JobStatusView(APIView):
    def get(self, request, job_id):
        try:
            job = ProcessingJob.objects.get(id=job_id)
        except ProcessingJob.DoesNotExist:
            return Response({"error": f"ProcessingJob with id {job_id} does not exist."}, status=status.HTTP_404_NOT_FOUND)

        response_data = {
            "job_id": job.id,
            "status": job.status,
            "progress": job.progress,
            "error_message": job.error_message,
        }

        if job.status == "SUCCESS" and job.preview_file_path:
            try:
                page = int(request.query_params.get('page', 1))
                size = int(request.query_params.get('size', 50))
            except ValueError:
                page = 1
                size = 50

            preview_path = os.path.join(settings.BASE_DIR, job.preview_file_path)
            if os.path.exists(preview_path):
                with open(preview_path, 'r') as f:
                    all_rows = json.load(f)
                
                total_rows = len(all_rows)
                start = (page - 1) * size
                end = page * size
                sliced_rows = all_rows[start:end]

                response_data["preview_data"] = sliced_rows
                response_data["total_preview_rows"] = total_rows
                response_data["page"] = page
                response_data["size"] = size

        return Response(response_data, status=status.HTTP_200_OK)


class JobDownloadView(APIView):
    def get(self, request, job_id):
        try:
            job = ProcessingJob.objects.get(id=job_id)
        except ProcessingJob.DoesNotExist:
            return Response({"error": f"ProcessingJob with id {job_id} does not exist."}, status=status.HTTP_404_NOT_FOUND)

        if job.status != "SUCCESS" or not job.output_file_path:
            return Response({"error": "ProcessingJob has not completed successfully or output file is missing."}, status=status.HTTP_400_BAD_REQUEST)

        file_path = os.path.join(settings.BASE_DIR, job.output_file_path)
        if not os.path.exists(file_path):
            return Response({"error": "Output file not found on filesystem."}, status=status.HTTP_404_NOT_FOUND)

        filename = os.path.basename(file_path)
        response = FileResponse(open(file_path, 'rb'), as_attachment=True, filename=filename)
        return response
```

Create `backend/jobs/urls.py`:
```python
from django.urls import path
from jobs.views import JobCreateView, JobStatusView, JobDownloadView

urlpatterns = [
    path('create/', JobCreateView.as_view(), name='job-create'),
    path('<int:job_id>/status/', JobStatusView.as_view(), name='job-status'),
    path('<int:job_id>/download/', JobDownloadView.as_view(), name='job-download'),
]
```

Modify `backend/core/urls.py`:
```python
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/uploads/', include('uploads.urls')),
    path('api/jobs/', include('jobs.urls')),
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python manage.py test jobs.tests_views` (from `backend` directory)
Expected: PASS (`OK`)

- [ ] **Step 5: Commit changes**

```bash
git add backend/core/urls.py backend/jobs
git commit -m "feat(jobs): implement JobCreateView, JobStatusView, and JobDownloadView with preview pagination"
```

---
