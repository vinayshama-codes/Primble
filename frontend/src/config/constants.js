// Set VITE_GOOGLE_CLIENT_ID, VITE_API_BASE, VITE_STRIPE_PORTAL in your .env file.
// Do NOT hardcode production values here — this file is committed to source control.
export const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID || "";
export const API_BASE = (import.meta.env.VITE_API_BASE || "http://localhost:8000").replace(/\/$/, "");
export const STRIPE_PORTAL = import.meta.env.VITE_STRIPE_PORTAL || "https://billing.stripe.com/p/login/";