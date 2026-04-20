// AcordModal.jsx

import { useState, useEffect, useRef } from "react";
import { API_BASE } from "../../config/constants";
import { gradeColor, barColor } from "../../utils/formatters";
import ProcessStageOverlay from "../overlays/ProcessStageOverlay";
import PDFJsViewer from "./PDFJsViewer";

const SQS_LABELS = {
  structural_completeness: "Structural Completeness",
  exposure_consistency:    "Exposure Consistency",
  property_integrity:      "Property Integrity",
  loss_history_alignment:  "Loss History",
  umbrella_limit_adequacy: "Umbrella Adequacy",
  narrative_quality:       "Narrative Quality",
};
const SQS_WEIGHTS = {
  structural_completeness: 25, exposure_consistency: 25,
  property_integrity: 15,      loss_history_alignment: 15,
  umbrella_limit_adequacy: 10, narrative_quality: 10,
};

// ── Delete Confirm Modal ───────────────────────────────────────────────────
function DeleteConfirmModal({ onConfirm, onCancel }) {
  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(15,23,42,0.7)", backdropFilter: "blur(6px)", zIndex: 99999, display: "flex", alignItems: "center", justifyContent: "center", padding: 20 }}>
      <div style={{ background: "#fff", borderRadius: 16, padding: "32px 28px", maxWidth: 400, width: "100%", boxShadow: "0 24px 60px rgba(0,0,0,0.25)", animation: "slideUp 0.2s ease-out" }}>
        <div style={{ width: 52, height: 52, borderRadius: "50%", background: "#fef2f2", border: "2px solid #fecaca", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 22, margin: "0 auto 18px" }}>🗑️</div>
        <h3 style={{ textAlign: "center", fontSize: 18, fontWeight: 700, color: "#0f172a", marginBottom: 8 }}>Delete Session?</h3>
        <p style={{ textAlign: "center", fontSize: 14, color: "#64748b", lineHeight: 1.6, marginBottom: 24 }}>This submission package will be permanently deleted and cannot be recovered.</p>
        <div style={{ display: "flex", gap: 10 }}>
          <button onClick={onCancel} style={{ flex: 1, padding: "10px 0", borderRadius: 8, border: "1px solid #e2e8f0", background: "#f8fafc", color: "#475569", fontSize: 14, fontWeight: 600, cursor: "pointer" }}>Cancel</button>
          <button onClick={onConfirm} style={{ flex: 1, padding: "10px 0", borderRadius: 8, border: "none", background: "#dc2626", color: "#fff", fontSize: 14, fontWeight: 600, cursor: "pointer" }}>Delete</button>
        </div>
      </div>
    </div>
  );
}

