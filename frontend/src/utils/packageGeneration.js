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

import { formLabel } from "./formInstances.js";

export const GEN_NONE = "none";
export const GEN_RUNNING = "running";
export const GEN_DONE = "done";
export const GEN_INTERRUPTED = "interrupted";

// Word for word the backend's refusals (generation_state.forms_locked_reason);
// a test keeps them equal.
export const FORMS_LOCKED_TEXT = "Forms are generated - make changes in the form editor.";
export const FORMS_RUNNING_TEXT = "Forms are being generated - wait for them to finish.";
export const GENERATION_DIDNT_FINISH = "Generation didn't finish";
// Names the place, not a button: before forms the rail's footer reads "Skip to
// form selection" on every page but the last (Choice Electric #2).
export const GENERATION_DIDNT_FINISH_NEXT = "Go to form selection to generate the forms again.";
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

// Why the pre-form actions (confirm a value through the pre-form route, resolve
// integrity, add a form by ticking it) are switched off, or null.
export function lockedReason(state) {
  if (state === GEN_DONE) return FORMS_LOCKED_TEXT;
  if (state === GEN_RUNNING) return FORMS_RUNNING_TEXT;
  return null;
}

// Documents are the exception (Choice Electric #25, 7 Oct 2026): adding a
// document, or changing one's type / exclusion / supporting-only, works before
// AND after forms - after forms the server re-stamps the forms from the change
// (backend services/session_documents.py). Only a run in progress locks them,
// word for word the backend's generation_state.documents_locked_reason.
export function documentsLockedReason(state) {
  if (state === GEN_RUNNING) return FORMS_RUNNING_TEXT;
  return null;
}

// What a document change does once forms exist - said before it happens.
export const DOCUMENTS_UPDATE_FORMS_TEXT = "Forms will be updated from this change";
export const DOCUMENTS_AFTER_FORMS_NOTE = "Changes to documents update your generated forms. Boxes you typed are kept.";

// Confirming a Data Consistency value is the exception (owner, 5 Oct 2026):
// once forms exist it goes to /api/underwriting/confirm-value-in-editor, which
// applies the value to the stored facts and re-stamps the forms in place. Only
// a run in progress locks it - its forms are stamped from the facts it read.
export function confirmLockedReason(state) {
  if (state === GEN_RUNNING) return FORMS_RUNNING_TEXT;
  return null;
}

// "Continue where you left off" once forms exist or are on their way;
// "Continue to form selection" otherwise - including after a run that did not
// finish, which is the way to generate them again.
export function continueLabel(state) {
  return state === GEN_DONE || state === GEN_RUNNING ? CONTINUE_WHERE_LEFT : CONTINUE_TO_SELECTION;
}

// Choice Electric #2 (Brent; owner, 9 Oct 2026): before forms, the review's
// main button walks the producer through its pages in rail order - "Continue
// to Documents", "Continue to Submission Integrity", ... - and only the last
// page's button goes to form selection. Until then "Skip to form selection"
// sits beside it, so form selection is always one click away.
export const SKIP_TO_SELECTION = "Skip to form selection";

// The page the main button opens: { id, label } for the page after `current`
// in `sections` ([{ id, label }], rail order), or null when the main button is
// the continue button - on the last page, on a page the list does not hold,
// and on every page once forms exist or are being generated (no form
// selection lies ahead then; it reads "Continue where you left off").
export function nextReviewStep(sections, current, state) {
  if (state === GEN_DONE || state === GEN_RUNNING) return null;
  const list = Array.isArray(sections) ? sections : [];
  const at = list.findIndex((s) => s && s.id === current);
  if (at < 0 || at >= list.length - 1) return null;
  const next = list[at + 1];
  if (!next || !next.id || !next.label) return null;
  return { id: next.id, label: `Continue to ${next.label}` };
}

// The score's name on the package page: the number IS the Total Package Score
// once forms exist (the backend returns the persisted editor score then);
// before that it is the score so far.
export function scoreHeading(state) {
  return state === GEN_DONE ? "Total Package Score" : "Submission Score";
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
      // "ACORD 131", and a form's second copy "ACORD 131 (Excess)" (7 Oct 2026).
      label: formLabel(formId),
      score,
      grade: typeof sqs.grade === "string" && sqs.grade ? sqs.grade : null,
      tier: typeof sqs.tier === "string" && sqs.tier ? sqs.tier : null,
    };
  });
}
