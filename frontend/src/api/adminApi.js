import { API_BASE } from "../config/constants";

// Returns true only if the logged-in user is a platform admin (email in
// ADMIN_EMAILS). The server gates /api/admin/status with _require_admin, so a
// non-200 response (403) means "not an admin" and the UI stays hidden.
export async function checkAdmin() {
  try {
    const res = await fetch(`${API_BASE}/api/admin/status`, { credentials: "include" });
    if (!res.ok) return false;
    const data = await res.json();
    return !!data.is_admin;
  } catch {
    return false;
  }
}

// Reset a user's ACORD license confirmation by email. They will be prompted to
// re-confirm on their next download.
export async function resetLicense(email) {
  try {
    const res = await fetch(`${API_BASE}/api/admin/reset-license`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email }),
    });
    const data = await res.json().catch(() => ({}));
    return { ok: res.ok, status: res.status, data };
  } catch {
    return { ok: false, status: 0, data: {} };
  }
}

// List all current admins: permanent env-var admins (source: "env", not
// removable here) and database-granted admins (source: "database", removable).
export async function listAdmins() {
  try {
    const res = await fetch(`${API_BASE}/api/admin/admins`, { credentials: "include" });
    if (!res.ok) return { ok: false, status: res.status, admins: [] };
    const data = await res.json();
    return { ok: true, status: res.status, admins: data.admins || [] };
  } catch {
    return { ok: false, status: 0, admins: [] };
  }
}

// Grant admin access to an email via the database (no redeploy needed).
export async function addAdmin(email) {
  try {
    const res = await fetch(`${API_BASE}/api/admin/admins`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email }),
    });
    const data = await res.json().catch(() => ({}));
    return { ok: res.ok, status: res.status, data };
  } catch {
    return { ok: false, status: 0, data: {} };
  }
}

// Revoke a database-granted admin's access. Admins set via the ADMIN_EMAILS
// env var cannot be removed this way (server returns 400 with an explanation).
export async function removeAdmin(email) {
  try {
    const res = await fetch(`${API_BASE}/api/admin/admins?email=${encodeURIComponent(email)}`, {
      method: "DELETE",
      credentials: "include",
    });
    const data = await res.json().catch(() => ({}));
    return { ok: res.ok, status: res.status, data };
  } catch {
    return { ok: false, status: 0, data: {} };
  }
}

// Download the license confirmation audit export (csv default, or json) with
// optional filters. Streams the response to a file download in the browser.
export async function downloadLicenseAudit({ format = "csv", organization = "", since = "", until = "" } = {}) {
  const params = new URLSearchParams();
  params.set("format", format);
  if (organization) params.set("organization", organization);
  if (since) params.set("since", since);
  if (until) params.set("until", until);

  try {
    const res = await fetch(
      `${API_BASE}/api/admin/license-audit-export?${params.toString()}`,
      { credentials: "include" },
    );
    if (!res.ok) return { ok: false, status: res.status };

    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "");
    a.download = `acord_license_audit_${stamp}.${format === "json" ? "json" : "csv"}`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    return { ok: true };
  } catch {
    return { ok: false, status: 0 };
  }
}