// ── ARQ Modal ─────────────────────────────────────────────────────────────
function ARQModal({ sessionId, token, questions, onClose, onSuccess }) {
  const [clientEmail, setClientEmail] = useState("");
  const [clientName, setClientName] = useState("");
  const [selectedQuestions, setSelectedQuestions] = useState({});
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [selectAll, setSelectAll] = useState(true);

  useEffect(() => {
    const init = {};
    questions.forEach(q => { init[q.field_name] = true; });
    setSelectedQuestions(init);
  }, [questions]);

  const handleToggle = fn => setSelectedQuestions(prev => ({ ...prev, [fn]: !prev[fn] }));
  const handleSelectAll = () => {
    const next = !selectAll; setSelectAll(next);
    const updated = {}; questions.forEach(q => { updated[q.field_name] = next; });
    setSelectedQuestions(updated);
  };

  const selectedCount = Object.values(selectedQuestions).filter(Boolean).length;
  const isEmailValid = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(clientEmail);
  const canSend = isEmailValid && selectedCount > 0;

  const handleSend = async () => {
    if (!canSend) return;
    setSending(true); setError("");
    const selectedList = questions.filter(q => selectedQuestions[q.field_name]);
    try {
      const res = await fetch(`${API_BASE}/api/arq/send`, { method: "POST", headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` }, body: JSON.stringify({ session_id: sessionId, client_email: clientEmail, client_name: clientName, questions: selectedList }) });
      const data = await res.json();
      if (res.ok && data.success) onSuccess(data);
      else setError(data.detail || data.message || "Failed to send questionnaire.");
    } catch (e) { setError("Network error: " + e.message); }
    finally { setSending(false); }
  };

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(15,23,42,0.75)", backdropFilter: "blur(8px)", zIndex: 99999, display: "flex", alignItems: "center", justifyContent: "center", padding: 20 }}>
      <div onClick={e => e.stopPropagation()} style={{ background: "#fff", borderRadius: 20, width: "100%", maxWidth: 620, maxHeight: "90vh", overflow: "hidden", display: "flex", flexDirection: "column", boxShadow: "0 32px 80px rgba(0,0,0,0.2)" }}>
        <div style={{ padding: "24px 28px 0", flexShrink: 0 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 20 }}>
            <div>
              <div style={{ fontSize: 11, fontWeight: 700, color: "#e6007a", marginBottom: 4, letterSpacing: "0.05em", textTransform: "uppercase" }}>Client Questionnaire</div>
              <h2 style={{ fontSize: 22, fontWeight: 700, color: "#0f172a", margin: 0 }}>Send to Client</h2>
              <p style={{ fontSize: 13, color: "#64748b", marginTop: 4 }}>Client answers will auto-populate your ACORD forms.</p>
            </div>
            <button onClick={onClose} style={{ width: 32, height: 32, borderRadius: "50%", border: "1px solid #e6007a", background: "rgba(230,0,122,0.08)", color: "#e6007a", fontSize: 16, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0, transition: "all 0.2s" }}
              onMouseEnter={e => { e.currentTarget.style.background = "#e6007a"; e.currentTarget.style.color = "#fff"; }}
              onMouseLeave={e => { e.currentTarget.style.background = "rgba(230,0,122,0.08)"; e.currentTarget.style.color = "#e6007a"; }}>✕</button>
          </div>
          {error && <div style={{ background: "#fef2f2", border: "1px solid #fecaca", borderRadius: 8, padding: "10px 14px", marginBottom: 16, color: "#dc2626", fontSize: 13 }}>⚠️ {error}</div>}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 20 }}>
            <div>
              <label style={{ display: "block", fontSize: 12, fontWeight: 600, color: "#374151", marginBottom: 6 }}>Client Email <span style={{ color: "#e6007a" }}>*</span></label>
              <input type="email" value={clientEmail} onChange={e => setClientEmail(e.target.value)} placeholder="client@company.com"
                style={{ width: "100%", padding: "9px 12px", border: "1px solid #e2e8f0", borderRadius: 8, fontSize: 13, outline: "none", boxSizing: "border-box" }}
                onFocus={e => e.target.style.borderColor = "#e6007a"} onBlur={e => e.target.style.borderColor = "#e2e8f0"} />
            </div>
            <div>
              <label style={{ display: "block", fontSize: 12, fontWeight: 600, color: "#374151", marginBottom: 6 }}>First Name <span style={{ color: "#94a3b8", fontWeight: 400 }}>(optional)</span></label>
              <input type="text" value={clientName} onChange={e => setClientName(e.target.value)} placeholder="e.g. John"
                style={{ width: "100%", padding: "9px 12px", border: "1px solid #e2e8f0", borderRadius: 8, fontSize: 13, outline: "none", boxSizing: "border-box" }}
                onFocus={e => e.target.style.borderColor = "#e6007a"} onBlur={e => e.target.style.borderColor = "#e2e8f0"} />
            </div>
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10, paddingBottom: 10, borderBottom: "1px solid #f1f5f9" }}>
            <span style={{ fontSize: 13, fontWeight: 600, color: "#1e293b" }}>Questions <span style={{ color: "#64748b", fontWeight: 400 }}>({selectedCount}/{questions.length} selected)</span></span>
            <button onClick={handleSelectAll} style={{ fontSize: 12, fontWeight: 600, color: "#4f7cff", background: "rgba(79,124,255,0.06)", border: "1px solid rgba(79,124,255,0.2)", borderRadius: 6, padding: "3px 10px", cursor: "pointer" }}>
              {selectAll ? "Deselect All" : "Select All"}
            </button>
          </div>
        </div>
        <div style={{ flex: 1, overflowY: "auto", padding: "0 28px 4px" }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {questions.map((q, idx) => (
              <div key={idx} onClick={() => handleToggle(q.field_name)}
                style={{ border: `1.5px solid ${selectedQuestions[q.field_name] ? "#e6007a" : "#e2e8f0"}`, borderRadius: 10, padding: "10px 14px", cursor: "pointer", background: selectedQuestions[q.field_name] ? "rgba(230,0,122,0.03)" : "#fafafa", display: "flex", alignItems: "flex-start", gap: 10, opacity: selectedQuestions[q.field_name] ? 1 : 0.5, transition: "all 0.15s" }}>
                <input type="checkbox" checked={!!selectedQuestions[q.field_name]} onChange={() => handleToggle(q.field_name)} onClick={e => e.stopPropagation()} style={{ marginTop: 3, width: 15, height: 15, cursor: "pointer", accentColor: "#e6007a", flexShrink: 0 }} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <span style={{ fontSize: 10, fontWeight: 700, color: "#e6007a", background: "#fdf2f8", padding: "1px 7px", borderRadius: 20, display: "inline-block", marginBottom: 4 }}>ACORD {q.forms}</span>
                  <p style={{ margin: 0, fontSize: 13, fontWeight: 600, color: "#0f172a", lineHeight: 1.45 }}>{q.question}</p>
                  {q.current_value && <p style={{ margin: "3px 0 0", fontSize: 11, color: "#94a3b8" }}>Current: {q.current_value}</p>}
                </div>
              </div>
            ))}
          </div>
        </div>
        <div style={{ padding: "16px 28px 24px", flexShrink: 0, borderTop: "1px solid #f1f5f9", marginTop: 8 }}>
          <button onClick={handleSend} disabled={!canSend || sending}
            style={{ width: "100%", padding: "12px 0", borderRadius: 10, border: "none", background: canSend && !sending ? "#e6007a" : "#e2e8f0", color: canSend && !sending ? "#fff" : "#94a3b8", fontSize: 14, fontWeight: 700, cursor: canSend && !sending ? "pointer" : "not-allowed", display: "flex", alignItems: "center", justifyContent: "center", gap: 8 }}>
            {sending ? <><span style={{ width: 14, height: 14, border: "2px solid rgba(255,255,255,0.4)", borderTopColor: "#fff", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" }} />Sending…</> : `Send ${selectedCount} Question${selectedCount !== 1 ? "s" : ""} to Client`}
          </button>
          {!isEmailValid && clientEmail && <p style={{ fontSize: 11, color: "#ef4444", textAlign: "center", marginTop: 8 }}>Please enter a valid email address.</p>}
          <p style={{ fontSize: 11, color: "#94a3b8", textAlign: "center", marginTop: 10 }}>Client receives a secure link valid for 72 hours.</p>
        </div>
      </div>
    </div>
  );
}

// ── ARQ Status Panel ───────────────────────────────────────────────────────
function ARQStatusPanel({ arqSessions, token, onRefresh }) {
  const [reminding, setReminding] = useState(null);
  const handleRemind = async (arq_id) => {
    setReminding(arq_id);
    try { await fetch(`${API_BASE}/api/arq/remind/${arq_id}`, { method: "POST", headers: { Authorization: `Bearer ${token}` } }); onRefresh(); } catch (_) {}
    setReminding(null);
  };
  const fmtDate = iso => iso ? new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "—";
  if (!arqSessions || arqSessions.length === 0) return null;
  return (
    <div style={{ marginTop: 8 }}>
      <div style={{ fontSize: 10, fontWeight: 700, color: "#94a3b8", letterSpacing: "0.06em", marginBottom: 5, textTransform: "uppercase" }}>Sent Questionnaires</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
        {arqSessions.map(arq => {
          const isExpired = new Date() > new Date(arq.expires_at) && arq.status !== "submitted";
          const status = isExpired ? "expired" : arq.status;
          const sc = { submitted: { bg: "#dcfce7", color: "#166534", border: "#86efac", label: "✓ Done" }, expired: { bg: "#f1f5f9", color: "#64748b", border: "#cbd5e1", label: "Expired" }, pending: { bg: "#fef9c3", color: "#854d0e", border: "#fde047", label: "Pending" } }[status] || {};
          return (
            <div key={arq.id} style={{ background: "#fff", border: "1px solid #e2e8f0", borderRadius: 8, padding: "7px 10px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div style={{ fontSize: 11, fontWeight: 600, color: "#1e293b", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{arq.client_name ? `${arq.client_name} (${arq.email})` : arq.email}</div>
                  <div style={{ fontSize: 10, color: "#94a3b8", marginTop: 1 }}>{fmtDate(arq.created_at)}</div>
                </div>
                <span style={{ fontSize: 10, fontWeight: 700, padding: "2px 7px", borderRadius: 20, border: `1px solid ${sc.border}`, background: sc.bg, color: sc.color, flexShrink: 0 }}>{sc.label}</span>
              </div>
              {arq.status === "pending" && !isExpired && (
                <button onClick={() => handleRemind(arq.id)} disabled={reminding === arq.id}
                  style={{ marginTop: 5, fontSize: 10, fontWeight: 600, color: "#4f7cff", background: "rgba(79,124,255,0.06)", border: "1px solid rgba(79,124,255,0.2)", borderRadius: 5, padding: "2px 8px", cursor: reminding === arq.id ? "wait" : "pointer", opacity: reminding === arq.id ? 0.6 : 1 }}>
                  {reminding === arq.id ? "Sending…" : "Remind"}{arq.reminder_count > 0 && ` (${arq.reminder_count})`}
                </button>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Dashboard Step ─────────────────────────────────────────────────────────
const STATUS_CONFIG = {
  COMPLETED:   { label: "Completed",   dot: "#10b981", bg: "#dcfce7", color: "#166534", border: "#86efac", icon: "✅" },
  IN_PROGRESS: { label: "In Progress", dot: "#f59e0b", bg: "#fef9c3", color: "#854d0e", border: "#fde047", icon: "📝" },
  NOT_STARTED: { label: "Not Started", dot: "#94a3b8", bg: "#f1f5f9", color: "#64748b", border: "#cbd5e1", icon: "📄" },
};

function DashboardStep({ token, onResume, onNewPackage }) {
  const [sessions, setSessions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [deleteTarget, setDeleteTarget] = useState(null);

  useEffect(() => {
    fetch(`${API_BASE}/api/sessions`, { headers: { Authorization: `Bearer ${token}` } })
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d?.success) setSessions(d.sessions || []); })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [token]);

  const handleDelete = async sid => {
    setSessions(prev => prev.filter(s => s.session_id !== sid));
    setDeleteTarget(null);
    try { await fetch(`${API_BASE}/api/sessions/${sid}`, { method: "DELETE", headers: { Authorization: `Bearer ${token}` } }); } catch (_) {}
  };

  const fmtDate = iso => iso ? new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) : "—";
  const avgSqs = sqsMap => { const scores = Object.values(sqsMap || {}).map(s => s?.sqs_score).filter(n => n != null); return scores.length ? Math.round(scores.reduce((a, b) => a + b, 0) / scores.length) : null; };
  const sqsColor = v => v >= 75 ? "#10b981" : v >= 50 ? "#f59e0b" : "#ef4444";

  const completedCount  = sessions.filter(s => s.status === "COMPLETED").length;
  const inProgressCount = sessions.filter(s => s.status === "IN_PROGRESS").length;

  return (
    <div style={{ maxWidth: 860, margin: "0 auto", padding: "0 0 48px" }}>
      {deleteTarget && <DeleteConfirmModal onConfirm={() => handleDelete(deleteTarget)} onCancel={() => setDeleteTarget(null)} />}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", marginBottom: 28 }}>
        <div>
          <div style={{ fontSize: 11, fontWeight: 700, color: "#e6007a", letterSpacing: "0.06em", marginBottom: 6, textTransform: "uppercase" }}>Submissions</div>
          <h2 style={{ fontSize: 26, fontWeight: 700, color: "#0f172a", margin: 0, lineHeight: 1.2 }}>Package Dashboard</h2>
          <p style={{ fontSize: 14, color: "#64748b", marginTop: 5 }}>Open any submission to edit or re-download, or start a new one.</p>
          {sessions.length > 0 && (
            <div style={{ display: "flex", gap: 10, marginTop: 10, flexWrap: "wrap" }}>
              {completedCount > 0 && (
                <span style={{ fontSize: 11, fontWeight: 600, padding: "3px 10px", borderRadius: 20, background: STATUS_CONFIG.COMPLETED.bg, color: STATUS_CONFIG.COMPLETED.color, border: `1px solid ${STATUS_CONFIG.COMPLETED.border}` }}>
                  {completedCount} Completed
                </span>
              )}
              {inProgressCount > 0 && (
                <span style={{ fontSize: 11, fontWeight: 600, padding: "3px 10px", borderRadius: 20, background: STATUS_CONFIG.IN_PROGRESS.bg, color: STATUS_CONFIG.IN_PROGRESS.color, border: `1px solid ${STATUS_CONFIG.IN_PROGRESS.border}` }}>
                  {inProgressCount} In Progress
                </span>
              )}
            </div>
          )}
        </div>
        <button onClick={onNewPackage}
          style={{ display: "flex", alignItems: "center", gap: 7, padding: "10px 20px", background: "#e6007a", color: "#fff", border: "none", borderRadius: 10, fontSize: 14, fontWeight: 700, cursor: "pointer", boxShadow: "0 4px 14px rgba(230,0,122,0.3)", whiteSpace: "nowrap" }}
          onMouseEnter={e => { e.currentTarget.style.background = "#c00066"; e.currentTarget.style.transform = "translateY(-1px)"; }}
          onMouseLeave={e => { e.currentTarget.style.background = "#e6007a"; e.currentTarget.style.transform = "none"; }}>
          <span style={{ fontSize: 16 }}>+</span> New Package
        </button>
      </div>
      {loading ? (
        <div style={{ textAlign: "center", padding: "80px 0" }}>
          <div style={{ width: 36, height: 36, border: "3px solid #f1f5f9", borderTopColor: "#e6007a", borderRadius: "50%", animation: "spin 0.8s linear infinite", margin: "0 auto 14px" }} />
          <p style={{ color: "#94a3b8", fontSize: 14 }}>Loading packages…</p>
        </div>
      ) : sessions.length === 0 ? (
        <div style={{ textAlign: "center", padding: "80px 24px", background: "#fafafa", borderRadius: 16, border: "2px dashed #e2e8f0" }}>
          <div style={{ width: 64, height: 64, borderRadius: 16, background: "rgba(230,0,122,0.06)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 28, margin: "0 auto 16px" }}>📂</div>
          <p style={{ fontSize: 16, fontWeight: 700, color: "#1e293b", marginBottom: 6 }}>No packages yet</p>
          <p style={{ fontSize: 14, color: "#64748b", marginBottom: 24 }}>Upload your first submission documents to get started.</p>
          <button onClick={onNewPackage} style={{ padding: "10px 24px", background: "#e6007a", color: "#fff", border: "none", borderRadius: 10, fontSize: 14, fontWeight: 700, cursor: "pointer" }}>+ Start First Package</button>
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {sessions.map(s => {
            const avg = avgSqs(s.sqs);
            const sc  = STATUS_CONFIG[s.status] || STATUS_CONFIG.NOT_STARTED;
            return (
              <div key={s.session_id} className="session-card"
                onClick={() => onResume(s.session_id)}
                style={{ background: "#fff", border: "1px solid #e8edf5", borderRadius: 12, padding: "16px 18px", cursor: "pointer", display: "flex", alignItems: "center", gap: 14, transition: "all 0.18s", position: "relative", boxShadow: "0 1px 4px rgba(0,0,0,0.04)" }}
                onMouseEnter={e => { e.currentTarget.style.borderColor = "#e6007a"; e.currentTarget.style.boxShadow = "0 4px 20px rgba(230,0,122,0.1)"; e.currentTarget.style.transform = "translateY(-1px)"; }}
                onMouseLeave={e => { e.currentTarget.style.borderColor = "#e8edf5"; e.currentTarget.style.boxShadow = "0 1px 4px rgba(0,0,0,0.04)"; e.currentTarget.style.transform = "none"; }}>
                <div style={{ width: 42, height: 42, borderRadius: 10, background: "linear-gradient(135deg, rgba(230,0,122,0.1), rgba(230,0,122,0.05))", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 18, flexShrink: 0 }}>{sc.icon}</div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontWeight: 700, fontSize: 14, color: "#0f172a", marginBottom: 3, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.applicant}</div>
                  <div style={{ fontSize: 12, color: "#64748b", display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                    <span style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 11, fontWeight: 600, padding: "1px 8px", borderRadius: 20, background: sc.bg, color: sc.color, border: `1px solid ${sc.border}`, flexShrink: 0 }}>
                      <span style={{ width: 5, height: 5, borderRadius: "50%", background: sc.dot, display: "inline-block" }} />
                      {sc.label}
                    </span>
                    {s.form_ids.length > 0 && <span style={{ background: "#f1f5f9", borderRadius: 4, padding: "1px 6px" }}>{s.form_ids.join(", ")}</span>}
                    {s.lines?.length > 0 && <span>{s.lines.slice(0, 2).join(", ")}{s.lines.length > 2 ? ` +${s.lines.length - 2}` : ""}</span>}
                  </div>
                </div>
                <div style={{ textAlign: "right", flexShrink: 0 }}>
                  {avg != null && <div style={{ fontSize: 17, fontWeight: 800, color: sqsColor(avg), marginBottom: 1, lineHeight: 1 }}>{avg}<span style={{ fontSize: 10, fontWeight: 500, color: "#94a3b8" }}>/100</span></div>}
                  <div style={{ fontSize: 11, color: "#94a3b8" }}>{fmtDate(s.updated_at)}</div>
                  {s.status === "COMPLETED" && s.last_downloaded_at && (
                    <div style={{ fontSize: 10, color: "#10b981", fontWeight: 600, marginTop: 2 }}>Downloaded {fmtDate(s.last_downloaded_at)}</div>
                  )}
                </div>
                <div style={{ color: "#cbd5e1", fontSize: 16, flexShrink: 0 }}>→</div>
                <button className="session-delete-btn" onClick={e => { e.stopPropagation(); setDeleteTarget(s.session_id); }} title="Delete session">✕</button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── Main AcordModal ────────────────────────────────────────────────────────
export default function AcordModal({
  onClose, user, token, onUserUpdate, onShowUpgrade,
  resumeSessionId, savedSignature, onOpenSignatureModal,
  onOpenBillingPortal, billingPortalLoading,
  fullPage = false,
}) {
  const dropRef = useRef(null);
  const [files, setFiles] = useState([]);
  const [dragging, setDragging] = useState(false);
  const [loading, setLoading] = useState(false);
  const [processingStage, setProcessingStage] = useState("");
  const [step, setStep] = useState(resumeSessionId ? "resuming" : "dashboard");

  useEffect(() => {
    if (step === "editor") {
      document.body.style.overflow = "hidden";
      window.scrollTo(0, 0);
    } else {
      document.body.style.overflow = "";
    }
    return () => { document.body.style.overflow = ""; };
  }, [step]);

  const [error, setError] = useState(null);
  const [sessionId, setSessionId] = useState(resumeSessionId || null);
  const [docSummary, setDocSummary] = useState([]);
  const [flags, setFlags] = useState({});
  const [hardStops, setHardStops] = useState([]);
  const [softStops, setSoftStops] = useState([]);
  const [tier2Score, setTier2Score] = useState(null);
  const [tier2Missing, setTier2Missing] = useState([]);
  const [recommendations, setRecommendations] = useState([]);
  const [allAvailableForms, setAllAvailableForms] = useState([]);
  const [checkedFormIds, setCheckedFormIds] = useState(new Set());
  const [showAddForms, setShowAddForms] = useState(false);
  const [generatedForms, setGeneratedForms] = useState({});
  const [activeFormId, setActiveFormId] = useState(null);
  const [crossIssues, setCrossIssues] = useState([]);
  const [pdfLoading, setPdfLoading] = useState({});
  const [pkgStatusMsg, setPkgStatusMsg] = useState("");
  const [pkgStatusType, setPkgStatusType] = useState("");
  const [signedForms, setSignedForms] = useState(new Set());
  const [showUploadOverlay, setShowUploadOverlay] = useState(false);
  const [showGenerateOverlay, setShowGenerateOverlay] = useState(false);
  const [showDownloadOverlay, setShowDownloadOverlay] = useState(false);
  const [showAcordModal, setShowAcordModal] = useState(false);
  const [acordModalAction, setAcordModalAction] = useState(null);
  const [acordLicenseChecked, setAcordLicenseChecked] = useState(false);
  const [acordModalLoading, setAcordModalLoading] = useState(false);
  const [epicLoading, setEpicLoading] = useState(false);
  const [epicSuccess, setEpicSuccess] = useState(false);
  const [showARQModal, setShowARQModal] = useState(false);
  const [arqQuestions, setArqQuestions] = useState([]);
  const [arqLoadingQ, setArqLoadingQ] = useState(false);
  const [arqSessions, setArqSessions] = useState([]);
  const [arqNotifCount, setArqNotifCount] = useState(0);
  const [clientFilledFields, setClientFilledFields] = useState([]);
  const [liteSqsData, setLiteSqsData] = useState(null);
  const [liteCoverLoading, setLiteCoverLoading] = useState(false);

  useEffect(() => {
    if (step !== "lite" || !sessionId || !token) return;
    fetch(`${API_BASE}/api/clarity/analyze/${sessionId}`, { method: "POST", headers: { Authorization: `Bearer ${token}` } })
      .then(r => r.ok ? r.json() : null)
      .then(d => {
        if (d?.success) {
          // Normalise into the shape the rest of the Lite step expects
          setLiteSqsData({
            sqs:          d.sqs_combined,
            soft_stops:   d.soft_stops   || [],
            hard_stops:   d.hard_stops   || [],
            arq_questions: d.arq_questions || [],
          });
        }
      })
      .catch(() => {});
  }, [step, sessionId]); // eslint-disable-line

  useEffect(() => {
    if (!resumeSessionId) return;
    setLoading(true); setProcessingStage("Restoring your session...");
    fetch(`${API_BASE}/api/session/${resumeSessionId}`, { headers: { Authorization: `Bearer ${token}` } })
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (data && data.generated_forms && Object.keys(data.generated_forms).length > 0) {
          setGeneratedForms(data.generated_forms); setCrossIssues(data.cross_issues || []);
          const firstId = Object.keys(data.generated_forms)[0]; setActiveFormId(firstId);
          const readyMap = {}; Object.keys(data.generated_forms).forEach(fid => { readyMap[fid] = false; });
          setPdfLoading(readyMap); setStep("editor");
        } else { setStep("dashboard"); setSessionId(null); }
      })
      .catch(() => { setStep("dashboard"); setSessionId(null); })
      .finally(() => { setLoading(false); setProcessingStage(""); });
  }, [resumeSessionId]); // eslint-disable-line

  useEffect(() => {
    const el = dropRef.current; if (!el) return;
    const over = e => { e.preventDefault(); setDragging(true); };
    const leave = () => setDragging(false);
    const drop = e => {
      e.preventDefault(); setDragging(false);
      const uploaded = Array.from(e.dataTransfer.files).filter(f => f.type === "application/pdf" || f.name.toLowerCase().endsWith(".zip") || f.type.startsWith("image/"));
      setFiles(prev => [...prev, ...uploaded]);
    };
    el.addEventListener("dragover", over); el.addEventListener("dragleave", leave); el.addEventListener("drop", drop);
    return () => { el.removeEventListener("dragover", over); el.removeEventListener("dragleave", leave); el.removeEventListener("drop", drop); };
  }, []);

  useEffect(() => {
    if ((step !== "editor" && step !== "lite") || !sessionId || !token) return;
    refreshArqData();
  }, [step, sessionId]); // eslint-disable-line

  const refreshArqData = async () => {
    if (!sessionId || !token) return [];
    fetch(`${API_BASE}/api/arq/list/${sessionId}`, { headers: { Authorization: `Bearer ${token}` } })
      .then(r => r.ok ? r.json() : null).then(d => { if (d?.success) setArqSessions(d.arq_sessions || []); }).catch(() => {});
    fetch(`${API_BASE}/api/arq/notifications`, { headers: { Authorization: `Bearer ${token}` } })
      .then(r => r.ok ? r.json() : null).then(d => { if (d?.notifications) setArqNotifCount(d.notifications.filter(n => !n.read_status).length); }).catch(() => {});
    try {
      const r = await fetch(`${API_BASE}/api/arq/client-filled/${sessionId}`, { headers: { Authorization: `Bearer ${token}` } });
      const d = r.ok ? await r.json() : null;
      const fields = d?.client_filled_fields || [];
      setClientFilledFields(fields); return fields;
    } catch { return []; }
  };

  const handleOpenARQ = async () => {
    if (!sessionId) return;
    setArqLoadingQ(true);
    try {
      const res = await fetch(`${API_BASE}/api/arq/generate/${sessionId}`, { headers: { Authorization: `Bearer ${token}` } });
      const data = await res.json();
      if (res.ok && data.success) { setArqQuestions(data.questions || []); setShowARQModal(true); }
      else setError(data.detail || "Failed to generate questions.");
    } catch (e) { setError("Network error: " + e.message); }
    finally { setArqLoadingQ(false); }
  };

  const resetToUpload = () => {
    setFiles([]); setSessionId(null); setStep("upload"); setError(null);
    setDocSummary([]); setFlags({}); setHardStops([]); setSoftStops([]);
    setTier2Score(null); setTier2Missing([]); setRecommendations([]);
    setAllAvailableForms([]); setCheckedFormIds(new Set());
    setGeneratedForms({}); setActiveFormId(null); setCrossIssues([]);
    setPdfLoading({}); setEpicLoading(false); setEpicSuccess(false);
    setSignedForms(new Set()); setShowUploadOverlay(false); setShowGenerateOverlay(false); setShowDownloadOverlay(false);
    setArqQuestions([]); setArqSessions([]); setClientFilledFields([]); setArqNotifCount(0);
  };

  const goToDashboard = () => {
    setFiles([]); setSessionId(null); setStep("dashboard"); setError(null);
    setDocSummary([]); setFlags({}); setHardStops([]); setSoftStops([]);
    setTier2Score(null); setTier2Missing([]); setRecommendations([]);
    setAllAvailableForms([]); setCheckedFormIds(new Set());
    setGeneratedForms({}); setActiveFormId(null); setCrossIssues([]);
    setPdfLoading({}); setEpicLoading(false); setEpicSuccess(false);
    setSignedForms(new Set()); setShowUploadOverlay(false); setShowGenerateOverlay(false); setShowDownloadOverlay(false);
    setArqQuestions([]); setArqSessions([]); setClientFilledFields([]); setArqNotifCount(0);
  };

  const handleResumeSession = sid => {
    setLoading(true); setProcessingStage("Restoring session…"); setSessionId(sid);
    fetch(`${API_BASE}/api/session/${sid}`, { headers: { Authorization: `Bearer ${token}` } })
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (data && data.generated_forms && Object.keys(data.generated_forms).length > 0) {
          setGeneratedForms(data.generated_forms); setCrossIssues(data.cross_issues || []);
          const firstId = Object.keys(data.generated_forms)[0]; setActiveFormId(firstId);
          const readyMap = {}; Object.keys(data.generated_forms).forEach(fid => { readyMap[fid] = false; });
          setPdfLoading(readyMap); setStep("editor");
        } else { setStep("upload"); setSessionId(null); }
      })
      .catch(() => { setStep("upload"); setSessionId(null); })
      .finally(() => { setLoading(false); setProcessingStage(""); });
  };

  const handleSendToEpic = async formId => {
    if (!formId || !sessionId) return;
    setEpicLoading(true); setEpicSuccess(false);
    try {
      const res = await fetch(`${API_BASE}/api/send-to-epic/${sessionId}/${formId}`, { headers: { Authorization: `Bearer ${token}` } });
      const data = await res.json();
      if (res.ok && data.success) { setEpicSuccess(true); setTimeout(() => setEpicSuccess(false), 3500); }
      else setError(data.detail || "Failed to send to EPIC.");
    } catch (e) { setError("EPIC send failed: " + e.message); }
    finally { setEpicLoading(false); }
  };

  const gatedDownload = action => {
    if (user?.acord_license_confirmed) { action(); return; }
    setAcordLicenseChecked(false); setAcordModalAction(() => action); setShowAcordModal(true);
  };

  const handleAcordConfirm = async () => {
    if (!acordLicenseChecked) return;
    setAcordModalLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/acord/confirm-license`, { method: "POST", headers: { Authorization: `Bearer ${token}` } });
      if (res.ok) { onUserUpdate({ ...user, acord_license_confirmed: true }); setShowAcordModal(false); if (acordModalAction) acordModalAction(); }
      else setError("License confirmation failed. Please try again.");
    } catch { setError("Network error during license confirmation."); }
    finally { setAcordModalLoading(false); }
  };

  const _doDownloadOne = async formId => {
    setLoading(true); setShowDownloadOverlay(true);
    try {
      const res = await fetch(`${API_BASE}/api/download-pdf/${sessionId}/${formId}`, { headers: { Authorization: `Bearer ${token}` } });
      if (res.status === 403) { const d = await res.json().catch(() => ({})); if (d.payment_locked) { setError("Account payment overdue."); return; } if (d.upgrade_required) { onShowUpgrade(); return; } setError(d.message || "Download blocked"); return; }
      if (!res.ok) { setError("Download failed"); return; }
      const pkgStatus = res.headers.get("X-Package-Status") || ""; const pkgMsg = res.headers.get("X-Package-Message") || "";
      const blob = await res.blob(); const url = URL.createObjectURL(blob);
      const a = document.createElement("a"); a.href = url; a.download = `${formId}_Package.zip`;
      document.body.appendChild(a); a.click(); document.body.removeChild(a); URL.revokeObjectURL(url);
      await refreshUser();
      if (pkgStatus) { setPkgStatusMsg(pkgMsg); setPkgStatusType(pkgStatus); setTimeout(() => setPkgStatusMsg(""), 12000); }
      setStep("success");
    } catch (err) { setError("Download failed: " + err.message); }
    finally { setLoading(false); setShowDownloadOverlay(false); }
  };

  const _doDownloadAll = async () => {
    setLoading(true); setShowDownloadOverlay(true);
    try {
      const res = await fetch(`${API_BASE}/api/download-all/${sessionId}`, { headers: { Authorization: `Bearer ${token}` } });
      if (res.status === 403) { const d = await res.json().catch(() => ({})); if (d.payment_locked) { setError("Account payment overdue."); return; } if (d.upgrade_required) { onShowUpgrade(); return; } setError(d.message || "Download blocked"); return; }
      if (!res.ok) { setError("Download failed"); return; }
      const pkgStatus = res.headers.get("X-Package-Status") || ""; const pkgMsg = res.headers.get("X-Package-Message") || "";
      const blob = await res.blob(); const url = URL.createObjectURL(blob);
      const a = document.createElement("a"); a.href = url; a.download = "ACORD_Package_Acordly.zip";
      document.body.appendChild(a); a.click(); document.body.removeChild(a); URL.revokeObjectURL(url);
      await refreshUser();
      if (pkgStatus) { setPkgStatusMsg(pkgMsg); setPkgStatusType(pkgStatus); setTimeout(() => setPkgStatusMsg(""), 12000); }
      setStep("success");
    } catch (err) { setError("Download failed: " + err.message); }
    finally { setLoading(false); setShowDownloadOverlay(false); }
  };

  const refreshUser = async () => {
    const res = await fetch(`${API_BASE}/api/auth/me`, { headers: { Authorization: `Bearer ${token}` } });
    if (res.ok) { const data = await res.json(); onUserUpdate(data); }
  };

  const handleUpload = async () => {
    if (!files.length) { setError("Select at least one file"); return; }
    setLoading(true); setError(null); setShowUploadOverlay(true);
    const fd = new FormData(); files.forEach(f => fd.append("files", f));
    try {
      const res = await fetch(`${API_BASE}/api/upload-declaration`, { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: fd });
      const data = await res.json();
      if (res.status === 401) { setError("Session expired. Please sign in again."); setTimeout(() => { localStorage.removeItem("acordly_token"); window.location.reload(); }, 2000); return; }
      if (res.status === 403) { const msg = data.detail || data.message || "Access blocked."; if (msg.includes("suspended")) setError("Your account is suspended."); else if (msg.includes("archived")) setError("Account archived. Contact support."); else if (msg.includes("soft_locked") || msg.includes("locked")) setError("Account Disabled — please update billing."); else setError(msg); return; }
      if (!data.success) { if (data.gate === "tier1_fail") { setHardStops(data.missing_fields || []); setStep("stopped"); } else setError(data.message || "Upload failed"); return; }
      setSessionId(data.session_id); setDocSummary(data.doc_summary || []); setFlags(data.flags || {});
      setHardStops(data.hard_stops || []); setSoftStops(data.soft_stops || []);
      setTier2Score(data.tier2_score ?? null); setTier2Missing(data.tier2_missing || []);
      setRecommendations(data.recommendations || []); setAllAvailableForms(data.all_available_forms || []);
      setCheckedFormIds(new Set((data.recommendations || []).map(r => r.form_id)));
      setStep("recommendations");
    } catch (e) { setError("Upload failed: " + e.message); }
    finally { setLoading(false); setShowUploadOverlay(false); }
  };

  const handleGenerateAll = async () => {
    const ids = Array.from(checkedFormIds);
    if (!ids.length) { setError("Select at least one form"); return; }
    setLoading(true); setError(null); setShowGenerateOverlay(true);
    try {
      const res = await fetch(`${API_BASE}/api/select-forms-bulk`, { method: "POST", headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` }, body: JSON.stringify({ session_id: sessionId, form_ids: ids }) });
      const data = await res.json();
      if (res.status === 403) {
        const msg = data.detail || data.message || "";
        if (msg.toLowerCase().includes("lite")) { setStep("lite"); return; }
        setError(msg || "Access blocked. Please update your billing."); return;
      }
      if (!data.success) { setError("Form generation failed"); return; }
      setGeneratedForms(data.generated || {}); setCrossIssues(data.cross_issues || []);
      const firstId = data.form_ids?.[0] || null; setActiveFormId(firstId); setStep("editor");
      const readyMap = {}; (data.form_ids || []).forEach(fid => { readyMap[fid] = false; }); setPdfLoading(readyMap);
    } catch (e) { setError("Generation failed: " + e.message); }
    finally { setLoading(false); setShowGenerateOverlay(false); }
  };

  const formIdList = Object.keys(generatedForms);
  const activeIdx = formIdList.indexOf(activeFormId);
  const goNext = () => { if (activeIdx < formIdList.length - 1) setActiveFormId(formIdList[activeIdx + 1]); };
  const goPrev = () => { if (activeIdx > 0) setActiveFormId(formIdList[activeIdx - 1]); };
  const toggleForm = formId => { setCheckedFormIds(prev => { const next = new Set(prev); if (next.has(formId)) next.delete(formId); else next.add(formId); return next; }); };

  const recommendedIds = new Set(recommendations.map(r => r.form_id));
  const extraForms = allAvailableForms.filter(f => !recommendedIds.has(f.form_id));
  const activeSqs = activeFormId && generatedForms[activeFormId]?.sqs;
  const pkgsUsed = user?.packages_used || 0;
  const pkgsLimit = user?.packages_limit || 0;
  const softBuffer = user?.packages_soft_buffer || 0;
  const inOverage = user?.subscription_tier !== "free" && pkgsLimit > 0 && pkgsUsed >= pkgsLimit + softBuffer;

  const freeExhausted = user?.subscription_tier === "free" && user?.downloads_remaining === 0;

  const handleNewPackage = () => {
    if (freeExhausted) { onShowUpgrade(); return; }
    resetToUpload();
  };

  const BillingBtnSpinner = () => (
    <span style={{ width: 11, height: 11, border: "2px solid currentColor", borderTopColor: "transparent", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite", marginRight: 4 }} />
  );

  const handleDownloadOne = formId => gatedDownload(() => _doDownloadOne(formId));
  const handleDownloadAll = () => gatedDownload(() => _doDownloadAll());

  const handleLiteCoverSheet = async () => {
    setLiteCoverLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/lite/cover-sheet/${sessionId}`, { headers: { Authorization: `Bearer ${token}` } });
      if (!res.ok) { setError("Failed to generate cover sheet."); return; }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a"); a.href = url; a.download = "Acordly_SQS_Cover_Sheet.pdf";
      document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
    } catch { setError("Download failed. Please try again."); }
    finally { setLiteCoverLoading(false); }
  };

 

return (
    <div style={{
      background: "#f8fafc", width: "100%",
      ...(step === "editor"
        ? { height: "calc(100vh - 81px)", display: "flex", flexDirection: "column", overflow: "hidden" }
        : { minHeight: "calc(100vh - 81px)" })
    }}>
      <div style={{
        padding: step === "editor" ? 0 : "32px 40px",
        ...(step === "editor" && { flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", minHeight: 0 })
      }}>
        {renderContent()}
      </div>
      {showAcordModal && renderAcordLicenseModal()}
      {showARQModal && <ARQModal sessionId={sessionId} token={token} questions={arqQuestions} onClose={() => setShowARQModal(false)} onSuccess={() => { setShowARQModal(false); refreshArqData(); }} />}
    </div>
  );

  function renderAcordLicenseModal() {
    return (
      <div className="modal-overlay">
        <div className="modal-content acord-license-modal" onClick={e => e.stopPropagation()}>
          <button className="modal-close" onClick={() => { setShowAcordModal(false); setAcordLicenseChecked(false); }}>✕</button>
          <div className="modal-inner">
            <div className="acord-license-icon">⚖️</div>
            <h2 className="acord-license-title">ACORD® License Confirmation</h2>
            <div className="acord-license-body">
              <p>ACORD® Forms are copyrighted material owned by ACORD Corporation and are licensed, not sold. By continuing, you confirm that you or your organization maintain a valid ACORD license permitting the use of these forms.</p>
              <p>If your organization does not currently have an ACORD license, you can obtain one{" "}<a href="https://www.acord.org/forms-pages/forms-participation-programs/forms-end-user-licenses" target="_blank" rel="noopener noreferrer" className="acord-license-link">HERE</a>.</p>
            </div>
            <label className="acord-confirm-checkbox-label" style={{ display: "flex", alignItems: "center", gap: 10, cursor: "pointer" }}>
              <input type="checkbox" checked={acordLicenseChecked} onChange={e => setAcordLicenseChecked(e.target.checked)} className="acord-confirm-checkbox" style={{ flexShrink: 0, width: 16, height: 16, marginTop: 0, cursor: "pointer" }} />
              <span>My organization holds a valid ACORD license.</span>
            </label>
            <button className="btn btn-modal-primary btn-block" onClick={handleAcordConfirm} disabled={!acordLicenseChecked || acordModalLoading}>
              {acordModalLoading ? <span style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 8 }}><span style={{ width: 14, height: 14, border: "2px solid currentColor", borderTopColor: "transparent", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" }} />Confirming...</span> : "Confirm and Download"}
            </button>
            <div className="acord-stub-actions">
              <span className="acord-stub-label">Coming soon:</span>
              <button className="btn-stub" disabled>✉ Email</button>
              <button className="btn-stub" disabled>🔗 Share</button>
              <button className="btn-stub" disabled>📠 Fax</button>
            </div>
            <button className="btn btn-modal-secondary btn-block" onClick={() => { setShowAcordModal(false); setAcordLicenseChecked(false); }}>Cancel</button>
          </div>
        </div>
      </div>
    );
  }

  function renderContent() {
    return (
      <>
        {showUploadOverlay && <ProcessStageOverlay stages={["Reading your documents…", "Extracting facts with AI…"]} advanceAfter={3500} />}
        {showGenerateOverlay && <ProcessStageOverlay stages={[`Selecting ${checkedFormIds.size} form${checkedFormIds.size !== 1 ? "s" : ""}…`, "Generating with AI…"]} advanceAfter={3000} />}
        {showDownloadOverlay && <ProcessStageOverlay stages={["Preparing your form…", "Packaging for download…"]} advanceAfter={2000} />}

        {loading && !showUploadOverlay && !showGenerateOverlay && !showDownloadOverlay && (
          <div className="loading-overlay"><div className="loading-spinner" /><p className="loading-text">{processingStage || "Processing..."}</p></div>
        )}

        {user && user.subscription_tier === "free" && step !== "upload" && step !== "dashboard" && (
          <div className={`freemium-banner ${user.downloads_remaining === 0 ? "freemium-depleted" : ""}`}>
            {user.downloads_remaining > 0
              ? <><span className="freemium-icon">🎉</span><span className="freemium-text">{user.downloads_remaining} free download{user.downloads_remaining > 1 ? "s" : ""} remaining</span></>
              : <><span className="freemium-icon">🚀</span><span className="freemium-text">Free limit reached — upgrade to continue</span><button className="freemium-upgrade-btn" onClick={onShowUpgrade}>Upgrade Now</button></>}
          </div>
        )}

        {inOverage && (
          <div style={{ background: "#fff7ed", border: "1px solid #fed7aa", borderRadius: 8, padding: "9px 14px", fontSize: 12, color: "#92400e", marginBottom: 8, display: "flex", alignItems: "center", gap: 8 }}>
            📋 <span>You're in overage territory — each additional download will be billed on your next invoice.</span>
          </div>
        )}

        {user && user.subscription_tier !== "free" && (() => {
          const ps = user.payment_status;
          if (ps === "archived") return <div className="payment-status-banner payment-status-archived">🗄️ Account archived — <a href="mailto:support@acordly.ai">Contact support</a> to restore.</div>;
          if (ps === "suspended") return <div className="payment-status-banner payment-status-suspended">🚫 Account suspended.{" "}<button onClick={onOpenBillingPortal} disabled={billingPortalLoading} style={{ color: "inherit", fontWeight: 700, textDecoration: "underline", background: "none", border: "none", cursor: billingPortalLoading ? "wait" : "pointer", padding: 0, display: "inline-flex", alignItems: "center", gap: 4 }}>{billingPortalLoading && <BillingBtnSpinner />}Restore billing</button></div>;
          if (ps === "soft_locked") return <div className="payment-status-banner payment-status-locked">🔒 Account Disabled — Please{" "}<button onClick={onOpenBillingPortal} disabled={billingPortalLoading} style={{ color: "inherit", fontWeight: 700, textDecoration: "underline", background: "none", border: "none", cursor: billingPortalLoading ? "wait" : "pointer", padding: 0, display: "inline-flex", alignItems: "center", gap: 4 }}>{billingPortalLoading && <BillingBtnSpinner />}update your billing</button>{" "}to restore access.</div>;
          if (ps === "failed") {
            const daysFailed = user.payment_failed_at ? Math.floor((Date.now() - new Date(user.payment_failed_at).getTime()) / 86400000) : 0;
            if (daysFailed >= 7) return <div className="payment-status-banner payment-status-failed" style={{ background: "#fef2f2", borderColor: "#fca5a5", fontWeight: 700, display: "flex", alignItems: "center", gap: 8, flexWrap: "nowrap" }}>🚨 Payment still overdue — account will be restricted soon.{" "}<button onClick={onOpenBillingPortal} disabled={billingPortalLoading} style={{ color: "inherit", fontWeight: 700, textDecoration: "underline", background: "none", border: "none", cursor: billingPortalLoading ? "wait" : "pointer", padding: 0, flexShrink: 0, display: "inline-flex", alignItems: "center", gap: 4 }}>{billingPortalLoading && <BillingBtnSpinner />}Update billing now</button></div>;
            return <div className="payment-status-banner payment-status-failed">⚠️ Payment overdue —{" "}<button onClick={onOpenBillingPortal} disabled={billingPortalLoading} style={{ color: "inherit", fontWeight: 700, textDecoration: "underline", background: "none", border: "none", cursor: billingPortalLoading ? "wait" : "pointer", padding: 0, display: "inline-flex", alignItems: "center", gap: 4 }}>{billingPortalLoading && <BillingBtnSpinner />}update billing</button></div>;
          }
          return null;
        })()}

        {pkgStatusMsg && (
          <div className="overage-inline-notice" style={{ background: pkgStatusType === "overage" ? "#fefce8" : "#f0fdf4", borderColor: pkgStatusType === "overage" ? "#fde047" : "#86efac", color: pkgStatusType === "overage" ? "#713f12" : "#14532d" }}>
            <span>{pkgStatusType === "overage" ? "💳" : "📦"}</span>
            <span>{pkgStatusMsg}{" "}<button onClick={() => setPkgStatusMsg("")} style={{ background: "none", border: "none", cursor: "pointer", color: "inherit", fontWeight: 700, fontSize: 12, textDecoration: "underline" }}>Dismiss</button></span>
          </div>
        )}

        {error && (
          <div className="alert alert-error">
            <span>⚠️ {error}</span>
            <button className="alert-close" onClick={() => setError(null)}>✕</button>
          </div>
        )}

        {step === "dashboard" && <DashboardStep token={token} onResume={handleResumeSession} onNewPackage={handleNewPackage} />}

        {step === "lite" && (() => {
          const sqs = liteSqsData?.sqs;
          const gradeColor = g => ({ A: "#10b981", B: "#22c55e", C: "#f59e0b", D: "#f97316", F: "#ef4444" }[g] || "#94a3b8");
          return (
            <div style={{ maxWidth: 720, margin: "0 auto" }}>
              <div style={{ marginBottom: 24 }}>
                <div style={{ fontSize: 22, fontWeight: 800, color: "#0f172a", marginBottom: 4 }}>Your Lite Analysis</div>
                <div style={{ fontSize: 13, color: "#64748b" }}>Form generation is not included in the Lite plan. Use the tools below to complete your workflow.</div>
              </div>

              {/* SQS Card */}
              <div style={{ background: "#fff", border: "1px solid #e2e8f0", borderRadius: 12, padding: "20px 24px", marginBottom: 16 }}>
                <div style={{ fontSize: 11, fontWeight: 700, color: "#94a3b8", letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: 12 }}>SQS Analysis</div>
                {!sqs ? (
                  <div style={{ display: "flex", alignItems: "center", gap: 8, color: "#94a3b8", fontSize: 13 }}>
                    <span style={{ width: 14, height: 14, border: "2px solid #cbd5e1", borderTopColor: "#4f7cff", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" }} />
                    Analyzing submission…
                  </div>
                ) : (
                  <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
                    <div style={{ width: 64, height: 64, borderRadius: "50%", background: gradeColor(sqs.grade), display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                      <span style={{ fontSize: 22, fontWeight: 800, color: "#fff", lineHeight: 1 }}>{sqs.sqs_score ?? "—"}</span>
                      <span style={{ fontSize: 11, fontWeight: 700, color: "rgba(255,255,255,0.85)" }}>{sqs.grade}</span>
                    </div>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 14, fontWeight: 700, color: "#0f172a", marginBottom: 2 }}>{sqs.tier} — {({ auto_quote: "Auto-Route to Quoting", review: "Light Review", full_review: "Full Underwriter Review", hold: "Hold — Remediation Required" })[sqs.routing_decision] || sqs.routing_decision}</div>
                      {liteSqsData.soft_stops?.length > 0 && (
                        <div style={{ marginTop: 8 }}>
                          <div style={{ fontSize: 11, fontWeight: 700, color: "#b45309", marginBottom: 4 }}>⚠️ Warnings</div>
                          {liteSqsData.soft_stops.map((s, i) => <div key={i} style={{ fontSize: 12, color: "#64748b", padding: "1px 0" }}>• {s}</div>)}
                        </div>
                      )}
                      {liteSqsData.hard_stops?.length > 0 && (
                        <div style={{ marginTop: 8 }}>
                          <div style={{ fontSize: 11, fontWeight: 700, color: "#991b1b", marginBottom: 4 }}>🚫 Hard Stops</div>
                          {liteSqsData.hard_stops.map((s, i) => <div key={i} style={{ fontSize: 12, color: "#64748b", padding: "1px 0" }}>• {s}</div>)}
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </div>

              {/* Action Cards */}
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 20 }}>
                <div style={{ background: "#fff", border: "1px solid #e2e8f0", borderRadius: 12, padding: "20px 20px" }}>
                  <div style={{ fontSize: 18, marginBottom: 8 }}>📧</div>
                  <div style={{ fontSize: 14, fontWeight: 700, color: "#0f172a", marginBottom: 6 }}>Client Questionnaire</div>
                  <div style={{ fontSize: 12, color: "#64748b", marginBottom: 14 }}>Generate and send a tailored questionnaire to your client to fill in missing information.</div>
                  <button
                    onClick={handleOpenARQ}
                    disabled={!liteSqsData || arqLoadingQ}
                    title={!liteSqsData ? "Waiting for analysis to complete…" : ""}
                    style={{ width: "100%", padding: "9px 14px", borderRadius: 8, border: "1px solid #e6007a", background: "#e6007a", color: "#fff", fontSize: 13, fontWeight: 700, cursor: (!liteSqsData || arqLoadingQ) ? "not-allowed" : "pointer", fontFamily: "inherit", display: "flex", alignItems: "center", justifyContent: "center", gap: 6, opacity: (!liteSqsData || arqLoadingQ) ? 0.45 : 1 }}>
                    {arqLoadingQ ? <><span style={{ width: 11, height: 11, border: "2px solid #fff", borderTopColor: "transparent", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" }} /> Loading…</> : "Send to Client"}
                  </button>
                  <ARQStatusPanel arqSessions={arqSessions} token={token} onRefresh={refreshArqData} />
                </div>

                <div style={{ background: "#fff", border: "1px solid #e2e8f0", borderRadius: 12, padding: "20px 20px" }}>
                  <div style={{ fontSize: 18, marginBottom: 8 }}>📄</div>
                  <div style={{ fontSize: 14, fontWeight: 700, color: "#0f172a", marginBottom: 6 }}>Summary Cover Sheet</div>
                  <div style={{ fontSize: 12, color: "#64748b", marginBottom: 14 }}>Download your AI-generated SQS summary cover page for use with any platform.</div>
                  <button
                    onClick={handleLiteCoverSheet}
                    disabled={!liteSqsData || liteCoverLoading}
                    title={!liteSqsData ? "Waiting for analysis to complete…" : ""}
                    style={{ width: "100%", padding: "9px 14px", borderRadius: 8, border: "1px solid #0f172a", background: "#0f172a", color: "#fff", fontSize: 13, fontWeight: 700, cursor: (!liteSqsData || liteCoverLoading) ? "not-allowed" : "pointer", fontFamily: "inherit", display: "flex", alignItems: "center", justifyContent: "center", gap: 6, opacity: (!liteSqsData || liteCoverLoading) ? 0.45 : 1 }}>
                    {liteCoverLoading ? <><span style={{ width: 11, height: 11, border: "2px solid #fff", borderTopColor: "transparent", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" }} /> Generating…</> : "Download Cover Sheet"}
                  </button>
                </div>
              </div>

              <div style={{ textAlign: "center" }}>
                <button onClick={() => { setStep("upload"); setSessionId(null); setFiles([]); setLiteSqsData(null); setArqSessions([]); setArqQuestions([]); setClientFilledFields([]); }}
                  style={{ background: "none", border: "1px solid #e2e8f0", borderRadius: 8, padding: "8px 20px", fontSize: 13, color: "#64748b", cursor: "pointer", fontFamily: "inherit" }}>
                  ← Upload a new package
                </button>
                <div style={{ marginTop: 10, fontSize: 12, color: "#94a3b8" }}>
                  Want full form generation?{" "}
                  <button onClick={onShowUpgrade} style={{ background: "none", border: "none", color: "#e6007a", fontWeight: 700, cursor: "pointer", padding: 0, fontSize: 12, fontFamily: "inherit" }}>Upgrade your plan →</button>
                </div>
              </div>
            </div>
          );
        })()}

        {step === "upload" && (() => {
          if (freeExhausted) {
            return (
              <div style={{ maxWidth: 560, margin: "0 auto", textAlign: "center", padding: "60px 24px" }}>
                <div style={{ width: 72, height: 72, borderRadius: 20, background: "rgba(230,0,122,0.08)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 32, margin: "0 auto 20px" }}>🚀</div>
                <h2 style={{ fontSize: 26, fontWeight: 700, color: "#0f172a", marginBottom: 10 }}>Free Limit Reached</h2>
                <p style={{ fontSize: 15, color: "#64748b", marginBottom: 28, lineHeight: 1.6 }}>You've used all your free downloads. Upgrade to keep generating ACORD packages.</p>
                <button onClick={onShowUpgrade}
                  style={{ padding: "13px 36px", background: "#e6007a", color: "#fff", border: "none", borderRadius: 10, fontSize: 15, fontWeight: 700, cursor: "pointer", boxShadow: "0 4px 14px rgba(230,0,122,0.3)" }}
                  onMouseEnter={e => { e.currentTarget.style.background = "#c00066"; e.currentTarget.style.transform = "translateY(-1px)"; }}
                  onMouseLeave={e => { e.currentTarget.style.background = "#e6007a"; e.currentTarget.style.transform = "none"; }}>
                  Upgrade Now
                </button>
                <div style={{ marginTop: 16 }}>
                  <button onClick={goToDashboard} style={{ background: "none", border: "none", color: "#94a3b8", fontSize: 13, cursor: "pointer", textDecoration: "underline" }}>Back to Dashboard</button>
                </div>
              </div>
            );
          }
          const ps = user?.payment_status;
          const uploadBlocked = ps === "soft_locked" || ps === "suspended" || ps === "archived";
          const blockMsg = ps === "archived" ? "Account archived — contact support to restore." : ps === "suspended" ? "Account suspended — restore billing to continue." : ps === "soft_locked" ? "Account Disabled — please update your billing." : null;
          return (
            <div style={{ maxWidth: 560, margin: "0 auto" }}>

              <div style={{ textAlign: "center", marginBottom: 32 }}>
                <div style={{ fontSize: 11, fontWeight: 700, color: "#e6007a", letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: 8 }}>New Submission</div>
                <h2 style={{ fontSize: 28, fontWeight: 700, color: "#0f172a", marginBottom: 8 }}>Upload Documents</h2>
                <p style={{ fontSize: 14, color: "#64748b" }}>Dec pages, loss runs, schedules, quotes — PDFs, images, or ZIP archives</p>
              </div>
              {uploadBlocked && <div style={{ background: "#fef2f2", border: "1px solid #fecaca", borderRadius: 10, padding: "12px 16px", marginBottom: 20, fontSize: 13, color: "#dc2626", textAlign: "center" }}>{blockMsg}</div>}
              <div ref={dropRef}
                style={{ textAlign: "center", padding: dragging ? "52px 20px" : "48px 20px", border: `2px dashed ${dragging ? "#e6007a" : "#d1d5db"}`, borderRadius: 16, background: dragging ? "rgba(230,0,122,0.04)" : "#fafafa", transition: "all 0.2s", transform: dragging ? "scale(1.01)" : "none" }}>
                <div style={{ fontSize: 40, marginBottom: 14, opacity: 0.7 }}>📁</div>
                <input type="file" id="file-upload" accept=".pdf,.zip,.jpg,.jpeg,.png,.bmp,.tiff,.webp,application/pdf,application/zip,image/*" multiple disabled={uploadBlocked} onChange={e => setFiles(prev => [...prev, ...Array.from(e.target.files)])} style={{ display: "none" }} />
                <label htmlFor="file-upload" style={{ display: "block", fontSize: 15, color: "#475569", cursor: uploadBlocked ? "not-allowed" : "pointer" }}>
                  Drag & drop or <span style={{ color: "#e6007a", textDecoration: "underline", fontWeight: 600 }}>browse files</span>
                </label>
                <p style={{ fontSize: 12, color: "#94a3b8", marginTop: 6 }}>PDFs, Images (JPG, PNG, BMP, TIFF) and ZIP archives</p>
              </div>
              {files.length > 0 && (
                <div style={{ display: "flex", flexDirection: "column", gap: 6, margin: "16px 0", maxHeight: 180, overflowY: "auto" }}>
                  {files.map((f, i) => (
                    <div key={i} style={{ display: "flex", alignItems: "center", gap: 10, padding: "9px 14px", background: "rgba(230,0,122,0.04)", border: "1px solid rgba(230,0,122,0.15)", borderRadius: 8, fontSize: 13 }}>
                      <span style={{ fontSize: 15, flexShrink: 0 }}>{f.name.endsWith(".zip") ? "📦" : f.type?.startsWith("image/") ? "🖼️" : "📄"}</span>
                      <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "#1e293b" }}>{f.name}</span>
                      <button onClick={() => setFiles(prev => prev.filter((_, j) => j !== i))} style={{ background: "none", border: "none", cursor: "pointer", color: "#94a3b8", fontSize: 15, padding: "0 2px" }}
                        onMouseEnter={e => e.currentTarget.style.color = "#e6007a"}
                        onMouseLeave={e => e.currentTarget.style.color = "#94a3b8"}>✕</button>
                    </div>
                  ))}
                </div>
              )}
              <button onClick={handleUpload} disabled={!files.length || loading || uploadBlocked}
                style={{ width: "100%", marginTop: 16, padding: "13px 0", borderRadius: 10, border: "none", background: files.length && !loading && !uploadBlocked ? "#e6007a" : "#e2e8f0", color: files.length && !loading && !uploadBlocked ? "#fff" : "#94a3b8", fontSize: 15, fontWeight: 700, cursor: files.length && !loading && !uploadBlocked ? "pointer" : "not-allowed", display: "flex", alignItems: "center", justifyContent: "center", gap: 8, boxShadow: files.length && !loading && !uploadBlocked ? "0 4px 14px rgba(230,0,122,0.3)" : "none" }}>
                <span style={{ fontSize: 16 }}>🚀</span>
                {loading ? "Analyzing..." : `Analyze ${files.length > 1 ? files.length + " Files" : "File"}`}
              </button>
            </div>
          );
        })()}

        {step === "stopped" && (
          <div className="modal-step">
            <div className="stop-banner stop-hard">
              <div className="stop-icon">🚫</div>
              <h2 className="stop-title">Submission Blocked — Minimum Fields Missing</h2>
              <p className="stop-subtitle">ACORD 125 cannot be generated. Missing:</p>
            </div>
            <div className="stop-fields">{hardStops.map((f, i) => <div key={i} className="stop-field-item"><span className="stop-field-icon">✗</span><span>{f}</span></div>)}</div>
            <p className="stop-advice">Upload documents that include these fields, then try again.</p>
            <button className="btn btn-modal-primary" onClick={resetToUpload}>← Upload New Documents</button>
          </div>
        )}

        {step === "recommendations" && (
          <div className="modal-step modal-step-wide">
            <div className="step-header">
              <h2 className="step-title">Select Forms to Generate</h2>
              <p className="step-subtitle">All recommended forms are pre-selected. Uncheck any you don't need, then generate all at once.</p>
            </div>
            <div className="doc-summary">
              <div className="doc-summary-title">📂 Documents Processed</div>
              <div className="doc-chips">
                {docSummary.map((d, i) => (
                  <div key={i} className={`doc-chip ${d.is_primary ? "doc-primary" : ""}`}>
                    <span className="doc-type-badge">{d.doc_type.replace(/_/g, " ")}</span>
                    <span className="doc-filename">{d.filename}</span>
                    {d.is_primary && <span className="doc-primary-tag">Primary</span>}
                  </div>
                ))}
              </div>
            </div>
            {hardStops.length > 0 && <div className="stops-banner stops-hard"><div className="stops-title">🚫 Hard Stops — Must Fix Before Submission</div>{hardStops.map((s, i) => <div key={i} className="stop-item stop-item-hard">✗ {s}</div>)}</div>}
            {softStops.length > 0 && <div className="stops-banner stops-soft"><div className="stops-title">⚠️ Warnings — Will Cap Your SQS Score</div>{softStops.map((s, i) => <div key={i} className="stop-item stop-item-soft">⚠ {s}</div>)}</div>}
            {tier2Score !== null && (
              <div className="tier2-bar">
                <div className="tier2-header"><span className="tier2-label">Underwriting Readiness</span><span className="tier2-score" style={{ color: barColor(tier2Score) }}>{tier2Score}%</span></div>
                <div className="metric-bar"><div className="metric-fill" style={{ width: `${tier2Score}%`, background: barColor(tier2Score) }} /></div>
                {tier2Missing.length > 0 && <div className="tier2-missing">Missing: {tier2Missing.join(" · ")}</div>}
              </div>
            )}
            <div className="form-selection-list">
              <div className="form-selection-header"><span className="form-selection-title">Recommended Forms</span><span className="form-selection-hint">{checkedFormIds.size} selected</span></div>
              {recommendations.map((rec, i) => (
                <div key={rec.form_id} className={`form-select-row ${checkedFormIds.has(rec.form_id) ? "form-row-checked" : ""}`}>
                  <label className="form-select-checkbox-label">
                    <input type="checkbox" checked={checkedFormIds.has(rec.form_id)} onChange={() => toggleForm(rec.form_id)} className="form-select-checkbox" />
                    <div className="form-select-info">
                      <div className="form-select-name"><span className="rec-rank">#{i + 1}</span>{rec.form_name}</div>
                      <div className="form-select-meta"><span className="confidence-badge">Match {((rec.confidence || 0) * 100).toFixed(0)}%</span><span className="form-select-reason">{rec.reason}</span></div>
                    </div>
                  </label>
                  <button className="btn-icon-only" onClick={() => toggleForm(rec.form_id)}>{checkedFormIds.has(rec.form_id) ? "✓" : "+"}</button>
                </div>
              ))}
            </div>
            {extraForms.length > 0 && (
              <div className="add-forms-section">
                <button className="btn btn-modal-secondary btn-small" onClick={() => setShowAddForms(v => !v)}>
                  {showAddForms ? "▲ Hide" : "▼ Add more ACORD forms"} ({extraForms.length} available)
                </button>
                {showAddForms && (
                  <div className="extra-forms-list">
                    {extraForms.map(f => (
                      <div key={f.form_id} className={`form-select-row ${checkedFormIds.has(f.form_id) ? "form-row-checked" : ""}`}>
                        <label className="form-select-checkbox-label">
                          <input type="checkbox" checked={checkedFormIds.has(f.form_id)} onChange={() => toggleForm(f.form_id)} className="form-select-checkbox" />
                          <div className="form-select-info"><div className="form-select-name">{f.form_name}</div>{f.description && <div className="form-select-reason">{f.description}</div>}</div>
                        </label>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
            <button className="btn btn-modal-primary btn-block btn-large" onClick={handleGenerateAll} disabled={loading || checkedFormIds.size === 0}>
              <span className="btn-icon">⚡</span>{loading ? "Generating..." : `Generate ${checkedFormIds.size} Form${checkedFormIds.size !== 1 ? "s" : ""} Now`}
            </button>
          </div>
        )}

        {step === "editor" && (
          <div className="editor-layout editor-layout-fullpage">
          
          <div className="editor-sidebar" style={{ background: "#fff", borderRight: "1px solid #e2e8f0", padding: 0, gap: 0 }}>

              {/* Form Navigator */}
              <div style={{ padding: "14px 14px 12px" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
                  <span style={{ fontSize: 10, fontWeight: 700, color: "#94a3b8", letterSpacing: "0.06em", textTransform: "uppercase" }}>Generated Forms</span>
                  <span style={{ fontSize: 11, fontWeight: 700, color: "#e6007a", background: "rgba(230,0,122,0.08)", padding: "1px 7px", borderRadius: 20 }}>{formIdList.length}</span>
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 2, maxHeight: 130, overflowY: "auto" }}>
                  {formIdList.map(fid => {
                    const fd = generatedForms[fid]; const sq = fd?.sqs;
                    const isActive = activeFormId === fid;
                    return (
                      <div key={fid} onClick={() => setActiveFormId(fid)}
                        style={{ padding: "7px 9px", borderRadius: 7, cursor: "pointer", border: `1px solid ${isActive ? "#e6007a" : "transparent"}`, background: isActive ? "rgba(230,0,122,0.05)" : "transparent", transition: "all 0.15s" }}
                        onMouseEnter={e => { if (!isActive) e.currentTarget.style.background = "#f8fafc"; }}
                        onMouseLeave={e => { if (!isActive) e.currentTarget.style.background = "transparent"; }}>
                        <div style={{ fontSize: 12, fontWeight: 600, color: isActive ? "#e6007a" : "#1e293b" }}>
                          {fd?.form_name || fid}
                          {signedForms.has(fid) && <span style={{ color: "#10b981" }}> ✍</span>}
                          {pdfLoading[fid] ? <span style={{ color: "#f59e0b" }}> ⏳</span> : <span style={{ color: "#10b981" }}> ✓</span>}
                        </div>
                        {sq && <div style={{ display: "flex", gap: 6, marginTop: 2 }}><span style={{ fontSize: 10, fontWeight: 700, color: gradeColor(sq.grade) }}>{sq.sqs_score} {sq.grade}</span><span style={{ fontSize: 10, color: "#94a3b8" }}>{sq.tier}</span></div>}
                      </div>
                    );
                  })}
                </div>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 10, paddingTop: 8, borderTop: "1px solid #f1f5f9" }}>
                  <button onClick={goPrev} disabled={activeIdx <= 0} style={{ padding: "4px 10px", borderRadius: 6, border: "1px solid #e2e8f0", background: "#f8fafc", fontSize: 12, fontWeight: 600, color: activeIdx <= 0 ? "#cbd5e1" : "#475569", cursor: activeIdx <= 0 ? "not-allowed" : "pointer" }}>← Prev</button>
                  <span style={{ fontSize: 11, color: "#94a3b8" }}>{activeIdx + 1} / {formIdList.length}</span>
                  <button onClick={goNext} disabled={activeIdx >= formIdList.length - 1} style={{ padding: "4px 10px", borderRadius: 6, border: "1px solid #e2e8f0", background: "#f8fafc", fontSize: 12, fontWeight: 600, color: activeIdx >= formIdList.length - 1 ? "#cbd5e1" : "#475569", cursor: activeIdx >= formIdList.length - 1 ? "not-allowed" : "pointer" }}>Next →</button>
                </div>
              </div>

              {/* SQS — unified hero block */}
              {activeSqs && (
                <>
                  <div style={{ height: 1, background: "#f1f5f9", margin: "0 14px" }} />
                  <div style={{ padding: "14px 14px 12px" }}>
                    {/* Hero row: score + grade + tier + routing all in one block */}
                    <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
                      <div style={{ width: 36, height: 36, borderRadius: "50%", background: gradeColor(activeSqs.grade), display: "flex", alignItems: "center", justifyContent: "center", fontSize: 14, fontWeight: 800, color: "#fff", flexShrink: 0 }}>{activeSqs.grade}</div>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ display: "flex", alignItems: "baseline", gap: 4 }}>
                          <span style={{ fontSize: 28, fontWeight: 800, lineHeight: 1, color: gradeColor(activeSqs.grade) }}>{activeSqs.sqs_score}</span>
                          <span style={{ fontSize: 11, color: "#94a3b8" }}>/100</span>
                          <span style={{ fontSize: 10, fontWeight: 700, padding: "2px 7px", borderRadius: 20, color: "#fff", marginLeft: 4, background: { green: "#10b981", yellow: "#f59e0b", orange: "#f97316", red: "#ef4444" }[activeSqs.tier_color] || "#94a3b8" }}>{activeSqs.tier}</span>
                        </div>
                        <div style={{ fontSize: 10, color: "#94a3b8", marginTop: 1, textTransform: "uppercase", letterSpacing: "0.04em", fontWeight: 600 }}>SQS Score</div>
                      </div>
                    </div>
                    {activeSqs.routing_decision && (
                      <div style={{ padding: "5px 9px", borderRadius: 7, fontSize: 11, fontWeight: 700, textAlign: "center", marginBottom: 12, background: { auto_quote: "#dcfce7", review: "#fef9c3", full_review: "#ffedd5", hold: "#fee2e2" }[activeSqs.routing_decision] || "#f1f5f9", color: { auto_quote: "#166534", review: "#854d0e", full_review: "#9a3412", hold: "#991b1b" }[activeSqs.routing_decision] || "#374151", border: `1px solid ${{ auto_quote: "#86efac", review: "#fde047", full_review: "#fdba74", hold: "#fca5a5" }[activeSqs.routing_decision] || "#e2e8f0"}` }}>
                        {{ auto_quote: "✅ Auto-Route to Quoting", review: "🔍 Light Review", full_review: "📋 Full Underwriter Review", hold: "🚫 Hold — Remediation Required" }[activeSqs.routing_decision]}
                      </div>
                    )}
                    <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: activeSqs.risk_drivers?.length || activeSqs.issues?.length || activeSqs.recommendations?.length ? 10 : 0 }}>
                      {Object.entries(activeSqs.breakdown || {}).map(([key, val]) => (
                        <div key={key}>
                          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, marginBottom: 3 }}>
                            <span style={{ color: "#64748b" }}>{SQS_LABELS[key] || key} <span style={{ color: "#e2e8f0" }}>({SQS_WEIGHTS[key] || 0}%)</span></span>
                            <span style={{ fontWeight: 700, color: barColor(val) }}>{val}%</span>
                          </div>
                          <div style={{ height: 5, background: "#f1f5f9", borderRadius: 3, overflow: "hidden" }}>
                            <div style={{ height: "100%", width: `${val}%`, background: barColor(val), borderRadius: 3, transition: "width 0.6s ease" }} />
                          </div>
                        </div>
                      ))}
                    </div>
                    {activeSqs.risk_drivers?.length > 0 && (
                      <div style={{ background: "#fafafa", borderRadius: 7, padding: "8px 10px", marginBottom: 8, border: "1px solid #f1f5f9" }}>
                        <div style={{ fontSize: 10, fontWeight: 700, color: "#94a3b8", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 6 }}>Top Risk Drivers</div>
                        {activeSqs.risk_drivers.map((d, i) => (
                          <div key={i} style={{ display: "flex", alignItems: "center", gap: 6, padding: "3px 0", borderBottom: i < activeSqs.risk_drivers.length - 1 ? "1px solid #f1f5f9" : "none" }}>
                            <span style={{ fontSize: 10, fontWeight: 700, color: "#e6007a", width: 16 }}>#{i + 1}</span>
                            <span style={{ flex: 1, fontSize: 11, color: "#374151" }}>{d.component}</span>
                            <span style={{ fontSize: 11, fontWeight: 700, color: barColor(d.score) }}>{d.score}%</span>
                          </div>
                        ))}
                      </div>
                    )}
                    {activeSqs.issues?.length > 0 && <div style={{ background: "rgba(245,158,11,0.06)", border: "1px solid rgba(245,158,11,0.2)", borderRadius: 7, padding: "7px 10px", marginBottom: 6 }}><div style={{ fontSize: 10, fontWeight: 700, color: "#b45309", marginBottom: 3 }}>⚠️ Issues</div>{activeSqs.issues.map((s, i) => <div key={i} style={{ fontSize: 11, color: "#64748b", padding: "1px 0" }}>• {s}</div>)}</div>}
                    {activeSqs.recommendations?.length > 0 && <div style={{ background: "rgba(16,185,129,0.06)", border: "1px solid rgba(16,185,129,0.2)", borderRadius: 7, padding: "7px 10px" }}><div style={{ fontSize: 10, fontWeight: 700, color: "#059669", marginBottom: 3 }}>💡 Remediation</div>{activeSqs.recommendations.map((s, i) => <div key={i} style={{ fontSize: 11, color: "#64748b", padding: "1px 0" }}>• {s}</div>)}</div>}
                  </div>
                </>
              )}

              {/* Cross issues */}
              {crossIssues.length > 0 && (
                <>
                  <div style={{ height: 1, background: "#f1f5f9", margin: "0 14px" }} />
                  <div style={{ padding: "12px 14px" }}>
                    <div style={{ fontSize: 10, fontWeight: 700, color: "#94a3b8", letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: 8 }}>Cross-Form Validation</div>
                    {crossIssues.map((iss, i) => <div key={i} style={{ fontSize: 12, padding: "3px 0", color: iss.type === "hard_stop" ? "#dc2626" : "#b45309" }}>{iss.type === "hard_stop" ? "🚫" : "⚠️"} {iss.message}</div>)}
                  </div>
                </>
              )}

              {/* Actions */}
              <div style={{ height: 1, background: "#f1f5f9", margin: "0 14px" }} />
              <div style={{ padding: "12px 14px 16px", display: "flex", flexDirection: "column", gap: 8 }}>
                <button onClick={handleOpenARQ} disabled={arqLoadingQ}
                  style={{ width: "100%", padding: "9px 14px", borderRadius: 8, border: "1px solid #e6007a", background: "#e6007a", color: "#fff", fontSize: 13, fontWeight: 700, cursor: arqLoadingQ ? "wait" : "pointer", fontFamily: "inherit", display: "flex", alignItems: "center", justifyContent: "center", gap: 6, opacity: arqLoadingQ ? 0.7 : 1 }}
                  onMouseEnter={e => { if (!arqLoadingQ) { e.currentTarget.style.background = "#c00066"; e.currentTarget.style.border = "1px solid #c00066"; } }}
                  onMouseLeave={e => { e.currentTarget.style.background = "#e6007a"; e.currentTarget.style.border = "1px solid #e6007a"; }}>
                  {arqLoadingQ ? <><span style={{ width: 11, height: 11, border: "2px solid #4f7cff", borderTopColor: "transparent", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" }} /> Loading…</> : <>📧 Send to Client {arqNotifCount > 0 && <span style={{ background: "#fff", color: "#e6007a", borderRadius: 10, fontSize: 10, padding: "1px 6px", fontWeight: 700 }}>{arqNotifCount}</span>}</>}
                </button>
                <ARQStatusPanel arqSessions={arqSessions} token={token} onRefresh={refreshArqData} />
                <button onClick={() => handleSendToEpic(activeFormId)} disabled={!activeFormId || epicLoading}
                  style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 6, width: "100%", padding: "9px 14px", borderRadius: 8, border: epicSuccess ? "1px solid #22c55e" : "1px solid #e6007a", background: epicSuccess ? "rgba(34,197,94,0.08)" : "#e6007a", color: epicSuccess ? "#22c55e" : "#fff", fontSize: 13, fontWeight: 700, cursor: epicLoading ? "wait" : "pointer", fontFamily: "inherit", transition: "all 0.18s", opacity: (!activeFormId || epicLoading) ? 0.55 : 1 }}
                  onMouseEnter={e => { if (activeFormId && !epicLoading && !epicSuccess) { e.currentTarget.style.background = "#c00066"; e.currentTarget.style.border = "1px solid #c00066"; } }}
                  onMouseLeave={e => { if (!epicSuccess) { e.currentTarget.style.background = "#e6007a"; e.currentTarget.style.border = "1px solid #e6007a"; } }}>
                  {epicSuccess ? "✅ Sent to EPIC" : epicLoading ? <><span style={{ width: 11, height: 11, border: "2px solid currentColor", borderTopColor: "transparent", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" }} /> Sending…</> : "🔗 Send to EPIC"}
                </button>
                <button onClick={() => handleDownloadOne(activeFormId)} disabled={!activeFormId}
                  style={{ width: "100%", padding: "9px 14px", borderRadius: 8, border: "1px solid #e6007a", background: "#e6007a", color: "#fff", fontSize: 13, fontWeight: 700, cursor: activeFormId ? "pointer" : "not-allowed", opacity: activeFormId ? 1 : 0.5, boxShadow: "0 3px 10px rgba(230,0,122,0.25)", fontFamily: "inherit" }}
                  onMouseEnter={e => { if (activeFormId) e.currentTarget.style.background = "#c00066"; }}
                  onMouseLeave={e => { e.currentTarget.style.background = "#e6007a"; }}>
                  ⬇ Download This Form
                </button>
                {formIdList.length > 1 && (
                  <button onClick={handleDownloadAll}
                    style={{ width: "100%", padding: "9px 14px", borderRadius: 8, border: "1px solid #e6007a", background: "#e6007a", color: "#fff", fontSize: 13, fontWeight: 700, cursor: "pointer", boxShadow: "0 3px 10px rgba(230,0,122,0.25)", fontFamily: "inherit" }}
                    onMouseEnter={e => { e.currentTarget.style.background = "#c00066"; e.currentTarget.style.border = "1px solid #c00066"; }}
                    onMouseLeave={e => { e.currentTarget.style.background = "#e6007a"; e.currentTarget.style.border = "1px solid #e6007a"; }}>
                    📦 Download All ({formIdList.length} forms)
                  </button>
                )}
                <button onClick={goToDashboard}
                  style={{ width: "100%", padding: "9px 14px", borderRadius: 8, border: "1px solid #e6007a", background: "#e6007a", color: "#fff", fontSize: 13, fontWeight: 700, cursor: "pointer", fontFamily: "inherit", transition: "all 0.15s" }}
                  onMouseEnter={e => { e.currentTarget.style.background = "#c00066"; e.currentTarget.style.border = "1px solid #c00066"; }}
                  onMouseLeave={e => { e.currentTarget.style.background = "#e6007a"; e.currentTarget.style.border = "1px solid #e6007a"; }}>
                  ← Dashboard
                </button>
              </div>
            </div>
            
            <div className="editor-main">
              <PDFJsViewer
                key={activeFormId}
                pdfUrl={`${API_BASE}/api/get-pdf/${sessionId}/${activeFormId}?token=${token}`}
                formName={activeFormId ? (generatedForms[activeFormId]?.form_name || activeFormId) : ""}
                onFormNav={{ goPrev, goNext, activeIdx, total: formIdList.length }}
                sessionId={sessionId} formId={activeFormId} token={token}
                savedSignature={savedSignature}
                isSigned={signedForms.has(activeFormId)}
                onSignApplied={fid => setSignedForms(prev => new Set([...prev, fid]))}
                onOpenSignatureModal={onOpenSignatureModal}
                clientFilledFields={clientFilledFields}
                onRefreshFields={refreshArqData}
              />
            </div>
          </div>
        )}

        {step === "success" && (
          <div style={{ maxWidth: 480, margin: "0 auto", textAlign: "center", padding: "56px 24px" }}>
            <div style={{ width: 80, height: 80, borderRadius: "50%", background: "linear-gradient(135deg, #e6007a, #c00066)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 36, color: "#fff", margin: "0 auto 24px", boxShadow: "0 8px 28px rgba(230,0,122,0.3)", animation: "successPop 0.5s ease-out" }}>✓</div>
            <h2 style={{ fontSize: 26, fontWeight: 800, color: "#0f172a", marginBottom: 8 }}>Download Complete!</h2>
            <p style={{ fontSize: 15, color: "#64748b", marginBottom: 28, lineHeight: 1.6 }}>Your filled ACORD forms have been downloaded. You can go back to the form to make edits and re-download at any time.</p>
            {user && user.subscription_tier === "free" && (
              <div style={{ background: "rgba(230,0,122,0.05)", border: "1px solid rgba(230,0,122,0.15)", borderRadius: 10, padding: "12px 16px", marginBottom: 24, fontSize: 14, color: "#1e293b" }}>
                You have <strong style={{ color: "#e6007a" }}>{Math.max(0, user.downloads_remaining)}</strong> free download{user.downloads_remaining !== 1 ? "s" : ""} remaining
              </div>
            )}
            <div style={{ display: "flex", flexDirection: "column", gap: 10, alignItems: "center" }}>
              <button onClick={() => setStep("editor")}
                style={{ minWidth: 260, padding: "12px 0", borderRadius: 10, border: "none", background: "#e6007a", color: "#fff", fontSize: 14, fontWeight: 700, cursor: "pointer", boxShadow: "0 4px 14px rgba(230,0,122,0.3)" }}
                onMouseEnter={e => e.currentTarget.style.background = "#c00066"}
                onMouseLeave={e => e.currentTarget.style.background = "#e6007a"}>
                ← Back to Form
              </button>
              <button onClick={goToDashboard}
                style={{ minWidth: 260, padding: "11px 0", borderRadius: 10, border: "1px solid #e2e8f0", background: "#f8fafc", color: "#475569", fontSize: 14, fontWeight: 600, cursor: "pointer" }}
                onMouseEnter={e => e.currentTarget.style.background = "#f1f5f9"}
                onMouseLeave={e => e.currentTarget.style.background = "#f8fafc"}>
                ← Dashboard
              </button>
            </div>
          </div>
        )}
      </>
    );
  }
}