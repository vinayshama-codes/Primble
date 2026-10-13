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
  verify:       { label: "Please verify", bg: "rgb(254,215,170)", fg: "#9a3412", hint: "Filled by the AI or calculated by us. Confirm it or correct it." },
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

// THE DOWNLOAD REVIEW'S COUNTS (Brent's Choice Electric #27, 10 Oct 2026). The
// headline read "176 items flagged": every open card plus every needs-attention
// row - Please verify and AI held back included - added into one number. On the
// owner's run `2076fe35` that was 190, of which 47 were things to FIX: the hard
// stops (a required box blocking the download included) and the Missing boxes
// the producer fills. The rest are listed, and counted, as what they are.
const isHardRec = (r) => r?.recommendation_type === "hard_stop"
  || String(r?.rec_id || "").includes("hardblock_");

export function downloadReviewCounts(openRecs, attention) {
  const recs = Array.isArray(openRecs) ? openRecs : [];
  const rows = (Array.isArray(attention?.forms) ? attention.forms : [])
    .flatMap((f) => (Array.isArray(f?.rows) ? f.rows : []));
  const hard = recs.filter(isHardRec).length;
  const missing = rows.filter((r) => r?.status === "missing" && !isApplicantStep(r)).length;
  const counts = {
    hard,
    missing,
    applicant: rows.filter(isApplicantStep).length,
    verify: rows.filter((r) => r?.status === "verify").length,
    heldBack: rows.filter((r) => r?.status === "ai_held_back").length,
    choices: Array.isArray(attention?.document_suggestions) ? attention.document_suggestions.length : 0,
    recommendations: recs.length - hard,
  };
  counts.toFix = hard + missing;
  counts.total = recs.length + rows.length + counts.choices;
  return counts;
}

const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

// "26 to verify, 93 held back by the AI, ..." - everything listed that is not a
// thing to fix, nonzero parts only; "" when there is none.
export function alsoListedText(c) {
  if (!c) return "";
  return [
    c.verify ? `${c.verify} to verify` : "",
    c.heldBack ? `${c.heldBack} held back by the AI` : "",
    c.applicant ? `${c.applicant} for the applicant to sign` : "",
    c.choices ? plural(c.choices, "new-document choice", "new-document choices") : "",
    c.recommendations ? plural(c.recommendations, "recommendation", "recommendations") : "",
  ].filter(Boolean).join(", ");
}

// The review's one-line headline.
export function downloadReviewHeadline(c) {
  if (!c || !c.total) return "All clear - review the SQS summary below";
  if (!c.toFix) return "Nothing to fix - look over the list before downloading";
  return `${plural(c.toFix, "item", "items")} to fix - review before downloading`;
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

