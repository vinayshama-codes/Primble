import { useState, useEffect } from "react";
import { API_BASE } from "../config/constants";
import { fetchCurrentUser } from "../api/authApi";

// Token is stored in sessionStorage (cleared when the tab closes) rather than
// localStorage to limit the XSS blast radius: a compromised tab cannot leak the
// token to other tabs or persist it across browser restarts.
const _storage = sessionStorage;

export function useAuth() {
  const [user, setUser]               = useState(null);
  const [token, setToken]             = useState(() => _storage.getItem("acordly_token"));
  const [authLoading, setAuthLoading] = useState(!!_storage.getItem("acordly_token"));

  useEffect(() => {
    if (!token) { setAuthLoading(false); return; }
    setAuthLoading(true);
    fetchCurrentUser(token)
      .then((data) => setUser(data))
      .catch(() => {
        _storage.removeItem("acordly_token");
        setToken(null);
      })
      .finally(() => setAuthLoading(false));
  }, [token]);

  const login = (tok, usr) => {
    _storage.setItem("acordly_token", tok);
    setToken(tok);
    setUser(usr);
  };

  const logout = () => {
    fetch(`${API_BASE}/api/auth/logout`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    }).finally(() => {
      _storage.removeItem("acordly_token");
      sessionStorage.removeItem("acordly_signature");
      localStorage.removeItem("acordly_token");      // clean up any legacy localStorage remnant
      localStorage.removeItem("acordly_signature");
      setToken(null);
      setUser(null);
    });
  };

  return { user, setUser, token, authLoading, login, logout };
}