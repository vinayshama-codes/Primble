// ClientQuestionnaire.jsx - Final version without restore prompt and error message
import { useState, useEffect, useRef, useCallback } from 'react';
import { API_BASE } from '../../config/constants';

// Validation helpers
const EMAIL_RE   = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const PHONE_RE   = /^[\+]?[(]?[0-9]{3}[)]?[-\s\.]?[0-9]{3}[-\s\.]?[0-9]{4,6}$/;
const DATE_RE    = /^\d{1,2}\/\d{1,2}\/\d{4}$|^\d{4}-\d{2}-\d{2}$/;
const NUMBER_RE  = /^\$?[\d,]+(\.\d+)?$/;

const FALLBACK_REPLY = "I'm not sure about that. Please contact your agent or broker for assistance.";

function isEmailField(fieldName) {
  return /email/i.test(fieldName);
}
function isPhoneField(fieldName) {
  return /phone|fax|tel/i.test(fieldName);
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

  // Producer contact info
  const [producerEmail, setProducerEmail] = useState('');
  const [producerPhone, setProducerPhone] = useState('');
  const [producerName, setProducerName]   = useState('');

  // Draft save state
  const draftTimerRef    = useRef(null);
  const pendingAnswersRef = useRef({});

  // Chat state
  const [chatOpen, setChatOpen]       = useState(false);
  const [chatHistory, setChatHistory] = useState([
    { role: 'assistant', content: "Hi! I'm your automated form assistant. What questions do you have about this document?" }
  ]);
  const [chatInput, setChatInput]     = useState('');
  const [chatLoading, setChatLoading] = useState(false);
  const chatBottomRef                 = useRef(null);
  const chatInputRef                  = useRef(null);

  // Server-side draft save (debounced 1s) — works across browsers, incognito, devices
  const saveDraftToServer = useCallback((currentAnswers) => {
    if (!token) return;
    if (draftTimerRef.current) clearTimeout(draftTimerRef.current);
    pendingAnswersRef.current = currentAnswers;
    draftTimerRef.current = setTimeout(() => {
      fetch(`${API_BASE}/api/arq/draft/${token}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ answers: pendingAnswersRef.current }),
      }).catch(() => {}); // silent — draft save failures are non-critical
    }, 1000);
  }, [token]);

  // Wrapper so the rest of the component calls setAnswers (same as before)
  const setAnswers = useCallback((updates) => {
    setAnswersState(prev => {
      const next = typeof updates === 'function' ? updates(prev) : { ...prev, ...updates };
      saveDraftToServer(next);
      return next;
    });
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
      if (!val || q.field_type === 'checkbox') return;
      const ft = q.field_type || 'text';
      const fn = q.field_name;

      if (isEmailField(fn) && !EMAIL_RE.test(val)) {
        errors[fn] = 'Enter a valid email address (e.g. john@company.com)';
      } else if (isPhoneField(fn) && !PHONE_RE.test(val.replace(/\s/g, ''))) {
        errors[fn] = 'Enter a valid phone number (e.g. (512) 555-1234)';
      } else if (ft === 'date' && !DATE_RE.test(val)) {
        errors[fn] = 'Use MM/DD/YYYY format (e.g. 01/15/2025)';
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

    // Basic sanitization — strip script tags
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

  // Auto-scroll chat
  useEffect(() => {
    if (chatOpen) chatBottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatHistory, chatOpen]);

  // Focus input when chat opens
  useEffect(() => {
    if (chatOpen) setTimeout(() => chatInputRef.current?.focus(), 150);
  }, [chatOpen]);

  // Load questionnaire data — runs once per token
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
          qs.forEach((q) => { init[q.field_name] = q.current_value || ''; });
          const serverDraft = data.draft_answers || {};
          setAnswersState({ ...init, ...serverDraft });
        } else if (data.error === 'expired') {
          setError('This questionnaire link has expired. Please contact your insurance agent for a new link.');
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

  const answeredCount = questions.filter(
    (q) => (answers[q.field_name] || '').trim() !== ''
  ).length;

  const handleSubmit = async () => {
    // Validate but don't block submission - just show warnings
    const errors = validateAnswers();
    if (Object.keys(errors).length) {
      // Show warning but allow user to choose
      const userConfirmed = window.confirm(
        `You have ${Object.keys(errors).length} question(s) with invalid or incomplete answers.\n\n` +
        `Do you want to submit anyway? Your agent will review the answers.\n\n` +
        `Click OK to submit, Cancel to go back and fix.`
      );

      if (!userConfirmed) {
        setFieldErrors(errors);
        const first = Object.keys(errors)[0];
        document.getElementById(`q-${first}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
        return;
      }
    }

    flushDraft();
    setFieldErrors({});
    setSubmitting(true);
    setError(null);
    try {
      const res  = await fetch(`${API_BASE}/api/arq/submit/${token}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ answers }),
      });
      const data = await res.json();
      if (res.ok && data.success) {
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
        <div style={{ fontWeight: 700, color: '#0369a1', marginBottom: 6 }}>📞 Contact Your Agent</div>
        {producerName && <div style={{ color: '#0f172a', marginBottom: 4 }}>{producerName}</div>}
        {producerEmail && (
          <div style={{ color: '#475569', marginBottom: 2 }}>
            ✉ <a href={`mailto:${producerEmail}`} style={{ color: '#0369a1', textDecoration: 'none' }}>{producerEmail}</a>
          </div>
        )}
        {producerPhone && (
          <div style={{ color: '#475569' }}>
            📱 <a href={`tel:${producerPhone}`} style={{ color: '#0369a1', textDecoration: 'none' }}>{producerPhone}</a>
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
        <div style={{ fontSize: 64, marginBottom: 16 }}>✅</div>
        <h2 style={{ fontSize: 24, fontWeight: 700, marginBottom: 12, color: '#1e293b' }}>Thank You!</h2>
        <p style={{ fontSize: 16, color: '#475569', marginBottom: 24 }}>
          Your answers have been submitted successfully. Your insurance agent has been notified and the forms will be updated automatically.
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
        <div style={{ fontSize: 48, marginBottom: 16 }}>⚠️</div>
        <h2 style={{ fontSize: 20, fontWeight: 600, marginBottom: 12, color: '#dc2626' }}>Questionnaire Unavailable</h2>
        <p style={{ fontSize: 14, color: '#475569', marginBottom: 24 }}>{error}</p>
        <p style={{ fontSize: 13, color: '#64748b', marginBottom: 20 }}>Please contact your agent or broker for further assistance.</p>
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
            <div style={{ fontSize: 32, marginBottom: 8 }}>📋</div>
            <h1 style={{ fontSize: 20, fontWeight: 700, marginBottom: 6 }}>Insurance Information Needed</h1>
            <p style={{ fontSize: 13, opacity: 0.9 }}>
              {clientName ? `Hi ${clientName},` : 'Hello,'} your insurance agent needs a few details to complete your application.
            </p>
            {expiresAt && (
              <p style={{ fontSize: 11, opacity: 0.7, marginTop: 8 }}>Expires: {formatDate(expiresAt)}</p>
            )}
          </div>

          {questions.length > 0 && (() => {
            const pct  = Math.round((answeredCount / questions.length) * 100);
            const r    = 20;
            const circ = 2 * Math.PI * r;
            return (
              <div style={{ flexShrink: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
                <svg width="56" height="56" viewBox="0 0 52 52">
                  <circle cx="26" cy="26" r={r} fill="none" stroke="rgba(255,255,255,0.15)" strokeWidth="5" />
                  <circle cx="26" cy="26" r={r} fill="none" stroke="#E61B84" strokeWidth="5"
                    strokeDasharray={circ} strokeDashoffset={circ - (pct / 100) * circ}
                    strokeLinecap="round" transform="rotate(-90 26 26)"
                    style={{ transition: 'stroke-dashoffset 0.4s ease' }} />
                  <text x="26" y="31" textAnchor="middle" fill="#fff" fontSize="11" fontWeight="700" fontFamily="Arial,sans-serif">{pct}%</text>
                </svg>
                <span style={{ fontSize: 10, color: 'rgba(255,255,255,0.6)' }}>{answeredCount}/{questions.length}</span>
              </div>
            );
          })()}
        </div>

        {/* Auto-save indicator - Shows when draft is being saved */}
        {answeredCount > 0 && (
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
            <span>💾 Auto-saving in progress...</span>
          </div>
        )}

        {/* Body */}
        <div style={{ padding: '20px 20px' }}>

          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, marginBottom: 20, flexWrap: 'wrap' }}>
            <div>
              <h2 style={{ fontSize: 16, fontWeight: 600, color: '#1e293b', marginBottom: 2 }}>Questions ({questions.length})</h2>
              <p style={{ fontSize: 12, color: '#64748b' }}>Answers are auto-saved as you type. You can close and return later.</p>
            </div>
          </div>

          {/* Questions */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {questions.map((q) => {
              const fieldType  = q.field_type || 'text';
              const isCheckbox = fieldType === 'checkbox';
              const isAnswered = (answers[q.field_name] || '').trim() !== '';
              const hasError   = !!fieldErrors[q.field_name];
              const hint       = q.hint || '';
              const isEmailF   = isEmailField(q.field_name);
              const isPhoneF   = isPhoneField(q.field_name);

              return (
                <div
                  id={`q-${q.field_name}`}
                  key={q.field_name}
                  style={{
                    border: `1px solid ${hasError ? '#fca5a5' : isAnswered ? '#bbf7d0' : '#e2e8f0'}`,
                    borderRadius: 10,
                    padding: '12px 14px',
                    background: hasError ? '#fff5f5' : isAnswered ? '#f0fdf4' : '#fff',
                    transition: 'border-color 0.2s, background 0.2s',
                  }}
                >
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                    <div>
                      <label style={{ fontWeight: 500, fontSize: 13, color: '#0f172a', lineHeight: 1.45, display: 'block' }}>
                        {q.question}
                      </label>
                      {hint && (
                        <div style={{ marginTop: 5, fontSize: 11, color: '#64748b', lineHeight: 1.5, display: 'flex', alignItems: 'flex-start', gap: 4 }}>
                          <span style={{ flexShrink: 0 }}>💡</span>
                          <span>{hint}</span>
                        </div>
                      )}
                      {hasError && (
                        <p style={{ margin: '4px 0 0', fontSize: 11, color: '#dc2626' }}>⚠️ {fieldErrors[q.field_name]}</p>
                      )}
                    </div>

                    <div>
                      {isCheckbox ? (
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
              <a href="https://acordly.ai" target="_blank" rel="noopener noreferrer" style={{ color: '#E61B84', textDecoration: 'none', fontWeight: '600' }}>
                acordly.ai
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

        {/* SUBMIT BUTTON */}
        <button
          onClick={handleSubmit}
          disabled={submitting}
          className="floating-save-btn"
          title={`Submit Answers (${answeredCount}/${questions.length})`}
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
              <span>✓</span>
              Submit
            </>
          )}
        </button>

        {/* Progress badge */}
        {!submitting && answeredCount > 0 && (
          <div style={{
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
            pointerEvents: 'none'
          }}>
            {answeredCount}
          </div>
        )}

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
          {chatOpen ? '✕ Close' : '💬 Chat'}
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
              <span style={{ fontSize: 18 }}>🤖</span>
              <div>
                <div style={{ fontSize: 13, fontWeight: 600 }}>Form Assistant</div>
                <div style={{ fontSize: 10, opacity: 0.7 }}>Ask me anything about this form</div>
              </div>
            </div>
            <button onClick={() => setChatOpen(false)} style={{ background: 'none', border: 'none', color: '#fff', cursor: 'pointer', fontSize: 18, lineHeight: 1, opacity: 0.7, padding: '4px 8px' }}>✕</button>
          </div>

          {/* Messages */}
          <div style={{ flex: 1, overflowY: 'auto', padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 10 }}>
            {chatHistory.map((msg, i) => (
              <div key={i} style={{ display: 'flex', justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start' }}>
                <div style={{
                  maxWidth: '82%', padding: '8px 12px', borderRadius: msg.role === 'user' ? '12px 12px 2px 12px' : '12px 12px 12px 2px',
                  background: msg.role === 'user' ? '#E61B84' : '#f1f5f9',
                  color: msg.role === 'user' ? '#fff' : '#0f172a',
                  fontSize: 12, lineHeight: 1.5,
                  wordBreak: 'break-word',
                }}>
                  {msg.content}
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
          content: "Submit your answers (${answeredCount}/${questions.length})";
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
