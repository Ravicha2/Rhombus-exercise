import logging
from celery import shared_task
from jobs.models import ProcessingJob
from jobs.services import LLMRegexService, RegexSafetyError

logger = logging.getLogger(__name__)


@shared_task(bind=True)
def generate_regex(self, job_id: int, natural_language_prompt: str) -> str:
    """Celery task: generate regex via LLM and update ProcessingJob lifecycle."""
    try:
        job = ProcessingJob.objects.get(id=job_id)
    except ProcessingJob.DoesNotExist:
        logger.error("ProcessingJob %s not found", job_id)
        raise

    job.mark_running(task_id=self.request.id)

    try:
        regex = LLMRegexService.get_or_generate_regex(natural_language_prompt)
        job.mark_success()
        return regex
    except (ValueError, RegexSafetyError) as exc:
        job.mark_failed(error_message=str(exc))
        raise
    except Exception as exc:
        job.mark_failed(error_message=str(exc))
        raise