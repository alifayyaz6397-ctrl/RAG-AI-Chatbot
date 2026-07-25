import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import "./App.css";
import { useAuth } from "./AuthContext";
import Login from "./Login";
import Signup from "./Signup";
import { Copy, Check, Send, Loader2 } from "lucide-react";
import { useState, useRef, useEffect } from "react";
import { AuthProvider } from './AuthContext';



// inside your component

function App() {
 
  const [showSignup, setShowSignup] = useState(false);

  const { token, role, logout } = useAuth();
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState([]);
  const [regNumber, setRegNumber] = useState("");
  const [isSending, setIsSending] = useState(false);

  const chatWrapperRef = useRef(null);

useEffect(() => {
  if (textareaRef.current) {
    const ta = textareaRef.current;
    ta.style.height = "auto";
    const newHeight = Math.min(ta.scrollHeight, 200); // 200 = your max-height
    ta.style.height = newHeight + "px";
    ta.style.overflowY = ta.scrollHeight > 200 ? "auto" : "hidden";
  }
   if (textareaRef.current && input === "") {
    textareaRef.current.style.height = "24px"; // roughly one line at your font-size/line-height
  }
}, [input]);

  const [copiedIndex, setCopiedIndex] = useState(null);

  const textareaRef = useRef(null);

useEffect(() => {
  if (textareaRef.current) {
    textareaRef.current.style.height = "auto";
    textareaRef.current.style.height = textareaRef.current.scrollHeight + "px";
  }
}, [input]);

useEffect(() => {
  if (chatWrapperRef.current) {
    chatWrapperRef.current.scrollTop = chatWrapperRef.current.scrollHeight;
  }
}, [messages]);

function copyToClipboard(text, index) {
  navigator.clipboard.writeText(text).then(() => {
    setCopiedIndex(index);
    setTimeout(() => setCopiedIndex(null), 1500);
  });
}

  async function sendMessage() {
  console.log("========== SEND BUTTON CLICKED ==========");

  const question = input.trim();
  console.log("Question:", question);

  if (!question || isSending) {
    console.log("Question is empty or already sending");
    return;
  }

  setIsSending(true);

  setMessages((prev) => [
    ...prev,
    { role: "user", content: question },
    { role: "assistant", content: "" },
  ]);

  setInput("");

  try {
    console.log("Sending request...");

    const response = await fetch("http://127.0.0.1:8000/api/chat", {
      method: "POST",
      headers: {
    "Content-Type": "application/json",
    "Authorization": `Bearer ${token}`,
  },
      body: JSON.stringify({ question: question }),
  
    });

    console.log("Status:", response.status);

   if (!response.ok) {
      console.log("HTTP Error");

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
      console.log("Chunk:", chunk);

      setMessages((prev) => {
        const updated = [...prev];
        updated[updated.length - 1] = {
          ...updated[updated.length - 1],
          content: updated[updated.length - 1].content + chunk,
        };
        return updated;
      });
    }

    console.log("Streaming Finished");
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

        {/* Chat history will go here */}

        <div className="sidebar-content"></div>

        {/* User info / Settings */}

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
    </div>
  );
}

export default App;
