# Distributed NL-to-Regex Data Processing & Django REST API Design Specification

## 1. Overview
This specification defines the architecture, data flow, Django REST API endpoints, and distributed PySpark processing engine for Issue #3 and Issue #1 of the Distributed NL-to-Regex Data Processing Platform. It also establishes the precise execution mechanics for ADR 0001, ensuring PostgreSQL is used strictly for transactional model concurrency while large raw and processed datasets remain on the shared filesystem.

## 2. Architecture & Infrastructure
- **Shared Volume Storage**: Raw dataset uploads, full processed exports, and lightweight pagination preview files are stored in a shared Docker volume (`/app/uploads_storage/`), accessible by both `web` and `celery` containers.
- **LLM Integration via OpenRouter**: `openai` Python client library will be added to `pyproject.toml` to interact with OpenRouter (`https://openrouter.ai/api/v1`). The `web` and `celery` containers in `docker-compose.yml` will be configured with `OPENROUTER_API_KEY`.
- **Redis Broker & Cache**: Celery uses Redis as the message broker (`redis://redis:6379/0`) and result backend (`redis://redis:6379/1`). Redis is also used as a caching layer (`redis://redis:6379/2`) to cache LLM-generated regex patterns.

## 3. Django Application Structure & Endpoints

### 3.1 `uploads` Application
Responsible for managing raw dataset ingestion without blocking the web process.
- **Model `DatasetUpload`**: Existing model tracking `file_path` (`CharField(max_length=1024)`) and `uploaded_at`.
- **View `UploadView` (`POST /api/uploads/`)**:
  - Accepts multipart form data containing a `file`.
  - Validates file extension (`.csv`, `.xlsx`, `.xls`).
  - Iterates over file chunks (`file.chunks()`) and writes directly to `/app/uploads_storage/<uuid>_<filename>`, ensuring large files are never buffered entirely in memory.
  - Creates a `DatasetUpload` record in PostgreSQL and returns `{"upload_id": dataset.id, "file_path": dataset.file_path, "uploaded_at": dataset.uploaded_at}` with HTTP `201 Created`.

### 3.2 `jobs` Application
Responsible for asynchronous task tracking, LLM regex generation, polling, and result retrieval.
- **Model `ProcessingJob` (Migration Required)**:
  - Add `output_file_path = models.CharField(max_length=1024, blank=True, null=True)`: Stores the relative path to the full processed export file on the shared filesystem.
  - Add `preview_file_path = models.CharField(max_length=1024, blank=True, null=True)`: Stores the relative path to the 1,000-row `preview_head.json` file on the shared filesystem.
- **Service `LLMRegexService`**:
  - Uses the `openai` client configured with `base_url="https://openrouter.ai/api/v1"` and `api_key=os.environ.get('OPENROUTER_API_KEY')`.
  - Sends a system prompt instructing the model (e.g. `meta-llama/llama-3-8b-instruct:free` or user-specified model) to output only the raw regex pattern for the natural language description.
  - Integrates with Redis (`CACHE_URL` / `django.core.cache.cache`) to get/set regex patterns keyed by `f"regex_prompt:{natural_language_prompt}"` with a 30-day TTL.
- **View `JobCreateView` (`POST /api/jobs/create/`)**:
  - Accepts JSON payload: `{"upload_id": 1, "natural_language_prompt": "find email addresses", "target_column": "Email", "replacement_value": "REDACTED"}`.
  - Calls `LLMRegexService` to fetch/generate the regex pattern.
  - Creates `ProcessingJob` record (`status='QUEUED'`, `progress=0.0`).
  - Dispatches Celery task `run_pyspark_job.delay(job.id, regex_pattern, target_column, replacement_value)`.
  - Returns `{"job_id": job.id, "status": "QUEUED", "regex_pattern": regex_pattern}` with HTTP `202 Accepted`.
