import os
import uuid

from django.conf import settings
from django.http import JsonResponse
from django.views import View
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

from uploads.models import DatasetUpload
from uploads.tasks import normalize_upload


@method_decorator(csrf_exempt, name="dispatch")
class UploadView(View):
    def post(self, request):
        uploaded_file = request.FILES.get("file")
        if not uploaded_file:
            return JsonResponse({"error": "No file provided."}, status=400)

        ext = os.path.splitext(uploaded_file.name)[1].lower()
        if ext not in [".csv", ".xlsx", ".xls"]:
            return JsonResponse(
                {"error": f"Unsupported file extension: {ext}. Permitted extensions are .csv, .xlsx, .xls"},
                status=400,
            )

        storage_dir = os.path.join(settings.BASE_DIR, "uploads_storage")
        if not os.path.exists(storage_dir):
            os.makedirs(storage_dir, exist_ok=True)

        filename = f"{uuid.uuid4().hex}_{uploaded_file.name}"
        save_path = os.path.join(storage_dir, filename)

        with open(save_path, "wb+") as destination:
            for chunk in uploaded_file.chunks():
                destination.write(chunk)

        rel_path = f"uploads_storage/{filename}"
        dataset = DatasetUpload.objects.create(file_path=rel_path)
        normalize_upload.delay(dataset.id)

        return JsonResponse(
            {
                "upload_id": dataset.id,
                "file_path": dataset.file_path,
                "uploaded_at": dataset.uploaded_at,
            },
            status=201,
        )