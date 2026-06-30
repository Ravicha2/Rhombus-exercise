# Retry, Cancellation, and API Design for ProcessingJob Lifecycle

Transient-failure retry with whole-task reset, cooperative cancellation with Celery revoke as safety net, and centralized API app for job endpoints.

## Status

accepted

## Considered Options

### Retry

- **`autoretry_for` on task decorator with whole-task reset**: Celery handles backoff and retry count. On retry, reset job to QUEUED so the normal flow re-marks it RUNNING. LLM cache makes re-running triage/regex cheap.
- **`self.retry()` per exception in task body**: More control over per-exception backoff, but more code for no clear benefit.
- **Per-call LLM retry within the task**: Wrap individual LLM calls in retry loops. Avoids re-running completed stages, but the LLM Redis cache already makes re-runs cheap. Refactor target for later if latency or cost matters.

### Cancellation

- **Cooperative cancellation (check DB status between stages) + `revoke(terminate=True)` safety net**: Task checks `job.status == CANCELLED` between triage, regex, spec building, and Spark stages. Returns cleanly (no exception). Revoke kills stuck tasks that can't check the flag.
- **Revoke-only (SIGTERM)**: Simple, but can leave partial Parquet files mid-write and the task's except blocks never run.
- **Redis flag for cancellation**: Faster than DB reads, but introduces a second source of truth for job state.

### API structure

- **Centralized `api` app**: All views (uploads + jobs) in one place. Service apps (`uploads`, `jobs`) keep models, services, and tasks. One file to find every endpoint.
- **Per-app views**: Each Django app owns its own views.py and urls.py. Follows Django convention but scatters endpoints across apps.

## Decision

**Retry**: `autoretry_for=(APIConnectionError, RateLimitError, APITimeoutError)` on the `@shared_task` decorator with `retry_backoff=True, max_retries=3`. At task start, if `job.status == "RUNNING"` (indicates a retry), reset to `QUEUED` with `error_message=None` and `progress=0.0`. Deterministic errors (`TriageError`, `ValueError`, `RegexSafetyError`) fail immediately, no retry.

**Cancellation**: Add `CANCELLED` as a terminal status (`QUEUED → CANCELLED`, `RUNNING → CANCELLED`). `mark_cancelled()` sets `error_message="Cancelled by user"`. Task checks `job.status == CANCELLED` from DB between stages and returns cleanly (no exception). Cancel endpoint sets status to CANCELLED first, then calls `revoke(task_id, terminate=True)` as a safety net.

**API**: Centralized `api` app with `views.py` and `urls.py` containing all endpoints. `UploadView` moves from `uploads` app. Manual dict responses, no DRF serializers. Error format: `{"error": "message"}`. No authentication.

**Endpoints**:
- `POST /api/jobs/start/` — takes `{upload_id, nl_prompt}`, validates upload exists/READY, stores `task_id` from `delay()` result, returns `{id, status}`.
- `GET /api/jobs/<int:id>/status/` — returns `{id, status, progress, error_message, created_at, updated_at}`.
- `GET /api/jobs/<int:id>/results/` — returns `{id, status, column_names, transformations, generated_regexes, rows, page, total_pages, total_rows}`. Only for SUCCESS jobs; returns 400 for other statuses.
- `POST /api/jobs/<int:id>/cancel/` — sets CANCELLED, revokes task, returns 200 with updated job status.

## Consequences

- Retry resets partial progress (transformations, generated_regexes are overwritten on re-run). Acceptable because LLM cache makes re-generation cheap and idempotent.
- The status reset bypasses `VALID_TRANSITIONS` as an internal recovery mechanism. Not exposed via API.
- `task_id` is stored at dispatch time in the start endpoint, not inside the task. Eliminates the NULL task_id race for cancellation.
- Partial Parquet files from cancelled jobs remain on disk. Harmless since no endpoint serves CANCELLED results. Add cleanup when disk usage matters.
- Per-call LLM retry is an explicit deferred item: add when LLM call latency or cost makes whole-task re-runs expensive.
- No uniqueness constraint on (dataset, nl_prompt). Frontend should debounce the submit button to avoid duplicate jobs.