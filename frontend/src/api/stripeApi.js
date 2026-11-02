import { API_BASE } from "../config/constants";
import { apiErrorCode, apiErrorMessage } from "../utils/billing";

// The one door for starting a checkout (2 Nov 2026). Returns {url} on success,
// else {code, message}: 409 subscription_exists / payment_due when a plan is
// already on file, 503 when Stripe can't be reached. Never throws.
export async function startCheckout(plan, billing_cycle) {
  try {
    const res = await fetch(`${API_BASE}/api/stripe/create-checkout`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ plan, billing_cycle }),
    });
    const data = await res.json().catch(() => ({}));
    if (res.ok && data.checkout_url) return { url: data.checkout_url };
    const fallback = res.status === 503
      ? "Billing is unavailable right now. Please try again in a few minutes."
      : "Failed to start checkout. Please try again.";
    return { code: apiErrorCode(data), message: apiErrorMessage(data, fallback) };
  } catch {
    return { code: null, message: "Network error. Please try again." };
  }
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
