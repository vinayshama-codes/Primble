import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./App.css";
import "./index.css";
import { API_BASE } from "./config/constants";

// Safari / iOS block cross-domain HttpOnly cookies (ITP). This interceptor
// reads the session token stored after login and sends it as a Bearer header
// on every API request, so all browsers work identically in production.
(function _installAuthInterceptor() {
  const _orig = window.fetch.bind(window);
  window.fetch = (url, opts = {}) => {
    const token = sessionStorage.getItem("acordly_tk");
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