//AcordModal.jsx
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

const PACKAGE_PILLAR_LABELS = {
  data_integrity: "Data Integrity",
  exposure_cope:  "Exposure & COPE",
  consistency:    "Cross-Form Consistency",
  loss_history:   "Loss History",
  narrative:      "Narrative Quality",
};

const REC_TYPE_STYLE = {
  hard_stop:    { bg: "#fef2f2", border: "#fca5a5", color: "#991b1b", icon: "🚫" },
  soft_warning: { bg: "#fffbeb", border: "#fde68a", color: "#92400e", icon: "⚠️" },
  missing_field:{ bg: "#eff6ff", border: "#bfdbfe", color: "#1d4ed8", icon: "📋" },
  suggestion:   { bg: "#f0fdf4", border: "#bbf7d0", color: "#166534", icon: "💡" },
};

const FALLBACK_CHAT_REPLY = "I'm not sure about that. Please contact your agent or broker for assistance.";

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
  const [emailTouched, setEmailTouched] = useState(false);

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

  const sanitizeEmail = val => val.trim().toLowerCase().slice(0, 254);

  const selectedCount = Object.values(selectedQuestions).filter(Boolean).length;
  const isEmailValid = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(clientEmail);
  const canSend = isEmailValid && selectedCount > 0;

  const handleSend = async () => {
    if (!canSend) return;
    setEmailTouched(true);
    setSending(true); setError("");
    const selectedList = questions.filter(q => selectedQuestions[q.field_name]);
    try {
      const res = await fetch(`${API_BASE}/api/arq/send`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          client_email: sanitizeEmail(clientEmail),
          client_name: clientName.trim().slice(0, 100),
          questions: selectedList,
        }),
      });
      const data = await res.json();
      if (res.ok && data.success) onSuccess(data);
      else setError(data.detail || data.message || "Failed to send questionnaire.");
    } catch (e) { setError("Network error: " + e.message); }
    finally { setSending(false); }
  };

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(15,23,42,0.75)", backdropFilter: "blur(8px)", zIndex: 99999, display: "flex", alignItems: "center", justifyContent: "center", padding: "16px" }}>
      <div onClick={e => e.stopPropagation()} style={{ background: "#fff", borderRadius: 20, width: "100%", maxWidth: 620, maxHeight: "92vh", overflow: "hidden", display: "flex", flexDirection: "column", boxShadow: "0 32px 80px rgba(0,0,0,0.2)" }}>
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
              <input type="email" value={clientEmail}
                onChange={e => { setClientEmail(e.target.value); setEmailTouched(true); }}
                onBlur={e => { setEmailTouched(true); e.target.style.borderColor = "#e2e8f0"; }}
                onFocus={e => e.target.style.borderColor = "#e6007a"}
                placeholder="client@company.com" maxLength={254}
                style={{ width: "100%", padding: "9px 12px", border: "1px solid #e2e8f0", borderRadius: 8, fontSize: 13, outline: "none", boxSizing: "border-box" }} />
              {emailTouched && clientEmail && !isEmailValid && (
                <p style={{ fontSize: 11, color: "#ef4444", marginTop: 4 }}>Please enter a valid email address.</p>
              )}
            </div>
            <div>
              <label style={{ display: "block", fontSize: 12, fontWeight: 600, color: "#374151", marginBottom: 6 }}>First Name <span style={{ color: "#94a3b8", fontWeight: 400 }}>(optional)</span></label>
              <input type="text" value={clientName} onChange={e => setClientName(e.target.value)} placeholder="e.g. John" maxLength={100}
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
            style={{ width: "100%", padding: "12px 0", borderRadius: 10, border: "none", background: canSend && !sending ? "#e6007a" : "#e2e8f0", color: canSend && !sending ? "#fff" : "#94a3b8", fontSize: 14, fontWeight: 700, cursor: canSend && !sending ? "pointer" : "not-allowed", display: "flex", alignItems: "center", justifyContent: "center", gap: 8, minHeight: 46 }}>
            {sending ? <><span style={{ width: 14, height: 14, border: "2px solid rgba(255,255,255,0.4)", borderTopColor: "#fff", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" }} />Sending…</> : `Send ${selectedCount} Question${selectedCount !== 1 ? "s" : ""} to Client`}
          </button>
          {emailTouched && clientEmail && !isEmailValid && <p style={{ fontSize: 11, color: "#ef4444", textAlign: "center", marginTop: 8 }}>Please enter a valid email address.</p>}
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
    try { await fetch(`${API_BASE}/api/arq/remind/${arq_id}`, { method: "POST", credentials: "include" }); onRefresh(); } catch (_) {}
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

// ── Side panel recommendation row — own local state avoids shared-state race ──
function SidePanelRec({ rec, index, sqsScore, onDismiss }) {
  const [reason, setReason] = useState("");
  const isObj  = typeof rec === "object" && rec !== null;
  const msg    = isObj ? rec.message : rec;
  const impact = isObj ? rec.score_impact : null;
  const recId  = isObj ? rec.rec_id : `legacy_${index}`;
  const recType = isObj ? rec.type : "suggestion";
  const st = REC_TYPE_STYLE[recType] || REC_TYPE_STYLE.suggestion;

  const submit = () => onDismiss(rec, sqsScore, reason);
  const dismiss = () => onDismiss(rec, sqsScore, "");

  return (
    <div style={{ background: st.bg, border: `1px solid ${st.border}`, borderRadius: 8, padding: "8px 10px" }}>
      <div style={{ display: "flex", alignItems: "flex-start", gap: 7 }}>
        <span style={{ fontSize: 12, flexShrink: 0, marginTop: 1 }}>{st.icon}</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 11, color: st.color, fontWeight: 600, lineHeight: 1.4 }}>{msg}</div>
          {impact > 0 && <div style={{ fontSize: 10, color: "#10b981", fontWeight: 700, marginTop: 2 }}>+{impact} pts if fixed</div>}
        </div>
      </div>
      {isObj && (
        <div style={{ marginTop: 7, display: "flex", gap: 5, alignItems: "center" }}>
          <input
            placeholder="Add a reason (optional)…"
            value={reason}
            onChange={e => setReason(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter") submit(); }}
            style={{ flex: 1, fontSize: 10, padding: "3px 7px", border: "1px solid #e2e8f0", borderRadius: 5, outline: "none", fontFamily: "inherit", minWidth: 0 }}
          />
          {reason.trim() && (
            <button
              onMouseDown={e => { e.preventDefault(); submit(); }}
              style={{ padding: "3px 8px", borderRadius: 5, border: "1px solid #6366f1", background: "#6366f1", fontSize: 10, fontWeight: 600, color: "#fff", cursor: "pointer", whiteSpace: "nowrap" }}>
              Submit
            </button>
          )}
          <button
            onMouseDown={e => { e.preventDefault(); dismiss(); }}
            style={{ padding: "3px 8px", borderRadius: 5, border: "1px solid #e2e8f0", background: "#f8fafc", fontSize: 10, fontWeight: 600, color: "#64748b", cursor: "pointer", whiteSpace: "nowrap" }}>
            Dismiss
          </button>
        </div>
      )}
    </div>
  );
}

// ── Download Pre-flight Modal ──────────────────────────────────────────────
function DownloadPreflightModal({ openRecs, narrative, overrideReason, onOverrideChange, onProceed, onCancel, loading }) {
  const hardRecs = openRecs.filter(r => r.recommendation_type === "hard_stop");
  const softRecs = openRecs.filter(r => r.recommendation_type !== "hard_stop");
  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(15,23,42,0.75)", backdropFilter: "blur(6px)", zIndex: 99999, display: "flex", alignItems: "center", justifyContent: "center", padding: 20 }}>
      <div style={{ background: "#fff", borderRadius: 16, padding: "28px 28px 24px", maxWidth: 520, width: "100%", boxShadow: "0 24px 60px rgba(0,0,0,0.22)", display: "flex", flexDirection: "column", gap: 0, maxHeight: "88vh", overflow: "hidden" }}>
        <div style={{ flexShrink: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
            <div style={{ width: 40, height: 40, borderRadius: "50%", background: openRecs.length > 0 ? "#fef3c7" : "#f0fdf4", border: `2px solid ${openRecs.length > 0 ? "#fde68a" : "#bbf7d0"}`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 18, flexShrink: 0 }}>{openRecs.length > 0 ? "⚠️" : "✅"}</div>
            <div>
              <div style={{ fontSize: 16, fontWeight: 700, color: "#0f172a" }}>SQS Review</div>
              <div style={{ fontSize: 12, color: "#64748b" }}>{openRecs.length > 0 ? `${openRecs.length} item${openRecs.length !== 1 ? "s" : ""} flagged — review before downloading` : "All clear — review the SQS summary below"}</div>
            </div>
          </div>
        </div>
        <div style={{ flex: 1, overflowY: "auto", marginBottom: 16 }}>
          {hardRecs.length > 0 && (
            <div style={{ background: "#fef2f2", border: "1px solid #fca5a5", borderRadius: 8, padding: "10px 12px", marginBottom: 10 }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: "#991b1b", marginBottom: 6 }}>🚫 Hard Stops ({hardRecs.length})</div>
              {hardRecs.map((r, i) => (
                <div key={i} style={{ fontSize: 12, color: "#7f1d1d", padding: "2px 0" }}>• {r.message}{r.score_impact ? <span style={{ color: "#dc2626", fontWeight: 700 }}> (–{r.score_impact} pts)</span> : ""}</div>
              ))}
            </div>
          )}
          {softRecs.length > 0 && (
            <div style={{ background: "#fffbeb", border: "1px solid #fde68a", borderRadius: 8, padding: "10px 12px", marginBottom: 10 }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: "#92400e", marginBottom: 6 }}>⚠️ Open Recommendations ({softRecs.length})</div>
              {softRecs.map((r, i) => (
                <div key={i} style={{ fontSize: 12, color: "#78350f", padding: "2px 0" }}>• {r.message}{r.score_impact > 0 ? <span style={{ color: "#d97706", fontWeight: 600 }}> (+{r.score_impact} pts if fixed)</span> : ""}</div>
              ))}
            </div>
          )}
          {narrative && (
            <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: 10, padding: "16px 18px", marginTop: softRecs.length > 0 || hardRecs.length > 0 ? 10 : 0 }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: "#94a3b8", letterSpacing: "0.05em", textTransform: "uppercase", marginBottom: 10 }}>📊 SQS Analysis Summary</div>
              <p style={{ fontSize: 13, color: "#334155", lineHeight: 1.75, margin: 0 }}>{narrative.replace(/\n+/g, " ").trim()}</p>
            </div>
          )}
        </div>
        <div style={{ flexShrink: 0 }}>
          <div style={{ marginBottom: 12 }}>
            <label style={{ display: "block", fontSize: 12, fontWeight: 600, color: "#374151", marginBottom: 5 }}>
              Override Note <span style={{ color: "#94a3b8", fontWeight: 400 }}>(recommended for E&O record)</span>
            </label>
            <textarea
              value={overrideReason}
              onChange={e => onOverrideChange(e.target.value)}
              placeholder="e.g. Client acknowledged gaps and approved submission as-is"
              rows={2}
              style={{ width: "100%", padding: "8px 10px", border: "1px solid #e2e8f0", borderRadius: 8, fontSize: 12, resize: "vertical", outline: "none", fontFamily: "inherit", boxSizing: "border-box" }}
              onFocus={e => e.target.style.borderColor = "#e6007a"}
              onBlur={e => e.target.style.borderColor = "#e2e8f0"}
            />
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <button onClick={onCancel} style={{ flex: 1, padding: "9px 0", borderRadius: 8, border: "1px solid #e2e8f0", background: "#f8fafc", color: "#475569", fontSize: 13, fontWeight: 600, cursor: "pointer" }}>
              Cancel
            </button>
            <button
              onClick={onProceed}
              disabled={loading}
              style={{ flex: 2, padding: "9px 0", borderRadius: 8, border: "none", background: !loading ? "#e6007a" : "#e2e8f0", color: !loading ? "#fff" : "#94a3b8", fontSize: 13, fontWeight: 700, cursor: !loading ? "pointer" : "not-allowed", display: "flex", alignItems: "center", justifyContent: "center", gap: 6 }}>
              {loading ? <><span style={{ width: 11, height: 11, border: "2px solid rgba(255,255,255,0.5)", borderTopColor: "#fff", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" }} />Processing…</> : "Download Anyway"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Dashboard Step ─────────────────────────────────────────────────────────
function DashboardStep({ token, onResume, onNewPackage }) {
  const [sessions, setSessions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);
  const [deleteTarget, setDeleteTarget] = useState(null);

  useEffect(() => {
    fetch(`${API_BASE}/api/sessions`, { credentials: "include" })
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d?.success) setSessions(d.sessions || []); else setLoadError("Could not load your sessions. Please refresh."); })
      .catch(() => setLoadError("Network error loading sessions. Please refresh."))
      .finally(() => setLoading(false));
  }, []);

  const handleDelete = async sid => {
    setSessions(prev => prev.filter(s => s.session_id !== sid));
    setDeleteTarget(null);
    try { await fetch(`${API_BASE}/api/sessions/${sid}`, { method: "DELETE", credentials: "include" }); } catch (_) {}
  };

  const fmtDate = iso => {
    if (!iso) return "—";
    const d = new Date(iso);
    const diffDays = Math.floor((Date.now() - d) / 86400000);
    if (diffDays === 0) return "Today";
    if (diffDays === 1) return "Yesterday";
    if (diffDays < 7) return `${diffDays}d ago`;
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: diffDays > 300 ? "numeric" : undefined });
  };

  const avgSqs = sqsMap => {
    const scores = Object.values(sqsMap || {}).map(s => s?.sqs_score).filter(n => n != null);
    return scores.length ? Math.round(scores.reduce((a, b) => a + b, 0) / scores.length) : null;
  };
  const sqsColor  = v => v >= 75 ? "#10b981" : v >= 50 ? "#f59e0b" : "#ef4444";
  const sqsBg     = v => v >= 75 ? "rgba(16,185,129,0.1)" : v >= 50 ? "rgba(245,158,11,0.1)" : "rgba(239,68,68,0.1)";
  const sqsGrade  = v => v >= 90 ? "A" : v >= 75 ? "B" : v >= 60 ? "C" : v >= 50 ? "D" : "F";

  const totalForms = sessions.reduce((acc, s) => acc + (s.form_ids?.length || 0), 0);
  const allScores  = sessions.map(s => avgSqs(s.sqs)).filter(n => n != null);
  const globalAvg  = allScores.length ? Math.round(allScores.reduce((a, b) => a + b, 0) / allScores.length) : null;

  return (
    <div style={{ maxWidth: 900, margin: "0 auto", padding: "0 0 48px" }}>
      {deleteTarget && <DeleteConfirmModal onConfirm={() => handleDelete(deleteTarget)} onCancel={() => setDeleteTarget(null)} />}

      {loadError && (
        <div style={{ background: "#fef2f2", border: "1px solid #fecaca", borderRadius: 8, padding: "12px 16px", marginBottom: 20, color: "#dc2626", fontSize: 13 }}>
          ⚠️ {loadError}
        </div>
      )}

      {/* ── Header ── */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 24 }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 7, marginBottom: 8 }}>
            <div style={{ width: 7, height: 7, borderRadius: "50%", background: "#e6007a", boxShadow: "0 0 0 3px rgba(230,0,122,0.15)" }} />
            <span style={{ fontSize: 11, fontWeight: 700, color: "#e6007a", letterSpacing: "0.08em", textTransform: "uppercase" }}>Submissions</span>
          </div>
          <h2 style={{ fontSize: 28, fontWeight: 800, color: "#0f172a", margin: 0, lineHeight: 1.15, letterSpacing: "-0.02em" }}>Recent Packages</h2>
          <p style={{ fontSize: 14, color: "#64748b", marginTop: 6 }}>Pick up where you left off or start a new submission.</p>
        </div>
        <button onClick={onNewPackage}
          style={{ display: "flex", alignItems: "center", gap: 8, padding: "11px 22px", background: "linear-gradient(135deg,#e6007a,#c4006a)", color: "#fff", border: "none", borderRadius: 12, fontSize: 14, fontWeight: 700, cursor: "pointer", boxShadow: "0 4px 16px rgba(230,0,122,0.35)", whiteSpace: "nowrap", letterSpacing: "-0.01em", transition: "all 0.2s" }}
          onMouseEnter={e => { e.currentTarget.style.transform = "translateY(-2px)"; e.currentTarget.style.boxShadow = "0 8px 24px rgba(230,0,122,0.45)"; }}
          onMouseLeave={e => { e.currentTarget.style.transform = "none"; e.currentTarget.style.boxShadow = "0 4px 16px rgba(230,0,122,0.35)"; }}>
          <span style={{ fontSize: 18, lineHeight: 1 }}>+</span> New Package
        </button>
      </div>

      {/* ── Stats strip (only when sessions exist) ── */}
      {!loading && sessions.length > 0 && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10, marginBottom: 28 }}>
          {[
            { icon: "🗂️", value: sessions.length, label: "Total Packages", color: "#e6007a", bgColor: "rgba(230,0,122,0.07)" },
            { icon: globalAvg != null ? sqsGrade(globalAvg) : "—", value: globalAvg != null ? `${globalAvg}` : "—", sublabel: "/100", label: "Avg SQS Score", color: globalAvg != null ? sqsColor(globalAvg) : "#94a3b8", bgColor: globalAvg != null ? sqsBg(globalAvg) : "#f1f5f9", iconIsText: true },
            { icon: "📋", value: totalForms, label: "Forms Generated", color: "#4f7cff", bgColor: "rgba(79,124,255,0.08)" },
          ].map((stat, i) => (
            <div key={i} style={{ background: "#fff", border: "1px solid #e8edf5", borderRadius: 12, padding: "14px 16px", display: "flex", alignItems: "center", gap: 12, boxShadow: "0 1px 4px rgba(0,0,0,0.03)" }}>
              <div style={{ width: 38, height: 38, borderRadius: 10, background: stat.bgColor, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                {stat.iconIsText
                  ? <span style={{ fontSize: 15, fontWeight: 800, color: stat.color }}>{stat.icon}</span>
                  : <span style={{ fontSize: 17 }}>{stat.icon}</span>}
              </div>
              <div>
                <div style={{ fontSize: 20, fontWeight: 800, color: stat.color, lineHeight: 1 }}>
                  {stat.value}{stat.sublabel && <span style={{ fontSize: 11, fontWeight: 500, color: "#94a3b8" }}>{stat.sublabel}</span>}
                </div>
                <div style={{ fontSize: 11, color: "#94a3b8", marginTop: 3 }}>{stat.label}</div>
              </div>
            </div>
          ))}
        </div>
      )}

      {loading ? (
        /* ── Skeleton cards ── */
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {[1, 2, 3].map(i => (
            <div key={i} style={{ background: "#fff", borderRadius: 14, border: "1px solid #e8edf5", display: "flex", alignItems: "stretch", overflow: "hidden", opacity: 1 - (i - 1) * 0.22 }}>
              <div style={{ width: 4, background: "#f1f5f9" }} />
              <div style={{ flex: 1, padding: "18px 20px", display: "flex", alignItems: "center", gap: 14 }}>
                <div style={{ width: 44, height: 44, borderRadius: 12, background: "#f1f5f9", animation: "pulse 1.5s ease-in-out infinite", flexShrink: 0 }} />
                <div style={{ flex: 1 }}>
                  <div style={{ height: 13, width: `${72 - i * 8}%`, background: "#f1f5f9", borderRadius: 5, marginBottom: 9, animation: "pulse 1.5s ease-in-out infinite" }} />
                  <div style={{ height: 10, width: "40%", background: "#f1f5f9", borderRadius: 5, animation: "pulse 1.5s ease-in-out infinite" }} />
                </div>
                <div style={{ width: 52, height: 52, borderRadius: "50%", background: "#f1f5f9", animation: "pulse 1.5s ease-in-out infinite", flexShrink: 0 }} />
              </div>
            </div>
          ))}
        </div>
      ) : sessions.length === 0 ? (
        /* ── Empty state ── */
        <div style={{ textAlign: "center", padding: "56px 24px 64px", background: "#fff", borderRadius: 20, border: "1.5px dashed #e2e8f0", position: "relative", overflow: "hidden" }}>
          <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 3, background: "linear-gradient(90deg,#e6007a,#4f7cff,#10b981)", borderRadius: "20px 20px 0 0" }} />
          <div style={{ width: 72, height: 72, borderRadius: 20, background: "linear-gradient(135deg,rgba(230,0,122,0.1),rgba(79,124,255,0.1))", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 32, margin: "0 auto 20px", border: "1px solid rgba(230,0,122,0.12)" }}>📂</div>
          <p style={{ fontSize: 19, fontWeight: 800, color: "#0f172a", marginBottom: 8, letterSpacing: "-0.02em" }}>No packages yet</p>
          <p style={{ fontSize: 14, color: "#64748b", lineHeight: 1.65, maxWidth: 330, margin: "0 auto 32px" }}>Upload your first submission documents — Acordly will extract data and fill ACORD forms automatically.</p>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 6, marginBottom: 28, flexWrap: "wrap" }}>
            {[["📄", "Upload docs"], ["⚡", "AI extracts data"], ["✅", "Download forms"]].map(([icon, label], i, arr) => (
              <div key={i} style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 6, background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: 9, padding: "7px 14px" }}>
                  <span style={{ fontSize: 14 }}>{icon}</span>
                  <span style={{ fontSize: 12, fontWeight: 600, color: "#475569" }}>{label}</span>
                </div>
                {i < arr.length - 1 && <span style={{ color: "#d1d5db", fontSize: 13, fontWeight: 600 }}>→</span>}
              </div>
            ))}
          </div>
          <button onClick={onNewPackage}
            style={{ padding: "12px 30px", background: "linear-gradient(135deg,#e6007a,#c4006a)", color: "#fff", border: "none", borderRadius: 12, fontSize: 14, fontWeight: 700, cursor: "pointer", boxShadow: "0 4px 16px rgba(230,0,122,0.35)", transition: "all 0.2s" }}
            onMouseEnter={e => { e.currentTarget.style.transform = "translateY(-2px)"; e.currentTarget.style.boxShadow = "0 8px 24px rgba(230,0,122,0.45)"; }}
            onMouseLeave={e => { e.currentTarget.style.transform = "none"; e.currentTarget.style.boxShadow = "0 4px 16px rgba(230,0,122,0.35)"; }}>
            + Start First Package
          </button>
        </div>
      ) : (
        /* ── Session list ── */
        <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: "#94a3b8", letterSpacing: "0.07em", textTransform: "uppercase", marginBottom: 10, paddingLeft: 2 }}>
            {sessions.length} Package{sessions.length !== 1 ? "s" : ""}
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {sessions.map(s => {
              const avg   = avgSqs(s.sqs);
              const color = avg != null ? sqsColor(avg)  : "#94a3b8";
              const bg    = avg != null ? sqsBg(avg)     : "rgba(148,163,184,0.08)";
              const grade = avg != null ? sqsGrade(avg)  : null;
              const formCount = s.form_ids?.length || 0;
              return (
                <div key={s.session_id} className="session-card"
                  onClick={() => onResume(s.session_id)}
                  style={{ background: "#fff", border: "1px solid #e8edf5", borderRadius: 14, cursor: "pointer", display: "flex", alignItems: "stretch", transition: "all 0.18s", position: "relative", boxShadow: "0 1px 3px rgba(0,0,0,0.05)", overflow: "hidden" }}
                  onMouseEnter={e => { e.currentTarget.style.borderColor = "#e6007a"; e.currentTarget.style.boxShadow = "0 4px 24px rgba(230,0,122,0.12)"; e.currentTarget.style.transform = "translateY(-1px)"; }}
                  onMouseLeave={e => { e.currentTarget.style.borderColor = "#e8edf5"; e.currentTarget.style.boxShadow = "0 1px 3px rgba(0,0,0,0.05)"; e.currentTarget.style.transform = "none"; }}>

                  {/* Left score-coloured accent bar */}
                  <div style={{ width: 4, background: color, borderRadius: "14px 0 0 14px", flexShrink: 0, transition: "background 0.2s" }} />

                  {/* Card body */}
                  <div style={{ flex: 1, padding: "15px 18px", display: "flex", alignItems: "center", gap: 14, minWidth: 0 }}>

                    {/* Icon */}
                    <div style={{ width: 44, height: 44, borderRadius: 12, background: `linear-gradient(135deg,${color}1a,${color}09)`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 20, flexShrink: 0, border: `1px solid ${color}22` }}>
                      📄
                    </div>

                    {/* Text */}
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontWeight: 700, fontSize: 15, color: "#0f172a", marginBottom: 6, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", letterSpacing: "-0.01em" }}>
                        {s.applicant || "Unnamed Package"}
                      </div>
                      <div style={{ display: "flex", gap: 5, flexWrap: "wrap", alignItems: "center" }}>
                        {formCount > 0 && (
                          <span style={{ fontSize: 11, fontWeight: 600, color: "#4f7cff", background: "rgba(79,124,255,0.08)", border: "1px solid rgba(79,124,255,0.18)", borderRadius: 6, padding: "2px 8px" }}>
                            {formCount} form{formCount !== 1 ? "s" : ""}
                          </span>
                        )}
                        {s.form_ids?.slice(0, 4).map(fid => (
                          <span key={fid} style={{ fontSize: 11, color: "#64748b", background: "#f1f5f9", border: "1px solid #e8edf5", borderRadius: 5, padding: "2px 7px", fontWeight: 500 }}>{fid.replace(/_/g, " ")}</span>
                        ))}
                        {(s.form_ids?.length || 0) > 4 && <span style={{ fontSize: 11, color: "#94a3b8" }}>+{s.form_ids.length - 4}</span>}
                        {s.lines?.length > 0 && (
                          <span style={{ fontSize: 11, color: "#94a3b8" }}>· {s.lines.slice(0, 2).join(", ")}{s.lines.length > 2 ? ` +${s.lines.length - 2}` : ""}</span>
                        )}
                      </div>
                    </div>

                    {/* Date */}
                    <div style={{ flexShrink: 0, textAlign: "right", marginRight: 6 }}>
                      <div style={{ fontSize: 12, fontWeight: 600, color: "#64748b" }}>{fmtDate(s.updated_at)}</div>
                    </div>

                    {/* SQS circle badge */}
                    <div style={{ width: 52, height: 52, borderRadius: "50%", background: bg, border: `2px solid ${color}44`, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                      {avg != null ? (
                        <>
                          <span style={{ fontSize: 14, fontWeight: 800, color, lineHeight: 1 }}>{avg}</span>
                          <span style={{ fontSize: 9, fontWeight: 700, color, opacity: 0.75, marginTop: 1 }}>{grade}</span>
                        </>
                      ) : (
                        <span style={{ fontSize: 9, color: "#94a3b8", fontWeight: 600, textAlign: "center", lineHeight: 1.3 }}>SQS{"\n"}—</span>
                      )}
                    </div>

                    {/* Chevron */}
                    <div style={{ color: "#cbd5e1", flexShrink: 0, display: "flex", alignItems: "center" }}>
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none"><path d="M9 18l6-6-6-6" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"/></svg>
                    </div>

                    <button className="session-delete-btn" onClick={e => { e.stopPropagation(); setDeleteTarget(s.session_id); }} title="Delete session" style={{ position: "absolute", top: 10, right: 10 }}>✕</button>
                  </div>
                </div>
              );
            })}
          </div>
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

  // ── SQS enhancement state ──────────────────────────────────────────────────
  const [packageSqs, setPackageSqs] = useState(null);
  const [dismissedRecs, setDismissedRecs] = useState(new Set());
  const [showDownloadPreflight, setShowDownloadPreflight] = useState(false);
  const [preflightRecs, setPreflightRecs] = useState([]);
  const [preflightOverrideReason, setPreflightOverrideReason] = useState("");
  const [preflightCallback, setPreflightCallback] = useState(null);
  const [sqsNarrative, setSqsNarrative] = useState("");
  const [downloadPreflightLoading, setDownloadPreflightLoading] = useState(false);

  useEffect(() => {
    if (step !== "lite" || !sessionId || !token) return;
    fetch(`${API_BASE}/api/lite/generate-internal/${sessionId}`, { method: "POST", credentials: "include" })
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d?.success) setLiteSqsData(d); })
      .catch(() => {});
  }, [step, sessionId]); // eslint-disable-line

  useEffect(() => {
    if (!resumeSessionId) return;
    setLoading(true); setProcessingStage("Restoring your session...");
    fetch(`${API_BASE}/api/session/${resumeSessionId}`, { credentials: "include" })
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (data && data.generated_forms && Object.keys(data.generated_forms).length > 0) {
          setGeneratedForms(data.generated_forms); setCrossIssues(data.cross_issues || []);
          const firstId = Object.keys(data.generated_forms)[0]; setActiveFormId(firstId);
          const readyMap = {}; Object.keys(data.generated_forms).forEach(fid => { readyMap[fid] = false; });
          setPdfLoading(readyMap); setStep("editor");
        } else { setStep("dashboard"); setSessionId(null); }
      })
      .catch(() => { setError("Could not restore session. Please try again."); setStep("dashboard"); setSessionId(null); })
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
    fetch(`${API_BASE}/api/arq/list/${sessionId}`, { credentials: "include" })
      .then(r => r.ok ? r.json() : null).then(d => { if (d?.success) setArqSessions(d.arq_sessions || []); }).catch(() => {});
    fetch(`${API_BASE}/api/arq/notifications`, { credentials: "include" })
      .then(r => r.ok ? r.json() : null).then(d => { if (d?.notifications) setArqNotifCount(d.notifications.filter(n => !n.read_status).length); }).catch(() => {});
    try {
      const r = await fetch(`${API_BASE}/api/arq/client-filled/${sessionId}`, { credentials: "include" });
      const d = r.ok ? await r.json() : null;
      const fields = d?.client_filled_fields || [];
      setClientFilledFields(fields); return fields;
    } catch { return []; }
  };

  const handleOpenARQ = async () => {
    if (!sessionId) return;
    setArqLoadingQ(true);
    try {
      const res = await fetch(`${API_BASE}/api/arq/generate/${sessionId}`, { credentials: "include" });
      const data = await res.json();
      if (res.ok && data.success) { setArqQuestions(data.questions || []); setShowARQModal(true); }
      else setError(data.detail || "Failed to generate questions.");
    } catch (e) { setError("Network error: " + e.message); }
    finally { setArqLoadingQ(false); }
  };

  const _resetSqsState = () => {
    setPackageSqs(null); setDismissingRec(null); setDismissReason("");
    setDismissedRecs(new Set()); setShowDownloadPreflight(false);
    setPreflightRecs([]); setPreflightOverrideReason(""); setPreflightCallback(null);
    setSqsNarrative("");
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
    _resetSqsState();
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
    _resetSqsState();
  };

  const handleResumeSession = sid => {
    setLoading(true); setProcessingStage("Restoring session…"); setSessionId(sid);
    fetch(`${API_BASE}/api/session/${sid}`, { credentials: "include" })
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (data && data.generated_forms && Object.keys(data.generated_forms).length > 0) {
          setGeneratedForms(data.generated_forms); setCrossIssues(data.cross_issues || []);
          const firstId = Object.keys(data.generated_forms)[0]; setActiveFormId(firstId);
          const readyMap = {}; Object.keys(data.generated_forms).forEach(fid => { readyMap[fid] = false; });
          setPdfLoading(readyMap); setStep("editor");
        } else { setStep("upload"); setSessionId(null); }
      })
      .catch(() => { setError("Could not load session. Please try again."); setStep("upload"); setSessionId(null); })
      .finally(() => { setLoading(false); setProcessingStage(""); });
  };

  const handleSendToEpic = async formId => {
    if (!formId || !sessionId) return;
    setEpicLoading(true); setEpicSuccess(false);
    try {
      const res = await fetch(`${API_BASE}/api/send-to-epic/${sessionId}/${formId}`, { credentials: "include" });
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
      const res = await fetch(`${API_BASE}/api/acord/confirm-license`, { method: "POST", credentials: "include" });
      if (res.ok) { onUserUpdate({ ...user, acord_license_confirmed: true }); setShowAcordModal(false); if (acordModalAction) acordModalAction(); }
      else setError("License confirmation failed. Please try again.");
    } catch { setError("Network error during license confirmation."); }
    finally { setAcordModalLoading(false); }
  };

  const _doDownloadOne = async formId => {
    setLoading(true); setShowDownloadOverlay(true);
    try {
      const res = await fetch(`${API_BASE}/api/download-pdf/${sessionId}/${formId}`, { credentials: "include" });
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
      const res = await fetch(`${API_BASE}/api/download-all/${sessionId}`, { credentials: "include" });
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
    const res = await fetch(`${API_BASE}/api/auth/me`, { credentials: "include" });
    if (res.ok) { const data = await res.json(); onUserUpdate(data); }
  };

  const handleUpload = async () => {
    if (!files.length) { setError("Select at least one file"); return; }
    setLoading(true); setError(null); setShowUploadOverlay(true);
    const fd = new FormData(); files.forEach(f => fd.append("files", f));
    try {
      const res = await fetch(`${API_BASE}/api/upload-declaration`, { method: "POST", credentials: "include", body: fd });
      const data = await res.json();
      if (res.status === 401) { setError("Session expired. Please sign in again."); setTimeout(() => { localStorage.removeItem("acordly_token"); window.location.reload(); }, 2000); return; }
      if (res.status === 403) { if (data.upgrade_required) { onShowUpgrade(); return; } const msg = data.detail || data.message || "Access blocked."; if (msg.includes("suspended")) setError("Your account is suspended."); else if (msg.includes("archived")) setError("Account archived. Contact support."); else if (msg.includes("soft_locked") || msg.includes("locked")) setError("Account Disabled — please update billing."); else setError(msg); return; }
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
      const res = await fetch(`${API_BASE}/api/select-forms-bulk`, { method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session_id: sessionId, form_ids: ids }) });
      const data = await res.json();
      if (res.status === 403) {
        const msg = data.detail || data.message || "";
        if (msg.toLowerCase().includes("lite")) { setStep("lite"); return; }
        setError(msg || "Access blocked. Please update your billing."); return;
      }
      if (!data.success) { setError("Form generation failed"); return; }
      setGeneratedForms(data.generated || {}); setCrossIssues(data.cross_issues || []);
      if (data.package_sqs) setPackageSqs(data.package_sqs);
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

  const handleDismissRec = (rec, currentScore, reason = "") => {
    const id = rec?.rec_id;
    if (!id) return;
    // Remove from dismissedRecs set (for filter)
    setDismissedRecs(prev => {
      const next = new Set(prev);
      next.add(id);
      return next;
    });
    // Also remove directly from generatedForms so rec doesn't reappear on re-render
    if (activeFormId) {
      setGeneratedForms(prev => {
        const form = prev[activeFormId];
        if (!form?.sqs?.recommendations) return prev;
        return {
          ...prev,
          [activeFormId]: {
            ...form,
            sqs: {
              ...form.sqs,
              recommendations: form.sqs.recommendations.filter(r =>
                (typeof r === "object" ? r.rec_id : r) !== id
              ),
            },
          },
        };
      });
    }
    fetch(`${API_BASE}/api/audit/dismiss`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: sessionId,
        rec_id: id,
        override_reason: reason.trim() || "No reason provided",
        sqs_score_at_action: currentScore ?? 0,
        message: rec.message ?? null,
        field: rec.field ?? null,
        component: rec.component ?? null,
        score_impact: rec.score_impact ?? null,
        form_id: activeFormId ?? null,
      }),
    }).catch(() => {});
  };

  const _runPreflightThenDownload = async (downloadFn) => {
    setDownloadPreflightLoading(true);
    try {
      const [recsRes, narrativeRes] = await Promise.allSettled([
        fetch(`${API_BASE}/api/audit/open/${sessionId}`, { credentials: "include" }),
        fetch(`${API_BASE}/api/sqs/narrative/${sessionId}`, { credentials: "include" }),
      ]);
      const recsData = recsRes.status === "fulfilled" && recsRes.value.ok ? await recsRes.value.json() : null;
      const openRecs = recsData?.open_recommendations || [];
      const narrativeData = narrativeRes.status === "fulfilled" && narrativeRes.value.ok ? await narrativeRes.value.json() : null;
      if (narrativeData?.narrative) setSqsNarrative(narrativeData.narrative);
      setPreflightRecs(openRecs);
      setPreflightOverrideReason("");
      setPreflightCallback(() => downloadFn);
      setShowDownloadPreflight(true);
    } catch (_) { downloadFn(); }
    finally { setDownloadPreflightLoading(false); }
  };

  const handlePreflightProceed = () => {
    setShowDownloadPreflight(false);
    // Fire audit log in background — don't block the download
    fetch(`${API_BASE}/api/audit/download-anyway`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, override_reason: preflightOverrideReason.trim() }),
    }).catch(() => {});
    if (preflightCallback) preflightCallback();
  };

  const handleDownloadOne = formId => gatedDownload(() => _runPreflightThenDownload(() => _doDownloadOne(formId)));
  const handleDownloadAll = () => gatedDownload(() => _runPreflightThenDownload(() => _doDownloadAll()));

  const handleLiteCoverSheet = async () => {
    setLiteCoverLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/lite/cover-sheet/${sessionId}`, { credentials: "include" });
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
      {downloadPreflightLoading && <ProcessStageOverlay stages={["Checking recommendations", "Loading SQS summary"]} advanceAfter={1800} />}
      {showDownloadPreflight && (
        <DownloadPreflightModal
          openRecs={preflightRecs}
          narrative={sqsNarrative}
          overrideReason={preflightOverrideReason}
          onOverrideChange={setPreflightOverrideReason}
          onProceed={handlePreflightProceed}
          onCancel={() => { setShowDownloadPreflight(false); setPreflightCallback(null); }}
          loading={loading}
        />
      )}
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

        {loading && !showUploadOverlay && !showGenerateOverlay && !showDownloadOverlay && step !== "editor" && (
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

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 20 }}>
                <div style={{ background: "#fff", border: "1px solid #e2e8f0", borderRadius: 12, padding: "20px 20px" }}>
                  <div style={{ fontSize: 18, marginBottom: 8 }}>📧</div>
                  <div style={{ fontSize: 14, fontWeight: 700, color: "#0f172a", marginBottom: 6 }}>Client Questionnaire</div>
                  <div style={{ fontSize: 12, color: "#64748b", marginBottom: 14 }}>Generate and send a tailored questionnaire to your client to fill in missing information.</div>
                  <button onClick={handleOpenARQ} disabled={arqLoadingQ}
                    style={{ width: "100%", padding: "9px 14px", borderRadius: 8, border: "1px solid #e6007a", background: "#e6007a", color: "#fff", fontSize: 13, fontWeight: 700, cursor: arqLoadingQ ? "wait" : "pointer", fontFamily: "inherit", display: "flex", alignItems: "center", justifyContent: "center", gap: 6, opacity: arqLoadingQ ? 0.7 : 1 }}>
                    {arqLoadingQ ? <><span style={{ width: 11, height: 11, border: "2px solid #fff", borderTopColor: "transparent", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" }} /> Loading…</> : "Send to Client"}
                  </button>
                  <ARQStatusPanel arqSessions={arqSessions} token={token} onRefresh={refreshArqData} />
                </div>

                <div style={{ background: "#fff", border: "1px solid #e2e8f0", borderRadius: 12, padding: "20px 20px" }}>
                  <div style={{ fontSize: 18, marginBottom: 8 }}>📄</div>
                  <div style={{ fontSize: 14, fontWeight: 700, color: "#0f172a", marginBottom: 6 }}>Summary Cover Sheet</div>
                  <div style={{ fontSize: 12, color: "#64748b", marginBottom: 14 }}>Download your AI-generated SQS summary cover page for use with any platform.</div>
                  <button onClick={handleLiteCoverSheet} disabled={liteCoverLoading}
                    style={{ width: "100%", padding: "9px 14px", borderRadius: 8, border: "1px solid #0f172a", background: "#0f172a", color: "#fff", fontSize: 13, fontWeight: 700, cursor: liteCoverLoading ? "wait" : "pointer", fontFamily: "inherit", display: "flex", alignItems: "center", justifyContent: "center", gap: 6, opacity: liteCoverLoading ? 0.7 : 1 }}>
                    {liteCoverLoading ? <><span style={{ width: 11, height: 11, border: "2px solid #fff", borderTopColor: "transparent", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" }} /> Generating…</> : "Download Cover Sheet"}
                  </button>
                </div>
              </div>

              <div style={{ textAlign: "center" }}>
                <button onClick={() => { setStep("upload"); setSessionId(null); setFiles([]); setLiteSqsData(null); }}
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
              {recommendations.map((rec, i) => {
                const pct = Math.round((rec.confidence || 0) * 100);
                const tooltipText = rec.fields_total > 0
                  ? `${rec.fields_filled} of ${rec.fields_total} required fields found in your document`
                  : rec.reason || "";
                return (
                  <div key={rec.form_id} className={`form-select-row ${checkedFormIds.has(rec.form_id) ? "form-row-checked" : ""}`}>
                    <label className="form-select-checkbox-label">
                      <input type="checkbox" checked={checkedFormIds.has(rec.form_id)} onChange={() => toggleForm(rec.form_id)} className="form-select-checkbox" />
                      <div className="form-select-info">
                        <div className="form-select-name"><span className="rec-rank">#{i + 1}</span>{rec.form_name}</div>
                        <div className="form-select-meta">
                          <span
                            className="confidence-badge"
                            title={tooltipText}
                            style={{ cursor: "help" }}
                          >
                            Match {pct}%
                          </span>
                          <span className="form-select-reason">{rec.reason || rec.trigger_reason}</span>
                        </div>
                      </div>
                    </label>
                    <button className="btn-icon-only" onClick={() => toggleForm(rec.form_id)}>{checkedFormIds.has(rec.form_id) ? "✓" : "+"}</button>
                  </div>
                );
              })}
            </div>
            {extraForms.length > 0 && (
              <div className="add-forms-section">
                <button className="btn btn-modal-secondary btn-small" onClick={() => setShowAddForms(v => !v)}>
                  {showAddForms ? "▲ Hide" : "▼ Add more ACORD forms"} ({extraForms.length} available)
                </button>
                {showAddForms && (
                  <div className="extra-forms-list">
                    {extraForms.map(f => {
                      const pct = Math.round((f.confidence || 0) * 100);
                      const tooltipText = f.fields_total > 0
                        ? `${f.fields_filled} of ${f.fields_total} required fields found in your document`
                        : f.description || "";
                      return (
                        <div key={f.form_id} className={`form-select-row ${checkedFormIds.has(f.form_id) ? "form-row-checked" : ""}`}>
                          <label className="form-select-checkbox-label">
                            <input type="checkbox" checked={checkedFormIds.has(f.form_id)} onChange={() => toggleForm(f.form_id)} className="form-select-checkbox" />
                            <div className="form-select-info">
                              <div className="form-select-name">{f.form_name}</div>
                              <div className="form-select-meta">
                                {pct > 0 && (
                                  <span
                                    className="confidence-badge confidence-badge--extra"
                                    title={tooltipText}
                                    style={{ cursor: "help" }}
                                  >
                                    Match {pct}%
                                  </span>
                                )}
                                {(f.reason || f.description) && (
                                  <span className="form-select-reason">{f.reason || f.description}</span>
                                )}
                              </div>
                            </div>
                          </label>
                        </div>
                      );
                    })}
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

              {activeSqs && (
                <>
                  <div style={{ height: 1, background: "#f1f5f9", margin: "0 14px" }} />
                  <div style={{ padding: "14px 14px 12px" }}>

                    {/* ── Score header ── */}
                    <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
                      <div style={{ width: 36, height: 36, borderRadius: "50%", background: gradeColor(activeSqs.grade), display: "flex", alignItems: "center", justifyContent: "center", fontSize: 14, fontWeight: 800, color: "#fff", flexShrink: 0 }}>{activeSqs.grade}</div>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ display: "flex", alignItems: "baseline", gap: 4 }}>
                          <span style={{ fontSize: 28, fontWeight: 800, lineHeight: 1, color: gradeColor(activeSqs.grade) }}>{activeSqs.sqs_score}</span>
                          <span style={{ fontSize: 11, color: "#94a3b8" }}>/100</span>
                          <span style={{ fontSize: 10, fontWeight: 700, padding: "2px 7px", borderRadius: 20, color: "#fff", marginLeft: 4, background: { green: "#10b981", yellow: "#f59e0b", orange: "#f97316", red: "#ef4444" }[activeSqs.tier_color] || "#94a3b8" }}>{activeSqs.tier}</span>
                        </div>
                        <div style={{ fontSize: 10, color: "#94a3b8", marginTop: 1, textTransform: "uppercase", letterSpacing: "0.04em", fontWeight: 600 }}>Form SQS Score</div>
                      </div>
                    </div>

                    {/* ── Confidence fill rate ── */}
                    {activeSqs.confidence_fill_rate != null && (
                      <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: 7, padding: "7px 10px", marginBottom: 10 }}>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
                          <span style={{ fontSize: 10, fontWeight: 700, color: "#64748b" }}>Quality Fill Rate</span>
                          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                            {activeSqs.fill_rate != null && activeSqs.fill_rate !== activeSqs.confidence_fill_rate && (
                              <span style={{ fontSize: 10, color: "#94a3b8", textDecoration: "line-through" }}>{activeSqs.fill_rate}%</span>
                            )}
                            <span style={{ fontSize: 12, fontWeight: 800, color: barColor(activeSqs.confidence_fill_rate) }}>{activeSqs.confidence_fill_rate}%</span>
                          </div>
                        </div>
                        <div style={{ height: 4, background: "#e2e8f0", borderRadius: 2, overflow: "hidden" }}>
                          <div style={{ height: "100%", width: `${activeSqs.confidence_fill_rate}%`, background: barColor(activeSqs.confidence_fill_rate), borderRadius: 2, transition: "width 0.6s ease" }} />
                        </div>
                        <div style={{ fontSize: 9, color: "#94a3b8", marginTop: 3 }}>Producer edits = 100% · AI high = 85% · AI low = 50%</div>
                      </div>
                    )}

                    {/* ── Session delta ── */}
                    {packageSqs && packageSqs.sqs_history?.length > 1 && (
                      <div style={{ background: packageSqs.delta_this_session >= 0 ? "rgba(16,185,129,0.06)" : "rgba(239,68,68,0.06)", border: `1px solid ${packageSqs.delta_this_session >= 0 ? "rgba(16,185,129,0.2)" : "rgba(239,68,68,0.2)"}`, borderRadius: 7, padding: "6px 10px", marginBottom: 10, display: "flex", alignItems: "center", gap: 8 }}>
                        <span style={{ fontSize: 14 }}>{packageSqs.delta_this_session >= 0 ? "📈" : "📉"}</span>
                        <div>
                          <span style={{ fontSize: 11, fontWeight: 700, color: packageSqs.delta_this_session >= 0 ? "#059669" : "#dc2626" }}>
                            {packageSqs.delta_this_session >= 0 ? "+" : ""}{packageSqs.delta_this_session} pts this session
                          </span>
                          <div style={{ fontSize: 10, color: "#94a3b8" }}>
                            Started at {packageSqs.sqs_history[0].score} → now {packageSqs.package_sqs_score}
                          </div>
                        </div>
                      </div>
                    )}

                    {/* ── Routing decision ── */}
                    {activeSqs.routing_decision && (
                      <div style={{ padding: "5px 9px", borderRadius: 7, fontSize: 11, fontWeight: 700, textAlign: "center", marginBottom: 12, background: { auto_quote: "#dcfce7", review: "#fef9c3", full_review: "#ffedd5", hold: "#fee2e2" }[activeSqs.routing_decision] || "#f1f5f9", color: { auto_quote: "#166534", review: "#854d0e", full_review: "#9a3412", hold: "#991b1b" }[activeSqs.routing_decision] || "#374151", border: `1px solid ${{ auto_quote: "#86efac", review: "#fde047", full_review: "#fdba74", hold: "#fca5a5" }[activeSqs.routing_decision] || "#e2e8f0"}` }}>
                        {{ auto_quote: "✅ Auto-Route to Quoting", review: "🔍 Light Review", full_review: "📋 Full Underwriter Review", hold: "🚫 Hold — Remediation Required" }[activeSqs.routing_decision]}
                      </div>
                    )}

                    {/* ── Per-form breakdown bars ── */}
                    {/* doc-sourced = driven by uploaded documents, not form field edits */}
                    {(() => {
                      const docSourced = new Set(["property_integrity", "loss_history_alignment", "narrative_quality"]);
                      return (
                        <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 10 }}>
                          {Object.entries(activeSqs.breakdown || {}).map(([key, val]) => (
                            <div key={key}>
                              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, marginBottom: 3 }}>
                                <span style={{ color: "#64748b" }}>
                                  {SQS_LABELS[key] || key}
                                  <span style={{ color: "#cbd5e1" }}> ({SQS_WEIGHTS[key] || 0}%)</span>
                                  {docSourced.has(key) && (
                                    <span title="Sourced from uploaded documents — editing form fields won't change this" style={{ marginLeft: 4, fontSize: 9, color: "#94a3b8", cursor: "help" }}>📄</span>
                                  )}
                                </span>
                                <span style={{ fontWeight: 700, color: barColor(val) }}>{val}%</span>
                              </div>
                              <div style={{ height: 5, background: "#f1f5f9", borderRadius: 3, overflow: "hidden" }}>
                                <div style={{ height: "100%", width: `${val}%`, background: barColor(val), borderRadius: 3, transition: "width 0.6s ease" }} />
                              </div>
                            </div>
                          ))}
                          <div style={{ fontSize: 9, color: "#94a3b8", marginTop: 2 }}>📄 = sourced from uploaded docs, not form edits</div>
                        </div>
                      );
                    })()}

                    {/* ── Package SQS panel ── */}
                    {packageSqs && (
                      <div style={{ background: "#fafafa", border: "1px solid #e2e8f0", borderRadius: 8, padding: "10px 12px", marginBottom: 10 }}>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                          <div style={{ fontSize: 10, fontWeight: 700, color: "#94a3b8", textTransform: "uppercase", letterSpacing: "0.05em" }}>Package SQS</div>
                          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                            {packageSqs.lob && packageSqs.lob !== "generic" && (
                              <span style={{ fontSize: 9, fontWeight: 700, background: "rgba(230,0,122,0.08)", color: "#e6007a", borderRadius: 20, padding: "1px 6px", textTransform: "capitalize" }}>{packageSqs.lob}</span>
                            )}
                            <span style={{ fontSize: 16, fontWeight: 800, color: gradeColor(packageSqs.package_sqs_score >= 90 ? "A" : packageSqs.package_sqs_score >= 80 ? "B" : packageSqs.package_sqs_score >= 70 ? "C" : packageSqs.package_sqs_score >= 60 ? "D" : "F") }}>{packageSqs.package_sqs_score}</span>
                            <span style={{ fontSize: 9, color: "#94a3b8" }}>/100</span>
                          </div>
                        </div>
                        <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
                          {Object.entries(packageSqs.pillars || {}).map(([key, val]) => (
                            <div key={key}>
                              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, marginBottom: 2 }}>
                                <span style={{ color: "#64748b" }}>{PACKAGE_PILLAR_LABELS[key] || key}</span>
                                <span style={{ fontWeight: 700, color: barColor(val) }}>{val}</span>
                              </div>
                              <div style={{ height: 3, background: "#e2e8f0", borderRadius: 2, overflow: "hidden" }}>
                                <div style={{ height: "100%", width: `${val}%`, background: barColor(val), borderRadius: 2 }} />
                              </div>
                            </div>
                          ))}
                        </div>
                        {packageSqs.tier && (
                          <div style={{ marginTop: 8, padding: "3px 8px", borderRadius: 5, fontSize: 10, fontWeight: 700, textAlign: "center", background: { "Carrier-Ready": "#dcfce7", "Quote-Ready": "#fef9c3", "Review-Ready": "#ffedd5", "At-Risk": "#fee2e2", "Incomplete": "#f1f5f9" }[packageSqs.tier] || "#f1f5f9", color: { "Carrier-Ready": "#166534", "Quote-Ready": "#854d0e", "Review-Ready": "#9a3412", "At-Risk": "#991b1b", "Incomplete": "#64748b" }[packageSqs.tier] || "#374151" }}>
                            {packageSqs.tier}
                          </div>
                        )}
                      </div>
                    )}

                    {/* ── Risk drivers ── */}
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

                    {/* ── Issues ── */}
                    {activeSqs.issues?.length > 0 && (
                      <div style={{ background: "rgba(245,158,11,0.06)", border: "1px solid rgba(245,158,11,0.2)", borderRadius: 7, padding: "7px 10px", marginBottom: 8 }}>
                        <div style={{ fontSize: 10, fontWeight: 700, color: "#b45309", marginBottom: 3 }}>⚠️ Issues</div>
                        {activeSqs.issues.map((s, i) => <div key={i} style={{ fontSize: 11, color: "#64748b", padding: "1px 0" }}>• {s}</div>)}
                      </div>
                    )}

                    {/* ── Structured recommendations with score_impact + dismiss ── */}
                    {activeSqs.recommendations?.length > 0 && (
                      <div>
                        <div style={{ fontSize: 10, fontWeight: 700, color: "#94a3b8", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 6 }}>Recommendations</div>
                        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                          {activeSqs.recommendations
                            .filter(r => !dismissedRecs.has(typeof r === "string" ? r : r.rec_id))
                            .map((rec, i) => (
                              <SidePanelRec
                                key={typeof rec === "object" && rec !== null ? rec.rec_id : `legacy_${i}`}
                                rec={rec}
                                index={i}
                                sqsScore={activeSqs.sqs_score}
                                onDismiss={handleDismissRec}
                              />
                            ))}
                        </div>
                      </div>
                    )}

                  </div>
                </>
              )}

              {crossIssues.length > 0 && (
                <>
                  <div style={{ height: 1, background: "#f1f5f9", margin: "0 14px" }} />
                  <div style={{ padding: "12px 14px" }}>
                    <div style={{ fontSize: 10, fontWeight: 700, color: "#94a3b8", letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: 8 }}>Cross-Form Validation</div>
                    {crossIssues.map((iss, i) => <div key={i} style={{ fontSize: 12, padding: "3px 0", color: iss.type === "hard_stop" ? "#dc2626" : "#b45309" }}>{iss.type === "hard_stop" ? "🚫" : "⚠️"} {iss.message}</div>)}
                  </div>
                </>
              )}

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
                pdfUrl={`${API_BASE}/api/get-pdf/${sessionId}/${activeFormId}`}
                formName={activeFormId ? (generatedForms[activeFormId]?.form_name || activeFormId) : ""}
                onFormNav={{ goPrev, goNext, activeIdx, total: formIdList.length }}
                sessionId={sessionId} formId={activeFormId} token={token}
                savedSignature={savedSignature}
                isSigned={signedForms.has(activeFormId)}
                onSignApplied={fid => setSignedForms(prev => new Set([...prev, fid]))}
                onOpenSignatureModal={onOpenSignatureModal}
                clientFilledFields={clientFilledFields}
                onRefreshFields={refreshArqData}
                onSqsUpdate={(fid, newSqs) => setGeneratedForms(prev => ({
                  ...prev,
                  [fid]: { ...prev[fid], sqs: newSqs }
                }))}
              />
            </div>
          </div>
        )}

        {step === "success" && (
          <div style={{ maxWidth: 480, margin: "0 auto", textAlign: "center", padding: "56px 24px" }}>
            <div style={{ width: 80, height: 80, borderRadius: "50%", background: "linear-gradient(135deg, #e6007a, #c00066)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 36, color: "#fff", margin: "0 auto 24px", boxShadow: "0 8px 28px rgba(230,0,122,0.3)", animation: "successPop 0.5s ease-out" }}>✓</div>
            <h2 style={{ fontSize: 26, fontWeight: 800, color: "#0f172a", marginBottom: 8 }}>Download Complete!</h2>
            <p style={{ fontSize: 15, color: "#64748b", marginBottom: 28, lineHeight: 1.6 }}>Your filled ACORD forms have been downloaded successfully.</p>
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