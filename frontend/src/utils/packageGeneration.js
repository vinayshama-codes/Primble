// packageGeneration.js - the package page once forms exist (Orbin item 1,
// 1 Oct 2026).
//
// Clicking a package always lands on its package page. Whether its forms were
// never generated, are being generated, were generated, or did not finish comes
// from the backend's one door (services/generation_state.py) as
// `generation_state` on GET /api/session. This file reads that answer and holds
// the wording the package page prints for it, so the rail layout, the classic
// layout and the footer button can never disagree.
//
// Pure: no React, no fetch.

export const GEN_NONE = "none";
export const GEN_RUNNING = "running";
export const GEN_DONE = "done";
export const GEN_INTERRUPTED = "interrupted";

// Word for word the backend's refusals (generation_state.forms_locked_reason);
// a test keeps them equal.
export const FORMS_LOCKED_TEXT = "Forms are generated - make changes in the form editor.";
export const FORMS_RUNNING_TEXT = "Forms are being generated - wait for them to finish.";
export const GENERATION_DIDNT_FINISH = "Generation didn't finish";
export const GENERATION_DIDNT_FINISH_NEXT = "Continue to form selection to generate the forms again.";
export const GENERATION_RUNNING_TEXT = "Your forms are being generated.";

export const CONTINUE_WHERE_LEFT = "Continue where you left off";
export const CONTINUE_TO_SELECTION = "Continue to form selection";

const KNOWN = new Set([GEN_NONE, GEN_RUNNING, GEN_DONE, GEN_INTERRUPTED]);

const hasForms = (generated) =>
  !!generated && typeof generated === "object" && Object.keys(generated).length > 0;

// The package's generation state from a GET /api/session payload. The server's
// own answer wins; an older server without it is read the way the resume code
// always read it (forms -> done, a job marker -> running, else none).
export function generationStateOf(data) {
  if (!data || typeof data !== "object") return GEN_NONE;
  const s = data.generation_state;
  if (KNOWN.has(s)) return s;
  if (hasForms(data.generated_forms)) return GEN_DONE;
  if (data.generation_job_id) return GEN_RUNNING;
  return GEN_NONE;
}

// The generated forms in the producer's order: the server's `form_order`, then
// any form it did not list (the session row's JSONB sorts keys, ACORD_25 before
// ACORD_125, so the object's own order is never the producer's).
export function orderedFormIds(generated, order) {
  if (!hasForms(generated)) return [];
  const ids = [];
  for (const f of Array.isArray(order) ? order : []) {
    if (Object.prototype.hasOwnProperty.call(generated, f) && !ids.includes(f)) ids.push(f);
  }
  for (const f of Object.keys(generated)) if (!ids.includes(f)) ids.push(f);
  return ids;
}

// The same forms object, re-keyed in that order (an object keeps insertion
// order for string keys), so every list built from it reads the same way.
export function inProducerOrder(generated, order) {
  const out = {};
  for (const f of orderedFormIds(generated, order)) out[f] = generated[f];
  return out;
}

// The form "Continue where you left off" opens: the one asked for, else the
// last one open, else the first in the producer's order.
export function formToOpen(generated, order, preferred, lastOpen) {
  const ids = orderedFormIds(generated, order);
  if (!ids.length) return null;
  if (preferred && ids.includes(preferred)) return preferred;
  if (lastOpen && ids.includes(lastOpen)) return lastOpen;
  return ids[0];
}

// Why the pre-form actions (reclassify, exclude, confirm a value, resolve
// integrity, add a form by ticking it) are switched off, or null.
export function lockedReason(state) {
  if (state === GEN_DONE) return FORMS_LOCKED_TEXT;
  if (state === GEN_RUNNING) return FORMS_RUNNING_TEXT;
  return null;
}

// "Continue where you left off" once forms exist or are on their way;
// "Continue to form selection" otherwise - including after a run that did not
// finish, which is the way to generate them again.
export function continueLabel(state) {
  return state === GEN_DONE || state === GEN_RUNNING ? CONTINUE_WHERE_LEFT : CONTINUE_TO_SELECTION;
}

// The score's name on the package page: the number IS the Total Package Score
// once forms exist (the backend returns the persisted editor score then);
// before that it is the score so far.
export function scoreHeading(state) {
  return state === GEN_DONE ? "Total Package Score" : "Score so far";
}

// One row per generated form for the package page's list: label, the form's
// own score and tier. Missing scores stay null (printed as "Not scored").
export function formRows(generated, order) {
  return orderedFormIds(generated, order).map((formId) => {
    const sqs = (generated[formId] && generated[formId].sqs) || {};
    const raw = sqs.sqs_score;
    const score = (typeof raw === "number" || (typeof raw === "string" && raw.trim() !== ""))
      && Number.isFinite(Number(raw)) ? Number(raw) : null;
    return {
      formId,
      label: String(formId).replace(/_/g, " ").trim(),
      score,
      grade: typeof sqs.grade === "string" && sqs.grade ? sqs.grade : null,
      tier: typeof sqs.tier === "string" && sqs.tier ? sqs.tier : null,
    };
  });
}
