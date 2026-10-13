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

// The primary button's words before anything is applied.
export function applyLabel(facts, values, touched) {
  const { confirming, send } = fieldsToApply(facts, values, touched);
  if (!confirming) return "Apply";
  return send.length > 1 ? "Confirm these values" : "Confirm this value";
}
