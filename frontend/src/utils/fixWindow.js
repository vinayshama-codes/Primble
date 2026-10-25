// What "Apply" sends from the fix window's typed inputs (Brent's Choice
// Electric #18, 10 Oct 2026). Pure: no React.
//
// The window pre-fills each box with the value already on file. Apply used to
// send only the boxes the producer TYPED in - so a window showing the right
// values answered Apply with "Enter at least one value.", the error Brent hit.
//
// Now:
//   * the producer typed something -> exactly those boxes go (unchanged: an
//     untouched box is never re-sent beside a typed one, where re-checking the
//     value on file could refuse a box they never meant to change);
//   * nothing typed, and the window shows values -> those values go as the
//     producer's confirmation, and the button says so ("Confirm this value");
//   * nothing to send -> say what is missing.

const shownValue = (v) => String(v ?? "").trim();

// { send: [[fact, value], ...], confirming, error }
// `allowConfirm: false` - the window already applied something and asks for
// one more value ("fill in X above and apply again"): only a typed box goes.
export function fieldsToApply(facts, values, touched, { allowConfirm = true } = {}) {
  const list = Array.isArray(facts) ? facts : [];
  const vals = values || {};
  const hasTouched = (f) => !!touched && typeof touched.has === "function" && touched.has(f);
  const typed = list.filter((f) => hasTouched(f) && shownValue(vals[f]));
  if (typed.length) {
    return { send: typed.map((f) => [f, shownValue(vals[f])]), confirming: false, error: null };
  }
  const shown = list.filter((f) => shownValue(vals[f]));
  if (allowConfirm && !list.some(hasTouched) && shown.length) {
    return { send: shown.map((f) => [f, shownValue(vals[f])]), confirming: true, error: null };
  }
  return {
    send: [],
    confirming: false,
    error: shown.length && allowConfirm
      ? "Type the correct value, or close this window to keep what is on file."
      : "Enter at least one value.",
  };
}

// Every value one save sends, as { fact: value } (21 Oct 2026 review, M2). The
// window posts its boxes one request at a time; each request carries the whole
// save so the server judges a pair (the proposed effective and expiration
// dates) as the save, never box by box - moving both dates forward is never
// refused on the first box, and a backwards pair is refused before anything
// is written.
export function sameSave(send) {
  const out = {};
  (Array.isArray(send) ? send : []).forEach((pair) => {
    if (Array.isArray(pair) && pair.length >= 2 && String(pair[0] ?? "").trim()) {
      out[String(pair[0]).trim()] = String(pair[1] ?? "");
    }
  });
  return out;
}

// The primary button's words before anything is applied.
export function applyLabel(facts, values, touched) {
  const { confirming, send } = fieldsToApply(facts, values, touched);
  if (!confirming) return "Apply";
  return send.length > 1 ? "Confirm these values" : "Confirm this value";
}

// The columns a table fix window shows (21 Oct 2026, Brent's item 8: "ask only
// what is missing"). A window the server scoped (`show_columns` - each
// building's identity cells, then the cells it asks for; services/premises_cope)
// shows those, in the table's own order, and always every column it asks for
// (`columns`). Any other window - or a scope naming nothing the table has -
// shows the whole table, as before: a window never opens on an empty table.
// The rows keep every cell either way, so a save never drops a hidden one.
export function windowColumns(columns, resolution) {
  const all = Array.isArray(columns) ? columns.filter((c) => c && typeof c === "object") : [];
  const show = Array.isArray(resolution?.show_columns) ? resolution.show_columns : [];
  if (!show.length) return all;
  const asked = Array.isArray(resolution?.columns) ? resolution.columns : [];
  const keep = new Set([...show, ...asked].map((k) => String(k ?? "").trim()).filter(Boolean));
  const out = all.filter((c) => keep.has(c.key));
  return out.length ? out : all;
}

// Does a table window's save send the table? When the table was edited, or when
// nothing else was typed - as before (an untouched table beside a typed box is
// not re-saved, so a later document re-read can still refresh it). And when the
// window shows cells every building already states that the submission still
// lacks (`confirm_columns`, services/premises_cope, 21 Oct 2026): only a save of
// the table carries them to the submission, so a typed box beside them must not
// leave them behind - the card would stay open with nothing left to type.
export function tableIsSaved({ typedOne = false, rowsTouched = false, resolution = null } = {}) {
  if (!typedOne || rowsTouched) return true;
  return Array.isArray(resolution?.confirm_columns) && resolution.confirm_columns.length > 0;
}

// Did a save from a recommendation CARD's table window close that card? (21 Oct
// 2026: a table saved as progress - building 1 of 2 - was filed as answered.)
// Read off the recomputed form scores the save returns (`updated_forms[*]
// .new_sqs.recommendations`): closed only when at least one form score came back
// and none of them still carries the card. No scores to read = not closed.
export function recClosedBySave(data, recId) {
  const forms = data && typeof data === "object" ? data.updated_forms : null;
  if (!recId || !forms || typeof forms !== "object") return false;
  const lists = Object.values(forms)
    .map((u) => (u && Array.isArray(u.new_sqs?.recommendations) ? u.new_sqs.recommendations : null))
    .filter(Boolean);
  if (!lists.length) return false;
  return !lists.some((recs) => recs.some((r) => r && typeof r === "object" && r.rec_id === recId));
}
