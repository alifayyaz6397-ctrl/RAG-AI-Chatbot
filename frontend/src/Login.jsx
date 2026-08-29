import { useState } from "react";
import { X } from "lucide-react";
import { useAuth } from "./AuthContext";
import "./Auth.css";

function Login({ onSwitchToSignup }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  const { login } = useAuth();
 const API_BASE = import.meta.env.VITE_API_URL;
  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    setIsLoading(true);

    try {
      const response = await fetch(`${API_BASE}/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });

      const data = await response.json();

      if (!response.ok) {
        setError(data.detail || "Login failed. Please try again.");
        return;
      }

      login(data.access_token, data.role, data.username);
    } catch (err) {
      console.error("Login error:", err); // logs the real error to devtools console
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

        <h1>Log in</h1>
        <p className="auth-subtitle">
          Sign in to ask Exam AI about your results, schedule, and exam rules.
        </p>

        <form className="auth-form" onSubmit={handleSubmit}>
          {error && <div className="auth-error">{error}</div>}

          <input
            type="text"
            className="auth-field"
            placeholder="Username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
          />

          <input
            type="password"
            className="auth-field"
            placeholder="Password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />

          <button type="submit" className="auth-submit" disabled={isLoading}>
            {isLoading ? "Logging in..." : "Continue"}
          </button>
        </form>

        <p className="auth-switch">
          Don&apos;t have an account?{" "}
          <button type="button" onClick={onSwitchToSignup} className="link-btn">
            Sign up
          </button>
        </p>
      </div>
    </div>
  );
}

export default Login;