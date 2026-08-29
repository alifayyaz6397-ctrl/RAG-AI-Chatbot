import { useState, useEffect } from "react";
import { Upload, Trash2, Eye, X, Loader2 } from "lucide-react";
import { useAuth } from "./AuthContext";
import "./AdminPanel.css";

const API_BASE = import.meta.env.VITE_API_URL;

function AdminPanel() {
  const { token, logout } = useAuth();

  const [documents, setDocuments] = useState([]);
  const [isLoadingList, setIsLoadingList] = useState(true);
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState("");

  const [previewDoc, setPreviewDoc] = useState(null); // { id, filename }
  const [previewChunks, setPreviewChunks] = useState([]);
  const [isLoadingPreview, setIsLoadingPreview] = useState(false);

  async function fetchDocuments() {
    setIsLoadingList(true);
    try {
      const res = await fetch(`${API_BASE}/api/documents`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await res.json();
      setDocuments(data.documents || []);
    } catch (err) {
      setError("Could not load documents.");
    } finally {
      setIsLoadingList(false);
    }
  }

  useEffect(() => {
    fetchDocuments();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleUpload(e) {
    const file = e.target.files[0];
    if (!file) return;

    setIsUploading(true);
    setError("");

    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await fetch(`${API_BASE}/api/documents/upload`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body: formData,
      });
      const data = await res.json();

      if (!res.ok || data.error) {
        setError(data.error || "Upload failed.");
        return;
      }

      await fetchDocuments();
    } catch (err) {
      setError("Could not reach the server.");
    } finally {
      setIsUploading(false);
      e.target.value = ""; // reset file input
    }
  }

  async function handleDelete(docId) {
    if (!window.confirm("Delete this document and all its chunks?")) return;

    try {
      const res = await fetch(`${API_BASE}/api/documents/${docId}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await res.json();

      if (!res.ok || data.error) {
        setError(data.error || "Delete failed.");
        return;
      }

      setDocuments((prev) => prev.filter((d) => d.id !== docId));
    } catch (err) {
      setError("Could not reach the server.");
    }
  }

  async function handlePreview(doc) {
    setPreviewDoc(doc);
    setIsLoadingPreview(true);
    setPreviewChunks([]);

    try {
      const res = await fetch(`${API_BASE}/api/documents/${doc.id}/chunks`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await res.json();
      setPreviewChunks(data.chunks || []);
    } catch (err) {
      setError("Could not load chunk preview.");
    } finally {
      setIsLoadingPreview(false);
    }
  }

  return (
    <div className="admin-page">
      <div className="admin-header">
        <h1>Knowledge Base Manager</h1>
        <button onClick={logout} className="logout-btn">Log out</button>
      </div>

      {error && <div className="auth-error admin-error">{error}</div>}

      <label className="upload-box">
        <Upload size={20} />
        <span>{isUploading ? "Uploading..." : "Upload a .pdf or .md document"}</span>
        <input
          type="file"
          accept=".pdf,.md"
          onChange={handleUpload}
          disabled={isUploading}
          hidden
        />
      </label>

      <div className="doc-list">
        {isLoadingList ? (
          <div className="admin-loading"><Loader2 className="spin" size={20} /> Loading documents...</div>
        ) : documents.length === 0 ? (
          <p className="admin-empty">No documents uploaded yet.</p>
        ) : (
          documents.map((doc) => (
            <div key={doc.id} className="doc-row">
              <div className="doc-info">
                <span className="doc-filename">{doc.filename}</span>
                <span className="doc-meta">
                  {doc.chunk_count} chunks · uploaded {new Date(doc.upload_date).toLocaleDateString()}
                </span>
              </div>
              <div className="doc-actions">
                <button onClick={() => handlePreview(doc)} title="Preview chunks">
                  <Eye size={18} />
                </button>
                <button onClick={() => handleDelete(doc.id)} title="Delete" className="danger">
                  <Trash2 size={18} />
                </button>
              </div>
            </div>
          ))
        )}
      </div>

      {previewDoc && (
        <div className="preview-overlay" onClick={() => setPreviewDoc(null)}>
          <div className="preview-modal" onClick={(e) => e.stopPropagation()}>
            <div className="preview-header">
              <h2>{previewDoc.filename}</h2>
              <button onClick={() => setPreviewDoc(null)} className="auth-close">
                <X size={20} />
              </button>
            </div>

            {isLoadingPreview ? (
              <div className="admin-loading"><Loader2 className="spin" size={20} /> Loading chunks...</div>
            ) : (
              <div className="chunk-list">
                {previewChunks.map((chunk) => (
                  <div key={chunk.chunk_index} className="chunk-item">
                    <span className="chunk-index">Chunk {chunk.chunk_index}</span>
                    <p>{chunk.content}</p>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default AdminPanel;