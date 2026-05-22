// Set VITE_GOOGLE_CLIENT_ID, VITE_API_BASE, VITE_STRIPE_PORTAL, VITE_LOGOUT_REDIRECT_URL in your .env file.
// Do NOT hardcode production values here — this file is committed to source control.
export const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID || "";
const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1", "0.0.0.0"]);

function resolveApiBase(value) {
  const raw = (value || "http://localhost:8000").replace(/\/$/, "");
  if (typeof window === "undefined") return raw;
  try {
    const url = new URL(raw);
    const pageHost = window.location.hostname;
    if (LOCAL_HOSTS.has(url.hostname) && pageHost && !LOCAL_HOSTS.has(pageHost)) {
      url.hostname = pageHost;
      return url.toString().replace(/\/$/, "");
    }
  } catch {
    // keep relative or custom API bases untouched
  }
  return raw;
}

export const API_BASE = resolveApiBase(import.meta.env.VITE_API_BASE);
export const STRIPE_PORTAL = import.meta.env.VITE_STRIPE_PORTAL || "https://billing.stripe.com/p/login/";
export const LOGOUT_REDIRECT_URL = import.meta.env.VITE_LOGOUT_REDIRECT_URL || "/";