from django.urls import path
from api.views import UploadView, JobStartView, JobStatusView, JobResultsView, JobCancelView, JobListView

urlpatterns = [
    path("uploads/", UploadView.as_view(), name="upload-dataset"),
    path("jobs/", JobListView.as_view(), name="job-list"),
    path("jobs/start/", JobStartView.as_view(), name="job-start"),
    path("jobs/<int:id>/status/", JobStatusView.as_view(), name="job-status"),
    path("jobs/<int:id>/results/", JobResultsView.as_view(), name="job-results"),
    path("jobs/<int:id>/cancel/", JobCancelView.as_view(), name="job-cancel"),
]