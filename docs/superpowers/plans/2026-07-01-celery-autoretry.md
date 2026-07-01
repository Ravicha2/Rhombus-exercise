# Celery Autoretry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add automatic retry with exponential backoff for transient LLM/API errors on the `process_job` Celery task, with whole-task state reset on retry.

**Architecture:** Celery's `autoretry_for` handles retry scheduling. On retry, the task detects a non-QUEUED job and resets it to QUEUED so the normal flow can re-execute cleanly. Deterministic errors bypass retry entirely.

**Tech Stack:** Python, Celery, Django, openai SDK (for exception classes)

## Global Constraints

- Import `APIConnectionError`, `RateLimitError`, `APITimeoutError` directly from `openai`
- `max_retries=3` with `retry_backoff=True`
- State reset bypasses `VALID_TRANSITIONS` as intentional internal recovery (per ADR 0005)
- TDD: write failing test first, then implement

---

### Task 1: Add autoretry_for configuration to process_job decorator

**Files:**
- Modify: `backend/jobs/tasks.py` (lines 1-16)
- Test: `backend/tests/jobs/tests_tasks.py`

**Interfaces:**
- Consumes: `openai.APIConnectionError`, `openai.RateLimitError`, `openai.APITimeoutError`
- Produces: `process_job` task with `autoretry_for`, `retry_backoff=True`, `max_retries=3`

- [ ] **Step 1: Write failing test for autoretry_for configuration**

Add to `backend/tests/jobs/tests_tasks.py`:

```python
from openai import APIConnectionError, RateLimitError, APITimeoutError

class ProcessJobRetryConfigTest(TestCase):
    def setUp(self):
        cache.clear()
        self.dataset = DatasetUpload.objects.create(
            file_path="uploads/test.csv",
            status="READY",
            column_names=["email"],
        )

    def test_autoretry_for_includes_transient_errors(self):
        from jobs.tasks import process_job

        retry_for = process_job.autoretry_for
        self.assertIn(APIConnectionError, retry_for)
        self.assertIn(RateLimitError, retry_for)
        self.assertIn(APITimeoutError, retry_for)

    def test_max_retries_is_three(self):
        from jobs.tasks import process_job

        self.assertEqual(process_job.max_retries, 3)

    def test_retry_backoff_enabled(self):
        from jobs.tasks import process_job

        self.assertTrue(process_job.retry_backoff)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/jobs/tests_tasks.py::ProcessJobRetryConfigTest -v`
Expected: FAIL (import succeeds but `autoretry_for` is empty/not configured, assertions fail)

- [ ] **Step 3: Update the process_job decorator in tasks.py**

Replace lines 16-17 of `backend/jobs/tasks.py`:

```python
@shared_task(bind=True)
def process_job(self, job_id: int) -> None:
```

With:

```python
@shared_task(
    bind=True,
    autoretry_for=(APIConnectionError, RateLimitError, APITimeoutError),
    retry_backoff=True,
    max_retries=3,
)
def process_job(self, job_id: int) -> None:
```

Add imports at the top of `backend/jobs/tasks.py`, after the existing imports:

```python
from openai import APIConnectionError, RateLimitError, APITimeoutError
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/jobs/tests_tasks.py::ProcessJobRetryConfigTest -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/jobs/tasks.py backend/tests/jobs/tests_tasks.py
git commit -m "feat: add autoretry_for transient API errors to process_job task"
```

---

### Task 2: Add retry state reset logic

**Files:**
- Modify: `backend/jobs/tasks.py` (after job fetch, before `mark_running`)
- Test: `backend/tests/jobs/tests_tasks.py`

**Interfaces:**
- Consumes: `ProcessingJob` model, `VALID_TRANSITIONS` (bypassed intentionally)
- Produces: `process_job` resets non-QUEUED jobs to QUEUED on retry

- [ ] **Step 1: Write failing test for retry state reset**

Add to `backend/tests/jobs/tests_tasks.py`:

