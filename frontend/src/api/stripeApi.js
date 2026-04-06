import { API_BASE } from "../config/constants";

export async function createCheckout(token, plan, billing_cycle) {
  const res = await fetch(`${API_BASE}/api/stripe/create-checkout`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ plan, billing_cycle }),
  });
  return { ok: res.ok, data: await res.json() };
}

export async function createPortalSession(token) {
  const res = await fetch(`${API_BASE}/api/stripe/create-portal-session`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
  return { ok: res.ok, data: await res.json() };
}

export async function verifyUpgrade(token) {
  const res = await fetch(`${API_BASE}/api/stripe/verify-upgrade`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
  return { ok: res.ok, data: await res.json() };
}

export async function applyOverage(token, stripe_session_id, qty) {
  const res = await fetch(`${API_BASE}/api/stripe/apply-overage`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ stripe_session_id, qty }),
  });
  return { ok: res.ok, data: await res.json() };
}