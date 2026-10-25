// ResolutionModal.jsx - "Open" a Cross-Form Validation issue and fix it in place.
//
// Client feedback (SQS Panel #13): a producer wanted to click a validation and
// "enter correct responses right there instead of manually navigating to the
// form field(s)". This modal is that surface. It is entirely driven by the
// `resolution` descriptor the backend attaches to every cross-form issue
// (issue_registry.RESOLUTION_MAP), so it stays generic across all 17 forms and
// every rule - adding a rule server-side needs no change here.
//
//   field     -> one labelled input per canonical fact (POST /api/audit/resolve-issue)
//   schedule  -> the shared ScheduleTable (vehicles / locations / ...)
//   narrative -> a textarea appended to the ACORD 101 remarks
//   none      -> read-only detail + the existing Resolve / Dismiss work-tracking
//                controls (a coverage decision, an advisory)
//
// UX-05 (2026-09-08) adds `resolution.add_forms` ALONGSIDE any of those four:
// the ACORD form(s) this validation's own message tells the producer to add,
// already filtered server-side to the ones missing from this package. It is not
// a fifth mode because it composes - `acord101_required` needs the narrative
// box AND the offer to add ACORD 101; `contractor_missing_acord186` is `none`
// mode whose only fix IS the form. The producer used to get Dismiss / Mark
// resolved, neither of which adds anything.

import { useEffect, useRef, useState } from 'react';
import { API_BASE } from '../../config/constants';
import ScheduleTable from '../arq/ScheduleTable';
import { formLabel as instanceFormLabel } from '../../utils/formInstances';
import { positiveScoreWording } from '../../utils/positiveWording';
import { applyLabel, fieldsToApply, sameSave, tableIsSaved, windowColumns } from '../../utils/fixWindow';
import { missingRequiredSummary } from '../../utils/scheduleImport';
import { stillMissing as windowStillMissing, unmetNeeds, rowNeedsSummary, unfinishedStarters, textForCoverage, gapCovered } from '../../utils/fixProgress';
import { composePartLines, partPicks, partsLeft } from '../../utils/partLines';
import { createPreviewer, fetchFollowUps, followUpIssue, followUpIssueId, followUpSaves, prefetchAnswerLists, previewableAnswers, splitFollowUps, warmFollowUps } from '../../utils/followUpPreview';

const PINK = '#E61B84';

// Canonical fact key -> human label. Uppercases the insurance acronyms so
// "gl_each_occurrence" reads "GL Each Occurrence", not "Gl Each Occurrence".
const _ACRONYMS = { acv: 'ACV', bpp: 'BPP', gl: 'GL', wc: 'WC', vin: 'VIN', sir: 'SIR', aop: 'AOP', um: 'UM', uim: 'UIM', bi: 'BI', pd: 'PD', el: 'EL', dba: 'DBA' };
function humanizeFact(key) {
  return String(key || '')
    .split('_')
    .filter(Boolean)
    .map((w) => _ACRONYMS[w] || (w.charAt(0).toUpperCase() + w.slice(1)))
    .join(' ');
}

