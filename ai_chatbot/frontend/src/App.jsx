import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import "./App.css";
import "./DocsSidebar.css";
import { useAuth } from "./AuthContext";
import Login from "./Login";
import Signup from "./Signup";
import { Copy, Check, Send, Loader2, Paperclip, Trash2, X, FileText } from "lucide-react";
import { useState, useRef, useEffect } from "react";

const API_BASE = "http://127.0.0.1:8000";

function App() {
  const { token, role, logout } = useAuth();
  const [showSignup, setShowSignup] = useState(false);

  const [input, setInput] = useState("");
  const [messages, setMessages] = useState([]);
  const [isSending, setIsSending] = useState(false);
  const [copiedIndex, setCopiedIndex] = useState(null);

  const chatWrapperRef = useRef(null);
  const textareaRef = useRef(null);
  const fileInputRef = useRef(null);

  // ---------- Admin-only document management state ----------
  const [documents, setDocuments] = useState([]);
  const [isUploading, setIsUploading] = useState(false);
  const [previewDoc, setPreviewDoc] = useState(null);
  const [previewChunks, setPreviewChunks] = useState([]);
  const [isLoadingPreview, setIsLoadingPreview] = useState(false);

  useEffect(() => {
    if (textareaRef.current) {
      const ta = textareaRef.current;
      ta.style.height = "auto";
      const newHeight = Math.min(ta.scrollHeight, 200);
      ta.style.height = newHeight + "px";
      ta.style.overflowY = ta.scrollHeight > 200 ? "auto" : "hidden";
    }
    if (textareaRef.current && input === "") {
      textareaRef.current.style.height = "24px";
    }
  }, [input]);

  useEffect(() => {
    if (chatWrapperRef.current) {
      chatWrapperRef.current.scrollTop = chatWrapperRef.current.scrollHeight;
    }
  }, [messages]);

  // Fetch the document list once, only for admins, once logged in
  useEffect(() => {
    if (token && role === "admin") {
      fetchDocuments();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, role]);

  async function fetchDocuments() {
    try {
      const res = await fetch(`${API_BASE}/api/documents`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await res.json();
      setDocuments(data.documents || []);
    } catch (err) {
      console.error("Failed to load documents", err);
    }
  }

  async function handleUpload(e) {
    const file = e.target.files[0];
    if (!file) return;

    setIsUploading(true);
    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await fetch(`${API_BASE}/api/documents/upload`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body: formData,
      });
      const data = await res.json();
      if (res.ok && !data.error) {
        await fetchDocuments();
      }
    } catch (err) {
      console.error("Upload failed", err);
    } finally {
      setIsUploading(false);
      e.target.value = "";
    }
  }

  async function handleDeleteDoc(docId, e) {
    e.stopPropagation(); // don't trigger preview when clicking delete
    if (!window.confirm("Delete this document and all its chunks?")) return;

    try {
      const res = await fetch(`${API_BASE}/api/documents/${docId}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await res.json();
      if (res.ok && !data.error) {
        setDocuments((prev) => prev.filter((d) => d.id !== docId));
      }
    } catch (err) {
      console.error("Delete failed", err);
    }
  }

  async function handlePreviewDoc(doc) {
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
      console.error("Failed to load chunk preview", err);
    } finally {
      setIsLoadingPreview(false);
    }
  }

  function copyToClipboard(text, index) {
    navigator.clipboard.writeText(text).then(() => {
      setCopiedIndex(index);
      setTimeout(() => setCopiedIndex(null), 1500);
    });
  }

  async function sendMessage() {
    const question = input.trim();
    if (!question || isSending) return;

    setIsSending(true);

    setMessages((prev) => [
      ...prev,
      { role: "user", content: question },
      { role: "assistant", content: "" },
    ]);

    setInput("");

    try {
      const response = await fetch(`${API_BASE}/api/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ question: question }),
      });

      if (!response.ok) {
        let errorText = "⚠️ Something went wrong. Please try again.";
        if (response.status === 429) {
          errorText = "⚠️ Rate limit reached. Please wait a moment and try again.";
        }

        setMessages((prev) => {
          const updated = [...prev];
          updated[updated.length - 1] = {
            ...updated[updated.length - 1],
            content: errorText,
            isError: true,
          };
          return updated;
        });
        return;
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value);

        setMessages((prev) => {
          const updated = [...prev];
          updated[updated.length - 1] = {
            ...updated[updated.length - 1],
            content: updated[updated.length - 1].content + chunk,
          };
          return updated;
        });
      }
    } catch (err) {
      console.error("Fetch Error:", err);
      setMessages((prev) => {
        const updated = [...prev];
        updated[updated.length - 1] = {
          ...updated[updated.length - 1],
          content: "⚠️ Something went wrong. Please try again.",
          isError: true,
        };
        return updated;
      });
    } finally {
      setIsSending(false);
    }
  }

  // ---------- Auth gating (after all hooks, per Rules of Hooks) ----------
  if (!token) {
    return showSignup
      ? <Signup onSwitchToLogin={() => setShowSignup(false)} />
      : <Login onSwitchToSignup={() => setShowSignup(true)} />;
  }

  return (
    <div className="app">
      {/* ---------- Sidebar ---------- */}

      <div className="sidebar">
        <div className="logo">Exam AI</div>

        <div className="sidebar-content">
          {role === "admin" && (
            <div className="docs-section">
              <div className="docs-section-title">Documents</div>
              {documents.length === 0 ? (
                <div className="docs-empty">No documents uploaded yet.</div>
              ) : (
                documents.map((doc) => (
                  <div
                    key={doc.id}
                    className="doc-sidebar-row"
                    onClick={() => handlePreviewDoc(doc)}
                  >
                    <div className="doc-sidebar-icon">
                      <FileText size={15} />
                    </div>
                    <div className="doc-sidebar-info">
                      <span className="doc-sidebar-name">{doc.filename}</span>
                      <span className="doc-sidebar-meta">{doc.chunk_count} chunks</span>
                    </div>
                    <button
                      className="doc-sidebar-delete"
                      onClick={(e) => handleDeleteDoc(doc.id, e)}
                      title="Delete"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                ))
              )}
            </div>
          )}

          {/* Chat history placeholder — lower half of sidebar */}
        </div>

        <div className="sidebar-footer">
          <div className="user-info">
            <span className="user-role">{role}</span>
            <button onClick={logout} className="logout-btn">Log out</button>
          </div>
        </div>
      </div>

      {/* ---------- Main Chat Area ---------- */}

      <div className="main">
        <h1>Exam AI Chatbot</h1>

        <div className="chat-wrapper" ref={chatWrapperRef}>
          <div className="content">
            <div className="chat-box">
              {messages.map((msg, index) => (
                <div
                  key={index}
                  className={
                    msg.role === "user"
                      ? "user-message-wrapper"
                      : "assistant-message-wrapper"
                  }
                >
                  <div
                    className={
                      msg.role === "user"
                        ? "user-message"
                        : msg.isError
                        ? "assistant-message error"
                        : "assistant-message"
                    }
                  >
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {msg.content}
                    </ReactMarkdown>
                  </div>

                  <button
                    className="copy-btn"
                    onClick={() => copyToClipboard(msg.content, index)}
                    title="Copy"
                  >
                    {copiedIndex === index ? <Check size={16} /> : <Copy size={16} />}
                  </button>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* ---------- Input ---------- */}

        <div className="footer">
          <div className="content">
            <div className="input-area">
              {role === "admin" && (
                <>
                  <button
                    className="attach-btn"
                    onClick={() => fileInputRef.current.click()}
                    disabled={isUploading}
                    title="Upload document"
                  >
                    {isUploading ? <Loader2 size={18} className="spin" /> : <Paperclip size={18} />}
                  </button>
                  <input
                    type="file"
                    accept=".pdf,.md"
                    ref={fileInputRef}
                    onChange={handleUpload}
                    hidden
                  />
                </>
              )}

              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="Message Exam AI..."
                rows={1}
                ref={textareaRef}
                disabled={isSending}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    sendMessage();
                  }
                }}
              />

              <button onClick={sendMessage} disabled={isSending} className="send-btn">
                {isSending ? <Loader2 size={20} className="spin" /> : <Send size={20} />}
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* ---------- Chunk preview modal (admin only) ---------- */}

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
              <div className="admin-loading">
                <Loader2 className="spin" size={20} /> Loading chunks...
              </div>
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

export default App;