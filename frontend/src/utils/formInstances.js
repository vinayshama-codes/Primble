// formInstances.js - one ACORD form generated more than once (7 Oct 2026).
// The JS twin of backend/services/form_instances.py: "ACORD_131__excess" is the
// Excess layer's ACORD 131. Use these helpers wherever a form id is SHOWN; the
// backend owns which files and rules an id maps to.

export const SEPARATOR = "__";
const KEY_RE = /^[a-z][a-z0-9-]{0,31}$/;
const LABEL_WORDS = { excess: "Excess" };

export function isInstance(formId) {
  const s = String(formId || "");
  const i = s.indexOf(SEPARATOR);
  if (i <= 0) return false;
  return KEY_RE.test(s.slice(i + SEPARATOR.length));
}

export function baseFormId(formId) {
  const s = String(formId || "");
  return isInstance(s) ? s.slice(0, s.indexOf(SEPARATOR)) : s;
}

export function instanceKey(formId) {
  const s = String(formId || "");
  return isInstance(s) ? s.slice(s.indexOf(SEPARATOR) + SEPARATOR.length) : null;
}

// "ACORD_131" -> "ACORD 131"; "ACORD_131__excess" -> "ACORD 131 (Excess)";
// "ACORD_131__excess-2" -> "ACORD 131 (Excess 2)".
export function formLabel(formId) {
  const base = baseFormId(formId).replace(/_/g, " ").trim();
  const key = instanceKey(formId);
  if (!key) return base;
  const dash = key.indexOf("-");
  const stem = dash >= 0 ? key.slice(0, dash) : key;
  const num = dash >= 0 ? key.slice(dash + 1) : "";
  const word = LABEL_WORDS[stem] || stem.charAt(0).toUpperCase() + stem.slice(1);
  return `${base} (${word}${num ? " " + num : ""})`;
}

// A download file stem - the backend's `form_instances.file_stem`:
// "ACORD_131" -> "ACORD_131"; "ACORD_131__excess" -> "ACORD_131_Excess";
// "ACORD_131__excess-2" -> "ACORD_131_Excess2".
export function fileStem(formId) {
  const base = baseFormId(formId);
  const key = instanceKey(formId);
  if (!key) return base;
  const dash = key.indexOf("-");
  const stem = dash >= 0 ? key.slice(0, dash) : key;
  const num = dash >= 0 ? key.slice(dash + 1) : "";
  const word = LABEL_WORDS[stem] || stem.charAt(0).toUpperCase() + stem.slice(1);
  return `${base}_${word}${num}`;
}