export default function ResolutionModal({ issue, sessionId, onApplied, onSetStatus, onClose, onOpenFollowUp, onAddDocuments, onFollowUpSaved }) {
  const resolution = issue?.resolution || {};
  const mode = resolution.mode || 'none';
  // A schedule fix may ALSO need a few whole-submission values (Choice
  // Electric #18, 7 Oct 2026): on a package with two or more buildings the
  // COPE card opens the location table for the per-building values, and the
  // values that are not per building (occupancy, valuation) ride along as
  // typed inputs above it - the table never has to hold them.
  const extraFacts = mode === 'schedule' && Array.isArray(resolution.facts) ? resolution.facts.filter(Boolean) : [];
  const fieldFacts = mode === 'field' ? (resolution.facts || []) : extraFacts;
  // The coverage-part window (14 Oct 2026): its one fact lists a choice per part.
  const partLinesWindow = mode === 'field'
    && fieldFacts.some((f) => ((resolution.controls || {})[f] || {}).control === 'part_lines');

  const [values, setValues] = useState({});     // field mode: fact -> typed value
  // Which facts the producer put into "Other" (free-text) mode. Tracked
  // explicitly because it CANNOT be inferred from the value: the old code used
  // `picked === 'Other'`, so the first character typed into the Other box made
  // the condition false, unmounted the box mid-keystroke and blanked the select.
  // "Other" was therefore unusable on every choice field.
  const [otherFacts, setOtherFacts] = useState(() => new Set());
  const setOtherMode = (fact, on) => setOtherFacts((prev) => {
    const next = new Set(prev);
    if (on) next.add(fact); else next.delete(fact);
    return next;
  });
  const [text, setText] = useState('');          // narrative mode: new text to add
  const [existingRemarks, setExistingRemarks] = useState(''); // narrative: what's already saved
  const [schedule, setSchedule] = useState(null); // schedule mode: fetched def + rows
  const [rows, setRows] = useState([]);
  // ONLY the schedule table needs data before it can render at all; field and
  // narrative hold a brief spinner instead, so nothing flashes an empty state
  // before its saved value lands.
  const [loading, setLoading] = useState(mode === 'schedule');
  // Field/narrative modes hydrate their saved values from the server (so
  // reopening a resolved validation shows what was applied). `prefillLoading`
  // gates BOTH behind a spinner until that value lands, instead of flashing an
  // empty box that fills a beat later (client #3, and the same complaint on
  // narrative 2026-09-09 - "Already on ACORD 101" popped in after a second, so
  // for that beat the modal said nothing was saved).
  const [prefillLoading, setPrefillLoading] = useState(mode === 'field' || mode === 'narrative' || extraFacts.length > 0);
  // Bumped after an apply that raised a follow-up, to re-read what is now on
  // file. Without it the producer is asked to "apply again" while looking at
  // the pre-apply snapshot (fix 2026-08-25, live run S10).
  const [prefillNonce, setPrefillNonce] = useState(0);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  // A value CAN apply cleanly and still raise something else - changing an
  // expiration date to clear an expired term misaligns the umbrella's own
  // printed period. The backend returns that as `note`; we hold the modal open
  // and say so, instead of closing on a silent trade. The write already
  // succeeded, so `applied` keeps the authoritative response and EVERY exit
  // path below must still refresh the panel with it.
  const [note, setNote] = useState('');
  // Does the raised issue have an input the producer can still fill HERE? The
  // backend decides (audit_routes._trade_off_settleable_here) so the footer's
  // primary action can never contradict the note's own wording - a note reading
  // "Resolve it from the validation panel" used to sit above a pink "Apply the
  // fix" button, telling the producer to do something unavailable right after a
  // save that had actually succeeded.
  const [noteSettleHere, setNoteSettleHere] = useState(false);
  const applied = useRef(null);
  // Facts the producer has started editing - the async pre-fill must never
  // overwrite these, or a value would jump under the cursor.
  const touched = useRef(new Set());
  // Did the producer change the table? A COPE card on a 2+ building package
  // shows the location table beside its whole-submission inputs (round 4, 7 Oct
  // 2026); answering only those inputs must not save the untouched table, which
  // would mark it as the person's own and keep a later document re-read from
  // refreshing it.
  const rowsTouched = useRef(false);
  const editRows = (next) => { rowsTouched.current = true; setRows(next); };

  // UX-05. Forms this validation says are missing, as the SERVER declared them.
  // Held in state, not read straight off `resolution`, because a successful add
  // must drop that form from the offer immediately - the panel behind refreshes
  // asynchronously and the producer is still looking at this modal.
  const [addForms, setAddForms] = useState(() =>
    (Array.isArray(resolution.add_forms) ? resolution.add_forms : []).filter(Boolean));
  const [addingForm, setAddingForm] = useState(null);   // form id in flight
  const [addedForms, setAddedForms] = useState([]);     // form ids added here
  // "ACORD 131", and a form's second copy "ACORD 131 (Excess)" (7 Oct 2026).
  const formLabel = (fid) => instanceFormLabel(fid);

  // The add's own payload, kept so it survives a LATER apply in the same modal.
  //
  // A composite card does two things in one visit: `acord101_required` needs
  // the form AND the narrative. Adding sets `applied.current`, but
  // applyNarrative / applyField / applySchedule then call `onApplied` with
  // THEIR OWN response, which carries no `added_form` - so the panel never
  // learned the form existed and the Generated Forms list stayed one short
  // until a reload. Reported live 2026-09-09: ACORD 101 was in the package
  // (the validation cleared, which requires it) and absent from the list.
  const addedRef = useRef(null);

  // Follow-up questions (owner, 24 Oct 2026): what the answer chosen here will
  // ask next, shown below it as soon as it is chosen - the server reads the
  // page with the answer written on a copy (backend services/answer_preview).
  // Field windows only; a newer answer's reply always wins (followUpPreview).
  const [followUps, setFollowUps] = useState([]);
  const [fuValues, setFuValues] = useState({});
  const [fuOther, setFuOther] = useState(() => new Set());
  const previewer = useRef(null);
  if (!previewer.current && mode === 'field' && sessionId) {
    previewer.current = createPreviewer(
      (answers, opts) => fetchFollowUps(API_BASE, sessionId, answers, fieldFacts, opts),
      (list) => setFollowUps(Array.isArray(list) ? list : []),
    );
  }
  useEffect(() => () => previewer.current?.cancel(), []);
  // Z38 lane F (speed): on opening, the server reads the page as it stands,
  // then the follow-ups of each choice of a short one-question list are read
  // ahead - picking one shows its follow-ups at once.
  useEffect(() => {
    if (!previewer.current || !sessionId) return;
    let live = true;
    (async () => {
      await warmFollowUps(API_BASE, sessionId);
      if (live) previewer.current?.prefetch(prefetchAnswerLists(fieldFacts, resolution.controls));
    })();
    return () => { live = false; };
    // Once per window: the window's question and session do not change while it is open.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  // Ask with the answers the producer gave in this window (pre-filled values on
  // file are not new answers). Called on a choice, on every change of a typed
  // box and when it is left - a typed value counts only once it reads as a
  // whole answer (Z39 lane G: never a half-typed date), and the previewer's
  // 350 ms debounce asks once per pause.
  const askPreview = (nextValues, left = false) => {
    if (!previewer.current) return;
    const mine = fieldFacts.filter((f) => touched.current.has(f));
    const ctl = resolution.controls || {};
    const typed = (f) => !Array.isArray((ctl[f] || {}).options) || otherFacts.has(f) || nextValues[f] === 'Other';
    previewer.current.request(previewableAnswers(nextValues, mine, ctl, typed, left));
  };
  const onTyped = (fact, text) => {
    touched.current.add(fact);
    setValues((v) => ({ ...v, [fact]: text }));
    askPreview({ ...values, [fact]: text });
    if (err) setErr('');
  };
  const fuSplit = splitFollowUps(followUps);

  // Carry the add forward onto whatever response finally reaches the panel.
  // Never overwrites a fresher field: the later response's `cross_issues`,
  // scores and stop lists win, because they are the ones computed last.
  const withAdded = (data) => (
    addedRef.current && data && !data.added_form
      ? { ...data, ...addedRef.current }
      : data
  );

  // Leave the modal, refreshing the panel if anything was applied while it was
  // open. Cancel, the X, Escape and the backdrop all route through here, so a
  // producer who reads the note and walks away still gets an accurate panel.
  const finish = () => {
    const data = applied.current;
    applied.current = null;
    if (data) onApplied?.(withAdded(data), issue);
    else onClose?.();
  };

  // Pre-fill field inputs (and narrative's "already saved" context) from the
  // current session facts, so reopening a validation shows what was applied.
  // Both modes hold a spinner until this resolves, so a previously-entered
  // value never flashes in a beat after an empty box (client #3).
  useEffect(() => {
    if (mode !== 'field' && mode !== 'narrative' && extraFacts.length === 0) { setPrefillLoading(false); return; }
    let alive = true;
    const facts = mode === 'narrative' ? ['additional_remarks_text'] : fieldFacts;
    (async () => {
      try {
        const q = encodeURIComponent(facts.join(','));
        const res = await fetch(`${API_BASE}/api/audit/issue-values/${sessionId}?facts=${q}`, { credentials: 'include' });
        const data = await res.json();
        if (!alive) return;
        const vals = data?.values || {};
        if (mode !== 'narrative') {
          setValues((prev) => {
            const next = { ...prev };
            for (const [k, v] of Object.entries(vals)) {
              if (!touched.current.has(k) && !String(next[k] || '').trim()) next[k] = v;
            }
            return next;
          });
        } else {
          setExistingRemarks(String(vals.additional_remarks_text || ''));
        }
      } catch {
        /* non-fatal: inputs stay as-is */
      } finally {
        if (alive) setPrefillLoading(false);
      }
    })();
    return () => { alive = false; };
  }, [mode, sessionId, prefillNonce]);  // eslint-disable-line react-hooks/exhaustive-deps

  // Load the current schedule rows + column spec so the producer edits a
  // populated table, not a blank one.
  useEffect(() => {
    if (mode !== 'schedule') return;
    let alive = true;
    (async () => {
      try {
        // Ask for ONLY the schedule this modal needs (client #2). The endpoint
        // otherwise builds, validates and serialises EVERY capturable schedule
        // for the session - expensive on a large fleet - when we use exactly one.
        const key = encodeURIComponent(resolution.schedule_key || '');
        const res = await fetch(`${API_BASE}/api/arq/schedules/${sessionId}?schedule_key=${key}`, { credentials: 'include' });
        const data = await res.json();
        const match = (data?.schedules || []).find((s) => s.schedule_key === resolution.schedule_key);
        if (!alive) return;
        if (!match) {
          setErr('This schedule is not available for the current forms.');
        } else {
          // Ask only what is missing (21 Oct 2026, Brent's item 8): a window the
          // server scoped shows each building's identity and the cells it asks
          // for, not the whole location table. The rows keep every cell.
          setSchedule({ ...match, columns: windowColumns(match.columns, resolution) });
          setRows(Array.isArray(match.rows) ? match.rows : []);
        }
      } catch {
        if (alive) setErr('Could not load the schedule. Please try again.');
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
    // The window's scope (`resolution.show_columns`) is the card it opened for -
    // read once with the table, never a reason to fetch it again.
  }, [mode, sessionId, resolution.schedule_key]);  // eslint-disable-line react-hooks/exhaustive-deps

  // Only the window scrolls (owner, 13 Oct 2026: scrolling a long window also
  // scrolled the faded page behind it - twice: locking the body alone let a wheel
  // over the faded area, or past the window's end, reach the page). The page is
  // held still (html and body, given back exactly as they were - the editor's
  // own lock included, the scrollbar's width kept so nothing shifts), and every
  // wheel over the overlay is the window's: it scrolls whatever inside the window
  // can still scroll that way, and never passes on.
  const overlayRef = useRef(null);
  const cardRef = useRef(null);
  useEffect(() => {
    const html = document.documentElement;
    const body = document.body;
    const prev = [html.style.overflow, body.style.overflow, body.style.paddingRight];
    const scrollbar = window.innerWidth - html.clientWidth;
    html.style.overflow = 'hidden';
    body.style.overflow = 'hidden';
    if (scrollbar > 0) body.style.paddingRight = `${scrollbar}px`;
    const el = overlayRef.current;
    const onWheel = (e) => {
      const card = cardRef.current;
      if (!card || !card.contains(e.target)) { e.preventDefault(); return; }
      // A sideways swipe is a table's (the location / driver tables scroll
      // left and right inside the window).
      const sideways = Math.abs(e.deltaX) > Math.abs(e.deltaY);
      for (let n = e.target; n && n !== card.parentNode; n = n.parentNode) {
        if (n.nodeType !== 1) continue;
        const style = window.getComputedStyle(n);
        const room = sideways
          ? /(auto|scroll)/.test(style.overflowX) && n.scrollWidth > n.clientWidth + 1
            && (e.deltaX > 0 ? n.scrollLeft + n.clientWidth < n.scrollWidth - 1 : n.scrollLeft > 0)
          : /(auto|scroll)/.test(style.overflowY) && n.scrollHeight > n.clientHeight + 1
            && (e.deltaY > 0 ? n.scrollTop + n.clientHeight < n.scrollHeight - 1 : n.scrollTop > 0);
        if (room) return;                  // this element takes the scroll
      }
      e.preventDefault();                  // nothing inside can move that way
    };
    if (el) el.addEventListener('wheel', onWheel, { passive: false });
    return () => {
      if (el) el.removeEventListener('wheel', onWheel);
      [html.style.overflow, body.style.overflow, body.style.paddingRight] = prev;
    };
  }, []);

  // Close on Escape.
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape' && !busy && !addingForm) finish(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [busy, addingForm, onClose]);  // eslint-disable-line react-hooks/exhaustive-deps

  // Returns the parsed body on success, and THROWS an Error whose message is
  // already fit to show a broker on anything else.
  //
  // It used to be `return res.json()` with no status check, so three different
  // failures were indistinguishable: a real {success:false} validation reply, a
  // 500, and a rejected fetch. Every one of them landed in a bare catch that
  // printed one generic sentence. Backend 500s now carry CORS headers
  // (main.py), so the status actually reaches us instead of the browser killing
  // the response and rejecting the fetch.
  const post = async (body) => {
    let res;
    try {
      res = await fetch(`${API_BASE}/api/audit/resolve-issue`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId,
          issue_id: issue?.issue_id ?? null,
          code: issue?.code ?? null,
          form_id: Array.isArray(issue?.forms) ? issue.forms[0] : null,
          ...body,
        }),
      });
    } catch {
      throw new Error('Could not reach the server. Check your connection and try again.');
    }
    let data = null;
    try { data = await res.json(); } catch { data = null; }
    if (!res.ok) {
      // 5xx: the write may or may not have landed before the failure, so we do
      // not claim either way - saying "nothing was saved" and being wrong is
      // how a producer ends up applying the same value twice.
      if (res.status >= 500) {
        throw new Error(`The server hit an error (${res.status}). Your change may not have been saved - close this and check the panel before retrying.`);
      }
      const detail = data?.validation_error || data?.message || data?.detail;
      throw new Error(detail || `That request was rejected (error ${res.status}).`);
    }
    return data || {};
  };

  // `after` (optional): run once the save has landed and the window closed - a
  // follow-up's "Open to fix" / "Add documents" saves the answer above first.
  const applyField = async (after) => {
    // Send the fields the producer typed into. `values` also carries whatever
    // the async pre-fill loaded from the current session facts (so a reopened
    // validation shows what's already on file). Beside a typed box those stay
    // display only: re-sending an untouched pre-filled value re-validates it as
    // a fresh producer answer, which can reject a value the extraction pipeline
    // already accepted (e.g. a peril marked "Not covered") purely because the
    // producer never meant to change it. With NOTHING typed, the shown values
    // are what the producer is confirming (Choice Electric #18 - Apply on a
    // window full of values said "Enter at least one value."): see fixWindow.js.
    // "Save progress" sends only what was typed: confirming the values already
    // on file is a finished fix's step, not a partial one's.
    const { send: filled, error } = fieldsToApply(fieldFacts, values, touched.current,
                                                  { allowConfirm: !note && !progressGap });
    if (!filled.length) {
      setErr(partLinesWindow ? 'Pick a line for at least one coverage part.' : (error || 'Enter at least one value.'));
      return;
    }
    setBusy(true); setErr(''); setNote('');
    let last = null;
    try {
      // Apply each provided fact; each re-runs the rules, the final response is
      // authoritative for the panel refresh. Filling BOTH sides of a trade-off
      // in one go therefore reports no note: the second write clears what the
      // first one raised, and only the last response is read.
      // The whole save rides each request, so the server judges the term pair
      // as one save (fixWindow.sameSave).
      const saveValues = sameSave(filled);
      for (const [field, value] of filled) {
        last = await post({ mode: 'field', field, value, same_save: saveValues });
        if (!last?.success) {
          setErr(last?.validation_error || last?.message || 'Could not apply that value.');
          setBusy(false);
          return;
        }
      }
      // Then the follow-ups typed below it, each under its own row's id so its
      // Resolved / Open again work like the row's own window. Blank ones are
      // not saved - the row appears on the page afterwards, as before.
      const parentNote = last?.note ? last : null;
      for (const { fu, field, value } of followUpSaves(fuSplit.field, fuValues)) {
        const fuIssue = followUpIssue(fu);
        const r = await post({ mode: 'field', field, value, issue_id: followUpIssueId(fu),
                               code: fu.source === 'card' ? (fu.code ?? null) : null });
        if (!r?.success) {
          applied.current = last;
          setErr(`Your answer above is saved. ${fu.label}: ${r?.validation_error || r?.message || 'could not be saved'}`);
          setBusy(false);
          return;
        }
        last = r;
        try { onFollowUpSaved?.(r, fuIssue); } catch { /* tracking only */ }
      }
      if (parentNote && !last?.note) last = { ...last, note: parentNote.note, note_settle_here: parentNote.note_settle_here };
      // Applied, but it raised something else. Hold the modal open on the note
      // so the producer can settle it here instead of discovering it later on
      // the panel and starting the loop again. The value stands either way -
      // `applied` carries it to whichever exit they take.
      if (last?.note) {
        applied.current = last;
        setFuValues({}); setFollowUps([]);       // saved with it; never sent twice
        setNote(String(last.note));
        setNoteSettleHere(!!last.note_settle_here);
        touched.current.clear();
        // Re-read what is now on file so the inputs show the values that just
        // landed instead of the pre-apply snapshot. Without this the producer
        // is looking at a stale form while being asked to "apply again", which
        // is the loop this note exists to end (fix 2026-08-25, live run S10).
        setPrefillNonce((n) => n + 1);
        setBusy(false);
        return;
      }
    } catch (e) {
      setErr(e?.message || 'Could not apply that value.');
      setBusy(false);
      return;
    }
    // OUTSIDE the try on purpose. The server write has already succeeded here,
    // so a panel-refresh callback that throws must never be reported back to
    // the producer as a failed apply - that invites them to retype a value that
    // is already on file. Every early return above has already exited.
    onApplied?.(withAdded(last), issue);
    if (typeof after === 'function') after();
  };

  const applyNarrative = async () => {
    if (!text.trim()) { setErr('Enter an explanation.'); return; }
    const open = unfinishedStarters(text, resolution.gaps);
    if (open.length) {
      setErr(`Finish the sentence after "${String(open[0].starter).trim()}", or untick it.`);
      return;
    }
    setBusy(true); setErr('');
    let data;
    try {
      data = await post({ mode: 'narrative', text: text.trim() });
      if (!data?.success) { setErr(data?.message || 'Could not save the explanation.'); setBusy(false); return; }
    } catch (e) {
      setErr(e?.message || 'Could not save the explanation.');
      setBusy(false);
      return;
    }
    onApplied?.(withAdded(data), issue);
  };

  const applySchedule = async () => {
    setBusy(true); setErr('');
    let data;
    try {
      // The whole-submission values typed above the table go first (only the
      // ones the producer touched - same rule as field mode), then the table.
      let typedOne = null;
      for (const [field, value] of Object.entries(values)) {
        if (!extraFacts.includes(field) || !touched.current.has(field) || !String(value || '').trim()) continue;
        const r = await post({ mode: 'field', field, value: String(value).trim() });
        if (!r?.success) {
          setErr(r?.validation_error || r?.message || 'Could not apply that value.');
          setBusy(false);
          return;
        }
        applied.current = r;
        typedOne = r;
      }
      // The table is saved when it was edited, or when it is the only thing
      // being saved (an unchanged table still lets every row's stated value
      // answer the card - premises_cope.derive_package_cope), or when it shows
      // cells every building already states that only its save carries to the
      // submission (`confirm_columns`, 21 Oct 2026).
      const savedTable = tableIsSaved({ typedOne: !!typedOne, rowsTouched: rowsTouched.current, resolution });
      data = savedTable
        ? await post({ mode: 'schedule', schedule_key: resolution.schedule_key, rows })
        : typedOne;
      if (!data?.success) { setErr(data?.message || 'Could not save the schedule.'); setBusy(false); return; }
      // Saved, and the window closes - also on "Save progress" (owner, 13 Oct
      // 2026). What is still missing was named above the button before the
      // click; an unfinished item stays in its list with "Open to fix" (the
      // panel reads the server's lists, AcordModal.handleIssueResolved), and
      // opening it again shows what was saved. No "Apply the fix" over a fix
      // that is not finished.
    } catch (e) {
      setErr(e?.message || 'Could not save the schedule.');
      setBusy(false);
      return;
    }
    applied.current = null;
    onApplied?.(withAdded(data), issue);
  };

  // UX-05: generate a missing ACORD form into this package.
  //
  // Slow on purpose - this runs a real form generation (Pass 1 / 1.5 / gap
  // fill), so it can take minutes. The button holds a spinner rather than
  // closing the modal, because closing would strand the producer on a stale
  // panel with no idea whether the form is coming.
  //
  // The modal does NOT close on success. Adding a form can raise NEW
  // validations (a form in the package switches on every rule scoped to it),
  // and a modal that vanished would hide that. `applied` carries the refresh to
  // whichever exit they take, exactly like the field path.
  const addForm = async (formId) => {
    if (!formId || addingForm) return;
    setAddingForm(formId); setErr(''); setNote('');
    let data;
    try {
      data = await post({ mode: 'add_form', add_form_id: formId });
    } catch (e) {
      setErr(e?.message || 'Could not add that form.');
      setAddingForm(null);
      return;
    }
    if (!data?.success) {
      setErr(data?.message || 'Could not add that form.');
      // The server refuses an add it can no longer justify - already in the
      // package, or no open validation asking for it. Both mean the offer is
      // stale, so retire it rather than leaving a button that will fail again.
      if (data?.outcome === 'already_present' || data?.outcome === 'not_requested') {
        setAddForms((prev) => prev.filter((f) => f !== formId));
      }
      setAddingForm(null);
      return;
    }
    applied.current = data;
    addedRef.current = { added_form: data.added_form, form_ids: data.form_ids };
    setAddForms((prev) => prev.filter((f) => f !== formId));
    setAddedForms((prev) => (prev.includes(formId) ? prev : [...prev, formId]));
    setAddingForm(null);
  };

  // Save progress (owner, 13 Oct 2026). A table window - with or without the
  // whole-submission boxes above it - that still lacks a value it shows saves
  // as PROGRESS: the button says "Save progress", the line above it names what
  // is missing, and the item stays open with "Open to fix" until a save really
  // clears it. Field windows with several boxes are "whichever applies" (their
  // own hint says so) unless the card declares the box groups its rule needs
  // (`resolution.needs` - the COPE cards); without that the server's answer
  // after the save decides whether they were fixed.
  // The narrative window's options the typed text already covers (13 Oct 2026).
  const narrativeGaps = mode === 'narrative' && Array.isArray(resolution.gaps) ? resolution.gaps : [];
  const narrativeCoverage = narrativeGaps.length ? textForCoverage(text, narrativeGaps) : '';
  const narrativeCovered = narrativeGaps.filter((g) => gapCovered(narrativeCoverage, g)).length;

  const progressGap = mode === 'schedule' && schedule && !loading && !prefillLoading
    ? windowStillMissing({
        boxes: extraFacts.map((f) => [humanizeFact(f), values[f]]),
        hasTable: true,
        // The table's required cells, and each building row's COPE column
        // groups the card declares (`resolution.row_needs`).
        table: [missingRequiredSummary(rows, schedule.columns || []),
                rowNeedsSummary(rows, resolution.row_needs, schedule.columns || [], resolution.building_columns)]
          .filter(Boolean).join('; '),
      })
    : (mode === 'field' && !prefillLoading && Array.isArray(resolution.needs)
      ? unmetNeeds(resolution.needs, values, humanizeFact)
      : '');

  const label = {
    field: 'Enter the correct value',
    schedule: 'Update the schedule',
    narrative: 'Explain via ACORD 101',
    none: 'Review this validation',
  }[mode] || 'Resolve';

  const overlay = { position: 'fixed', inset: 0, background: 'rgba(15,23,42,0.6)', backdropFilter: 'blur(4px)', zIndex: 100000, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16, overscrollBehavior: 'contain' };
  const card = { background: '#fff', borderRadius: 16, width: '100%', maxWidth: mode === 'schedule' ? 760 : 480, maxHeight: '90vh', overflowY: 'auto', overscrollBehavior: 'contain', boxShadow: '0 24px 60px rgba(0,0,0,0.28)', animation: 'slideUp 0.2s ease-out' };
  const primaryBtn = { padding: '9px 16px', borderRadius: 9, border: 'none', background: PINK, color: '#fff', fontSize: 13, fontWeight: 700, cursor: busy ? 'wait' : 'pointer', fontFamily: 'inherit', opacity: busy ? 0.7 : 1 };
  const ghostBtn = { padding: '9px 16px', borderRadius: 9, border: '1px solid #e2e8f0', background: '#f8fafc', color: '#475569', fontSize: 13, fontWeight: 600, cursor: 'pointer', fontFamily: 'inherit' };
  const inputStyle = { width: '100%', padding: '9px 11px', fontSize: 13, border: '1px solid #e2e8f0', borderRadius: 8, outline: 'none', fontFamily: 'inherit', boxSizing: 'border-box' };

  const stop = (e) => e.stopPropagation();

  return (
    <div ref={overlayRef} role="dialog" aria-modal="true" data-header-autohide="off" style={overlay} onMouseDown={() => { if (!busy && !addingForm) finish(); }}>
      <div ref={cardRef} style={card} onMouseDown={stop}>
        {/* Header */}
        <div style={{ padding: '18px 20px 12px', borderBottom: '1px solid #f1f5f9' }}>
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: PINK, textTransform: 'uppercase', letterSpacing: '0.06em' }}>{label}</div>
              {/* Plain pink text, no pill (Brent's Choice Electric #24) - the
                  same as the editor's Cross-Form rows. */}
              {Array.isArray(issue?.forms) && issue.forms.length > 0 && (
                <div style={{ fontSize: 10.5, fontWeight: 700, color: PINK, lineHeight: 1.4, marginTop: 5 }}>
                  {issue.forms.map((f) => instanceFormLabel(f)).join(', ')}
                </div>
              )}
            </div>
            <button
              type="button"
              onClick={finish}
              disabled={busy || !!addingForm}
              aria-label="Close"
              style={{
                flexShrink: 0, width: 30, height: 30, borderRadius: '50%',
                border: `1px solid ${PINK}`, background: 'rgba(230,27,132,0.1)', color: PINK,
                fontSize: 15, lineHeight: 1, cursor: busy ? 'default' : 'pointer',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                transition: 'all 0.2s', opacity: busy ? 0.5 : 1,
              }}
              onMouseEnter={(e) => { if (busy) return; e.currentTarget.style.background = PINK; e.currentTarget.style.color = '#fff'; e.currentTarget.style.transform = 'rotate(90deg)'; }}
              onMouseLeave={(e) => { e.currentTarget.style.background = 'rgba(230,27,132,0.1)'; e.currentTarget.style.color = PINK; e.currentTarget.style.transform = 'rotate(0deg)'; }}
            >×</button>
          </div>
          <div style={{ fontSize: 13, color: '#334155', lineHeight: 1.5, marginTop: 10 }}>{positiveScoreWording(issue?.message)}</div>
        </div>

        {/* Body */}
        <div style={{ padding: '16px 20px' }}>
          {/* UX-05 - the missing form(s) this validation is asking for. Sits
              ABOVE the mode content on purpose: for a `none`-mode row it is the
              only real action on the card, and for a narrative row it is the
              other half of what the message asked for ("attach ACORD 101"). */}
          {addForms.length > 0 && (
            <div style={{ marginBottom: mode === 'none' ? 0 : 14, background: '#fdf2f8', border: '1px solid #f9a8d4', borderRadius: 10, padding: '12px 14px' }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: '#be185d', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 6 }}>
                {addForms.length > 1 ? 'Missing forms' : 'Missing form'}
              </div>
              <div style={{ fontSize: 12, color: '#475569', lineHeight: 1.5, marginBottom: 10 }}>
                {addForms.length > 1
                  ? 'These forms are not in this package yet. Adding one generates it and re-runs the checks.'
                  : 'This form is not in this package yet. Adding it generates the form and re-runs the checks.'}
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                {addForms.map((fid) => (
                  <button
                    key={fid}
                    type="button"
                    disabled={busy || !!addingForm}
                    onClick={() => addForm(fid)}
                    style={{ ...primaryBtn, opacity: (busy || addingForm) ? 0.6 : 1, cursor: addingForm ? 'wait' : 'pointer' }}
                  >
                    {addingForm === fid ? `Adding ${formLabel(fid)}...` : `Add ${formLabel(fid)}`}
                  </button>
                ))}
              </div>
              {addingForm && (
                <div style={{ fontSize: 11.5, color: '#9d174d', marginTop: 8, lineHeight: 1.45 }}>
                  Generating the form and re-checking the package - this can take a few minutes. Please keep this window open.
                </div>
              )}
            </div>
          )}

          {/* Added in this session of the modal. Green, and deliberately honest
              about what an added form does NOT do: putting a form in the package
              switches on every rule scoped to it, so new items can appear. */}
          {addedForms.length > 0 && (
            <div style={{ marginBottom: mode === 'none' ? 0 : 14, background: '#f0fdf4', border: '1px solid #86efac', borderRadius: 10, padding: '11px 13px' }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: '#15803d', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 4 }}>
                {addedForms.length > 1 ? 'Forms added' : 'Form added'}
              </div>
              <div style={{ fontSize: 12.5, color: '#166534', lineHeight: 1.5 }}>
                {addedForms.map(formLabel).join(', ')} {addedForms.length > 1 ? 'are' : 'is'} now in this package and the checks have been re-run. Adding a form can raise new items for that form - check the panel before you download.
              </div>
            </div>
          )}

          {(mode === 'field' || mode === 'narrative' || extraFacts.length > 0) && prefillLoading && (
            <div style={{ padding: '24px 0', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 9, color: '#64748b', fontSize: 13 }}>
              <span style={{ width: 15, height: 15, border: '2px solid #e2e8f0', borderTopColor: PINK, borderRadius: '50%', display: 'inline-block', animation: 'spin 0.7s linear infinite' }} />
              {mode === 'narrative' ? 'Loading saved remarks...' : 'Loading current value...'}
            </div>
          )}
          {(mode === 'field' || extraFacts.length > 0) && !prefillLoading && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12, marginBottom: mode === 'schedule' ? 14 : 0 }}>
              {mode === 'schedule' && (
                <div style={{ fontSize: 10, fontWeight: 700, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em' }}>For the whole submission</div>
              )}
              {fieldFacts.length > 1 && !Array.isArray(resolution.needs) && (
                <div style={{ fontSize: 11.5, color: '#64748b' }}>Provide the correct value for whichever applies - you don't have to fill every field.</div>
              )}
              {fieldFacts.map((fact) => {
                // A closed question is offered as a choice list (backend
                // `resolution.controls`), so a hard stop or warning is never
                // resolved by guessing at wording. "Other" reveals free text.
                const ctl = (resolution.controls || {})[fact] || {};
                // "Which line is this coverage part?" (owner, 14 Oct 2026): one
                // choice per part the server lists, saved as ONE answer - the
                // parts, their choices and what an answer means are the
                // server's (issue_registry.unmapped_line_issue); this only
                // composes the text (utils/partLines).
                if (ctl.control === 'part_lines') {
                  const parts = Array.isArray(ctl.parts) ? ctl.parts : [];
                  const choices = Array.isArray(ctl.options) ? ctl.options : [];
                  const picks = partPicks(ctl, values[fact]);
                  const left = partsLeft(ctl, picks);
                  return (
                    <div key={fact} data-testid="part-lines">
                      <span style={{ display: 'block', fontSize: 12, fontWeight: 600, color: '#334155', marginBottom: 5 }}>{ctl.label || humanizeFact(fact)}</span>
                      {resolution.note && (
                        <div style={{ fontSize: 11.5, color: '#64748b', lineHeight: 1.5, marginBottom: 8 }}>{resolution.note}</div>
                      )}
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 9 }}>
                        {parts.map((p, i) => (
                          <label key={p.key} style={{ display: 'block' }}>
                            <span style={{ display: 'block', fontSize: 12, color: '#475569', marginBottom: 4 }}>{p.label}</span>
                            <select
                              style={inputStyle}
                              value={picks[p.key] || ''}
                              disabled={busy}
                              autoFocus={i === 0}
                              onChange={(e) => {
                                const chosen = e.target.value;
                                touched.current.add(fact);
                                const composed = composePartLines(ctl, { ...partPicks(ctl, values[fact]), [p.key]: chosen });
                                setValues((v) => ({
                                  ...v,
                                  [fact]: composePartLines(ctl, { ...partPicks(ctl, v[fact]), [p.key]: chosen }),
                                }));
                                askPreview({ ...values, [fact]: composed });
                                if (err) setErr('');
                              }}
                              onFocus={() => { if (note) setNote(''); }}
                            >
                              <option value="">Select a line...</option>
                              {choices.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                            </select>
                          </label>
                        ))}
                      </div>
                      {parts.length > 1 && left > 0 && (
                        <div style={{ fontSize: 11.5, color: '#64748b', marginTop: 8 }}>
                          {left === parts.length
                            ? `Pick a line for each of the ${parts.length} parts.`
                            : `${left} of ${parts.length} parts still need a line - the item stays open until each has one.`}
                        </div>
                      )}
                    </div>
                  );
                }
                const opts = Array.isArray(ctl.options) ? ctl.options : null;
                const picked = values[fact] || '';
                const isOther = !!opts && (otherFacts.has(fact) || picked === 'Other');
                // A value already on file need not be one of the offered labels:
                // the backend stores the canonical form the fact can hold
                // ("RCV", "3", "Joisted Masonry") while the list offers readable
                // labels ("Replacement Cost", "Protection Class 3", ...). Show it
                // rather than a blank select, so re-opening a resolved card does
                // not look like the answer was lost.
                const onFile = opts && picked && !isOther && !opts.includes(picked)
                  ? picked : null;
                return (
                <label key={fact} style={{ display: 'block' }}>
                  <span style={{ display: 'block', fontSize: 12, fontWeight: 600, color: '#334155', marginBottom: 5 }}>{humanizeFact(fact)}</span>
                  {opts ? (
                    <>
                      <select
                        style={inputStyle}
                        value={isOther ? 'Other' : picked}
                        disabled={busy}
                        autoFocus={fieldFacts[0] === fact}
                        onChange={(e) => {
                          const chosen = e.target.value;
                          touched.current.add(fact);
                          setOtherMode(fact, chosen === 'Other');
                          // Entering Other clears the box rather than submitting
                          // the literal word "Other", which the backend refuses
                          // (answer_semantics: it is an affordance, not a value).
                          const nextValues = { ...values, [fact]: chosen === 'Other' ? '' : chosen };
                          setValues((v) => ({ ...v, [fact]: chosen === 'Other' ? '' : chosen }));
                          askPreview(nextValues);
                          if (err) setErr('');
                        }}
                        onFocus={() => { if (note) setNote(''); }}
                      >
                        <option value="">Select an answer...</option>
                        {onFile && <option value={onFile}>{onFile} (current value)</option>}
                        {opts.map((o) => <option key={o} value={o}>{o}</option>)}
                      </select>
                      {isOther && (
                        <input
                          style={{ ...inputStyle, marginTop: 6 }}
                          placeholder="Type the correct value..."
                          disabled={busy}
                          autoFocus
                          value={picked}
                          onChange={(e) => onTyped(fact, e.target.value)}
                          onBlur={() => askPreview(values, true)}
                          onKeyDown={(e) => { if (e.key === 'Enter' && mode === 'field') applyField(); }}
                        />
                      )}
                    </>
                  ) : (
                  <input
                    style={inputStyle}
                    value={picked}
                    placeholder="Type the correct value..."
                    disabled={busy}
                    autoFocus={fieldFacts[0] === fact}
                    onChange={(e) => onTyped(fact, e.target.value)}
                    onFocus={() => { if (note) setNote(''); }}
                    onBlur={() => askPreview(values, true)}
                    onKeyDown={(e) => { if (e.key === 'Enter' && mode === 'field') applyField(); }}
                  />
                  )}
                </label>
                );
              })}
            </div>
          )}

          {mode === 'field' && !prefillLoading && followUps.length > 0 && (
            <div data-testid="follow-ups" style={{ marginTop: 14, background: '#fdf2f8', border: '1px solid #f9a8d4', borderRadius: 10, padding: '11px 13px', display: 'flex', flexDirection: 'column', gap: 10 }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: '#be185d', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Then:</div>
              {fuSplit.warning.map((fu) => (
                <div key={fu.id} data-testid="follow-up-warning" style={{ fontSize: 12, color: '#92400e', background: '#fffbeb', border: '1px solid #fcd34d', borderRadius: 8, padding: '7px 10px', lineHeight: 1.45 }}>
                  This answer raises a warning: {fu.label}
                </div>
              ))}
              {fuSplit.field.map((fu) => (
                <div key={fu.id} style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  <span style={{ fontSize: 12, fontWeight: 600, color: '#334155' }}>{fu.label}</span>
                  {((fu.resolution && fu.resolution.facts) || []).map((fact) => {
                    const ctl = ((fu.resolution && fu.resolution.controls) || {})[fact] || {};
                    const opts = Array.isArray(ctl.options) ? ctl.options : null;
                    const v = fuValues[fact] || '';
                    const other = !!opts && fuOther.has(fact);
                    const setFu = (val) => setFuValues((cur) => ({ ...cur, [fact]: val }));
                    return (
                      <div key={fact}>
                        {fu.resolution.facts.length > 1 && (
                          <span style={{ display: 'block', fontSize: 11.5, color: '#475569', marginBottom: 4 }}>{humanizeFact(fact)}</span>
                        )}
                        {opts ? (
                          <>
                            <select style={inputStyle} value={other ? 'Other' : v} disabled={busy}
                              onChange={(e) => {
                                const chosen = e.target.value;
                                setFuOther((prev) => { const n = new Set(prev); if (chosen === 'Other') n.add(fact); else n.delete(fact); return n; });
                                setFu(chosen === 'Other' ? '' : chosen);
                                if (err) setErr('');
                              }}>
                              <option value="">Select an answer (optional)...</option>
                              {opts.map((o) => <option key={o} value={o}>{o}</option>)}
                            </select>
                            {other && (
                              <input style={{ ...inputStyle, marginTop: 6 }} placeholder="Type the value..." disabled={busy}
                                value={v} onChange={(e) => setFu(e.target.value)} />
                            )}
                          </>
                        ) : (
                          <input style={inputStyle} placeholder="Type the value (optional)..." disabled={busy}
                            value={v} onChange={(e) => { setFu(e.target.value); if (err) setErr(''); }} />
                        )}
                      </div>
                    );
                  })}
                </div>
              ))}
              {fuSplit.open.map((fu) => (
                <div key={fu.id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10 }}>
                  <span style={{ fontSize: 12, color: '#334155', lineHeight: 1.45 }}>{fu.label}</span>
                  {typeof onOpenFollowUp === 'function' && (
                    <button type="button" style={{ ...ghostBtn, padding: '6px 11px', fontSize: 12, whiteSpace: 'nowrap' }} disabled={busy}
                      onClick={() => applyField(() => onOpenFollowUp(followUpIssue(fu)))}>Open to fix</button>
                  )}
                </div>
              ))}
              {fuSplit.document.map((fu) => (
                <div key={fu.id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10 }}>
                  <span style={{ fontSize: 12, color: '#334155', lineHeight: 1.45 }}>{fu.label}</span>
                  {typeof onAddDocuments === 'function' && (
                    <button type="button" style={{ ...ghostBtn, padding: '6px 11px', fontSize: 12, whiteSpace: 'nowrap' }} disabled={busy}
                      onClick={() => applyField(() => onAddDocuments())}>Add documents</button>
                  )}
                </div>
              ))}
              <div style={{ fontSize: 11, color: '#64748b', lineHeight: 1.45 }}>
                These appear because of the answer above. What you fill in here is saved with it; anything left blank stays on the page to answer later.
              </div>
            </div>
          )}

          {mode === 'narrative' && !prefillLoading && (
            <div>
              <div style={{ fontSize: 11.5, color: '#64748b', marginBottom: 8 }}>Your explanation is added to the ACORD 101 Additional Remarks Schedule and sent to the underwriter.</div>
              {/* What the score still looks for (owner, 13 Oct 2026: a producer
                  could not tell why the card stayed). Tick one or several - each
                  adds a sentence starter to finish below. */}
              {Array.isArray(resolution.gaps) && resolution.gaps.length > 0 && (
                <div style={{ marginBottom: 10, background: '#fdf2f8', border: '1px solid #f9a8d4', borderRadius: 10, padding: '10px 12px' }}>
                  <div style={{ fontSize: 10, fontWeight: 700, color: '#be185d', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 6 }}>Still missing - tick to add a starter</div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                    {resolution.gaps.map((g) => {
                      // Ticked when its starter is in the box OR the text already
                      // covers it the way the score reads it (13 Oct 2026). One the
                      // producer's own words cover cannot be unticked - unticking
                      // only takes a starter line out.
                      const starterIn = !!g.starter && text.includes(g.starter);
                      const coveredByText = gapCovered(narrativeCoverage, g);
                      const on = starterIn || coveredByText;
                      const locked = coveredByText && !starterIn;
                      return (
                        <label key={g.key} title={locked ? 'Your text already covers this' : undefined} style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 11.5, color: '#334155', background: on ? '#fce7f3' : '#fff', border: `1px solid ${on ? PINK : '#e2e8f0'}`, borderRadius: 999, padding: '3px 10px', cursor: busy || locked ? 'default' : 'pointer' }}>
                          <input
                            type="checkbox"
                            checked={on}
                            disabled={busy || !g.starter || locked}
                            onChange={() => {
                              if (!g.starter) return;
                              setText((t) => (t.includes(g.starter)
                                ? t.split('\n').filter((line) => line !== g.starter.trimEnd() && line !== g.starter).join('\n')
                                : (t.trim() ? `${t.replace(/\s+$/, '')}\n${g.starter}` : g.starter)));
                              if (err) setErr('');
                            }}
                            style={{ accentColor: PINK, margin: 0 }}
                          />
                          {g.label}
                        </label>
                      );
                    })}
                  </div>
                  {narrativeCovered > 0 && (
                    <div style={{ fontSize: 11, color: '#9d174d', marginTop: 7 }} data-testid="narrative-covered">
                      {narrativeCovered === resolution.gaps.length
                        ? 'Your text covers all of these.'
                        : `Your text covers ${narrativeCovered} of ${resolution.gaps.length}.`}
                    </div>
                  )}
                </div>
              )}
              {existingRemarks.trim() && (
                <div style={{ marginBottom: 10, background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 8, padding: '9px 11px' }}>
                  <div style={{ fontSize: 10, fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 4 }}>Already on ACORD 101</div>
                  <div style={{ fontSize: 12, color: '#475569', lineHeight: 1.5, whiteSpace: 'pre-wrap' }}>{existingRemarks}</div>
                </div>
              )}
              <textarea
                style={{ ...inputStyle, minHeight: 110, resize: 'vertical' }}
                value={text}
                placeholder={existingRemarks.trim() ? 'Add another explanation...' : 'Explain how this is reconciled or why it is intentional...'}
                disabled={busy}
                autoFocus
                onChange={(e) => { setText(e.target.value); if (err) setErr(''); }}
              />
            </div>
          )}

          {mode === 'schedule' && (
            <div>
              {/* A table with its own heading (21 Oct 2026, Brent's item 6: "one
                  pop-up titled General Liability Classification & Exposure
                  Details") - the server's `title` and `intro` for that table. */}
              {schedule && !loading && schedule.title && (
                <div style={{ fontSize: 15, fontWeight: 700, color: '#0f172a', marginBottom: 6 }} data-testid="schedule-title">
                  {schedule.title}
                </div>
              )}
              {schedule && !loading && schedule.intro && (
                <div style={{ fontSize: 12, color: '#475569', lineHeight: 1.5, marginBottom: 10 }}>{schedule.intro}</div>
              )}
              {/* What this fix needs from the table (the COPE card on a package
                  with two or more buildings, 7 Oct 2026): one row per building. */}
              {(resolution.note || (Array.isArray(resolution.columns) && resolution.columns.length > 0)) && !loading && (
                <div style={{ fontSize: 12, color: '#475569', lineHeight: 1.5, marginBottom: 10 }}>
                  {resolution.note ? `${resolution.note} ` : ''}
                  {Array.isArray(resolution.columns) && resolution.columns.length > 0 && schedule && (
                    <>Per building: {resolution.columns
                      .map((k) => ((schedule.columns || []).find((c) => c.key === k) || {}).label || humanizeFact(k))
                      .join(', ')}.</>
                  )}
                </div>
              )}
              {loading ? (
                <div style={{ padding: '24px 0', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 9, color: '#64748b', fontSize: 13 }}>
                  <span style={{ width: 15, height: 15, border: '2px solid #e2e8f0', borderTopColor: PINK, borderRadius: '50%', display: 'inline-block', animation: 'spin 0.7s linear infinite' }} />
                  Loading schedule...
                </div>
              ) : schedule ? (
                <ScheduleTable
                  columns={schedule.columns || []}
                  rows={rows}
                  onChange={editRows}
                  label={schedule.schedule_label || 'Schedule'}
                  singular={schedule.schedule_singular || 'row'}
                  dedupKeys={schedule.dedup_keys || []}
                  vinDecode={!!schedule.vin_decode}
                  rowCapacity={schedule.row_capacity || 0}
                  compact
                  fixedRows={resolution.per_building === true}
                  followUp={schedule.follow_up === true}
                />
              ) : (
                <div style={{ padding: '16px 0', color: '#b91c1c', fontSize: 13 }}>{err || 'Schedule unavailable.'}</div>
              )}
            </div>
          )}

          {/* The generic "handle it elsewhere" sentence is only true when there
              is nothing to click. With an Add-form action on the card it was
              actively wrong, so it is suppressed while one is offered or has
              just been used (UX-05). */}
          {mode === 'none' && addForms.length === 0 && addedForms.length === 0 && (
            <div style={{ fontSize: 12.5, color: '#475569', lineHeight: 1.55, background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 10, padding: '12px 14px' }}>
              {resolution.note
                || "This one is settled by a coverage or form decision rather than a typed value. Make the change on the form it names, then mark it resolved here, or dismiss it with a note."}
            </div>
          )}

          {/* Applied, but it traded one issue for another. Amber, not red - the
              value saved; this is the heads-up the producer never used to get. */}
          {note && (
            <div style={{ marginTop: 12, fontSize: 12.5, color: '#78350f', lineHeight: 1.55, background: '#fffbeb', border: '1px solid #fcd34d', borderRadius: 10, padding: '11px 13px' }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: '#b45309', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 4 }}>Saved - one thing to check</div>
              {note}
            </div>
          )}

          {progressGap && !note && (
            <div style={{ marginTop: 12, fontSize: 12, color: '#475569', lineHeight: 1.5, background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 10, padding: '10px 12px' }}>
              <b style={{ color: '#334155' }}>Still missing:</b> {progressGap}. Save your progress now and finish it later - it stays open until everything is in.
            </div>
          )}

          {err && mode !== 'schedule' && (
            <div style={{ marginTop: 10, fontSize: 12, fontWeight: 600, color: '#b91c1c' }}>{err}</div>
          )}
          {err && mode === 'schedule' && schedule && (
            <div style={{ marginTop: 10, fontSize: 12, fontWeight: 600, color: '#b91c1c' }}>{err}</div>
          )}
        </div>

        {/* Footer */}
        <div style={{ padding: '12px 20px 18px', display: 'flex', gap: 10, justifyContent: 'flex-end', borderTop: '1px solid #f1f5f9' }}>
          {mode === 'none' && addedForms.length > 0 ? (
            // A form WAS added, so Dismiss / Mark resolved are both wrong here.
            // The producer already fixed it - asking them to also file a status
            // is paperwork about their own action, and it is what created the
            // confusing state reported on 2026-09-09: "Mark resolved" made a
            // Resolved receipt, "Reopen" flipped it to open, and the row then
            // rendered nowhere because the validation no longer fires and could
            // never fire again. One "Done"; the panel marks it resolved itself,
            // and only if the validation actually stopped firing.
            <button type="button" style={primaryBtn} onClick={finish}>Done</button>
          ) : mode === 'none' ? (
            <>
              {/* `finish`, not `onClose`: since UX-05 a `none`-mode card can
                  APPLY something (add a form), and leaving via Dismiss / Mark
                  resolved must still refresh the panel behind it. `finish`
                  falls through to onClose when nothing was applied, so the
                  no-add case is byte-identical to the old behaviour. */}
              <button type="button" style={ghostBtn} disabled={!!addingForm} onClick={() => { onSetStatus?.(issue, 'dismissed'); finish(); }}>Dismiss</button>
              <button type="button" style={primaryBtn} disabled={!!addingForm} onClick={() => { onSetStatus?.(issue, 'resolved'); finish(); }}>Mark resolved</button>
            </>
          ) : (
            <>
              {/* `finish` not `onClose`: once a value has been applied the panel
                  behind this modal is stale, whichever way the producer leaves. */}
              {/* Nothing left to type here means there is nothing to cancel
                  either - the value is already saved. One unambiguous "Done"
                  beats a Close/Done pair that both do the same thing. */}
              {!(note && !noteSettleHere) && (
                <button type="button" style={ghostBtn} disabled={busy} onClick={finish}>
                  {note ? 'Done' : 'Cancel'}
                </button>
              )}
              <button
                type="button"
                style={primaryBtn}
                disabled={busy || (mode === 'schedule' && (loading || !schedule))}
                onClick={note && !noteSettleHere
                  ? finish
                  : (mode === 'field' ? applyField : mode === 'narrative' ? applyNarrative : applySchedule)}
              >
                {busy
                  ? (progressGap ? 'Saving...' : 'Applying...')
                  : note
                    ? (noteSettleHere ? 'Apply the fix' : 'Done')
                    : progressGap
                      ? 'Save progress'
                      : (mode === 'field' && !prefillLoading && !partLinesWindow
                        ? applyLabel(fieldFacts, values, touched.current)
                        : 'Apply')}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
