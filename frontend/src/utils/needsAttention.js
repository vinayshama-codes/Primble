import { API_BASE } from "../config/constants";

// Orbin 22 Sep items 9 and 19 (30 Sep 2026): shared pieces of the
// needs-attention list (GET /api/needs-attention, backend door
// services/needs_attention.py). Components live in
// components/form/NeedsAttentionPanel.jsx.

export const ATTENTION_STATUS_ORDER = ["missing", "ai_held_back", "verify"];

// Colours follow the viewer's own legend: Required = yellow, Verify = orange.
export const ATTENTION_TAG_STYLE = {
  missing:      { label: "Missing",       bg: "rgb(254,243,199)", fg: "#92400e", hint: "Required on this form and still empty." },
  ai_held_back: { label: "AI held back",  bg: "#e0e7ff",          fg: "#3730a3", hint: "A value was found but did not fit, so it was left blank." },
  verify:       { label: "Please verify", bg: "rgb(254,215,170)", fg: "#9a3412", hint: "Filled by the AI or calculated by us, and not confirmed in your documents." },
  // The applicant's own steps (sign, date, initial) - not the producer's to fill
  // in (1 Oct 2026). A group of their own wherever the list is drawn.
  applicant:    { label: "Applicant signs", bg: "#f1f5f9", fg: "#475569", hint: "The applicant signs and dates the form before it is sent." },
};

// The heading of the applicant's group, as the download review names it.
export const APPLICANT_GROUP_LABEL = "To be signed by the applicant";

// A Missing row that is the applicant's own step, not a box for the producer.
export const isApplicantStep = (row) => row?.status === "missing" && !!row?.applicant_step;

// The groups a list is drawn in: Missing (the producer's), then the applicant's
// steps, AI held back, Please verify. Pure, so the side panel, the review and
// its counts read one split.
export function attentionGroups(rows) {
  const list = Array.isArray(rows) ? rows : [];
  const groups = [];
  ATTENTION_STATUS_ORDER.forEach((status) => {
    groups.push({ key: status, label: ATTENTION_TAG_STYLE[status].label, fg: ATTENTION_TAG_STYLE[status].fg,
                  rows: list.filter((r) => r?.status === status && !isApplicantStep(r)) });
    if (status === "missing") {
      groups.push({ key: "applicant", label: APPLICANT_GROUP_LABEL, fg: ATTENTION_TAG_STYLE.applicant.fg,
                    rows: list.filter(isApplicantStep) });
    }
  });
  return groups.filter((g) => g.rows.length > 0);
}

// Pre-form (item 9): the "Key details missing" line is the pre-form list, and
// each detail opens its fix (review/KeyDetailsMissing.jsx). The pointer line
// that only SAID where the list would appear was removed (owner, 30 Sep 2026).

export async function fetchNeedsAttention(sessionId, formId, signal) {
  if (!sessionId) return null;
  const q = formId ? `?form_id=${encodeURIComponent(formId)}` : "";
  const res = await fetch(`${API_BASE}/api/needs-attention/${sessionId}${q}`, { credentials: "include", signal });
  if (!res.ok) return null;
  const data = await res.json();
  return data?.success ? data : null;
}

// Stored review rows the live list already shows box by box (the server marks
// them). A failed fetch keeps them all. Otherwise a superseded row is dropped
// PER FORM: kept only for a form the server could not read (its live list is
// missing), so a box is never counted twice (review, 30 Sep). A form-less
// superseded row (the old summary) is kept only when some form failed.
export function withoutSupersededRecs(recs, attention) {
  if (!attention) return recs || [];
  const failed = new Set((attention.forms || []).filter(f => f?.ok === false).map(f => f?.form_id));
  return (recs || []).filter(r => {
    if (!r?.attention_superseded) return true;
    if (r.component) return failed.has(r.component);
    return failed.size > 0;
  });
}

