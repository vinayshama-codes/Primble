import { useState, useEffect } from "react";
import { fetchCurrentUser, logoutUser } from "../api/authApi";

export function useAuth() {
  const [user, setUser]               = useState(null);
  const [authLoading, setAuthLoading] = useState(true);

  useEffect(() => {
    fetchCurrentUser()
      .then((data) => setUser(data))
      .catch(() => setUser(null))
      .finally(() => setAuthLoading(false));
  }, []);

  const login = (usr) => {
    setUser(usr);
  };

  const logout = () => {
    logoutUser().finally(() => {
      sessionStorage.removeItem("acordly_signature");
      localStorage.removeItem("acordly_signature");
      setUser(null);
    });
  };

  // token is intentionally null — auth is carried by HttpOnly cookie.
  // Callers that still pass token to Authorization headers need migration.
  return { user, setUser, token: null, authLoading, login, logout };
}
