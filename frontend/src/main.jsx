import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./App.css";
import "./index.css";
import { API_BASE } from "./config/constants";

// Safari / iOS block cross-domain HttpOnly cookies (ITP). This interceptor
// reads the session token stored after login and sends it as a Bearer header
// on every API request, so all browsers work identically in production.
// localStorage is checked first (persists across tab close on iOS Safari);
// sessionStorage is kept as a fallback for older sessions. Both reads are
// guarded because Safari Private/Lockdown mode can throw on storage access.
(function _installAuthInterceptor() {
  const _orig = window.fetch.bind(window);
  const _readToken = () => {
    try { return localStorage.getItem("acordly_tk") || sessionStorage.getItem("acordly_tk") || null; }
    catch { return null; }
  };
  window.fetch = (url, opts = {}) => {
    const token = _readToken();
    if (token && API_BASE && typeof url === "string" && url.startsWith(API_BASE)) {
      const headers = new Headers(opts.headers || {});
      if (!headers.has("Authorization")) headers.set("Authorization", `Bearer ${token}`);
      return _orig(url, { ...opts, headers });
    }
    return _orig(url, opts);
  };
})();

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);