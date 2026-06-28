# Django Base Setup, Models, & Celery Configuration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Initialize the Django database configuration with PostgreSQL support, configure Celery with Redis, and implement `DatasetUpload` and `ProcessingJob` models in dedicated Django apps.

**Architecture:** The project uses two separate Django apps (`uploads` and `jobs`) for clear separation of concerns. `docker-compose.yml` defines a PostgreSQL 15 service (`db`), and `settings.py` connects to PostgreSQL via environment variables with a clean fallback to SQLite for local management commands. Celery uses Redis as its message broker and result backend.

**Tech Stack:** Python 3.10+, Django 4.2.11, Celery 5.3.6, Redis 5.0.3, psycopg2-binary 2.9.9, PostgreSQL 15.

## Global Constraints

- Python version floor: `>=3.10`
- Django version: `4.2.11`
- Database driver: `psycopg2-binary==2.9.9`
- Shared filesystem path storage for `DatasetUpload` (per ADR 0001)
- Valid job status choices: `QUEUED`, `RUNNING`, `SUCCESS`, `FAILED`
- Default progress for `ProcessingJob`: `0.0`

---

### Task 1: Add `psycopg2-binary` to `pyproject.toml` and configure `docker-compose.yml`

**Files:**
- Modify: `backend/pyproject.toml:6-16`
- Modify: `docker-compose.yml:1-58`

**Interfaces:**
- Consumes: None
- Produces: `psycopg2-binary` dependency for Django ORM, `db` PostgreSQL service on port 5432.

- [ ] **Step 1: Modify `backend/pyproject.toml` to add `psycopg2-binary`**

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
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

- [ ] **Step 2: Modify `docker-compose.yml` to add PostgreSQL service and environment variables**

```yaml
services:
  redis:
    image: redis:7.2-alpine
    container_name: rhombus_redis
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5
    restart: unless-stopped

  db:
    image: postgres:15-alpine
    container_name: rhombus_db
    ports:
      - "5432:5432"
    environment:
      - POSTGRES_DB=rhombus
      - POSTGRES_USER=postgres
      - POSTGRES_PASSWORD=postgres
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres -d rhombus"]
      interval: 5s
      timeout: 3s
      retries: 5
    restart: unless-stopped

  web:
    build:
      context: ./backend
      dockerfile: Dockerfile.web   # slim image, no Spark
    image: rhombus_web
    container_name: rhombus_web
    command: python manage.py runserver 0.0.0.0:8000
    volumes:
      - ./backend:/app
    ports:
      - "8000:8000"
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
    depends_on:
      redis:
        condition: service_healthy
      db:
        condition: service_healthy
    restart: unless-stopped

  celery:
    build:
      context: ./backend
      dockerfile: Dockerfile
    image: rhombus_celery
    container_name: rhombus_celery
    command: celery -A core worker --loglevel=info
    volumes:
      - ./backend:/app
    environment:
      - CELERY_BROKER_URL=redis://redis:6379/0
      - CELERY_RESULT_BACKEND=redis://redis:6379/1
      - CACHE_URL=redis://redis:6379/2
      - DB_NAME=rhombus
      - DB_USER=postgres
      - DB_PASSWORD=postgres
      - DB_HOST=db
      - DB_PORT=5432
      - SPARK_MASTER=local[*]
      - GEMINI_API_KEY=${GEMINI_API_KEY:-mock_key}
    depends_on:
      redis:
        condition: service_healthy
      db:
        condition: service_healthy
    restart: unless-stopped

volumes:
  redis_data:
  postgres_data:
```

- [ ] **Step 3: Commit changes**

```bash
git add backend/pyproject.toml docker-compose.yml
git commit -m "chore: add psycopg2-binary and postgres service to docker-compose"
```

---

### Task 2: Configure `backend/core/settings.py` for database environment variables and `uploads` / `jobs` apps

**Files:**
- Modify: `backend/core/settings.py:34-43,77-86`

**Interfaces:**
- Consumes: Environment variables `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`.
- Produces: Installed apps `uploads` and `jobs`, database connection to PostgreSQL (with SQLite fallback).

- [ ] **Step 1: Modify `backend/core/settings.py` to add `uploads` and `jobs` to `INSTALLED_APPS` and update `DATABASES`**

```python
# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'corsheaders',
    'uploads',
    'jobs',
]
```

```python
# Database
# https://docs.djangoproject.com/en/4.2/ref/settings/#databases

if os.environ.get('DB_HOST'):
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.environ.get('DB_NAME', 'rhombus'),
            'USER': os.environ.get('DB_USER', 'postgres'),
            'PASSWORD': os.environ.get('DB_PASSWORD', 'postgres'),
            'HOST': os.environ.get('DB_HOST', 'db'),
            'PORT': os.environ.get('DB_PORT', '5432'),
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }
```

- [ ] **Step 2: Commit changes**

```bash
git add backend/core/settings.py
git commit -m "chore: configure postgres database settings and register uploads and jobs apps"
```

---

