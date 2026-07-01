import { useState, useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import { listUploads, getUpload, uploadFile, startJob } from "../api/client";

export default function HeroPage() {
  const [uploads, setUploads] = useState([]);
  const [selectedUpload, setSelectedUpload] = useState(null);
  const [previewCache, setPreviewCache] = useState({});
  const [isUploading, setIsUploading] = useState(false);
  const [prompt, setPrompt] = useState("");
  const [isStarting, setIsStarting] = useState(false);
  const [toast, setToast] = useState(null);
  const [error, setError] = useState(null);
  const fileInputRef = useRef(null);

  useEffect(() => {
    listUploads().then(setUploads).catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(null), 3000);
    return () => clearTimeout(timer);
  }, [toast]);

  const handleFileSelect = async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    const ext = file.name.split(".").pop().toLowerCase();
    if (!["csv", "xlsx", "xls"].includes(ext)) {
      setError("Only CSV, XLSX, and XLS files are allowed.");
      return;
    }

    setIsUploading(true);
    setError(null);
    try {
      const data = await uploadFile(file);
      const upload = { ...data, id: data.upload_id };
      setSelectedUpload(upload);
      setPreviewCache((prev) => ({ ...prev, [upload.id]: data.preview }));
      const all = await listUploads();
      setUploads(all);
    } catch (err) {
      setError(err.message);
    } finally {
      setIsUploading(false);
    }
  };

  const handleSelectUpload = async (upload) => {
    setSelectedUpload(upload);
    setError(null);

    if (!previewCache[upload.id]) {
      try {
        const data = await getUpload(upload.id);
        setPreviewCache((prev) => ({ ...prev, [upload.id]: data.preview }));
        setSelectedUpload((prev) => ({ ...prev, column_names: data.column_names }));
      } catch (err) {
        setError(err.message);
      }
    }
  };

  const handleStart = async () => {
    if (!selectedUpload || !prompt.trim()) return;
    setIsStarting(true);
    setError(null);
    try {
      const uploadId = selectedUpload.upload_id || selectedUpload.id;
      await startJob(uploadId, prompt.trim());
      setToast("Job started");
      setPrompt("");
    } catch (err) {
      setError(err.message);
    } finally {
      setIsStarting(false);
    }
  };

  const previewRows = selectedUpload ? previewCache[selectedUpload.id] || [] : [];
  const fileName = selectedUpload ? selectedUpload.file_path.split("/").pop() : "";

  return (
    <div className="min-h-screen flex flex-col md:flex-row">
      {/* Toast */}
      {toast && (
        <div className="fixed top-4 right-4 bg-ink text-white px-4 py-2 rounded shadow z-50">
          {toast}
        </div>
      )}

      {/* Sidebar */}
      <aside className="w-full md:w-64 border-r border-surface bg-canvas p-4 shrink-0">
        <h1 className="font-semibold text-ink text-[30px] mb-3 border-b">Rhombus AI</h1>
        <h2 className="font-semibold text-ink mb-3">Uploaded Files</h2>
        <ul className="space-y-2">
          {uploads.map((u) => (
            <li key={u.id}>
              <button
                onClick={() => handleSelectUpload(u)}
                className={`w-full text-left px-3 py-2 rounded text-sm transition-colors ${
                  selectedUpload?.id === u.id
                    ? "bg-ink text-white"
                    : "hover:bg-surface text-muted"
                }`}
                title={u.file_path.split("/").pop()}
              >
                {u.file_path.split("/").pop().slice(0,5)+"..."}
              </button>
            </li>
          ))}
          {uploads.length === 0 && (
            <li className="text-sm text-muted">No uploads yet.</li>
          )}
        </ul>
      </aside>

      {/* Main */}
      <main className="flex-1 p-6">
        <div className="max-w-3xl mx-auto">
          <div className="flex items-center justify-end mb-6">
            <Link to="/jobs" className="text-ink text-sm rounded-xl btn-primary p-2 bg-blue-400 hover:bg-blue-500">
              Go to Jobs
            </Link>
          </div>

          {error && (
            <div className="mb-4 p-3 bg-canvas text-ink rounded border-l-4 border-ink text-sm">
              {error}
            </div>
          )}

          {/* Upload area or preview */}
          {!selectedUpload ? (
            <div
              onClick={() => fileInputRef.current?.click()}
              className="border-2 border-dashed border-surface rounded-lg p-8 text-center cursor-pointer hover:bg-canvas transition-colors"
            >
              <p className="text-muted">
                {isUploading ? "Uploading..." : "Click to select a CSV/XLSX/XLS file"}
              </p>
              <input
                ref={fileInputRef}
                type="file"
                accept=".csv,.xlsx,.xls"
                className="hidden"
                onChange={handleFileSelect}
              />
            </div>
          ) : (
            <div className="mt-2">
              <div className="flex items-center justify-between mb-2">
                <h3 className="font-semibold text-ink">Preview: {fileName.slice(0,5)}...</h3>
                <button
                  onClick={() => {
                    setSelectedUpload(null);
                    setError(null);
                  }}
                  className="text-sm text-ink hover:underline"
                >
                  Upload another file
                </button>
              </div>
              {selectedUpload.column_names && selectedUpload.column_names.length > 0 ? (
                <div className="overflow-x-auto border border-surface rounded">
                  <table className="min-w-full text-sm text-left">
                    <thead className="bg-surface text-muted">
                      <tr>
                        {selectedUpload.column_names.map((col) => (
                          <th key={col} className="px-3 py-2 font-medium border-b">
                            {col}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {previewRows.length > 0 ? (
                        previewRows.slice(0, 5).map((row, i) => (
                          <tr key={i} className="border-b border-surface last:border-b-0">
                            {selectedUpload.column_names.map((col) => (
                              <td key={col} className="px-3 py-2">
                                {row[col] != null ? String(row[col]) : ""}
                              </td>
                            ))}
                          </tr>
                        ))
                      ) : (
                        <tr>
                          <td
                            colSpan={selectedUpload.column_names.length}
                            className="px-3 py-2 text-muted italic"
                          >
                            Row preview available after upload
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="text-muted italic">No columns available.</p>
              )}
            </div>
          )}

          {/* Prompt */}
          <div className="mt-6">
            <label htmlFor="prompt" className="block text-sm font-medium text-muted mb-1">
              Natural language prompt
            </label>
            <textarea
              id="prompt"
              rows={4}
              className="w-full border border-surface rounded-lg p-3 text-sm focus:outline-none focus:ring-2 focus:ring-ink disabled:bg-surface disabled:text-muted/50"
              placeholder="Describe your data transformation..."
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              disabled={!selectedUpload}
            />
            <button
              onClick={handleStart}
              disabled={!selectedUpload || !prompt.trim() || isStarting}
              className="mt-3 px-4 py-2 bg-ink text-white rounded hover:bg-muted disabled:bg-surface disabled:text-muted disabled:cursor-not-allowed text-sm font-medium"
            >
              {isStarting ? "Starting..." : "Start Job"}
            </button>
          </div>
        </div>
      </main>
    </div>
  );
}
