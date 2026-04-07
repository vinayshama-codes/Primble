import { API_BASE } from "../config/constants";

export async function generateArqQuestions(token, session_id) {
  const res = await fetch(`${API_BASE}/api/arq/generate/${session_id}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return { ok: res.ok, status: res.status, data: await res.json() };
}

export async function sendArq(token, payload) {
  const res = await fetch(`${API_BASE}/api/arq/send`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify(payload),
  });
  return { ok: res.ok, status: res.status, data: await res.json() };
}

export async function getArqStatus(token, arq_id) {
  const res = await fetch(`${API_BASE}/api/arq/status/${arq_id}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return { ok: res.ok, data: await res.json() };
}

export async function listArqSessions(token, session_id) {
  const res = await fetch(`${API_BASE}/api/arq/list/${session_id}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return { ok: res.ok, data: await res.json() };
}

export async function sendArqReminder(token, arq_id) {
  const res = await fetch(`${API_BASE}/api/arq/remind/${arq_id}`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
  return { ok: res.ok, data: await res.json() };
}

export async function getArqNotifications(token) {
  const res = await fetch(`${API_BASE}/api/arq/notifications`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return { ok: res.ok, data: await res.json() };
}

export async function markArqNotificationsRead(token) {
  await fetch(`${API_BASE}/api/arq/notifications/read`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
}

export async function getClientFilledFields(token, session_id) {
  const res = await fetch(`${API_BASE}/api/arq/client-filled/${session_id}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return res.ok ? (await res.json()).client_filled_fields || [] : [];
}