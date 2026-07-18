import { useState } from "react";
import "./App.css";

function App() {
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState([]);

  async function sendMessage() {
    console.log("========== SEND BUTTON CLICKED ==========");

    const question = input.trim();

    console.log("Question:", question);

    if (!question) {
      console.log("Question is empty");
      return;
    }

    // Add user message and empty assistant message
    setMessages((prev) => [
      ...prev,
      {
        role: "user",
        content: question,
      },
      {
        role: "assistant",
        content: "",
      },
    ]);

    setInput("");

    try {
      console.log("Sending request...");

      const response = await fetch(
        "http://127.0.0.1:8000/api/chat",
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            question: question,
          }),
        }
      );

      console.log("Status:", response.status);
      console.log("Response:", response);

      if (!response.ok) {
        console.log("HTTP Error");
        return;
      }

      if (!response.body) {
        console.log("No response body");
        return;
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();

      while (true) {
        const { value, done } = await reader.read();

        if (done) {
          break;
        }

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
    }
  }

  return (
    <div className="container">
      <h1>Exam AI Chatbot</h1>

      <div className="chat-box">
        {messages.map((msg, index) => (
          <div
            key={index}
            className={
              msg.role === "user"
                ? "user-message"
                : "assistant-message"
            }
          >
            {msg.content}
          </div>
        ))}
      </div>

      <div className="input-area">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Message Exam AI..."
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              sendMessage();
            }
          }}
        />

        <button onClick={sendMessage}>➤</button>
      </div>
    </div>
  );
}

export default App;