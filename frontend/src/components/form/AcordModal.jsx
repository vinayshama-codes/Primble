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
  hard_stop:    { bg: "#fdf2f8", border: "#f9a8d4", color: "#000", icon: "🚫" },
  soft_warning: { bg: "#fdf2f8", border: "#f9a8d4", color: "#000", icon: "⚠️" },
  missing_field:{ bg: "#fdf2f8", border: "#f9a8d4", color: "#000", icon: "📋" },
  suggestion:   { bg: "#fdf2f8", border: "#f9a8d4", color: "#000", icon: "💡" },
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
              <div style={{ fontSize: 11, fontWeight: 700, color: "#E61B84", marginBottom: 4, letterSpacing: "0.05em", textTransform: "uppercase" }}>Client Questionnaire</div>
              <h2 style={{ fontSize: 22, fontWeight: 700, color: "#0f172a", margin: 0 }}>Send to Client</h2>
              <p style={{ fontSize: 13, color: "#64748b", marginTop: 4 }}>Client answers will auto-populate your ACORD forms.</p>
            </div>
            <button onClick={onClose} style={{ width: 32, height: 32, borderRadius: "50%", border: "1px solid #E61B84", background: "rgba(230,0,122,0.08)", color: "#E61B84", fontSize: 16, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0, transition: "all 0.2s" }}
              onMouseEnter={e => { e.currentTarget.style.background = "#E61B84"; e.currentTarget.style.color = "#fff"; }}
              onMouseLeave={e => { e.currentTarget.style.background = "rgba(230,0,122,0.08)"; e.currentTarget.style.color = "#E61B84"; }}>✕</button>
          </div>
          {error && <div style={{ background: "#fef2f2", border: "1px solid #fecaca", borderRadius: 8, padding: "10px 14px", marginBottom: 16, color: "#dc2626", fontSize: 13 }}>⚠️ {error}</div>}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 20 }}>
            <div>
              <label style={{ display: "block", fontSize: 12, fontWeight: 600, color: "#374151", marginBottom: 6 }}>Client Email <span style={{ color: "#E61B84" }}>*</span></label>
              <input type="email" value={clientEmail}
                onChange={e => { setClientEmail(e.target.value); setEmailTouched(true); }}
                onBlur={e => { setEmailTouched(true); e.target.style.borderColor = "#e2e8f0"; }}
                onFocus={e => e.target.style.borderColor = "#E61B84"}
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
                onFocus={e => e.target.style.borderColor = "#E61B84"} onBlur={e => e.target.style.borderColor = "#e2e8f0"} />
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
                style={{ border: `1.5px solid ${selectedQuestions[q.field_name] ? "#E61B84" : "#e2e8f0"}`, borderRadius: 10, padding: "10px 14px", cursor: "pointer", background: selectedQuestions[q.field_name] ? "rgba(230,0,122,0.03)" : "#fafafa", display: "flex", alignItems: "flex-start", gap: 10, opacity: selectedQuestions[q.field_name] ? 1 : 0.5, transition: "all 0.15s" }}>
                <input type="checkbox" checked={!!selectedQuestions[q.field_name]} onChange={() => handleToggle(q.field_name)} onClick={e => e.stopPropagation()} style={{ marginTop: 3, width: 15, height: 15, cursor: "pointer", accentColor: "#E61B84", flexShrink: 0 }} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <span style={{ fontSize: 10, fontWeight: 700, color: "#E61B84", background: "#fdf2f8", padding: "1px 7px", borderRadius: 20, display: "inline-block", marginBottom: 4 }}>ACORD {q.forms}</span>
                  <p style={{ margin: 0, fontSize: 13, fontWeight: 600, color: "#0f172a", lineHeight: 1.45 }}>{q.question}</p>
                  {q.current_value && <p style={{ margin: "3px 0 0", fontSize: 11, color: "#94a3b8" }}>Current: {q.current_value}</p>}
                </div>
              </div>
            ))}
          </div>
        </div>
        <div style={{ padding: "16px 28px 24px", flexShrink: 0, borderTop: "1px solid #f1f5f9", marginTop: 8 }}>
          <button onClick={handleSend} disabled={!canSend || sending}
            style={{ width: "100%", padding: "12px 0", borderRadius: 10, border: "none", background: canSend && !sending ? "#E61B84" : "#e2e8f0", color: canSend && !sending ? "#fff" : "#94a3b8", fontSize: 14, fontWeight: 700, cursor: canSend && !sending ? "pointer" : "not-allowed", display: "flex", alignItems: "center", justifyContent: "center", gap: 8, minHeight: 46 }}>
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
    <div style={{ background: st.bg, border: `1px solid ${st.border}`, borderRadius: 8, padding: "8px 10px", boxShadow: "0 2px 8px rgba(230,0,122,0.07)" }}>
      <div style={{ display: "flex", alignItems: "flex-start", gap: 7 }}>
        <span style={{ fontSize: 12, flexShrink: 0, marginTop: 1 }}>{st.icon}</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 11, color: st.color, fontWeight: 600, lineHeight: 1.4 }}>{msg}</div>
          {impact > 0 && <div style={{ fontSize: 10, color: "#000", fontWeight: 700, marginTop: 2 }}>+{impact} pts if fixed</div>}
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
              onFocus={e => e.target.style.borderColor = "#E61B84"}
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
              style={{ flex: 2, padding: "9px 0", borderRadius: 8, border: "none", background: !loading ? "#E61B84" : "#e2e8f0", color: !loading ? "#fff" : "#94a3b8", fontSize: 13, fontWeight: 700, cursor: !loading ? "pointer" : "not-allowed", display: "flex", alignItems: "center", justifyContent: "center", gap: 6 }}>
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
  const [stats, setStats] = useState({ total_packages: 0, total_forms: 0, avg_sqs_score: null });
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);
  const [deleteTarget, setDeleteTarget] = useState(null);

  const fetchDashboardData = async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const [sessData, statsData] = await Promise.all([
        fetch(`${API_BASE}/api/sessions`, { credentials: "include" }).then(r => r.ok ? r.json() : null),
        fetch(`${API_BASE}/api/sessions/stats`, { credentials: "include" }).then(r => r.ok ? r.json() : null),
      ]);
      if (sessData?.success) setSessions(sessData.sessions || []); else setLoadError("Could not load your sessions. Please refresh.");
      if (statsData) setStats({ total_packages: statsData.total_packages ?? 0, total_forms: statsData.total_forms ?? 0, avg_sqs_score: statsData.avg_sqs_score ?? null });
    } catch {
      setLoadError("Network error loading sessions. Please refresh.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchDashboardData(); }, []);

  const handleDelete = async sid => {
    setDeleteTarget(null);
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/sessions/${sid}`, { method: "DELETE", credentials: "include" });
      if (!res.ok) throw new Error("Delete failed");
    } catch {
      setLoading(false);
      setLoadError("Failed to delete session. Please try again.");
      return;
    }
    await fetchDashboardData();
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

  const totalForms = stats.total_forms;
  const globalAvg  = stats.avg_sqs_score;

  const tips = [
    "Upload source documents as PDFs — Acordly pre-fills ACORD fields automatically.",
    "Generate multiple ACORD forms from a single submission in one pass.",
    "Add e-signatures directly inside the form editor before downloading.",
    "Download completed packages as a single merged PDF.",
  ];

  return (
    <>
    {loading && (
      <div className="loading-overlay">
        <div className="loading-spinner" />
        <p className="loading-text">Loading sessions…</p>
      </div>
    )}
    <div className="dashboard-shell">
      {deleteTarget && <DeleteConfirmModal onConfirm={() => handleDelete(deleteTarget)} onCancel={() => setDeleteTarget(null)} />}

      {loadError && (
        <div className="db-error-banner">
          {loadError}
        </div>
      )}

      {/* ── Header ── */}
      <div className="db-header">
        <div>
          <div className="db-header-eyebrow">Submissions</div>
          <h2 className="db-header-title">Recent Packages</h2>
          <p className="db-header-sub">Pick up where you left off or start a new submission.</p>
        </div>
        <button onClick={onNewPackage} className="db-primary-btn">+ Upload New Package</button>
      </div>

      {/* ── Two-column body ── */}
      <div className="dashboard-body">

        {/* ── Main: package list ── */}
        <div className="dashboard-main">
          {loading ? null : sessions.length === 0 ? (
            <div className="db-empty-state">
              <div className="db-empty-topbar" />
              <p className="db-empty-title">No packages yet</p>
              <p className="db-empty-desc">Upload your first submission documents — Acordly will extract data and fill ACORD forms automatically.</p>
              <div className="db-empty-steps">
                {[["Upload docs", "AI extracts data", "Download forms"]].flat().map((label, i, arr) => (
                  <div key={i} style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    <div className="db-empty-step-pill">{label}</div>
                    {i < arr.length - 1 && <span className="db-empty-step-arrow">→</span>}
                  </div>
                ))}
              </div>
              <button onClick={onNewPackage} className="db-primary-btn">
                Start First Package
              </button>
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
              <div className="db-list-count">
                {sessions.length} Package{sessions.length !== 1 ? "s" : ""}
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {sessions.map(s => {
                  const avg   = avgSqs(s.sqs);
                  const color = avg != null ? sqsColor(avg) : "#94a3b8";
                  const bg    = avg != null ? sqsBg(avg)    : "rgba(148,163,184,0.08)";
                  const grade = avg != null ? sqsGrade(avg) : null;
                  const formCount = s.form_ids?.length || 0;
                  return (
                    <div key={s.session_id} className="session-card"
                      onClick={() => onResume(s.session_id)}
                      style={{ background: "#fff", border: "1.5px solid #e0e0e0", borderRadius: 18, cursor: "pointer", display: "flex", alignItems: "stretch", transition: "all 0.18s", position: "relative", boxShadow: "0 2px 8px rgba(0,0,0,0.06)", overflow: "hidden" }}
                      onMouseEnter={e => { e.currentTarget.style.borderColor = "#E61B84"; e.currentTarget.style.boxShadow = "0 8px 32px rgba(230,0,122,0.12)"; e.currentTarget.style.transform = "translateY(-1px)"; }}
                      onMouseLeave={e => { e.currentTarget.style.borderColor = "#e0e0e0"; e.currentTarget.style.boxShadow = "0 2px 8px rgba(0,0,0,0.06)"; e.currentTarget.style.transform = "none"; }}>

                      <div style={{ width: 4, background: "#E61B84", flexShrink: 0 }} />

                      <div style={{ flex: 1, padding: "18px 22px", display: "flex", alignItems: "center", gap: 16, minWidth: 0 }}>

                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ fontWeight: 700, fontSize: 15, color: "#0b0b0b", marginBottom: 6, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                            {s.applicant || "Unnamed Package"}
                          </div>
                          <div style={{ display: "flex", gap: 5, flexWrap: "wrap", alignItems: "center" }}>
                            {formCount > 0 && (
                              <span className="db-badge db-badge-pink">
                                {formCount} form{formCount !== 1 ? "s" : ""}
                              </span>
                            )}
                            {s.form_ids?.slice(0, 4).map(fid => (
                              <span key={fid} className="db-badge db-badge-gray">{fid.replace(/_/g, " ")}</span>
                            ))}
                            {(s.form_ids?.length || 0) > 4 && <span style={{ fontSize: 11, color: "#b5b5b5" }}>+{s.form_ids.length - 4}</span>}
                            {s.lines?.length > 0 && (
                              <span style={{ fontSize: 11, color: "#b5b5b5" }}>· {s.lines.slice(0, 2).join(", ")}{s.lines.length > 2 ? ` +${s.lines.length - 2}` : ""}</span>
                            )}
                          </div>
                        </div>

                        <div style={{ flexShrink: 0, textAlign: "right", marginRight: 4 }}>
                          <div style={{ fontSize: 12, fontWeight: 600, color: "#6a6a6a" }}>{fmtDate(s.updated_at)}</div>
                        </div>

                        <div style={{ width: 54, height: 54, borderRadius: "50%", background: avg != null ? "rgba(230,0,122,0.08)" : "rgba(148,163,184,0.08)", border: `2px solid ${avg != null ? "#E61B8455" : "#94a3b855"}`, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                          {avg != null ? (
                            <>
                              <span style={{ fontSize: 15, fontWeight: 800, color: "#E61B84", lineHeight: 1 }}>{avg}</span>
                              <span style={{ fontSize: 9, fontWeight: 700, color: "#E61B84", opacity: 0.8, marginTop: 1 }}>{grade}</span>
                            </>
                          ) : (
                            <span style={{ fontSize: 9, color: "#b5b5b5", fontWeight: 600, textAlign: "center", lineHeight: 1.3 }}>{"SQS\n—"}</span>
                          )}
                        </div>

                        <div style={{ color: "#e0e0e0", flexShrink: 0, display: "flex", alignItems: "center" }}>
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

        {/* ── Right sidebar ── */}
        <aside className="dashboard-sidebar">

          {/* Key metrics card */}
          <div className="db-sidebar-card">
            <div className="db-sidebar-card-title">Overview</div>
            <div style={{ display: "flex", flexDirection: "column" }}>
              {[
                { label: "Total Packages", value: loading ? "—" : stats.total_packages, border: true },
                { label: "Forms Generated", value: loading ? "—" : totalForms, border: true },
                { label: "Avg SQS Score",   value: loading ? "—" : (globalAvg != null ? `${globalAvg} / 100` : "—"), border: false },
              ].map((item, i) => (
                <div key={i} className="db-metric-row" style={{ borderBottom: item.border ? "1px solid #f0f0f0" : "none" }}>
                  <span className="db-metric-label">{item.label}</span>
                  <span className="db-metric-value" style={{ color: "#E61B84" }}>{item.value}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Tips card */}
          <div className="db-sidebar-card">
            <div className="db-sidebar-card-title">Tips</div>
            <ol className="db-tips-list">
              {tips.map((tip, i) => (
                <li key={i} className="db-tip-item">{tip}</li>
              ))}
            </ol>
          </div>

        </aside>
      </div>
    </div>
    </>
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
  const [vertaforeLoading, setVertaforeLoading] = useState(false);
  const [vertaforeSuccess, setVertaforeSuccess] = useState(false);
  const [showARQModal, setShowARQModal] = useState(false);
  const [arqQuestions, setArqQuestions] = useState([]);
  const [arqLoadingQ, setArqLoadingQ] = useState(false);
  const [arqSessions, setArqSessions] = useState([]);
  const [arqNotifCount, setArqNotifCount] = useState(0);
  const [clientFilledFields, setClientFilledFields] = useState([]);
  const [actionsOpen, setActionsOpen] = useState(false);
  const [integrationsExpanded, setIntegrationsExpanded] = useState(false);
  const [downloadExpanded, setDownloadExpanded] = useState(false);
  const [showEnterprisePopup, setShowEnterprisePopup] = useState(false);
  const [enterprisePopupPos, setEnterprisePopupPos] = useState({ top: 0, left: 0 });
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
    if (step !== "lite" || !sessionId) return;
    fetch(`${API_BASE}/api/lite/generate-internal/${sessionId}`, { method: "POST", credentials: "include" })
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d?.success) setLiteSqsData(d); })
      .catch(() => {});
  }, [step, sessionId]); // eslint-disable-line

  useEffect(() => {
    if (!resumeSessionId) return;
    setLoading(true); setProcessingStage("Restoring your session...");
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 20000);
    fetch(`${API_BASE}/api/session/${resumeSessionId}`, { credentials: "include", signal: ctrl.signal })
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
      .finally(() => { clearTimeout(timer); setLoading(false); setProcessingStage(""); });
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
    if ((step !== "editor" && step !== "lite") || !sessionId) return;
    refreshArqData();
  }, [step, sessionId]); // eslint-disable-line

  const refreshArqData = async () => {
    if (!sessionId) return [];
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
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 20000);
    fetch(`${API_BASE}/api/session/${sid}`, { credentials: "include", signal: ctrl.signal })
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        const isEssentials = user?.subscription_tier === "essentials";
        if (!isEssentials && data && data.generated_forms && Object.keys(data.generated_forms).length > 0) {
          setGeneratedForms(data.generated_forms); setCrossIssues(data.cross_issues || []);
          const firstId = Object.keys(data.generated_forms)[0]; setActiveFormId(firstId);
          const readyMap = {}; Object.keys(data.generated_forms).forEach(fid => { readyMap[fid] = false; });
          setPdfLoading(readyMap); setStep("editor");
        } else if (isEssentials && data?.session_id) {
          setSessionId(sid); setStep("lite");
        } else { setStep("upload"); setSessionId(null); }
      })
      .catch(() => { setError("Could not load session. Please try again."); setStep("upload"); setSessionId(null); })
      .finally(() => { clearTimeout(timer); setLoading(false); setProcessingStage(""); });
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

  const triggerEnterprisePopup = (buttonEl) => {
    const rect = buttonEl.getBoundingClientRect();
    setEnterprisePopupPos({ top: rect.top, left: rect.right + 12 });
    setShowEnterprisePopup(true);
  };

  const handleSendToVertafore = async formId => {
    if (!formId || !sessionId) return;
    setVertaforeLoading(true); setVertaforeSuccess(false);
    try {
      const res = await fetch(`${API_BASE}/api/send-to-vertafore/${sessionId}/${formId}`, { credentials: "include" });
      const data = await res.json();
      if (res.ok && data.success) { setVertaforeSuccess(true); setTimeout(() => setVertaforeSuccess(false), 3500); }
      else setError(data.detail || "Failed to send to Vertafore.");
    } catch (e) { setError("Vertafore send failed: " + e.message); }
    finally { setVertaforeLoading(false); }
  };

  const _doDownloadOneNoSummary = async formId => {
    setLoading(true); setShowDownloadOverlay(true);
    try {
      const res = await fetch(`${API_BASE}/api/download-pdf/${sessionId}/${formId}?include_cover=false`, { credentials: "include" });
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

  const handleDownloadOneNoSummary = formId => gatedDownload(() => _runPreflightThenDownload(() => _doDownloadOneNoSummary(formId)));

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
      setCheckedFormIds(new Set());
      setStep(user?.subscription_tier === "essentials" ? "lite" : "recommendations");
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
      {showEnterprisePopup && (
        <div style={{ position: "fixed", top: enterprisePopupPos.top, left: enterprisePopupPos.left, zIndex: 9999, width: 210, borderRadius: 10, background: "#fdf2f8", border: "1px solid #f9a8d4", boxShadow: "0 6px 24px rgba(230,0,122,0.15), 0 2px 8px rgba(230,0,122,0.08)", overflow: "hidden", animation: "slideDown 0.18s ease-out" }}>
          {/* left-pointing caret */}
          <div style={{ position: "absolute", top: 14, left: -6, width: 11, height: 11, background: "#fdf2f8", border: "1px solid #f9a8d4", borderRight: "none", borderTop: "none", transform: "rotate(45deg)" }} />
          <div style={{ padding: "10px 10px 10px 14px", display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 6 }}>
            <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
              <span style={{ fontSize: 12, fontWeight: 700, color: "#be185d" }}>Enterprise only for now</span>
              <span style={{ fontSize: 11, color: "#9d174d", lineHeight: 1.45 }}>Join the waitlist to get early access.</span>
            </div>
            <button onClick={() => setShowEnterprisePopup(false)} style={{ flexShrink: 0, background: "none", border: "none", cursor: "pointer", color: "#be185d", fontSize: 15, lineHeight: 1, padding: "1px 3px", opacity: 0.6 }} onMouseEnter={e => e.currentTarget.style.opacity = "1"} onMouseLeave={e => e.currentTarget.style.opacity = "0.6"}>×</button>
          </div>
          <div style={{ height: 3, background: "linear-gradient(90deg, #f9a8d4, #E61B84)" }} />
        </div>
      )}
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
          if (ps === "archived") return <div className="payment-status-banner payment-status-archived">🗄️ Account archived — <a href="mailto:support@primble.ai">Contact support</a> to restore.</div>;
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
          const liteGradeColor = g => ({ A: "#10b981", B: "#22c55e", C: "#f59e0b", D: "#f97316", F: "#ef4444" }[g] || "#94a3b8");
          const liteGradeBg = g => ({ A: "rgba(16,185,129,0.08)", B: "rgba(34,197,94,0.08)", C: "rgba(245,158,11,0.08)", D: "rgba(249,115,22,0.08)", F: "rgba(239,68,68,0.08)" }[g] || "rgba(148,163,184,0.08)");
          const routingLabel = { auto_quote: "Auto-Route to Quoting", review: "Light Review", full_review: "Full Underwriter Review", hold: "Hold — Remediation Required" };
          const routingStyle = {
            auto_quote: { bg: "#dcfce7", color: "#166534", border: "#86efac" },
            review:     { bg: "#fef9c3", color: "#854d0e", border: "#fde047" },
            full_review:{ bg: "#fef2f2", color: "#991b1b", border: "#fecaca" },
            hold:       { bg: "#fee2e2", color: "#991b1b", border: "#fca5a5" },
          };
          const rd = sqs?.routing_decision;
          const rs = routingStyle[rd] || { bg: "#f1f5f9", color: "#475569", border: "#e2e8f0" };
          return (
            <div style={{ maxWidth: 960, margin: "0 auto", padding: "0 16px" }}>

              {/* ── Page header ── */}
              <div style={{ marginBottom: 28 }}>
                <div style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 13, fontWeight: 700, color: "#E61B84", letterSpacing: "0.08em", textTransform: "uppercase", background: "rgba(230,0,122,0.07)", padding: "3px 10px", borderRadius: 20, marginBottom: 10 }}>
                  Essentials
                </div>
                <h2 style={{ fontSize: 26, fontWeight: 700, color: "#0f172a", margin: "0 0 6px", letterSpacing: "-0.3px" }}>Submission Analysis</h2>
                <p style={{ fontSize: 13.5, color: "#64748b", margin: 0 }}>Your SQS score is ready. Use the tools below to complete your workflow.</p>
              </div>

              {/* ── SQS hero card ── */}
              <div style={{ background: "#fff", border: "1.5px solid #e2e8f0", borderRadius: 20, padding: "28px 36px", marginBottom: 16, boxShadow: "0 2px 8px rgba(0,0,0,0.05)" }}>
                {!sqs ? (
                  <div style={{ display: "flex", flexDirection: "column", alignItems: "center", padding: "24px 0", gap: 14 }}>
                    <span style={{ width: 40, height: 40, border: "3px solid #e2e8f0", borderTopColor: "#E61B84", borderRadius: "50%", display: "inline-block", animation: "spin 0.8s linear infinite" }} />
                    <div style={{ fontSize: 14, color: "#64748b", fontWeight: 500 }}>Scoring your submission…</div>
                    <div style={{ fontSize: 12, color: "#94a3b8" }}>This typically takes a few seconds</div>
                  </div>
                ) : (
                  <div>
                    <div style={{ fontSize: 15, fontWeight: 800, color: "#94a3b8", letterSpacing: "0.07em", textTransform: "uppercase", marginBottom: 20 }}>Submission Quality Score</div>
                    <div style={{ display: "flex", alignItems: "center", gap: 28, marginBottom: 20, flexWrap: "wrap" }}>

                      {/* Score circle */}
                      <div style={{ position: "relative", flexShrink: 0 }}>
                        <div style={{ width: 120, height: 120, borderRadius: "50%", background: liteGradeBg(sqs.grade), border: `3px solid ${liteGradeColor(sqs.grade)}`, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center" }}>
                          <span style={{ fontSize: 42, fontWeight: 900, color: liteGradeColor(sqs.grade), lineHeight: 1 }}>{sqs.sqs_score ?? "—"}</span>
                          <span style={{ fontSize: 12, fontWeight: 700, color: liteGradeColor(sqs.grade), opacity: 0.75, marginTop: 2 }}>/100</span>
                        </div>
                        <div style={{ position: "absolute", bottom: -4, right: -4, width: 32, height: 32, borderRadius: "50%", background: liteGradeColor(sqs.grade), display: "flex", alignItems: "center", justifyContent: "center", fontSize: 14, fontWeight: 800, color: "#fff", boxShadow: "0 2px 6px rgba(0,0,0,0.2)" }}>
                          {sqs.grade}
                        </div>
                      </div>

                      {/* Score details */}
                      <div style={{ flex: 1, minWidth: 200 }}>
                        <div style={{ fontSize: 18, fontWeight: 700, color: "#0f172a", marginBottom: 6 }}>{sqs.tier || "Submission Scored"}</div>
                        {rd && (
                          <div style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "5px 12px", borderRadius: 20, border: `1px solid ${rs.border}`, background: rs.bg, color: rs.color, fontSize: 12, fontWeight: 700, marginBottom: 12 }}>
                            {{ auto_quote: "✅", review: "🔍", full_review: "📋", hold: "🚫" }[rd]} {routingLabel[rd] || rd}
                          </div>
                        )}
                        {/* Breakdown pillars */}
                        {sqs.breakdown && Object.keys(sqs.breakdown).length > 0 && (
                          <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 4 }}>
                            {Object.entries(sqs.breakdown).slice(0, 4).map(([key, val]) => (
                              <div key={key}>
                                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, marginBottom: 2 }}>
                                  <span style={{ color: "#64748b" }}>{SQS_LABELS[key] || key}</span>
                                  <span style={{ fontWeight: 700, color: barColor(val) }}>{val}%</span>
                                </div>
                                <div style={{ height: 4, background: "#f1f5f9", borderRadius: 2, overflow: "hidden" }}>
                                  <div style={{ height: "100%", width: `${val}%`, background: barColor(val), borderRadius: 2, transition: "width 0.6s ease" }} />
                                </div>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>

                    {/* Stops — side by side on desktop, stacked on mobile */}
                    {(liteSqsData?.hard_stops?.length > 0 || liteSqsData?.soft_stops?.length > 0) && (
                      <div style={{ borderTop: "1px solid #f1f5f9", paddingTop: 16 }}>
                        <div className="lite-stops-grid">
                          {liteSqsData?.hard_stops?.length > 0 && (
                            <div style={{ background: "#fef2f2", border: "1px solid #fecaca", borderRadius: 10, padding: "12px 16px" }}>
                              <div style={{ fontSize: 11, fontWeight: 700, color: "#991b1b", marginBottom: 7 }}>Hard Stops — Must Resolve Before Submission</div>
                              {liteSqsData.hard_stops.map((s, i) => (
                                <div key={i} style={{ fontSize: 12, color: "#7f1d1d", padding: "2px 0", display: "flex", gap: 6 }}>
                                  <span style={{ flexShrink: 0 }}>•</span><span>{s}</span>
                                </div>
                              ))}
                            </div>
                          )}
                          {liteSqsData?.soft_stops?.length > 0 && (
                            <div style={{ background: "#fef2f2", border: "1px solid #fecaca", borderRadius: 10, padding: "12px 16px" }}>
                              <div style={{ fontSize: 11, fontWeight: 700, color: "#991b1b", marginBottom: 7 }}>Warnings — Will Cap Your Score</div>
                              {liteSqsData.soft_stops.map((s, i) => (
                                <div key={i} style={{ fontSize: 12, color: "#7f1d1d", padding: "2px 0", display: "flex", gap: 6 }}>
                                  <span style={{ flexShrink: 0 }}>•</span><span>{s}</span>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>

              {/* ── Action cards ── */}
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, marginBottom: 24 }}>

                {/* Send to Client (ARQ) */}
                <div style={{ background: "#fff", border: "1.5px solid #e2e8f0", borderRadius: 16, padding: "22px 24px 20px", display: "flex", flexDirection: "column", boxShadow: "0 1px 4px rgba(0,0,0,0.04)" }}>
                  <div style={{ width: 40, height: 40, borderRadius: 10, background: "rgba(230,0,122,0.08)", display: "flex", alignItems: "center", justifyContent: "center", marginBottom: 12 }}>
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#E61B84" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg>
                  </div>
                  <div style={{ fontSize: 14, fontWeight: 700, color: "#0f172a", marginBottom: 4 }}>Send to Client</div>
                  <div style={{ fontSize: 12, color: "#64748b", marginBottom: 16, lineHeight: 1.55, flex: 1 }}>Client-in-the-Loop™ — send a targeted questionnaire to fill gaps and improve your score.</div>
                  <button onClick={handleOpenARQ} disabled={arqLoadingQ}
                    style={{ width: "100%", padding: "11px 14px", borderRadius: 10, border: "none", background: arqLoadingQ ? "#e2e8f0" : "#E61B84", color: arqLoadingQ ? "#94a3b8" : "#fff", fontSize: 13, fontWeight: 700, cursor: arqLoadingQ ? "wait" : "pointer", fontFamily: "inherit", display: "flex", alignItems: "center", justifyContent: "center", gap: 6, transition: "background 0.15s, box-shadow 0.15s", boxShadow: arqLoadingQ ? "none" : "0 4px 12px rgba(230,0,122,0.25)" }}
                    onMouseEnter={e => { if (!arqLoadingQ) { e.currentTarget.style.background = "#C0157A"; e.currentTarget.style.boxShadow = "0 6px 18px rgba(230,0,122,0.35)"; } }}
                    onMouseLeave={e => { if (!arqLoadingQ) { e.currentTarget.style.background = "#E61B84"; e.currentTarget.style.boxShadow = "0 4px 12px rgba(230,0,122,0.25)"; } }}>
                    {arqLoadingQ ? <><span style={{ width: 11, height: 11, border: "2px solid #94a3b8", borderTopColor: "#475569", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" }} /> Loading…</> : "Send to Client (ARQ)"}
                  </button>
                  <ARQStatusPanel arqSessions={arqSessions} token={token} onRefresh={refreshArqData} />
                </div>

                {/* Cover Summary */}
                <div style={{ background: "#fff", border: "1.5px solid #e2e8f0", borderRadius: 16, padding: "22px 24px 20px", display: "flex", flexDirection: "column", boxShadow: "0 1px 4px rgba(0,0,0,0.04)" }}>
                  <div style={{ width: 40, height: 40, borderRadius: 10, background: "rgba(230,0,122,0.08)", display: "flex", alignItems: "center", justifyContent: "center", marginBottom: 12 }}>
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#E61B84" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>
                  </div>
                  <div style={{ fontSize: 14, fontWeight: 700, color: "#0f172a", marginBottom: 4 }}>Cover Summary</div>
                  <div style={{ fontSize: 12, color: "#64748b", marginBottom: 16, lineHeight: 1.55, flex: 1 }}>AI-generated SQS narrative cover sheet — submittable with any platform, ready to download.</div>
                  <button onClick={handleLiteCoverSheet} disabled={liteCoverLoading}
                    style={{ width: "100%", padding: "11px 14px", borderRadius: 10, border: "none", background: liteCoverLoading ? "#e2e8f0" : "#E61B84", color: liteCoverLoading ? "#94a3b8" : "#fff", fontSize: 13, fontWeight: 700, cursor: liteCoverLoading ? "wait" : "pointer", fontFamily: "inherit", display: "flex", alignItems: "center", justifyContent: "center", gap: 6, transition: "background 0.15s, box-shadow 0.15s", boxShadow: liteCoverLoading ? "none" : "0 4px 12px rgba(230,0,122,0.25)" }}
                    onMouseEnter={e => { if (!liteCoverLoading) { e.currentTarget.style.background = "#C0157A"; e.currentTarget.style.boxShadow = "0 6px 18px rgba(230,0,122,0.35)"; } }}
                    onMouseLeave={e => { if (!liteCoverLoading) { e.currentTarget.style.background = "#E61B84"; e.currentTarget.style.boxShadow = "0 4px 12px rgba(230,0,122,0.25)"; } }}>
                    {liteCoverLoading ? <><span style={{ width: 11, height: 11, border: "2px solid #94a3b8", borderTopColor: "#475569", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" }} /> Generating…</> : "Cover Summary"}
                  </button>
                </div>
              </div>

              {/* ── Footer nav ── */}
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", paddingTop: 4, gap: 12 }}>
                <button onClick={() => { resetToUpload(); }}
                  style={{ padding: "10px 22px", borderRadius: 10, border: "1.5px solid #fecaca", background: "#fef2f2", color: "#991b1b", fontSize: 13, fontWeight: 600, cursor: "pointer", fontFamily: "inherit", boxShadow: "0 2px 8px rgba(0,0,0,0.07)", transition: "box-shadow 0.15s, transform 0.15s, border-color 0.15s" }}
                  onMouseEnter={e => { e.currentTarget.style.boxShadow = "0 4px 16px rgba(0,0,0,0.12)"; e.currentTarget.style.transform = "translateY(-1px)"; e.currentTarget.style.borderColor = "#fca5a5"; }}
                  onMouseLeave={e => { e.currentTarget.style.boxShadow = "0 2px 8px rgba(0,0,0,0.07)"; e.currentTarget.style.transform = "none"; e.currentTarget.style.borderColor = "#fecaca"; }}>
                  ← New Submission
                </button>
                <button onClick={onShowUpgrade}
                  style={{ padding: "10px 22px", borderRadius: 10, border: "1.5px solid #fecaca", background: "#fef2f2", color: "#991b1b", fontSize: 13, fontWeight: 700, cursor: "pointer", fontFamily: "inherit", boxShadow: "0 2px 8px rgba(0,0,0,0.07)", transition: "box-shadow 0.15s, transform 0.15s, background 0.15s, border-color 0.15s" }}
                  onMouseEnter={e => { e.currentTarget.style.background = "#fee2e2"; e.currentTarget.style.boxShadow = "0 4px 16px rgba(0,0,0,0.12)"; e.currentTarget.style.transform = "translateY(-1px)"; e.currentTarget.style.borderColor = "#fca5a5"; }}
                  onMouseLeave={e => { e.currentTarget.style.background = "#fef2f2"; e.currentTarget.style.boxShadow = "0 2px 8px rgba(0,0,0,0.07)"; e.currentTarget.style.transform = "none"; e.currentTarget.style.borderColor = "#fecaca"; }}>
                  Unlock Full Forms
                </button>
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
                  style={{ padding: "13px 36px", background: "#E61B84", color: "#fff", border: "none", borderRadius: 10, fontSize: 15, fontWeight: 700, cursor: "pointer", boxShadow: "0 4px 14px rgba(230,0,122,0.3)" }}
                  onMouseEnter={e => { e.currentTarget.style.background = "#C0157A"; e.currentTarget.style.transform = "translateY(-1px)"; }}
                  onMouseLeave={e => { e.currentTarget.style.background = "#E61B84"; e.currentTarget.style.transform = "none"; }}>
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
          const activeBtn = files.length && !loading && !uploadBlocked;
          return (
            <div style={{ maxWidth: 640, margin: "0 auto", padding: "0 4px" }}>
              {/* Header */}
              <div style={{ textAlign: "center", marginBottom: 28 }}>
                <div style={{ display: "inline-block", fontSize: 10, fontWeight: 700, color: "#991b1b", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 10, padding: "3px 10px", background: "#fef2f2", border: "1px solid #fecaca", borderRadius: 20 }}>New Submission</div>
                <h2 style={{ fontSize: 26, fontWeight: 700, color: "#0f172a", margin: "0 0 6px", letterSpacing: "-0.3px" }}>Upload Documents</h2>
                <p style={{ fontSize: 13.5, color: "#64748b", margin: 0, lineHeight: 1.5 }}>Dec pages, loss runs, schedules, quotes — PDFs, images, or ZIP archives</p>
              </div>

              {/* Blocked banner */}
              {uploadBlocked && (
                <div style={{ background: "#fef2f2", border: "1px solid #fecaca", borderRadius: 10, padding: "11px 16px", marginBottom: 20, fontSize: 13, color: "#dc2626", textAlign: "center" }}>{blockMsg}</div>
              )}

              {/* Drop zone card */}
              <div style={{
                background: "#fff",
                borderRadius: 20,
                boxShadow: "0 2px 8px rgba(0,0,0,0.06), 0 8px 32px rgba(0,0,0,0.09), 0 0 0 1px rgba(0,0,0,0.04)",
                overflow: "hidden",
                padding: "8px",
              }}>
                {/* Drop target */}
                <input type="file" id="file-upload" accept=".pdf,.zip,.jpg,.jpeg,.png,.bmp,.tiff,.webp,application/pdf,application/zip,image/*" multiple disabled={uploadBlocked} onChange={e => setFiles(prev => [...prev, ...Array.from(e.target.files)])} style={{ display: "none" }} />
                <label htmlFor="file-upload"
                  ref={dropRef}
                  style={{
                    display: "block",
                    position: "relative",
                    padding: dragging ? "52px 32px" : "44px 32px",
                    border: `2px dashed ${dragging ? "#E61B84" : "#e2e8f0"}`,
                    borderRadius: 14,
                    background: dragging ? "rgba(230,0,122,0.03)" : "#fafbfc",
                    transition: "all 0.18s ease",
                    cursor: uploadBlocked ? "not-allowed" : "pointer",
                    textAlign: "center",
                  }}
                >
                  {/* Upload icon — SVG, no emoji */}
                  <div style={{ marginBottom: 16, display: "flex", justifyContent: "center" }}>
                    <svg width="44" height="44" viewBox="0 0 44 44" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ opacity: dragging ? 1 : 0.55, transition: "opacity 0.18s" }}>
                      <rect width="44" height="44" rx="12" fill={dragging ? "rgba(230,0,122,0.1)" : "#f1f5f9"} />
                      <path d="M22 28V18M22 18L18 22M22 18L26 22" stroke={dragging ? "#E61B84" : "#64748b"} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                      <path d="M14 31h16" stroke={dragging ? "#E61B84" : "#64748b"} strokeWidth="2" strokeLinecap="round"/>
                    </svg>
                  </div>

                  <p style={{ fontSize: 15, fontWeight: 600, color: "#1e293b", margin: "0 0 4px" }}>
                    Drag & drop files
                  </p>
                  <p style={{ fontSize: 13.5, color: "#64748b", margin: "0 0 12px" }}>
                    or <span style={{ color: "#E61B84", fontWeight: 600, textDecoration: "underline" }}>click to browse</span>
                  </p>
                  <p style={{ fontSize: 11.5, color: "#94a3b8", margin: 0, letterSpacing: "0.01em" }}>
                    PDFs · Images (JPG, PNG, BMP, TIFF) · ZIP archives
                  </p>
                </label>

                {/* File list */}
                {files.length > 0 && (
                  <div style={{ padding: "0 16px 16px", marginTop: -4 }}>
                    <div style={{ display: "flex", flexDirection: "column", gap: 6, maxHeight: 196, overflowY: "auto", paddingRight: 2 }}>
                      {files.map((f, i) => {
                        const isZip = f.name.toLowerCase().endsWith(".zip");
                        const isImg = f.type?.startsWith("image/");
                        const ext = f.name.split(".").pop()?.toUpperCase() || "FILE";
                        return (
                          <div key={i} style={{ display: "flex", alignItems: "center", gap: 10, padding: "9px 12px", background: "#f8fafc", border: "1px solid #e9edf2", borderRadius: 9, fontSize: 13 }}>
                            {/* Type badge */}
                            <span style={{
                              flexShrink: 0, width: 32, height: 32, borderRadius: 7,
                              background: isZip ? "#fef3c7" : isImg ? "#ede9fe" : "#dbeafe",
                              color: isZip ? "#92400e" : isImg ? "#6d28d9" : "#1d4ed8",
                              fontSize: 9, fontWeight: 800, letterSpacing: "0.04em",
                              display: "flex", alignItems: "center", justifyContent: "center",
                            }}>{isZip ? "ZIP" : isImg ? ext : "PDF"}</span>
                            <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "#1e293b", fontWeight: 500 }}>{f.name}</span>
                            <span style={{ fontSize: 11, color: "#94a3b8", flexShrink: 0 }}>{(f.size / 1024).toFixed(0)} KB</span>
                            <button
                              onClick={() => setFiles(prev => prev.filter((_, j) => j !== i))}
                              style={{ background: "none", border: "none", cursor: "pointer", color: "#cbd5e1", fontSize: 14, padding: "2px 4px", lineHeight: 1, borderRadius: 4, transition: "color 0.15s" }}
                              onMouseEnter={e => e.currentTarget.style.color = "#E61B84"}
                              onMouseLeave={e => e.currentTarget.style.color = "#cbd5e1"}
                              title="Remove file"
                            >✕</button>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}

                {/* CTA */}
                <div style={{ padding: "8px 8px 8px" }}>
                  <button
                    onClick={handleUpload}
                    disabled={!files.length || loading || uploadBlocked}
                    style={{
                      width: "100%",
                      padding: "13px 0",
                      borderRadius: 12,
                      border: "none",
                      background: loading ? "#cc006e" : "#E61B84",
                      color: "#fff",
                      fontSize: 14.5,
                      fontWeight: 700,
                      cursor: activeBtn ? "pointer" : "not-allowed",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      gap: 10,
                      boxShadow: "0 4px 18px rgba(230,0,122,0.32)",
                      transition: "all 0.18s ease",
                      letterSpacing: "0.01em",
                      opacity: uploadBlocked ? 0.6 : 1,
                    }}
                    onMouseEnter={e => { if (!loading) e.currentTarget.style.background = "#cc006e"; }}
                    onMouseLeave={e => { if (!loading) e.currentTarget.style.background = "#E61B84"; }}
                  >
                    {loading && (
                      <svg width="16" height="16" viewBox="0 0 16 16" fill="none" style={{ animation: "spin 0.8s linear infinite", flexShrink: 0 }}>
                        <circle cx="8" cy="8" r="6" stroke="rgba(255,255,255,0.35)" strokeWidth="2.5"/>
                        <path d="M8 2a6 6 0 0 1 6 6" stroke="#fff" strokeWidth="2.5" strokeLinecap="round"/>
                      </svg>
                    )}
                    {loading ? "Analyzing..." : files.length > 0 ? `Analyze ${files.length > 1 ? files.length + " Files" : "File"}` : "Analyze File"}
                  </button>
                </div>
              </div>
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
              <h2 className="step-title" style={{ color: "#1e293b" }}>Select Forms to Generate</h2>
              <p className="step-subtitle">Select the forms you need, then generate all at once.</p>
            </div>
            <div className="doc-summary">
              <div className="doc-summary-title">DOCUMENTS PROCESSED</div>
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
            {(hardStops.length > 0 || softStops.length > 0) && (
              <div className="stops-row">
                {hardStops.length > 0 && (
                  <div className="stops-banner stops-hard">
                    <div className="stops-title">Hard Stops - Must Fix Before Submission</div>
                    {hardStops.map((s, i) => <div key={i} className="stop-item stop-item-hard">- {s}</div>)}
                  </div>
                )}
                {softStops.length > 0 && (
                  <div className="stops-banner stops-soft">
                    <div className="stops-title">Warnings - Will Cap Your SQS Score</div>
                    {softStops.map((s, i) => <div key={i} className="stop-item stop-item-soft">- {s}</div>)}
                  </div>
                )}
              </div>
            )}
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
{loading ? "Generating..." : `Generate ${checkedFormIds.size} Form${checkedFormIds.size !== 1 ? "s" : ""} Now`}
            </button>
          </div>
        )}

        {step === "editor" && (
          <div className="editor-layout editor-layout-fullpage">
            <div className="editor-sidebar" style={{ background: "#fff", borderRight: "1px solid #e2e8f0", padding: 0, gap: 0 }}>
              <div style={{ padding: "14px 14px 12px" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
                  <span style={{ fontSize: 10, fontWeight: 700, color: "#94a3b8", letterSpacing: "0.06em", textTransform: "uppercase" }}>Generated Forms</span>
                  <span style={{ fontSize: 11, fontWeight: 700, color: "#E61B84", background: "rgba(230,0,122,0.08)", padding: "1px 7px", borderRadius: 20 }}>{formIdList.length}</span>
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 2, maxHeight: 130, overflowY: "auto" }}>
                  {formIdList.map(fid => {
                    const fd = generatedForms[fid]; const sq = fd?.sqs;
                    const isActive = activeFormId === fid;
                    return (
                      <div key={fid} onClick={() => setActiveFormId(fid)}
                        style={{ padding: "7px 9px", borderRadius: 7, cursor: "pointer", border: `1px solid ${isActive ? "#E61B84" : "transparent"}`, background: isActive ? "rgba(230,0,122,0.05)" : "transparent", transition: "all 0.15s" }}
                        onMouseEnter={e => { if (!isActive) e.currentTarget.style.background = "#f8fafc"; }}
                        onMouseLeave={e => { if (!isActive) e.currentTarget.style.background = "transparent"; }}>
                        <div style={{ fontSize: 12, fontWeight: 600, color: isActive ? "#E61B84" : "#1e293b" }}>
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
                      <div style={{ background: "#fdf2f8", border: "1px solid #f9a8d4", borderRadius: 7, padding: "7px 10px", marginBottom: 10, boxShadow: "0 2px 8px rgba(230,0,122,0.07)" }}>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
                          <span style={{ fontSize: 10, fontWeight: 700, color: "#000" }}>Quality Fill Rate</span>
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
                      <div style={{ background: "#fdf2f8", border: "1px solid #f9a8d4", borderRadius: 7, padding: "6px 10px", marginBottom: 10, display: "flex", alignItems: "center", gap: 8, boxShadow: "0 2px 8px rgba(230,0,122,0.07)" }}>
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
                      <div style={{ padding: "5px 9px", borderRadius: 7, fontSize: 11, fontWeight: 700, textAlign: "center", marginBottom: 12, background: "#fdf2f8", color: "#000", border: "1px solid #f9a8d4", boxShadow: "0 2px 8px rgba(230,0,122,0.07)" }}>
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
                                <span style={{ color: "#000" }}>
                                  {SQS_LABELS[key] || key}
                                  <span style={{ color: "#94a3b8" }}> ({SQS_WEIGHTS[key] || 0}%)</span>
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
                      <div style={{ background: "#fdf2f8", border: "1px solid #f9a8d4", borderRadius: 8, padding: "10px 12px", marginBottom: 10, boxShadow: "0 2px 8px rgba(230,0,122,0.07)" }}>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                          <div style={{ fontSize: 10, fontWeight: 700, color: "#000", textTransform: "uppercase", letterSpacing: "0.05em" }}>Package SQS</div>
                          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                            {packageSqs.lob && packageSqs.lob !== "generic" && (
                              <span style={{ fontSize: 9, fontWeight: 700, background: "rgba(230,0,122,0.08)", color: "#E61B84", borderRadius: 20, padding: "1px 6px", textTransform: "capitalize" }}>{packageSqs.lob}</span>
                            )}
                            <span style={{ fontSize: 16, fontWeight: 800, color: gradeColor(packageSqs.package_sqs_score >= 90 ? "A" : packageSqs.package_sqs_score >= 80 ? "B" : packageSqs.package_sqs_score >= 70 ? "C" : packageSqs.package_sqs_score >= 60 ? "D" : "F") }}>{packageSqs.package_sqs_score}</span>
                            <span style={{ fontSize: 9, color: "#94a3b8" }}>/100</span>
                          </div>
                        </div>
                        <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
                          {Object.entries(packageSqs.pillars || {}).map(([key, val]) => (
                            <div key={key}>
                              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, marginBottom: 2 }}>
                                <span style={{ color: "#000" }}>{PACKAGE_PILLAR_LABELS[key] || key}</span>
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
                      <div style={{ background: "#fdf2f8", borderRadius: 7, padding: "8px 10px", marginBottom: 8, border: "1px solid #f9a8d4", boxShadow: "0 2px 8px rgba(230,0,122,0.07)" }}>
                        <div style={{ fontSize: 10, fontWeight: 700, color: "#000", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 6 }}>Top Risk Drivers</div>
                        {activeSqs.risk_drivers.map((d, i) => (
                          <div key={i} style={{ display: "flex", alignItems: "center", gap: 6, padding: "3px 0", borderBottom: i < activeSqs.risk_drivers.length - 1 ? "1px solid #f9a8d4" : "none" }}>
                            <span style={{ fontSize: 10, fontWeight: 700, color: "#E61B84", width: 16 }}>#{i + 1}</span>
                            <span style={{ flex: 1, fontSize: 11, color: "#000" }}>{d.component}</span>
                            <span style={{ fontSize: 11, fontWeight: 700, color: barColor(d.score) }}>{d.score}%</span>
                          </div>
                        ))}
                      </div>
                    )}

                    {/* ── Issues ── */}
                    {activeSqs.issues?.length > 0 && (
                      <div style={{ background: "#fdf2f8", border: "1px solid #f9a8d4", borderRadius: 7, padding: "7px 10px", marginBottom: 8, boxShadow: "0 2px 8px rgba(230,0,122,0.07)" }}>
                        <div style={{ fontSize: 10, fontWeight: 700, color: "#000", marginBottom: 3 }}>⚠️ Issues</div>
                        {activeSqs.issues.map((s, i) => <div key={i} style={{ fontSize: 11, color: "#000", padding: "1px 0" }}>• {s}</div>)}
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
                    <div style={{ background: "#fdf2f8", border: "1px solid #f9a8d4", borderRadius: 8, padding: "8px 10px", boxShadow: "0 2px 8px rgba(230,0,122,0.07)" }}>
                      <div style={{ fontSize: 10, fontWeight: 700, color: "#000", letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: 8 }}>Cross-Form Validation</div>
                      {crossIssues.map((iss, i) => <div key={i} style={{ fontSize: 12, padding: "3px 0", color: "#000" }}>{iss.type === "hard_stop" ? "🚫" : "⚠️"} {iss.message}</div>)}
                    </div>
                  </div>
                </>
              )}

              <div style={{ height: 1, background: "#f1f5f9", margin: "0 14px" }} />
              <div style={{ padding: "12px 14px 16px", display: "flex", flexDirection: "column", gap: 8 }}>

                {/* Collapsible secondary actions — above Send to Client */}
                <div style={{ borderRadius: 14, overflow: "hidden", border: actionsOpen ? "1.5px solid #f9a8d4" : "1.5px solid #fce7f3", boxShadow: actionsOpen ? "0 8px 28px rgba(230,0,122,0.18)" : "0 2px 8px rgba(230,0,122,0.08)", transition: "box-shadow 0.25s, border-color 0.25s" }}>
                  {/* Toggle header */}
                  <button
                    onClick={() => setActionsOpen(o => !o)}
                    style={{ width: "100%", padding: "12px 16px", background: "linear-gradient(135deg, #E61B84 0%, #C0157A 100%)", border: "none", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", fontFamily: "inherit", fontSize: 13, fontWeight: 700, color: "#fff", letterSpacing: "0.02em", transition: "background 0.2s", gap: 0 }}
                    onMouseEnter={e => { e.currentTarget.style.background = "linear-gradient(135deg, #C0157A 0%, #a30055 100%)"; }}
                    onMouseLeave={e => { e.currentTarget.style.background = "linear-gradient(135deg, #E61B84 0%, #C0157A 100%)"; }}>
                    <span style={{ width: 13, flexShrink: 0 }} />
                    <span style={{ flex: 1, textAlign: "center" }}>More Actions</span>
                    <svg width="13" height="13" viewBox="0 0 14 14" fill="none" style={{ transition: "transform 0.25s cubic-bezier(0.4,0,0.2,1)", transform: actionsOpen ? "rotate(180deg)" : "rotate(0deg)", flexShrink: 0 }}>
                      <path d="M2.5 5L7 9.5L11.5 5" stroke="rgba(255,255,255,0.9)" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
                    </svg>
                  </button>

                  {/* Drawer */}
                  {actionsOpen && (
                    <div style={{ background: "#fff", borderTop: "1px solid #fce7f3", padding: "8px 8px 10px", display: "flex", flexDirection: "column", gap: 4, animation: "slideDown 0.18s ease-out" }}>

                      {/* ── Integrations group ── */}
                      <div style={{ position: "relative" }}>
                        <div style={{ borderRadius: 9, overflow: "hidden", border: "1px solid #fce7f3" }}>
                          <button
                            onClick={() => setIntegrationsExpanded(o => !o)}
                            style={{ display: "flex", alignItems: "center", justifyContent: "space-between", width: "100%", padding: "8px 12px", border: "none", background: "linear-gradient(135deg, #E61B84 0%, #C0157A 100%)", color: "#fff", fontSize: 12, fontWeight: 600, cursor: "pointer", fontFamily: "inherit", transition: "all 0.15s", textAlign: "left" }}
                            onMouseEnter={e => { e.currentTarget.style.background = "linear-gradient(135deg, #C0157A 0%, #a30055 100%)"; }}
                            onMouseLeave={e => { e.currentTarget.style.background = "linear-gradient(135deg, #E61B84 0%, #C0157A 100%)"; }}>
                            <span>Integrations</span>
                            <svg width="11" height="11" viewBox="0 0 14 14" fill="none" style={{ transition: "transform 0.2s", transform: integrationsExpanded ? "rotate(180deg)" : "rotate(0deg)", flexShrink: 0 }}>
                              <path d="M2.5 5L7 9.5L11.5 5" stroke="rgba(255,255,255,0.85)" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
                            </svg>
                          </button>

                          {integrationsExpanded && (
                            <div style={{ background: "#fdf2f8", padding: "6px 8px", display: "flex", flexDirection: "column", gap: 4 }}>
                              {/* Share to Epic */}
                              <button
                                onClick={e => {
                                  if (user?.subscription_tier === "enterprise") { handleSendToEpic(activeFormId); }
                                  else { triggerEnterprisePopup(e.currentTarget); }
                                }}
                                disabled={epicLoading}
                                style={{ width: "100%", padding: "7px 10px", borderRadius: 7, border: "1px solid #f9a8d4", background: epicSuccess ? "rgba(34,197,94,0.1)" : "#fce7f3", color: epicSuccess ? "#16a34a" : "#9d174d", fontSize: 11, fontWeight: 600, cursor: epicLoading ? "wait" : "pointer", fontFamily: "inherit", transition: "all 0.15s", textAlign: "center", display: "flex", alignItems: "center", justifyContent: "center", gap: 6 }}
                                onMouseEnter={e => { if (!epicSuccess && !epicLoading) e.currentTarget.style.background = "#f9a8d4"; }}
                                onMouseLeave={e => { if (!epicSuccess) e.currentTarget.style.background = "#fce7f3"; }}>
                                <span>{epicSuccess ? "Sent to Epic" : epicLoading ? "Sending…" : "Share to Epic"}</span>
                                {epicLoading && <span style={{ width: 9, height: 9, border: "2px solid #f9a8d4", borderTopColor: "#be185d", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" }} />}
                              </button>

                              {/* Share to Vertafore */}
                              <button
                                onClick={e => {
                                  if (user?.subscription_tier === "enterprise") { handleSendToVertafore(activeFormId); }
                                  else { triggerEnterprisePopup(e.currentTarget); }
                                }}
                                disabled={vertaforeLoading}
                                style={{ width: "100%", padding: "7px 10px", borderRadius: 7, border: "1px solid #f9a8d4", background: vertaforeSuccess ? "rgba(34,197,94,0.1)" : "#fce7f3", color: vertaforeSuccess ? "#16a34a" : "#9d174d", fontSize: 11, fontWeight: 600, cursor: vertaforeLoading ? "wait" : "pointer", fontFamily: "inherit", transition: "all 0.15s", textAlign: "center", display: "flex", alignItems: "center", justifyContent: "center", gap: 6 }}
                                onMouseEnter={e => { if (!vertaforeSuccess && !vertaforeLoading) e.currentTarget.style.background = "#f9a8d4"; }}
                                onMouseLeave={e => { if (!vertaforeSuccess) e.currentTarget.style.background = "#fce7f3"; }}>
                                <span>{vertaforeSuccess ? "Sent to Vertafore" : vertaforeLoading ? "Sending…" : "Share to Vertafore"}</span>
                                {vertaforeLoading && <span style={{ width: 9, height: 9, border: "2px solid #f9a8d4", borderTopColor: "#be185d", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" }} />}
                              </button>
                            </div>
                          )}
                        </div>

                      </div>

                      {/* ── Download group ── */}
                      <div style={{ borderRadius: 9, overflow: "hidden", border: "1px solid #fce7f3" }}>
                        <button
                          onClick={() => setDownloadExpanded(o => !o)}
                          style={{ display: "flex", alignItems: "center", justifyContent: "space-between", width: "100%", padding: "8px 12px", border: "none", background: "linear-gradient(135deg, #E61B84 0%, #C0157A 100%)", color: "#fff", fontSize: 12, fontWeight: 600, cursor: "pointer", fontFamily: "inherit", transition: "all 0.15s", textAlign: "left" }}
                          onMouseEnter={e => { e.currentTarget.style.background = "linear-gradient(135deg, #C0157A 0%, #a30055 100%)"; }}
                          onMouseLeave={e => { e.currentTarget.style.background = "linear-gradient(135deg, #E61B84 0%, #C0157A 100%)"; }}>
                          <span>Download</span>
                          <svg width="11" height="11" viewBox="0 0 14 14" fill="none" style={{ transition: "transform 0.2s", transform: downloadExpanded ? "rotate(180deg)" : "rotate(0deg)", flexShrink: 0 }}>
                            <path d="M2.5 5L7 9.5L11.5 5" stroke="rgba(255,255,255,0.85)" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
                          </svg>
                        </button>

                        {downloadExpanded && (
                          <div style={{ background: "#fdf2f8", padding: "6px 8px", display: "flex", flexDirection: "column", gap: 4 }}>
                            {/* This Form — no summary */}
                            <button
                              onClick={() => handleDownloadOneNoSummary(activeFormId)}
                              disabled={!activeFormId}
                              style={{ width: "100%", padding: "7px 10px", borderRadius: 7, border: "1px solid #f9a8d4", background: "#fce7f3", color: "#9d174d", fontSize: 11, fontWeight: 600, cursor: activeFormId ? "pointer" : "not-allowed", opacity: activeFormId ? 1 : 0.5, fontFamily: "inherit", transition: "all 0.15s", textAlign: "center" }}
                              onMouseEnter={e => { if (activeFormId) e.currentTarget.style.background = "#f9a8d4"; }}
                              onMouseLeave={e => { e.currentTarget.style.background = "#fce7f3"; }}>
                              This Form
                            </button>

                            {/* Entire Package — all forms + summary */}
                            <button
                              onClick={() => handleDownloadAll()}
                              style={{ width: "100%", padding: "7px 10px", borderRadius: 7, border: "1px solid #f9a8d4", background: "#fce7f3", color: "#9d174d", fontSize: 11, fontWeight: 600, cursor: "pointer", fontFamily: "inherit", transition: "all 0.15s", textAlign: "center" }}
                              onMouseEnter={e => { e.currentTarget.style.background = "#f9a8d4"; }}
                              onMouseLeave={e => { e.currentTarget.style.background = "#fce7f3"; }}>
                              Entire Package
                            </button>

                            {/* Submission Brief — summary only */}
                            <button
                              onClick={() => handleLiteCoverSheet()}
                              disabled={liteCoverLoading}
                              style={{ width: "100%", padding: "7px 10px", borderRadius: 7, border: "1px solid #f9a8d4", background: "#fce7f3", color: "#9d174d", fontSize: 11, fontWeight: 600, cursor: liteCoverLoading ? "wait" : "pointer", opacity: liteCoverLoading ? 0.6 : 1, fontFamily: "inherit", transition: "all 0.15s", textAlign: "center", display: "flex", alignItems: "center", justifyContent: "center", gap: 6 }}
                              onMouseEnter={e => { if (!liteCoverLoading) e.currentTarget.style.background = "#f9a8d4"; }}
                              onMouseLeave={e => { e.currentTarget.style.background = "#fce7f3"; }}>
                              <span>{liteCoverLoading ? "Generating…" : "Submission Brief"}</span>
                              {liteCoverLoading && <span style={{ width: 9, height: 9, border: "2px solid #f9a8d4", borderTopColor: "#be185d", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" }} />}
                            </button>
                          </div>
                        )}
                      </div>

                    </div>
                  )}
                </div>

                {/* Primary CTA — Client-in-the-Loop™ */}
                <button onClick={handleOpenARQ} disabled={arqLoadingQ}
                  style={{ width: "100%", padding: "12px 16px", borderRadius: 14, border: "none", background: "linear-gradient(135deg, #E61B84 0%, #C0157A 100%)", color: "#fff", fontSize: 13, fontWeight: 700, cursor: arqLoadingQ ? "wait" : "pointer", fontFamily: "inherit", display: "flex", alignItems: "center", justifyContent: "center", gap: 8, opacity: arqLoadingQ ? 0.7 : 1, boxShadow: "0 4px 16px rgba(230,0,122,0.35), 0 1px 3px rgba(230,0,122,0.2)", letterSpacing: "0.02em", transition: "all 0.2s" }}
                  onMouseEnter={e => { if (!arqLoadingQ) { e.currentTarget.style.background = "linear-gradient(135deg, #C0157A 0%, #a30055 100%)"; e.currentTarget.style.boxShadow = "0 6px 20px rgba(230,0,122,0.45), 0 1px 3px rgba(230,0,122,0.2)"; e.currentTarget.style.transform = "translateY(-1px)"; } }}
                  onMouseLeave={e => { e.currentTarget.style.background = "linear-gradient(135deg, #E61B84 0%, #C0157A 100%)"; e.currentTarget.style.boxShadow = "0 4px 16px rgba(230,0,122,0.35), 0 1px 3px rgba(230,0,122,0.2)"; e.currentTarget.style.transform = "translateY(0)"; }}>
                  {arqLoadingQ
                    ? <><span style={{ width: 12, height: 12, border: "2px solid rgba(255,255,255,0.5)", borderTopColor: "#fff", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" }} /> Loading…</>
                    : <>Send to Client{arqNotifCount > 0 && <span style={{ background: "#fff", color: "#E61B84", borderRadius: 10, fontSize: 10, padding: "2px 7px", fontWeight: 800, marginLeft: 2 }}>{arqNotifCount}</span>}</>
                  }
                </button>
                <ARQStatusPanel arqSessions={arqSessions} token={token} onRefresh={refreshArqData} />

                {/* Dashboard — return to recent forms */}
                <button onClick={goToDashboard}
                  style={{ width: "100%", padding: "12px 16px", borderRadius: 14, border: "none", background: "linear-gradient(135deg, #E61B84 0%, #C0157A 100%)", color: "#fff", fontSize: 13, fontWeight: 700, cursor: "pointer", fontFamily: "inherit", letterSpacing: "0.02em", boxShadow: "0 4px 16px rgba(230,0,122,0.35), 0 1px 3px rgba(230,0,122,0.2)", transition: "all 0.2s" }}
                  onMouseEnter={e => { e.currentTarget.style.background = "linear-gradient(135deg, #C0157A 0%, #a30055 100%)"; e.currentTarget.style.boxShadow = "0 6px 20px rgba(230,0,122,0.45), 0 1px 3px rgba(230,0,122,0.2)"; e.currentTarget.style.transform = "translateY(-1px)"; }}
                  onMouseLeave={e => { e.currentTarget.style.background = "linear-gradient(135deg, #E61B84 0%, #C0157A 100%)"; e.currentTarget.style.boxShadow = "0 4px 16px rgba(230,0,122,0.35), 0 1px 3px rgba(230,0,122,0.2)"; e.currentTarget.style.transform = "translateY(0)"; }}>
                  Dashboard
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
            <div style={{ width: 80, height: 80, borderRadius: "50%", background: "linear-gradient(135deg, #E61B84, #C0157A)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 36, color: "#fff", margin: "0 auto 24px", boxShadow: "0 8px 28px rgba(230,0,122,0.3)", animation: "successPop 0.5s ease-out" }}>✓</div>
            <h2 style={{ fontSize: 26, fontWeight: 800, color: "#0f172a", marginBottom: 8 }}>Download Complete!</h2>
            <p style={{ fontSize: 15, color: "#64748b", marginBottom: 28, lineHeight: 1.6 }}>Your filled ACORD forms have been downloaded successfully.</p>
            {user && user.subscription_tier === "free" && (
              <div style={{ background: "rgba(230,0,122,0.05)", border: "1px solid rgba(230,0,122,0.15)", borderRadius: 10, padding: "12px 16px", marginBottom: 24, fontSize: 14, color: "#1e293b" }}>
                You have <strong style={{ color: "#E61B84" }}>{Math.max(0, user.downloads_remaining)}</strong> free download{user.downloads_remaining !== 1 ? "s" : ""} remaining
              </div>
            )}
            <div style={{ display: "flex", flexDirection: "column", gap: 10, alignItems: "center" }}>
              <button onClick={() => setStep("editor")}
                style={{ minWidth: 260, padding: "12px 0", borderRadius: 10, border: "none", background: "#E61B84", color: "#fff", fontSize: 14, fontWeight: 700, cursor: "pointer", boxShadow: "0 4px 14px rgba(230,0,122,0.3)" }}
                onMouseEnter={e => e.currentTarget.style.background = "#C0157A"}
                onMouseLeave={e => e.currentTarget.style.background = "#E61B84"}>
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