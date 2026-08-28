import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import "./App.css";
import "./DocsSidebar.css";
import { useAuth } from "./AuthContext";
import Login from "./Login";
import Signup from "./Signup";
import {
  Copy,
  Check,
  Send,
  Loader2,
  Paperclip,
  Trash2,
  X,
  FileText,
  MessageSquare,
  Search,
  ArrowLeft,
  ThumbsUp,
  ThumbsDown,
  Plus,
  Users,
  AlertTriangle,
  RefreshCw,
  Bot,
} from "lucide-react";
import { useState, useRef, useEffect } from "react";

const API_BASE = "http://127.0.0.1:8000";

function App() {
  // alert(localStorage.getItem("token"))
  const { token, role,username, logout } = useAuth();
  const [showSignup, setShowSignup] = useState(false);
  const [citationStats, setCitationStats] = useState([]);
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
  const [examMode, setExamMode] = useState(false);
  const [analyticMode, setAnalyticMode] = useState(false);
  const [fetchExams, setFetchExams] = useState([]);
  const [myConvo, setMyConvo] = useState([]);
  const [sessionId, setSessionId] = useState(null);
  const [sessionChat, setSessionChat] = useState([]);
  const [isNewSession, setIsNewSession] = useState(false);
  const [searchChat, setSearchChat] = useState([]);
  const [roleFilter, setRoleFilter] = useState("");
  const [modeFilter, setModeFilter] = useState("");
  const [escalatedFilter, setEscalatedFilter] = useState(null);
  const [userIdFilter, setUserIdFilter] = useState(null);
  const [adminPanelView, setAdminPanelView] = useState(null); // null | "chats" | "documents" — drives which center modal is open
  const [examListOpen, setExamListOpen] = useState(false);
  const [examDetailOpen, setExamDetailOpen] = useState(false);
  const [selectedExam, setSelectedExam] = useState(null);
  const [isLoadingExamDetail, setIsLoadingExamDetail] = useState(false);
  const [selectedChatDetail, setSelectedChatDetail] = useState(null);
  const [currentChatTitle, setCurrentChatTitle] = useState("New Chat");
  const [suggestions, setSuggestion] = useState([]);

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
      fetchChunkCount();
    } else if (token && role === "instructor") {
      fetchInstructorExams();
    }
    getMyConversation();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, role]);

  useEffect(() => {
    if (!token || role !== "student") return;
    fetchExamMode();

    const intervalId = setInterval(() => {
      fetchExamMode();
    }, 30000);

    return () => clearInterval(intervalId);
  }, [token, role]);

  useEffect(() => {
    setSessionId(crypto.randomUUID());
    setIsNewSession(true);
    setMessages([]);
    setExamMode(false);
    setAnalyticMode(false);
    setFetchExams([]);
    setCurrentChatTitle("New Chat");
  }, [token]);

  // Fetch latest client chats whenever the admin opens the Client Chats modal
  // (adminSearchChat() reads current filter state, so empty filters -> latest chats).
  useEffect(() => {
    if (role === "admin" && adminPanelView === "chats") {
      adminSearchChat();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [role, adminPanelView]);

  // Fetch the sample/suggestion questions for the current role + mode combo,
  // so they're ready the moment an empty chat (New Chat / login) is shown.
  useEffect(() => {
    if (token && role) {
      suggestionQns();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, role, analyticMode, examMode]);

  async function suggestionQns() {
    // Your suggestion_qns table folds instructor-analysis and student-exam-mode
    // questions into the same `role` column ('analysis' / 'exam') rather than
    // a separate mode column, so map the current role+mode combo to that value.
    let effectiveRole = role;
    if (role === "instructor" && analyticMode) effectiveRole = "analysis";
    if (role === "student" && examMode) effectiveRole = "exam";

    try {
      const res = await fetch(`${API_BASE}/api/suggestion_qns/${effectiveRole}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await res.json();
      setSuggestion(data.suggestions || []);
    } catch (err) {
      console.error("Failed to load suggestion questions", err);
    }
  }

  async function adminSearchChat() {
    const params = new URLSearchParams();
    if (roleFilter) params.append("role", roleFilter);
    if (modeFilter) params.append("mode", modeFilter);
    if (escalatedFilter) params.append("escalated", escalatedFilter);
    if (userIdFilter) params.append("user_id", userIdFilter);
    const res = await fetch(`${API_BASE}/api/admin/conversations?${params}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const data = await res.json();
    setSearchChat(data.conversations || []);
  }

  async function handleNewChat() {
    setMessages([]);
    setSessionId(crypto.randomUUID());
    setIsNewSession(true);
    setCurrentChatTitle("New Chat");
  }
  async function getMyConversation() {
    const res = await fetch(`${API_BASE}/api/conversations`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const data = await res.json();
    setMyConvo(data.session || []);
  }

  async function fetchExamMode() {
    const res = await fetch(`${API_BASE}/api/exam_mode`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const data = await res.json();
    setExamMode(data.exam_mode);
  }

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
  async function fetchInstructorExams() {
    try {
      // alert("fetchInstructorExams called");
      const res = await fetch(`${API_BASE}/api/instructor/exams`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await res.json();
      // alert("Response: " + JSON.stringify(data));
      setFetchExams(data.exams || []);
    } catch (err) {
      // alert("Error: " + err.message);
    }
  }

  async function fetchExamDetail(examId) {
    setIsLoadingExamDetail(true);
    setSelectedExam(null);
    try {
      const res = await fetch(`${API_BASE}/api/exam/${examId}/info`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await res.json();
      setSelectedExam(data.exam || data);
    } catch (err) {
      console.error("Failed to load exam info", err);
    } finally {
      setIsLoadingExamDetail(false);
    }
  }

  async function fetchChunkCount() {
    try {
      const res = await fetch(`${API_BASE}/api/documents/citation-stats`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await res.json();
      setCitationStats(data.chunk_stats || []);
      // console.log("Citation Stats:", data.chunk_stats);
      // console.log("Documents:", documents);
    } catch (err) {
      console.error("Failed to load document stats", err);
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

  async function rateMessage(index, convId, rating) {
    if (!convId) return;

    // Optimistic update so the button reflects the click immediately.
    setMessages((prev) => {
      const updated = [...prev];
      updated[index] = {
        ...updated[index],
        rating: updated[index].rating === rating ? null : rating, // click again to un-rate
      };
      return updated;
    });

    try {
      // TODO: swap in your real rating endpoint (path/method/body) once it exists.
      await fetch(`${API_BASE}/api/conversations/${convId}/rate`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ rating }),
      });
    } catch (err) {
      console.error("Failed to submit rating", err);
    }
  }

  async function readAnalytic(question) {
    try {
      const res = await fetch(`${API_BASE}/api/instructor/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ question, session_id: sessionId, isNewSession }),
      });
      setIsNewSession(false);

      if (!res.ok) {
        let errorText = "Something went wrong. Please try again.";
        if (res.status === 429) {
          errorText =
            "Rate limit reached. Please wait a moment and try again.";
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

      const data = await res.json();
      const summaryText =
        `${data.answer}\n\n` +
        `Intent: ${data.intent}\n\n` +
        `Confidence: ${(data.confidence * 100).toFixed(0)}%`;

      setMessages((prev) => {
        const updated = [...prev];
        updated[updated.length - 1] = {
          ...updated[updated.length - 1],
          content: summaryText,
        };
        return updated;
      });
    } catch (err) {
      console.error("Analytic fetch error:", err);
      setMessages((prev) => {
        const updated = [...prev];
        updated[updated.length - 1] = {
          ...updated[updated.length - 1],
          content: "Something went wrong. Please try again.",
          isError: true,
        };
        return updated;
      });
    } finally {
      setIsSending(false);
    }
  }

  async function historyChat(id) {
    try {
      setIsNewSession(false);
      const res = await fetch(`${API_BASE}/api/conversations/${id}`, {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });

      if (!res.ok) {
        throw new Error(`HTTP error: ${res.status}`);
      }

      const data = await res.json();

      console.log("History response:", data);

      const chat = data.chat || [];

      setSessionId(id);
      setSessionChat(chat);
      setCurrentChatTitle(
        myConvo.find((c) => c.session_id === id)?.title || "Chat",
      );

      setMessages(
        chat.flatMap((doc) => [
          {
            role: "user",
            content: doc.question || "",
          },
          {
            role: "assistant",
            content: doc.answer || "",
            convId: doc.id,
            rating: doc.rating || null,
          },
        ]),
      );
    } catch (err) {
      console.error("Failed to load conversation:", err);
    }
  }

  async function sendMessage(overrideQuestion) {
    const question = (overrideQuestion ?? input).trim();
    if (!question || isSending) return;

    setIsSending(true);

    setMessages((prev) => [
      ...prev,
      { role: "user", content: question },
      { role: "assistant", content: "" },
    ]);

    setInput("");

    try {
      let url = `chat`;
      if (examMode) {
        url = `exam/chat`;
      } else if (analyticMode) {
        await readAnalytic(question);
        return;
      }

      const response = await fetch(`${API_BASE}/api/${url}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          question: question,
          session_id: sessionId,
          isNewSession,
        }),
      });
      setIsNewSession(false);

      // Capture the per-message conversation id from the response header
      // (sent alongside the streamed body, doesn't touch the stream itself)
      // and attach it to this assistant message before any chunks arrive.
      const convId = response.headers.get("X-Conversation-Id");
      if (convId) {
        setMessages((prev) => {
          const updated = [...prev];
          updated[updated.length - 1] = {
            ...updated[updated.length - 1],
            convId,
          };
          return updated;
        });
      }

      if (!response.ok) {
        let errorText = "Something went wrong. Please try again.";
        if (response.status === 429) {
          errorText =
            "Rate limit reached. Please wait a moment and try again.";
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

      // /api/chat now returns either a streamed RAG answer (text/plain) or
      // a JSON analytics result (when an admin question got routed to
      // run_analytics server-side). No X-Conversation-Id header comes with
      // the JSON path, so conversation_id from the body fills that in.
      const contentType = response.headers.get("content-type") || "";

      if (contentType.includes("application/json")) {
        const data = await response.json();

        setMessages((prev) => {
          const updated = [...prev];
          updated[updated.length - 1] = {
            ...updated[updated.length - 1],
            content: data.answer ?? "No answer was returned.",
            data: data.data ?? null,
            intent: data.intent ?? null,
            confidence: data.confidence ?? null,
            convId: updated[updated.length - 1].convId ?? data.conversation_id,
            isError: !data.resolved,
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
          content: "Something went wrong. Please try again.",
          isError: true,
        };
        return updated;
      });
    } finally {
      setIsSending(false);
    }
  }

  // Retries a failed assistant turn: drops the failed pair from the
  // visible history and resends the original question through the
  // normal sendMessage() flow (which re-appends both messages).
  function retryMessage(index) {
    const userMsg = messages[index - 1];
    if (!userMsg || userMsg.role !== "user") return;
    setMessages((prev) => prev.slice(0, index - 1));
    sendMessage(userMsg.content);
  }

  function getGreeting() {
    const hour = new Date().getHours();
    if (hour < 12) return "Good morning";
    if (hour < 18) return "Good afternoon";
    return "Good evening";
  }

  function handleSuggestionClick(question) {
    sendMessage(question);
  }

  // ---------- Auth gating (after all hooks, per Rules of Hooks) ----------
  if (!token) {
    return showSignup ? (
      <Signup onSwitchToLogin={() => setShowSignup(false)} />
    ) : (
      <Login onSwitchToSignup={() => setShowSignup(true)} />
    );
  }

  return (
    <div className="app">
      {/* ---------- Sidebar ---------- */}

      <div className="sidebar">
        <div className="sidebar-logo">
          <svg
            className="bot-icon"
            width="24"
            height="24"
            viewBox="0 0 100 100"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
          >
            <circle cx="50" cy="10" r="5" fill="currentColor" />
            <rect x="47.5" y="15" width="5" height="14" fill="currentColor" />
            <rect x="24" y="29" width="52" height="46" rx="14" fill="currentColor" />
            <rect x="14" y="44" width="11" height="18" rx="5.5" fill="currentColor" />
            <rect x="75" y="44" width="11" height="18" rx="5.5" fill="currentColor" />
            <circle cx="39" cy="50" r="5" fill="#171717" />
            <circle cx="61" cy="50" r="5" fill="#171717" />
            <path
              d="M36 60 Q50 70 64 60"
              stroke="#171717"
              strokeWidth="4"
              strokeLinecap="round"
              fill="none"
            />
          </svg>
          <span>Chatbot</span>
        </div>

        {/* ---------- Sidebar content: single continuous scroll region ---------- */}
        <div className="sidebar-content">
          {role === "admin" && (
            <div className="admin-panel">
              <div className="sidebar-nav">
                <button
                  className="sidebar-nav-item"
                  onClick={() => setAdminPanelView("documents")}
                >
                  <FileText size={16} />
                  Documents
                </button>
                <button
                  className="sidebar-nav-item"
                  onClick={() => setAdminPanelView("chats")}
                >
                  <Users size={16} />
                  Client Chats
                </button>
              </div>
            </div>
          )}

          {role === "instructor" && (
            <>
              <div className="mode-tabs">
                <button
                  className={!analyticMode ? "active" : ""}
                  onClick={() => setAnalyticMode(false)}
                >
                  Chat
                </button>
                <button
                  className={analyticMode ? "active" : ""}
                  onClick={() => setAnalyticMode(true)}
                >
                  Analytics
                </button>
              </div>

              <div className="sidebar-nav">
                <button
                  className="sidebar-nav-item"
                  onClick={() => setExamListOpen(true)}
                >
                  <FileText size={16} />
                  Exams
                </button>
              </div>
            </>
          )}

          {!examMode && (
            <button
              className="sidebar-nav-item"
              onClick={() => {
                handleNewChat();
              }}
            >
              <Plus size={16} />
              New Chat
            </button>
          )}

          {!examMode && (
            <>
              <div className="sidebar-section-title">Recents</div>
              <div className="history-list">
              {myConvo.length === 0 ? (
                <div className="empty-state">
                  <MessageSquare size={14} />
                  No chat history yet
                </div>
              ) : (
                myConvo.map((doc) => (
                  <button
                    key={doc.session_id}
                    className={`history-item ${sessionId === doc.session_id ? "active" : ""}`}
                    onClick={() => historyChat(doc.session_id)}
                    title={doc.title}
                  >
                    <MessageSquare size={14} />
                    {doc.title}
                  </button>
                ))
              )}
              </div>
            </>
          )}
        </div>

        <div className="sidebar-footer">
          <div className="user-info">
            <span className={`user-role ${role}`}>{username}</span>
            <button onClick={logout} className="logout-btn">
              Log out
            </button>
          </div>
        </div>
      </div>

      {/* ---------- Main Chat Area ---------- */}

      <div className="main">
        <div className="main-header">
          <div className="chat-title-label">{currentChatTitle}</div>
          <h1></h1>
          {examMode && (
            <div className="exam-mode-badge">
              <span className="exam-mode-dot" />
              Exam Mode
            </div>
          )}
        </div>

        <div className="chat-wrapper" ref={chatWrapperRef}>
          <div className="content">
            {messages.length === 0 ? (
              <div className="empty-hero">
                <svg
                  className="empty-hero-icon"
                  width="52"
                  height="52"
                  viewBox="0 0 100 100"
                  fill="none"
                  xmlns="http://www.w3.org/2000/svg"
                >
                  <circle cx="50" cy="10" r="5" fill="currentColor" />
                  <rect x="47.5" y="15" width="5" height="14" fill="currentColor" />
                  <rect x="24" y="29" width="52" height="46" rx="14" fill="currentColor" />
                  <rect x="14" y="44" width="11" height="18" rx="5.5" fill="currentColor" />
                  <rect x="75" y="44" width="11" height="18" rx="5.5" fill="currentColor" />
                  <circle cx="39" cy="50" r="5" fill="#171717" />
                  <circle cx="61" cy="50" r="5" fill="#171717" />
                  <path
                    d="M36 60 Q50 70 64 60"
                    stroke="#171717"
                    strokeWidth="4"
                    strokeLinecap="round"
                    fill="none"
                  />
                </svg>

                <div className="empty-hero-greeting">
                  {getGreeting()}
                  {username ? `, ${username.charAt(0).toUpperCase()}${username.slice(1)}` : ""}
                </div>

                {suggestions.length > 0 && (
                  <div className="suggestion-list">
                    {suggestions.map((s, i) => (
                      <button
                        key={i}
                        className="suggestion-row"
                        onClick={() => handleSuggestionClick(s.question)}
                      >
                        <Search size={15} />
                        <span>{s.question}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            ) : (
              <div className="chat-box">
                {messages.map((msg, index) => (
                  <div key={index} className={`message-row ${msg.role}`}>
                    <div className={`message-avatar ${msg.role}`}>
                      {msg.role === "user"
                        ? (username ? username.charAt(0).toUpperCase() : "U")
                        : <Bot size={15} />}
                    </div>

                    <div className={`message-col ${msg.role}`}>
                      {msg.role === "user" ? (
                        <div className="user-message">
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>
                            {msg.content}
                          </ReactMarkdown>
                        </div>
                      ) : msg.isError ? (
                        <div className="assistant-message error">
                          <AlertTriangle size={16} className="error-icon" />
                          <div className="error-body">
                            <ReactMarkdown remarkPlugins={[remarkGfm]}>
                              {msg.content}
                            </ReactMarkdown>
                            <button
                              className="retry-btn"
                              onClick={() => retryMessage(index)}
                            >
                              <RefreshCw size={13} />
                              Try again
                            </button>
                          </div>
                        </div>
                      ) : (
                        <div className="assistant-message">
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>
                            {msg.content}
                          </ReactMarkdown>
                        </div>
                      )}

                      <div className="message-actions">
                        <button
                          className="copy-btn"
                          onClick={() => copyToClipboard(msg.content, index)}
                          title="Copy"
                        >
                          {copiedIndex === index ? (
                            <Check size={16} />
                          ) : (
                            <Copy size={16} />
                          )}
                        </button>

                        {msg.role === "assistant" && msg.convId && (
                          <>
                            <button
                              className={`rate-btn rate-up ${msg.rating === "up" ? "active" : ""}`}
                              onClick={() => rateMessage(index, msg.convId, "up")}
                              title="Good response"
                            >
                              <ThumbsUp size={15} />
                            </button>
                            <button
                              className={`rate-btn rate-down ${msg.rating === "down" ? "active" : ""}`}
                              onClick={() => rateMessage(index, msg.convId, "down")}
                              title="Bad response"
                            >
                              <ThumbsDown size={15} />
                            </button>
                          </>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
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
                    {isUploading ? (
                      <Loader2 size={18} className="spin" />
                    ) : (
                      <Paperclip size={18} />
                    )}
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

              <button
                onClick={() => sendMessage()}
                disabled={isSending}
                className="send-btn"
              >
                {isSending ? (
                  <Loader2 size={20} className="spin" />
                ) : (
                  <Send size={20} />
                )}
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
              <div className="preview-header-left">
                {adminPanelView === "documents" && (
                  <button
                    className="modal-back-btn"
                    onClick={() => setPreviewDoc(null)}
                    title="Back"
                  >
                    <ArrowLeft size={18} />
                  </button>
                )}
                <h2>{previewDoc.filename}</h2>
              </div>
              <button
                onClick={() => {
                  setPreviewDoc(null);
                  setAdminPanelView(null);
                }}
                className="auth-close"
              >
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
                    <span className="chunk-index">
                      Chunk {chunk.chunk_index}
                    </span>
                    <p>{chunk.content}</p>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* ---------- Exams list modal (instructor only) ---------- */}

      {examListOpen && !examDetailOpen && (
        <div className="preview-overlay" onClick={() => setExamListOpen(false)}>
          <div className="preview-modal" onClick={(e) => e.stopPropagation()}>
            <div className="preview-header">
              <h2>Exams</h2>
              <button
                onClick={() => setExamListOpen(false)}
                className="auth-close"
              >
                <X size={20} />
              </button>
            </div>

            {fetchExams.length === 0 ? (
              <div className="docs-empty">No exams yet.</div>
            ) : (
              <div className="doc-list">
                {fetchExams.map((doc) => (
                  <div
                    key={doc.id}
                    className="doc-sidebar-row"
                    onClick={() => {
                      setExamDetailOpen(true);
                      fetchExamDetail(doc.id);
                    }}
                  >
                    <div className="doc-sidebar-icon">
                      <FileText size={15} />
                    </div>
                    <div className="doc-sidebar-info">
                      <span className="doc-sidebar-name">{doc.title}</span>
                      <span className="doc-sidebar-meta">
                        <span className={`status-pill ${doc.status}`}>
                          {doc.status}
                        </span>
                        {doc.id}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* ---------- Exam detail modal (instructor only) ---------- */}

      {examDetailOpen && (
        <div
          className="preview-overlay"
          onClick={() => {
            setExamDetailOpen(false);
            setSelectedExam(null);
          }}
        >
          <div className="preview-modal" onClick={(e) => e.stopPropagation()}>
            <div className="preview-header">
              <div className="preview-header-left">
                <button
                  className="modal-back-btn"
                  onClick={() => {
                    setExamDetailOpen(false);
                    setSelectedExam(null);
                  }}
                  title="Back"
                >
                  <ArrowLeft size={18} />
                </button>
                <h2>{selectedExam ? selectedExam.title : "Exam Detail"}</h2>
              </div>
              <button
                onClick={() => {
                  setExamDetailOpen(false);
                  setSelectedExam(null);
                  setExamListOpen(false);
                }}
                className="auth-close"
              >
                <X size={20} />
              </button>
            </div>

            {isLoadingExamDetail ? (
              <div className="admin-loading">
                <Loader2 className="spin" size={20} /> Loading exam...
              </div>
            ) : selectedExam ? (
              <div className="chat-detail-fields">
                {Object.entries(selectedExam).map(([key, value]) => (
                  <div key={key} className="chat-detail-row">
                    <span className="chat-detail-label">
                      {key.replace(/_/g, " ")}
                    </span>
                    <span className="chat-detail-value">
                      {value === null || value === undefined
                        ? "—"
                        : typeof value === "object"
                          ? JSON.stringify(value)
                          : String(value)}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="docs-empty">Couldn't load exam details.</div>
            )}
          </div>
        </div>
      )}

      {/* ---------- Documents list modal (admin only) ---------- */}

      {adminPanelView === "documents" && !previewDoc && (
        <div
          className="preview-overlay"
          onClick={() => setAdminPanelView(null)}
        >
          <div className="preview-modal" onClick={(e) => e.stopPropagation()}>
            <div className="preview-header">
              <h2>Documents</h2>
              <button
                onClick={() => setAdminPanelView(null)}
                className="auth-close"
              >
                <X size={20} />
              </button>
            </div>

            {documents.length === 0 ? (
              <div className="docs-empty">No documents uploaded yet.</div>
            ) : (
              <div className="doc-list">
                {documents.map((doc) => (
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
                      <span className="doc-sidebar-meta">
                        {doc.chunk_count} chunks
                        {citationStats.find((s) => s.document_id === doc.id) &&
                          ` · cited ${citationStats.find((s) => s.document_id === doc.id).chunk_count}x`}
                      </span>
                    </div>
                    <button
                      className="doc-sidebar-delete"
                      onClick={(e) => handleDeleteDoc(doc.id, e)}
                      title="Delete"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* ---------- Client Chats modal: filters + results (admin only) ---------- */}

      {adminPanelView === "chats" && !selectedChatDetail && (
        <div
          className="preview-overlay"
          onClick={() => setAdminPanelView(null)}
        >
          <div className="preview-modal" onClick={(e) => e.stopPropagation()}>
            <div className="preview-header">
              <h2>Client Chats</h2>
              <button
                onClick={() => setAdminPanelView(null)}
                className="auth-close"
              >
                <X size={20} />
              </button>
            </div>

            <div className="filter-groups">
              <div className="filter-group">
                <div className="filter-group-title">Role</div>
                <div className="filter-chips">
                  <label className="chip">
                    <input
                      type="checkbox"
                      checked={roleFilter === "admin"}
                      onChange={(e) => setRoleFilter(e.target.checked ? "admin" : "")}
                    />
                    Admin
                  </label>
                  <label className="chip">
                    <input
                      type="checkbox"
                      checked={roleFilter === "student"}
                      onChange={(e) => setRoleFilter(e.target.checked ? "student" : "")}
                    />
                    Student
                  </label>
                  <label className="chip">
                    <input
                      type="checkbox"
                      checked={roleFilter === "instructor"}
                      onChange={(e) => setRoleFilter(e.target.checked ? "instructor" : "")}
                    />
                    Instructor
                  </label>
                </div>
              </div>

              <div className="filter-group">
                <div className="filter-group-title">Mode</div>
                <div className="filter-chips">
                  <label className="chip">
                    <input
                      type="checkbox"
                      checked={modeFilter === "general"}
                      onChange={(e) => setModeFilter(e.target.checked ? "general" : "")}
                    />
                    General
                  </label>
                  <label className="chip">
                    <input
                      type="checkbox"
                      checked={modeFilter === "exam"}
                      onChange={(e) => setModeFilter(e.target.checked ? "exam" : "")}
                    />
                    Exam
                  </label>
                  <label className="chip">
                    <input
                      type="checkbox"
                      checked={modeFilter === "instructor"}
                      onChange={(e) => setModeFilter(e.target.checked ? "instructor" : "")}
                    />
                    Analysis
                  </label>
                </div>
              </div>

              <div className="filter-group">
                <div className="filter-group-title">Response</div>
                <div className="filter-chips">
                  <label className="chip">
                    <input
                      type="checkbox"
                      checked={escalatedFilter === true}
                      onChange={(e) => setEscalatedFilter(e.target.checked ? true : null)}
                    />
                    Escalated
                  </label>
                </div>
              </div>

              <div className="filter-group">
                <div className="filter-group-title">User</div>
                <div className="filter-search-input">
                  <Search size={14} />
                  <input
                    type="text"
                    placeholder="Enter Reg no."
                    value={userIdFilter}
                    onChange={(e) => setUserIdFilter(e.target.value)}
                  />
                </div>
              </div>
            </div>

            <button
              className="filter-search-btn full-width"
              onClick={() => adminSearchChat()}
            >
              <Search size={13} />
              Search
            </button>

            <div className="client-chats-results">
              {searchChat.length === 0 ? (
                <div className="empty-state">
                  <MessageSquare size={14} />
                  No chat history found
                </div>
              ) : (
                searchChat.map((doc, i) => (
                  <button
                    key={i}
                    className="filter-result-item"
                    onClick={() => setSelectedChatDetail(doc)}
                  >
                    {doc.question_preview || doc.question || `Conversation ${i + 1}`}
                  </button>
                ))
              )}
            </div>
          </div>
        </div>
      )}

      {/* ---------- Client chat detail modal (admin only) ---------- */}

      {selectedChatDetail && (
        <div
          className="preview-overlay"
          onClick={() => setSelectedChatDetail(null)}
        >
          <div className="preview-modal" onClick={(e) => e.stopPropagation()}>
            <div className="preview-header">
              <div className="preview-header-left">
                {adminPanelView === "chats" && (
                  <button
                    className="modal-back-btn"
                    onClick={() => setSelectedChatDetail(null)}
                    title="Back"
                  >
                    <ArrowLeft size={18} />
                  </button>
                )}
                <h2>Conversation Detail</h2>
              </div>
              <button
                onClick={() => {
                  setSelectedChatDetail(null);
                  setAdminPanelView(null);
                }}
                className="auth-close"
              >
                <X size={20} />
              </button>
            </div>

            <div className="chat-detail-fields">
              {Object.entries(selectedChatDetail).map(([key, value]) => (
                <div key={key} className="chat-detail-row">
                  <span className="chat-detail-label">
                    {key.replace(/_/g, " ")}
                  </span>
                  <span className="chat-detail-value">
                    {value === null || value === undefined
                      ? "—"
                      : typeof value === "object"
                        ? JSON.stringify(value)
                        : String(value)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default App;