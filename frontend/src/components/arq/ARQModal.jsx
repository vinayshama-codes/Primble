//ARQModal.jsx
import { useState, useEffect } from "react";
import { sendArq } from "../../api/arqApi";

export default function ARQModal({ sessionId, token, questions, producerFullName, producerFirstName, onClose, onSuccess }) {
  const [clientEmail,        setClientEmail]        = useState("");
  const [clientName,         setClientName]          = useState("");
  const [selectedQuestions,  setSelectedQuestions]   = useState({});
  const [selectAll,          setSelectAll]            = useState(true);
  const [sending,            setSending]              = useState(false);
  const [error,              setError]                = useState("");
  const [emailTouched,       setEmailTouched]         = useState(false);

  useEffect(() => {
    const initial = {};
    questions.forEach((q) => { initial[q.field_name] = true; });
    setSelectedQuestions(initial);
  }, [questions]);

  const handleToggle = (fieldName) => {
    setSelectedQuestions((prev) => ({ ...prev, [fieldName]: !prev[fieldName] }));
  };

  const handleSelectAll = () => {
    const next = !selectAll;
    setSelectAll(next);
    const updated = {};
    questions.forEach((q) => { updated[q.field_name] = next; });
    setSelectedQuestions(updated);
  };

  // Sanitize email input
  const sanitizeEmail = (val) => val.trim().toLowerCase().slice(0, 254);

  const selectedCount = Object.values(selectedQuestions).filter(Boolean).length;
  const isEmailValid  = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(clientEmail);
  const canSend       = isEmailValid && selectedCount > 0;

  const handleSend = async () => {
    if (!canSend) return;
    setEmailTouched(true);
    setSending(true);
    setError("");

    const selectedList = questions.filter((q) => selectedQuestions[q.field_name]);
    const { ok, data } = await sendArq(token, {
      session_id:   sessionId,
      client_email: sanitizeEmail(clientEmail),
      client_name:  clientName.trim().slice(0, 100),
      questions:    selectedList,
    });

    setSending(false);
    if (ok && data.success) {
      onSuccess({ arq_id: data.arq_id, client_email: clientEmail, client_name: clientName });
    } else {
      setError(data.detail || data.message || "Failed to send questionnaire.");
    }
  };

  return (
    <div className="modal-overlay" style={{ padding: "12px" }}>
      <div
        className="modal-content"
        style={{ maxWidth: 700, width: "100%", maxHeight: "95vh", display: "flex", flexDirection: "column", overflow: "hidden" }}
        onClick={(e) => e.stopPropagation()}
      >
        <button className="modal-close" onClick={onClose}>✕</button>
        <div className="modal-inner" style={{ display: "flex", flexDirection: "column", flex: 1, overflow: "hidden", padding: "24px 28px" }}>
          <div style={{ fontSize: 32, marginBottom: 6, textAlign: "center" }}>📧</div>
          <h2 className="step-title" style={{ textAlign: "center", marginBottom: 4 }}>Send to Client</h2>
          <p className="step-subtitle" style={{ textAlign: "center", marginBottom: 16 }}>
            Select questions to send. The client receives a secure link to answer them.
          </p>

          {error && (
            <div className="alert alert-error" style={{ marginBottom: 14 }}>
              ⚠️ {error}
              <button className="alert-close" onClick={() => setError("")}>✕</button>
            </div>
          )}

          {/* Email + Name */}
          <div style={{ display: "flex", gap: 12, marginBottom: 16, flexWrap: "wrap" }}>
            <div className="form-group" style={{ flex: "2 1 200px", marginBottom: 0 }}>
              <label>Client Email <span className="field-required">*</span></label>
              <input
                type="email"
                value={clientEmail}
                onChange={(e) => { setClientEmail(e.target.value); setEmailTouched(true); }}
                onBlur={() => setEmailTouched(true)}
                placeholder="client@theircompany.com"
                className="form-input"
                maxLength={254}
                autoComplete="off"
              />
              {emailTouched && clientEmail && !isEmailValid && (
                <p style={{ fontSize: 11, color: "#ef4444", marginTop: 4 }}>Please enter a valid email address.</p>
              )}
            </div>
            <div className="form-group" style={{ flex: "1 1 140px", marginBottom: 0 }}>
              <label style={{ display: "flex", gap: 4, alignItems: "center" }}>
                First Name <span style={{ color: "#94a3b8", fontWeight: 400, fontSize: 11 }}>(optional)</span>
              </label>
              <input
                type="text"
                value={clientName}
                onChange={(e) => setClientName(e.target.value)}
                placeholder="e.g. John"
                className="form-input"
                maxLength={100}
              />
            </div>
          </div>

          {/* Questions list */}
          <div style={{ borderTop: "1px solid #e2e8f0", paddingTop: 14, flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
              <span style={{ fontWeight: 600, fontSize: 13, color: "#1e293b" }}>
                Questions ({selectedCount}/{questions.length} selected)
              </span>
              <button
                onClick={handleSelectAll}
                style={{ background: "none", border: "1px solid #e2e8f0", borderRadius: 6, padding: "3px 10px", fontSize: 11, cursor: "pointer", color: "#4f7cff", fontWeight: 500 }}
              >
                {selectAll ? "Deselect All" : "Select All"}
              </button>
            </div>

            <div style={{ flex: 1, overflowY: "auto", display: "flex", flexDirection: "column", gap: 6, minHeight: 0 }}>
              {questions.map((q, idx) => (
                <div
                  key={idx}
                  onClick={() => handleToggle(q.field_name)}
                  style={{
                    border: "1px solid",
                    borderColor: selectedQuestions[q.field_name] ? "#e6007a" : "#e2e8f0",
                    borderRadius: 8,
                    padding: "9px 12px",
                    cursor: "pointer",
                    background: selectedQuestions[q.field_name] ? "rgba(230,0,122,0.04)" : "#fff",
                    display: "flex",
                    alignItems: "center",
                    gap: 10,
                    transition: "all 0.15s",
                    opacity: selectedQuestions[q.field_name] ? 1 : 0.5,
                  }}
                >
                  <input
                    type="checkbox"
                    checked={!!selectedQuestions[q.field_name]}
                    onChange={() => handleToggle(q.field_name)}
                    onClick={(e) => e.stopPropagation()}
                    style={{ width: 15, height: 15, cursor: "pointer", accentColor: "#e6007a", flexShrink: 0 }}
                  />
                  <div style={{ flex: 1, minWidth: 0, display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
                    {q.forms && (
                      <span style={{ fontSize: 10, fontWeight: 700, color: "#e6007a", background: "#fdf2f8", padding: "1px 7px", borderRadius: 20, whiteSpace: "nowrap", flexShrink: 0 }}>
                        {q.forms.split(",").map((f) => {
                          const t = f.trim();
                          return /^\d+$/.test(t) ? `ACORD ${t}` : t;
                        }).join(", ")}
                      </span>
                    )}
                    <span style={{ fontSize: 13, fontWeight: 500, color: "#0f172a", lineHeight: 1.4 }}>
                      {q.question}
                    </span>
                    {q.current_value && (
                      <span style={{ fontSize: 11, color: "#94a3b8", flexShrink: 0 }}>
                        · Current: {q.current_value}
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>

          <button
            className="btn btn-modal-primary btn-block"
            onClick={handleSend}
            disabled={!canSend || sending}
            style={{ marginTop: 18, opacity: (!canSend || sending) ? 0.6 : 1, cursor: (!canSend || sending) ? "not-allowed" : "pointer", minHeight: 44 }}
          >
            {sending ? (
              <span style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 8 }}>
                <span style={{ width: 14, height: 14, border: "2px solid white", borderTopColor: "transparent", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" }} />
                Sending…
              </span>
            ) : (
              `📧 Send ${selectedCount} Question${selectedCount !== 1 ? "s" : ""} to Client`
            )}
          </button>

          {selectedCount === 0 && (
            <p style={{ fontSize: 11, color: "#f59e0b", textAlign: "center", marginTop: 6 }}>
              ⚠️ Select at least one question to send.
            </p>
          )}

          <p style={{ fontSize: 11, color: "#94a3b8", textAlign: "center", marginTop: 12 }}>
            The client will receive a secure link. Their answers automatically populate your forms.
          </p>
        </div>
      </div>
    </div>
  );
}