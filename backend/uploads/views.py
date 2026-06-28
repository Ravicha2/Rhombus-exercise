import os
import uuid
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from uploads.models import DatasetUpload


class UploadView(APIView):
    def post(self, request):
        uploaded_file = request.FILES.get('file')
        if not uploaded_file:
            return Response({"error": "No file provided."}, status=status.HTTP_400_BAD_REQUEST)

        ext = os.path.splitext(uploaded_file.name)[1].lower()
        if ext not in ['.csv', '.xlsx', '.xls']:
            return Response({"error": f"Unsupported file extension: {ext}. Permitted extensions are .csv, .xlsx, .xls"}, status=status.HTTP_400_BAD_REQUEST)

        storage_dir = os.path.join(settings.BASE_DIR, 'uploads_storage')
        if not os.path.exists(storage_dir):
            os.makedirs(storage_dir, exist_ok=True)

        filename = f"{uuid.uuid4().hex}_{uploaded_file.name}"
        save_path = os.path.join(storage_dir, filename)

        # Stream chunks directly to shared volume
        with open(save_path, 'wb+') as destination:
            for chunk in uploaded_file.chunks():
                destination.write(chunk)

        rel_path = f"uploads_storage/{filename}"
        dataset = DatasetUpload.objects.create(file_path=rel_path)

        return Response({
            "upload_id": dataset.id,
            "file_path": dataset.file_path,
            "uploaded_at": dataset.uploaded_at
        }, status=status.HTTP_201_CREATED)
