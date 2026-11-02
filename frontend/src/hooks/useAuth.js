import { useState, useEffect } from "react";
import { fetchCurrentUser, logoutUser } from "../api/authApi";
import { LOGOUT_REDIRECT_URL } from "../config/constants";

export function useAuth() {
  const [user, setUser]               = useState(null);
  const [authLoading, setAuthLoading] = useState(true);

  useEffect(() => {
    fetchCurrentUser()
      .then((data) => setUser(data))
      .catch(() => setUser(null))
      .finally(() => setAuthLoading(false));
  }, []);

  // A sign-in response is a short record (no package numbers, limits or
  // payment status): show it at once, then load the full account the way a
  // reload does - else the plan panel read "0 used" until a refresh (LT-2).
  const login = (usr) => {
    setUser(usr);
    fetchCurrentUser()
      .then((full) => { if (full) setUser(full); })
      .catch(() => { /* signed out meanwhile: keep what the sign-in gave */ });
  };

  const logout = () => {
    logoutUser().finally(() => {
      sessionStorage.removeItem("acordly_signature");
      localStorage.removeItem("acordly_signature");
      setUser(null);
      window.location.href = LOGOUT_REDIRECT_URL;
    });
  };

  // token is intentionally null — auth is carried by HttpOnly cookie.
  // Callers that still pass token to Authorization headers need migration.
  return { user, setUser, token: null, authLoading, login, logout };
}
