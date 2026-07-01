import { useState, useEffect } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { getJobStatus, getJobResults } from "../api/client";

export default function JobDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [job, setJob] = useState(null);
  const [results, setResults] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  // Fetch job status on mount
  useEffect(() => {
    let cancelled = false;

    async function fetchStatus() {
      try {
        const data = await getJobStatus(id);
        if (cancelled) return;
        setJob(data);

        if (data.status === "RUNNING" || data.status === "QUEUED") {
          navigate("/jobs", { replace: true });
          return;
        }

        if (data.status === "SUCCESS") {
          const res = await getJobResults(id, 1);
          if (cancelled) return;
          setResults(res);
        }
      } catch (err) {
        if (!cancelled) setError(err.message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    fetchStatus();
    return () => {
      cancelled = true;
    };
  }, [id, navigate]);

  const goToPage = async (page) => {
    if (!results || page < 1 || page > results.total_pages) return;
    setLoading(true);
    try {
      const res = await getJobResults(id, page);
      setResults(res);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <p className="text-gray-500 text-sm">Loading…</p>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-5xl mx-auto px-4 py-8">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-bold text-gray-900">Job Detail</h1>
          <Link to="/jobs" className="text-purple-600 hover:underline text-sm">
            Back to Jobs
          </Link>
        </div>

        {error && (
          <div className="mb-4 p-3 bg-red-50 text-red-700 rounded border border-red-200 text-sm">
            {error}
          </div>
        )}

        {job?.status === "FAILED" && (
          <div className="mb-4 p-4 bg-red-50 text-red-800 rounded border border-red-200">
            <p className="font-medium text-sm mb-1">Job failed</p>
            <p className="text-sm">{job.error_message || "Unknown error"}</p>
          </div>
        )}

        {job?.status === "CANCELLED" && (
          <div className="mb-4 p-4 bg-gray-50 text-gray-600 rounded border border-gray-200 text-sm">
            Job cancelled
          </div>
        )}

        {job?.status === "SUCCESS" && results && (
          <>
            <div className="bg-white rounded-lg border shadow-sm overflow-x-auto">
              <table className="min-w-full text-sm text-left">
                <thead className="bg-gray-100 text-gray-700">
                  <tr>
                    {results.column_names?.map((col) => (
                      <th key={col} className="px-4 py-3 font-medium">
                        {col}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {results.rows?.map((row, i) => (
                    <tr key={i} className="border-b last:border-b-0">
                      {results.column_names?.map((col) => (
                        <td key={col} className="px-4 py-3">
                          {row[col] != null ? String(row[col]) : ""}
                        </td>
                      ))}
                    </tr>
                  ))}
                  {results.rows?.length === 0 && (
                    <tr>
                      <td
                        colSpan={results.column_names?.length || 1}
                        className="px-4 py-3 text-gray-500 italic"
                      >
                        No results
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            {results.total_pages > 1 && (
              <div className="flex items-center justify-between mt-4 text-sm">
                <p className="text-gray-500">
                  Page {results.page} of {results.total_pages} ({results.total_rows} rows)
                </p>
                <div className="flex gap-2">
                  <button
                    onClick={() => goToPage(results.page - 1)}
                    disabled={results.page <= 1}
                    className="px-3 py-1 border rounded text-gray-700 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    Previous
                  </button>
                  <button
                    onClick={() => goToPage(results.page + 1)}
                    disabled={results.page >= results.total_pages}
                    className="px-3 py-1 border rounded text-gray-700 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    Next
                  </button>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
