from django.db import models
from django.core.exceptions import ValidationError
from uploads.models import DatasetUpload


class ProcessingJob(models.Model):
    STATUS_CHOICES = [
        ("QUEUED", "QUEUED"),
        ("RUNNING", "RUNNING"),
        ("SUCCESS", "SUCCESS"),
        ("FAILED", "FAILED"),
        ("CANCELLED", "CANCELLED"),
    ]

    dataset = models.ForeignKey(DatasetUpload, on_delete=models.CASCADE, related_name="jobs")
    task_id = models.CharField(max_length=255, blank=True, null=True)
    nl_prompt = models.TextField(blank=True, default="", help_text="Natural language prompt describing the desired transformation")
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default="QUEUED")
    progress = models.FloatField(default=0.0)
    error_message = models.TextField(blank=True, null=True)
    transformations = models.JSONField(default=list, help_text="Triage output: list of {column, nl_pattern, replacement} dicts")
    generated_regexes = models.JSONField(blank=True, null=True, help_text="Per-column regexes: list of {column, regex} dicts")
    output_file_path = models.CharField(max_length=1024, blank=True, null=True)
    preview_file_path = models.CharField(max_length=1024, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    VALID_TRANSITIONS = {
        "QUEUED": ["RUNNING", "FAILED", "CANCELLED"],
        "RUNNING": ["SUCCESS", "FAILED", "CANCELLED"],
        "SUCCESS": [],
        "FAILED": [],
        "CANCELLED": [],
    }

    def _transition(self, new_status, **kwargs):
        if new_status not in self.VALID_TRANSITIONS.get(self.status, []):
            raise ValidationError(
                f"Cannot transition from {self.status} to {new_status}"
            )
        self.status = new_status
        for field, value in kwargs.items():
            setattr(self, field, value)
        self.save()

    def mark_running(self, task_id=None):
        kwargs = {}
        if task_id is not None:
            kwargs["task_id"] = task_id
        self._transition("RUNNING", **kwargs)

    def update_progress(self, progress):
        if self.status != "RUNNING":
            raise ValidationError("Can only update progress on a RUNNING job")
        self.progress = min(max(progress, 0.0), 100.0)
        self.save()

    def mark_success(self, output_file_path=None, preview_file_path=None):
        kwargs = {"progress": 100.0}
        if output_file_path is not None:
            kwargs["output_file_path"] = output_file_path
        if preview_file_path is not None:
            kwargs["preview_file_path"] = preview_file_path
        self._transition("SUCCESS", **kwargs)

    def mark_failed(self, error_message):
        self._transition("FAILED", error_message=error_message)

    def mark_cancelled(self):
        self._transition("CANCELLED", error_message="Cancelled by user")

    def __str__(self):
        return f"ProcessingJob {self.id} ({self.status}) - Progress: {self.progress}%"
