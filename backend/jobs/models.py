from django.db import models
from uploads.models import DatasetUpload


class ProcessingJob(models.Model):
    STATUS_CHOICES = [
        ("QUEUED", "Queued"),
        ("RUNNING", "Running"),
        ("SUCCESS", "Success"),
        ("FAILED", "Failed"),
    ]

    dataset = models.ForeignKey(DatasetUpload, on_delete=models.CASCADE, related_name="jobs", help_text="The uploaded dataset being processed")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="QUEUED", help_text="Current processing state")
    progress = models.FloatField(default=0.0, help_text="Task progress percentage (0.0 to 100.0)")
    task_id = models.CharField(max_length=255, blank=True, null=True, help_text="Celery async task identifier")
    error_message = models.TextField(blank=True, null=True, help_text="Failure explanation if status is FAILED")
    output_file_path = models.CharField(max_length=1024, blank=True, null=True, help_text="Relative path to full processed output file")
    preview_file_path = models.CharField(max_length=1024, blank=True, null=True, help_text="Relative path to 1000-row preview JSON file")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"ProcessingJob {self.id} ({self.status}) - Progress: {self.progress}%"
