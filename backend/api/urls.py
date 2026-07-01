from django.urls import path
from api.views import UploadView

urlpatterns = [
    path("uploads/", UploadView.as_view(), name="upload-dataset"),
]