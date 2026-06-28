from django.db import models


class DatasetUpload(models.Model):
    file_path = models.CharField(max_length=512, help_text="Relative path to the uploaded dataset on the shared filesystem")
    uploaded_at = models.DateTimeField(auto_now_add=True, help_text="Timestamp when the dataset upload was registered")

    def __str__(self):
        return f"DatasetUpload {self.id}: {self.file_path}"
