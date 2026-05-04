import { API_BASE } from "../config/constants";

export async function uploadDeclaration(files) {
  const fd = new FormData();
  files.forEach((f) => fd.append("files", f));
  const res = await fetch(`${API_BASE}/api/upload-declaration`, {
    method: "POST",
    credentials: "include",
    body: fd,
  });
  return { ok: res.ok, status: res.status, data: await res.json() };
}

export async function selectFormsBulk(session_id, form_ids) {
  const res = await fetch(`${API_BASE}/api/select-forms-bulk`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id, form_ids }),
  });
  return { ok: res.ok, status: res.status, data: await res.json() };
}

export async function updatePdf(session_id, field_updates) {
  const res = await fetch(`${API_BASE}/api/update-pdf`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id, field_updates }),
  });
  return { ok: res.ok, data: await res.json() };
}

export async function applySignatureApi(session_id, form_id) {
  const res = await fetch(`${API_BASE}/api/apply-signature/${session_id}/${form_id}`, {
    method: "POST",
    credentials: "include",
  });
  return { ok: res.ok, data: await res.json() };
}

export async function sendToEpicApi(session_id, form_id) {
  const res = await fetch(`${API_BASE}/api/send-to-epic/${session_id}/${form_id}`, {
    credentials: "include",
  });
  return { ok: res.ok, data: await res.json() };
}

export async function confirmAcordLicense() {
  const res = await fetch(`${API_BASE}/api/acord/confirm-license`, {
    method: "POST",
    credentials: "include",
  });
  return { ok: res.ok, data: await res.json() };
}

export async function getSessionApi(session_id) {
  const res = await fetch(`${API_BASE}/api/session/${session_id}`, {
    credentials: "include",
  });
  return res.ok ? res.json() : null;
}
