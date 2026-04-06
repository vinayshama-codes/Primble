import { useState, useEffect } from "react";
import { API_BASE } from "../config/constants";
import { fetchCurrentUser } from "../api/authApi";

export function useAuth() {
  const [user, setUser]               = useState(null);
  const [token, setToken]             = useState(() => localStorage.getItem("acordly_token"));
  const [authLoading, setAuthLoading] = useState(!!localStorage.getItem("acordly_token"));

  useEffect(() => {
    if (!token) { setAuthLoading(false); return; }
    setAuthLoading(true);
    fetchCurrentUser(token)
      .then((data) => setUser(data))
      .catch(() => {
        localStorage.removeItem("acordly_token");
        setToken(null);
      })
      .finally(() => setAuthLoading(false));
  }, [token]);

  const login = (tok, usr) => {
    localStorage.setItem("acordly_token", tok);
    setToken(tok);
    setUser(usr);
  };

  const logout = () => {
    fetch(`${API_BASE}/api/auth/logout`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    }).finally(() => {
      localStorage.removeItem("acordly_token");
      localStorage.removeItem("acordly_signature");
      setToken(null);
      setUser(null);
    });
  };

  return { user, setUser, token, authLoading, login, logout };
}