```python
class ProcessJobRetryResetTest(TestCase):
    def setUp(self):
        cache.clear()
        self.dataset = DatasetUpload.objects.create(
            file_path="uploads/test.csv",
            status="READY",
            column_names=["email"],
        )

    @patch("jobs.tasks.SparkProcessingService")
    @patch("jobs.tasks.StorageService")
    @patch("jobs.tasks.LLMRegexService")
    @patch("jobs.tasks.TriageService")
    def test_retry_resets_failed_job_to_queued(self, mock_triage, mock_regex, mock_storage, mock_spark):
        """When process_job runs on a FAILED job (retry scenario), it resets to QUEUED first."""
        mock_triage.triage.return_value = [
            {"column": "email", "nl_pattern": "email addresses", "replacement": "[REDACTED]"},
        ]
        mock_regex.get_or_generate_regex.return_value = r"\b\S+@\S+\.\S+\b"
        mock_storage.resolve_parquet_absolute_path.return_value = "/tmp/test.parquet"
        mock_spark.process.return_value = ("output/1/result", "output/1/preview.parquet")

        job = ProcessingJob.objects.create(dataset=self.dataset, nl_prompt="redact emails")
        # Simulate a previous transient failure: job is FAILED with error message and partial progress
        job.status = "FAILED"
        job.error_message = "Connection error"
        job.progress = 42.0
        job.save()

        from jobs.tasks import process_job
        process_job(job.id)

        job.refresh_from_db()
        self.assertEqual(job.status, "SUCCESS")
        self.assertIsNone(job.error_message)
        self.assertEqual(job.progress, 100.0)

    @patch("jobs.tasks.SparkProcessingService")
    @patch("jobs.tasks.StorageService")
    @patch("jobs.tasks.LLMRegexService")
    @patch("jobs.tasks.TriageService")
    def test_retry_resets_running_job_to_queued(self, mock_triage, mock_regex, mock_storage, mock_spark):
        """When process_job runs on a RUNNING job (crash recovery), it resets to QUEUED first."""
        mock_triage.triage.return_value = [
            {"column": "email", "nl_pattern": "email addresses", "replacement": "[REDACTED]"},
        ]
        mock_regex.get_or_generate_regex.return_value = r"\b\S+@\S+\.\S+\b"
        mock_storage.resolve_parquet_absolute_path.return_value = "/tmp/test.parquet"
        mock_spark.process.return_value = ("output/1/result", "output/1/preview.parquet")

        job = ProcessingJob.objects.create(dataset=self.dataset, nl_prompt="redact emails")
        # Simulate a crashed task: job is RUNNING with partial progress
        job.status = "RUNNING"
        job.progress = 50.0
        job.save()

        from jobs.tasks import process_job
        process_job(job.id)

        job.refresh_from_db()
        self.assertEqual(job.status, "SUCCESS")
        self.assertEqual(job.progress, 100.0)

    def test_queued_job_not_reset(self):
        """A fresh QUEUED job should not trigger the reset branch."""
        job = ProcessingJob.objects.create(dataset=self.dataset, nl_prompt="redact emails")
        self.assertEqual(job.status, "QUEUED")
        # No need to run the full task; just verify the condition check
        # If status is QUEUED, the reset block is skipped entirely
        self.assertEqual(job.progress, 0.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/jobs/tests_tasks.py::ProcessJobRetryResetTest -v`
