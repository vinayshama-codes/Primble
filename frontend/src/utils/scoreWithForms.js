// The score and the forms (Brent, 23 Oct 2026, Z34-1 #1: "Yes, this is
// acceptable"). The package score is the same number before and after forms -
// the forms never move it - so the screen prints ONE number. What the forms
// still need is the "Forms ready" meter: the values to confirm and the boxes to
// fill on the generated forms, read off the needs-attention list
// (GET /api/needs-attention, services/needs_attention.py) - never a second
// engine. "Confirm all" moves this meter, not the score.
//
// Replaces the 13 Oct "Without forms X · With forms Y" line (formsEffect).
//
// Pure functions, no React: the backend suite runs them under node.

const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

// A Missing row that is the applicant's own step (sign, date, initial) is not a
// box the producer fills - the same split as utils/needsAttention.attentionGroups.
const isApplicantStep = (row) => row?.status === "missing" && !!row?.applicant_step;

// { verify, missing } for one form's rows.
function rowCounts(rows) {
  const list = Array.isArray(rows) ? rows : [];
  return {
    verify: list.filter((r) => r?.status === "verify").length,
    missing: list.filter((r) => r?.status === "missing" && !isApplicantStep(r)).length,
  };
}

// The counts in words: "3 values to confirm · 1 box to fill".
export function formsReadyDetail(counts) {
  const verify = Number(counts?.verify) || 0;
  const missing = Number(counts?.missing) || 0;
  if (!verify && !missing) return "nothing left to confirm or fill";
  return `${plural(verify, "value", "values")} to confirm · ${plural(missing, "box", "boxes")} to fill`;
}

// The meter's line: "Forms ready: 3 values to confirm · 1 box to fill".
export const formsReadyText = (counts) => `Forms ready: ${formsReadyDetail(counts)}`;

const withWords = (c) => ({ verify: c.verify, missing: c.missing, text: formsReadyText(c), detail: formsReadyDetail(c) });

// The meter for the whole package and, given `formId`, for that form:
// { overall: {verify, missing, text, detail}, form: {...} | null,
//   forms: [{form_id, form_label, verify, missing}] } - or null while the list
// has not loaded (or could not be read), so the screen shows no meter rather
// than a wrong one.
export function formsReady(attention, formId = null) {
  const forms = Array.isArray(attention?.forms) ? attention.forms : null;
  if (!forms) return null;
  const perForm = forms.map((f) => ({ form_id: f?.form_id, form_label: f?.form_label || f?.form_id, ...rowCounts(f?.rows) }));
  const overall = perForm.reduce((t, f) => ({ verify: t.verify + f.verify, missing: t.missing + f.missing }), { verify: 0, missing: 0 });
  const one = formId ? perForm.find((f) => f.form_id === formId) || null : null;
  return { overall: withWords(overall), form: one ? withWords(one) : null, forms: perForm };
}
