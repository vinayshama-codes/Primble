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

export default function ResolutionModal({ issue, sessionId, onApplied, onSetStatus, onClose }) {
  const resolution = issue?.resolution || {};
  const mode = resolution.mode || 'none';

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
  const [prefillLoading, setPrefillLoading] = useState(mode === 'field' || mode === 'narrative');
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

  // UX-05. Forms this validation says are missing, as the SERVER declared them.
  // Held in state, not read straight off `resolution`, because a successful add
  // must drop that form from the offer immediately - the panel behind refreshes
  // asynchronously and the producer is still looking at this modal.
  const [addForms, setAddForms] = useState(() =>
    (Array.isArray(resolution.add_forms) ? resolution.add_forms : []).filter(Boolean));
  const [addingForm, setAddingForm] = useState(null);   // form id in flight
  const [addedForms, setAddedForms] = useState([]);     // form ids added here
  const formLabel = (fid) => String(fid || '').replace(/_/g, ' ');

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
    if (mode !== 'field' && mode !== 'narrative') { setPrefillLoading(false); return; }
    let alive = true;
    const facts = mode === 'field' ? (resolution.facts || []) : ['additional_remarks_text'];
    (async () => {
      try {
        const q = encodeURIComponent(facts.join(','));
        const res = await fetch(`${API_BASE}/api/audit/issue-values/${sessionId}?facts=${q}`, { credentials: 'include' });
        const data = await res.json();
        if (!alive) return;
        const vals = data?.values || {};
        if (mode === 'field') {
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
          setSchedule(match);
          setRows(Array.isArray(match.rows) ? match.rows : []);
        }
      } catch {
        if (alive) setErr('Could not load the schedule. Please try again.');
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, [mode, sessionId, resolution.schedule_key]);

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

  const applyField = async () => {
    // Only send fields the producer actually typed into. `values` also carries
    // whatever the async pre-fill loaded from the current session facts (so a
    // reopened validation shows what's already on file) - those are display
    // only. Submitting an untouched pre-filled value back through this endpoint
    // re-validates it as a fresh producer answer, which can reject a value the
    // extraction pipeline already accepted as legitimate (e.g. a peril marked
    // "Not covered") purely because the producer never meant to change it.
    const filled = Object.entries(values).filter(
      ([k, v]) => touched.current.has(k) && String(v || '').trim()
    );
    if (!filled.length) { setErr('Enter at least one value.'); return; }
    setBusy(true); setErr(''); setNote('');
    let last = null;
    try {
      // Apply each provided fact; each re-runs the rules, the final response is
      // authoritative for the panel refresh. Filling BOTH sides of a trade-off
      // in one go therefore reports no note: the second write clears what the
      // first one raised, and only the last response is read.
      for (const [field, value] of filled) {
        last = await post({ mode: 'field', field, value: String(value).trim() });
        if (!last?.success) {
          setErr(last?.validation_error || last?.message || 'Could not apply that value.');
          setBusy(false);
          return;
        }
      }
      // Applied, but it raised something else. Hold the modal open on the note
      // so the producer can settle it here instead of discovering it later on
      // the panel and starting the loop again. The value stands either way -
      // `applied` carries it to whichever exit they take.
      if (last?.note) {
        applied.current = last;
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
  };

  const applyNarrative = async () => {
    if (!text.trim()) { setErr('Enter an explanation.'); return; }
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
      data = await post({ mode: 'schedule', schedule_key: resolution.schedule_key, rows });
      if (!data?.success) { setErr(data?.message || 'Could not save the schedule.'); setBusy(false); return; }
    } catch (e) {
      setErr(e?.message || 'Could not save the schedule.');
      setBusy(false);
      return;
    }
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

  const label = {
    field: 'Enter the correct value',
    schedule: 'Update the schedule',
    narrative: 'Explain via ACORD 101',
    none: 'Review this validation',
  }[mode] || 'Resolve';

  const overlay = { position: 'fixed', inset: 0, background: 'rgba(15,23,42,0.6)', backdropFilter: 'blur(4px)', zIndex: 100000, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 };
  const card = { background: '#fff', borderRadius: 16, width: '100%', maxWidth: mode === 'schedule' ? 760 : 480, maxHeight: '90vh', overflowY: 'auto', boxShadow: '0 24px 60px rgba(0,0,0,0.28)', animation: 'slideUp 0.2s ease-out' };
  const primaryBtn = { padding: '9px 16px', borderRadius: 9, border: 'none', background: PINK, color: '#fff', fontSize: 13, fontWeight: 700, cursor: busy ? 'wait' : 'pointer', fontFamily: 'inherit', opacity: busy ? 0.7 : 1 };
  const ghostBtn = { padding: '9px 16px', borderRadius: 9, border: '1px solid #e2e8f0', background: '#f8fafc', color: '#475569', fontSize: 13, fontWeight: 600, cursor: 'pointer', fontFamily: 'inherit' };
  const inputStyle = { width: '100%', padding: '9px 11px', fontSize: 13, border: '1px solid #e2e8f0', borderRadius: 8, outline: 'none', fontFamily: 'inherit', boxSizing: 'border-box' };

  const stop = (e) => e.stopPropagation();

  return (
    <div style={overlay} onMouseDown={() => { if (!busy && !addingForm) finish(); }}>
      <div style={card} onMouseDown={stop}>
        {/* Header */}
        <div style={{ padding: '18px 20px 12px', borderBottom: '1px solid #f1f5f9' }}>
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: PINK, textTransform: 'uppercase', letterSpacing: '0.06em' }}>{label}</div>
              {Array.isArray(issue?.forms) && issue.forms.length > 0 && (
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 6 }}>
                  {issue.forms.map((f, i) => (
                    <span key={i} style={{ fontSize: 9.5, fontWeight: 700, color: '#9d174d', background: '#fce7f3', border: '1px solid #f9a8d4', borderRadius: 10, padding: '1px 7px' }}>{String(f).replace(/_/g, ' ')}</span>
                  ))}
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
          <div style={{ fontSize: 13, color: '#334155', lineHeight: 1.5, marginTop: 10 }}>{issue?.message}</div>
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

          {(mode === 'field' || mode === 'narrative') && prefillLoading && (
            <div style={{ padding: '24px 0', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 9, color: '#64748b', fontSize: 13 }}>
              <span style={{ width: 15, height: 15, border: '2px solid #e2e8f0', borderTopColor: PINK, borderRadius: '50%', display: 'inline-block', animation: 'spin 0.7s linear infinite' }} />
              {mode === 'field' ? 'Loading current value...' : 'Loading saved remarks...'}
            </div>
          )}
          {mode === 'field' && !prefillLoading && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {(resolution.facts || []).length > 1 && (
                <div style={{ fontSize: 11.5, color: '#64748b' }}>Provide the correct value for whichever applies - you don't have to fill every field.</div>
              )}
              {(resolution.facts || []).map((fact) => {
                // A closed question is offered as a choice list (backend
                // `resolution.controls`), so a hard stop or warning is never
                // resolved by guessing at wording. "Other" reveals free text.
                const ctl = (resolution.controls || {})[fact] || {};
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
                        autoFocus={(resolution.facts || [])[0] === fact}
                        onChange={(e) => {
                          const chosen = e.target.value;
                          touched.current.add(fact);
                          setOtherMode(fact, chosen === 'Other');
                          // Entering Other clears the box rather than submitting
                          // the literal word "Other", which the backend refuses
                          // (answer_semantics: it is an affordance, not a value).
                          setValues((v) => ({ ...v, [fact]: chosen === 'Other' ? '' : chosen }));
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
                          onChange={(e) => { touched.current.add(fact); setValues((v) => ({ ...v, [fact]: e.target.value })); if (err) setErr(''); }}
                          onKeyDown={(e) => { if (e.key === 'Enter') applyField(); }}
                        />
                      )}
                    </>
                  ) : (
                  <input
                    style={inputStyle}
                    value={picked}
                    placeholder="Type the correct value..."
                    disabled={busy}
                    autoFocus={(resolution.facts || [])[0] === fact}
                    onChange={(e) => { touched.current.add(fact); setValues((v) => ({ ...v, [fact]: e.target.value })); if (err) setErr(''); }}
                    onFocus={() => { if (note) setNote(''); }}
                    onKeyDown={(e) => { if (e.key === 'Enter') applyField(); }}
                  />
                  )}
                </label>
                );
              })}
            </div>
          )}

          {mode === 'narrative' && !prefillLoading && (
            <div>
              <div style={{ fontSize: 11.5, color: '#64748b', marginBottom: 8 }}>Your explanation is added to the ACORD 101 Additional Remarks Schedule and sent to the underwriter.</div>
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
              {loading ? (
                <div style={{ padding: '24px 0', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 9, color: '#64748b', fontSize: 13 }}>
                  <span style={{ width: 15, height: 15, border: '2px solid #e2e8f0', borderTopColor: PINK, borderRadius: '50%', display: 'inline-block', animation: 'spin 0.7s linear infinite' }} />
                  Loading schedule...
                </div>
              ) : schedule ? (
                <ScheduleTable
                  columns={schedule.columns || []}
                  rows={rows}
                  onChange={setRows}
                  label={schedule.schedule_label || 'Schedule'}
                  singular={schedule.schedule_singular || 'row'}
                  dedupKeys={schedule.dedup_keys || []}
                  vinDecode={!!schedule.vin_decode}
                  rowCapacity={schedule.row_capacity || 0}
                  compact
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
                || "This validation can't be fixed by entering a single value - it usually means adding or adjusting a coverage or form. Handle it on the relevant form, then mark it resolved here, or dismiss it with a note."}
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
                  ? 'Applying...'
                  : note
                    ? (noteSettleHere ? 'Apply the fix' : 'Done')
                    : 'Apply'}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
