import { useState, useEffect } from 'react';
import { API_BASE } from '../../config/constants';

export default function ClientQuestionnaire({ token }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [questions, setQuestions] = useState([]);
  const [answers, setAnswers] = useState(() => ({}));
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [expiresAt, setExpiresAt] = useState(null);
  const [clientName, setClientName] = useState('');

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
          setQuestions(data.questions || []);
          setExpiresAt(data.expires_at);
          setClientName(data.client_name || '');

          const init = {};
          (data.questions || []).forEach((q) => {
            init[q.field_name] = q.current_value || '';
          });
          setAnswers(init);
        } else if (data.error === 'expired') {
          setError(
            'This questionnaire link has expired. Please contact your insurance agent for a new link.'
          );
        } else if (data.error === 'already_submitted') {
          setError('You have already submitted answers for this questionnaire.');
        } else {
          setError(data.message || 'Failed to load questionnaire');
        }
      })
      .catch((err) => {
        if (err.name !== 'AbortError') {
          setError('Network error. Please try again.');
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      });

    return () => controller.abort();
  }, [token]);

  const answeredCount = questions.filter(
    (q) => (answers[q.field_name] || '').trim() !== ''
  ).length;

  const handleSubmit = async () => {
    setSubmitting(true);
    setError(null);

    try {
      const res = await fetch(`${API_BASE}/api/arq/submit/${token}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ answers }),
      });

      const data = await res.json();

      if (res.ok && data.success) {
        setSubmitted(true);
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
      year: 'numeric',
      month: 'long',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh', flexDirection: 'column', gap: 16 }}>
        <div style={{ width: 40, height: 40, border: '3px solid #e2e8f0', borderTopColor: '#e6007a', borderRadius: '50%', animation: 'spin 0.7s linear infinite' }} />
        <p style={{ color: '#64748b' }}>Loading your questionnaire...</p>
        <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      </div>
    );
  }

  if (submitted) {
    return (
      <div style={{ maxWidth: 600, margin: '60px auto', padding: '40px 32px', textAlign: 'center', background: '#fff', borderRadius: 16, boxShadow: '0 4px 20px rgba(0,0,0,0.08)', border: '1px solid #e2e8f0' }}>
        <div style={{ fontSize: 64, marginBottom: 16 }}>✅</div>
        <h2 style={{ fontSize: 24, fontWeight: 700, marginBottom: 12, color: '#1e293b' }}>Thank You!</h2>
        <p style={{ fontSize: 16, color: '#475569', marginBottom: 24 }}>
          Your answers have been submitted successfully. Your insurance agent has been notified and the forms will be updated automatically.
        </p>
        <button
          onClick={() => window.close()}
          style={{ padding: '10px 24px', background: '#e6007a', color: '#fff', border: 'none', borderRadius: 8, fontSize: 14, fontWeight: 600, cursor: 'pointer' }}
        >
          Close Window
        </button>
      </div>
    );
  }

  if (error && !questions.length) {
    return (
      <div style={{ maxWidth: 500, margin: '60px auto', padding: '40px 32px', textAlign: 'center', background: '#fff', borderRadius: 16, boxShadow: '0 4px 20px rgba(0,0,0,0.08)', border: '1px solid #fee2e2' }}>
        <div style={{ fontSize: 48, marginBottom: 16 }}>⚠️</div>
        <h2 style={{ fontSize: 20, fontWeight: 600, marginBottom: 12, color: '#dc2626' }}>Questionnaire Unavailable</h2>
        <p style={{ fontSize: 14, color: '#475569', marginBottom: 24 }}>{error}</p>
        <button onClick={() => window.close()} style={{ padding: '8px 20px', background: '#64748b', color: '#fff', border: 'none', borderRadius: 6, fontSize: 13, cursor: 'pointer' }}>
          Close
        </button>
      </div>
    );
  }

  return (
    <div style={{ minHeight: '100vh', background: '#f8fafc', padding: '32px 20px' }}>
      <div style={{ maxWidth: 720, margin: '0 auto', background: '#fff', borderRadius: 20, boxShadow: '0 8px 30px rgba(0,0,0,0.08)', overflow: 'hidden' }}>

        {/* Header */}
        <div style={{ padding: '28px 32px 22px', background: 'linear-gradient(135deg, #0f172a 0%, #1e293b 100%)', color: '#fff', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 36, marginBottom: 10 }}>📋</div>
            <h1 style={{ fontSize: 22, fontWeight: 700, marginBottom: 6 }}>Insurance Information Needed</h1>
            <p style={{ fontSize: 14, opacity: 0.9 }}>
              {clientName ? `Hi ${clientName},` : 'Hello,'} your insurance agent needs a few details to complete your application.
            </p>
            {expiresAt && (
              <p style={{ fontSize: 12, opacity: 0.7, marginTop: 10 }}>Expires: {formatDate(expiresAt)}</p>
            )}
          </div>

          {questions.length > 0 && (() => {
            const pct = Math.round((answeredCount / questions.length) * 100);
            const r = 20;
            const circ = 2 * Math.PI * r;
            return (
              <div style={{ flexShrink: 0, marginLeft: 20, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
                <svg width="56" height="56" viewBox="0 0 52 52">
                  <circle cx="26" cy="26" r={r} fill="none" stroke="rgba(255,255,255,0.15)" strokeWidth="5" />
                  <circle cx="26" cy="26" r={r} fill="none" stroke="#e6007a" strokeWidth="5"
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

        {/* Body */}
        <div style={{ padding: '24px 32px' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, marginBottom: 20 }}>
            <div>
              <h2 style={{ fontSize: 16, fontWeight: 600, color: '#1e293b', marginBottom: 2 }}>
                Questions ({questions.length})
              </h2>
              <p style={{ fontSize: 12, color: '#64748b' }}>Please answer as accurately as possible.</p>
            </div>
            <button
              onClick={handleSubmit}
              disabled={submitting || answeredCount === 0}
              style={{ flexShrink: 0, padding: '7px 14px', background: '#e6007a', color: '#fff', border: 'none', borderRadius: 8, fontSize: 12, fontWeight: 600, cursor: submitting || answeredCount === 0 ? 'not-allowed' : 'pointer', opacity: submitting || answeredCount === 0 ? 0.5 : 1, whiteSpace: 'nowrap', transition: 'opacity 0.2s' }}
            >
              {submitting ? 'Submitting...' : `✓ Submit (${answeredCount}/${questions.length})`}
            </button>
          </div>

          {error && (
            <div style={{ background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 8, padding: '12px 16px', marginBottom: 20, color: '#dc2626', fontSize: 13 }}>
              ⚠️ {error}
            </div>
          )}

          {/* Questions — compact inline layout */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {questions.map((q) => {
              const fieldType = q.field_type || 'text';
              const isCheckbox = fieldType === 'checkbox';
              const isAnswered = (answers[q.field_name] || '').trim() !== '';

              return (
                <div
                  key={q.field_name}
                  style={{
                    border: `1px solid ${isAnswered ? '#bbf7d0' : '#e2e8f0'}`,
                    borderRadius: 10,
                    padding: isCheckbox ? '12px 16px' : '12px 16px',
                    background: isAnswered ? '#f0fdf4' : '#fff',
                    transition: 'border-color 0.2s, background 0.2s',
                    display: 'flex',
                    alignItems: isCheckbox ? 'center' : 'flex-start',
                    gap: 16,
                  }}
                >
                  {/* Question label */}
                  <label
                    style={{
                      flex: '0 0 auto',
                      width: '45%',
                      fontWeight: 500,
                      fontSize: 13,
                      color: '#0f172a',
                      lineHeight: 1.45,
                      paddingTop: isCheckbox ? 0 : 2,
                    }}
                  >
                    {q.question}
                  </label>

                  {/* Answer input */}
                  <div style={{ flex: 1, minWidth: 0 }}>
                    {isCheckbox ? (
                      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                        <button
                          onClick={() =>
                            setAnswers((prev) => ({
                              ...prev,
                              [q.field_name]: prev[q.field_name] === 'Yes' ? 'No' : 'Yes',
                            }))
                          }
                          style={{
                            padding: '5px 16px',
                            borderRadius: 20,
                            border: '1px solid',
                            borderColor: answers[q.field_name] === 'Yes' ? '#e6007a' : '#cbd5e1',
                            background: answers[q.field_name] === 'Yes' ? '#fdf2f8' : '#f8fafc',
                            color: answers[q.field_name] === 'Yes' ? '#e6007a' : '#64748b',
                            fontWeight: 600,
                            fontSize: 13,
                            cursor: 'pointer',
                            transition: 'all 0.15s',
                          }}
                        >
                          {answers[q.field_name] === 'Yes' ? '✓ Yes' : 'No'}
                        </button>
                        {!answers[q.field_name] && (
                          <span style={{ fontSize: 11, color: '#94a3b8' }}>Tap to answer</span>
                        )}
                      </div>
                    ) : (
                      <textarea
                        value={answers[q.field_name] ?? ''}
                        onChange={(e) =>
                          setAnswers((prev) => ({ ...prev, [q.field_name]: e.target.value }))
                        }
                        placeholder="Your answer..."
                        rows={2}
                        className="questionnaire-textarea"
                        style={{
                          width: '100%',
                          padding: '8px 12px',
                          fontSize: 13,
                          border: '1px solid #e2e8f0',
                          borderRadius: 7,
                          fontFamily: 'inherit',
                          resize: 'vertical',
                          boxSizing: 'border-box',
                          outline: 'none',
                          transition: 'border-color 0.2s',
                          display: 'block',
                          background: '#fff',
                        }}
                      />
                    )}
                  </div>
                </div>
              );
            })}
          </div>

          {/* Submit button */}
          <button
            onClick={handleSubmit}
            disabled={submitting}
            style={{ width: '100%', marginTop: 24, padding: '13px', background: '#e6007a', color: '#fff', border: 'none', borderRadius: 12, fontSize: 15, fontWeight: 600, cursor: submitting ? 'not-allowed' : 'pointer', opacity: submitting ? 0.6 : 1, transition: 'all 0.2s' }}
          >
            {submitting ? (
              <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8 }}>
                <span style={{ width: 16, height: 16, border: '2px solid white', borderTopColor: 'transparent', borderRadius: '50%', display: 'inline-block', animation: 'spin 0.7s linear infinite' }} />
                Submitting...
              </span>
            ) : '✓ Submit Answers'}
          </button>

          <p style={{ fontSize: 11, color: '#94a3b8', textAlign: 'center', marginTop: 16, paddingTop: 16, borderTop: '1px solid #e2e8f0' }}>
            Your answers will be sent directly to your insurance agent.
          </p>

          <footer style={{ marginTop: '16px', paddingTop: '12px', textAlign: 'center', borderTop: '1px solid #e2e8f0' }}>
            <p style={{ fontSize: '11px', color: '#94a3b8', margin: 0 }}>
              Powered by{' '}
              <a href="https://acordly.ai" target="_blank" rel="noopener noreferrer" style={{ color: '#e6007a', textDecoration: 'none', fontWeight: '600' }}>
                acordly.ai
              </a>
            </p>
          </footer>
        </div>
      </div>

      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
        .questionnaire-textarea:focus { border-color: #e6007a !important; }
      `}</style>
    </div>
  );
}