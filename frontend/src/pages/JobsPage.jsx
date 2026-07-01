import { useState, useEffect, useCallback } from "react";
import { useNavigate, Link } from "react-router-dom";
import { listJobs, getJobStatus, cancelJob } from "../api/client";

const STATUS_COLORS = {
  QUEUED: "bg-yellow-100 text-yellow-800",
  RUNNING: "bg-blue-100 text-blue-800",
  SUCCESS: "bg-green-100 text-green-800",
  FAILED: "bg-red-100 text-red-800",
  CANCELLED: "bg-gray-100 text-gray-600",
};

function fileNameFromPath(path) {
  return path?.split("/").pop() || "Unknown";
}

function formatDate(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleString();
}

function promptSnippet(prompt) {
  if (!prompt) return "";
  return prompt.length > 50 ? prompt.slice(0, 50) + "…" : prompt;
}

export default function JobsPage() {
  const [jobs, setJobs] = useState([]);
  const [error, setError] = useState(null);
  const [cancellingId, setCancellingId] = useState(null);
  const navigate = useNavigate();

  const fetchJobs = useCallback(async () => {
    try {
      const data = await listJobs();
      setJobs(data);
      setError(null);
    } catch (err) {
      setError(err.message);
    }
  }, []);

  useEffect(() => {
    fetchJobs();
  }, [fetchJobs]);

  // Poll running/queued jobs every 1s
  useEffect(() => {
    const activeIds = jobs
      .filter((j) => j.status === "RUNNING" || j.status === "QUEUED")
      .map((j) => j.id);

    if (activeIds.length === 0) return;

    const poll = async () => {
      const updates = await Promise.all(
        activeIds.map(async (id) => {
          try {
            return await getJobStatus(id);
          } catch {
            return null;
          }
        })
      );

      setJobs((prev) => {
        const map = new Map(prev.map((j) => [j.id, j]));
        for (const u of updates) {
          if (!u) continue;
          const existing = map.get(u.id);
          if (existing) {
            map.set(u.id, { ...existing, status: u.status, progress: u.progress, error_message: u.error_message });
          }
        }
        return Array.from(map.values());
      });
    };

    const interval = setInterval(poll, 1000);
    return () => clearInterval(interval);
  }, [jobs]);

  const handleRowClick = (job) => {
    if (job.status === "RUNNING" || job.status === "QUEUED") return;
    navigate(`/jobs/${job.id}`);
  };

  const handleCancel = async (e, id) => {
    e.stopPropagation();
    setCancellingId(id);
    try {
      await cancelJob(id);
      setJobs((prev) =>
        prev.map((j) =>
          j.id === id
            ? { ...j, status: "CANCELLED", error_message: "Cancelled by user" }
            : j
        )
      );
    } catch (err) {
      setError(err.message);
    } finally {
      setCancellingId(null);
    }
  };

  const isActive = (status) => status === "RUNNING" || status === "QUEUED";

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-5xl mx-auto px-4 py-8">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-bold text-gray-900">Job Logs</h1>
          <Link to="/" className="text-purple-600 hover:underline text-sm">
            Back to Home
          </Link>
        </div>

        {error && (
          <div className="mb-4 p-3 bg-red-50 text-red-700 rounded border border-red-200 text-sm">
            {error}
          </div>
        )}

        {jobs.length === 0 ? (
          <p className="text-gray-500 text-sm">No jobs yet.</p>
        ) : (
          <div className="bg-white rounded-lg border shadow-sm overflow-x-auto">
            <table className="min-w-full text-sm text-left">
              <thead className="bg-gray-100 text-gray-700">
                <tr>
                  <th className="px-4 py-3 font-medium">Filename</th>
                  <th className="px-4 py-3 font-medium">Status</th>
                  <th className="px-4 py-3 font-medium">Progress</th>
                  <th className="px-4 py-3 font-medium">Prompt</th>
                  <th className="px-4 py-3 font-medium">Created</th>
                  <th className="px-4 py-3 font-medium"></th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((job) => (
                  <tr
                    key={job.id}
                    onClick={() => handleRowClick(job)}
                    className={`border-b last:border-b-0 ${
                      job.status === "RUNNING" || job.status === "QUEUED"
                        ? ""
                        : "cursor-pointer hover:bg-gray-50"
                    }`}
                  >
                    <td className="px-4 py-3">
                      {fileNameFromPath(job.file_path)}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-block px-2 py-1 rounded text-xs font-medium ${
                          STATUS_COLORS[job.status] || "bg-gray-100 text-gray-800"
                        }`}
                      >
                        {job.status}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <div className="w-24 h-2 bg-gray-200 rounded overflow-hidden">
                        <div
                          className="h-full bg-purple-600 transition-all duration-300"
                          style={{ width: `${job.progress}%` }}
                        />
                      </div>
                      <span className="text-xs text-gray-500">{job.progress}%</span>
                    </td>
                    <td className="px-4 py-3 max-w-xs truncate" title={job.nl_prompt}>
                      {promptSnippet(job.nl_prompt)}
                    </td>
                    <td className="px-4 py-3 text-gray-500">
                      {formatDate(job.created_at)}
                    </td>
                    <td className="px-4 py-3">
                      {isActive(job.status) && (
                        <button
                          onClick={(e) => handleCancel(e, job.id)}
                          disabled={cancellingId === job.id}
                          className="text-xs px-2 py-1 border rounded text-red-600 border-red-200 hover:bg-red-50 disabled:opacity-50"
                        >
                          {cancellingId === job.id ? "Cancelling…" : "Cancel"}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
