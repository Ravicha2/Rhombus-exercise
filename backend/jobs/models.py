from django.db import models
from uploads.models import DatasetUpload


class ProcessingJob(models.Model):
    STATUS_CHOICES = [
        ("QUEUED", "QUEUED"),
        ("RUNNING", "RUNNING"),
        ("SUCCESS", "SUCCESS"),
        ("FAILED", "FAILED"),
    ]

    dataset = models.ForeignKey(DatasetUpload, on_delete=models.CASCADE, related_name="jobs")
    task_id = models.CharField(max_length=255, blank=True, null=True)
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default="QUEUED")
    progress = models.FloatField(default=0.0)
    error_message = models.TextField(blank=True, null=True)
    output_file_path = models.CharField(max_length=1024, blank=True, null=True)
    preview_file_path = models.CharField(max_length=1024, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"ProcessingJob {self.id} ({self.status}) - Progress: {self.progress}%"
