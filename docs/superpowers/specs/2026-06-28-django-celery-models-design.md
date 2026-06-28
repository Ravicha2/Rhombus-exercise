# Django Base Setup, Models, & Celery Configuration Design Specification

## 1. Overview
This specification details the architecture and data models for Subtask 2 of the Distributed NL-to-Regex Data Processing Platform. It establishes a multi-app Django backend (`uploads` and `jobs`) backed by PostgreSQL, with Celery configured to use Redis as the message broker and result backend.

## 2. Architecture & Infrastructure
- **Database Service**: A PostgreSQL 15 service (`db`) using `postgres:15-alpine` will be added to `docker-compose.yml`, persisting data via a Docker volume named `postgres_data`.
- **Driver**: `psycopg2-binary` will be added to `pyproject.toml` to serve as the DB-API driver for Django's ORM.
- **Environment Variables**: The `web` and `celery` containers will be configured with environment variables for database connectivity (`DB_NAME=rhombus`, `DB_USER=postgres`, `DB_PASSWORD=postgres`, `DB_HOST=db`, `DB_PORT=5432`) and will include `db` in their `depends_on` configurations.

## 3. Django Application Structure & Models
To maintain clean separation of concerns and support future distributed scalability, two separate Django applications will be created.

### 3.1 `uploads` Application
Responsible for tracking dataset files ingested into the shared filesystem.
- **Model `DatasetUpload`**:
  - `file_path`: `models.CharField(max_length=1024)` storing the absolute or relative path to the file on the shared filesystem (per ADR 0001).
  - `uploaded_at`: `models.DateTimeField(auto_now_add=True)`.
  - `__str__`: Returns `f"DatasetUpload {self.id}: {self.file_path}"`.

### 3.2 `jobs` Application
Responsible for tracking asynchronous background processing workflows in Celery.
- **Model `ProcessingJob`**:
  - `dataset`: `models.ForeignKey('uploads.DatasetUpload', on_delete=models.CASCADE, related_name='jobs')`.
  - `task_id`: `models.CharField(max_length=255, blank=True, null=True)` storing the Celery task ID once dispatched.
  - `status`: `models.CharField(max_length=32, choices=[('QUEUED', 'QUEUED'), ('RUNNING', 'RUNNING'), ('SUCCESS', 'SUCCESS'), ('FAILED', 'FAILED')], default='QUEUED')`.
  - `progress`: `models.FloatField(default=0.0)` tracking execution percentage (0.0 to 100.0).
  - `error_message`: `models.TextField(blank=True, null=True)` storing traceback or error details if a task fails.
  - `created_at`: `models.DateTimeField(auto_now_add=True)`.
  - `updated_at`: `models.DateTimeField(auto_now=True)`.
  - `__str__`: Returns `f"ProcessingJob {self.id} ({self.status}) - Progress: {self.progress}%"`.

## 4. Celery & Redis Configuration
- **Broker & Backend**: `CELERY_BROKER_URL` and `CELERY_RESULT_BACKEND` are defined in `settings.py` pointing to Redis (`redis://redis:6379/0` and `redis://redis:6379/1`).
- **App Autodiscovery**: `core.celery.app` uses `autodiscover_tasks()`, which will automatically detect task modules inside `uploads` and `jobs`.

## 5. Error Handling & Validation
- **Model Constraints**: Django model field choices will enforce valid job statuses (`QUEUED`, `RUNNING`, `SUCCESS`, `FAILED`).
- **Database Fallback**: In `settings.py`, `DATABASES` will check for `DB_HOST`. If absent (e.g. running local management commands outside Docker), it will cleanly fall back to `db.sqlite3`.

## 6. Testing Strategy
- **Unit Tests**: `uploads/tests.py` and `jobs/tests.py` will include test cases verifying model creation, correct default values (`QUEUED`, `0.0`), foreign key cascade deletion, and string representations.
