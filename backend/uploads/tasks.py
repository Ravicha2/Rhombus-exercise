import logging
from celery import shared_task
from uploads.models import DatasetUpload
from uploads.services import NormalizationService

logger = logging.getLogger(__name__)


@shared_task(bind=True)
def normalize_upload(self, dataset_id: int) -> None:
    """Celery task: normalize an uploaded file to Parquet."""
    try:
        dataset = DatasetUpload.objects.get(id=dataset_id)
    except DatasetUpload.DoesNotExist:
        logger.error("DatasetUpload %s not found", dataset_id)
        raise

    dataset.mark_converting()

    try:
        parquet_path, column_names = NormalizationService.normalize(dataset)
        dataset.mark_ready(parquet_file_path=parquet_path, column_names=column_names)
    except Exception as exc:
        dataset.mark_failed(error_message=str(exc))
        raise