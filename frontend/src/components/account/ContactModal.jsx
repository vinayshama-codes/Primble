import { useState } from "react";
import { API_BASE } from "../../config/constants";

export default function ContactModal({ user, onClose }) {
  const [contactEmail, setContactEmail] = useState(user?.email || "");
  const [subject, setSubject] = useState("");
  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [sent, setSent] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!subject.trim() || !message.trim()) {
      setError("Please fill in the subject and message.");
      return;
    }
    setSending(true);
    setError("");
    try {
      const res = await fetch(`${API_BASE}/api/auth/contact`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          from_email: contactEmail.trim(),
          subject: subject.trim(),
          message: message.trim(),
        }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        setError(data.detail || "Failed to send message. Please try again.");
        return;
      }
      setSent(true);
    } catch {
      setError("Network error. Please try again.");
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal-content" style={{ maxWidth: 460 }} onClick={(e) => e.stopPropagation()}>
        <button className="modal-close" onClick={onClose}>✕</button>
        <div className="modal-inner">

          {sent ? (
            <div style={{ textAlign: "center", padding: "20px 0" }}>
              <div style={{
                width: 64, height: 64, borderRadius: "50%",
                background: "rgba(16,185,129,0.1)",
                display: "flex", alignItems: "center", justifyContent: "center",
                margin: "0 auto 20px",
              }}>
                <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="#059669" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="20 6 9 17 4 12" />
                </svg>
              </div>
              <h2 className="step-title" style={{ marginBottom: 10 }}>Message sent!</h2>
              <p className="step-subtitle" style={{ marginBottom: 28 }}>
                We'll get back to you at <strong>{contactEmail}</strong> as soon as possible.
              </p>
              <button className="btn btn-modal-primary" style={{ width: "100%" }} onClick={onClose}>
                Done
              </button>
            </div>
          ) : (
            <>
              <h2 className="step-title" style={{ marginBottom: 6 }}>Contact Primble</h2>
              <p className="step-subtitle" style={{ marginBottom: 24 }}>
                We typically respond within one business day.
              </p>
              <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
                  <label style={{ fontSize: 12.5, fontWeight: 700, color: "#475569" }}>Your Email</label>
                  <input
                    className="acct-input"
                    type="email"
                    value={contactEmail}
                    onChange={e => setContactEmail(e.target.value)}
                    required
                    placeholder="your@email.com"
                  />
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
                  <label style={{ fontSize: 12.5, fontWeight: 700, color: "#475569" }}>Subject</label>
                  <input
                    className="acct-input"
                    type="text"
                    value={subject}
                    onChange={e => setSubject(e.target.value)}
                    required
                    placeholder="How can we help?"
                    maxLength={150}
                  />
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
                  <label style={{ fontSize: 12.5, fontWeight: 700, color: "#475569" }}>Message</label>
                  <textarea
                    className="acct-input"
                    value={message}
                    onChange={e => setMessage(e.target.value)}
                    required
                    placeholder="Describe your question or issue…"
                    rows={5}
                    style={{ resize: "vertical", minHeight: 100, lineHeight: 1.5 }}
                  />
                </div>
                {error && (
                  <div className="alert alert-error"><span>{error}</span></div>
                )}
                <div style={{ display: "flex", gap: 10 }}>
                  <button
                    type="submit"
                    className="btn btn-modal-primary"
                    style={{ flex: 1 }}
                    disabled={sending}
                  >
                    {sending ? (
                      <span style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 8 }}>
                        <span style={{ width: 14, height: 14, border: "2px solid currentColor", borderTopColor: "transparent", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" }} />
                        Sending…
                      </span>
                    ) : "Send Message"}
                  </button>
                  <button type="button" className="btn btn-modal-secondary" onClick={onClose}>Cancel</button>
                </div>
              </form>
            </>
          )}

        </div>
      </div>
    </div>
  );
}
