import json
import os
import uuid

from django.conf import settings
from django.http import JsonResponse
from django.views import View
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

from jobs.models import ProcessingJob
from jobs.tasks import process_job
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


@method_decorator(csrf_exempt, name="dispatch")
class JobStartView(View):
    def post(self, request):
        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"error": "Invalid JSON body."}, status=400)

        upload_id = body.get("upload_id")
        nl_prompt = body.get("nl_prompt")

        if upload_id is None:
            return JsonResponse({"error": "upload_id is required."}, status=400)
        if not nl_prompt:
            return JsonResponse({"error": "nl_prompt is required and must be non-empty."}, status=400)

        try:
            upload = DatasetUpload.objects.get(id=upload_id)
        except DatasetUpload.DoesNotExist:
            return JsonResponse({"error": f"Upload {upload_id} not found."}, status=404)

        if upload.status != "READY":
            return JsonResponse(
                {"error": f"Upload is {upload.status}, not READY."},
                status=400,
            )

        job = ProcessingJob.objects.create(
            dataset=upload,
            nl_prompt=nl_prompt,
        )
        result = process_job.delay(job.id)
        job.task_id = result.id
        job.save(update_fields=["task_id"])

        return JsonResponse({"id": job.id, "status": job.status}, status=201)


class JobStatusView(View):
    def get(self, request, id):
        try:
            job = ProcessingJob.objects.get(id=id)
        except ProcessingJob.DoesNotExist:
            return JsonResponse({"error": f"Job {id} not found."}, status=404)

        return JsonResponse({
            "id": job.id,
            "status": job.status,
            "progress": job.progress,
            "error_message": job.error_message,
            "created_at": job.created_at.isoformat(),
            "updated_at": job.updated_at.isoformat(),
        })