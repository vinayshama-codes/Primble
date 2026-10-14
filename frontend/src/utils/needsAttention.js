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

// THE DOWNLOAD REVIEW (owner, 14 Oct 2026). Brent: "the download modal is
// flooded with what appears to be new flags". Two rules:
//   1. It lists only what an earlier screen showed and is still open (the
//      server decides the rows: `needs_attention.download_review_rows`).
//   2. It lists ONE BY ONE only the items to fix - hard stops (the download
//      gate's boxes included), warnings, recommendation cards and Missing
//      boxes. "Please verify", "AI held back", the applicant's signing steps
//      and new-document choices are each ONE line with its count and a Show
//      link that opens the group in place. Nothing is hidden; it is not a
//      flood. The headline counts the listed fix-items only; each group line
//      carries its own count. (Before: Choice Electric #27, 10 Oct - the
//      headline counted hard stops + Missing, the rest named on one line.)
const isHardRec = (r) => r?.recommendation_type === "hard_stop"
  || String(r?.rec_id || "").includes("hardblock_");
const isWarningRec = (r) => !isHardRec(r) && r?.recommendation_type === "soft_warning";

// ONE PROBLEM, ONE LINE. A box the download gate holds is a side-panel row
// (`blocks_download`) AND a hard stop: listed once, under Hard Stops - its row
// is left out only when a hard stop names that very box, so nothing is lost if
// the hard stops did not load. A Missing or AI-held-back box whose fact a
// listed card or issue fixes (`fix_facts`, from the server) is that line's.
const boxKey = (formId, field) => `${formId || ""}\u0000${field || ""}`;
const absorbable = (r) => !r?.blocks_download
  && ((r?.status === "missing" && !isApplicantStep(r)) || r?.status === "ai_held_back");

export function withoutListedBoxes(openRecs, attention) {
  const recs = Array.isArray(openRecs) ? openRecs : [];
  const boxes = new Set(recs
    .filter((r) => String(r?.rec_id || "").includes("hardblock_") && r?.field && (r?.component || r?.form_id))
    .map((r) => boxKey(r.component || r.form_id, r.field)));
  const facts = new Set(recs.flatMap((r) => (Array.isArray(r?.fix_facts) ? r.fix_facts : [])));
  if (!attention || (!boxes.size && !facts.size) || !Array.isArray(attention.forms)) return attention;
  return {
    ...attention,
    forms: attention.forms.map((f) => ({
      ...f,
      rows: (Array.isArray(f?.rows) ? f.rows : []).filter((r) =>
        !boxes.has(boxKey(r?.form_id || f?.form_id, r?.field))
        && !(absorbable(r) && r?.fact_key && facts.has(r.fact_key))),
    })),
  };
}

// The review's parts, each list exactly as drawn. `missing` / `verify` /
// `heldBack` / `applicant` are per form ([{ form_id, form_label, rows }]).
export function downloadReviewParts(openRecs, attention) {
  const recs = Array.isArray(openRecs) ? openRecs : [];
  const listed = withoutListedBoxes(recs, attention);
  const forms = Array.isArray(listed?.forms) ? listed.forms : [];
  // ONE split for the side panel, the review and its counts: `attentionGroups`.
  const split = forms.map((f) => ({ f, by: Object.fromEntries(attentionGroups(f?.rows).map((g) => [g.key, g.rows])) }));
  const byForm = (key) => split
    .map(({ f, by }) => ({ form_id: f?.form_id, form_label: f?.form_label || f?.form_id, rows: by[key] || [] }))
    .filter((f) => f.rows.length > 0);
  const gate = (r) => String(r?.rec_id || "").includes("hardblock_");
  return {
    // the download gate's boxes first (it is what a clean download waits on)
    hard: [...recs.filter(gate), ...recs.filter((r) => isHardRec(r) && !gate(r))],
    warnings: recs.filter(isWarningRec),
    recommendations: recs.filter((r) => !isHardRec(r) && !isWarningRec(r)),
    missing: byForm("missing"),
    verify: byForm("verify"),
    heldBack: byForm("ai_held_back"),
    applicant: byForm("applicant"),
    choices: Array.isArray(attention?.document_suggestions) ? attention.document_suggestions : [],
  };
}

const rowCount = (groups) => groups.reduce((n, g) => n + g.rows.length, 0);

export function downloadReviewCounts(openRecs, attention) {
  const p = downloadReviewParts(openRecs, attention);
  const counts = {
    hard: p.hard.length,
    warnings: p.warnings.length,
    recommendations: p.recommendations.length,
    missing: rowCount(p.missing),
    verify: rowCount(p.verify),
    heldBack: rowCount(p.heldBack),
    applicant: rowCount(p.applicant),
    choices: p.choices.length,
  };
  // Exactly what is listed one by one ...
  counts.toFix = counts.hard + counts.warnings + counts.recommendations + counts.missing;
  // ... and everything on the screen, the groups by their own counts.
  counts.total = counts.toFix + counts.verify + counts.heldBack + counts.applicant + counts.choices;
  return counts;
}

const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

// The groups shown as ONE line each, in this order, with their words.
export const DOWNLOAD_GROUPS = [
  { key: "verify", one: "value to confirm", many: "values to confirm" },
  { key: "heldBack", one: "value the AI held back", many: "values the AI held back" },
  { key: "applicant", one: "box for the applicant to sign", many: "boxes for the applicant to sign" },
  { key: "choices", one: "new-document choice", many: "new-document choices" },
];

// "45 values to confirm" - the group line's words; "" for an empty group.
export function groupLineText(key, n) {
  const g = DOWNLOAD_GROUPS.find((x) => x.key === key);
  return g && n > 0 ? plural(n, g.one, g.many) : "";
}

// The review's one-line headline: the listed fix-items only.
export function downloadReviewHeadline(c) {
  if (!c || !c.total) return "All clear - review the SQS summary below";
  if (!c.toFix) return "Nothing to fix - look over the groups below before downloading";
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

