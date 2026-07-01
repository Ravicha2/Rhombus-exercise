import { useState, useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import { listUploads, uploadFile, startJob } from "../api/client";

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

  const handleSelectUpload = (upload) => {
    setSelectedUpload(upload);
    setError(null);
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
        <div className="fixed top-4 right-4 bg-green-600 text-white px-4 py-2 rounded shadow z-50">
          {toast}
        </div>
      )}

      {/* Sidebar */}
      <aside className="w-full md:w-64 border-r bg-gray-50 p-4 shrink-0">
        <h2 className="font-semibold text-gray-800 mb-3">Uploaded Files</h2>
        <ul className="space-y-2">
          {uploads.map((u) => (
            <li key={u.id}>
              <button
                onClick={() => handleSelectUpload(u)}
                className={`w-full text-left px-3 py-2 rounded text-sm truncate ${
                  selectedUpload?.id === u.id
                    ? "bg-purple-100 text-purple-800"
                    : "hover:bg-gray-100 text-gray-700"
                }`}
                title={u.file_path.split("/").pop()}
              >
                {u.file_path.split("/").pop()}
              </button>
            </li>
          ))}
          {uploads.length === 0 && (
            <li className="text-sm text-gray-500">No uploads yet.</li>
          )}
        </ul>
      </aside>

      {/* Main */}
      <main className="flex-1 p-6">
        <div className="max-w-3xl mx-auto">
          <div className="flex items-center justify-between mb-6">
            <h1 className="text-2xl font-bold text-gray-900">Rhombus</h1>
            <Link to="/jobs" className="text-purple-600 hover:underline text-sm">
              Go to Jobs
            </Link>
          </div>

          {error && (
            <div className="mb-4 p-3 bg-red-50 text-red-700 rounded border border-red-200 text-sm">
              {error}
            </div>
          )}

          {/* Upload area or preview */}
          {!selectedUpload ? (
            <div
              onClick={() => fileInputRef.current?.click()}
              className="border-2 border-dashed border-gray-300 rounded-lg p-8 text-center cursor-pointer hover:bg-gray-50 transition-colors"
            >
              <p className="text-gray-600">
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
                <h3 className="font-semibold text-gray-800">Preview: {fileName}</h3>
                <button
                  onClick={() => {
                    setSelectedUpload(null);
                    setError(null);
                  }}
                  className="text-sm text-purple-600 hover:underline"
                >
                  Upload another file
                </button>
              </div>
              {selectedUpload.column_names && selectedUpload.column_names.length > 0 ? (
                <div className="overflow-x-auto border rounded">
                  <table className="min-w-full text-sm text-left">
                    <thead className="bg-gray-100 text-gray-700">
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
                        previewRows.map((row, i) => (
                          <tr key={i} className="border-b last:border-b-0">
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
                            className="px-3 py-2 text-gray-500 italic"
                          >
                            Row preview available after upload
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="text-gray-500 italic">No columns available.</p>
              )}
            </div>
          )}

          {/* Prompt */}
          <div className="mt-6">
            <label htmlFor="prompt" className="block text-sm font-medium text-gray-700 mb-1">
              Natural language prompt
            </label>
            <textarea
              id="prompt"
              rows={4}
              className="w-full border rounded-lg p-3 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500 disabled:bg-gray-100 disabled:text-gray-400"
              placeholder="Describe your data transformation..."
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              disabled={!selectedUpload}
            />
            <button
              onClick={handleStart}
              disabled={!selectedUpload || !prompt.trim() || isStarting}
              className="mt-3 px-4 py-2 bg-purple-600 text-white rounded hover:bg-purple-700 disabled:bg-gray-300 disabled:cursor-not-allowed text-sm font-medium"
            >
              {isStarting ? "Starting..." : "Start Job"}
            </button>
          </div>
        </div>
      </main>
    </div>
  );
}
