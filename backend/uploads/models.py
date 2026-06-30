from django.db import models
from django.core.exceptions import ValidationError


class DatasetUpload(models.Model):
    STATUS_CHOICES = [
        ("UPLOADING", "UPLOADING"),
        ("CONVERTING", "CONVERTING"),
        ("READY", "READY"),
        ("FAILED", "FAILED"),
    ]

    VALID_TRANSITIONS = {
        "UPLOADING": ["CONVERTING", "FAILED"],
        "CONVERTING": ["READY", "FAILED"],
        "READY": [],
        "FAILED": [],
    }

    file_path = models.CharField(max_length=512, help_text="Relative path to the uploaded dataset on the shared filesystem")
    uploaded_at = models.DateTimeField(auto_now_add=True, help_text="Timestamp when the dataset upload was registered")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="UPLOADING")
    parquet_file_path = models.CharField(max_length=512, blank=True, null=True, help_text="Relative path to the normalized Parquet file")
    column_names = models.JSONField(blank=True, null=True, help_text="List of column names extracted from the dataset")
    error_message = models.TextField(blank=True, null=True, help_text="Error message if normalization failed")

    def _transition(self, new_status, **kwargs):
        if new_status not in self.VALID_TRANSITIONS.get(self.status, []):
            raise ValidationError(f"Cannot transition from {self.status} to {new_status}")
        self.status = new_status
        for field, value in kwargs.items():
            setattr(self, field, value)
        self.save()

    def mark_converting(self):
        self._transition("CONVERTING")

    def mark_ready(self, parquet_file_path, column_names):
        self._transition("READY", parquet_file_path=parquet_file_path, column_names=column_names)

    def mark_failed(self, error_message):
        self._transition("FAILED", error_message=error_message)

    def __str__(self):
        return f"DatasetUpload {self.id}: {self.file_path}"