import { API_BASE } from "../config/constants";

export async function getActivityLog() {
  const res = await fetch(`${API_BASE}/api/activity`, { credentials: "include" });
  if (!res.ok) return { ok: false, events: [] };
  const data = await res.json();
  return { ok: true, events: data.events || [] };
}
