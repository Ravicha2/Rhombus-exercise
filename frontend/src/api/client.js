const API_BASE = "/api";

async function handleResponse(response) {
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const error = (data && data.error) || `HTTP ${response.status}`;
    throw new Error(error);
  }
  return data;
}

export async function uploadFile(file) {
  const formData = new FormData();
  formData.append("file", file);
  const response = await fetch(`${API_BASE}/uploads/`, {
    method: "POST",
    body: formData,
  });
  return handleResponse(response);
}

export async function getUpload(id) {
  const response = await fetch(`${API_BASE}/uploads/${id}/`);
  return handleResponse(response);
}

export async function listUploads() {
  const response = await fetch(`${API_BASE}/uploads/`);
  return handleResponse(response);
}

export async function startJob(uploadId, nlPrompt) {
  const response = await fetch(`${API_BASE}/jobs/start/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ upload_id: uploadId, nl_prompt: nlPrompt }),
  });
  return handleResponse(response);
}

export async function listJobs() {
  const response = await fetch(`${API_BASE}/jobs/`);
  return handleResponse(response);
}

export async function getJobStatus(id) {
  const response = await fetch(`${API_BASE}/jobs/${id}/status/`);
  return handleResponse(response);
}

export async function getJobResults(id, page = 1, pageSize = 50) {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  const response = await fetch(`${API_BASE}/jobs/${id}/results/?${params}`);
  return handleResponse(response);
}

export async function cancelJob(id) {
  const response = await fetch(`${API_BASE}/jobs/${id}/cancel/`, {
    method: "POST",
  });
  return handleResponse(response);
}
