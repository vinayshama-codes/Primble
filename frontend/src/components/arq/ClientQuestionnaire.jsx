// ClientQuestionnaire.jsx - Final version without restore prompt and error message
import { useState, useEffect, useRef, useCallback } from 'react';
import { API_BASE } from '../../config/constants';
import ScheduleTable from './ScheduleTable';
import { isBlankRow } from '../../utils/scheduleImport';
// BUG-01: the progress rule lives in one pure module so the ring, the badge,
// the per-question styling and the submission receipt cannot disagree.
import {
  decodeRows,
  encodeRows,
  hasResponded as respondedTo,
  progressCounts,
  restoreTouched,
  DRAFT_MARKER,
} from '../../utils/questionnaireProgress';

// Schedule answers (Figure 15) travel through the SAME answers map as every
// other question, JSON-encoded, so draft autosave and submit need no special
// casing. These two helpers are the only place that encoding is known.
// Validation helpers
const EMAIL_RE   = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const PHONE_RE   = /^[\+]?[(]?[0-9]{3}[)]?[-\s\.]?[0-9]{3}[-\s\.]?[0-9]{4,6}$/;
const DATE_RE    = /^\d{1,2}\/\d{1,2}\/\d{4}$|^\d{4}-\d{2}-\d{2}$/;
const NUMBER_RE  = /^\$?[\d,]+(\.\d+)?$/;

// Shown only when the request itself fails (network error / empty response), so
// it must read as a technical hiccup - not as the assistant refusing to answer.
const FALLBACK_REPLY = "Sorry, I couldn't reach the assistant just now. Please try again in a moment, or ask your broker.";

// Client requirement (Figure 14): a client who genuinely cannot answer a question
// - SIC / NAICS being the canonical example - must be able to say so and move on
// rather than abandoning the questionnaire.
//
// This sentinel is stored like any other answer while drafting (so it survives a
// close-and-return), but the server splits it out at submit time into a separate
// follow-up list. It is never written into an ACORD field and never counts as an
// answer. MUST stay identical to NOT_SURE_SENTINEL in backend/services/arq_service.py.
const NOT_SURE = '__NOT_SURE__';

// Chat bubbles render plain text, so any Markdown the assistant emits would be
// shown to the client literally ("**238160**"). The system prompt already asks
// for plain text; this is the belt-and-braces strip for when the model does it
// anyway. Deliberately conservative - it only unwraps the emphasis markers that
// are unambiguous, and leaves list dashes and ordinary punctuation alone.
function stripMarkdown(text) {
  return (text || '')
    .replace(/\*\*(.+?)\*\*/gs, '$1')
    .replace(/__(.+?)__/gs, '$1')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/^\s{0,3}#{1,6}\s+/gm, '');
}

function isEmailField(fieldName) {
  return /email/i.test(fieldName);
}
function isPhoneField(fieldName) {
  return /phone|fax|tel/i.test(fieldName);
}

// ---------------------------------------------------------------------------
// Structured input types (Figure 18)
// ---------------------------------------------------------------------------
// The backend now sends field_type "currency" | "date" | "code" | "number" for
// questions that hold exactly one scalar (see _FIELD_INPUT_TYPE in
// arq_service.py). These helpers mirror the SERVER normalizers one-for-one, so
// what the client sees on blur is exactly what gets stored - no surprise
// reformatting after submit.
//
// Every one of them is forgiving by design: if a value cannot be parsed it is
// returned UNCHANGED rather than cleared. Losing what a client typed is the
// bug this whole change exists to fix.

const MONTHS = { jan: 1, feb: 2, mar: 3, apr: 4, may: 5, jun: 6,
                 jul: 7, aug: 8, sep: 9, oct: 10, nov: 11, dec: 12 };

function pad2(n) { return String(n).padStart(2, '0'); }

// Mirrors _fmt_date: rejects impossible dates such as 02/31.
function fmtDateParts(y, mo, d) {
  if (mo < 1 || mo > 12 || d < 1 || d > 31) return null;
  const dt = new Date(y, mo - 1, d);
  if (dt.getFullYear() !== y || dt.getMonth() !== mo - 1 || dt.getDate() !== d) return null;
  return `${pad2(mo)}/${pad2(d)}/${y}`;
}

// Mirrors _normalize_date. Returns MM/DD/YYYY, or null when unreadable.
function normalizeDate(raw) {
  const s = (raw || '').trim();
  if (!s) return null;
  let m;
  if ((m = s.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/)))
    return fmtDateParts(+m[1], +m[2], +m[3]);
  if ((m = s.match(/^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2}|\d{4})$/))) {
    let y = +m[3];
    if (y < 100) y += y >= 70 ? 1900 : 2000;
    return fmtDateParts(y, +m[1], +m[2]);
  }
  if ((m = s.match(/^([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})$/))) {
    const mo = MONTHS[m[1].slice(0, 3).toLowerCase()];
    if (mo) return fmtDateParts(+m[3], mo, +m[2]);
  }
  if ((m = s.match(/^(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})$/))) {
    const mo = MONTHS[m[2].slice(0, 3).toLowerCase()];
    if (mo) return fmtDateParts(+m[3], mo, +m[1]);
  }
  return null;
}

// Mirrors _normalize_currency, including the "keep the trailing qualifier"
// rule ("$20,000 per month") and the "leave compound answers alone" guard
// ("$1,000,000 / $2,000,000" is two amounts, not one).
function normalizeCurrency(raw) {
  const s = (raw || '').trim();
  if (!s) return null;
  const m = s.match(/^\$?\s*([\d,]*\.?\d+)\s*([kKmM])?\b(.*)$/);
  if (!m) return null;
  let amount = parseFloat(m[1].replace(/,/g, ''));
  if (!isFinite(amount)) return null;
  const suffix = (m[2] || '').toLowerCase();
  if (suffix === 'k') amount *= 1000;
  if (suffix === 'm') amount *= 1000000;
  const rest = (m[3] || '').trim().replace(/^[,;]+|[,;]+$/g, '');
  if (rest && /^[/\-]?\s*\$?[\d,]/.test(rest)) return null;
  const body = amount % 1
    ? `$${amount.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`.replace('.00', '')
    : `$${amount.toLocaleString('en-US')}`;
  return rest ? `${body} ${rest}` : body;
}

// Mirrors _normalize_code. FEIN (9 digits) is written XX-XXXXXXX on ACORD.
function normalizeCode(raw, digits) {
  const s = (raw || '').trim();
  if (!s) return null;
  const d = s.replace(/\D/g, '');
  if (!d) return s;
  if (digits && d.length !== digits) return s;
  return digits === 9 ? `${d.slice(0, 2)}-${d.slice(2)}` : d;
}