- **View `JobStatusView` (`GET /api/jobs/<job_id>/status/?page=1&size=50`)**:
  - Fetches `ProcessingJob`.
  - Returns base JSON: `{"job_id": job.id, "status": job.status, "progress": job.progress, "error_message": job.error_message}`.
  - If `status == 'SUCCESS'` and `preview_file_path` exists, loads `preview_<job_id>.json` into memory, slices `[(page-1)*size : page*size]`, and attaches `{"preview_data": sliced_data, "total_preview_rows": len(all_data), "page": page, "size": size}`.
- **View `JobDownloadView` (`GET /api/jobs/<job_id>/download/`)**:
  - Fetches `ProcessingJob`. If `status == 'SUCCESS'`, opens `output_file_path` and returns a Django `FileResponse` with `as_attachment=True` and `filename=f"processed_{job.id}.csv"`.

## 4. Distributed PySpark Engine (`jobs.tasks`)
- **Task `run_pyspark_job(job_id, regex_pattern, target_column, replacement_value)`**:
  - Runs in the `celery` container. Updates `ProcessingJob.status = 'RUNNING'`.
  - Initializes PySpark: `SparkSession.builder.master("local[*]").appName("RhombusWorker").getOrCreate()`.
  - Reads the raw dataset from `DatasetUpload.file_path`. For CSV: `spark.read.csv(file_path, header=True, inferSchema=True)`. For Excel: uses `pandas` to read and converts to Spark DataFrame via `spark.createDataFrame()`.
  - Updates `ProcessingJob.progress = 25.0`.
  - Applies transformation: `df.withColumn(target_column, pyspark.sql.functions.regexp_replace(pyspark.sql.functions.col(target_column), regex_pattern, replacement_value))`.
  - Updates `ProcessingJob.progress = 75.0`.
  - Writes full processed DataFrame to `/app/uploads_storage/processed_<job_id>.csv` using `df.write.csv(..., header=True)`.
  - Generates lightweight preview: `df.limit(1000).toPandas().to_json('/app/uploads_storage/preview_<job_id>.json', orient='records')`.
  - Updates `ProcessingJob.status = 'SUCCESS'`, `progress = 100.0`, `output_file_path = 'uploads_storage/processed_<job_id>.csv'`, `preview_file_path = 'uploads_storage/preview_<job_id>.json'`.

## 5. Error Handling & Validation
- **LLM Regex Validation**: Before applying or caching the regex, `LLMRegexService` strips any surrounding markdown (e.g. ````regex ... ````) and verifies `re.compile(regex_pattern)`. If invalid, `JobCreateView` returns HTTP `400 Bad Request` with an error explanation.
- **Task Failures**: `run_pyspark_job` wraps execution in a try/except block. On failure, it captures `traceback.format_exc()`, sets `ProcessingJob.status = 'FAILED'`, and populates `error_message`.
- **Celery Retries**: Configured with `autoretry_for=(Exception,)`, `max_retries=2`, `countdown=5` with exponential backoff.

## 6. Testing Strategy
- **Unit Tests (`uploads/tests.py`)**:
  - `test_upload_view_success`: Mocks `SimpleUploadedFile`, verifies file streaming to disk and `DatasetUpload` creation.
  - `test_upload_view_invalid_file`: Submits `.exe` file, verifies HTTP `400 Bad Request`.
- **Unit Tests (`jobs/tests.py`)**:
  - `test_job_create_view`: Mocks `LLMRegexService` and Celery `delay`, verifies `ProcessingJob` creation and HTTP `202 Accepted`.
  - `test_job_status_view_running`: Verifies correct progress reporting when `RUNNING`.
  - `test_job_status_view_success_pagination`: Mocks `preview_head.json`, verifies correct slicing for `page=1&size=50` and `page=2&size=50`.
  - `test_job_download_view`: Verifies `FileResponse` headers for full export download.
- **PySpark Engine Tests (`jobs/tests_pyspark.py`)**:
  - `test_run_pyspark_job_execution`: Sets `CELERY_TASK_ALWAYS_EAGER=True`, runs `run_pyspark_job` synchronously against a temporary 10-row CSV file, verifying correct regex replacement, full export creation, and preview JSON creation.
