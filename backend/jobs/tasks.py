import logging
from celery import shared_task
from openai import APIConnectionError, RateLimitError, APITimeoutError
from jobs.models import ProcessingJob
from jobs.services import (
    LLMRegexService,
    RegexSafetyError,
    SparkProcessingService,
    StorageService,
    TriageError,
    TriageService,
)

logger = logging.getLogger(__name__)


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
    if job.status in ("RUNNING", "FAILED"):
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