### Task 3: Create `uploads` app structure and implement `DatasetUpload` model with TDD

**Files:**
- Create: `backend/uploads/__init__.py`
- Create: `backend/uploads/apps.py`
- Create: `backend/uploads/migrations/__init__.py`
- Create: `backend/uploads/models.py`
- Create: `backend/uploads/tests.py`

**Interfaces:**
- Consumes: Django base models.
- Produces: `uploads.models.DatasetUpload` model with `file_path` (`CharField(max_length=1024)`) and `uploaded_at` (`DateTimeField(auto_now_add=True)`).

- [ ] **Step 1: Create `uploads` app base files and write failing test in `backend/uploads/tests.py`**

Create `backend/uploads/__init__.py`:
```python
# uploads package
```

Create `backend/uploads/apps.py`:
```python
from django.apps import AppConfig


class UploadsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "uploads"
```

Create `backend/uploads/migrations/__init__.py`:
```python
# migrations package
```

Create `backend/uploads/models.py`:
```python
from django.db import models

# Create your models here.
```

Create `backend/uploads/tests.py`:
```python
from django.test import TestCase
from uploads.models import DatasetUpload


class DatasetUploadModelTest(TestCase):

    def test_create_dataset_upload(self):
        dataset = DatasetUpload.objects.create(file_path="uploads/test_file.csv")
        self.assertEqual(dataset.file_path, "uploads/test_file.csv")
        self.assertIsNotNone(dataset.uploaded_at)
        self.assertEqual(str(dataset), f"DatasetUpload {dataset.id}: uploads/test_file.csv")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test uploads` (from `backend` directory)
Expected: FAIL with `ImportError: cannot import name 'DatasetUpload' from 'uploads.models'`

- [ ] **Step 3: Implement `DatasetUpload` model in `backend/uploads/models.py` and generate migrations**

Modify `backend/uploads/models.py`:
```python
from django.db import models


class DatasetUpload(models.Model):
    file_path = models.CharField(max_length=1024)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"DatasetUpload {self.id}: {self.file_path}"
```

Run: `python manage.py makemigrations uploads` (from `backend` directory)
Expected: `Migrations for 'uploads': backend/uploads/migrations/0001_initial.py`

- [ ] **Step 4: Run test to verify it passes**

Run: `python manage.py test uploads` (from `backend` directory)
Expected: PASS (`OK`)

- [ ] **Step 5: Commit changes**

```bash
git add backend/uploads
git commit -m "feat(uploads): implement DatasetUpload model with tests and initial migration"
```

---

### Task 4: Create `jobs` app structure and implement `ProcessingJob` model with TDD

**Files:**
- Create: `backend/jobs/__init__.py`
- Create: `backend/jobs/apps.py`
- Create: `backend/jobs/migrations/__init__.py`
- Create: `backend/jobs/models.py`
- Create: `backend/jobs/tests.py`

**Interfaces:**
- Consumes: `uploads.models.DatasetUpload`.
- Produces: `jobs.models.ProcessingJob` model tracking status (`QUEUED`, `RUNNING`, `SUCCESS`, `FAILED`), progress, error_message, and task_id.

- [ ] **Step 1: Create `jobs` app base files and write failing test in `backend/jobs/tests.py`**

Create `backend/jobs/__init__.py`:
```python
# jobs package
```

Create `backend/jobs/apps.py`:
```python
from django.apps import AppConfig


class JobsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "jobs"
```

Create `backend/jobs/migrations/__init__.py`:
```python
# migrations package
```

Create `backend/jobs/models.py`:
```python
from django.db import models

# Create your models here.
```

Create `backend/jobs/tests.py`:
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
        self.assertEqual(str(job), f"ProcessingJob {job.id} (QUEUED) - Progress: 0.0%")

    def test_update_processing_job_status(self):
        job = ProcessingJob.objects.create(dataset=self.dataset, status="RUNNING", progress=50.5, task_id="celery-123")
        self.assertEqual(job.status, "RUNNING")
        self.assertEqual(job.progress, 50.5)
        self.assertEqual(job.task_id, "celery-123")
        self.assertEqual(str(job), f"ProcessingJob {job.id} (RUNNING) - Progress: 50.5%")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test jobs` (from `backend` directory)
Expected: FAIL with `ImportError: cannot import name 'ProcessingJob' from 'jobs.models'`

- [ ] **Step 3: Implement `ProcessingJob` model in `backend/jobs/models.py` and generate migrations**

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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"ProcessingJob {self.id} ({self.status}) - Progress: {self.progress}%"
```

Run: `python manage.py makemigrations jobs` (from `backend` directory)
Expected: `Migrations for 'jobs': backend/jobs/migrations/0001_initial.py`

- [ ] **Step 4: Run test to verify it passes**

Run: `python manage.py test jobs` (from `backend` directory)
Expected: PASS (`OK`)

- [ ] **Step 5: Commit changes**

```bash
git add backend/jobs
git commit -m "feat(jobs): implement ProcessingJob model with tests and initial migration"
```
