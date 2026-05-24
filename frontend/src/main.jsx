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

// Bootstrap the notification service worker on app start (independent of any
// user gesture). We don't request Notification permission here — that still
// happens lazily on the first upload/generate click. Registering early means:
//   1. The SW exists before any resume-after-reload code path tries to use it.
//   2. New deploys propagate the updated SW as soon as the user opens the app.
//   3. registration.showNotification() always has a live registration to use.
// Failures are logged but never block app boot.
window.__primbleSwReady = (async () => {
  if (typeof window === "undefined") return null;
  if (!("serviceWorker" in navigator)) {
    console.info("[primble-sw] serviceWorker API unavailable");
    return null;
  }
  if (window.location.protocol !== "https:" && window.location.hostname !== "localhost" && window.location.hostname !== "127.0.0.1") {
    console.warn("[primble-sw] non-https origin, SW registration skipped:", window.location.origin);
    return null;
  }
  try {
    const reg = await navigator.serviceWorker.register("/notification-sw.js", { scope: "/" });
    // Trigger an update check on every load so deploys propagate.
    try { reg.update().catch(() => {}); } catch {}
    const active = await navigator.serviceWorker.ready;
    console.info("[primble-sw] registered, scope=", active.scope);
    return active;
  } catch (err) {
    console.error("[primble-sw] register failed:", err && err.message ? err.message : err);
    return null;
  }
})();

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);