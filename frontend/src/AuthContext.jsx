import { createContext, useContext, useState, useEffect, useRef } from "react";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  // Load any existing session from localStorage on first render,
  // so a page refresh doesn't log the user out.
  const [token, setToken] = useState(() => localStorage.getItem("token"));
  const [role, setRole] = useState(() => localStorage.getItem("role"));
  const [username, setUsername] = useState(() => localStorage.getItem("username"));

  function login(newToken, newRole, newUsername) {
    localStorage.setItem("token", newToken);
    localStorage.setItem("role", newRole);
    localStorage.setItem("username", newUsername);
    setToken(newToken);
    setRole(newRole);
    setUsername(newUsername);
  }

  function logout() {
    localStorage.removeItem("token");
    localStorage.removeItem("role");
    localStorage.removeItem("username");
    setToken(null);
    setRole(null);
    setUsername(null);
  }

  // logout() gets redefined on every render (it closes over state), but the
  // fetch patch below is only installed once on mount. Keep a ref so the
  // patched fetch always calls the *current* logout, not a stale one.
  const logoutRef = useRef(logout);
  logoutRef.current = logout;

  // Globally intercept every fetch response in the app. If any request
  // comes back 401 while we believe we're logged in (token in
  // localStorage), the backend has rejected our token — e.g. it expired
  // while the laptop was asleep. Force a logout so the frontend UI
  // matches reality instead of silently failing requests while still
  // showing "logged in".
  useEffect(() => {
    const originalFetch = window.fetch;

    window.fetch = async (...args) => {
      const response = await originalFetch(...args);

      if (response.status === 401 && localStorage.getItem("token")) {
        logoutRef.current();
      }

      return response;
    };

    return () => {
      window.fetch = originalFetch;
    };
  }, []);

  return (
    <AuthContext.Provider value={{ token, role, username, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

// Custom hook so any component can just call useAuth()
export function useAuth() {
  return useContext(AuthContext);
}