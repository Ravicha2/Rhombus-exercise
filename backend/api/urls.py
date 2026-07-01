from django.urls import path
from api.views import UploadView, JobStartView, JobStatusView

urlpatterns = [
    path("uploads/", UploadView.as_view(), name="upload-dataset"),
    path("jobs/start/", JobStartView.as_view(), name="job-start"),
    path("jobs/<int:id>/status/", JobStatusView.as_view(), name="job-status"),
]