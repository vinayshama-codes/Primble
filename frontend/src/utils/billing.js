// billing.js - plan and checkout rules shared by every billing screen (2 Nov 2026).
//
// A user who already pays for a plan never starts a new checkout: a second
// checkout opened a second full-price subscription. Plan changes go through
// support until in-app switching is built; the server refuses a second
// checkout with 409 either way.

export const SUPPORT_EMAIL = "support@primble.ai";
export const CHANGE_PLAN_NOTE = `To change your plan, contact ${SUPPORT_EMAIL}.`;

// Billing e-mails link to /?open=billing; the intent survives sign-in here.
export const OPEN_BILLING_PARAM = "billing";
export const OPEN_BILLING_KEY = "primble_open_billing";

// True for any paid tier (including a plan set to cancel at period end, an
// overdue or a locked one): each still has a subscription on file.
export function hasPaidPlan(user) {
  return !!user && (user.subscription_tier || "free") !== "free";
}

// Server errors arrive as {"detail": "text"} or {"detail": {"code", "message"}}.
// Always a string, so nothing renders an object.
export function apiErrorMessage(data, fallback) {
  const d = data && data.detail;
  if (typeof d === "string" && d) return d;
  if (d && typeof d === "object" && typeof d.message === "string" && d.message) return d.message;
  if (data && typeof data.message === "string" && data.message) return data.message;
  return fallback;
}

export function apiErrorCode(data) {
  const d = data && data.detail;
  return d && typeof d === "object" && typeof d.code === "string" ? d.code : null;
}

// The refusal the user fixes in Manage billing (an unpaid last invoice).
export function needsBillingFix(code) {
  return code === "payment_due";
}
