import { useState, useEffect, useCallback } from "react";
import { useNavigate, Link } from "react-router-dom";
import { listJobs, getJobStatus, cancelJob } from "../api/client";

const STATUS_COLORS = {
  QUEUED: "bg-canvas text-muted border border-surface",
  RUNNING: "bg-surface text-ink",
  SUCCESS: "bg-ink text-white",
  FAILED: "bg-muted text-white",
  CANCELLED: "bg-canvas text-muted border border-surface",
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
    <div className="min-h-screen bg-canvas">
      <div className="max-w-5xl mx-auto px-4 py-8">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-bold text-ink">Job Logs</h1>
          <Link to="/" className="text-ink text-sm rounded-xl btn-primary p-2 bg-blue-400 hover:bg-blue-500">
            Back to Home
          </Link>
        </div>

        {error && (
          <div className="mb-4 p-3 bg-canvas text-ink rounded border-l-4 border-ink text-sm">
            {error}
          </div>
        )}

        {jobs.length === 0 ? (
          <p className="text-muted text-sm">No jobs yet.</p>
        ) : (
          <div className="bg-white rounded-lg border border-surface shadow-sm overflow-x-auto">
            <table className="min-w-full text-sm text-left">
              <thead className="bg-surface text-muted">
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
                    className={`border-b border-surface last:border-b-0 ${
                      job.status === "RUNNING" || job.status === "QUEUED"
                        ? ""
                        : "cursor-pointer hover:bg-canvas"
                    }`}
                  >
                    <td className="px-4 py-3">
                      {fileNameFromPath(job.file_path)}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-block px-2 py-1 rounded text-xs font-medium ${
                          STATUS_COLORS[job.status] || "bg-surface text-ink"
                        }`}
                      >
                        {job.status}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <div className="w-24 h-2 bg-surface rounded overflow-hidden">
                        <div
                          className="h-full bg-ink transition-all duration-300"
                          style={{ width: `${job.progress}%` }}
                        />
                      </div>
                      <span className="text-xs text-muted">{job.progress}%</span>
                    </td>
                    <td className="px-4 py-3 max-w-xs truncate" title={job.nl_prompt}>
                      {promptSnippet(job.nl_prompt)}
                    </td>
                    <td className="px-4 py-3 text-muted">
                      {formatDate(job.created_at)}
                    </td>
                    <td className="px-4 py-3">
                      {isActive(job.status) && (
                        <button
                          onClick={(e) => handleCancel(e, job.id)}
                          disabled={cancellingId === job.id}
                          className="text-xs px-2 py-1 border rounded text-ink border-surface hover:bg-surface disabled:opacity-50"
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
