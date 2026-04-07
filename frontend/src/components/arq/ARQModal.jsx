import { useState, useEffect } from "react";
import { sendArq } from "../../api/arqApi";

export default function ARQModal({ sessionId, token, questions, producerFullName, producerFirstName, onClose, onSuccess }) {
  const [clientEmail,        setClientEmail]        = useState("");
  const [clientName,         setClientName]          = useState("");
  const [selectedQuestions,  setSelectedQuestions]   = useState({});
  const [selectAll,          setSelectAll]            = useState(true);
  const [sending,            setSending]              = useState(false);
  const [error,              setError]                = useState("");

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

  const selectedCount = Object.values(selectedQuestions).filter(Boolean).length;
  const isEmailValid  = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(clientEmail);
  const canSend       = isEmailValid && selectedCount > 0;

  const handleSend = async () => {
    if (!canSend) return;
    setSending(true);
    setError("");

    const selectedList = questions.filter((q) => selectedQuestions[q.field_name]);
    const { ok, data } = await sendArq(token, {
      session_id:   sessionId,
      client_email: clientEmail,
      client_name:  clientName,
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
    <div className="modal-overlay">
      <div className="modal-content" style={{ maxWidth: 680 }} onClick={(e) => e.stopPropagation()}>
        <button className="modal-close" onClick={onClose}>✕</button>
        <div className="modal-inner">
          <div style={{ fontSize: 36, marginBottom: 8, textAlign: "center" }}>📧</div>
          <h2 className="step-title" style={{ textAlign: "center" }}>Send to Client</h2>
          <p className="step-subtitle" style={{ textAlign: "center" }}>
            Select questions to send. The client will receive a secure link to answer them.
          </p>

          {error && (
            <div className="alert alert-error" style={{ marginBottom: 16 }}>
              ⚠️ {error}
              <button className="alert-close" onClick={() => setError("")}>✕</button>
            </div>
          )}

          <div className="form-group" style={{ marginBottom: 16 }}>
            <label>Client Email <span className="field-required">*</span></label>
            <input
              type="email"
              value={clientEmail}
              onChange={(e) => setClientEmail(e.target.value)}
              placeholder="client@theircompany.com"
              className="form-input"
            />
          </div>

          <div className="form-group" style={{ marginBottom: 20 }}>
            <label>Client First Name <span style={{ color: "#94a3b8", fontWeight: 400 }}>(optional)</span></label>
            <input
              type="text"
              value={clientName}
              onChange={(e) => setClientName(e.target.value)}
              placeholder="e.g. John"
              className="form-input"
            />
          </div>

          <div style={{ borderTop: "1px solid #e2e8f0", paddingTop: 16 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
              <span style={{ fontWeight: 600, fontSize: 14, color: "#1e293b" }}>
                Questions ({selectedCount}/{questions.length} selected)
              </span>
              <button
                onClick={handleSelectAll}
                style={{ background: "none", border: "1px solid #e2e8f0", borderRadius: 6, padding: "4px 12px", fontSize: 12, cursor: "pointer", color: "#4f7cff", fontWeight: 500 }}
              >
                {selectAll ? "Deselect All" : "Select All"}
              </button>
            </div>

            <div style={{ maxHeight: 340, overflowY: "auto", display: "flex", flexDirection: "column", gap: 8 }}>
              {questions.map((q, idx) => (
                <div
                  key={idx}
                  onClick={() => handleToggle(q.field_name)}
                  style={{
                    border: "1px solid",
                    borderColor: selectedQuestions[q.field_name] ? "#e6007a" : "#e2e8f0",
                    borderRadius: 8,
                    padding: "10px 14px",
                    cursor: "pointer",
                    background: selectedQuestions[q.field_name] ? "rgba(230,0,122,0.04)" : "#fff",
                    display: "flex",
                    alignItems: "flex-start",
                    gap: 10,
                    transition: "all 0.15s",
                    opacity: selectedQuestions[q.field_name] ? 1 : 0.55,
                  }}
                >
                  <input
                    type="checkbox"
                    checked={!!selectedQuestions[q.field_name]}
                    onChange={() => handleToggle(q.field_name)}
                    onClick={(e) => e.stopPropagation()}
                    style={{ marginTop: 3, width: 16, height: 16, cursor: "pointer", accentColor: "#e6007a", flexShrink: 0 }}
                  />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <span style={{ fontSize: 11, fontWeight: 600, color: "#e6007a", background: "#fdf2f8", padding: "1px 8px", borderRadius: 20, display: "inline-block", marginBottom: 4 }}>
                      ACORD: {q.forms}
                    </span>
                    <p style={{ margin: 0, fontSize: 13, fontWeight: 600, color: "#0f172a", lineHeight: 1.4 }}>
                      {q.question}
                    </p>
                    {q.current_value && (
                      <p style={{ margin: "4px 0 0", fontSize: 11, color: "#94a3b8" }}>
                        Current: {q.current_value}
                      </p>
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
            style={{ marginTop: 20, opacity: (!canSend || sending) ? 0.6 : 1, cursor: (!canSend || sending) ? "not-allowed" : "pointer" }}
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

          {!isEmailValid && clientEmail && (
            <p style={{ fontSize: 11, color: "#ef4444", textAlign: "center", marginTop: 8 }}>
              Please enter a valid email address.
            </p>
          )}
          {selectedCount === 0 && (
            <p style={{ fontSize: 11, color: "#f59e0b", textAlign: "center", marginTop: 8 }}>
              ⚠️ Select at least one question to send.
            </p>
          )}

          <p style={{ fontSize: 11, color: "#94a3b8", textAlign: "center", marginTop: 14 }}>
            The client will receive a secure link. Their answers will automatically populate your forms.
          </p>
        </div>
      </div>
    </div>
  );
}