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
//                controls (no single value fixes it - e.g. "add ACORD 186")

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
  const [text, setText] = useState('');          // narrative mode: new text to add
  const [existingRemarks, setExistingRemarks] = useState(''); // narrative: what's already saved
  const [schedule, setSchedule] = useState(null); // schedule mode: fetched def + rows
  const [rows, setRows] = useState([]);
  // ONLY the schedule table needs data before it can render at all; field and
  // narrative render immediately (typeable) and hydrate their saved values in the
  // background, so the producer never waits to start typing.
  const [loading, setLoading] = useState(mode === 'schedule');
  // Field/narrative modes hydrate their saved values from the server (so
  // reopening a resolved validation shows what was applied). `prefillLoading`
  // gates the field inputs behind a spinner until that value lands, instead of
  // flashing an empty box that fills a beat later (client #3).
  const [prefillLoading, setPrefillLoading] = useState(mode === 'field' || mode === 'narrative');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  // Facts the producer has started editing - the async pre-fill must never
  // overwrite these, or a value would jump under the cursor.
  const touched = useRef(new Set());

  // Pre-fill field inputs (and narrative's "already saved" context) from the
  // current session facts, so reopening a validation shows what was applied.
  // Field mode holds a spinner until this resolves (client #3) so a
  // previously-entered value never flashes in a beat after an empty box;
  // narrative stays non-blocking (its textarea is empty on open anyway).
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
  }, [mode, sessionId]);  // eslint-disable-line react-hooks/exhaustive-deps

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
    const onKey = (e) => { if (e.key === 'Escape' && !busy) onClose?.(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [busy, onClose]);

  const post = async (body) => {
    const res = await fetch(`${API_BASE}/api/audit/resolve-issue`, {
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
    return res.json();
  };

  const applyField = async () => {
    const filled = Object.entries(values).filter(([, v]) => String(v || '').trim());
    if (!filled.length) { setErr('Enter at least one value.'); return; }
    setBusy(true); setErr('');
    let last = null;
    try {
      // Apply each provided fact; each re-runs the rules, the final response is
      // authoritative for the panel refresh.
      for (const [field, value] of filled) {
        last = await post({ mode: 'field', field, value: String(value).trim() });
        if (!last?.success) {
          setErr(last?.validation_error || last?.message || 'Could not apply that value.');
          setBusy(false);
          return;
        }
      }
      onApplied?.(last, issue);
    } catch {
      setErr('Something went wrong applying your answer.');
      setBusy(false);
    }
  };

  const applyNarrative = async () => {
    if (!text.trim()) { setErr('Enter an explanation.'); return; }
    setBusy(true); setErr('');
    try {
      const data = await post({ mode: 'narrative', text: text.trim() });
      if (!data?.success) { setErr(data?.message || 'Could not save the explanation.'); setBusy(false); return; }
      onApplied?.(data, issue);
    } catch { setErr('Something went wrong saving the explanation.'); setBusy(false); }
  };

  const applySchedule = async () => {
    setBusy(true); setErr('');
    try {
      const data = await post({ mode: 'schedule', schedule_key: resolution.schedule_key, rows });
      if (!data?.success) { setErr(data?.message || 'Could not save the schedule.'); setBusy(false); return; }
      onApplied?.(data, issue);
    } catch { setErr('Something went wrong saving the schedule.'); setBusy(false); }
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
    <div style={overlay} onMouseDown={() => { if (!busy) onClose?.(); }}>
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
              onClick={() => onClose?.()}
              disabled={busy}
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
          {mode === 'field' && prefillLoading && (
            <div style={{ padding: '24px 0', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 9, color: '#64748b', fontSize: 13 }}>
              <span style={{ width: 15, height: 15, border: '2px solid #e2e8f0', borderTopColor: PINK, borderRadius: '50%', display: 'inline-block', animation: 'spin 0.7s linear infinite' }} />
              Loading current value...
            </div>
          )}
          {mode === 'field' && !prefillLoading && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {(resolution.facts || []).length > 1 && (
                <div style={{ fontSize: 11.5, color: '#64748b' }}>Provide the correct value for whichever applies - you don't have to fill every field.</div>
              )}
              {(resolution.facts || []).map((fact) => (
                <label key={fact} style={{ display: 'block' }}>
                  <span style={{ display: 'block', fontSize: 12, fontWeight: 600, color: '#334155', marginBottom: 5 }}>{humanizeFact(fact)}</span>
                  <input
                    style={inputStyle}
                    value={values[fact] || ''}
                    placeholder="Type the correct value..."
                    disabled={busy}
                    autoFocus={(resolution.facts || [])[0] === fact}
                    onChange={(e) => { touched.current.add(fact); setValues((v) => ({ ...v, [fact]: e.target.value })); if (err) setErr(''); }}
                    onKeyDown={(e) => { if (e.key === 'Enter') applyField(); }}
                  />
                </label>
              ))}
            </div>
          )}

          {mode === 'narrative' && (
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

          {mode === 'none' && (
            <div style={{ fontSize: 12.5, color: '#475569', lineHeight: 1.55, background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 10, padding: '12px 14px' }}>
              {resolution.note
                || "This validation can't be fixed by entering a single value - it usually means adding or adjusting a coverage or form. Handle it on the relevant form, then mark it resolved here, or dismiss it with a note."}
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
          {mode === 'none' ? (
            <>
              <button type="button" style={ghostBtn} onClick={() => { onSetStatus?.(issue, 'dismissed'); onClose?.(); }}>Dismiss</button>
              <button type="button" style={primaryBtn} onClick={() => { onSetStatus?.(issue, 'resolved'); onClose?.(); }}>Mark resolved</button>
            </>
          ) : (
            <>
              <button type="button" style={ghostBtn} disabled={busy} onClick={() => onClose?.()}>Cancel</button>
              <button
                type="button"
                style={primaryBtn}
                disabled={busy || (mode === 'schedule' && (loading || !schedule))}
                onClick={mode === 'field' ? applyField : mode === 'narrative' ? applyNarrative : applySchedule}
              >
                {busy ? 'Applying...' : 'Apply'}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
