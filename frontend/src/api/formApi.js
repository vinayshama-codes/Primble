import { API_BASE } from "../config/constants";

export async function uploadDeclaration(token, files) {
  const fd = new FormData();
  files.forEach((f) => fd.append("files", f));
  const res = await fetch(`${API_BASE}/api/upload-declaration`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: fd,
  });
  return { ok: res.ok, status: res.status, data: await res.json() };
}

export async function selectFormsBulk(token, session_id, form_ids) {
  const res = await fetch(`${API_BASE}/api/select-forms-bulk`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ session_id, form_ids }),
  });
  return { ok: res.ok, status: res.status, data: await res.json() };
}

export async function updatePdf(token, session_id, field_updates) {
  const res = await fetch(`${API_BASE}/api/update-pdf`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ session_id, field_updates }),
  });
  return { ok: res.ok, data: await res.json() };
}

export async function applySignatureApi(token, session_id, form_id) {
  const res = await fetch(`${API_BASE}/api/apply-signature/${session_id}/${form_id}`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
  return { ok: res.ok, data: await res.json() };
}

export async function sendToEpicApi(token, session_id, form_id) {
  const res = await fetch(`${API_BASE}/api/send-to-epic/${session_id}/${form_id}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return { ok: res.ok, data: await res.json() };
}

export async function confirmAcordLicense(token) {
  const res = await fetch(`${API_BASE}/api/acord/confirm-license`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
  return { ok: res.ok, data: await res.json() };
}

export async function getSessionApi(token, session_id) {
  const res = await fetch(`${API_BASE}/api/session/${session_id}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return res.ok ? res.json() : null;
}