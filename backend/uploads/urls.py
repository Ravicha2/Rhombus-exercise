from django.urls import path
from uploads.views import UploadView

urlpatterns = [
    path('', UploadView.as_view(), name='upload-dataset'),
]
