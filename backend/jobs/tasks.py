import logging
from celery import shared_task
from jobs.models import ProcessingJob
from jobs.services import LLMRegexService, RegexSafetyError, TriageService, TriageError

logger = logging.getLogger(__name__)


@shared_task(bind=True)
def process_job(self, job_id: int) -> None:
    """Orchestrate triage + regex generation for a ProcessingJob."""
    try:
        job = ProcessingJob.objects.get(id=job_id)
    except ProcessingJob.DoesNotExist:
        logger.error("ProcessingJob %s not found", job_id)
        raise

    job.mark_running(task_id=self.request.id)

    try:
        dataset = job.dataset
        column_names = dataset.column_names or []
        transformations = TriageService.triage(job.nl_prompt, column_names)
        job.transformations = transformations
        job.save()

        generated_regexes = []
        for t in transformations:
            regex = LLMRegexService.get_or_generate_regex(t["nl_pattern"])
            generated_regexes.append({"column": t["column"], "regex": regex})

        job.generated_regexes = generated_regexes
        job.mark_success()
    except (TriageError, ValueError, RegexSafetyError) as exc:
        job.mark_failed(error_message=str(exc))
        raise
    except Exception as exc:
        job.mark_failed(error_message=str(exc))
        raise