import { API_BASE } from "../config/constants";

const _json = (res) => res.json();

export async function fetchCurrentUser() {
  const res = await fetch(`${API_BASE}/api/auth/me`, { credentials: "include" });
  if (!res.ok) throw new Error("Not authenticated");
  return _json(res);
}

export async function loginUser(email, password) {
  const res = await fetch(`${API_BASE}/api/auth/login`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  const data = await _json(res);
  if (res.ok && data.session_token) sessionStorage.setItem("acordly_tk", data.session_token);
  return { ok: res.ok, status: res.status, data };
}

export async function signupUser(payload) {
  const res = await fetch(`${API_BASE}/api/auth/signup`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return { ok: res.ok, status: res.status, data: await _json(res) };
}

export async function googleAuthUser(credential, nonce) {
  const res = await fetch(`${API_BASE}/api/auth/google`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ credential, nonce }),
  });
  const data = await _json(res);
  if (res.ok && data.session_token) sessionStorage.setItem("acordly_tk", data.session_token);
  return { ok: res.ok, status: res.status, data };
}

export async function fetchGoogleNonce() {
  const res = await fetch(`${API_BASE}/api/auth/google/nonce`, { credentials: "include" });
  if (!res.ok) throw new Error("Failed to fetch nonce");
  const data = await _json(res);
  return data.nonce;
}

export async function verifyEmailCode(email, code) {
  const res = await fetch(`${API_BASE}/api/auth/verify-email`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, code }),
  });
  const data = await _json(res);
  if (res.ok && data.session_token) sessionStorage.setItem("acordly_tk", data.session_token);
  return { ok: res.ok, status: res.status, data };
}

export async function resendVerification(email) {
  await fetch(`${API_BASE}/api/auth/resend-verification`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
  });
}

export async function forgotPassword(email) {
  const res = await fetch(`${API_BASE}/api/auth/forgot-password`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
  });
  return { ok: res.ok, data: await _json(res) };
}

export async function resetPassword(email, code, new_password) {
  const res = await fetch(`${API_BASE}/api/auth/reset-password`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, code, new_password }),
  });
  return { ok: res.ok, data: await _json(res) };
}

export async function completeProfile(organization_name, acord_disclaimer_accepted) {
  const res = await fetch(`${API_BASE}/api/auth/complete-profile`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ organization_name, acord_disclaimer_accepted }),
  });
  const data = await _json(res);
  if (res.ok && data.session_token) sessionStorage.setItem("acordly_tk", data.session_token);
  return { ok: res.ok, data };
}

export async function logoutUser() {
  sessionStorage.removeItem("acordly_tk");
  await fetch(`${API_BASE}/api/auth/logout`, {
    method: "POST",
    credentials: "include",
  });
}

export async function saveSignature(signature_data) {
  const res = await fetch(`${API_BASE}/api/auth/save-signature`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ signature_data }),
  });
  return { ok: res.ok, status: res.status, data: await _json(res) };
}

export async function getSignature() {
  const res = await fetch(`${API_BASE}/api/auth/get-signature`, { credentials: "include" });
  return res.ok ? _json(res) : null;
}
