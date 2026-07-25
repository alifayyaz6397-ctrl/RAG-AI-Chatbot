import { useState } from "react";
import { X } from "lucide-react";
import { useAuth } from "./AuthContext";
import "./Auth.css";

function Signup({ onSwitchToLogin }) {
  const [studentId, setStudentId] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  const { login } = useAuth();

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    setIsLoading(true);

    try {
      const response = await fetch("http://127.0.0.1:8000/signup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          student_id: studentId,
          username,
          password,
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        setError(data.detail || "Signup failed. Please try again.");
        return;
      }

      login(data.access_token, data.role);
    } catch (err) {
      setError("Could not reach the server. Please try again.");
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-card">
        <button className="auth-close" title="Close" type="button">
          <X size={20} />
        </button>

        <h1>Create your account</h1>
        <p className="auth-subtitle">
          Use the Student ID on your enrollment record to link your account.
        </p>

        <form className="auth-form" onSubmit={handleSubmit}>
          {error && <div className="auth-error">{error}</div>}

          <input
            type="text"
            className="auth-field"
            placeholder="Student ID (e.g. 2025-CS-01)"
            value={studentId}
            onChange={(e) => setStudentId(e.target.value)}
            required
          />

          <input
            type="text"
            className="auth-field"
            placeholder="Choose a username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
          />

          <input
            type="password"
            className="auth-field"
            placeholder="Choose a password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />

          <button type="submit" className="auth-submit" disabled={isLoading}>
            {isLoading ? "Creating account..." : "Continue"}
          </button>
        </form>

        <p className="auth-switch">
          Already have an account?{" "}
          <button type="button" onClick={onSwitchToLogin} className="link-btn">
            Log in
          </button>
        </p>
      </div>
    </div>
  );
}

export default Signup;
