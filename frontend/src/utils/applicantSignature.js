// The producer's view of the applicant's signature (Orbin item 14, 1 Oct
// 2026): the status read and the one line each form prints. Pure helpers, kept
// apart from the components (react-refresh).
import { API_BASE } from "../config/constants";

export const fmtDate = (iso) => {
  try { return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" }); }
  catch { return ""; }
};

export const SIGNATURE_STALE_TEXT = "Signature no longer matches - send for signature again.";

export async function fetchSignatureStatus(sessionId) {
  if (!sessionId) return null;
  try {
    const res = await fetch(`${API_BASE}/api/applicant-sign/${encodeURIComponent(sessionId)}/status`, { credentials: "include" });
    const body = res.ok ? await res.json() : null;
    return body?.success ? body : null;
  } catch { return null; }
}

// One line per form the applicant signs.
export function formSignatureLine(f) {
  if (f.state === "signed") return `Signed on ${f.signed_date || fmtDate(f.signed_at)}${f.signer_name ? ` by ${f.signer_name}` : ""}`;
  if (f.state === "stale") return SIGNATURE_STALE_TEXT;
  return "Not signed yet";
}