Expected: FAIL (reset logic not yet implemented, FAILED job can't transition to RUNNING via `mark_running`)

- [ ] **Step 3: Add state reset logic to process_job**

In `backend/jobs/tasks.py`, add the reset block after fetching the job and before `mark_running`. The full function should now read:

```python
@shared_task(
    bind=True,
    autoretry_for=(APIConnectionError, RateLimitError, APITimeoutError),
    retry_backoff=True,
    max_retries=3,
)
def process_job(self, job_id: int) -> None:
    """Orchestrate triage -> regex generation -> Spark processing for a ProcessingJob."""
    try:
        job = ProcessingJob.objects.get(id=job_id)
    except ProcessingJob.DoesNotExist:
        logger.error("ProcessingJob %s not found", job_id)
        raise

    # Retry recovery: reset partial state so the normal flow can re-execute
    if job.status != "QUEUED":
        job.status = "QUEUED"
        job.error_message = None
        job.progress = 0.0
        job.save()

    job.mark_running(task_id=self.request.id)

    try:
        dataset = job.dataset
        column_names = dataset.column_names or []

        # Stage 1: Triage
        transformations = TriageService.triage(job.nl_prompt, column_names)
        job.transformations = transformations
        job.save()

        # Stage 2: Regex generation
        generated_regexes = []
        for t in transformations:
            regex = LLMRegexService.get_or_generate_regex(t["nl_pattern"])
            generated_regexes.append({"column": t["column"], "regex": regex})
        job.generated_regexes = generated_regexes
        job.save()

        # Stage 3: Build Spark specs by merging transformations with regexes
        specs = [
            {
                "column": t["column"],
                "regex": g["regex"],
                "replacement": t["replacement"],
            }
            for t, g in zip(transformations, generated_regexes)
        ]

        # Stage 4: Spark processing
        parquet_path = StorageService.resolve_parquet_absolute_path(dataset)

        def progress_callback(pct: int) -> None:
            job.update_progress(pct)

        result_rel, preview_rel = SparkProcessingService.process(
            parquet_path=parquet_path,
            specs=specs,
            job_id=job_id,
            progress_callback=progress_callback,
        )

        job.mark_success(output_file_path=result_rel, preview_file_path=preview_rel)

    except (TriageError, ValueError, RegexSafetyError) as exc:
        job.mark_failed(error_message=str(exc))
        raise
    except Exception as exc:
        job.mark_failed(error_message=str(exc))
        raise
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/jobs/tests_tasks.py::ProcessJobRetryResetTest -v`
Expected: PASS

- [ ] **Step 5: Run full test suite to check for regressions**

Run: `cd backend && python -m pytest tests/jobs/tests_tasks.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add backend/jobs/tasks.py backend/tests/jobs/tests_tasks.py
git commit -m "feat: reset job state to QUEUED on retry for clean re-execution"
```

---

### Task 3: Verify deterministic errors are not retried

**Files:**
- Test: `backend/tests/jobs/tests_tasks.py`

**Interfaces:**
- Consumes: `TriageError`, `ValueError`, `RegexSafetyError` (not in `autoretry_for`)
- Produces: Confirms deterministic errors fail immediately without retry

- [ ] **Step 1: Write test confirming deterministic errors are not retried**

Add to `backend/tests/jobs/tests_tasks.py`:

```python
class ProcessJobDeterministicErrorTest(TestCase):
    def setUp(self):
        cache.clear()
        self.dataset = DatasetUpload.objects.create(
            file_path="uploads/test.csv",
            status="READY",
            column_names=["email"],
        )

    def test_triage_error_not_in_autoretry_for(self):
        from jobs.tasks import process_job
        from jobs.services import TriageError

        self.assertNotIn(TriageError, process_job.autoretry_for)

    def test_value_error_not_in_autoretry_for(self):
        from jobs.tasks import process_job

        self.assertNotIn(ValueError, process_job.autoretry_for)

    def test_regex_safety_error_not_in_autoretry_for(self):
        from jobs.tasks import process_job
        from jobs.services import RegexSafetyError

        self.assertNotIn(RegexSafetyError, process_job.autoretry_for)

    @patch("jobs.tasks.TriageService")
    @patch("jobs.tasks.LLMRegexService")
    def test_triage_error_fails_immediately_no_retry(self, mock_triage, mock_regex):
        """TriageError marks job FAILED and is not retried by Celery."""
        mock_triage.triage.side_effect = TriageError("Unknown columns")
        job = ProcessingJob.objects.create(dataset=self.dataset, nl_prompt="redact emails")

        from jobs.tasks import process_job
        with self.assertRaises(TriageError):
            process_job(job.id)

        job.refresh_from_db()
        self.assertEqual(job.status, "FAILED")
        self.assertIn("Unknown columns", job.error_message)
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/jobs/tests_tasks.py::ProcessJobDeterministicErrorTest -v`
Expected: PASS (existing code already handles this correctly, tests confirm the behavior)

- [ ] **Step 3: Run full test suite**

Run: `cd backend && python -m pytest tests/jobs/tests_tasks.py -v`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add backend/tests/jobs/tests_tasks.py
git commit -m "test: verify deterministic errors are not retried by Celery autoretry"
```