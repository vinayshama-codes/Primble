import { API_BASE } from "../config/constants";

export async function createCheckout(plan, billing_cycle) {
  const res = await fetch(`${API_BASE}/api/stripe/create-checkout`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ plan, billing_cycle }),
  });
  return { ok: res.ok, data: await res.json() };
}

export async function createPortalSession() {
  const res = await fetch(`${API_BASE}/api/stripe/create-portal-session`, {
    method: "POST",
    credentials: "include",
  });
  return { ok: res.ok, data: await res.json() };
}

export async function verifyUpgrade() {
  const res = await fetch(`${API_BASE}/api/stripe/verify-upgrade`, {
    method: "POST",
    credentials: "include",
  });
  return { ok: res.ok, data: await res.json() };
}

export async function applyOverage(stripe_session_id, qty) {
  const res = await fetch(`${API_BASE}/api/stripe/apply-overage`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ stripe_session_id, qty }),
  });
  return { ok: res.ok, data: await res.json() };
}
