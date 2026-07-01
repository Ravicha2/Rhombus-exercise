# Celery Autoretry with Whole-Task State Reset

## Context

ProcessingJob tasks can fail transiently due to LLM/API errors (network, rate limits, timeouts). These should auto-retry with backoff. Deterministic errors (triage failures, invalid regex, safety errors) must fail immediately.

## Design

### Task decorator

Add `autoretry_for`, `retry_backoff`, and `max_retries` to the `process_job` task decorator:

```python
@shared_task(
    bind=True,
    autoretry_for=(APIConnectionError, RateLimitError, APITimeoutError),
    retry_backoff=True,
    max_retries=3,
)
```

Import `APIConnectionError`, `RateLimitError`, `APITimeoutError` directly from `openai`.

### Retry state reset

At the top of `process_job`, after fetching the job, reset state if the job is not in QUEUED (indicates a retry after a transient failure):

```python
if job.status in ("RUNNING", "FAILED"):
    job.status = "QUEUED"
    job.error_message = None
    job.progress = 0.0
    job.save()
```

This bypasses `VALID_TRANSITIONS` as an intentional internal recovery mechanism (per ADR 0005). The subsequent `mark_running()` call transitions QUEUED to RUNNING through normal validation. Terminal states (SUCCESS, CANCELLED) are intentionally excluded to prevent re-processing completed or cancelled jobs.

This handles two retry scenarios:
- Job stuck in RUNNING (task crashed mid-execution before any except block ran)
- Job already marked FAILED (except block ran, called `mark_failed`, then re-raised, and Celery retries because the exception is in `autoretry_for`)

### Deterministic errors

No code changes. The existing `except (TriageError, ValueError, RegexSafetyError)` block calls `mark_failed` and re-raises. Since these are not in `autoretry_for`, Celery won't retry them.

Other exceptions (e.g. `RuntimeError`) also call `mark_failed` and re-raise. Since they're not in `autoretry_for`, they also fail immediately without retry.

### Tests

1. **Transient error triggers retry**: Mock triage to raise `openai.APIConnectionError`. Verify the task has `autoretry_for` configured with the correct exceptions and `max_retries=3`.
2. **Deterministic error fails immediately**: Mock triage to raise `TriageError`. Verify the job is FAILED with no retry configuration triggered.
3. **Retry resets job state**: Create a job in FAILED state (simulating a previous transient failure). Call `process_job`. Verify job resets to QUEUED first, then proceeds normally to RUNNING and SUCCESS.

## Acceptance criteria

- [x] `autoretry_for=(APIConnectionError, RateLimitError, APITimeoutError)` on the task decorator with `retry_backoff=True, max_retries=3`
- [x] Deterministic errors (TriageError, ValueError, RegexSafetyError) are NOT retried
- [x] On retry, if `job.status in ("RUNNING", "FAILED")`, reset to QUEUED with `error_message=None` and `progress=0.0`
- [x] Tests: transient errors trigger retry config, deterministic errors fail immediately, retry resets job state, SUCCESS/CANCELLED jobs are not reset