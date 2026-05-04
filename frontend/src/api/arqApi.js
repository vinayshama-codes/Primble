import { API_BASE } from "../config/constants";

export async function generateArqQuestions(session_id) {
  const res = await fetch(`${API_BASE}/api/arq/generate/${session_id}`, { credentials: "include" });
  return { ok: res.ok, status: res.status, data: await res.json() };
}

export async function sendArq(payload) {
  const res = await fetch(`${API_BASE}/api/arq/send`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return { ok: res.ok, status: res.status, data: await res.json() };
}

export async function getArqStatus(arq_id) {
  const res = await fetch(`${API_BASE}/api/arq/status/${arq_id}`, { credentials: "include" });
  return { ok: res.ok, data: await res.json() };
}

export async function listArqSessions(session_id) {
  const res = await fetch(`${API_BASE}/api/arq/list/${session_id}`, { credentials: "include" });
  return { ok: res.ok, data: await res.json() };
}

export async function sendArqReminder(arq_id) {
  const res = await fetch(`${API_BASE}/api/arq/remind/${arq_id}`, {
    method: "POST",
    credentials: "include",
  });
  return { ok: res.ok, data: await res.json() };
}

export async function getArqNotifications() {
  const res = await fetch(`${API_BASE}/api/arq/notifications`, { credentials: "include" });
  return { ok: res.ok, data: await res.json() };
}

export async function markArqNotificationsRead() {
  await fetch(`${API_BASE}/api/arq/notifications/read`, {
    method: "POST",
    credentials: "include",
  });
}

export async function getClientFilledFields(session_id) {
  const res = await fetch(`${API_BASE}/api/arq/client-filled/${session_id}`, { credentials: "include" });
  return res.ok ? (await res.json()).client_filled_fields || [] : [];
}
