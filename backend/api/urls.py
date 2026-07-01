from django.urls import path
from api.views import UploadView, JobStartView

urlpatterns = [
    path("uploads/", UploadView.as_view(), name="upload-dataset"),
    path("jobs/start/", JobStartView.as_view(), name="job-start"),
]