/**
 * Client questionnaire progress (BUG-01, 2026-09-08).
 *
 * The reported defect: the questionnaire opened at "1/11 - 9%" before the
 * client had answered anything. Progress asked "does this field hold content?"
 * when the question it had to answer is "did the CLIENT put content there?".
 *
 * Those differ because a schedule question is deliberately sent PRE-FILLED with
 * the rows extraction (or a producer pre-load) already found - the client edits
 * a known fleet instead of retyping it. Our own pre-fill was counting itself.
 *
 * Kept out of the component, and pure, so the rule can be executed and reasoned
 * about on its own. Every progress-shaped surface in the questionnaire reads it,
 * so the ring, the badge, the per-card styling and the submission receipt cannot
 * drift apart - the receipt used to have its own copy of "answered".
 */

// One definition of "is this row empty?", shared with the table editor and the
// spreadsheet importer. A second copy here would be free to drift from the one
// the client actually sees enforced in the grid.
import { isBlankRow } from './scheduleImport';

export function decodeRows(raw) {
  if (Array.isArray(raw)) return raw;
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function encodeRows(rows) {
  return JSON.stringify(rows || []);
}

/**
 * Is there anything in this value at all?
 *
 * Deliberately type-agnostic at the call site: a schedule holds a JSON array so
 * it is measured by its non-blank ROWS, everything else by its trimmed string.
 * Both reduce to the same idea, so the predicate below never branches on type.
 */
export function hasContent(question, value) {
  if ((question?.field_type) === 'schedule') {
    return decodeRows(value).some((r) => !isBlankRow(r, question.columns || []));
  }
  return String(value ?? '').trim() !== '';
}

/**
 * Has the client responded to this question?
 *
 * `touched` is the set of fields the client has actually edited. It is STICKY -
 * once a field is in it, it never comes out - which is what stops the bar
 * walking backwards when someone deletes five rows and retypes the same five.
 *
 * Three cases, one rule:
 *   * they put something in           -> content now         -> counts
 *   * they cleared what WE pre-filled -> content in the seed  -> counts
 *     ("we do not own those vehicles" is an answer, and a real one)
 *   * they typed then deleted it      -> content neither side -> does not count
 * Untouched is never counted, whatever the box happens to hold.
 *
 * Both halves are load-bearing. Touch alone would count a box someone typed in
 * and cleared; a seed-vs-now diff alone would UNCOUNT the retype case, which is
 * the one direction a progress bar must never move.
 */
export function hasResponded(question, value, seedValue, touched) {
  if (!touched || !touched.has(question?.field_name)) return false;
  return hasContent(question, value) || hasContent(question, seedValue);
}

/**
 * The counts every progress surface renders.
 *
 * `answered` and `notSure` are split because they are different things to the
 * producer - one is data, the other is a follow-up - while both are genuine
 * forward motion for the client and both move the bar. Showing one number with
 * no split is what made "I'm not sure" feel like it did nothing.
 */
export function progressCounts(questions, answers, seed, touched, notSureValue) {
  let answered = 0;
  let notSure = 0;
  (questions || []).forEach((q) => {
    if (!hasResponded(q, answers?.[q.field_name], seed?.[q.field_name], touched)) return;
    if (String(answers?.[q.field_name] ?? '').trim() === notSureValue) notSure += 1;
    else answered += 1;
  });
  const total = (questions || []).length;
  const responded = answered + notSure;
  return {
    answered,
    notSure,
    responded,
    total,
    remaining: Math.max(total - responded, 0),
    pct: total ? Math.round((responded / total) * 100) : 0,
  };
}

/**
 * The key a draft carries to say "my keys ARE the touch record".
 *
 * A draft written by this code holds only the fields the client touched (see
 * `saveDraftToServer`). A draft written before that fix held the whole answer
 * map, pre-fill included.
 */
export const DRAFT_MARKER = '__draft_touched_v2__';

/**
 * Rebuild the touch record from a stored draft.
 *
 * Marked draft: every key in it is a field the client touched. That is the only
 * reading that survives "deleted the rows, then typed the same rows back" - the
 * one case a value comparison cannot see.
 *
 * Unmarked (pre-fix) draft: a key proves nothing, because the old code stored
 * every field including the schedule pre-fill. Restoring those as touched
 * reproduces the reported bug verbatim on reload AND sends our own pre-fill back
 * as a client answer, since `touched` is corroboration the server accepts. So a
 * field counts only where the stored value actually DIFFERS from the seed. That
 * keeps the fix intact for sessions already in flight; the only thing it cannot
 * recover is an edit-then-restore, which self-heals on the client's next edit.
 */
export function restoreTouched(serverDraft, seed) {
  const draft = { ...(serverDraft || {}) };
  const marked = draft[DRAFT_MARKER] != null;
  delete draft[DRAFT_MARKER];
  const keys = marked
    ? Object.keys(draft)
    : Object.keys(draft).filter((k) => draft[k] !== (seed || {})[k]);
  return { answers: draft, touched: new Set(keys) };
}