export default function ClientQuestionnaire({ token }) {
  const [loading, setLoading]         = useState(true);
  const [error, setError]             = useState(null);
  const [questions, setQuestions]     = useState([]);
  const [submitting, setSubmitting]   = useState(false);
  const [submitted, setSubmitted]     = useState(false);
  const [expiresAt, setExpiresAt]     = useState(null);
  const [clientName, setClientName]   = useState('');
  const [fieldErrors, setFieldErrors] = useState({});
  const [answers, setAnswersState]    = useState({});
  const [scoreUpdate, setScoreUpdate] = useState(null);  // §6.2 post-remediation feedback
  // Figure 21: frozen snapshot of what the client actually submitted, built at
  // the moment of submission and never mutated afterwards. Stays null on the
  // "already submitted" path (nothing was loaded to summarise), which the
  // confirmation screen handles by simply omitting the summary.
  const [receipt, setReceipt]         = useState(null);
  const [receiptRef, setReceiptRef]   = useState('');

  // Producer contact info
  const [producerEmail, setProducerEmail] = useState('');
  const [producerPhone, setProducerPhone] = useState('');
  const [producerName, setProducerName]   = useState('');

  // Draft save state
  const draftTimerRef    = useRef(null);
  const pendingAnswersRef = useRef({});

  // BUG-01: progress must measure the CLIENT's contribution, never the box's
  // contents. A schedule question ships PRE-FILLED with rows extraction already
  // found (that is deliberate - the client edits a known fleet instead of
  // retyping it), so counting "is there something in this field?" reported
  // 1/11 = 9% on a questionnaire nobody had touched yet.
  //
  // Two pieces of state answer the two different questions:
  //   * `seedRef`     - exactly what the SERVER handed us at load. Frozen.
  //   * `touched`     - field names the client has actually changed. STICKY:
  //                     once set it never clears, so deleting five rows and
  //                     retyping the same five does not walk the bar backwards.
  // Both are needed. A pure seed-vs-now diff fails the retype case; a pure
  // touch flag cannot tell a typed-then-cleared box from an untouched one.
  const seedRef = useRef({});
  const [touched, setTouched] = useState(() => new Set());
  // Refs mirror both maps SYNCHRONOUSLY. `setAnswers` has to diff against the
  // previous answers and union into the previous touch set in the same tick,
  // and two edits inside one tick (tapping a NAICS chip, then typing) would
  // read stale values from either React state or a useEffect-updated ref.
  const answersRef = useRef({});
  const touchedRef = useRef(new Set());

  // Chat state
  const [chatOpen, setChatOpen]       = useState(false);
  // Figure 19: the greeting is NOT stored in history - it is derived on every
  // render from what the client is actually looking at, so it stays accurate as
  // they move down the form, and it never gets replayed back to the model.
  const [chatHistory, setChatHistory] = useState([]);
  // The question the client currently has focused. Sent to the assistant so an
  // unqualified "where do I find this?" resolves to the right field.
  const [activeField, setActiveField] = useState('');
  const [chatInput, setChatInput]     = useState('');
  const [chatLoading, setChatLoading] = useState(false);
  const chatBottomRef                 = useRef(null);
  const chatInputRef                  = useRef(null);

  // Server-side draft save (debounced 1s) - works across browsers, incognito, devices
  // The draft carries ONLY what the client has touched. It used to carry the
  // whole answer map - every untouched empty box and, worse, the pre-filled
  // schedule seed - so on reload there was no way to tell our own pre-fill from
  // the client's work. Touched-only makes the stored draft mean exactly one
  // thing ("what the client supplied"), which is also what restores `touched`
  // across a reload with no extra column and no extra request.
  const saveDraftToServer = useCallback((currentAnswers, touchedKeys) => {
    if (!token) return;
    if (draftTimerRef.current) clearTimeout(draftTimerRef.current);
    const draft = { [DRAFT_MARKER]: '1' };
    touchedKeys.forEach((k) => { draft[k] = currentAnswers[k] ?? ''; });
    pendingAnswersRef.current = draft;
    draftTimerRef.current = setTimeout(() => {
      fetch(`${API_BASE}/api/arq/draft/${token}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ answers: pendingAnswersRef.current }),
      }).catch(() => {}); // silent - draft save failures are non-critical
    }, 1000);
  }, [token]);

  // Wrapper so the rest of the component calls setAnswers (same as before).
  //
  // Every mutation in this file funnels through here - typing, selecting,
  // toggling "I'm not sure", tapping a NAICS chip, and every schedule edit
  // (ScheduleTable routes cell edits, row adds, row deletes and spreadsheet
  // imports through its single `onChange`). So this is the ONE place that has
  // to record a touch, and any question type added later inherits the correct
  // behaviour without a second edit.
  //
  // Touch is recorded by DIFFING prev against next, not by trusting the caller:
  // a no-op write (the blur normaliser re-setting an identical value) must not
  // mark a field the client never changed.
  const setAnswers = useCallback((updates) => {
    // Editing anything clears the blocked-submit banner, so a stale "fix these
    // fields" message never lingers after the client has fixed them.
    setError(null);
    const prev = answersRef.current;
    const next = typeof updates === 'function' ? updates(prev) : { ...prev, ...updates };
    // Touch is recorded by DIFFING prev against next, never by trusting the
    // caller: the blur normaliser re-writes an identical value, and that must
    // not mark a field the client never changed.
    const changed = Object.keys(next).filter(k => next[k] !== prev[k]);
    answersRef.current = next;
    if (changed.length) {
      const grew = changed.some(k => !touchedRef.current.has(k));
      if (grew) {
        touchedRef.current = new Set([...touchedRef.current, ...changed]);
        setTouched(touchedRef.current);
      }
      saveDraftToServer(next, touchedRef.current);
    }
    setAnswersState(next);
  }, [saveDraftToServer]);

  // Flush any pending draft save immediately (used on submit)
  const flushDraft = useCallback(() => {
    if (draftTimerRef.current) {
      clearTimeout(draftTimerRef.current);
      draftTimerRef.current = null;
    }
  }, []);

  const validateAnswers = useCallback(() => {
    const errors = {};
    questions.forEach((q) => {
      const val = (answers[q.field_name] || '').trim();
      // "I'm not sure" is a valid, deliberate response - never validate it as if
      // it were a typed answer (it would fail every format rule below).
      if (val === NOT_SURE) return;
      // Schedules validate per cell inside the table itself, and a partly-filled
      // fleet is deliberately still submittable - so they are never blocked here.
      if (q.field_type === 'schedule') return;
      if (!val || q.field_type === 'checkbox' || q.field_type === 'select') return;
      const ft = q.field_type || 'text';
      const fn = q.field_name;

      if (isEmailField(fn) && !EMAIL_RE.test(val)) {
        errors[fn] = 'Enter a valid email address (e.g. john@company.com)';
      } else if (isPhoneField(fn) && !PHONE_RE.test(val.replace(/\s/g, ''))) {
        errors[fn] = 'Enter a valid phone number (e.g. (512) 555-1234)';
      } else if (ft === 'date') {
        // Accept anything the shared normalizer can read, not just the two
        // literal shapes DATE_RE matched - "June 1, 2025" is a valid answer.
        if (!normalizeDate(val) && !DATE_RE.test(val))
          errors[fn] = 'Use MM/DD/YYYY format (e.g. 01/15/2025)';
      } else if (ft === 'currency') {
        if (!normalizeCurrency(val))
          errors[fn] = 'Enter a dollar amount (e.g. $200,000)';
      } else if (ft === 'code') {
        const digits = q.code_digits || 0;
        const got    = val.replace(/\D/g, '');
        if (digits && got.length !== digits)
          errors[fn] = `This code should be ${digits} digits - you entered ${got.length}`;
      } else if (ft === 'number' && !NUMBER_RE.test(val.replace(/\s/g, ''))) {
        errors[fn] = 'Enter a valid number or dollar amount (e.g. $500,000)';
      } else if (ft === 'text' && val.length < 2) {
        errors[fn] = 'Please provide more detail';
      }
    });
    return errors;
  }, [questions, answers]);

  const sendChatMessage = async () => {
    const msg = chatInput.trim();
    if (!msg || chatLoading) return;

    // Basic sanitization - strip script tags
    const sanitized = msg.replace(/<[^>]*>/g, '').slice(0, 500);

    const userMsg = { role: 'user', content: sanitized };
    const newHistory = [...chatHistory, userMsg];
    setChatHistory(newHistory);
    setChatInput('');
    setChatLoading(true);

    try {
      const res  = await fetch(`${API_BASE}/api/arq/chat/${token}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: sanitized,
          history: chatHistory.filter(h => h.role !== 'system'),
          active_field: activeField,
        }),
      });
      const data = await res.json();
      const reply = (data.reply || '').trim() || FALLBACK_REPLY;
      setChatHistory(prev => [...prev, { role: 'assistant', content: reply }]);
    } catch {
      setChatHistory(prev => [...prev, { role: 'assistant', content: FALLBACK_REPLY }]);
    } finally {
      setChatLoading(false);
    }
  };

  // Figure 19: a context-aware opener. The old greeting was a fixed "What
  // questions do you have about this document?" - it told the client nothing and
  // ignored where they actually were on the form.
  // Clip on a word boundary - cutting mid-word ("(NAICS cod...") reads as a
  // rendering glitch to the client rather than as a deliberate shortening.
  const clipQ = (s) => {
    const t = (s || '').trim();
    if (t.length <= 70) return t;
    const cut = t.slice(0, 67);
    const sp  = cut.lastIndexOf(' ');
    return `${(sp > 40 ? cut.slice(0, sp) : cut).replace(/[\s(,;:-]+$/, '')}...`;
  };
  // UI-02: the opener names itself AND names a question that is genuinely still
  // open, so the client can see what the assistant is for without typing first.
  //
  // "Still open" is read off `respondedTo` - the SAME door the progress bar and
  // the receipt use - so the greeting can never offer a question the bar counts
  // as done, nor stay silent on one it counts as remaining. It used to test
  // `answers[...]` directly and skip schedules outright: a table the producer
  // pre-loaded and the client never opened read as ANSWERED to that rule while
  // the bar called it remaining, and a questionnaire whose only gaps were
  // schedules got the "everything is answered" greeting.
  const chatGreeting = (() => {
    const active = questions.find(q => q.field_name === activeField);
    if (active) {
      return `Hi! I'm your automated forms assistant. You're on "${clipQ(active.question)}" - `
           + `I can explain what it means, where to find it, or what format it needs. Ask away.`;
    }
    const next = questions.find(
      q => !respondedTo(q, answers[q.field_name], seedRef.current[q.field_name], touched)
    );
    if (next) {
      return `Hi! I'm your automated forms assistant. For example, "${clipQ(next.question)}" is still open, `
           + `so feel free to ask me about that or anything else on this questionnaire.`;
    }
    return `Hi! I'm your automated forms assistant. Ask me what any question on this questionnaire means, `
         + `or where to find the information it's asking for.`;
  })();

  // Open the assistant already pointed at one specific question.
  const askAboutField = useCallback((fieldName) => {
    setActiveField(fieldName);
    setChatOpen(true);
  }, []);

  // Auto-scroll chat
  useEffect(() => {
    if (chatOpen) chatBottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatHistory, chatOpen]);

  // Focus input when chat opens
  useEffect(() => {
    if (chatOpen) setTimeout(() => chatInputRef.current?.focus(), 150);
  }, [chatOpen]);

  // Load questionnaire data - runs once per token
  useEffect(() => {
    if (!token) {
      setError('Invalid questionnaire link.');
      setLoading(false);
      return;
    }

    const controller = new AbortController();

    fetch(`${API_BASE}/api/arq/client-view/${token}`, { signal: controller.signal })
      .then((res) => res.json())
      .then((data) => {
        if (data.success) {
          const qs = data.questions || [];
          setQuestions(qs);
          setExpiresAt(data.expires_at);
          setClientName(data.client_name || '');
          setProducerEmail(data.producer_email || '');
          setProducerPhone(data.producer_phone || '');
          setProducerName(data.producer_name || '');

          // Build baseline from server values, then overlay server-side draft answers.
          // draft_answers are saved server-side so they survive incognito / different browsers.
          const init = {};
          qs.forEach((q) => {
            // A schedule seeds from the rows already known (extracted from the
            // documents, or pre-loaded by the agent) so the client edits a
            // populated table instead of re-typing a fleet from scratch.
            init[q.field_name] = q.field_type === 'schedule'
              ? encodeRows(q.current_rows || [])
              : (q.current_value || '');
          });
          // Freeze what the SERVER supplied before the draft is layered on. This
          // is the baseline every "did the client provide this?" question is
          // measured against, and it must never include the client's own work.
          seedRef.current = init;
          const serverDraft = data.draft_answers || {};
          // The draft holds only fields the client has touched (see
          // `saveDraftToServer`), so its key set IS the restored touch record -
          // no extra column, no extra request. A pre-fix draft may still carry
          // untouched keys; those restore as touched, which over-counts by at
          // most the old behaviour and never under-counts real work.
          // One rule, in `utils/questionnaireProgress`, so a pre-fix draft
          // cannot quietly restore our own pre-fill as the client's work.
          const restored = restoreTouched(serverDraft, init);
          touchedRef.current = restored.touched;
          setTouched(restored.touched);
          answersRef.current = { ...init, ...restored.answers };
          setAnswersState(answersRef.current);
        } else if (data.error === 'expired') {
          setError('This questionnaire link has expired. Please contact your insurance broker for a new link.');
        } else if (data.error === 'already_submitted') {
          setSubmitted(true);
        } else {
          setError(data.message || 'Failed to load questionnaire');
        }
      })
      .catch((err) => {
        if (err.name !== 'AbortError') setError('Network error. Please try again.');
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });

    return () => controller.abort();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  // Cleanup debounce timer on unmount
  useEffect(() => {
    return () => {
      if (draftTimerRef.current) clearTimeout(draftTimerRef.current);
    };
  }, []);

  // ── Progress (BUG-01) ────────────────────────────────────────────────────
  // Progress counts anything the client has RESPONDED to, including "I'm not
  // sure" - the goal is to show forward motion so nobody gets stuck on a
  // question they cannot answer.
  //
  // What it must NOT count is our own pre-fill. A schedule question arrives
  // holding the rows extraction already found, so the previous test ("does this
  // field hold content?") reported one answered question before the client had
  // typed anything.
  //
  // One call, one rule (see `utils/questionnaireProgress`). "I'm not sure" is
  // split out because it is a response but not an answer: both move the bar,
  // and saying which is which is the whole point of showing the split.
  const hasResponded = (q) =>
    respondedTo(q, answers[q.field_name], seedRef.current[q.field_name], touched);

  const {
    answered:  answeredCount,
    notSure:   notSureCount,
    responded: respondedCount,
    remaining: remainingCount,
    pct:       progressPct,
  } = progressCounts(questions, answers, seedRef.current, touched, NOT_SURE);

  const isNotSure = (fieldName) => (answers[fieldName] || '').trim() === NOT_SURE;

  // Toggling "I'm not sure" clears any typed value; toggling it off restores an
  // empty input so the client can type a real answer.
  const toggleNotSure = (fieldName) => {
    setAnswers({ [fieldName]: isNotSure(fieldName) ? '' : NOT_SURE });
    setFieldErrors((prev) => {
      const n = { ...prev };
      delete n[fieldName];
      return n;
    });
  };

  // Figure 21: the confirmation used to say only "thank you", so a client had no
  // way to check what actually went across - and no record of it once the tab
  // was closed. This builds that summary from the SAME rules the progress
  // counter uses (a schedule counts once it holds a non-blank row; "I'm not
  // sure" is a response but not an answer), so the two can never disagree.
  //
  // Called once, immediately before the screen swaps, and the result is frozen
  // in state: a summary that could drift from what was sent is worse than none.
  const buildReceipt = () => {
    const items = [];
    let answeredItems = 0;
    let notSureItems  = 0;

    questions.forEach((q) => {
      const raw = answers[q.field_name];

      // Built from `hasResponded`, the SAME rule the progress counter uses, so
      // the receipt can never credit the client for a table we pre-filled and
      // they never opened.
      if (!hasResponded(q)) return;

      if (q.field_type === 'schedule') {
        const rows = decodeRows(raw).filter((r) => !isBlankRow(r, q.columns || []));
        const singular = q.schedule_singular || 'row';
        answeredItems += 1;
        items.push({
          key:   q.field_name,
          label: q.question,
          // An emptied table is a real answer ("we do not have any"), and saying
          // "0 provided" would read like a failure to fill it in.
          value: rows.length
            ? `${rows.length} ${rows.length === 1 ? singular : `${singular}s`} provided`
            : `Confirmed none - the pre-filled ${singular}s were removed`,
          kind:  'answer',
        });
        return;
      }

      const val = (raw || '').trim();
      if (!val) return;

      if (val === NOT_SURE) {
        notSureItems += 1;
        items.push({ key: q.field_name, label: q.question, value: 'Marked "I\'m not sure"', kind: 'notsure' });
        return;
      }

      answeredItems += 1;
      items.push({ key: q.field_name, label: q.question, value: val, kind: 'answer' });
    });

    return { items, answeredItems, notSureItems, total: questions.length };
  };

  const handleSubmit = async () => {
    // A badly formatted answer is BLOCKED, not warned about. It used to be
    // submittable, and "sometime in December" then landed in the ACORD
    // PROPOSED EXP DATE box highlighted green - indistinguishable from a
    // verified answer on a form an underwriter reads.
    //
    // This can never dead-end anyone: blank is always allowed, and every
    // question keeps its "I'm not sure" escape hatch, which the message below
    // points at explicitly. The server enforces the same rule (422) for a
    // request that does not come from this page.
    const errors = validateAnswers();
    if (Object.keys(errors).length) {
      const n = Object.keys(errors).length;
      setFieldErrors(errors);
      setError(
        `${n} answer${n !== 1 ? 's need' : ' needs'} a small correction before you can submit - ` +
        `${n !== 1 ? 'they are' : 'it is'} highlighted in red below. ` +
        `If you are not sure of the right format, tap "I'm not sure" on that question instead.`
      );
      const first = Object.keys(errors)[0];
      document.getElementById(`q-${first}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      return;
    }

    flushDraft();
    setFieldErrors({});
    setSubmitting(true);
    setError(null);
    try {
      const res  = await fetch(`${API_BASE}/api/arq/submit/${token}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        // `touched` tells the server which fields the CLIENT supplied, so an
        // untouched pre-filled schedule is never written back as a client
        // answer. The server also re-derives this from its own copy of the
        // seed, so a payload that omits or fakes the list cannot mislabel
        // provenance - this only adds the cases the seed cannot see (a table
        // emptied, or restored to identical values).
        body: JSON.stringify({ answers, touched: Array.from(touched) }),
      });
      const data = await res.json();
      if (res.ok && data.success) {
        // Built from the answers that were just accepted, before the view
        // swaps. Never allowed to break a successful submission: if the
        // summary cannot be built the client still gets their confirmation.
        try { setReceipt(buildReceipt()); } catch { setReceipt(null); }
        // Server-side receipt reference (Figure 21). Empty when the receipt
        // could not be written - the summary still renders, just without a
        // reference to quote, which is honest rather than inventing one.
        setReceiptRef(data.receipt_ref || '');
        setScoreUpdate(data.score_update || null);
        setSubmitted(true);
      } else if (res.status === 422 && data.field_errors) {
        setFieldErrors(data.field_errors);
        setError('Please fix the highlighted fields and resubmit.');
        const first = Object.keys(data.field_errors)[0];
        document.getElementById(`q-${first}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      } else {
        setError(data.message || 'Failed to submit answers. Please try again.');
      }
    } catch {
      setError('Network error. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  const formatDate = (dateStr) => {
    if (!dateStr) return '';
    return new Date(dateStr).toLocaleDateString('en-US', {
      year: 'numeric', month: 'long', day: 'numeric',
      hour: '2-digit', minute: '2-digit',
    });
  };

  // Agent escalation card - FLOATING (Top position, above save button)
  const AgentContactCard = () => {
    if (!producerEmail && !producerPhone && !producerName) return null;
    return (
      <div style={{
        background: '#f0f9ff',
        border: '1px solid #bae6fd',
        borderRadius: 12,
        padding: '12px 16px',
        fontSize: 13,
        width: '240px',
        boxShadow: '0 4px 12px rgba(0,0,0,0.1)',
        marginBottom: '12px',
      }}>
        <div style={{ fontWeight: 700, color: '#0369a1', marginBottom: 6 }}>Contact Your Broker</div>
        {producerName && <div style={{ color: '#0f172a', marginBottom: 4 }}>{producerName}</div>}
        {producerEmail && (
          <div style={{ color: '#475569', marginBottom: 2 }}>
            <a href={`mailto:${producerEmail}`} style={{ color: '#0369a1', textDecoration: 'none' }}>{producerEmail}</a>
          </div>
        )}
        {producerPhone && (
          <div style={{ color: '#475569' }}>
            <a href={`tel:${producerPhone}`} style={{ color: '#0369a1', textDecoration: 'none' }}>{producerPhone}</a>
          </div>
        )}
      </div>
    );
  };

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh', flexDirection: 'column', gap: 16 }}>
        <div style={{ width: 40, height: 40, border: '3px solid #e2e8f0', borderTopColor: '#E61B84', borderRadius: '50%', animation: 'spin 0.7s linear infinite' }} />
        <p style={{ color: '#64748b' }}>Loading your questionnaire...</p>
        <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      </div>
    );
  }

  if (submitted) {
    return (
      <div style={{ maxWidth: 600, margin: '40px auto', padding: '32px 24px', textAlign: 'center', background: '#fff', borderRadius: 16, boxShadow: '0 4px 20px rgba(0,0,0,0.08)', border: '1px solid #e2e8f0' }}>
        <h2 style={{ fontSize: 24, fontWeight: 700, marginBottom: 12, color: '#1e293b' }}>Thank You!</h2>
        <p style={{ fontSize: 16, color: '#475569', marginBottom: 24 }}>
          Your answers have been submitted successfully. Your insurance broker has been notified and the forms will be updated automatically.
        </p>
        {scoreUpdate && (() => {
          // All 7 post-remediation states from §6.2 - messages are plain-language
          // and client-appropriate; nothing technical leaks to the client.
          const msgs = {
            resolved:                    { text: 'Your answers resolved outstanding items on this submission - thank you!',                                          bg: '#ecfdf5', border: '#a7f3d0', color: '#065f46' },
            improved:                    { text: 'Your answers improved this submission - thank you!',                                                               bg: '#ecfdf5', border: '#a7f3d0', color: '#065f46' },
            pending_validation:          { text: 'Your answers have been received and are pending review by your broker.',                                            bg: '#eff6ff', border: '#bfdbfe', color: '#1e40af' },
            user_provided_only:          { text: 'Your answers have been recorded. Your broker will confirm the details.',                                            bg: '#eff6ff', border: '#bfdbfe', color: '#1e40af' },
            conflicting_evidence_remains:{ text: 'Your answers have been submitted. Your broker will review a few items that need clarification.',                    bg: '#fffbeb', border: '#fde68a', color: '#92400e' },
            requires_supporting_document:{ text: 'Your answers have been submitted. You may also need to provide supporting documents - your broker will be in touch.', bg: '#fffbeb', border: '#fde68a', color: '#92400e' },
            still_missing:               { text: 'Your answers have been submitted. Your broker may follow up for any remaining information.',                         bg: '#f1f5f9', border: '#cbd5e1', color: '#475569' },
          };
          const m = msgs[scoreUpdate.status];
          if (!m) return null;
          return (
            <p style={{ fontSize: 14, color: m.color, background: m.bg, border: `1px solid ${m.border}`, borderRadius: 8, padding: '10px 14px', marginBottom: 24, lineHeight: 1.5 }}>
              {m.text}
            </p>
          );
        })()}

        {/* Figure 21: mini-summary of what was actually submitted. Read-only,
            built client-side from the frozen snapshot - it never re-fetches and
            never re-renders from live answer state, so what is shown here is
            exactly what was sent. Omitted entirely when there is no snapshot
            (a client returning to an already-submitted link). */}
        {receipt && receipt.items.length > 0 && (
          <div style={{
            textAlign: 'left', border: '1px solid #e2e8f0', borderRadius: 10,
            background: '#f8fafc', padding: '14px 16px', marginBottom: 20,
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 10, marginBottom: 3 }}>
              <div style={{ fontSize: 13, fontWeight: 700, color: '#0f172a' }}>
                Summary of what you sent
              </div>
              {receiptRef && (
                <div style={{ fontSize: 10.5, color: '#94a3b8', fontFamily: 'monospace', flexShrink: 0 }}
                     title="Quote this reference if you contact your broker about this submission">
                  Ref {receiptRef}
                </div>
              )}
            </div>
            <div style={{ fontSize: 12, color: '#64748b', marginBottom: 10 }}>
              {receipt.answeredItems} of {receipt.total} question{receipt.total !== 1 ? 's' : ''} answered
              {receipt.notSureItems > 0 && ` - ${receipt.notSureItems} marked "I'm not sure"`}
            </div>
            <div style={{ maxHeight: 240, overflowY: 'auto', paddingRight: 4 }}>
              {receipt.items.map((it, i) => {
                // Long narrative answers are trimmed for display only; the full
                // value was already sent and stored server-side.
                const shown = it.value.length > 140 ? `${it.value.slice(0, 140)}...` : it.value;
                return (
                  <div
                    key={it.key}
                    style={{
                      padding: '7px 0',
                      borderBottom: i < receipt.items.length - 1 ? '1px solid #e8edf3' : 'none',
                    }}
                  >
                    <div style={{ fontSize: 11, color: '#64748b', lineHeight: 1.45, marginBottom: 2 }}>
                      {it.label}
                    </div>
                    <div style={{
                      fontSize: 12.5, lineHeight: 1.45, wordBreak: 'break-word',
                      color: it.kind === 'notsure' ? '#92400e' : '#0f172a',
                      fontWeight: it.kind === 'notsure' ? 500 : 600,
                    }}>
                      {shown}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Always shown, deliberately outside the scoreUpdate block above: that
            banner is absent whenever score recalculation was skipped or failed,
            and the client must never be left wondering whether something more is
            expected of them. */}
        <p style={{ fontSize: 13, color: '#475569', marginBottom: 24, lineHeight: 1.55 }}>
          You don't need to do anything else right now. If anything further is needed,
          your broker{producerName ? ` (${producerName})` : ''} will follow up with you directly.
        </p>

        <button onClick={() => window.close()} style={{ padding: '12px 28px', background: '#E61B84', color: '#fff', border: 'none', borderRadius: 8, fontSize: 14, fontWeight: 600, cursor: 'pointer', minWidth: 140 }}>
          Close Window
        </button>
      </div>
    );
  }

  if (error && !questions.length) {
    return (
      <div style={{ maxWidth: 500, margin: '40px auto', padding: '32px 24px', textAlign: 'center', background: '#fff', borderRadius: 16, boxShadow: '0 4px 20px rgba(0,0,0,0.08)', border: '1px solid #fee2e2' }}>
        <h2 style={{ fontSize: 20, fontWeight: 600, marginBottom: 12, color: '#dc2626' }}>Questionnaire Unavailable</h2>
        <p style={{ fontSize: 14, color: '#475569', marginBottom: 24 }}>{error}</p>
        <p style={{ fontSize: 13, color: '#64748b', marginBottom: 20 }}>Please contact your broker for further assistance.</p>
        <AgentContactCard />
        <button onClick={() => window.close()} style={{ marginTop: 20, padding: '10px 24px', background: '#64748b', color: '#fff', border: 'none', borderRadius: 6, fontSize: 13, cursor: 'pointer' }}>Close</button>
      </div>
    );
  }

  return (
    <div style={{ minHeight: '100vh', background: '#f8fafc', padding: '20px 16px' }}>
      <div style={{ maxWidth: 720, margin: '0 auto', background: '#fff', borderRadius: 20, boxShadow: '0 8px 30px rgba(0,0,0,0.08)', overflow: 'hidden' }}>

        {/* Header */}
        <div style={{ padding: '24px 24px 20px', background: 'linear-gradient(135deg, #0f172a 0%, #1e293b 100%)', color: '#fff', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <h1 style={{ fontSize: 20, fontWeight: 700, marginBottom: 6 }}>Insurance Information Needed</h1>
            <p style={{ fontSize: 13, opacity: 0.9 }}>
              {clientName ? `Hi ${clientName},` : 'Hello,'} your insurance broker needs a few details to complete your application.
            </p>
            {expiresAt && (
              <p style={{ fontSize: 11, opacity: 0.7, marginTop: 8 }}>Expires: {formatDate(expiresAt)}</p>
            )}
            {/* The ring shows ONE number; this says what it is made of. It sits
                in the header, next to the ring it explains - it used to be a
                third line of grey helper text under "Questions (N)", where it
                read as more instructions and nobody saw it. Chips, not prose,
                so the three states are scannable at a glance. */}
            {respondedCount > 0 && (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 12 }}>
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 11, fontWeight: 600,
                               background: 'rgba(16,185,129,0.18)', color: '#6ee7b7',
                               border: '1px solid rgba(110,231,183,0.35)', borderRadius: 20, padding: '3px 9px' }}>
                  <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#34d399' }} />
                  {answeredCount} answered
                </span>
                {notSureCount > 0 && (
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 11, fontWeight: 600,
                                 background: 'rgba(251,191,36,0.18)', color: '#fcd34d',
                                 border: '1px solid rgba(252,211,77,0.35)', borderRadius: 20, padding: '3px 9px' }}>
                    <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#fbbf24' }} />
                    {notSureCount} not sure
                  </span>
                )}
                {remainingCount > 0 && (
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 11, fontWeight: 600,
                                 background: 'rgba(255,255,255,0.10)', color: 'rgba(255,255,255,0.75)',
                                 border: '1px solid rgba(255,255,255,0.18)', borderRadius: 20, padding: '3px 9px' }}>
                    <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'rgba(255,255,255,0.55)' }} />
                    {remainingCount} to go
                  </span>
                )}
              </div>
            )}
          </div>

          {questions.length > 0 && (() => {
            const pct  = progressPct;
            const r    = 20;
            const circ = 2 * Math.PI * r;
            return (
              <div
                title={`${answeredCount} answered`
                       + (notSureCount > 0 ? `, ${notSureCount} marked "I'm not sure"` : '')
                       + `, ${remainingCount} still open`}
                style={{ flexShrink: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
                <svg width="56" height="56" viewBox="0 0 52 52">
                  <circle cx="26" cy="26" r={r} fill="none" stroke="rgba(255,255,255,0.15)" strokeWidth="5" />
                  <circle cx="26" cy="26" r={r} fill="none" stroke="#E61B84" strokeWidth="5"
                    strokeDasharray={circ} strokeDashoffset={circ - (pct / 100) * circ}
                    strokeLinecap="round" transform="rotate(-90 26 26)"
                    style={{ transition: 'stroke-dashoffset 0.4s ease' }} />
                  <text x="26" y="31" textAnchor="middle" fill="#fff" fontSize="11" fontWeight="700" fontFamily="Arial,sans-serif">{pct}%</text>
                </svg>
                <span style={{ fontSize: 10, color: 'rgba(255,255,255,0.6)' }}>{respondedCount}/{questions.length}</span>
              </div>
            );
          })()}
        </div>

        {/* Auto-save indicator. Gated on the client having actually touched
            something: it used to read off the same broken counter as the
            progress ring, so it announced "auto-saving" on a questionnaire
            where nothing had been typed and nothing had been sent. */}
        {touched.size > 0 && (
          <div style={{
            margin: '12px 20px 0',
            padding: '8px 12px',
            background: '#ecfdf5',
            borderRadius: 6,
            fontSize: 11,
            color: '#065f46',
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            justifyContent: 'flex-start'
          }}>
            <span>Auto-saving in progress...</span>
          </div>
        )}

        {/* Body */}
        <div style={{ padding: '20px 20px' }}>

          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, marginBottom: 20, flexWrap: 'wrap' }}>
            <div>
              <h2 style={{ fontSize: 16, fontWeight: 600, color: '#1e293b', marginBottom: 2 }}>Questions ({questions.length})</h2>
              <p style={{ fontSize: 12, color: '#64748b' }}>Answers are auto-saved as you type. You can close and return later.</p>
              {/* Agent-assist: make the escape hatch discoverable up front so a
                  confusing question never becomes a dead end. */}
              <p style={{ fontSize: 12, color: '#64748b', marginTop: 4 }}>
                Not sure about something? Tap <strong>"I'm not sure"</strong> on that question and your
                broker will take care of it - or tap the <strong>Help</strong> button to ask a question.
              </p>
              {notSureCount > 0 && (
                <p style={{ fontSize: 12, color: '#92400e', marginTop: 6, background: '#fffbeb', border: '1px solid #fde68a', borderRadius: 6, padding: '6px 10px' }}>
                  {notSureCount} question{notSureCount !== 1 ? 's' : ''} marked "I'm not sure" - your broker will follow up on {notSureCount !== 1 ? 'these' : 'this'}.
                </p>
              )}
            </div>
          </div>

          {/* Questions */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {questions.map((q) => {
              const fieldType  = q.field_type || 'text';
              const isCheckbox = fieldType === 'checkbox';
              const isSelect   = fieldType === 'select';
              const isSchedule = fieldType === 'schedule';
              const notSure    = isNotSure(q.field_name);
              // "Not sure" is a response but not an answer - it gets its own
              // amber treatment rather than the green "answered" styling.
              // Same rule as the progress bar (see `hasResponded`), so a card can
              // never render green while the counter says the question is open.
              const isAnswered = hasResponded(q) && !notSure;
              const hasError   = !!fieldErrors[q.field_name];
              const hint       = q.hint || '';
              const isEmailF   = isEmailField(q.field_name);
              const isPhoneF   = isPhoneField(q.field_name);
              // Figure 18: single-scalar structured types get a real input
              // instead of a free-form textarea.
              const isStructured = fieldType === 'currency' || fieldType === 'date'
                                || fieldType === 'code'     || fieldType === 'number';

              return (
                <div
                  id={`q-${q.field_name}`}
                  key={q.field_name}
                  // Figure 19: one handler on the card covers every input type
                  // inside it (textarea, select, structured input, checkbox
                  // button, schedule cells) - React focus events bubble.
                  onFocus={() => setActiveField(q.field_name)}
                  style={{
                    border: `1px solid ${hasError ? '#fca5a5' : notSure ? '#fde68a' : isAnswered ? '#bbf7d0' : '#e2e8f0'}`,
                    borderRadius: 10,
                    padding: '12px 14px',
                    background: hasError ? '#fff5f5' : notSure ? '#fffbeb' : isAnswered ? '#f0fdf4' : '#fff',
                    transition: 'border-color 0.2s, background 0.2s',
                  }}
                >
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                    <div>
                      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8 }}>
                        <label style={{ fontWeight: 500, fontSize: 13, color: '#0f172a', lineHeight: 1.45, flex: 1 }}>
                          {q.question}
                        </label>
                        {/* Figure 19: opens the assistant already pointed at
                            THIS question, so the client never has to re-type
                            which field they mean. */}
                        <button
                          type="button"
                          onClick={() => askAboutField(q.field_name)}
                          title="Ask the Form Assistant about this question"
                          aria-label="Ask the Form Assistant about this question"
                          style={{
                            flexShrink: 0, width: 22, height: 22, borderRadius: '50%',
                            border: '1px solid #e2e8f0', background: '#f8fafc',
                            color: '#64748b', fontSize: 12, fontWeight: 700,
                            cursor: 'pointer', lineHeight: 1, padding: 0,
                            display: 'flex', alignItems: 'center', justifyContent: 'center',
                            transition: 'all 0.15s',
                          }}
                          onMouseEnter={(e) => {
                            e.currentTarget.style.background  = '#fdf2f8';
                            e.currentTarget.style.borderColor = '#E61B84';
                            e.currentTarget.style.color       = '#E61B84';
                          }}
                          onMouseLeave={(e) => {
                            e.currentTarget.style.background  = '#f8fafc';
                            e.currentTarget.style.borderColor = '#e2e8f0';
                            e.currentTarget.style.color       = '#64748b';
                          }}
                        >
                          ?
                        </button>
                      </div>
                      {hint && (
                        <div style={{ marginTop: 5, fontSize: 11, color: '#64748b', lineHeight: 1.5 }}>
                          {hint}
                        </div>
                      )}
                      {/* Figure 20: industry-classification candidates derived from
                          the business's own operations text. These are SUGGESTIONS,
                          never answers - nothing is pre-filled, the client has to tap
                          one, and the copy tells them to confirm it with their broker. */}
                      {!notSure && Array.isArray(q.suggestions) && q.suggestions.length > 0 && (
                        <div style={{ marginTop: 8 }}>
                          <div style={{ fontSize: 11, color: '#7c2d12', marginBottom: 5 }}>
                            Suggested for your business - tap one to use it, then confirm with
                            your broker. Leaving this blank is still fine.
                          </div>
                          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                            {q.suggestions.map((s) => {
                              const picked = (answers[q.field_name] || '').trim() === s.code;
                              const tone = s.confidence === 'high'
                                ? { bg: '#ecfdf5', bd: '#a7f3d0', tx: '#065f46' }
                                : s.confidence === 'medium'
                                  ? { bg: '#fffbeb', bd: '#fde68a', tx: '#92400e' }
                                  : { bg: '#f8fafc', bd: '#e2e8f0', tx: '#475569' };
                              return (
                                <button
                                  key={s.code}
                                  type="button"
                                  onClick={() => setAnswers({ [q.field_name]: s.code })}
                                  title={`Suggestion only - ${s.label}. Confirm with your broker before relying on it.`}
                                  style={{
                                    display: 'flex', alignItems: 'center', gap: 6,
                                    padding: '5px 10px', borderRadius: 16, cursor: 'pointer',
                                    border: `1px solid ${picked ? '#E61B84' : tone.bd}`,
                                    background: picked ? '#fdf2f8' : tone.bg,
                                    color: picked ? '#9d174d' : tone.tx,
                                    fontSize: 11.5, lineHeight: 1.3, textAlign: 'left',
                                    transition: 'all 0.15s',
                                  }}
                                >
                                  <strong>{s.code}</strong>
                                  <span style={{ opacity: 0.85 }}>{s.label}</span>
                                  <span style={{
                                    fontSize: 9.5, textTransform: 'uppercase', letterSpacing: 0.3,
                                    opacity: 0.7, borderLeft: '1px solid currentColor',
                                    paddingLeft: 6, marginLeft: 1,
                                  }}>
                                    {s.confidence}
                                  </span>
                                </button>
                              );
                            })}
                          </div>
                          {q.suggestions.some((s) => (answers[q.field_name] || '').trim() === s.code) && (
                            <div style={{ marginTop: 5, fontSize: 11, color: '#92400e' }}>
                              You picked a suggestion. It is not confirmed - your broker will check it.
                            </div>
                          )}
                        </div>
                      )}
                      {hasError && (
                        <p style={{ margin: '4px 0 0', fontSize: 11, color: '#dc2626' }}>{fieldErrors[q.field_name]}</p>
                      )}
                    </div>

                    <div>
                      {isSchedule ? (
                        <ScheduleTable
                          columns={q.columns || []}
                          rows={decodeRows(answers[q.field_name])}
                          onChange={(rows) => setAnswers({ [q.field_name]: encodeRows(rows) })}
                          label={q.schedule_label || 'Schedule'}
                          singular={q.schedule_singular || 'row'}
                          dedupKeys={q.dedup_keys || []}
                          vinDecode={!!q.vin_decode}
                          rowCapacity={q.row_capacity || 0}
                        />
                      ) : notSure ? (
                        <div style={{
                          padding: '10px 12px', borderRadius: 7, background: '#fef3c7',
                          border: '1px solid #fde68a', color: '#92400e', fontSize: 12.5, lineHeight: 1.5,
                        }}>
                          Marked <strong>"I'm not sure"</strong>. That's fine - you can skip it and your
                          broker will follow up on this one. Tap below if you'd like to answer after all.
                        </div>
                      ) : isCheckbox ? (
                        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                          <button
                            onClick={() => setAnswers({ [q.field_name]: answers[q.field_name] === 'Yes' ? 'No' : 'Yes' })}
                            style={{
                              padding: '8px 18px', borderRadius: 20, border: '1px solid',
                              borderColor: answers[q.field_name] === 'Yes' ? '#E61B84' : '#cbd5e1',
                              background: answers[q.field_name] === 'Yes' ? '#fdf2f8' : '#f8fafc',
                              color: answers[q.field_name] === 'Yes' ? '#E61B84' : '#64748b',
                              fontWeight: 600, fontSize: 13, cursor: 'pointer', transition: 'all 0.15s',
                              minHeight: 40,
                            }}
                          >
                            {answers[q.field_name] === 'Yes' ? '✓ Yes' : 'No'}
                          </button>
                          {!answers[q.field_name] && <span style={{ fontSize: 11, color: '#94a3b8' }}>Tap to answer</span>}
                        </div>
                      ) : isSelect ? (
                        (() => {
                          const rawVal      = answers[q.field_name] ?? '';
                          const isOtherSel  = rawVal === 'Other' || rawVal.startsWith('Other: ');
                          const otherText   = rawVal.startsWith('Other: ') ? rawVal.slice(7) : '';
                          const hasOtherOpt = (q.options || []).includes('Other');
                          return (
                            <>
                              <select
                                value={isOtherSel ? 'Other' : rawVal}
                                onChange={(e) => setAnswers({ [q.field_name]: e.target.value })}
                                style={{
                                  width: '100%', padding: '9px 12px', fontSize: 13,
                                  border: `1px solid ${hasError ? '#fca5a5' : '#e2e8f0'}`,
                                  borderRadius: 7, fontFamily: 'inherit',
                                  boxSizing: 'border-box', outline: 'none',
                                  background: '#fff', minHeight: 44, cursor: 'pointer',
                                  color: rawVal ? '#0f172a' : '#94a3b8',
                                  appearance: 'auto',
                                }}
                              >
                                <option value="" disabled>Select one...</option>
                                {(q.options || []).map((opt) => (
                                  <option key={opt} value={opt}>{opt}</option>
                                ))}
                              </select>
                              {hasOtherOpt && isOtherSel && (
                                <textarea
                                  value={otherText}
                                  onChange={(e) => setAnswers({ [q.field_name]: e.target.value ? `Other: ${e.target.value}` : 'Other' })}
                                  placeholder="Please explain..."
                                  rows={2}
                                  style={{
                                    marginTop: 6, width: '100%', padding: '8px 12px', fontSize: 13,
                                    border: '1px solid #e2e8f0', borderRadius: 7,
                                    fontFamily: 'inherit', boxSizing: 'border-box',
                                    outline: 'none', resize: 'vertical',
                                  }}
                                />
                              )}
                            </>
                          );
                        })()
                      ) : isStructured ? (
                        (() => {
                          const digits = q.code_digits || 0;
                          // Normalizing on BLUR rather than on every keystroke
                          // is deliberate: live re-formatting fights the caret
                          // (typing "1000" into a comma-formatter jumps the
                          // cursor). The client types freely, sees the tidy
                          // value when they move on, and an unparseable entry
                          // is left exactly as typed rather than cleared.
                          const onBlur = (e) => {
                            const val = e.target.value.trim();
                            if (!val) return;
                            let out = val, err = '';
                            if (fieldType === 'date') {
                              out = normalizeDate(val) || val;
                              if (!normalizeDate(val)) err = 'Use MM/DD/YYYY format (e.g. 01/15/2025)';
                            } else if (fieldType === 'currency') {
                              out = normalizeCurrency(val) || val;
                              if (!normalizeCurrency(val)) err = 'Enter a dollar amount (e.g. $200,000)';
                            } else if (fieldType === 'code') {
                              out = normalizeCode(val, digits) || val;
                              const got = val.replace(/\D/g, '');
                              if (digits && got.length !== digits)
                                err = `This code should be ${digits} digits - you entered ${got.length}`;
                            }
                            if (out !== val) setAnswers({ [q.field_name]: out });
                            setFieldErrors((prev) => {
                              const n = { ...prev };
                              if (err) n[q.field_name] = err; else delete n[q.field_name];
                              return n;
                            });
                          };
                          return (
                            <input
                              type="text"
                              value={answers[q.field_name] ?? ''}
                              onChange={(e) => {
                                let v = e.target.value;
                                // Codes and counts are digits only, so stray
                                // characters are dropped as they are typed.
                                if (fieldType === 'code')   v = v.replace(/[^\d-]/g, '').slice(0, digits ? digits + 1 : 20);
                                if (fieldType === 'number') v = v.replace(/[^\d.]/g, '');
                                setAnswers({ [q.field_name]: v });
                                if (fieldErrors[q.field_name])
                                  setFieldErrors((prev) => { const n = { ...prev }; delete n[q.field_name]; return n; });
                              }}
                              onBlur={onBlur}
                              placeholder={
                                fieldType === 'date' ? 'MM/DD/YYYY' :
                                // NOT "$0" - a placeholder shaped like a value
                                // reads as an answer the client already gave,
                                // and an empty box looking like a zero payroll
                                // is exactly the wrong thing to show.
                                fieldType === 'currency' ? 'Amount...' :
                                fieldType === 'code'     ? (digits ? `${digits} digits` : 'Your answer...') :
                                                           'Your answer...'
                              }
                              inputMode={fieldType === 'currency' ? 'decimal' : 'numeric'}
                              autoComplete="off"
                              style={{
                                width: '100%', padding: '9px 12px', fontSize: 13,
                                border: `1px solid ${hasError ? '#fca5a5' : '#e2e8f0'}`,
                                borderRadius: 7, fontFamily: 'inherit',
                                boxSizing: 'border-box', outline: 'none',
                                transition: 'border-color 0.2s',
                                display: 'block', background: '#fff', minHeight: 44,
                              }}
                              maxLength={100}
                            />
                          );
                        })()
                      ) : (
                        <textarea
                          value={answers[q.field_name] ?? ''}
                          onChange={(e) => {
                            setAnswers({ [q.field_name]: e.target.value });
                            if (fieldErrors[q.field_name])
                              setFieldErrors((prev) => { const n = { ...prev }; delete n[q.field_name]; return n; });
                          }}
                          onBlur={(e) => {
                            const val = e.target.value.trim();
                            if (!val) return;
                            let err = '';
                            if (isEmailF && !EMAIL_RE.test(val))
                              err = 'Enter a valid email address (e.g. john@company.com)';
                            else if (isPhoneF && !PHONE_RE.test(val.replace(/\s/g, '')))
                              err = 'Enter a valid phone or fax number (e.g. (512) 555-1234)';
                            if (err) setFieldErrors(prev => ({ ...prev, [q.field_name]: err }));
                            else setFieldErrors(prev => { const n = { ...prev }; delete n[q.field_name]; return n; });
                          }}
                          placeholder={
                            isEmailF ? 'e.g. john@company.com' :
                            isPhoneF ? 'e.g. (512) 555-1234' :
                            'Your answer...'
                          }
                          rows={2}
                          inputMode={isEmailF ? 'email' : isPhoneF ? 'tel' : 'text'}
                          className="questionnaire-textarea"
                          style={{
                            width: '100%', padding: '9px 12px', fontSize: 13,
                            border: `1px solid ${hasError ? '#fca5a5' : '#e2e8f0'}`,
                            borderRadius: 7, fontFamily: 'inherit', resize: 'vertical',
                            boxSizing: 'border-box', outline: 'none', transition: 'border-color 0.2s',
                            display: 'block', background: '#fff', minHeight: 44,
                          }}
                          maxLength={500}
                        />
                      )}

                      {/*
                        "I do not know" behavior (client requirement, Figure 14).
                        Always available on every question type so a confusing
                        field - SIC / NAICS above all - can never dead-end the
                        client. Recorded explicitly, so the agent can tell
                        "didn't know" apart from "never got to it".
                      */}
                      {/* Not offered on a schedule: the table is already
                          all-optional (any number of rows, blanks allowed), so
                          "I'm not sure" would replace real rows with a sentinel
                          string and lose the client's work. */}
                      {!isSchedule && (
                        <button
                          type="button"
                          onClick={() => toggleNotSure(q.field_name)}
                          aria-pressed={notSure}
                          style={{
                            marginTop: 8, padding: '5px 12px', borderRadius: 20,
                            border: `1px solid ${notSure ? '#d97706' : '#e2e8f0'}`,
                            background: notSure ? '#fef3c7' : '#fff',
                            color: notSure ? '#92400e' : '#64748b',
                            fontSize: 12, fontWeight: 600, cursor: 'pointer',
                            fontFamily: 'inherit', minHeight: 32,
                          }}
                        >
                          {notSure ? "✕ I'd like to answer this" : "I'm not sure"}
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>

          <p style={{ fontSize: 11, color: '#94a3b8', textAlign: 'center', marginTop: 24, paddingTop: 16, borderTop: '1px solid #e2e8f0' }}>
            Your answers are auto-saved as you type. You can close and return later.
          </p>

          <footer style={{ marginTop: '16px', paddingTop: '12px', textAlign: 'center', borderTop: '1px solid #e2e8f0' }}>
            <p style={{ fontSize: '11px', color: '#94a3b8', margin: 0 }}>
              Powered by{' '}
              <a href="https://primble.vercel.app" target="_blank" rel="noopener noreferrer" style={{ color: '#E61B84', textDecoration: 'none', fontWeight: '600' }}>
                Primble
              </a>
            </p>
          </footer>
        </div>
      </div>

      {/* FLOATING BUTTONS CONTAINER */}
      <div style={{
        position: 'fixed',
        right: '24px',
        bottom: '24px',
        zIndex: 999,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'flex-end',
        gap: '12px',
      }}>

        {/* AGENT CONTACT CARD */}
        <AgentContactCard />

        {/* Submit feedback. The submit button floats at the bottom of the
            viewport, so a banner at the top of the page would be off-screen at
            the moment it matters. `error` had no renderer at all in this view
            before, which left the blocked-submit message (and the server's 422
            message) invisible - the client would tap Submit and see nothing
            happen. The page also scrolls to the first offending question, so
            this is the summary and the red text on the field is the detail. */}
        {error && questions.length > 0 && (
          <div
            role="alert"
            style={{
              maxWidth: 320, background: '#fef2f2', border: '1px solid #fecaca',
              color: '#991b1b', borderRadius: 10, padding: '10px 12px',
              fontSize: 12, lineHeight: 1.5,
              boxShadow: '0 4px 20px rgba(0,0,0,0.10)',
            }}
          >
            {error}
          </div>
        )}

        {/* SUBMIT BUTTON + its count badge.
            BUG-02: the badge is absolutely positioned, but it used to be a
            SIBLING of the button inside the fixed floating stack - so it
            anchored to the stack's top-right corner and rendered on the "Contact
            Your Broker" card, where it read as an unread-message dot. This
            wrapper is the positioning context it always assumed it had. */}
        <div style={{ position: 'relative', display: 'flex' }}>
        <button
          onClick={handleSubmit}
          disabled={submitting}
          className="floating-save-btn"
          title={`Submit answers (${respondedCount} of ${questions.length} responded)`}
          style={{
            width: 'auto',
            minWidth: '100px',
            padding: '12px 24px',
            borderRadius: '40px',
            background: submitting ? '#cbd5e1' : '#E61B84',
            border: 'none',
            cursor: submitting ? 'not-allowed' : 'pointer',
            color: '#fff',
            fontSize: '14px',
            fontWeight: 600,
            boxShadow: '0 4px 20px rgba(230,0,122,0.4)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '8px',
            transition: 'all 0.2s ease',
            position: 'relative',
            letterSpacing: '0.5px',
          }}
          onMouseEnter={(e) => {
            if (!submitting) {
              e.currentTarget.style.background = '#C0157A';
              e.currentTarget.style.transform = 'translateY(-2px)';
              e.currentTarget.style.boxShadow = '0 6px 24px rgba(230,0,122,0.5)';
            }
          }}
          onMouseLeave={(e) => {
            if (!submitting) {
              e.currentTarget.style.background = '#E61B84';
              e.currentTarget.style.transform = 'translateY(0)';
              e.currentTarget.style.boxShadow = '0 4px 20px rgba(230,0,122,0.4)';
            }
          }}
        >
          {submitting ? (
            <>
              <span style={{
                width: '16px',
                height: '16px',
                border: '2px solid white',
                borderTopColor: 'transparent',
                borderRadius: '50%',
                display: 'inline-block',
                animation: 'spin 0.7s linear infinite'
              }} />
              Submitting...
            </>
          ) : (
            <>
              Submit
            </>
          )}
        </button>

        {/* Progress badge. It counts the questions the client has responded to -
            it is not a notification. The tester could not tell, so it now says
            so on hover and to a screen reader. `pointerEvents` has to be enabled
            for the tooltip to fire; the badge overhangs the pill's rounded
            corner, which is transparent, so no clickable area is lost. */}
        {!submitting && respondedCount > 0 && (
          <div
            title={`${respondedCount} of ${questions.length} questions responded`}
            role="status"
            aria-label={`${respondedCount} of ${questions.length} questions responded`}
            style={{
              position: 'absolute',
              top: '-8px',
              right: '-8px',
              background: '#10b981',
              color: 'white',
              borderRadius: '50%',
              width: '24px',
              height: '24px',
              fontSize: '12px',
              fontWeight: 'bold',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              border: '2px solid white',
              cursor: 'default',
            }}>
            {respondedCount}
          </div>
        )}
        </div>

        {/* CHAT BUTTON */}
        <button
          onClick={() => setChatOpen(o => !o)}
          title="Ask Form Assistant"
          style={{
            width: 'auto',
            minWidth: '100px',
            padding: '12px 24px',
            borderRadius: '40px',
            background: chatOpen ? '#0f172a' : 'linear-gradient(135deg, #E61B84, #c0005f)',
            border: chatOpen ? '2px solid #E61B84' : 'none',
            cursor: 'pointer',
            color: '#fff',
            fontSize: '14px',
            fontWeight: 600,
            boxShadow: '0 4px 20px rgba(230,0,122,0.45)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '8px',
            transition: 'all 0.2s ease',
            letterSpacing: '0.5px',
          }}
          onMouseEnter={e => {
            if (!chatOpen) {
              e.currentTarget.style.transform = 'translateY(-2px)';
              e.currentTarget.style.background = '#C0157A';
            }
          }}
          onMouseLeave={e => {
            if (!chatOpen) {
              e.currentTarget.style.transform = 'translateY(0)';
              e.currentTarget.style.background = 'linear-gradient(135deg, #E61B84, #c0005f)';
            }
          }}
        >
          {chatOpen ? '✕ Close' : 'Help'}
        </button>
      </div>

      {/* CHAT WINDOW */}
      {chatOpen && (
        <div style={{
          position: 'fixed',
          bottom: '130px',
          right: '24px',
          zIndex: 1000,
          width: 'min(360px, calc(100vw - 32px))',
          background: '#fff',
          borderRadius: 16,
          boxShadow: '0 8px 40px rgba(0,0,0,0.18)',
          border: '1px solid #e2e8f0',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          maxHeight: 'min(460px, calc(100vh - 180px))',
        }}>
          {/* Chat header */}
          <div style={{ padding: '12px 16px', background: 'linear-gradient(135deg, #0f172a, #1e293b)', color: '#fff', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexShrink: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 18 }}></span>
              <div>
                <div style={{ fontSize: 13, fontWeight: 600 }}>Form Assistant</div>
                <div style={{ fontSize: 10, opacity: 0.7 }}>Ask me anything about this questionnaire</div>
              </div>
            </div>
            <button onClick={() => setChatOpen(false)} style={{ background: 'none', border: 'none', color: '#fff', cursor: 'pointer', fontSize: 18, lineHeight: 1, opacity: 0.7, padding: '4px 8px' }}>✕</button>
          </div>

          {/* Messages */}
          <div style={{ flex: 1, overflowY: 'auto', padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 10 }}>
            {[{ role: 'assistant', content: chatGreeting }, ...chatHistory].map((msg, i) => (
              <div key={i} style={{ display: 'flex', justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start' }}>
                <div style={{
                  maxWidth: '82%', padding: '8px 12px', borderRadius: msg.role === 'user' ? '12px 12px 2px 12px' : '12px 12px 12px 2px',
                  background: msg.role === 'user' ? '#E61B84' : '#f1f5f9',
                  color: msg.role === 'user' ? '#fff' : '#0f172a',
                  fontSize: 12, lineHeight: 1.5,
                  wordBreak: 'break-word',
                }}>
                  {stripMarkdown(msg.content)}
                </div>
              </div>
            ))}
            {chatLoading && (
              <div style={{ display: 'flex', justifyContent: 'flex-start' }}>
                <div style={{ background: '#f1f5f9', borderRadius: '12px 12px 12px 2px', padding: '8px 14px', display: 'flex', gap: 4, alignItems: 'center' }}>
                  {[0, 1, 2].map(i => (
                    <span key={i} style={{ width: 6, height: 6, borderRadius: '50%', background: '#94a3b8', display: 'inline-block', animation: `bounce 1s ease-in-out ${i * 0.2}s infinite` }} />
                  ))}
                </div>
              </div>
            )}
            <div ref={chatBottomRef} />
          </div>

          {/* Input */}
          <div style={{ padding: '10px 12px', borderTop: '1px solid #e2e8f0', display: 'flex', gap: 8, flexShrink: 0 }}>
            <input
              ref={chatInputRef}
              type="text"
              value={chatInput}
              onChange={(e) => setChatInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChatMessage(); } }}
              placeholder="Ask a question..."
              maxLength={500}
              style={{
                flex: 1, padding: '10px 12px', fontSize: 13, border: '1px solid #e2e8f0',
                borderRadius: 8, outline: 'none', fontFamily: 'inherit', minHeight: 40,
              }}
            />
            <button
              onClick={sendChatMessage}
              disabled={chatLoading || !chatInput.trim()}
              style={{
                padding: '10px 14px', background: '#E61B84', color: '#fff', border: 'none',
                borderRadius: 8, fontSize: 13, cursor: chatLoading || !chatInput.trim() ? 'not-allowed' : 'pointer',
                opacity: chatLoading || !chatInput.trim() ? 0.5 : 1, fontWeight: 600, minHeight: 40, minWidth: 40,
              }}
            >
              ↑
            </button>
          </div>
        </div>
      )}

      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
        @keyframes bounce { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-4px); } }
        .questionnaire-textarea:focus { border-color: #E61B84 !important; }

        /* Tooltip on hover for floating save button */
        .floating-save-btn:hover::after {
          content: "Submit your answers (${respondedCount}/${questions.length})";
          position: absolute;
          right: 100%;
          margin-right: 12px;
          white-space: nowrap;
          background: #1e293b;
          color: white;
          padding: 6px 12px;
          border-radius: 8px;
          font-size: 12px;
          font-weight: 500;
          pointer-events: none;
          z-index: 1000;
        }

        @media (max-width: 768px) {
          .floating-save-btn {
            min-width: 80px !important;
            padding: 10px 18px !important;
            font-size: 13px !important;
          }
          .floating-save-btn:hover::after {
            font-size: 10px !important;
            padding: 4px 8px !important;
          }
          div[style*="position: fixed"][style*="right: 24px"] {
            right: 16px !important;
            bottom: 16px !important;
          }
        }
      `}</style>
    </div>
  );
}
