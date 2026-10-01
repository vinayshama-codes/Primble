// The form viewer's box helpers - Orbin 22 Sep items 10 and 18 (30 Sep 2026).
//
// Pure functions, no React and no DOM, so one geometry is shared by the edit
// overlay and the double-click hit test, and a node test can run them.
//
// Item 10: "producers will want to click directly on the form to fix fields,
// so maybe allow double-click edit." `hitTestBox` finds the box under a
// double-click in view mode, measured exactly as the edit overlay draws it.
//
// Item 18: "all yes and no questions need to be highlighted and editable ...
// I could not edit them on 126 or 127, but I can on 186." On 126 / 127 ACORD
// draws the Y/N box as a strip at the top of a taller answer cell, so the
// server now sends that cell (`answer_rect`) and the whole cell is the target.

// The smallest box the overlay draws, in canvas pixels.
export const MIN_BOX_W = 18;
export const MIN_BOX_H = 14;

// A value that prints nothing on the form.
export const isBlankBoxValue = (v) => {
  const s = (v ?? "").toString().trim();
  return !s || s === "null" || s === "None" || s === "Off";
};

// The label a box carries while it holds the client's questionnaire answer.
export const CLIENT_VALUE_LABEL = "client_arq";

// Orbin item 17 (1 Oct 2026): green "Client" only while the CLIENT'S value is
// in the box - the box's own current label says so (`client_arq`), it prints
// something, and it still holds the value that label was saved with. A name on
// the client-filled list proves only that the client once answered it: a
// producer who retypes the box owns it (the server relabels it "producer" on
// save), and an unsaved retype is already not the client's value.
export const isClientValueBox = (label, value, savedValue) =>
  label === CLIENT_VALUE_LABEL
  && !isBlankBoxValue(value)
  && String(value ?? "") === String(savedValue ?? "");

// A PDF-space rect ({x, y, width, height}, origin bottom-left) as the overlay
// draws it: canvas pixels from the top-left, never smaller than the minimum.
export const boxPixelRect = (rect, scale, pageHeight) => {
  const r = rect || {};
  const x = Number(r.x) || 0;
  const y = Number(r.y) || 0;
  const w = Number(r.width) || 0;
  const h = Number(r.height) || 0;
  return {
    left: x * scale,
    top: (pageHeight - y - h) * scale,
    width: Math.max(w * scale, MIN_BOX_W),
    height: Math.max(h * scale, MIN_BOX_H),
  };
};

// Where a click may land for this box: a Y/N box's printed answer cell when
// the server sent one, otherwise the box itself.
export const boxHitRect = (field) =>
  (field && field.yes_no && field.answer_rect) ? field.answer_rect : field?.rect;

// The box under canvas pixel (px, py) on page `pageIdx` (0-based), or null.
// Two boxes can overlap on a real form; the smaller one is the one the
// producer is pointing at.
export const hitTestBox = (fields, pageIdx, px, py, scale, pageHeight) => {
  if (!Array.isArray(fields) || !(scale > 0) || !Number.isFinite(px) || !Number.isFinite(py)) return null;
  let best = null;
  let bestArea = Infinity;
  for (const f of fields) {
    if (!f || f.page !== pageIdx) continue;
    const r = boxHitRect(f);
    if (!r) continue;
    const b = boxPixelRect(r, scale, pageHeight);
    if (px < b.left || px > b.left + b.width || py < b.top || py > b.top + b.height) continue;
    const area = b.width * b.height;
    if (area < bestArea) { best = f; bestArea = area; }
  }
  return best;
};

const YES_WORDS = new Set(["y", "yes", "true"]);
const NO_WORDS = new Set(["n", "no", "false"]);

// What a one-letter Y/N box holds after a keystroke: "Y", "N" or "".
//   raw      the input's value after the keystroke
//   previous what the box held before it
//   caret    the input's selectionStart after the keystroke (optional)
// "yes" / "no" (typed or pasted) become ACORD's letter. One letter typed
// beside the one already there replaces it, so switching an answer never
// needs a delete first. A delete clears the box. Anything else is not a Y/N
// answer and the box keeps what it had - a stray key never blanks an answer.
export const normalizeYesNoEntry = (raw, previous = "", caret = null) => {
  const s = (raw ?? "").toString();
  const t = s.trim().toLowerCase();
  if (!t) return "";
  if (YES_WORDS.has(t)) return "Y";
  if (NO_WORDS.has(t)) return "N";
  const prev = (previous ?? "").toString();
  if (s.length === prev.length + 1) {
    const at = Number.isInteger(caret) && caret > 0 && caret <= s.length ? caret - 1 : s.length - 1;
    const typed = s.charAt(at).toLowerCase();
    if (typed === "y") return "Y";
    if (typed === "n") return "N";
  }
  if (s.length < prev.length) return "";
  const kept = prev.trim().toUpperCase();
  return kept === "Y" || kept === "N" ? kept : prev;
};

// True when no box of this Y/N question holds an answer. A text box is its
// own question; a Yes/No checkbox pair shares one `yn_group`.
export const isYesNoQuestionBlank = (field, fields, values) => {
  if (!field || !field.yn_question) return false;
  const group = field.yn_group || field.name;
  const vals = values || {};
  const members = (fields || []).filter(f => f && (f.yn_group || f.name) === group && f.yn_question);
  const list = members.length ? members : [field];
  return list.every(f => isBlankBoxValue(vals[f.name] ?? f.value));
};
