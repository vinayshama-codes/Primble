import { useState, useEffect, useRef, forwardRef, useImperativeHandle } from "react";
import { API_BASE } from "../../config/constants";
import { gradeColor, barColor } from "../../utils/formatters";
import ProcessStageOverlay from "../overlays/ProcessStageOverlay";
import PDFJsViewer from "./PDFJsViewer";
const SQS_LABELS = {
  structural_completeness: "Structural Completeness",
  exposure_consistency: "Exposure Consistency",
  property_integrity: "Property Integrity",
  loss_history_alignment: "Loss History",
  umbrella_limit_adequacy: "Umbrella Adequacy",
  narrative_quality: "Narrative Quality"
};
const SQS_WEIGHTS = {
  structural_completeness: 25,
  exposure_consistency: 25,
  property_integrity: 15,
  loss_history_alignment: 15,
  umbrella_limit_adequacy: 10,
  narrative_quality: 10
};
const PACKAGE_PILLAR_LABELS = {
  // Spec-compliant pillar keys returned by calculate_package_sqs.
  structural_completeness: "Structural Completeness",
  exposure_consistency: "Exposure Consistency",
  property_integrity: "Property Integrity",
  loss_history_alignment: "Loss History",
  umbrella_limit_adequacy: "Umbrella Adequacy",
  narrative_quality: "Narrative Quality",
  // Legacy keys (older session payloads) kept for backward-compat display.
  data_integrity: "Data Integrity",
  exposure_cope: "Exposure & COPE",
  consistency: "Cross-Form Consistency",
  loss_history: "Loss History",
  narrative: "Narrative Quality"
};
const REC_TYPE_STYLE = {
  hard_stop: { bg: "#fdf2f8", border: "#f9a8d4", color: "#000" },
  soft_warning: { bg: "#fdf2f8", border: "#f9a8d4", color: "#000" },
  missing_field: { bg: "#fdf2f8", border: "#f9a8d4", color: "#000" },
  suggestion: { bg: "#fdf2f8", border: "#f9a8d4", color: "#000" }
};
const FALLBACK_CHAT_REPLY = "I'm not sure about that. Please contact your agent or broker for assistance.";
function DeleteConfirmModal({ onConfirm, onCancel }) {
  return /* @__PURE__ */ React.createElement("div", { style: { position: "fixed", inset: 0, background: "rgba(15,23,42,0.7)", backdropFilter: "blur(6px)", zIndex: 99999, display: "flex", alignItems: "center", justifyContent: "center", padding: 20 } }, /* @__PURE__ */ React.createElement("div", { style: { background: "#fff", borderRadius: 16, padding: "32px 28px", maxWidth: 400, width: "100%", boxShadow: "0 24px 60px rgba(0,0,0,0.25)", animation: "slideUp 0.2s ease-out" } }, /* @__PURE__ */ React.createElement("div", { style: { width: 52, height: 52, borderRadius: "50%", background: "#fef2f2", border: "2px solid #fecaca", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 22, margin: "0 auto 18px" } }), /* @__PURE__ */ React.createElement("h3", { style: { textAlign: "center", fontSize: 18, fontWeight: 700, color: "#0f172a", marginBottom: 8 } }, "Delete Session?"), /* @__PURE__ */ React.createElement("p", { style: { textAlign: "center", fontSize: 14, color: "#64748b", lineHeight: 1.6, marginBottom: 24 } }, "This submission package will be permanently deleted and cannot be recovered."), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 10 } }, /* @__PURE__ */ React.createElement("button", { onClick: onCancel, style: { flex: 1, padding: "10px 0", borderRadius: 8, border: "1px solid #e2e8f0", background: "#f8fafc", color: "#475569", fontSize: 14, fontWeight: 600, cursor: "pointer" } }, "Cancel"), /* @__PURE__ */ React.createElement("button", { onClick: onConfirm, style: { flex: 1, padding: "10px 0", borderRadius: 8, border: "none", background: "#dc2626", color: "#fff", fontSize: 14, fontWeight: 600, cursor: "pointer" } }, "Delete"))));
}
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
    questions.forEach((q) => {
      init[q.field_name] = true;
    });
    setSelectedQuestions(init);
  }, [questions]);
  const handleToggle = (fn) => setSelectedQuestions((prev) => ({ ...prev, [fn]: !prev[fn] }));
  const handleSelectAll = () => {
    const next = !selectAll;
    setSelectAll(next);
    const updated = {};
    questions.forEach((q) => {
      updated[q.field_name] = next;
    });
    setSelectedQuestions(updated);
  };
  const sanitizeEmail = (val) => val.trim().toLowerCase().slice(0, 254);
  const selectedCount = Object.values(selectedQuestions).filter(Boolean).length;
  const isEmailValid = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(clientEmail);
  const canSend = isEmailValid && selectedCount > 0;
  const handleSend = async () => {
    if (!canSend) return;
    setEmailTouched(true);
    setSending(true);
    setError("");
    const selectedList = questions.filter((q) => selectedQuestions[q.field_name]);
    try {
      const res = await fetch(`${API_BASE}/api/arq/send`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          client_email: sanitizeEmail(clientEmail),
          client_name: clientName.trim().slice(0, 100),
          questions: selectedList
        })
      });
      const data = await res.json();
      if (res.ok && data.success) onSuccess(data);
      else setError(data.detail || data.message || "Failed to send questionnaire.");
    } catch (e) {
      setError("Network error: " + e.message);
    } finally {
      setSending(false);
    }
  };
  return /* @__PURE__ */ React.createElement("div", { style: { position: "fixed", inset: 0, background: "rgba(15,23,42,0.75)", backdropFilter: "blur(8px)", zIndex: 99999, display: "flex", alignItems: "center", justifyContent: "center", padding: "16px" } }, /* @__PURE__ */ React.createElement("div", { onClick: (e) => e.stopPropagation(), style: { background: "#fff", borderRadius: 20, width: "100%", maxWidth: 620, maxHeight: "92vh", overflow: "hidden", display: "flex", flexDirection: "column", boxShadow: "0 32px 80px rgba(0,0,0,0.2)" } }, /* @__PURE__ */ React.createElement("div", { style: { padding: "24px 28px 0", flexShrink: 0 } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 20 } }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, fontWeight: 700, color: "#E61B84", marginBottom: 4, letterSpacing: "0.05em", textTransform: "uppercase" } }, "Client Questionnaire"), /* @__PURE__ */ React.createElement("h2", { style: { fontSize: 22, fontWeight: 700, color: "#0f172a", margin: 0 } }, "Send to Client"), /* @__PURE__ */ React.createElement("p", { style: { fontSize: 13, color: "#64748b", marginTop: 4 } }, "Client answers will auto-populate your ACORD forms.")), /* @__PURE__ */ React.createElement(
    "button",
    {
      onClick: onClose,
      style: { width: 32, height: 32, borderRadius: "50%", border: "1px solid #E61B84", background: "rgba(230,0,122,0.08)", color: "#E61B84", fontSize: 16, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0, transition: "all 0.2s" },
      onMouseEnter: (e) => {
        e.currentTarget.style.background = "#E61B84";
        e.currentTarget.style.color = "#fff";
      },
      onMouseLeave: (e) => {
        e.currentTarget.style.background = "rgba(230,0,122,0.08)";
        e.currentTarget.style.color = "#E61B84";
      }
    },
    "\u2715"
  )), error && /* @__PURE__ */ React.createElement("div", { style: { background: "#fef2f2", border: "1px solid #fecaca", borderRadius: 8, padding: "10px 14px", marginBottom: 16, color: "#dc2626", fontSize: 13 } }, error), /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 20 } }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("label", { style: { display: "block", fontSize: 12, fontWeight: 600, color: "#374151", marginBottom: 6 } }, "Client Email ", /* @__PURE__ */ React.createElement("span", { style: { color: "#E61B84" } }, "*")), /* @__PURE__ */ React.createElement(
    "input",
    {
      type: "email",
      value: clientEmail,
      onChange: (e) => {
        setClientEmail(e.target.value);
        setEmailTouched(true);
      },
      onBlur: (e) => {
        setEmailTouched(true);
        e.target.style.borderColor = "#e2e8f0";
      },
      onFocus: (e) => e.target.style.borderColor = "#E61B84",
      placeholder: "client@company.com",
      maxLength: 254,
      style: { width: "100%", padding: "9px 12px", border: "1px solid #e2e8f0", borderRadius: 8, fontSize: 13, outline: "none", boxSizing: "border-box" }
    }
  ), emailTouched && clientEmail && !isEmailValid && /* @__PURE__ */ React.createElement("p", { style: { fontSize: 11, color: "#ef4444", marginTop: 4 } }, "Please enter a valid email address.")), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("label", { style: { display: "block", fontSize: 12, fontWeight: 600, color: "#374151", marginBottom: 6 } }, "First Name ", /* @__PURE__ */ React.createElement("span", { style: { color: "#94a3b8", fontWeight: 400 } }, "(optional)")), /* @__PURE__ */ React.createElement(
    "input",
    {
      type: "text",
      value: clientName,
      onChange: (e) => setClientName(e.target.value),
      placeholder: "e.g. John",
      maxLength: 100,
      style: { width: "100%", padding: "9px 12px", border: "1px solid #e2e8f0", borderRadius: 8, fontSize: 13, outline: "none", boxSizing: "border-box" },
      onFocus: (e) => e.target.style.borderColor = "#E61B84",
      onBlur: (e) => e.target.style.borderColor = "#e2e8f0"
    }
  ))), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10, paddingBottom: 10, borderBottom: "1px solid #f1f5f9" } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 13, fontWeight: 600, color: "#1e293b" } }, "Questions ", /* @__PURE__ */ React.createElement("span", { style: { color: "#64748b", fontWeight: 400 } }, "(", selectedCount, "/", questions.length, " selected)")), /* @__PURE__ */ React.createElement("button", { onClick: handleSelectAll, style: { fontSize: 12, fontWeight: 600, color: "#4f7cff", background: "rgba(79,124,255,0.06)", border: "1px solid rgba(79,124,255,0.2)", borderRadius: 6, padding: "3px 10px", cursor: "pointer" } }, selectAll ? "Deselect All" : "Select All"))), /* @__PURE__ */ React.createElement("div", { style: { flex: 1, overflowY: "auto", padding: "0 28px 4px" } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 8 } }, questions.map((q, idx) => /* @__PURE__ */ React.createElement(
    "div",
    {
      key: idx,
      onClick: () => handleToggle(q.field_name),
      style: { border: `1.5px solid ${selectedQuestions[q.field_name] ? "#E61B84" : "#e2e8f0"}`, borderRadius: 10, padding: "10px 14px", cursor: "pointer", background: selectedQuestions[q.field_name] ? "rgba(230,0,122,0.03)" : "#fafafa", display: "flex", alignItems: "flex-start", gap: 10, opacity: selectedQuestions[q.field_name] ? 1 : 0.5, transition: "all 0.15s" }
    },
    /* @__PURE__ */ React.createElement("input", { type: "checkbox", checked: !!selectedQuestions[q.field_name], onChange: () => handleToggle(q.field_name), onClick: (e) => e.stopPropagation(), style: { marginTop: 3, width: 15, height: 15, cursor: "pointer", accentColor: "#E61B84", flexShrink: 0 } }),
    /* @__PURE__ */ React.createElement("div", { style: { flex: 1, minWidth: 0 } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10, fontWeight: 700, color: "#E61B84", background: "#fdf2f8", padding: "1px 7px", borderRadius: 20, display: "inline-block", marginBottom: 4 } }, "ACORD ", q.forms), /* @__PURE__ */ React.createElement("p", { style: { margin: 0, fontSize: 13, fontWeight: 600, color: "#0f172a", lineHeight: 1.45 } }, q.question), q.current_value && /* @__PURE__ */ React.createElement("p", { style: { margin: "3px 0 0", fontSize: 11, color: "#94a3b8" } }, "Current: ", q.current_value))
  )))), /* @__PURE__ */ React.createElement("div", { style: { padding: "16px 28px 24px", flexShrink: 0, borderTop: "1px solid #f1f5f9", marginTop: 8 } }, /* @__PURE__ */ React.createElement(
    "button",
    {
      onClick: handleSend,
      disabled: !canSend || sending,
      style: { width: "100%", padding: "12px 0", borderRadius: 10, border: "none", background: canSend && !sending ? "#E61B84" : "#e2e8f0", color: canSend && !sending ? "#fff" : "#94a3b8", fontSize: 14, fontWeight: 700, cursor: canSend && !sending ? "pointer" : "not-allowed", display: "flex", alignItems: "center", justifyContent: "center", gap: 8, minHeight: 46 }
    },
    sending ? /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("span", { style: { width: 14, height: 14, border: "2px solid rgba(255,255,255,0.4)", borderTopColor: "#fff", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" } }), "Sending\u2026") : `Send ${selectedCount} Question${selectedCount !== 1 ? "s" : ""} to Client`
  ), emailTouched && clientEmail && !isEmailValid && /* @__PURE__ */ React.createElement("p", { style: { fontSize: 11, color: "#ef4444", textAlign: "center", marginTop: 8 } }, "Please enter a valid email address."), /* @__PURE__ */ React.createElement("p", { style: { fontSize: 11, color: "#94a3b8", textAlign: "center", marginTop: 10 } }, "Client receives a secure link valid for 72 hours."))));
}
function ARQStatusPanel({ arqSessions, token, onRefresh }) {
  const [reminding, setReminding] = useState(null);
  const handleRemind = async (arq_id) => {
    setReminding(arq_id);
    try {
      await fetch(`${API_BASE}/api/arq/remind/${arq_id}`, { method: "POST", credentials: "include" });
      onRefresh();
    } catch (_) {
    }
    setReminding(null);
  };
  const fmtDate = (iso) => iso ? new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "\u2014";
  if (!arqSessions || arqSessions.length === 0) return null;
  return /* @__PURE__ */ React.createElement("div", { style: { marginTop: 8 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, fontWeight: 700, color: "#94a3b8", letterSpacing: "0.06em", marginBottom: 5, textTransform: "uppercase" } }, "Sent Questionnaires"), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 5 } }, arqSessions.map((arq) => {
    const isExpired = /* @__PURE__ */ new Date() > new Date(arq.expires_at) && arq.status !== "submitted";
    const status = isExpired ? "expired" : arq.status;
    const sc = { submitted: { bg: "#dcfce7", color: "#166534", border: "#86efac", label: "\u2713 Done" }, expired: { bg: "#f1f5f9", color: "#64748b", border: "#cbd5e1", label: "Expired" }, pending: { bg: "#fef9c3", color: "#854d0e", border: "#fde047", label: "Pending" } }[status] || {};
    return /* @__PURE__ */ React.createElement("div", { key: arq.id, style: { background: "#fff", border: "1px solid #e2e8f0", borderRadius: 8, padding: "7px 10px" } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 } }, /* @__PURE__ */ React.createElement("div", { style: { minWidth: 0, flex: 1 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, fontWeight: 600, color: "#1e293b", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } }, arq.client_name ? `${arq.client_name} (${arq.email})` : arq.email), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "#94a3b8", marginTop: 1 } }, fmtDate(arq.created_at))), /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10, fontWeight: 700, padding: "2px 7px", borderRadius: 20, border: `1px solid ${sc.border}`, background: sc.bg, color: sc.color, flexShrink: 0 } }, sc.label)), arq.status === "pending" && !isExpired && /* @__PURE__ */ React.createElement(
      "button",
      {
        onClick: () => handleRemind(arq.id),
        disabled: reminding === arq.id,
        style: { marginTop: 5, fontSize: 10, fontWeight: 600, color: "#4f7cff", background: "rgba(79,124,255,0.06)", border: "1px solid rgba(79,124,255,0.2)", borderRadius: 5, padding: "2px 8px", cursor: reminding === arq.id ? "wait" : "pointer", opacity: reminding === arq.id ? 0.6 : 1 }
      },
      reminding === arq.id ? "Sending\u2026" : "Remind",
      arq.reminder_count > 0 && ` (${arq.reminder_count})`
    ));
  })));
}
function SidePanelRec({ rec, index, sqsScore, onDismiss }) {
  const [reason, setReason] = useState("");
  const isObj = typeof rec === "object" && rec !== null;
  const msg = isObj ? rec.message : rec;
  const impact = isObj ? rec.score_impact : null;
  const recId = isObj ? rec.rec_id : `legacy_${index}`;
  const recType = isObj ? rec.type : "suggestion";
  const st = REC_TYPE_STYLE[recType] || REC_TYPE_STYLE.suggestion;
  const submit = () => onDismiss(rec, sqsScore, reason);
  const dismiss = () => onDismiss(rec, sqsScore, "");
  return /* @__PURE__ */ React.createElement("div", { style: { background: st.bg, border: `1px solid ${st.border}`, borderRadius: 8, padding: "8px 10px", boxShadow: "0 2px 8px rgba(230,0,122,0.07)" } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "flex-start", gap: 7 } }, /* @__PURE__ */ React.createElement("div", { style: { flex: 1, minWidth: 0 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: st.color, fontWeight: 600, lineHeight: 1.4 } }, msg), impact > 0 && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "#000", fontWeight: 700, marginTop: 2 } }, "+", impact, " pts if fixed"))), isObj && /* @__PURE__ */ React.createElement("div", { style: { marginTop: 7, display: "flex", gap: 5, alignItems: "center" } }, /* @__PURE__ */ React.createElement(
    "input",
    {
      placeholder: "Add a reason (optional)\u2026",
      value: reason,
      onChange: (e) => setReason(e.target.value),
      onKeyDown: (e) => {
        if (e.key === "Enter") submit();
      },
      style: { flex: 1, fontSize: 10, padding: "3px 7px", border: "1px solid #e2e8f0", borderRadius: 5, outline: "none", fontFamily: "inherit", minWidth: 0 }
    }
  ), reason.trim() && /* @__PURE__ */ React.createElement(
    "button",
    {
      onMouseDown: (e) => {
        e.preventDefault();
        submit();
      },
      style: { padding: "3px 8px", borderRadius: 5, border: "1px solid #6366f1", background: "#6366f1", fontSize: 10, fontWeight: 600, color: "#fff", cursor: "pointer", whiteSpace: "nowrap" }
    },
    "Submit"
  ), /* @__PURE__ */ React.createElement(
    "button",
    {
      onMouseDown: (e) => {
        e.preventDefault();
        dismiss();
      },
      style: { padding: "3px 8px", borderRadius: 5, border: "1px solid #e2e8f0", background: "#f8fafc", fontSize: 10, fontWeight: 600, color: "#64748b", cursor: "pointer", whiteSpace: "nowrap" }
    },
    "Dismiss"
  )));
}
function DownloadPreflightModal({ openRecs, narrative, overrideReason, onOverrideChange, onProceed, onCancel, loading }) {
  const hardRecs = openRecs.filter((r) => r.recommendation_type === "hard_stop");
  const softRecs = openRecs.filter((r) => r.recommendation_type !== "hard_stop");
  return /* @__PURE__ */ React.createElement("div", { style: { position: "fixed", inset: 0, background: "rgba(15,23,42,0.75)", backdropFilter: "blur(6px)", zIndex: 99999, display: "flex", alignItems: "center", justifyContent: "center", padding: 20 } }, /* @__PURE__ */ React.createElement("div", { style: { background: "#fff", borderRadius: 16, padding: "28px 28px 24px", maxWidth: 520, width: "100%", boxShadow: "0 24px 60px rgba(0,0,0,0.22)", display: "flex", flexDirection: "column", gap: 0, maxHeight: "88vh", overflow: "hidden" } }, /* @__PURE__ */ React.createElement("div", { style: { flexShrink: 0 } }, /* @__PURE__ */ React.createElement("div", { style: { marginBottom: 14 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 16, fontWeight: 700, color: "#0f172a" } }, "SQS Review"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 12, color: "#64748b" } }, openRecs.length > 0 ? `${openRecs.length} item${openRecs.length !== 1 ? "s" : ""} flagged \u2014 review before downloading` : "All clear \u2014 review the SQS summary below"))), /* @__PURE__ */ React.createElement("div", { style: { flex: 1, overflowY: "auto", marginBottom: 16 } }, hardRecs.length > 0 && /* @__PURE__ */ React.createElement("div", { style: { background: "#fef2f2", border: "1px solid #fca5a5", borderRadius: 8, padding: "10px 12px", marginBottom: 10 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, fontWeight: 700, color: "#991b1b", marginBottom: 6 } }, "Hard Stops (", hardRecs.length, ")"), hardRecs.map((r, i) => /* @__PURE__ */ React.createElement("div", { key: i, style: { fontSize: 12, color: "#7f1d1d", padding: "2px 0" } }, "\u2022 ", r.message, r.score_impact ? /* @__PURE__ */ React.createElement("span", { style: { color: "#dc2626", fontWeight: 700 } }, " (\u2013", r.score_impact, " pts)") : ""))), softRecs.length > 0 && /* @__PURE__ */ React.createElement("div", { style: { background: "#fffbeb", border: "1px solid #fde68a", borderRadius: 8, padding: "10px 12px", marginBottom: 10 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, fontWeight: 700, color: "#92400e", marginBottom: 6 } }, "Open Recommendations (", softRecs.length, ")"), softRecs.map((r, i) => /* @__PURE__ */ React.createElement("div", { key: i, style: { fontSize: 12, color: "#78350f", padding: "2px 0" } }, "\u2022 ", r.message, r.score_impact > 0 ? /* @__PURE__ */ React.createElement("span", { style: { color: "#d97706", fontWeight: 600 } }, " (+", r.score_impact, " pts if fixed)") : ""))), narrative && /* @__PURE__ */ React.createElement("div", { style: { background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: 10, padding: "16px 18px", marginTop: softRecs.length > 0 || hardRecs.length > 0 ? 10 : 0 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, fontWeight: 700, color: "#94a3b8", letterSpacing: "0.05em", textTransform: "uppercase", marginBottom: 10 } }, "SQS Analysis Summary"), /* @__PURE__ */ React.createElement("p", { style: { fontSize: 13, color: "#334155", lineHeight: 1.75, margin: 0 } }, narrative.replace(/\n+/g, " ").trim()))), /* @__PURE__ */ React.createElement("div", { style: { flexShrink: 0 } }, /* @__PURE__ */ React.createElement("div", { style: { marginBottom: 12 } }, /* @__PURE__ */ React.createElement("label", { style: { display: "block", fontSize: 12, fontWeight: 600, color: "#374151", marginBottom: 5 } }, "Override Note ", /* @__PURE__ */ React.createElement("span", { style: { color: "#94a3b8", fontWeight: 400 } }, "(recommended for E&O record)")), /* @__PURE__ */ React.createElement(
    "textarea",
    {
      value: overrideReason,
      onChange: (e) => onOverrideChange(e.target.value),
      placeholder: "e.g. Client acknowledged gaps and approved submission as-is",
      rows: 2,
      style: { width: "100%", padding: "8px 10px", border: "1px solid #e2e8f0", borderRadius: 8, fontSize: 12, resize: "vertical", outline: "none", fontFamily: "inherit", boxSizing: "border-box" },
      onFocus: (e) => e.target.style.borderColor = "#E61B84",
      onBlur: (e) => e.target.style.borderColor = "#e2e8f0"
    }
  )), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 8 } }, /* @__PURE__ */ React.createElement("button", { onClick: onCancel, style: { flex: 1, padding: "9px 0", borderRadius: 8, border: "1px solid #e2e8f0", background: "#f8fafc", color: "#475569", fontSize: 13, fontWeight: 600, cursor: "pointer" } }, "Cancel"), /* @__PURE__ */ React.createElement(
    "button",
    {
      onClick: onProceed,
      disabled: loading,
      style: { flex: 2, padding: "9px 0", borderRadius: 8, border: "none", background: !loading ? "#E61B84" : "#e2e8f0", color: !loading ? "#fff" : "#94a3b8", fontSize: 13, fontWeight: 700, cursor: !loading ? "pointer" : "not-allowed", display: "flex", alignItems: "center", justifyContent: "center", gap: 6 }
    },
    loading ? /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("span", { style: { width: 11, height: 11, border: "2px solid rgba(255,255,255,0.5)", borderTopColor: "#fff", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" } }), "Processing\u2026") : "Download Anyway"
  )))));
}
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
        fetch(`${API_BASE}/api/sessions`, { credentials: "include" }).then((r) => r.ok ? r.json() : null),
        fetch(`${API_BASE}/api/sessions/stats`, { credentials: "include" }).then((r) => r.ok ? r.json() : null)
      ]);
      if (sessData?.success) setSessions(sessData.sessions || []);
      else setLoadError("Could not load your sessions. Please refresh.");
      if (statsData) setStats({ total_packages: statsData.total_packages ?? 0, total_forms: statsData.total_forms ?? 0, avg_sqs_score: statsData.avg_sqs_score ?? null });
    } catch {
      setLoadError("Network error loading sessions. Please refresh.");
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    fetchDashboardData();
  }, []);
  const handleDelete = async (sid) => {
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
  const fmtDate = (iso) => {
    if (!iso) return "\u2014";
    const d = new Date(iso);
    const diffDays = Math.floor((Date.now() - d) / 864e5);
    if (diffDays === 0) return "Today";
    if (diffDays === 1) return "Yesterday";
    if (diffDays < 7) return `${diffDays}d ago`;
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: diffDays > 300 ? "numeric" : void 0 });
  };
  const avgSqs = (sqsMap) => {
    const scores = Object.values(sqsMap || {}).map((s) => s?.sqs_score).filter((n) => n != null);
    return scores.length ? Math.round(scores.reduce((a, b) => a + b, 0) / scores.length) : null;
  };
  const sqsColor = (v) => v >= 80 ? "#10b981" : v >= 70 ? "#f59e0b" : "#ef4444";
  const sqsBg = (v) => v >= 80 ? "rgba(16,185,129,0.1)" : v >= 70 ? "rgba(245,158,11,0.1)" : "rgba(239,68,68,0.1)";
  const sqsGrade = (v) => v >= 90 ? "A" : v >= 80 ? "B" : v >= 70 ? "C" : v >= 60 ? "D" : "F";
  const totalForms = stats.total_forms;
  const globalAvg = stats.avg_sqs_score;
  const tips = [
    "Upload client documents, applications, loss runs, schedules, or other submission materials.",
    "Let Primble extract key data and check the package for missing or inconsistent information.",
    "Resolve quality findings with guided client follow-up before finalizing the package.",
    "Download underwriting-ready forms, supporting materials, and/or a submission brief once the package is complete."
  ];
  return /* @__PURE__ */ React.createElement(React.Fragment, null, loading && /* @__PURE__ */ React.createElement("div", { className: "loading-overlay" }, /* @__PURE__ */ React.createElement("div", { className: "loading-spinner" }), /* @__PURE__ */ React.createElement("p", { className: "loading-text" }, "Loading sessions\u2026")), /* @__PURE__ */ React.createElement("div", { className: "dashboard-shell" }, deleteTarget && /* @__PURE__ */ React.createElement(DeleteConfirmModal, { onConfirm: () => handleDelete(deleteTarget), onCancel: () => setDeleteTarget(null) }), loadError && /* @__PURE__ */ React.createElement("div", { className: "db-error-banner" }, loadError), /* @__PURE__ */ React.createElement("div", { className: "db-header" }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("div", { className: "db-header-eyebrow" }, "Submissions"), /* @__PURE__ */ React.createElement("h2", { className: "db-header-title" }, "Recent Packages"), /* @__PURE__ */ React.createElement("p", { className: "db-header-sub" }, "Pick up where you left off or start a new submission.")), /* @__PURE__ */ React.createElement("button", { onClick: onNewPackage, className: "db-primary-btn" }, "+ Upload New Package")), /* @__PURE__ */ React.createElement("div", { className: "dashboard-body" }, /* @__PURE__ */ React.createElement("div", { className: "dashboard-main" }, loading ? null : sessions.length === 0 ? /* @__PURE__ */ React.createElement("div", { className: "db-empty-state" }, /* @__PURE__ */ React.createElement("div", { className: "db-empty-topbar" }), /* @__PURE__ */ React.createElement("p", { className: "db-empty-title" }, "No packages yet"), /* @__PURE__ */ React.createElement("p", { className: "db-empty-desc" }, "Upload your first submission package to extract key data, check submission quality, and prepare underwriting-ready forms and materials."), /* @__PURE__ */ React.createElement("div", { className: "db-empty-steps" }, [["Upload docs", "Check quality", "Fix issues", "Generate forms"]].flat().map((label, i, arr) => /* @__PURE__ */ React.createElement("div", { key: i, style: { display: "flex", alignItems: "center", gap: 6 } }, /* @__PURE__ */ React.createElement("div", { className: "db-empty-step-pill" }, label), i < arr.length - 1 && /* @__PURE__ */ React.createElement("span", { className: "db-empty-step-arrow" }, "\u2192")))), /* @__PURE__ */ React.createElement("button", { onClick: onNewPackage, className: "db-primary-btn" }, "Start First Package")) : /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 0 } }, /* @__PURE__ */ React.createElement("div", { className: "db-list-count" }, sessions.length, " Package", sessions.length !== 1 ? "s" : ""), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 10 } }, sessions.map((s) => {
    const avg = avgSqs(s.sqs);
    const color = avg != null ? sqsColor(avg) : "#94a3b8";
    const bg = avg != null ? sqsBg(avg) : "rgba(148,163,184,0.08)";
    const grade = avg != null ? sqsGrade(avg) : null;
    const formCount = s.form_ids?.length || 0;
    return /* @__PURE__ */ React.createElement(
      "div",
      {
        key: s.session_id,
        className: "session-card",
        onClick: () => onResume(s.session_id),
        style: { background: "#fff", border: "1.5px solid #e0e0e0", borderRadius: 18, cursor: "pointer", display: "flex", alignItems: "stretch", transition: "all 0.18s", position: "relative", boxShadow: "0 2px 8px rgba(0,0,0,0.06)", overflow: "hidden" },
        onMouseEnter: (e) => {
          e.currentTarget.style.borderColor = "#E61B84";
          e.currentTarget.style.boxShadow = "0 8px 32px rgba(230,0,122,0.12)";
          e.currentTarget.style.transform = "translateY(-1px)";
        },
        onMouseLeave: (e) => {
          e.currentTarget.style.borderColor = "#e0e0e0";
          e.currentTarget.style.boxShadow = "0 2px 8px rgba(0,0,0,0.06)";
          e.currentTarget.style.transform = "none";
        }
      },
      /* @__PURE__ */ React.createElement("div", { style: { width: 4, background: "#E61B84", flexShrink: 0 } }),
      /* @__PURE__ */ React.createElement("div", { style: { flex: 1, padding: "18px 22px", display: "flex", alignItems: "center", gap: 16, minWidth: 0 } }, /* @__PURE__ */ React.createElement("div", { style: { flex: 1, minWidth: 0 } }, /* @__PURE__ */ React.createElement("div", { style: { fontWeight: 700, fontSize: 15, color: "#0b0b0b", marginBottom: 6, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } }, s.applicant || "Unnamed Package"), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 5, flexWrap: "wrap", alignItems: "center" } }, formCount > 0 && /* @__PURE__ */ React.createElement("span", { className: "db-badge db-badge-pink" }, formCount, " form", formCount !== 1 ? "s" : ""), s.form_ids?.slice(0, 4).map((fid) => /* @__PURE__ */ React.createElement("span", { key: fid, className: "db-badge db-badge-gray" }, fid.replace(/_/g, " "))), (s.form_ids?.length || 0) > 4 && /* @__PURE__ */ React.createElement("span", { style: { fontSize: 11, color: "#b5b5b5" } }, "+", s.form_ids.length - 4), s.lines?.length > 0 && /* @__PURE__ */ React.createElement("span", { style: { fontSize: 11, color: "#b5b5b5" } }, "\xB7 ", s.lines.slice(0, 2).join(", "), s.lines.length > 2 ? ` +${s.lines.length - 2}` : ""))), /* @__PURE__ */ React.createElement("div", { style: { flexShrink: 0, textAlign: "right", marginRight: 4 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 12, fontWeight: 600, color: "#6a6a6a" } }, fmtDate(s.updated_at))), /* @__PURE__ */ React.createElement("div", { style: { width: 54, height: 54, borderRadius: "50%", background: avg != null ? "rgba(230,0,122,0.08)" : "rgba(148,163,184,0.08)", border: `2px solid ${avg != null ? "#E61B8455" : "#94a3b855"}`, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", flexShrink: 0 } }, avg != null ? /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 15, fontWeight: 800, color: "#E61B84", lineHeight: 1 } }, avg), /* @__PURE__ */ React.createElement("span", { style: { fontSize: 9, fontWeight: 700, color: "#E61B84", opacity: 0.8, marginTop: 1 } }, grade)) : /* @__PURE__ */ React.createElement("span", { style: { fontSize: 9, color: "#b5b5b5", fontWeight: 600, textAlign: "center", lineHeight: 1.3 } }, "SQS\n\u2014")), /* @__PURE__ */ React.createElement("div", { style: { color: "#e0e0e0", flexShrink: 0, display: "flex", alignItems: "center" } }, /* @__PURE__ */ React.createElement("svg", { width: "16", height: "16", viewBox: "0 0 24 24", fill: "none" }, /* @__PURE__ */ React.createElement("path", { d: "M9 18l6-6-6-6", stroke: "currentColor", strokeWidth: "2.5", strokeLinecap: "round", strokeLinejoin: "round" }))), /* @__PURE__ */ React.createElement("button", { className: "session-delete-btn", onClick: (e) => {
        e.stopPropagation();
        setDeleteTarget(s.session_id);
      }, title: "Delete session", style: { position: "absolute", top: 10, right: 10 } }, "\u2715"))
    );
  })))), /* @__PURE__ */ React.createElement("aside", { className: "dashboard-sidebar" }, /* @__PURE__ */ React.createElement("div", { className: "db-sidebar-card" }, /* @__PURE__ */ React.createElement("div", { className: "db-sidebar-card-title" }, "Overview"), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column" } }, [
    { label: "Total Packages", value: loading ? "\u2014" : stats.total_packages, border: true },
    { label: "Forms Generated", value: loading ? "\u2014" : totalForms, border: true },
    { label: "Avg SQS Score", value: loading ? "\u2014" : globalAvg != null ? `${globalAvg} / 100` : "\u2014", border: false }
  ].map((item, i) => /* @__PURE__ */ React.createElement("div", { key: i, className: "db-metric-row", style: { borderBottom: item.border ? "1px solid #f0f0f0" : "none" } }, /* @__PURE__ */ React.createElement("span", { className: "db-metric-label" }, item.label), /* @__PURE__ */ React.createElement("span", { className: "db-metric-value", style: { color: "#E61B84" } }, item.value))))), /* @__PURE__ */ React.createElement("div", { className: "db-sidebar-card" }, /* @__PURE__ */ React.createElement("div", { className: "db-sidebar-card-title" }, "Tips"), /* @__PURE__ */ React.createElement("ol", { className: "db-tips-list" }, tips.map((tip, i) => /* @__PURE__ */ React.createElement("li", { key: i, className: "db-tip-item" }, tip))))))));
}
const AcordModal = forwardRef(function AcordModal2({
  onClose,
  user,
  token,
  onUserUpdate,
  onShowUpgrade,
  resumeSessionId,
  savedSignature,
  onOpenSignatureModal,
  onOpenBillingPortal,
  billingPortalLoading,
  fullPage = false
}, ref) {
  const fileInputRef = useRef(null);
  const [files, setFiles] = useState([]);
  const [dragging, setDragging] = useState(false);
  const [loading, setLoading] = useState(false);
  const [processingStage, setProcessingStage] = useState("");
  const [step, setStep] = useState(resumeSessionId ? "resuming" : "dashboard");
  const [showUploadOverlay, setShowUploadOverlay] = useState(false);
  const [showSlowUploadMsg, setShowSlowUploadMsg] = useState(false);
  const [jobToasts, setJobToasts] = useState([]);
  useEffect(() => {
    if (step === "editor") {
      document.body.style.overflow = "hidden";
      window.scrollTo(0, 0);
    } else {
      document.body.style.overflow = "";
    }
    return () => {
      document.body.style.overflow = "";
    };
  }, [step]);
  useEffect(() => {
    if (!showUploadOverlay) {
      setShowSlowUploadMsg(false);
      return;
    }
    const t = setTimeout(() => setShowSlowUploadMsg(true), 5e3);
    return () => clearTimeout(t);
  }, [showUploadOverlay]);
  const [error, setError] = useState(null);
  const [sessionId, setSessionId] = useState(resumeSessionId || null);
  const [docSummary, setDocSummary] = useState([]);
  const [flags, setFlags] = useState({});
  const [hardStops, setHardStops] = useState([]);
  const [canProceedWithWarning, setCanProceedWithWarning] = useState(false);
  const [warningStops, setWarningStops] = useState([]);
  const [softStops, setSoftStops] = useState([]);
  const [tier2Score, setTier2Score] = useState(null);
  const [tier2Missing, setTier2Missing] = useState([]);
  const [recommendations, setRecommendations] = useState([]);
  const [allAvailableForms, setAllAvailableForms] = useState([]);
  const [integrity, setIntegrity] = useState(null);
  const [integrityBusy, setIntegrityBusy] = useState(false);
  const [removeDocIds, setRemoveDocIds] = useState(/* @__PURE__ */ new Set());
  const [availableDocTypes, setAvailableDocTypes] = useState([]);
  const [reclassDocId, setReclassDocId] = useState(null);
  const [underwriting, setUnderwriting] = useState(null);
  const [underwritingBusy, setUnderwritingBusy] = useState(null);
  const [underwritingPicks, setUnderwritingPicks] = useState({});
  const [checkedFormIds, setCheckedFormIds] = useState(/* @__PURE__ */ new Set());
  const [showAddForms, setShowAddForms] = useState(false);
  const [generatedForms, setGeneratedForms] = useState({});
  const [activeFormId, setActiveFormId] = useState(null);
  const [crossIssues, setCrossIssues] = useState([]);
  const [pdfLoading, setPdfLoading] = useState({});
  const [pkgStatusMsg, setPkgStatusMsg] = useState("");
  const [pkgStatusType, setPkgStatusType] = useState("");
  const [signedForms, setSignedForms] = useState(/* @__PURE__ */ new Set());
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
  const [liteGenerating, setLiteGenerating] = useState(false);
  const [liteCoverLoading, setLiteCoverLoading] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(() => window.innerWidth > 900);
  const [packageSqs, setPackageSqs] = useState(null);
  const [dismissedRecs, setDismissedRecs] = useState(/* @__PURE__ */ new Set());
  const [showDownloadPreflight, setShowDownloadPreflight] = useState(false);
  const [preflightRecs, setPreflightRecs] = useState([]);
  const [preflightOverrideReason, setPreflightOverrideReason] = useState("");
  const [preflightCallback, setPreflightCallback] = useState(null);
  const [sqsNarrative, setSqsNarrative] = useState("");
  const [downloadPreflightLoading, setDownloadPreflightLoading] = useState(false);
  useEffect(() => {
    if (step !== "lite" || !sessionId) return;
    setLiteGenerating(true);
    setLiteSqsData(null);
    fetch(`${API_BASE}/api/lite/generate-internal/${sessionId}`, { method: "POST", credentials: "include" }).then((r) => r.ok ? r.json() : null).then((d) => {
      if (d?.success) setLiteSqsData(d);
      else setError("Could not score submission. Please try again.");
    }).catch(() => setError("Could not score submission. Please try again.")).finally(() => setLiteGenerating(false));
  }, [step, sessionId]);
  useEffect(() => {
    if (!resumeSessionId) return;
    setLoading(true);
    setProcessingStage("Restoring your session...");
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 2e4);
    fetch(`${API_BASE}/api/session/${resumeSessionId}`, { credentials: "include", signal: ctrl.signal }).then((r) => r.ok ? r.json() : null).then((data) => {
      const isEssentials = user?.subscription_tier === "essentials";
      if (isEssentials && data?.session_id) {
        setSessionId(resumeSessionId);
        setStep("lite");
      } else if (!isEssentials && data && data.generated_forms && Object.keys(data.generated_forms).length > 0) {
        setGeneratedForms(data.generated_forms);
        setCrossIssues(data.cross_issues || []);
        if (data.package_sqs) setPackageSqs(data.package_sqs);
        const firstId = Object.keys(data.generated_forms)[0];
        setActiveFormId(firstId);
        const readyMap = {};
        Object.keys(data.generated_forms).forEach((fid) => {
          readyMap[fid] = false;
        });
        setPdfLoading(readyMap);
        setStep("editor");
      } else {
        setStep("dashboard");
        setSessionId(null);
      }
    }).catch(() => {
      setError("Could not restore session. Please try again.");
      setStep("dashboard");
      setSessionId(null);
    }).finally(() => {
      clearTimeout(timer);
      setLoading(false);
      setProcessingStage("");
    });
  }, [resumeSessionId]);
  const handleDragOver = (e) => {
    e.preventDefault();
    setDragging(true);
  };
  const handleDragLeave = () => setDragging(false);
  const handleDrop = (e) => {
    e.preventDefault();
    setDragging(false);
    const uploaded = Array.from(e.dataTransfer.files).filter((f) => f.type === "application/pdf" || f.name.toLowerCase().endsWith(".zip") || f.type.startsWith("image/"));
    setFiles((prev) => [...prev, ...uploaded]);
  };
  useEffect(() => {
    if (step !== "editor" && step !== "lite" || !sessionId) return;
    refreshArqData();
  }, [step, sessionId]);
  const refreshArqData = async () => {
    if (!sessionId) return [];
    fetch(`${API_BASE}/api/arq/list/${sessionId}`, { credentials: "include" }).then((r) => r.ok ? r.json() : null).then((d) => {
      if (d?.success) setArqSessions(d.arq_sessions || []);
    }).catch(() => {
    });
    fetch(`${API_BASE}/api/arq/notifications`, { credentials: "include" }).then((r) => r.ok ? r.json() : null).then((d) => {
      if (d?.notifications) setArqNotifCount(d.notifications.filter((n) => !n.read_status).length);
    }).catch(() => {
    });
    try {
      const r = await fetch(`${API_BASE}/api/arq/client-filled/${sessionId}`, { credentials: "include" });
      const d = r.ok ? await r.json() : null;
      const fields = d?.client_filled_fields || [];
      setClientFilledFields(fields);
      return fields;
    } catch {
      return [];
    }
  };
  const handleOpenARQ = async () => {
    if (!sessionId) return;
    setArqLoadingQ(true);
    try {
      const res = await fetch(`${API_BASE}/api/arq/generate/${sessionId}`, { credentials: "include" });
      const data = await res.json();
      if (res.ok && data.success) {
        setArqQuestions(data.questions || []);
        setShowARQModal(true);
      } else setError(data.detail || "Failed to generate questions.");
    } catch (e) {
      setError("Network error: " + e.message);
    } finally {
      setArqLoadingQ(false);
    }
  };
  const _resetSqsState = () => {
    setPackageSqs(null);
    setDismissedRecs(/* @__PURE__ */ new Set());
    setShowDownloadPreflight(false);
    setPreflightRecs([]);
    setPreflightOverrideReason("");
    setPreflightCallback(null);
    setSqsNarrative("");
  };
  const resetToUpload = () => {
    setFiles([]);
    setSessionId(null);
    setStep("upload");
    setError(null);
    setDocSummary([]);
    setFlags({});
    setHardStops([]);
    setSoftStops([]);
    setCanProceedWithWarning(false);
    setWarningStops([]);
    setTier2Score(null);
    setTier2Missing([]);
    setRecommendations([]);
    setAllAvailableForms([]);
    setCheckedFormIds(/* @__PURE__ */ new Set());
    setGeneratedForms({});
    setActiveFormId(null);
    setCrossIssues([]);
    setPdfLoading({});
    setEpicLoading(false);
    setEpicSuccess(false);
    setSignedForms(/* @__PURE__ */ new Set());
    setShowUploadOverlay(false);
    setShowGenerateOverlay(false);
    setShowDownloadOverlay(false);
    setArqQuestions([]);
    setArqSessions([]);
    setClientFilledFields([]);
    setArqNotifCount(0);
    _resetSqsState();
  };
  const goToDashboard = () => {
    setFiles([]);
    setSessionId(null);
    setStep("dashboard");
    setError(null);
    setDocSummary([]);
    setFlags({});
    setHardStops([]);
    setSoftStops([]);
    setTier2Score(null);
    setTier2Missing([]);
    setRecommendations([]);
    setAllAvailableForms([]);
    setCheckedFormIds(/* @__PURE__ */ new Set());
    setGeneratedForms({});
    setActiveFormId(null);
    setCrossIssues([]);
    setPdfLoading({});
    setEpicLoading(false);
    setEpicSuccess(false);
    setSignedForms(/* @__PURE__ */ new Set());
    setShowUploadOverlay(false);
    setShowGenerateOverlay(false);
    setShowDownloadOverlay(false);
    setArqQuestions([]);
    setArqSessions([]);
    setClientFilledFields([]);
    setArqNotifCount(0);
    _resetSqsState();
  };
  useImperativeHandle(ref, () => ({ goToDashboard }));
  const handleResumeSession = (sid) => {
    setLoading(true);
    setProcessingStage("Restoring session\u2026");
    setSessionId(sid);
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 2e4);
    fetch(`${API_BASE}/api/session/${sid}`, { credentials: "include", signal: ctrl.signal }).then((r) => r.ok ? r.json() : null).then((data) => {
      const isEssentials = user?.subscription_tier === "essentials";
      if (!isEssentials && data && data.generated_forms && Object.keys(data.generated_forms).length > 0) {
        setGeneratedForms(data.generated_forms);
        setCrossIssues(data.cross_issues || []);
        if (data.package_sqs) setPackageSqs(data.package_sqs);
        const firstId = Object.keys(data.generated_forms)[0];
        setActiveFormId(firstId);
        const readyMap = {};
        Object.keys(data.generated_forms).forEach((fid) => {
          readyMap[fid] = false;
        });
        setPdfLoading(readyMap);
        setStep("editor");
      } else if (isEssentials && data?.session_id) {
        setSessionId(sid);
        setStep("lite");
      } else {
        setStep("upload");
        setSessionId(null);
      }
    }).catch(() => {
      setError("Could not load session. Please try again.");
      setStep("upload");
      setSessionId(null);
    }).finally(() => {
      clearTimeout(timer);
      setLoading(false);
      setProcessingStage("");
    });
  };
  const handleSendToEpic = async (formId) => {
    if (!formId || !sessionId) return;
    setEpicLoading(true);
    setEpicSuccess(false);
    try {
      const res = await fetch(`${API_BASE}/api/send-to-epic/${sessionId}/${formId}`, { credentials: "include" });
      const data = await res.json();
      if (res.ok && data.success) {
        setEpicSuccess(true);
        setTimeout(() => setEpicSuccess(false), 3500);
      } else setError(data.detail || "Failed to send to EPIC.");
    } catch (e) {
      setError("EPIC send failed: " + e.message);
    } finally {
      setEpicLoading(false);
    }
  };
  const triggerEnterprisePopup = (buttonEl) => {
    const rect = buttonEl.getBoundingClientRect();
    const popupWidth = 210;
    const spaceRight = window.innerWidth - rect.right - 12;
    const left = spaceRight >= popupWidth ? rect.right + 12 : Math.max(8, rect.left - popupWidth - 4);
    const top = Math.min(rect.top, window.innerHeight - 110);
    setEnterprisePopupPos({ top, left });
    setShowEnterprisePopup(true);
  };
  const handleSendToVertafore = async (formId) => {
    if (!formId || !sessionId) return;
    setVertaforeLoading(true);
    setVertaforeSuccess(false);
    try {
      const res = await fetch(`${API_BASE}/api/send-to-vertafore/${sessionId}/${formId}`, { credentials: "include" });
      const data = await res.json();
      if (res.ok && data.success) {
        setVertaforeSuccess(true);
        setTimeout(() => setVertaforeSuccess(false), 3500);
      } else setError(data.detail || "Failed to send to Vertafore.");
    } catch (e) {
      setError("Vertafore send failed: " + e.message);
    } finally {
      setVertaforeLoading(false);
    }
  };
  const _doDownloadOneNoSummary = async (formId) => {
    setLoading(true);
    setShowDownloadOverlay(true);
    try {
      const res = await fetch(`${API_BASE}/api/download-pdf/${sessionId}/${formId}?include_cover=false`, { credentials: "include" });
      if (res.status === 403) {
        const d = await res.json().catch(() => ({}));
        if (d.payment_locked) {
          setError("Account payment overdue.");
          return;
        }
        if (d.upgrade_required) {
          onShowUpgrade();
          return;
        }
        setError(d.message || "Download blocked");
        return;
      }
      if (!res.ok) {
        setError("Download failed");
        return;
      }
      const pkgStatus = res.headers.get("X-Package-Status") || "";
      const pkgMsg = res.headers.get("X-Package-Message") || "";
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${formId}_Package.zip`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      await refreshUser();
      if (pkgStatus) {
        setPkgStatusMsg(pkgMsg);
        setPkgStatusType(pkgStatus);
        setTimeout(() => setPkgStatusMsg(""), 12e3);
      }
      setStep("success");
    } catch (err) {
      setError("Download failed: " + err.message);
    } finally {
      setLoading(false);
      setShowDownloadOverlay(false);
    }
  };
  const handleDownloadOneNoSummary = (formId) => gatedDownload(() => _runPreflightThenDownload(() => _doDownloadOneNoSummary(formId)));
  const gatedDownload = (action) => {
    if (user?.acord_license_confirmed) {
      action();
      return;
    }
    setAcordLicenseChecked(false);
    setAcordModalAction(() => action);
    setShowAcordModal(true);
  };
  const handleAcordConfirm = async () => {
    if (!acordLicenseChecked) return;
    setAcordModalLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/acord/confirm-license`, { method: "POST", credentials: "include" });
      if (res.ok) {
        onUserUpdate({ ...user, acord_license_confirmed: true });
        setShowAcordModal(false);
        if (acordModalAction) acordModalAction();
      } else setError("License confirmation failed. Please try again.");
    } catch {
      setError("Network error during license confirmation.");
    } finally {
      setAcordModalLoading(false);
    }
  };
  const _doDownloadOne = async (formId) => {
    setLoading(true);
    setShowDownloadOverlay(true);
    try {
      const res = await fetch(`${API_BASE}/api/download-pdf/${sessionId}/${formId}`, { credentials: "include" });
      if (res.status === 403) {
        const d = await res.json().catch(() => ({}));
        if (d.payment_locked) {
          setError("Account payment overdue.");
          return;
        }
        if (d.upgrade_required) {
          onShowUpgrade();
          return;
        }
        setError(d.message || "Download blocked");
        return;
      }
      if (!res.ok) {
        setError("Download failed");
        return;
      }
      const pkgStatus = res.headers.get("X-Package-Status") || "";
      const pkgMsg = res.headers.get("X-Package-Message") || "";
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${formId}_Package.zip`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      await refreshUser();
      if (pkgStatus) {
        setPkgStatusMsg(pkgMsg);
        setPkgStatusType(pkgStatus);
        setTimeout(() => setPkgStatusMsg(""), 12e3);
      }
      setStep("success");
    } catch (err) {
      setError("Download failed: " + err.message);
    } finally {
      setLoading(false);
      setShowDownloadOverlay(false);
    }
  };
  const _doDownloadAll = async () => {
    setLoading(true);
    setShowDownloadOverlay(true);
    try {
      const res = await fetch(`${API_BASE}/api/download-all/${sessionId}`, { credentials: "include" });
      if (res.status === 403) {
        const d = await res.json().catch(() => ({}));
        if (d.payment_locked) {
          setError("Account payment overdue.");
          return;
        }
        if (d.upgrade_required) {
          onShowUpgrade();
          return;
        }
        setError(d.message || "Download blocked");
        return;
      }
      if (!res.ok) {
        setError("Download failed");
        return;
      }
      const pkgStatus = res.headers.get("X-Package-Status") || "";
      const pkgMsg = res.headers.get("X-Package-Message") || "";
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "ACORD_Package_Primble.zip";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      await refreshUser();
      if (pkgStatus) {
        setPkgStatusMsg(pkgMsg);
        setPkgStatusType(pkgStatus);
        setTimeout(() => setPkgStatusMsg(""), 12e3);
      }
      setStep("success");
    } catch (err) {
      setError("Download failed: " + err.message);
    } finally {
      setLoading(false);
      setShowDownloadOverlay(false);
    }
  };
  const refreshUser = async () => {
    const res = await fetch(`${API_BASE}/api/auth/me`, { credentials: "include" });
    if (res.ok) {
      const data = await res.json();
      onUserUpdate(data);
    }
  };
  const _ACTIVE_JOB_KEY = "primble_active_job";
  const _persistActiveJob = (jobId, kind) => {
    try {
      localStorage.setItem(_ACTIVE_JOB_KEY, JSON.stringify({ jobId, kind, ts: Date.now() }));
    } catch {
    }
  };
  const _clearActiveJob = () => {
    try {
      localStorage.removeItem(_ACTIVE_JOB_KEY);
    } catch {
    }
  };
  const _notifPermissionAsked = useRef(false);
  const _permissionWarnedThisSession = useRef(false);
  const _wasHiddenDuringJob = useRef(false);
  const _markJobStart = () => {
    _wasHiddenDuringJob.current = typeof document !== "undefined" && document.hidden || false;
  };
  const _requestNotificationPermission = async () => {
    if (_notifPermissionAsked.current) return;
    _notifPermissionAsked.current = true;
    try {
      if (typeof Notification === "undefined") {
        console.info("[primble-notify] Notification API unavailable");
        return;
      }
      if (Notification.permission === "default") {
        const result = await Notification.requestPermission().catch(() => "default");
        console.info("[primble-notify] permission ->", result);
      }
      if (Notification.permission !== "granted" && !_permissionWarnedThisSession.current) {
        _permissionWarnedThisSession.current = true;
        _pushJobToast(
          "Background alerts are off",
          "Click the lock or bell icon in your browser's address bar to allow notifications, then reload.",
          false
        );
      }
    } catch (err) {
      console.warn("[primble-notify] permission request threw:", err && err.message ? err.message : err);
    }
  };
  const _resolveSwRegistration = async () => {
    if (!("serviceWorker" in navigator)) return null;
    try {
      if (window.__primbleSwReady) {
        const reg = await window.__primbleSwReady;
        if (reg && typeof reg.showNotification === "function") return reg;
      }
    } catch (err) {
      console.warn("[primble-notify] __primbleSwReady failed:", err && err.message ? err.message : err);
    }
    try {
      const existing = await navigator.serviceWorker.getRegistration("/");
      if (existing && typeof existing.showNotification === "function") return existing;
    } catch (err) {
      console.warn("[primble-notify] getRegistration failed:", err && err.message ? err.message : err);
    }
    try {
      const reg = await navigator.serviceWorker.register("/notification-sw.js", { scope: "/" });
      await navigator.serviceWorker.ready;
      if (reg && typeof reg.showNotification === "function") return reg;
    } catch (err) {
      console.error("[primble-notify] just-in-time register failed:", err && err.message ? err.message : err);
    }
    return null;
  };
  const _setTitleBadge = (on) => {
    try {
      const base = document.title.replace(/^\(\d+\)\s*/, "");
      document.title = on ? `(1) ${base}` : base;
    } catch {
    }
  };
  const _pushJobToast = (title, body, ok) => {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
    setJobToasts((prev) => [...prev, { id, title, body, ok }]);
  };
  const _notifyJobDone = async (kind, ok) => {
    const title = ok ? "Primble \u2014 Ready" : "Primble \u2014 Action needed";
    const body = ok ? kind === "generate" ? "Your ACORD forms are ready to review." : "Your documents have finished processing." : "There was an issue with your submission. Please reopen to review.";
    console.info("[primble-notify] _notifyJobDone fired", {
      kind,
      ok,
      hidden: typeof document !== "undefined" ? document.hidden : "n/a",
      wasAwayDuringJob: _wasHiddenDuringJob.current,
      permission: typeof Notification !== "undefined" ? Notification.permission : "n/a"
    });
    _pushJobToast(title, body, ok);
    if (typeof document !== "undefined" && document.hidden) _setTitleBadge(true);
    _wasHiddenDuringJob.current = false;
    if (typeof Notification === "undefined") {
      console.info("[primble-notify] skip: Notification API unavailable");
      return;
    }
    if (Notification.permission !== "granted") {
      console.info("[primble-notify] skip: permission=", Notification.permission);
      return;
    }
    const tag = `primble-${kind}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
    const reg = await _resolveSwRegistration();
    if (!reg) {
      console.error("[primble-notify] no SW registration available, OS notification skipped");
      return;
    }
    try {
      await reg.showNotification(title, { body, tag });
      console.info("[primble-notify] showNotification ok, tag=", tag);
      return;
    } catch (err) {
      console.warn("[primble-notify] showNotification rejected, trying SW postMessage:", err && err.message ? err.message : err);
    }
    try {
      const target = reg.active || reg.waiting || reg.installing;
      if (target && target.postMessage) {
        target.postMessage({ type: "SHOW_NOTIFICATION", title, body, tag });
        console.info("[primble-notify] postMessage to SW ok (fallback), tag=", tag);
      } else {
        console.error("[primble-notify] no SW worker target available for postMessage fallback");
      }
    } catch (err) {
      console.error("[primble-notify] postMessage to SW failed:", err && err.message ? err.message : err);
    }
  };
  useEffect(() => {
    window.__primbleTestNotification = async (delaySec = 3) => {
      const ms = Math.max(0, Number(delaySec) * 1e3);
      console.info("[primble-notify] TEST scheduled in", ms, "ms \u2014 switch tabs now");
      console.info("[primble-notify] TEST state at schedule:", {
        hidden: typeof document !== "undefined" ? document.hidden : "n/a",
        permission: typeof Notification !== "undefined" ? Notification.permission : "n/a",
        hasSW: "serviceWorker" in navigator
      });
      await new Promise((r) => setTimeout(r, ms));
      console.info("[primble-notify] TEST firing now \u2014 hidden=", document.hidden);
      if (typeof Notification === "undefined" || Notification.permission !== "granted") {
        console.error("[primble-notify] TEST aborted: no permission");
        return;
      }
      const reg = await _resolveSwRegistration();
      if (!reg) {
        console.error("[primble-notify] TEST aborted: no SW registration");
        return;
      }
      const tag = `primble-test-${Date.now()}`;
      try {
        await reg.showNotification("Primble \u2014 Test", { body: "If you see this banner, OS-level notifications work. \u2713", tag });
        console.info("[primble-notify] TEST showNotification resolved. If no banner appeared, the OS/browser is suppressing it.");
      } catch (err) {
        console.error("[primble-notify] TEST showNotification rejected:", err && err.message ? err.message : err);
      }
    };
    return () => {
      try {
        delete window.__primbleTestNotification;
      } catch {
      }
    };
  }, []);
  useEffect(() => {
    const onVis = () => {
      if (document.hidden) {
        _wasHiddenDuringJob.current = true;
      } else {
        _setTitleBadge(false);
      }
    };
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, []);
  const _pollJobStatus = async (jobId, maxAttempts = 100, interval = 3e3) => {
    let consecutiveErrors = 0;
    const MAX_CONSECUTIVE_ERRORS = 8;
    for (let i = 0; i < maxAttempts; i++) {
      await new Promise((r) => setTimeout(r, interval));
      let res;
      try {
        res = await fetch(`${API_BASE}/api/jobs/${jobId}/status`, { credentials: "include" });
      } catch (e) {
        consecutiveErrors++;
        if (consecutiveErrors >= MAX_CONSECUTIVE_ERRORS) throw e;
        continue;
      }
      if (res.status === 401 || res.status === 403) throw new Error("Session expired during processing. Please sign in again.");
      if (res.status === 404) throw new Error("Job not found");
      if (!res.ok) {
        consecutiveErrors++;
        if (consecutiveErrors >= MAX_CONSECUTIVE_ERRORS) throw new Error(`Job poll failed: ${res.status}`);
        continue;
      }
      consecutiveErrors = 0;
      const job = await res.json();
      if (job.status === "completed") return job;
      if (job.status === "failed") throw new Error(job.error || "Processing failed on the server");
    }
    throw new Error("Processing timed out. Please try again.");
  };
  useEffect(() => {
    let cancelled = false;
    try {
      const raw = localStorage.getItem(_ACTIVE_JOB_KEY);
      if (!raw) return;
      const { jobId, kind, ts } = JSON.parse(raw) || {};
      if (!jobId) {
        _clearActiveJob();
        return;
      }
      if (ts && Date.now() - ts > 30 * 60 * 1e3) {
        _clearActiveJob();
        return;
      }
      (async () => {
        try {
          await _pollJobStatus(jobId);
          if (cancelled) return;
          _notifyJobDone(kind || "upload", true);
        } catch {
          if (cancelled) return;
          _notifyJobDone(kind || "upload", false);
        } finally {
          if (!cancelled) _clearActiveJob();
        }
      })();
    } catch {
    }
    return () => {
      cancelled = true;
    };
  }, []);
  const handleUpload = async () => {
    if (!files.length) {
      setError("Select at least one file");
      return;
    }
    await _requestNotificationPermission();
    _markJobStart();
    setLoading(true);
    setError(null);
    setShowUploadOverlay(true);
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    try {
      const res = await fetch(`${API_BASE}/api/upload-declaration`, { method: "POST", credentials: "include", body: fd });
      if (res.status === 401) {
        setError("Session expired. Please sign in again.");
        setTimeout(() => {
          try {
            localStorage.removeItem("acordly_tk");
            sessionStorage.removeItem("acordly_tk");
          } catch {
          }
          window.location.reload();
        }, 2e3);
        return;
      }
      if (res.status === 403) {
        const d = await res.json().catch(() => ({}));
        if (d.upgrade_required) {
          onShowUpgrade();
          return;
        }
        const msg = d.detail || d.message || "Access blocked.";
        if (msg.includes("suspended")) setError("Your account is suspended.");
        else if (msg.includes("archived")) setError("Account archived. Contact support.");
        else if (msg.includes("soft_locked") || msg.includes("locked")) setError("Account Disabled \u2014 please update billing.");
        else setError(msg);
        return;
      }
      if (res.status === 429) {
        setError("Server busy \u2014 too many concurrent uploads. Please wait 30 seconds and try again.");
        return;
      }
      if (res.status >= 500) {
        setError("Server error during upload. Please try again. If this persists, the file may be too large or complex.");
        return;
      }
      let data;
      if (res.status === 202) {
        const queued = await res.json();
        _persistActiveJob(queued.job_id, "upload");
        let job;
        try {
          job = await _pollJobStatus(queued.job_id);
        } finally {
          _clearActiveJob();
        }
        _notifyJobDone("upload", true);
        const sid = job.result?.session_id || queued.session_id;
        const extRes = await fetch(`${API_BASE}/api/session/${sid}/extraction-result`, { credentials: "include" });
        if (!extRes.ok) {
          setError("Upload processing failed. Please try again.");
          return;
        }
        data = await extRes.json();
      } else {
        data = await res.json();
      }
      if (!data.success) {
        if (data.gate === "tier1_fail") {
          setSoftStops((data.missing_fields || []).map((m) => `ACORD 125 minimum field missing: ${m}`));
          setHardStops([]);
          setRecommendations(data.recommendations || []);
          setStep(user?.subscription_tier === "essentials" ? "lite" : "recommendations");
          return;
        }
        setError(data.message || "Upload failed");
        return;
      }
      _notifyJobDone("upload", true);
      setSessionId(data.session_id);
      setDocSummary(data.doc_summary || []);
      setFlags(data.flags || {});
      setAvailableDocTypes(data.available_doc_types || []);
      setHardStops(data.hard_stops || []);
      setSoftStops(data.soft_stops || []);
      setCanProceedWithWarning(!!data.can_proceed_with_warning);
      setWarningStops(data.warning_stops || []);
      setTier2Score(data.tier2_score ?? null);
      setTier2Missing(data.tier2_missing || []);
      setRecommendations(data.recommendations || []);
      setAllAvailableForms(data.all_available_forms || []);
      setCheckedFormIds(/* @__PURE__ */ new Set());
      setUnderwriting(data.underwriting_consistency || null);
      setUnderwritingPicks({});
      setIntegrity(data.integrity || null);
      if (data.integrity_review_required) {
        setRemoveDocIds(/* @__PURE__ */ new Set());
        setStep("integrity_review");
        return;
      }
      setStep(user?.subscription_tier === "essentials" ? "lite" : "recommendations");
    } catch (e) {
      if (e.message === "Failed to fetch" || e.name === "TypeError") {
        setError("Upload failed: could not reach the server. Check your connection, or the file may be too large. Please try again.");
      } else {
        setError("Upload failed: " + e.message);
      }
    } finally {
      setLoading(false);
      setShowUploadOverlay(false);
    }
  };
  const handleResolveIntegrity = async (action) => {
    if (!sessionId) return;
    if (action === "remove_documents" && removeDocIds.size === 0) {
      setError("Select at least one document to remove.");
      return;
    }
    setIntegrityBusy(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/submission-integrity/resolve`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          action,
          remove_doc_ids: action === "remove_documents" ? Array.from(removeDocIds) : []
        })
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.success) {
        setError(data.detail || data.message || "Could not resolve the submission integrity review.");
        return;
      }
      setIntegrity(data.integrity || null);
      setHardStops(data.hard_stops || []);
      setSoftStops(data.soft_stops || []);
      setCanProceedWithWarning(!!data.can_proceed_with_warning);
      setDocSummary(data.doc_summary || docSummary);
      if (data.available_doc_types) setAvailableDocTypes(data.available_doc_types);
      if (data.integrity_review_required) {
        setRemoveDocIds(/* @__PURE__ */ new Set());
        return;
      }
      setRecommendations(data.recommendations || []);
      setAllAvailableForms(data.all_available_forms || []);
      setCheckedFormIds(/* @__PURE__ */ new Set());
      setUnderwriting(data.underwriting_consistency || null);
      setStep(user?.subscription_tier === "essentials" ? "lite" : "recommendations");
    } catch (e) {
      setError("Could not resolve the submission integrity review: " + (e?.message || "network error"));
    } finally {
      setIntegrityBusy(false);
    }
  };
  const handleReclassify = async (docId, action, newType = null) => {
    if (!sessionId || !docId) return;
    setReclassDocId(docId);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/document/reclassify`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, doc_id: docId, action, new_doc_type: newType })
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.success) {
        setError(data.detail || data.message || "Could not update the document type.");
        return;
      }
      setDocSummary(data.doc_summary || docSummary);
      if (data.available_doc_types) setAvailableDocTypes(data.available_doc_types);
      setRecommendations(data.recommendations || []);
      setHardStops(data.hard_stops || []);
      setSoftStops(data.soft_stops || []);
      setCanProceedWithWarning(!!data.can_proceed_with_warning);
      setWarningStops(data.warning_stops || []);
      setFlags(data.flags || flags);
      if (data.integrity) setIntegrity(data.integrity);
      if (data.underwriting_consistency) setUnderwriting(data.underwriting_consistency);
    } catch (e) {
      setError("Could not update the document type: " + (e?.message || "network error"));
    } finally {
      setReclassDocId(null);
    }
  };
  const handleConfirmUnderwriting = async (factKey, value) => {
    if (!sessionId || !factKey) return;
    const v = (value ?? "").toString().trim();
    if (!v) {
      setError("Enter or select a value to confirm.");
      return;
    }
    setUnderwritingBusy(factKey);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/underwriting/confirm-value`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, fact_key: factKey, value: v })
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.success) {
        setError(data.detail || data.message || "Could not confirm the value.");
        return;
      }
      setUnderwriting(data.underwriting_consistency || null);
      setRecommendations(data.recommendations || recommendations);
      setAllAvailableForms(data.all_available_forms || allAvailableForms);
      setHardStops(data.hard_stops || []);
      setSoftStops(data.soft_stops || []);
      setCanProceedWithWarning(!!data.can_proceed_with_warning);
      setWarningStops(data.warning_stops || []);
      setTier2Score(data.tier2_score ?? tier2Score);
      setTier2Missing(data.tier2_missing || tier2Missing);
      setFlags(data.flags || flags);
    } catch (e) {
      setError("Could not confirm the value: " + (e?.message || "network error"));
    } finally {
      setUnderwritingBusy(null);
    }
  };
  const handleGenerateAll = async () => {
    const ids = Array.from(checkedFormIds);
    if (!ids.length) {
      setError("Select at least one form");
      return;
    }
    await _requestNotificationPermission();
    _markJobStart();
    setLoading(true);
    setError(null);
    setShowGenerateOverlay(true);
    try {
      const res = await fetch(`${API_BASE}/api/select-forms-bulk`, { method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session_id: sessionId, form_ids: ids }) });
      if (res.status === 403) {
        const d = await res.json().catch(() => ({}));
        const msg = d.detail || d.message || "";
        if (msg.toLowerCase().includes("lite")) {
          setStep("lite");
          return;
        }
        setError(msg || "Access blocked. Please update your billing.");
        return;
      }
      if (res.status === 409) {
        const d = await res.json().catch(() => ({}));
        const detail = d.detail || {};
        if (detail.error === "submission_integrity_review_required" || detail.integrity) {
          setIntegrity(detail.integrity || null);
          setRemoveDocIds(/* @__PURE__ */ new Set());
          setStep("integrity_review");
          return;
        }
        setError(detail.message || "Submission cannot proceed. Please review your documents.");
        return;
      }
      let data;
      if (res.status === 202) {
        const queued = await res.json();
        _persistActiveJob(queued.job_id, "generate");
        try {
          await _pollJobStatus(queued.job_id);
        } finally {
          _clearActiveJob();
        }
        _notifyJobDone("generate", true);
        const sessRes = await fetch(`${API_BASE}/api/session/${sessionId}`, { credentials: "include" });
        if (!sessRes.ok) {
          setError("Form generation failed. Please try again.");
          return;
        }
        const sessData = await sessRes.json();
        data = { success: true, generated: sessData.generated_forms, form_ids: Object.keys(sessData.generated_forms || {}), cross_issues: sessData.cross_issues, package_sqs: sessData.package_sqs || null };
      } else {
        data = await res.json();
      }
      if (!data.success) {
        setError(data.detail || data.message || "Form generation failed");
        return;
      }
      _notifyJobDone("generate", true);
      setGeneratedForms(data.generated || {});
      setCrossIssues(data.cross_issues || []);
      if (data.package_sqs) setPackageSqs(data.package_sqs);
      const firstId = data.form_ids?.[0] || null;
      setActiveFormId(firstId);
      setStep("editor");
      const readyMap = {};
      (data.form_ids || []).forEach((fid) => {
        readyMap[fid] = false;
      });
      setPdfLoading(readyMap);
    } catch (e) {
      if (e.message === "Failed to fetch" || e.name === "TypeError") {
        setError("Generation failed: could not reach the server. Your documents are still loaded \u2014 click Generate again to retry.");
      } else {
        setError("Generation failed: " + e.message + " \u2014 click Generate again to retry.");
      }
    } finally {
      setLoading(false);
      setShowGenerateOverlay(false);
    }
  };
  const formIdList = Object.keys(generatedForms);
  const activeIdx = formIdList.indexOf(activeFormId);
  const goNext = () => {
    if (activeIdx < formIdList.length - 1) setActiveFormId(formIdList[activeIdx + 1]);
  };
  const goPrev = () => {
    if (activeIdx > 0) setActiveFormId(formIdList[activeIdx - 1]);
  };
  const toggleForm = (formId) => {
    setCheckedFormIds((prev) => {
      const next = new Set(prev);
      if (next.has(formId)) next.delete(formId);
      else next.add(formId);
      return next;
    });
  };
  const recommendedIds = new Set(recommendations.map((r) => r.form_id));
  const extraForms = allAvailableForms.filter((f) => !recommendedIds.has(f.form_id));
  const activeSqs = activeFormId && generatedForms[activeFormId]?.sqs;
  const pkgsUsed = user?.packages_used || 0;
  const pkgsLimit = user?.packages_limit || 0;
  const softBuffer = user?.packages_soft_buffer || 0;
  const inOverage = user?.subscription_tier !== "free" && pkgsLimit > 0 && pkgsUsed >= pkgsLimit + softBuffer;
  const freeExhausted = user?.subscription_tier === "free" && user?.downloads_remaining === 0;
  const handleNewPackage = () => {
    if (freeExhausted) {
      onShowUpgrade();
      return;
    }
    resetToUpload();
  };
  const BillingBtnSpinner = () => /* @__PURE__ */ React.createElement("span", { style: { width: 11, height: 11, border: "2px solid currentColor", borderTopColor: "transparent", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite", marginRight: 4 } });
  const handleDismissRec = (rec, currentScore, reason = "") => {
    const id = rec?.rec_id;
    if (!id) return;
    setDismissedRecs((prev) => {
      const next = new Set(prev);
      next.add(id);
      return next;
    });
    if (activeFormId) {
      setGeneratedForms((prev) => {
        const form = prev[activeFormId];
        if (!form?.sqs?.recommendations) return prev;
        return {
          ...prev,
          [activeFormId]: {
            ...form,
            sqs: {
              ...form.sqs,
              recommendations: form.sqs.recommendations.filter(
                (r) => (typeof r === "object" ? r.rec_id : r) !== id
              )
            }
          }
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
        form_id: activeFormId ?? null
      })
    }).catch(() => {
    });
  };
  const _runPreflightThenDownload = async (downloadFn) => {
    setDownloadPreflightLoading(true);
    try {
      const [recsRes, narrativeRes] = await Promise.allSettled([
        fetch(`${API_BASE}/api/audit/open/${sessionId}`, { credentials: "include" }),
        fetch(`${API_BASE}/api/sqs/narrative/${sessionId}`, { credentials: "include" })
      ]);
      const recsData = recsRes.status === "fulfilled" && recsRes.value.ok ? await recsRes.value.json() : null;
      const openRecs = recsData?.open_recommendations || [];
      const narrativeData = narrativeRes.status === "fulfilled" && narrativeRes.value.ok ? await narrativeRes.value.json() : null;
      if (narrativeData?.narrative) setSqsNarrative(narrativeData.narrative);
      if (openRecs.length === 0) {
        downloadFn();
        return;
      }
      setPreflightRecs(openRecs);
      setPreflightOverrideReason("");
      setPreflightCallback(() => downloadFn);
      setShowDownloadPreflight(true);
    } catch (_) {
      downloadFn();
    } finally {
      setDownloadPreflightLoading(false);
    }
  };
  const handlePreflightProceed = () => {
    setShowDownloadPreflight(false);
    fetch(`${API_BASE}/api/audit/download-anyway`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, override_reason: preflightOverrideReason.trim() })
    }).catch(() => {
    });
    if (preflightCallback) preflightCallback();
  };
  const handleDownloadOne = (formId) => gatedDownload(() => _runPreflightThenDownload(() => _doDownloadOne(formId)));
  const handleDownloadAll = () => gatedDownload(() => _runPreflightThenDownload(() => _doDownloadAll()));
  const handleLiteCoverSheet = async () => {
    setLiteCoverLoading(true);
    setShowDownloadOverlay(true);
    try {
      const res = await fetch(`${API_BASE}/api/lite/cover-sheet/${sessionId}`, { credentials: "include" });
      if (res.status === 403) {
        onShowUpgrade();
        return;
      }
      if (!res.ok) {
        setError("Failed to generate cover sheet.");
        return;
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "Primble_SQS_Cover_Sheet.pdf";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch {
      setError("Download failed. Please try again.");
    } finally {
      setLiteCoverLoading(false);
      setShowDownloadOverlay(false);
    }
  };
  return /* @__PURE__ */ React.createElement("div", { className: step === "editor" ? "acord-modal-editor-root" : void 0, style: {
    background: "#f8fafc",
    width: "100%",
    ...step === "editor" ? { height: "calc(100vh - 81px)", display: "flex", flexDirection: "column", overflow: "hidden" } : { minHeight: "calc(100vh - 81px)" }
  } }, /* @__PURE__ */ React.createElement("div", { style: {
    padding: step === "editor" ? 0 : "32px 40px",
    ...step === "editor" && { flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", minHeight: 0 }
  } }, renderContent()), showEnterprisePopup && /* @__PURE__ */ React.createElement("div", { style: { position: "fixed", top: enterprisePopupPos.top, left: enterprisePopupPos.left, zIndex: 9999, width: 210, borderRadius: 10, background: "#fdf2f8", border: "1px solid #f9a8d4", boxShadow: "0 6px 24px rgba(230,0,122,0.15), 0 2px 8px rgba(230,0,122,0.08)", overflow: "hidden", animation: "slideDown 0.18s ease-out" } }, /* @__PURE__ */ React.createElement("div", { style: { position: "absolute", top: 14, left: -6, width: 11, height: 11, background: "#fdf2f8", border: "1px solid #f9a8d4", borderRight: "none", borderTop: "none", transform: "rotate(45deg)" } }), /* @__PURE__ */ React.createElement("div", { style: { padding: "10px 10px 10px 14px", display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 6 } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 3 } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 12, fontWeight: 700, color: "#be185d" } }, "Enterprise only for now"), /* @__PURE__ */ React.createElement("span", { style: { fontSize: 11, color: "#9d174d", lineHeight: 1.45 } }, "Join the waitlist to get early access.")), /* @__PURE__ */ React.createElement("button", { onClick: () => setShowEnterprisePopup(false), style: { flexShrink: 0, background: "none", border: "none", cursor: "pointer", color: "#be185d", fontSize: 15, lineHeight: 1, padding: "1px 3px", opacity: 0.6 }, onMouseEnter: (e) => e.currentTarget.style.opacity = "1", onMouseLeave: (e) => e.currentTarget.style.opacity = "0.6" }, "\xD7")), /* @__PURE__ */ React.createElement("div", { style: { height: 3, background: "linear-gradient(90deg, #f9a8d4, #E61B84)" } })), showAcordModal && renderAcordLicenseModal(), showARQModal && /* @__PURE__ */ React.createElement(ARQModal, { sessionId, token, questions: arqQuestions, onClose: () => setShowARQModal(false), onSuccess: () => {
    setShowARQModal(false);
    refreshArqData();
  } }), downloadPreflightLoading && /* @__PURE__ */ React.createElement(ProcessStageOverlay, { stages: ["Checking recommendations", "Loading SQS summary"], advanceAfter: 1800 }), showDownloadPreflight && /* @__PURE__ */ React.createElement(
    DownloadPreflightModal,
    {
      openRecs: preflightRecs,
      narrative: sqsNarrative,
      overrideReason: preflightOverrideReason,
      onOverrideChange: setPreflightOverrideReason,
      onProceed: handlePreflightProceed,
      onCancel: () => {
        setShowDownloadPreflight(false);
        setPreflightCallback(null);
      },
      loading
    }
  ), jobToasts.length > 0 && /* @__PURE__ */ React.createElement("div", { style: {
    position: "fixed",
    right: "max(16px, env(safe-area-inset-right))",
    bottom: "max(16px, env(safe-area-inset-bottom))",
    zIndex: 1e4,
    display: "flex",
    flexDirection: "column",
    gap: 10,
    maxWidth: "calc(100vw - 32px)",
    width: 340,
    pointerEvents: "none"
  } }, jobToasts.map((t) => /* @__PURE__ */ React.createElement(
    "div",
    {
      key: t.id,
      onClick: () => setJobToasts((prev) => prev.filter((x) => x.id !== t.id)),
      style: {
        pointerEvents: "auto",
        position: "relative",
        background: "#ffffff",
        border: `1px solid ${t.ok ? "#f9a8d4" : "#fecaca"}`,
        borderLeft: `4px solid ${t.ok ? "#e6007a" : "#dc2626"}`,
        borderRadius: 10,
        boxShadow: "0 10px 30px rgba(15,23,42,0.18), 0 2px 8px rgba(15,23,42,0.08)",
        padding: "12px 30px 12px 14px",
        cursor: "pointer",
        animation: "slideDown 0.18s ease-out"
      }
    },
    /* @__PURE__ */ React.createElement(
      "button",
      {
        type: "button",
        "aria-label": "Dismiss notification",
        onClick: (e) => {
          e.stopPropagation();
          setJobToasts((prev) => prev.filter((x) => x.id !== t.id));
        },
        style: {
          position: "absolute",
          top: 6,
          right: 6,
          width: 22,
          height: 22,
          border: "none",
          borderRadius: "50%",
          background: "transparent",
          color: "#64748b",
          fontSize: 16,
          lineHeight: "20px",
          cursor: "pointer",
          padding: 0,
          display: "flex",
          alignItems: "center",
          justifyContent: "center"
        }
      },
      "\xD7"
    ),
    /* @__PURE__ */ React.createElement("div", { style: { fontSize: 13, fontWeight: 700, color: "#0f172a", marginBottom: 4 } }, t.title),
    /* @__PURE__ */ React.createElement("div", { style: { fontSize: 13, color: "#475569", lineHeight: 1.4 } }, t.body)
  ))));
  function renderAcordLicenseModal() {
    return /* @__PURE__ */ React.createElement("div", { className: "modal-overlay" }, /* @__PURE__ */ React.createElement("div", { className: "modal-content acord-license-modal", onClick: (e) => e.stopPropagation() }, /* @__PURE__ */ React.createElement("button", { className: "modal-close", onClick: () => {
      setShowAcordModal(false);
      setAcordLicenseChecked(false);
    } }, "\u2715"), /* @__PURE__ */ React.createElement("div", { className: "modal-inner" }, /* @__PURE__ */ React.createElement("div", { className: "acord-license-icon" }), /* @__PURE__ */ React.createElement("h2", { className: "acord-license-title" }, "ACORD\xAE License Confirmation"), /* @__PURE__ */ React.createElement("div", { className: "acord-license-body" }, /* @__PURE__ */ React.createElement("p", null, "ACORD\xAE Forms are copyrighted material owned by ACORD Corporation and are licensed, not sold. By continuing, you confirm that you or your organization maintain a valid ACORD license permitting the use of these forms."), /* @__PURE__ */ React.createElement("p", null, "If your organization does not currently have an ACORD license, you can obtain one", " ", /* @__PURE__ */ React.createElement("a", { href: "https://www.acord.org/forms-pages/forms-participation-programs/forms-end-user-licenses", target: "_blank", rel: "noopener noreferrer", className: "acord-license-link" }, "HERE"), ".")), /* @__PURE__ */ React.createElement("label", { className: "acord-confirm-checkbox-label", style: { display: "flex", alignItems: "center", gap: 10, cursor: "pointer" } }, /* @__PURE__ */ React.createElement("input", { type: "checkbox", checked: acordLicenseChecked, onChange: (e) => setAcordLicenseChecked(e.target.checked), className: "acord-confirm-checkbox", style: { flexShrink: 0, width: 16, height: 16, marginTop: 0, cursor: "pointer" } }), /* @__PURE__ */ React.createElement("span", null, "My organization holds a valid ACORD license.")), /* @__PURE__ */ React.createElement("button", { className: "btn btn-modal-primary btn-block", onClick: handleAcordConfirm, disabled: !acordLicenseChecked || acordModalLoading }, acordModalLoading ? /* @__PURE__ */ React.createElement("span", { style: { display: "flex", alignItems: "center", justifyContent: "center", gap: 8 } }, /* @__PURE__ */ React.createElement("span", { style: { width: 14, height: 14, border: "2px solid currentColor", borderTopColor: "transparent", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" } }), "Confirming...") : "Confirm and Download"), /* @__PURE__ */ React.createElement("div", { className: "acord-stub-actions" }, /* @__PURE__ */ React.createElement("span", { className: "acord-stub-label" }, "Coming soon:"), /* @__PURE__ */ React.createElement("button", { className: "btn-stub", disabled: true }, "Email"), /* @__PURE__ */ React.createElement("button", { className: "btn-stub", disabled: true }, "Share"), /* @__PURE__ */ React.createElement("button", { className: "btn-stub", disabled: true }, "Fax")), /* @__PURE__ */ React.createElement("button", { className: "btn btn-modal-secondary btn-block", onClick: () => {
      setShowAcordModal(false);
      setAcordLicenseChecked(false);
    } }, "Cancel"))));
  }
  function renderContent() {
    return /* @__PURE__ */ React.createElement(React.Fragment, null, showUploadOverlay && /* @__PURE__ */ React.createElement(
      ProcessStageOverlay,
      {
        stages: ["Reading your documents\u2026", "Extracting facts\u2026"],
        advanceAfter: 3500,
        tagline: "Quality takes time. But not as much time if you were still doing this manually.",
        note: "You can leave this page during processing, but do not close it. Please enable your browser notifications, and we'll let you know as soon as it's ready."
      }
    ), showGenerateOverlay && /* @__PURE__ */ React.createElement(
      ProcessStageOverlay,
      {
        stages: [`Selecting ${checkedFormIds.size} form${checkedFormIds.size !== 1 ? "s" : ""}\u2026`, "Generating form\u2026"],
        advanceAfter: 3e3,
        tagline: "Quality takes time. But not as much time if you were still doing this manually.",
        note: "You can leave this page during processing, but do not close it. Please enable your browser notifications, and we'll let you know as soon as it's ready."
      }
    ), showDownloadOverlay && /* @__PURE__ */ React.createElement(ProcessStageOverlay, { stages: ["Preparing your form\u2026", "Packaging for download\u2026"], advanceAfter: 2e3 }), loading && !showUploadOverlay && !showGenerateOverlay && !showDownloadOverlay && step !== "editor" && /* @__PURE__ */ React.createElement("div", { className: "loading-overlay" }, /* @__PURE__ */ React.createElement("div", { className: "loading-spinner" }), /* @__PURE__ */ React.createElement("p", { className: "loading-text" }, processingStage || "Processing...")), user && user.subscription_tier === "free" && user.downloads_remaining === 0 && step !== "upload" && step !== "dashboard" && /* @__PURE__ */ React.createElement("div", { className: "freemium-banner freemium-depleted" }, /* @__PURE__ */ React.createElement("span", { className: "freemium-text" }, "Free limit reached \u2014 upgrade to continue"), /* @__PURE__ */ React.createElement("button", { className: "freemium-upgrade-btn", onClick: onShowUpgrade }, "Upgrade Now")), inOverage && /* @__PURE__ */ React.createElement("div", { style: { background: "#fff7ed", border: "1px solid #fed7aa", borderRadius: 8, padding: "9px 14px", fontSize: 12, color: "#92400e", marginBottom: 8, display: "flex", alignItems: "center", gap: 8 } }, /* @__PURE__ */ React.createElement("span", null, "You're in overage territory \u2014 each additional download will be billed on your next invoice.")), user && user.subscription_tier !== "free" && (() => {
      const ps = user.payment_status;
      if (ps === "archived") return /* @__PURE__ */ React.createElement("div", { className: "payment-status-banner payment-status-archived" }, "\u{1F5C4}\uFE0F Account archived \u2014 ", /* @__PURE__ */ React.createElement("a", { href: "mailto:support@primble.ai" }, "Contact support"), " to restore.");
      if (ps === "suspended") return /* @__PURE__ */ React.createElement("div", { className: "payment-status-banner payment-status-suspended" }, "Account suspended.", " ", /* @__PURE__ */ React.createElement("button", { onClick: onOpenBillingPortal, disabled: billingPortalLoading, style: { color: "inherit", fontWeight: 700, textDecoration: "underline", background: "none", border: "none", cursor: billingPortalLoading ? "wait" : "pointer", padding: 0, display: "inline-flex", alignItems: "center", gap: 4 } }, billingPortalLoading && /* @__PURE__ */ React.createElement(BillingBtnSpinner, null), "Restore billing"));
      if (ps === "soft_locked") return /* @__PURE__ */ React.createElement("div", { className: "payment-status-banner payment-status-locked" }, "Account Disabled \u2014 Please", " ", /* @__PURE__ */ React.createElement("button", { onClick: onOpenBillingPortal, disabled: billingPortalLoading, style: { color: "inherit", fontWeight: 700, textDecoration: "underline", background: "none", border: "none", cursor: billingPortalLoading ? "wait" : "pointer", padding: 0, display: "inline-flex", alignItems: "center", gap: 4 } }, billingPortalLoading && /* @__PURE__ */ React.createElement(BillingBtnSpinner, null), "update your billing"), " ", "to restore access.");
      if (ps === "failed") {
        const daysFailed = user.payment_failed_at ? Math.floor((Date.now() - new Date(user.payment_failed_at).getTime()) / 864e5) : 0;
        if (daysFailed >= 7) return /* @__PURE__ */ React.createElement("div", { className: "payment-status-banner payment-status-failed", style: { background: "#fef2f2", borderColor: "#fca5a5", fontWeight: 700, display: "flex", alignItems: "center", gap: 8, flexWrap: "nowrap" } }, "Payment still overdue \u2014 account will be restricted soon.", " ", /* @__PURE__ */ React.createElement("button", { onClick: onOpenBillingPortal, disabled: billingPortalLoading, style: { color: "inherit", fontWeight: 700, textDecoration: "underline", background: "none", border: "none", cursor: billingPortalLoading ? "wait" : "pointer", padding: 0, flexShrink: 0, display: "inline-flex", alignItems: "center", gap: 4 } }, billingPortalLoading && /* @__PURE__ */ React.createElement(BillingBtnSpinner, null), "Update billing now"));
        return /* @__PURE__ */ React.createElement("div", { className: "payment-status-banner payment-status-failed" }, "Payment overdue \u2014", " ", /* @__PURE__ */ React.createElement("button", { onClick: onOpenBillingPortal, disabled: billingPortalLoading, style: { color: "inherit", fontWeight: 700, textDecoration: "underline", background: "none", border: "none", cursor: billingPortalLoading ? "wait" : "pointer", padding: 0, display: "inline-flex", alignItems: "center", gap: 4 } }, billingPortalLoading && /* @__PURE__ */ React.createElement(BillingBtnSpinner, null), "update billing"));
      }
      return null;
    })(), pkgStatusMsg && /* @__PURE__ */ React.createElement("div", { className: "overage-inline-notice", style: { background: pkgStatusType === "overage" ? "#fefce8" : "#f0fdf4", borderColor: pkgStatusType === "overage" ? "#fde047" : "#86efac", color: pkgStatusType === "overage" ? "#713f12" : "#14532d" } }, /* @__PURE__ */ React.createElement("span", null), /* @__PURE__ */ React.createElement("span", null, pkgStatusMsg, " ", /* @__PURE__ */ React.createElement("button", { onClick: () => setPkgStatusMsg(""), style: { background: "none", border: "none", cursor: "pointer", color: "inherit", fontWeight: 700, fontSize: 12, textDecoration: "underline" } }, "Dismiss"))), error && /* @__PURE__ */ React.createElement("div", { className: "alert alert-error", style: { display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 8 } }, /* @__PURE__ */ React.createElement("span", { style: { flex: 1 } }, error), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 8, alignItems: "center" } }, step === "recommendations" && checkedFormIds.size > 0 && /* @__PURE__ */ React.createElement(
      "button",
      {
        onClick: () => {
          setError(null);
          handleGenerateAll();
        },
        style: { padding: "5px 14px", background: "#E61B84", color: "#fff", border: "none", borderRadius: 6, fontSize: 12, fontWeight: 700, cursor: "pointer", whiteSpace: "nowrap" }
      },
      "Retry Generation"
    ), /* @__PURE__ */ React.createElement("button", { className: "alert-close", onClick: () => setError(null) }, "\u2715"))), step === "dashboard" && /* @__PURE__ */ React.createElement(DashboardStep, { token, onResume: handleResumeSession, onNewPackage: handleNewPackage }), step === "lite" && (() => {
      const sqs = liteSqsData?.sqs;
      const liteReady = !liteGenerating && !!sqs;
      const liteGradeColor = (g) => ({ A: "#10b981", B: "#eab308", C: "#f59e0b", D: "#ef4444", F: "#ef4444" })[g] || "#94a3b8";
      const liteGradeBg = (g) => ({ A: "rgba(16,185,129,0.08)", B: "rgba(234,179,8,0.08)", C: "rgba(245,158,11,0.08)", D: "rgba(239,68,68,0.08)", F: "rgba(239,68,68,0.08)" })[g] || "rgba(148,163,184,0.08)";
      const routingLabel = {
        auto_quote: "Auto-Route to Quoting",
        review: "Light Review",
        priority_review: "Priority Review",
        standard_review: "Standard Review",
        full_review: "Full Package Review",
        hold: "Hold \u2014 Remediation Required"
      };
      const routingStyle = {
        auto_quote: { bg: "#dcfce7", color: "#166534", border: "#86efac" },
        review: { bg: "#fef9c3", color: "#854d0e", border: "#fde047" },
        priority_review: { bg: "#fef9c3", color: "#854d0e", border: "#fde047" },
        standard_review: { bg: "#fef3c7", color: "#92400e", border: "#fcd34d" },
        full_review: { bg: "#fef2f2", color: "#991b1b", border: "#fecaca" },
        hold: { bg: "#fee2e2", color: "#991b1b", border: "#fca5a5" }
      };
      const rd = sqs?.routing_decision;
      const rs = routingStyle[rd] || { bg: "#f1f5f9", color: "#475569", border: "#e2e8f0" };
      return /* @__PURE__ */ React.createElement("div", { style: { maxWidth: 960, margin: "0 auto", padding: "0 16px" } }, /* @__PURE__ */ React.createElement("div", { style: { marginBottom: 28 } }, /* @__PURE__ */ React.createElement("div", { style: { display: "inline-flex", alignItems: "center", gap: 6, fontSize: 13, fontWeight: 700, color: "#E61B84", letterSpacing: "0.08em", textTransform: "uppercase", background: "rgba(230,0,122,0.07)", padding: "3px 10px", borderRadius: 20, marginBottom: 10 } }, "Essentials"), /* @__PURE__ */ React.createElement("h2", { style: { fontSize: 26, fontWeight: 700, color: "#0f172a", margin: "0 0 6px", letterSpacing: "-0.3px" } }, "Submission Analysis"), /* @__PURE__ */ React.createElement("p", { style: { fontSize: 13.5, color: "#64748b", margin: 0 } }, liteGenerating ? "Carefully analyzing your submission to generate a submission quality score and identify critical gaps." : "Your SQS score is ready. Use the tools below to complete your workflow.")), /* @__PURE__ */ React.createElement("div", { style: { background: "#fff", border: "1.5px solid #e2e8f0", borderRadius: 20, padding: "28px 36px", marginBottom: 16, boxShadow: "0 2px 8px rgba(0,0,0,0.05)" } }, !sqs ? /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", alignItems: "center", padding: "24px 0", gap: 14 } }, /* @__PURE__ */ React.createElement("span", { style: { width: 40, height: 40, border: "3px solid #e2e8f0", borderTopColor: "#E61B84", borderRadius: "50%", display: "inline-block", animation: "spin 0.8s linear infinite" } }), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 14, color: "#64748b", fontWeight: 500 } }, "Generating your full analysis\u2026"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 12, color: "#94a3b8" } }, "Calculating SQS and pre-building client questionnaire\u2026")) : /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 15, fontWeight: 800, color: "#94a3b8", letterSpacing: "0.07em", textTransform: "uppercase", marginBottom: 20 } }, "Submission Quality Score"), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 28, marginBottom: 20, flexWrap: "wrap" } }, /* @__PURE__ */ React.createElement("div", { style: { position: "relative", flexShrink: 0 } }, /* @__PURE__ */ React.createElement("div", { style: { width: 120, height: 120, borderRadius: "50%", background: liteGradeBg(sqs.grade), border: `3px solid ${liteGradeColor(sqs.grade)}`, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center" } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 42, fontWeight: 900, color: liteGradeColor(sqs.grade), lineHeight: 1 } }, sqs.sqs_score ?? "\u2014"), /* @__PURE__ */ React.createElement("span", { style: { fontSize: 12, fontWeight: 700, color: liteGradeColor(sqs.grade), opacity: 0.75, marginTop: 2 } }, "/100")), /* @__PURE__ */ React.createElement("div", { style: { position: "absolute", bottom: -4, right: -4, width: 32, height: 32, borderRadius: "50%", background: liteGradeColor(sqs.grade), display: "flex", alignItems: "center", justifyContent: "center", fontSize: 14, fontWeight: 800, color: "#fff", boxShadow: "0 2px 6px rgba(0,0,0,0.2)" } }, sqs.grade)), /* @__PURE__ */ React.createElement("div", { style: { flex: 1, minWidth: 200 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 18, fontWeight: 700, color: "#0f172a", marginBottom: 6 } }, sqs.tier || "Submission Scored"), rd && /* @__PURE__ */ React.createElement("div", { style: { display: "inline-flex", alignItems: "center", gap: 6, padding: "5px 12px", borderRadius: 20, border: `1px solid ${rs.border}`, background: rs.bg, color: rs.color, fontSize: 12, fontWeight: 700, marginBottom: 12 } }, routingLabel[rd] || rd), sqs.breakdown && Object.keys(sqs.breakdown).length > 0 && /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 6, marginTop: 4 } }, Object.entries(sqs.breakdown).slice(0, 4).map(([key, val]) => /* @__PURE__ */ React.createElement("div", { key }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", justifyContent: "space-between", fontSize: 11, marginBottom: 2 } }, /* @__PURE__ */ React.createElement("span", { style: { color: "#64748b" } }, SQS_LABELS[key] || key), /* @__PURE__ */ React.createElement("span", { style: { fontWeight: 700, color: barColor(val) } }, val, "%")), /* @__PURE__ */ React.createElement("div", { style: { height: 4, background: "#f1f5f9", borderRadius: 2, overflow: "hidden" } }, /* @__PURE__ */ React.createElement("div", { style: { height: "100%", width: `${val}%`, background: barColor(val), borderRadius: 2, transition: "width 0.6s ease" } }))))))), (liteSqsData?.hard_stops?.length > 0 || liteSqsData?.soft_stops?.length > 0) && /* @__PURE__ */ React.createElement("div", { style: { borderTop: "1px solid #f1f5f9", paddingTop: 16 } }, /* @__PURE__ */ React.createElement("div", { className: "lite-stops-grid" }, liteSqsData?.hard_stops?.length > 0 && /* @__PURE__ */ React.createElement("div", { style: { background: "#fef2f2", border: "1px solid #fecaca", borderRadius: 10, padding: "12px 16px" } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, fontWeight: 700, color: "#991b1b", marginBottom: 7 } }, "Hard Stops \u2014 Caps Your Score at 60"), liteSqsData.hard_stops.map((s, i) => /* @__PURE__ */ React.createElement("div", { key: i, style: { fontSize: 12, color: "#7f1d1d", padding: "2px 0", display: "flex", gap: 6 } }, /* @__PURE__ */ React.createElement("span", { style: { flexShrink: 0 } }, "\u2022"), /* @__PURE__ */ React.createElement("span", null, s)))), liteSqsData?.soft_stops?.length > 0 && /* @__PURE__ */ React.createElement("div", { style: { background: "#fffbeb", border: "1px solid #fde68a", borderRadius: 10, padding: "12px 16px" } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, fontWeight: 700, color: "#92400e", marginBottom: 7 } }, "Warnings \u2014 Will Cap Your Score at 85"), liteSqsData.soft_stops.map((s, i) => /* @__PURE__ */ React.createElement("div", { key: i, style: { fontSize: 12, color: "#78350f", padding: "2px 0", display: "flex", gap: 6 } }, /* @__PURE__ */ React.createElement("span", { style: { flexShrink: 0 } }, "\u2022"), /* @__PURE__ */ React.createElement("span", null, s)))))))), /* @__PURE__ */ React.createElement("div", { style: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, marginBottom: 24 } }, /* @__PURE__ */ React.createElement("div", { style: { background: "#fff", border: "1.5px solid #e2e8f0", borderRadius: 16, padding: "22px 24px 20px", display: "flex", flexDirection: "column", boxShadow: "0 1px 4px rgba(0,0,0,0.04)" } }, /* @__PURE__ */ React.createElement("div", { style: { width: 40, height: 40, borderRadius: 10, background: "rgba(230,0,122,0.08)", display: "flex", alignItems: "center", justifyContent: "center", marginBottom: 12 } }, /* @__PURE__ */ React.createElement("svg", { width: "20", height: "20", viewBox: "0 0 24 24", fill: "none", stroke: "#E61B84", strokeWidth: "2", strokeLinecap: "round", strokeLinejoin: "round" }, /* @__PURE__ */ React.createElement("path", { d: "M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" }), /* @__PURE__ */ React.createElement("polyline", { points: "22,6 12,13 2,6" }))), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 14, fontWeight: 700, color: "#0f172a", marginBottom: 4 } }, "Send to Client"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 12, color: "#64748b", marginBottom: 16, lineHeight: 1.55, flex: 1 } }, "Client-in-the-Loop\u2122 - send a targeted questionnaire to fill gaps and improve your score."), /* @__PURE__ */ React.createElement(
        "button",
        {
          onClick: handleOpenARQ,
          disabled: !liteReady || arqLoadingQ,
          style: { width: "100%", padding: "11px 14px", borderRadius: 10, border: "none", background: !liteReady || arqLoadingQ ? "#e2e8f0" : "#E61B84", color: !liteReady || arqLoadingQ ? "#94a3b8" : "#fff", fontSize: 13, fontWeight: 700, cursor: !liteReady || arqLoadingQ ? "not-allowed" : "pointer", fontFamily: "inherit", display: "flex", alignItems: "center", justifyContent: "center", gap: 6, transition: "background 0.15s, box-shadow 0.15s", boxShadow: !liteReady || arqLoadingQ ? "none" : "0 4px 12px rgba(230,0,122,0.25)" },
          onMouseEnter: (e) => {
            if (liteReady && !arqLoadingQ) {
              e.currentTarget.style.background = "#C0157A";
              e.currentTarget.style.boxShadow = "0 6px 18px rgba(230,0,122,0.35)";
            }
          },
          onMouseLeave: (e) => {
            if (liteReady && !arqLoadingQ) {
              e.currentTarget.style.background = "#E61B84";
              e.currentTarget.style.boxShadow = "0 4px 12px rgba(230,0,122,0.25)";
            }
          }
        },
        liteGenerating ? /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("span", { style: { width: 11, height: 11, border: "2px solid #94a3b8", borderTopColor: "#475569", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" } }), " Preparing\u2026") : arqLoadingQ ? /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("span", { style: { width: 11, height: 11, border: "2px solid #94a3b8", borderTopColor: "#475569", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" } }), " Loading\u2026") : "Send to Client"
      ), /* @__PURE__ */ React.createElement(ARQStatusPanel, { arqSessions, token, onRefresh: refreshArqData })), /* @__PURE__ */ React.createElement("div", { style: { background: "#fff", border: "1.5px solid #e2e8f0", borderRadius: 16, padding: "22px 24px 20px", display: "flex", flexDirection: "column", boxShadow: "0 1px 4px rgba(0,0,0,0.04)" } }, /* @__PURE__ */ React.createElement("div", { style: { width: 40, height: 40, borderRadius: 10, background: "rgba(230,0,122,0.08)", display: "flex", alignItems: "center", justifyContent: "center", marginBottom: 12 } }, /* @__PURE__ */ React.createElement("svg", { width: "20", height: "20", viewBox: "0 0 24 24", fill: "none", stroke: "#E61B84", strokeWidth: "2", strokeLinecap: "round", strokeLinejoin: "round" }, /* @__PURE__ */ React.createElement("path", { d: "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" }), /* @__PURE__ */ React.createElement("polyline", { points: "14 2 14 8 20 8" }), /* @__PURE__ */ React.createElement("line", { x1: "16", y1: "13", x2: "8", y2: "13" }), /* @__PURE__ */ React.createElement("line", { x1: "16", y1: "17", x2: "8", y2: "17" }), /* @__PURE__ */ React.createElement("polyline", { points: "10 9 9 9 8 9" }))), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 14, fontWeight: 700, color: "#0f172a", marginBottom: 4 } }, "Submission Brief"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 12, color: "#64748b", marginBottom: 16, lineHeight: 1.55, flex: 1 } }, "Complete submission quality narrative - easy to read for both human review and AI intake engines."), /* @__PURE__ */ React.createElement(
        "button",
        {
          onClick: handleLiteCoverSheet,
          disabled: !liteReady || liteCoverLoading,
          style: { width: "100%", padding: "11px 14px", borderRadius: 10, border: "none", background: !liteReady || liteCoverLoading ? "#e2e8f0" : "#E61B84", color: !liteReady || liteCoverLoading ? "#94a3b8" : "#fff", fontSize: 13, fontWeight: 700, cursor: !liteReady || liteCoverLoading ? "not-allowed" : "pointer", fontFamily: "inherit", display: "flex", alignItems: "center", justifyContent: "center", gap: 6, transition: "background 0.15s, box-shadow 0.15s", boxShadow: !liteReady || liteCoverLoading ? "none" : "0 4px 12px rgba(230,0,122,0.25)" },
          onMouseEnter: (e) => {
            if (liteReady && !liteCoverLoading) {
              e.currentTarget.style.background = "#C0157A";
              e.currentTarget.style.boxShadow = "0 6px 18px rgba(230,0,122,0.35)";
            }
          },
          onMouseLeave: (e) => {
            if (liteReady && !liteCoverLoading) {
              e.currentTarget.style.background = "#E61B84";
              e.currentTarget.style.boxShadow = "0 4px 12px rgba(230,0,122,0.25)";
            }
          }
        },
        liteGenerating ? /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("span", { style: { width: 11, height: 11, border: "2px solid #94a3b8", borderTopColor: "#475569", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" } }), " Preparing\u2026") : liteCoverLoading ? /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("span", { style: { width: 11, height: 11, border: "2px solid #94a3b8", borderTopColor: "#475569", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" } }), " Generating\u2026") : "Download Brief"
      ))), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", justifyContent: "space-between", paddingTop: 4, gap: 12 } }, /* @__PURE__ */ React.createElement(
        "button",
        {
          onClick: () => {
            resetToUpload();
          },
          style: { padding: "10px 22px", borderRadius: 10, border: "1.5px solid #fecaca", background: "#fef2f2", color: "#991b1b", fontSize: 13, fontWeight: 600, cursor: "pointer", fontFamily: "inherit", boxShadow: "0 2px 8px rgba(0,0,0,0.07)", transition: "box-shadow 0.15s, transform 0.15s, border-color 0.15s" },
          onMouseEnter: (e) => {
            e.currentTarget.style.boxShadow = "0 4px 16px rgba(0,0,0,0.12)";
            e.currentTarget.style.transform = "translateY(-1px)";
            e.currentTarget.style.borderColor = "#fca5a5";
          },
          onMouseLeave: (e) => {
            e.currentTarget.style.boxShadow = "0 2px 8px rgba(0,0,0,0.07)";
            e.currentTarget.style.transform = "none";
            e.currentTarget.style.borderColor = "#fecaca";
          }
        },
        "\u2190 New Submission"
      ), /* @__PURE__ */ React.createElement(
        "button",
        {
          onClick: onShowUpgrade,
          style: { padding: "10px 22px", borderRadius: 10, border: "1.5px solid #fecaca", background: "#fef2f2", color: "#991b1b", fontSize: 13, fontWeight: 700, cursor: "pointer", fontFamily: "inherit", boxShadow: "0 2px 8px rgba(0,0,0,0.07)", transition: "box-shadow 0.15s, transform 0.15s, background 0.15s, border-color 0.15s" },
          onMouseEnter: (e) => {
            e.currentTarget.style.background = "#fee2e2";
            e.currentTarget.style.boxShadow = "0 4px 16px rgba(0,0,0,0.12)";
            e.currentTarget.style.transform = "translateY(-1px)";
            e.currentTarget.style.borderColor = "#fca5a5";
          },
          onMouseLeave: (e) => {
            e.currentTarget.style.background = "#fef2f2";
            e.currentTarget.style.boxShadow = "0 2px 8px rgba(0,0,0,0.07)";
            e.currentTarget.style.transform = "none";
            e.currentTarget.style.borderColor = "#fecaca";
          }
        },
        "Unlock Full Forms"
      )));
    })(), step === "upload" && (() => {
      if (freeExhausted) {
        return /* @__PURE__ */ React.createElement("div", { style: { maxWidth: 560, margin: "0 auto", textAlign: "center", padding: "60px 24px" } }, /* @__PURE__ */ React.createElement("div", { style: { width: 72, height: 72, borderRadius: 20, background: "rgba(230,0,122,0.08)", display: "flex", alignItems: "center", justifyContent: "center", margin: "0 auto 20px" } }, /* @__PURE__ */ React.createElement("svg", { width: "32", height: "32", viewBox: "0 0 24 24", fill: "none", stroke: "#E61B84", strokeWidth: "1.8", strokeLinecap: "round", strokeLinejoin: "round" }, /* @__PURE__ */ React.createElement("polyline", { points: "17 11 12 6 7 11" }), /* @__PURE__ */ React.createElement("line", { x1: "12", y1: "6", x2: "12", y2: "18" }))), /* @__PURE__ */ React.createElement("h2", { style: { fontSize: 26, fontWeight: 700, color: "#0f172a", marginBottom: 10 } }, "Free Limit Reached"), /* @__PURE__ */ React.createElement("p", { style: { fontSize: 15, color: "#64748b", marginBottom: 28, lineHeight: 1.6 } }, "You've used all your free downloads. Upgrade to keep generating ACORD packages."), /* @__PURE__ */ React.createElement(
          "button",
          {
            onClick: onShowUpgrade,
            style: { padding: "13px 36px", background: "#E61B84", color: "#fff", border: "none", borderRadius: 10, fontSize: 15, fontWeight: 700, cursor: "pointer", boxShadow: "0 4px 14px rgba(230,0,122,0.3)" },
            onMouseEnter: (e) => {
              e.currentTarget.style.background = "#C0157A";
              e.currentTarget.style.transform = "translateY(-1px)";
            },
            onMouseLeave: (e) => {
              e.currentTarget.style.background = "#E61B84";
              e.currentTarget.style.transform = "none";
            }
          },
          "Upgrade Now"
        ), /* @__PURE__ */ React.createElement("div", { style: { marginTop: 16 } }, /* @__PURE__ */ React.createElement("button", { onClick: goToDashboard, style: { background: "none", border: "none", color: "#94a3b8", fontSize: 13, cursor: "pointer", textDecoration: "underline" } }, "Back to Dashboard")));
      }
      const ps = user?.payment_status;
      const uploadBlocked = ps === "soft_locked" || ps === "suspended" || ps === "archived";
      const blockMsg = ps === "archived" ? "Account archived \u2014 contact support to restore." : ps === "suspended" ? "Account suspended \u2014 restore billing to continue." : ps === "soft_locked" ? "Account Disabled \u2014 please update your billing." : null;
      const activeBtn = files.length && !loading && !uploadBlocked;
      return /* @__PURE__ */ React.createElement("div", { style: { maxWidth: 640, margin: "0 auto", padding: "0 4px" } }, /* @__PURE__ */ React.createElement("div", { style: { textAlign: "center", marginBottom: 28 } }, /* @__PURE__ */ React.createElement("div", { style: { display: "inline-block", fontSize: 10, fontWeight: 700, color: "#991b1b", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 10, padding: "3px 10px", background: "#fef2f2", border: "1px solid #fecaca", borderRadius: 20 } }, "New Submission"), /* @__PURE__ */ React.createElement("h2", { style: { fontSize: 26, fontWeight: 700, color: "#0f172a", margin: "0 0 6px", letterSpacing: "-0.3px" } }, "Upload Documents"), /* @__PURE__ */ React.createElement("p", { style: { fontSize: 13.5, color: "#64748b", margin: 0, lineHeight: 1.5 } }, "Dec pages, loss runs, schedules, quotes \u2014 PDFs, images, or ZIP archives")), uploadBlocked && /* @__PURE__ */ React.createElement("div", { style: { background: "#fef2f2", border: "1px solid #fecaca", borderRadius: 10, padding: "11px 16px", marginBottom: 20, fontSize: 13, color: "#dc2626", textAlign: "center" } }, blockMsg), /* @__PURE__ */ React.createElement("div", { style: {
        background: "#fff",
        borderRadius: 20,
        boxShadow: "0 2px 8px rgba(0,0,0,0.06), 0 8px 32px rgba(0,0,0,0.09), 0 0 0 1px rgba(0,0,0,0.04)",
        overflow: "hidden",
        padding: "8px"
      } }, /* @__PURE__ */ React.createElement("input", { ref: fileInputRef, type: "file", accept: ".pdf,.zip,.jpg,.jpeg,.png,.bmp,.tiff,.webp,application/pdf,application/zip,image/*", multiple: true, disabled: uploadBlocked, onChange: (e) => setFiles((prev) => [...prev, ...Array.from(e.target.files)]), style: { position: "absolute", width: 1, height: 1, opacity: 0, overflow: "hidden", clip: "rect(0,0,0,0)", whiteSpace: "nowrap" } }), /* @__PURE__ */ React.createElement(
        "label",
        {
          onDragOver: handleDragOver,
          onDragLeave: handleDragLeave,
          onDrop: handleDrop,
          onClick: () => {
            if (!uploadBlocked) fileInputRef.current?.click();
          },
          style: {
            display: "block",
            position: "relative",
            padding: dragging ? "52px 32px" : "44px 32px",
            border: `2px dashed ${dragging ? "#E61B84" : "#e2e8f0"}`,
            borderRadius: 14,
            background: dragging ? "rgba(230,0,122,0.03)" : "#fafbfc",
            transition: "all 0.18s ease",
            cursor: uploadBlocked ? "not-allowed" : "pointer",
            textAlign: "center"
          }
        },
        /* @__PURE__ */ React.createElement("div", { style: { marginBottom: 16, display: "flex", justifyContent: "center" } }, /* @__PURE__ */ React.createElement("svg", { width: "44", height: "44", viewBox: "0 0 44 44", fill: "none", xmlns: "http://www.w3.org/2000/svg", style: { opacity: dragging ? 1 : 0.55, transition: "opacity 0.18s" } }, /* @__PURE__ */ React.createElement("rect", { width: "44", height: "44", rx: "12", fill: dragging ? "rgba(230,0,122,0.1)" : "#f1f5f9" }), /* @__PURE__ */ React.createElement("path", { d: "M22 28V18M22 18L18 22M22 18L26 22", stroke: dragging ? "#E61B84" : "#64748b", strokeWidth: "2", strokeLinecap: "round", strokeLinejoin: "round" }), /* @__PURE__ */ React.createElement("path", { d: "M14 31h16", stroke: dragging ? "#E61B84" : "#64748b", strokeWidth: "2", strokeLinecap: "round" }))),
        /* @__PURE__ */ React.createElement("p", { style: { fontSize: 15, fontWeight: 600, color: "#1e293b", margin: "0 0 4px" } }, "Drag & drop files"),
        /* @__PURE__ */ React.createElement("p", { style: { fontSize: 13.5, color: "#64748b", margin: "0 0 12px" } }, "or ", /* @__PURE__ */ React.createElement("span", { style: { color: "#E61B84", fontWeight: 600, textDecoration: "underline" } }, "click to browse")),
        /* @__PURE__ */ React.createElement("p", { style: { fontSize: 11.5, color: "#94a3b8", margin: 0, letterSpacing: "0.01em" } }, "PDFs \xB7 Images (JPG, PNG, BMP, TIFF) \xB7 ZIP archives")
      ), files.length > 0 && /* @__PURE__ */ React.createElement("div", { style: { padding: "0 16px 16px", marginTop: -4 } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 6, maxHeight: 196, overflowY: "auto", paddingRight: 2 } }, files.map((f, i) => {
        const isZip = f.name.toLowerCase().endsWith(".zip");
        const isImg = f.type?.startsWith("image/");
        const ext = f.name.split(".").pop()?.toUpperCase() || "FILE";
        return /* @__PURE__ */ React.createElement("div", { key: i, style: { display: "flex", alignItems: "center", gap: 10, padding: "9px 12px", background: "#f8fafc", border: "1px solid #e9edf2", borderRadius: 9, fontSize: 13 } }, /* @__PURE__ */ React.createElement("span", { style: {
          flexShrink: 0,
          width: 32,
          height: 32,
          borderRadius: 7,
          background: isZip ? "#fef3c7" : isImg ? "#ede9fe" : "#dbeafe",
          color: isZip ? "#92400e" : isImg ? "#6d28d9" : "#1d4ed8",
          fontSize: 9,
          fontWeight: 800,
          letterSpacing: "0.04em",
          display: "flex",
          alignItems: "center",
          justifyContent: "center"
        } }, isZip ? "ZIP" : isImg ? ext : "PDF"), /* @__PURE__ */ React.createElement("span", { style: { flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "#1e293b", fontWeight: 500 } }, f.name), /* @__PURE__ */ React.createElement("span", { style: { fontSize: 11, color: "#94a3b8", flexShrink: 0 } }, (f.size / 1024).toFixed(0), " KB"), /* @__PURE__ */ React.createElement(
          "button",
          {
            onClick: () => setFiles((prev) => prev.filter((_, j) => j !== i)),
            style: { background: "none", border: "none", cursor: "pointer", color: "#cbd5e1", fontSize: 14, padding: "2px 4px", lineHeight: 1, borderRadius: 4, transition: "color 0.15s" },
            onMouseEnter: (e) => e.currentTarget.style.color = "#E61B84",
            onMouseLeave: (e) => e.currentTarget.style.color = "#cbd5e1",
            title: "Remove file"
          },
          "\u2715"
        ));
      }))), /* @__PURE__ */ React.createElement("div", { style: { padding: "8px 8px 8px" } }, /* @__PURE__ */ React.createElement(
        "button",
        {
          onClick: handleUpload,
          disabled: !files.length || loading || uploadBlocked,
          style: {
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
            opacity: uploadBlocked ? 0.6 : 1
          },
          onMouseEnter: (e) => {
            if (!loading) e.currentTarget.style.background = "#cc006e";
          },
          onMouseLeave: (e) => {
            if (!loading) e.currentTarget.style.background = "#E61B84";
          }
        },
        loading && /* @__PURE__ */ React.createElement("svg", { width: "16", height: "16", viewBox: "0 0 16 16", fill: "none", style: { animation: "spin 0.8s linear infinite", flexShrink: 0 } }, /* @__PURE__ */ React.createElement("circle", { cx: "8", cy: "8", r: "6", stroke: "rgba(255,255,255,0.35)", strokeWidth: "2.5" }), /* @__PURE__ */ React.createElement("path", { d: "M8 2a6 6 0 0 1 6 6", stroke: "#fff", strokeWidth: "2.5", strokeLinecap: "round" })),
        loading ? "Analyzing..." : files.length > 0 ? `Analyze ${files.length > 1 ? files.length + " Files" : "File"}` : "Analyze File"
      ))));
    })(), step === "stopped" && /* @__PURE__ */ React.createElement("div", { className: "modal-step" }, /* @__PURE__ */ React.createElement("div", { className: "stop-banner stop-hard" }, /* @__PURE__ */ React.createElement("div", { className: "stop-icon" }), /* @__PURE__ */ React.createElement("h2", { className: "stop-title" }, "Submission Blocked \u2014 Minimum Fields Missing"), /* @__PURE__ */ React.createElement("p", { className: "stop-subtitle" }, "ACORD 125 cannot be generated. Missing:")), /* @__PURE__ */ React.createElement("div", { className: "stop-fields" }, hardStops.map((f, i) => /* @__PURE__ */ React.createElement("div", { key: i, className: "stop-field-item" }, /* @__PURE__ */ React.createElement("span", { className: "stop-field-icon" }), /* @__PURE__ */ React.createElement("span", null, f)))), /* @__PURE__ */ React.createElement("p", { className: "stop-advice" }, "Upload documents that include these fields, then try again."), /* @__PURE__ */ React.createElement("button", { className: "btn btn-modal-primary", onClick: resetToUpload }, "\u2190 Upload New Documents")), integrityBusy && /* @__PURE__ */ React.createElement(
      ProcessStageOverlay,
      {
        stages: ["Reviewing your documents...", "Re-assessing submission package..."],
        advanceAfter: 2e3,
        tagline: "Checking which documents belong together."
      }
    ), step === "integrity_review" && integrity && !integrityBusy && /* @__PURE__ */ React.createElement("div", { className: "modal-step modal-step-wide" }, /* @__PURE__ */ React.createElement("div", { style: {
      background: "rgba(230,27,132,0.07)",
      border: "1.5px solid rgba(230,27,132,0.25)",
      borderRadius: 12,
      padding: "18px 22px",
      marginBottom: 20
    } }, /* @__PURE__ */ React.createElement("h2", { style: { margin: 0, fontSize: 18, fontWeight: 700, color: "#9d0f5a" } }, "Submission Integrity Review Needed"), /* @__PURE__ */ React.createElement("p", { style: { margin: "8px 0 0", fontSize: 13.5, color: "#b01868", lineHeight: 1.55 } }, "Primble detected that the uploaded documents may not belong to the same submission. Please review the package before continuing.")), integrity.detected_entities?.length > 0 && /* @__PURE__ */ React.createElement("div", { style: { marginBottom: 16 } }, /* @__PURE__ */ React.createElement("div", { style: { fontWeight: 600, color: "#1e293b", marginBottom: 6, fontSize: 13 } }, "Detected entities"), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexWrap: "wrap", gap: 8 } }, integrity.detected_entities.map((e, i) => /* @__PURE__ */ React.createElement("span", { key: i, style: { background: "rgba(230,27,132,0.08)", color: "#9d0f5a", border: "1px solid rgba(230,27,132,0.22)", borderRadius: 999, padding: "4px 14px", fontSize: 13, fontWeight: 600 } }, e)))), integrity.reasons?.length > 0 && /* @__PURE__ */ React.createElement("div", { style: { marginBottom: 16, background: "#fff", border: "1px solid #e2e8f0", borderRadius: 8, padding: "12px 16px" } }, /* @__PURE__ */ React.createElement("div", { style: { fontWeight: 600, color: "#334155", marginBottom: 6, fontSize: 13 } }, "Why this was flagged"), integrity.reasons.map((r, i) => /* @__PURE__ */ React.createElement("div", { key: i, style: { color: "#475569", fontSize: 13, padding: "2px 0" } }, "\u2022 ", r))), /* @__PURE__ */ React.createElement("div", { style: { marginBottom: 8 } }, /* @__PURE__ */ React.createElement("div", { style: { fontWeight: 600, color: "#1e293b", marginBottom: 10, fontSize: 13 } }, "Uploaded documents \u2014 check any that don't belong, then remove them"), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 8 } }, (integrity.documents || []).map((d) => {
      const checked = removeDocIds.has(d.doc_id);
      return /* @__PURE__ */ React.createElement("label", { key: d.doc_id, style: {
        display: "flex",
        alignItems: "center",
        gap: 12,
        background: checked ? "rgba(230,27,132,0.07)" : "#fff",
        border: `1.5px solid ${checked ? "rgba(230,27,132,0.35)" : "#e2e8f0"}`,
        borderRadius: 9,
        padding: "10px 14px",
        cursor: "pointer",
        transition: "background 0.15s, border-color 0.15s"
      } }, /* @__PURE__ */ React.createElement(
        "input",
        {
          type: "checkbox",
          checked,
          disabled: integrityBusy,
          onChange: () => {
            setRemoveDocIds((prev) => {
              const next = new Set(prev);
              if (next.has(d.doc_id)) next.delete(d.doc_id);
              else next.add(d.doc_id);
              return next;
            });
          }
        }
      ), /* @__PURE__ */ React.createElement("span", { style: { background: "#eef2ff", color: "#4338ca", borderRadius: 6, padding: "2px 8px", fontSize: 11, fontWeight: 600, textTransform: "uppercase", flexShrink: 0 } }, String(d.doc_type || "unknown").replace(/_/g, " ")), /* @__PURE__ */ React.createElement("span", { style: { flex: 1, minWidth: 0 } }, /* @__PURE__ */ React.createElement("span", { style: { display: "block", fontWeight: 600, color: "#1e293b", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } }, d.filename), /* @__PURE__ */ React.createElement("span", { style: { display: "block", fontSize: 12, color: "#64748b" } }, "Insured: ", d.applicant, d.fein ? ` \xB7 FEIN \u2022\u2022${d.fein}` : "")));
    }))), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 10, marginTop: 24 } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexWrap: "wrap", gap: 10 } }, /* @__PURE__ */ React.createElement(
      "button",
      {
        className: "btn btn-modal-secondary",
        disabled: integrityBusy || removeDocIds.size === 0,
        onClick: () => handleResolveIntegrity("remove_documents")
      },
      `Remove selected${removeDocIds.size ? ` (${removeDocIds.size})` : ""}`
    ), /* @__PURE__ */ React.createElement(
      "button",
      {
        className: "btn btn-modal-primary",
        disabled: integrityBusy,
        onClick: () => handleResolveIntegrity("continue_anyway")
      },
      "Continue anyway"
    )), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement(
      "button",
      {
        className: "btn btn-modal-secondary",
        disabled: integrityBusy,
        onClick: resetToUpload,
        style: { fontSize: 13 }
      },
      "\u2190 Upload new documents"
    ))), /* @__PURE__ */ React.createElement("p", { style: { fontSize: 12, color: "#94a3b8", marginTop: 14, lineHeight: 1.5 } }, 'Choosing "Continue anyway" records your acknowledgment and proceeds with all documents as a single submission.')), step === "recommendations" && /* @__PURE__ */ React.createElement("div", { className: "modal-step modal-step-wide" }, /* @__PURE__ */ React.createElement("div", { className: "step-header" }, /* @__PURE__ */ React.createElement("h2", { className: "step-title", style: { color: "#1e293b" } }, "Select Forms to Generate"), /* @__PURE__ */ React.createElement("p", { className: "step-subtitle" }, "Select the forms you need, then generate all at once.")), /* @__PURE__ */ React.createElement("div", { className: "doc-summary" }, /* @__PURE__ */ React.createElement("div", { className: "doc-summary-title" }, "DOCUMENTS PROCESSED"), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 8 } }, docSummary.map((d, i) => {
      const docType = d.doc_type || "unknown";
      const label = d.doc_type_label || docType.replace(/_/g, " ");
      const conf = d.doc_type_confidence || "";
      const isUnknown = docType === "unknown";
      const needsReview = isUnknown || conf === "low" || d.doc_type_source === "filename";
      const excluded = !!d.excluded;
      const busy = reclassDocId && reclassDocId === d.doc_id;
      const confColor = conf === "high" ? "#16a34a" : conf === "medium" ? "#d97706" : "#dc2626";
      return /* @__PURE__ */ React.createElement("div", { key: d.doc_id || i, style: {
        display: "flex",
        alignItems: "center",
        gap: 10,
        flexWrap: "wrap",
        padding: "8px 12px",
        borderRadius: 8,
        border: `1px solid ${needsReview ? "#fbbf24" : "#e2e8f0"}`,
        background: excluded ? "#f8fafc" : needsReview ? "#fffbeb" : "#fff",
        opacity: excluded ? 0.6 : 1
      } }, /* @__PURE__ */ React.createElement("span", { className: "doc-type-badge", style: { textTransform: "capitalize" } }, label), d.doc_type_overridden ? /* @__PURE__ */ React.createElement("span", { title: "You set this type", style: { fontSize: 10, color: "#2563eb", fontWeight: 600 } }, "\u2713 you set this") : conf && /* @__PURE__ */ React.createElement("span", { title: `Classification confidence: ${conf}`, style: { fontSize: 10, color: confColor, fontWeight: 600, textTransform: "uppercase" } }, conf), /* @__PURE__ */ React.createElement("span", { className: "doc-filename", style: { flex: 1, minWidth: 120, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } }, d.filename), excluded && /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10, color: "#64748b", fontStyle: "italic" } }, "excluded from scoring"), availableDocTypes.length > 0 && !excluded && /* @__PURE__ */ React.createElement(
        "select",
        {
          value: docType,
          disabled: busy,
          onChange: (e) => {
            if (e.target.value && e.target.value !== docType) handleReclassify(d.doc_id, "set_type", e.target.value);
          },
          title: "Correct the document type",
          style: { fontSize: 12, padding: "3px 6px", borderRadius: 6, border: "1px solid #cbd5e1", background: "#fff", color: "#334155", cursor: busy ? "wait" : "pointer" }
        },
        availableDocTypes.map((t) => /* @__PURE__ */ React.createElement("option", { key: t.value, value: t.value }, t.label))
      ), /* @__PURE__ */ React.createElement(
        "button",
        {
          type: "button",
          disabled: busy,
          onClick: () => handleReclassify(d.doc_id, excluded ? "include" : "exclude"),
          title: excluded ? "Include this document in scoring" : "Exclude this document from scoring",
          style: { fontSize: 11, padding: "3px 8px", borderRadius: 6, border: "1px solid #cbd5e1", background: "#fff", color: "#475569", cursor: busy ? "wait" : "pointer", display: "inline-flex", alignItems: "center", gap: 4, minWidth: 58, justifyContent: "center" }
        },
        busy ? /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("span", { style: { width: 10, height: 10, border: "2px solid #cbd5e1", borderTopColor: "#E61B84", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" } }), excluded ? "Include" : "Exclude") : excluded ? "Include" : "Exclude"
      ));
    })), docSummary.some((d) => (d.doc_type || "unknown") === "unknown" || d.doc_type_confidence === "low") && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: "#92400e", marginTop: 6 } }, "Some documents need review. Set the correct type so scoring and form recommendations use them \u2014 or exclude documents that don't belong.")), underwriting?.fields?.length > 0 && /* @__PURE__ */ React.createElement("div", { className: "doc-summary", style: { marginTop: 12 } }, /* @__PURE__ */ React.createElement("div", { className: "doc-summary-title" }, "DATA CONSISTENCY"), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 10 } }, underwriting.fields.map((f) => {
      const isConflict = f.status === "conflict";
      const isConfirmed = f.status === "confirmed";
      const busy = underwritingBusy === f.fact_key;
      const picked = underwritingPicks[f.fact_key] ?? "";
      const formsLabel = (f.forms || []).map((x) => x.replace("ACORD_", "ACORD ")).join(", ");
      return /* @__PURE__ */ React.createElement("div", { key: f.fact_key, style: {
        padding: "10px 12px",
        borderRadius: 8,
        border: `1px solid ${isConflict ? "#fbbf24" : isConfirmed ? "#86efac" : "#e2e8f0"}`,
        background: isConflict ? "#fffbeb" : isConfirmed ? "#f0fdf4" : "#fff"
      } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" } }, /* @__PURE__ */ React.createElement("span", { style: { fontWeight: 600, color: "#1e293b", fontSize: 13 } }, f.label), isConflict && /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10, fontWeight: 700, color: "#b45309", textTransform: "uppercase" } }, "\u26A0 Values differ \u2014 confirm"), isConfirmed && /* @__PURE__ */ React.createElement("span", { style: { fontSize: 11, fontWeight: 600, color: "#16a34a" } }, "\u2713 Confirmed: ", f.confirmed_value, formsLabel ? ` \u2014 applied to ${formsLabel}` : ""), f.status === "consistent" && /* @__PURE__ */ React.createElement("span", { style: { fontSize: 11, color: "#16a34a" } }, "\u2713 Consistent: ", f.values?.[0]?.display)), (isConflict || f.status === "consistent") && /* @__PURE__ */ React.createElement("div", { style: { marginTop: 6, display: "flex", flexDirection: "column", gap: 4 } }, f.values.map((v, vi) => /* @__PURE__ */ React.createElement("div", { key: vi, style: { display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: "#475569", flexWrap: "wrap" } }, isConflict && /* @__PURE__ */ React.createElement(
        "input",
        {
          type: "radio",
          name: `uw-${f.fact_key}`,
          checked: picked === v.display,
          onChange: () => setUnderwritingPicks((p) => ({ ...p, [f.fact_key]: v.display })),
          disabled: busy
        }
      ), /* @__PURE__ */ React.createElement("span", { style: { fontWeight: 600, color: "#0f172a" } }, v.display), /* @__PURE__ */ React.createElement("span", { style: { color: "#94a3b8" } }, "from"), /* @__PURE__ */ React.createElement("span", { style: { color: "#334155" } }, v.sources.map((s) => s.filename).join(", "))))), isConflict && /* @__PURE__ */ React.createElement("div", { style: { marginTop: 8, display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" } }, /* @__PURE__ */ React.createElement(
        "input",
        {
          type: "text",
          value: picked,
          disabled: busy,
          placeholder: "\u2026or type a value",
          onChange: (e) => setUnderwritingPicks((p) => ({ ...p, [f.fact_key]: e.target.value })),
          style: { fontSize: 12, padding: "4px 8px", borderRadius: 6, border: "1px solid #cbd5e1", width: 160 }
        }
      ), /* @__PURE__ */ React.createElement(
        "button",
        {
          type: "button",
          disabled: busy || !picked,
          onClick: () => handleConfirmUnderwriting(f.fact_key, picked),
          style: { fontSize: 12, fontWeight: 600, padding: "5px 12px", borderRadius: 6, border: "none", background: picked && !busy ? "#2563eb" : "#cbd5e1", color: "#fff", cursor: picked && !busy ? "pointer" : "not-allowed" }
        },
        busy ? "Applying\u2026" : "Confirm & apply to forms"
      )));
    }))), (hardStops.length > 0 || softStops.length > 0) && /* @__PURE__ */ React.createElement("div", { className: "stops-row" }, hardStops.length > 0 && /* @__PURE__ */ React.createElement("div", { className: "stops-banner stops-hard" }, /* @__PURE__ */ React.createElement("div", { className: "stops-title" }, "Hard Stops - Caps Your SQS at 60"), hardStops.map((s, i) => /* @__PURE__ */ React.createElement("div", { key: i, className: "stop-item stop-item-hard" }, "- ", s))), softStops.length > 0 && /* @__PURE__ */ React.createElement("div", { className: "stops-banner stops-soft" }, /* @__PURE__ */ React.createElement("div", { className: "stops-title" }, "Warnings - Caps Your SQS at 85"), softStops.map((s, i) => /* @__PURE__ */ React.createElement("div", { key: i, className: "stop-item stop-item-soft" }, "- ", s)))), canProceedWithWarning && warningStops.length > 0 && /* @__PURE__ */ React.createElement("div", { className: "stops-banner stops-warning", style: { margin: "8px 0", padding: "12px 16px", background: "#fffbeb", border: "1px solid #f59e0b", borderRadius: 8 } }, /* @__PURE__ */ React.createElement("div", { className: "stops-title", style: { color: "#b45309", fontWeight: 600, marginBottom: 6 } }, "Incomplete Submission \u2014 Review Before Generating"), warningStops.map((s, i) => /* @__PURE__ */ React.createElement("div", { key: i, className: "stop-item", style: { color: "#92400e", fontSize: 13, marginBottom: 2 } }, "- ", s)), /* @__PURE__ */ React.createElement("div", { style: { marginTop: 10, fontSize: 13, color: "#78350f" } }, "This submission is missing information typically required for property coverage. Forms can still be generated, but the underwriter may request additional data.")), tier2Score !== null && /* @__PURE__ */ React.createElement("div", { className: "tier2-bar" }, /* @__PURE__ */ React.createElement("div", { className: "tier2-header" }, /* @__PURE__ */ React.createElement("span", { className: "tier2-label" }, "Submission Readiness"), /* @__PURE__ */ React.createElement("span", { className: "tier2-score", style: { color: barColor(tier2Score) } }, tier2Score, "%")), /* @__PURE__ */ React.createElement("div", { className: "metric-bar" }, /* @__PURE__ */ React.createElement("div", { className: "metric-fill", style: { width: `${tier2Score}%`, background: barColor(tier2Score) } })), tier2Missing.length > 0 && /* @__PURE__ */ React.createElement("div", { className: "tier2-missing" }, "Missing: ", tier2Missing.join(" \xB7 "))), /* @__PURE__ */ React.createElement("div", { className: "form-selection-list" }, /* @__PURE__ */ React.createElement("div", { className: "form-selection-header" }, /* @__PURE__ */ React.createElement("span", { className: "form-selection-title" }, "Recommended Forms"), /* @__PURE__ */ React.createElement("span", { className: "form-selection-hint" }, checkedFormIds.size, " selected")), recommendations.map((rec, i) => {
      const pct = Math.round((rec.confidence || 0) * 100);
      const tooltipText = rec.fields_total > 0 ? `${rec.fields_filled} of ${rec.fields_total} required fields found in your document` : rec.reason || "";
      return /* @__PURE__ */ React.createElement("div", { key: rec.form_id, className: `form-select-row ${checkedFormIds.has(rec.form_id) ? "form-row-checked" : ""}` }, /* @__PURE__ */ React.createElement("label", { className: "form-select-checkbox-label" }, /* @__PURE__ */ React.createElement("input", { type: "checkbox", checked: checkedFormIds.has(rec.form_id), onChange: () => toggleForm(rec.form_id), className: "form-select-checkbox" }), /* @__PURE__ */ React.createElement("div", { className: "form-select-info" }, /* @__PURE__ */ React.createElement("div", { className: "form-select-name" }, /* @__PURE__ */ React.createElement("span", { className: "rec-rank" }, "#", i + 1), rec.form_name), /* @__PURE__ */ React.createElement("div", { className: "form-select-meta" }, /* @__PURE__ */ React.createElement(
        "span",
        {
          className: "confidence-badge",
          title: tooltipText,
          style: { cursor: "help" }
        },
        "Match ",
        pct,
        "%"
      ), /* @__PURE__ */ React.createElement("span", { className: "form-select-reason" }, rec.reason || rec.trigger_reason)))));
    })), extraForms.length > 0 && /* @__PURE__ */ React.createElement("div", { className: "add-forms-section" }, /* @__PURE__ */ React.createElement("button", { className: "btn btn-modal-secondary btn-small", onClick: () => setShowAddForms((v) => !v) }, showAddForms ? "\u25B2 Hide" : "\u25BC Add more ACORD forms", " (", extraForms.length, " available)"), showAddForms && /* @__PURE__ */ React.createElement("div", { className: "extra-forms-list" }, extraForms.map((f) => {
      const pct = Math.round((f.confidence || 0) * 100);
      const tooltipText = f.fields_total > 0 ? `${f.fields_filled} of ${f.fields_total} required fields found in your document` : f.description || "";
      return /* @__PURE__ */ React.createElement("div", { key: f.form_id, className: `form-select-row ${checkedFormIds.has(f.form_id) ? "form-row-checked" : ""}` }, /* @__PURE__ */ React.createElement("label", { className: "form-select-checkbox-label" }, /* @__PURE__ */ React.createElement("input", { type: "checkbox", checked: checkedFormIds.has(f.form_id), onChange: () => toggleForm(f.form_id), className: "form-select-checkbox" }), /* @__PURE__ */ React.createElement("div", { className: "form-select-info" }, /* @__PURE__ */ React.createElement("div", { className: "form-select-name" }, f.form_name), /* @__PURE__ */ React.createElement("div", { className: "form-select-meta" }, pct > 0 && /* @__PURE__ */ React.createElement(
        "span",
        {
          className: "confidence-badge confidence-badge--extra",
          title: tooltipText,
          style: { cursor: "help" }
        },
        "Match ",
        pct,
        "%"
      ), (f.reason || f.description) && /* @__PURE__ */ React.createElement("span", { className: "form-select-reason" }, f.reason || f.description)))));
    }))), /* @__PURE__ */ React.createElement("button", { className: "btn btn-modal-primary btn-block btn-large", onClick: handleGenerateAll, disabled: loading || checkedFormIds.size === 0 }, loading ? "Generating..." : `Generate ${checkedFormIds.size} Form${checkedFormIds.size !== 1 ? "s" : ""} Now`)), step === "editor" && /* @__PURE__ */ React.createElement("div", { className: `editor-layout editor-layout-fullpage${!sidebarOpen ? " sidebar-closed" : ""}` }, /* @__PURE__ */ React.createElement("div", { className: "editor-sidebar", style: { background: "#fff", borderRight: "1px solid #e2e8f0", padding: 0, gap: 0 } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", justifyContent: "space-between", padding: "10px 14px", borderBottom: "1px solid #f1f5f9", background: "#fafbfc" } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 7 } }, /* @__PURE__ */ React.createElement("span", { style: { display: "flex", alignItems: "center", justifyContent: "center", width: 26, height: 26, borderRadius: 7, background: "rgba(230,27,132,0.1)" } }, /* @__PURE__ */ React.createElement("svg", { width: "13", height: "13", viewBox: "0 0 24 24", fill: "none", stroke: "#E61B84", strokeWidth: "2.2", strokeLinecap: "round", strokeLinejoin: "round" }, /* @__PURE__ */ React.createElement("polyline", { points: "22 12 18 12 15 21 9 3 6 12 2 12" }))), /* @__PURE__ */ React.createElement("span", { style: { fontSize: 12, fontWeight: 700, color: "#1e293b", letterSpacing: "0.01em" } }, "SQS & Actions")), /* @__PURE__ */ React.createElement("button", { className: "sidebar-close-btn", onClick: () => setSidebarOpen(false), title: "Hide panel" }, "\u2715")), /* @__PURE__ */ React.createElement("div", { style: { padding: "14px 14px 12px" } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10, fontWeight: 700, color: "#94a3b8", letterSpacing: "0.06em", textTransform: "uppercase" } }, "Generated Forms"), /* @__PURE__ */ React.createElement("span", { style: { fontSize: 11, fontWeight: 700, color: "#E61B84", background: "rgba(230,0,122,0.08)", padding: "1px 7px", borderRadius: 20 } }, formIdList.length)), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 2, maxHeight: 130, overflowY: "auto" } }, formIdList.map((fid) => {
      const fd = generatedForms[fid];
      const sq = fd?.sqs;
      const isActive = activeFormId === fid;
      return /* @__PURE__ */ React.createElement(
        "div",
        {
          key: fid,
          onClick: () => setActiveFormId(fid),
          style: { padding: "7px 9px", borderRadius: 7, cursor: "pointer", border: `1px solid ${isActive ? "#E61B84" : "transparent"}`, background: isActive ? "rgba(230,0,122,0.05)" : "transparent", transition: "all 0.15s" },
          onMouseEnter: (e) => {
            if (!isActive) e.currentTarget.style.background = "#f8fafc";
          },
          onMouseLeave: (e) => {
            if (!isActive) e.currentTarget.style.background = "transparent";
          }
        },
        /* @__PURE__ */ React.createElement("div", { style: { fontSize: 12, fontWeight: 600, color: isActive ? "#E61B84" : "#1e293b" } }, fd?.form_name || fid, signedForms.has(fid) && /* @__PURE__ */ React.createElement("span", { style: { color: "#10b981", fontSize: 10 } }, " (signed)"), pdfLoading[fid] ? /* @__PURE__ */ React.createElement("span", { style: { color: "#f59e0b", fontSize: 10 } }, " (loading)") : /* @__PURE__ */ React.createElement("span", { style: { color: "#10b981", fontSize: 10 } }, " (ready)")),
        sq && /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 6, marginTop: 2 } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10, fontWeight: 700, color: gradeColor(sq.grade) } }, sq.sqs_score, " ", sq.grade), /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10, color: "#94a3b8" } }, sq.tier))
      );
    })), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 10, paddingTop: 8, borderTop: "1px solid #f1f5f9" } }, /* @__PURE__ */ React.createElement("button", { onClick: goPrev, disabled: activeIdx <= 0, style: { padding: "4px 10px", borderRadius: 6, border: "1px solid #e2e8f0", background: "#f8fafc", fontSize: 12, fontWeight: 600, color: activeIdx <= 0 ? "#cbd5e1" : "#475569", cursor: activeIdx <= 0 ? "not-allowed" : "pointer" } }, "\u2190 Prev"), /* @__PURE__ */ React.createElement("span", { style: { fontSize: 11, color: "#94a3b8" } }, activeIdx + 1, " / ", formIdList.length), /* @__PURE__ */ React.createElement("button", { onClick: goNext, disabled: activeIdx >= formIdList.length - 1, style: { padding: "4px 10px", borderRadius: 6, border: "1px solid #e2e8f0", background: "#f8fafc", fontSize: 12, fontWeight: 600, color: activeIdx >= formIdList.length - 1 ? "#cbd5e1" : "#475569", cursor: activeIdx >= formIdList.length - 1 ? "not-allowed" : "pointer" } }, "Next \u2192"))), activeSqs && /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("div", { style: { height: 1, background: "#f1f5f9", margin: "0 14px" } }), /* @__PURE__ */ React.createElement("div", { style: { padding: "14px 14px 12px" } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 10, marginBottom: 10 } }, /* @__PURE__ */ React.createElement("div", { style: { width: 36, height: 36, borderRadius: "50%", background: gradeColor(activeSqs.grade), display: "flex", alignItems: "center", justifyContent: "center", fontSize: 14, fontWeight: 800, color: "#fff", flexShrink: 0 } }, activeSqs.grade), /* @__PURE__ */ React.createElement("div", { style: { flex: 1, minWidth: 0 } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "baseline", gap: 4 } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 28, fontWeight: 800, lineHeight: 1, color: gradeColor(activeSqs.grade) } }, activeSqs.sqs_score), /* @__PURE__ */ React.createElement("span", { style: { fontSize: 11, color: "#94a3b8" } }, "/100"), /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10, fontWeight: 700, padding: "2px 7px", borderRadius: 20, color: "#fff", marginLeft: 4, background: { green: "#10b981", yellow: "#f59e0b", orange: "#f97316", red: "#ef4444" }[activeSqs.tier_color] || "#94a3b8" } }, activeSqs.tier)), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "#94a3b8", marginTop: 1, textTransform: "uppercase", letterSpacing: "0.04em", fontWeight: 600 } }, "Form SQS Score"))), activeSqs.confidence_fill_rate != null && /* @__PURE__ */ React.createElement("div", { style: { background: "#fdf2f8", border: "1px solid #f9a8d4", borderRadius: 7, padding: "7px 10px", marginBottom: 10, boxShadow: "0 2px 8px rgba(230,0,122,0.07)" } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10, fontWeight: 700, color: "#000" } }, "Quality Fill Rate"), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 8, alignItems: "center" } }, activeSqs.fill_rate != null && activeSqs.fill_rate !== activeSqs.confidence_fill_rate && /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10, color: "#94a3b8", textDecoration: "line-through" } }, activeSqs.fill_rate, "%"), /* @__PURE__ */ React.createElement("span", { style: { fontSize: 12, fontWeight: 800, color: barColor(activeSqs.confidence_fill_rate) } }, activeSqs.confidence_fill_rate, "%"))), /* @__PURE__ */ React.createElement("div", { style: { height: 4, background: "#e2e8f0", borderRadius: 2, overflow: "hidden" } }, /* @__PURE__ */ React.createElement("div", { style: { height: "100%", width: `${activeSqs.confidence_fill_rate}%`, background: barColor(activeSqs.confidence_fill_rate), borderRadius: 2, transition: "width 0.6s ease" } })), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 9, color: "#94a3b8", marginTop: 3 } }, "Producer edits = 100% \xB7 AI high = 85% \xB7 AI low = 50%")), packageSqs && packageSqs.sqs_history?.length > 1 && (() => {
      const baseline = packageSqs.sqs_history.find((h) => h?.stage === "initial_extract") || packageSqs.sqs_history[0];
      return /* @__PURE__ */ React.createElement("div", { style: { background: "#fdf2f8", border: "1px solid #f9a8d4", borderRadius: 7, padding: "6px 10px", marginBottom: 10, display: "flex", alignItems: "center", gap: 8, boxShadow: "0 2px 8px rgba(230,0,122,0.07)" } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 14 } }), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 11, fontWeight: 700, color: packageSqs.delta_this_session >= 0 ? "#059669" : "#dc2626" } }, packageSqs.delta_this_session >= 0 ? "+" : "", packageSqs.delta_this_session, " pts this session"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, color: "#94a3b8" } }, "Started at ", baseline?.score ?? "\u2014", " \u2192 now ", packageSqs.package_sqs_score)));
    })(), activeSqs.routing_decision && /* @__PURE__ */ React.createElement("div", { style: { padding: "5px 9px", fontSize: 11, fontWeight: 700, textAlign: "center", marginBottom: 12, color: "#000" } }, {
      auto_quote: "Auto-Route to Quoting",
      review: "Light Review",
      priority_review: "Priority Review",
      standard_review: "Standard Review",
      full_review: "Full Package Review",
      hold: "Hold \u2014 Remediation Required"
    }[activeSqs.routing_decision] || activeSqs.routing_decision), (() => {
      const docSourced = /* @__PURE__ */ new Set(["property_integrity", "loss_history_alignment", "narrative_quality"]);
      return /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 8, marginBottom: 10 } }, Object.entries(activeSqs.breakdown || {}).map(([key, val]) => /* @__PURE__ */ React.createElement("div", { key }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", justifyContent: "space-between", fontSize: 11, marginBottom: 3 } }, /* @__PURE__ */ React.createElement("span", { style: { color: "#000" } }, SQS_LABELS[key] || key, /* @__PURE__ */ React.createElement("span", { style: { color: "#94a3b8" } }, " (", SQS_WEIGHTS[key] || 0, "%)"), docSourced.has(key) && /* @__PURE__ */ React.createElement("span", { title: "Sourced from uploaded documents \u2014 editing form fields won't change this", style: { marginLeft: 4, fontSize: 9, color: "#94a3b8", cursor: "help" } }, "(doc)")), /* @__PURE__ */ React.createElement("span", { style: { fontWeight: 700, color: barColor(val) } }, val, "%")), /* @__PURE__ */ React.createElement("div", { style: { height: 5, background: "#f1f5f9", borderRadius: 3, overflow: "hidden" } }, /* @__PURE__ */ React.createElement("div", { style: { height: "100%", width: `${val}%`, background: barColor(val), borderRadius: 3, transition: "width 0.6s ease" } })))), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 9, color: "#94a3b8", marginTop: 2 } }, "(doc) = sourced from uploaded docs, not form edits"));
    })(), packageSqs && /* @__PURE__ */ React.createElement("div", { style: { background: "#fdf2f8", border: "1px solid #f9a8d4", borderRadius: 8, padding: "10px 12px", marginBottom: 10, boxShadow: "0 2px 8px rgba(230,0,122,0.07)" } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, fontWeight: 700, color: "#000", textTransform: "uppercase", letterSpacing: "0.05em" } }, "Package SQS"), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 6 } }, packageSqs.lob && packageSqs.lob !== "generic" && /* @__PURE__ */ React.createElement("span", { style: { fontSize: 9, fontWeight: 700, background: "rgba(230,0,122,0.08)", color: "#E61B84", borderRadius: 20, padding: "1px 6px", textTransform: "capitalize" } }, packageSqs.lob), /* @__PURE__ */ React.createElement("span", { style: { fontSize: 16, fontWeight: 800, color: gradeColor(packageSqs.package_sqs_score >= 90 ? "A" : packageSqs.package_sqs_score >= 80 ? "B" : packageSqs.package_sqs_score >= 70 ? "C" : packageSqs.package_sqs_score >= 60 ? "D" : "F") } }, packageSqs.package_sqs_score), /* @__PURE__ */ React.createElement("span", { style: { fontSize: 9, color: "#94a3b8" } }, "/100"))), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 5 } }, Object.entries(packageSqs.pillars || {}).map(([key, val]) => /* @__PURE__ */ React.createElement("div", { key }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", justifyContent: "space-between", fontSize: 10, marginBottom: 2 } }, /* @__PURE__ */ React.createElement("span", { style: { color: "#000" } }, PACKAGE_PILLAR_LABELS[key] || key), /* @__PURE__ */ React.createElement("span", { style: { fontWeight: 700, color: barColor(val) } }, val)), /* @__PURE__ */ React.createElement("div", { style: { height: 3, background: "#e2e8f0", borderRadius: 2, overflow: "hidden" } }, /* @__PURE__ */ React.createElement("div", { style: { height: "100%", width: `${val}%`, background: barColor(val), borderRadius: 2 } }))))), packageSqs.tier && /* @__PURE__ */ React.createElement("div", { style: { marginTop: 8, padding: "3px 8px", borderRadius: 5, fontSize: 10, fontWeight: 700, textAlign: "center", background: { "Submission Ready": "#dcfce7", "Almost There": "#fef9c3", "Needs Work": "#ffedd5", "Major Gaps": "#fee2e2", "Not Ready": "#fee2e2", "Incomplete": "#f1f5f9" }[packageSqs.tier] || "#f1f5f9", color: { "Submission Ready": "#166534", "Almost There": "#854d0e", "Needs Work": "#9a3412", "Major Gaps": "#991b1b", "Not Ready": "#991b1b", "Incomplete": "#64748b" }[packageSqs.tier] || "#374151" } }, packageSqs.tier)), packageSqs?.top_recommendations?.length > 0 && /* @__PURE__ */ React.createElement("div", { style: { background: "#fdf2f8", borderRadius: 7, padding: "8px 10px", marginBottom: 8, border: "1px solid #f9a8d4", boxShadow: "0 2px 8px rgba(230,0,122,0.07)" } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, fontWeight: 700, color: "#000", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 6 } }, "TOP RECOMMENDATIONS"), packageSqs.top_recommendations.map((r, i) => {
      if (!r) return null;
      if (typeof r === "string") {
        return /* @__PURE__ */ React.createElement("div", { key: i, style: { display: "flex", alignItems: "flex-start", gap: 6, padding: "3px 0" } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10, fontWeight: 700, color: "#E61B84", width: 16 } }, "#", i + 1), /* @__PURE__ */ React.createElement("span", { style: { flex: 1, fontSize: 11, color: "#000" } }, r));
      }
      const pillarLabel = PACKAGE_PILLAR_LABELS[r.pillar] || r.pillar || "";
      return /* @__PURE__ */ React.createElement("div", { key: i, style: { padding: "4px 0", borderBottom: i < packageSqs.top_recommendations.length - 1 ? "1px solid #f9a8d4" : "none" } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", gap: 6 } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10, fontWeight: 700, color: "#E61B84", width: 16 } }, "#", i + 1), /* @__PURE__ */ React.createElement("span", { style: { flex: 1, fontSize: 11, fontWeight: 700, color: "#000" } }, pillarLabel), typeof r.score === "number" && /* @__PURE__ */ React.createElement("span", { style: { fontSize: 11, fontWeight: 700, color: barColor(r.score) } }, r.score, "%")), r.action && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 11, color: "#334155", marginLeft: 22, marginTop: 2 } }, r.action));
    })), activeSqs.risk_drivers?.length > 0 && !packageSqs?.top_recommendations?.length && /* @__PURE__ */ React.createElement("div", { style: { background: "#fdf2f8", borderRadius: 7, padding: "8px 10px", marginBottom: 8, border: "1px solid #f9a8d4", boxShadow: "0 2px 8px rgba(230,0,122,0.07)" } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, fontWeight: 700, color: "#000", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 6 } }, "TOP DRIVERS"), activeSqs.risk_drivers.map((d, i) => /* @__PURE__ */ React.createElement("div", { key: i, style: { display: "flex", alignItems: "center", gap: 6, padding: "3px 0", borderBottom: i < activeSqs.risk_drivers.length - 1 ? "1px solid #f9a8d4" : "none" } }, /* @__PURE__ */ React.createElement("span", { style: { fontSize: 10, fontWeight: 700, color: "#E61B84", width: 16 } }, "#", i + 1), /* @__PURE__ */ React.createElement("span", { style: { flex: 1, fontSize: 11, color: "#000" } }, d.component), /* @__PURE__ */ React.createElement("span", { style: { fontSize: 11, fontWeight: 700, color: barColor(d.score) } }, d.score, "%")))), activeSqs.issues?.length > 0 && /* @__PURE__ */ React.createElement("div", { style: { background: "#fdf2f8", border: "1px solid #f9a8d4", borderRadius: 7, padding: "7px 10px", marginBottom: 8, boxShadow: "0 2px 8px rgba(230,0,122,0.07)" } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, fontWeight: 700, color: "#000", marginBottom: 3 } }, "Issues"), activeSqs.issues.map((s, i) => /* @__PURE__ */ React.createElement("div", { key: i, style: { fontSize: 11, color: "#000", padding: "1px 0" } }, "\u2022 ", s))), activeSqs.recommendations?.length > 0 && /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, fontWeight: 700, color: "#94a3b8", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 6 } }, "Recommendations"), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 6 } }, activeSqs.recommendations.filter((r) => !dismissedRecs.has(typeof r === "string" ? r : r.rec_id)).map((rec, i) => /* @__PURE__ */ React.createElement(
      SidePanelRec,
      {
        key: typeof rec === "object" && rec !== null ? rec.rec_id : `legacy_${i}`,
        rec,
        index: i,
        sqsScore: activeSqs.sqs_score,
        onDismiss: handleDismissRec
      }
    )))))), crossIssues.length > 0 && /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("div", { style: { height: 1, background: "#f1f5f9", margin: "0 14px" } }), /* @__PURE__ */ React.createElement("div", { style: { padding: "12px 14px" } }, /* @__PURE__ */ React.createElement("div", { style: { background: "#fdf2f8", border: "1px solid #f9a8d4", borderRadius: 8, padding: "8px 10px", boxShadow: "0 2px 8px rgba(230,0,122,0.07)" } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 10, fontWeight: 700, color: "#000", letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: 8 } }, "Cross-Form Validation"), crossIssues.map((iss, i) => /* @__PURE__ */ React.createElement("div", { key: i, style: { fontSize: 12, padding: "3px 0", color: "#000" } }, iss.message))))), /* @__PURE__ */ React.createElement("div", { style: { height: 1, background: "#f1f5f9", margin: "0 14px" } }), /* @__PURE__ */ React.createElement("div", { style: { padding: "12px 14px 16px", display: "flex", flexDirection: "column", gap: 8 } }, /* @__PURE__ */ React.createElement(
      "button",
      {
        onClick: handleOpenARQ,
        disabled: arqLoadingQ,
        style: { width: "100%", padding: "12px 16px", borderRadius: 14, border: "none", background: "linear-gradient(135deg, #E61B84 0%, #C0157A 100%)", color: "#fff", fontSize: 13, fontWeight: 700, cursor: arqLoadingQ ? "wait" : "pointer", fontFamily: "inherit", display: "flex", alignItems: "center", justifyContent: "center", gap: 8, opacity: arqLoadingQ ? 0.7 : 1, boxShadow: "0 4px 16px rgba(230,0,122,0.35), 0 1px 3px rgba(230,0,122,0.2)", letterSpacing: "0.02em", transition: "all 0.2s" },
        onMouseEnter: (e) => {
          if (!arqLoadingQ) {
            e.currentTarget.style.background = "linear-gradient(135deg, #C0157A 0%, #a30055 100%)";
            e.currentTarget.style.boxShadow = "0 6px 20px rgba(230,0,122,0.45), 0 1px 3px rgba(230,0,122,0.2)";
            e.currentTarget.style.transform = "translateY(-1px)";
          }
        },
        onMouseLeave: (e) => {
          e.currentTarget.style.background = "linear-gradient(135deg, #E61B84 0%, #C0157A 100%)";
          e.currentTarget.style.boxShadow = "0 4px 16px rgba(230,0,122,0.35), 0 1px 3px rgba(230,0,122,0.2)";
          e.currentTarget.style.transform = "translateY(0)";
        }
      },
      arqLoadingQ ? /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("span", { style: { width: 12, height: 12, border: "2px solid rgba(255,255,255,0.5)", borderTopColor: "#fff", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" } }), " Loading\u2026") : /* @__PURE__ */ React.createElement(React.Fragment, null, "Send to Client", arqNotifCount > 0 && /* @__PURE__ */ React.createElement("span", { style: { background: "#fff", color: "#E61B84", borderRadius: 10, fontSize: 10, padding: "2px 7px", fontWeight: 800, marginLeft: 2 } }, arqNotifCount))
    ), /* @__PURE__ */ React.createElement(ARQStatusPanel, { arqSessions, token, onRefresh: refreshArqData }), /* @__PURE__ */ React.createElement("div", { style: { borderRadius: 14, overflow: "hidden", border: actionsOpen ? "1.5px solid #f9a8d4" : "1.5px solid #fce7f3", boxShadow: actionsOpen ? "0 8px 28px rgba(230,0,122,0.18)" : "0 2px 8px rgba(230,0,122,0.08)", transition: "box-shadow 0.25s, border-color 0.25s" } }, /* @__PURE__ */ React.createElement(
      "button",
      {
        onClick: () => setActionsOpen((o) => !o),
        style: { width: "100%", padding: "12px 16px", background: "linear-gradient(135deg, #E61B84 0%, #C0157A 100%)", border: "none", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", fontFamily: "inherit", fontSize: 13, fontWeight: 700, color: "#fff", letterSpacing: "0.02em", transition: "background 0.2s", gap: 0 },
        onMouseEnter: (e) => {
          e.currentTarget.style.background = "linear-gradient(135deg, #C0157A 0%, #a30055 100%)";
        },
        onMouseLeave: (e) => {
          e.currentTarget.style.background = "linear-gradient(135deg, #E61B84 0%, #C0157A 100%)";
        }
      },
      /* @__PURE__ */ React.createElement("span", { style: { width: 13, flexShrink: 0 } }),
      /* @__PURE__ */ React.createElement("span", { style: { flex: 1, textAlign: "center" } }, "More Actions"),
      /* @__PURE__ */ React.createElement("svg", { width: "13", height: "13", viewBox: "0 0 14 14", fill: "none", style: { transition: "transform 0.25s cubic-bezier(0.4,0,0.2,1)", transform: actionsOpen ? "rotate(180deg)" : "rotate(0deg)", flexShrink: 0 } }, /* @__PURE__ */ React.createElement("path", { d: "M2.5 5L7 9.5L11.5 5", stroke: "rgba(255,255,255,0.9)", strokeWidth: "1.8", strokeLinecap: "round", strokeLinejoin: "round" }))
    ), actionsOpen && /* @__PURE__ */ React.createElement("div", { style: { background: "#fff", borderTop: "1px solid #fce7f3", padding: "8px 8px 10px", display: "flex", flexDirection: "column", gap: 4, animation: "slideDown 0.18s ease-out" } }, /* @__PURE__ */ React.createElement("div", { style: { position: "relative" } }, /* @__PURE__ */ React.createElement("div", { style: { borderRadius: 9, overflow: "hidden", border: "1px solid #fce7f3" } }, /* @__PURE__ */ React.createElement(
      "button",
      {
        onClick: () => setIntegrationsExpanded((o) => !o),
        style: { display: "flex", alignItems: "center", justifyContent: "space-between", width: "100%", padding: "8px 12px", border: "none", background: "linear-gradient(135deg, #E61B84 0%, #C0157A 100%)", color: "#fff", fontSize: 12, fontWeight: 600, cursor: "pointer", fontFamily: "inherit", transition: "all 0.15s", textAlign: "left" },
        onMouseEnter: (e) => {
          e.currentTarget.style.background = "linear-gradient(135deg, #C0157A 0%, #a30055 100%)";
        },
        onMouseLeave: (e) => {
          e.currentTarget.style.background = "linear-gradient(135deg, #E61B84 0%, #C0157A 100%)";
        }
      },
      /* @__PURE__ */ React.createElement("span", null, "Integrations"),
      /* @__PURE__ */ React.createElement("svg", { width: "11", height: "11", viewBox: "0 0 14 14", fill: "none", style: { transition: "transform 0.2s", transform: integrationsExpanded ? "rotate(180deg)" : "rotate(0deg)", flexShrink: 0 } }, /* @__PURE__ */ React.createElement("path", { d: "M2.5 5L7 9.5L11.5 5", stroke: "rgba(255,255,255,0.85)", strokeWidth: "1.8", strokeLinecap: "round", strokeLinejoin: "round" }))
    ), integrationsExpanded && /* @__PURE__ */ React.createElement("div", { style: { background: "#fdf2f8", padding: "6px 8px", display: "flex", flexDirection: "column", gap: 4 } }, /* @__PURE__ */ React.createElement(
      "button",
      {
        onClick: (e) => {
          if (user?.subscription_tier === "enterprise") {
            handleSendToEpic(activeFormId);
          } else {
            triggerEnterprisePopup(e.currentTarget);
          }
        },
        disabled: epicLoading,
        style: { width: "100%", padding: "7px 10px", borderRadius: 7, border: "1px solid #f9a8d4", background: epicSuccess ? "rgba(34,197,94,0.1)" : "#fce7f3", color: epicSuccess ? "#16a34a" : "#9d174d", fontSize: 11, fontWeight: 600, cursor: epicLoading ? "wait" : "pointer", fontFamily: "inherit", transition: "all 0.15s", textAlign: "center", display: "flex", alignItems: "center", justifyContent: "center", gap: 6 },
        onMouseEnter: (e) => {
          if (!epicSuccess && !epicLoading) e.currentTarget.style.background = "#f9a8d4";
        },
        onMouseLeave: (e) => {
          if (!epicSuccess) e.currentTarget.style.background = "#fce7f3";
        }
      },
      /* @__PURE__ */ React.createElement("span", null, epicSuccess ? "Sent to Epic" : epicLoading ? "Sending\u2026" : "Share to Epic"),
      epicLoading && /* @__PURE__ */ React.createElement("span", { style: { width: 9, height: 9, border: "2px solid #f9a8d4", borderTopColor: "#be185d", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" } })
    ), /* @__PURE__ */ React.createElement(
      "button",
      {
        onClick: (e) => {
          if (user?.subscription_tier === "enterprise") {
            handleSendToVertafore(activeFormId);
          } else {
            triggerEnterprisePopup(e.currentTarget);
          }
        },
        disabled: vertaforeLoading,
        style: { width: "100%", padding: "7px 10px", borderRadius: 7, border: "1px solid #f9a8d4", background: vertaforeSuccess ? "rgba(34,197,94,0.1)" : "#fce7f3", color: vertaforeSuccess ? "#16a34a" : "#9d174d", fontSize: 11, fontWeight: 600, cursor: vertaforeLoading ? "wait" : "pointer", fontFamily: "inherit", transition: "all 0.15s", textAlign: "center", display: "flex", alignItems: "center", justifyContent: "center", gap: 6 },
        onMouseEnter: (e) => {
          if (!vertaforeSuccess && !vertaforeLoading) e.currentTarget.style.background = "#f9a8d4";
        },
        onMouseLeave: (e) => {
          if (!vertaforeSuccess) e.currentTarget.style.background = "#fce7f3";
        }
      },
      /* @__PURE__ */ React.createElement("span", null, vertaforeSuccess ? "Sent to Vertafore" : vertaforeLoading ? "Sending\u2026" : "Share to Vertafore"),
      vertaforeLoading && /* @__PURE__ */ React.createElement("span", { style: { width: 9, height: 9, border: "2px solid #f9a8d4", borderTopColor: "#be185d", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" } })
    )))), /* @__PURE__ */ React.createElement("div", { style: { borderRadius: 9, overflow: "hidden", border: "1px solid #fce7f3" } }, /* @__PURE__ */ React.createElement(
      "button",
      {
        onClick: () => setDownloadExpanded((o) => !o),
        style: { display: "flex", alignItems: "center", justifyContent: "space-between", width: "100%", padding: "8px 12px", border: "none", background: "linear-gradient(135deg, #E61B84 0%, #C0157A 100%)", color: "#fff", fontSize: 12, fontWeight: 600, cursor: "pointer", fontFamily: "inherit", transition: "all 0.15s", textAlign: "left" },
        onMouseEnter: (e) => {
          e.currentTarget.style.background = "linear-gradient(135deg, #C0157A 0%, #a30055 100%)";
        },
        onMouseLeave: (e) => {
          e.currentTarget.style.background = "linear-gradient(135deg, #E61B84 0%, #C0157A 100%)";
        }
      },
      /* @__PURE__ */ React.createElement("span", null, "Download"),
      /* @__PURE__ */ React.createElement("svg", { width: "11", height: "11", viewBox: "0 0 14 14", fill: "none", style: { transition: "transform 0.2s", transform: downloadExpanded ? "rotate(180deg)" : "rotate(0deg)", flexShrink: 0 } }, /* @__PURE__ */ React.createElement("path", { d: "M2.5 5L7 9.5L11.5 5", stroke: "rgba(255,255,255,0.85)", strokeWidth: "1.8", strokeLinecap: "round", strokeLinejoin: "round" }))
    ), downloadExpanded && /* @__PURE__ */ React.createElement("div", { style: { background: "#fdf2f8", padding: "6px 8px", display: "flex", flexDirection: "column", gap: 4 } }, /* @__PURE__ */ React.createElement(
      "button",
      {
        onClick: () => handleDownloadOneNoSummary(activeFormId),
        disabled: !activeFormId,
        style: { width: "100%", padding: "7px 10px", borderRadius: 7, border: "1px solid #f9a8d4", background: "#fce7f3", color: "#9d174d", fontSize: 11, fontWeight: 600, cursor: activeFormId ? "pointer" : "not-allowed", opacity: activeFormId ? 1 : 0.5, fontFamily: "inherit", transition: "all 0.15s", textAlign: "center" },
        onMouseEnter: (e) => {
          if (activeFormId) e.currentTarget.style.background = "#f9a8d4";
        },
        onMouseLeave: (e) => {
          e.currentTarget.style.background = "#fce7f3";
        }
      },
      "This Form"
    ), /* @__PURE__ */ React.createElement(
      "button",
      {
        onClick: () => handleDownloadAll(),
        style: { width: "100%", padding: "7px 10px", borderRadius: 7, border: "1px solid #f9a8d4", background: "#fce7f3", color: "#9d174d", fontSize: 11, fontWeight: 600, cursor: "pointer", fontFamily: "inherit", transition: "all 0.15s", textAlign: "center" },
        onMouseEnter: (e) => {
          e.currentTarget.style.background = "#f9a8d4";
        },
        onMouseLeave: (e) => {
          e.currentTarget.style.background = "#fce7f3";
        }
      },
      "Entire Package"
    ), /* @__PURE__ */ React.createElement(
      "button",
      {
        onClick: () => handleLiteCoverSheet(),
        disabled: liteCoverLoading,
        style: { width: "100%", padding: "7px 10px", borderRadius: 7, border: "1px solid #f9a8d4", background: "#fce7f3", color: "#9d174d", fontSize: 11, fontWeight: 600, cursor: liteCoverLoading ? "wait" : "pointer", opacity: liteCoverLoading ? 0.6 : 1, fontFamily: "inherit", transition: "all 0.15s", textAlign: "center", display: "flex", alignItems: "center", justifyContent: "center", gap: 6 },
        onMouseEnter: (e) => {
          if (!liteCoverLoading) e.currentTarget.style.background = "#f9a8d4";
        },
        onMouseLeave: (e) => {
          e.currentTarget.style.background = "#fce7f3";
        }
      },
      /* @__PURE__ */ React.createElement("span", null, liteCoverLoading ? "Generating\u2026" : "Submission Brief"),
      liteCoverLoading && /* @__PURE__ */ React.createElement("span", { style: { width: 9, height: 9, border: "2px solid #f9a8d4", borderTopColor: "#be185d", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" } })
    ))))))), /* @__PURE__ */ React.createElement("div", { className: "editor-main" }, !sidebarOpen && /* @__PURE__ */ React.createElement("button", { className: "sidebar-open-btn", onClick: () => setSidebarOpen(true), title: "Show SQS & Actions" }, /* @__PURE__ */ React.createElement("span", { className: "sidebar-open-label" }, "SQS & ACTIONS")), /* @__PURE__ */ React.createElement(
      PDFJsViewer,
      {
        key: activeFormId,
        pdfUrl: `${API_BASE}/api/get-pdf/${sessionId}/${activeFormId}`,
        formName: activeFormId ? generatedForms[activeFormId]?.form_name || activeFormId : "",
        onFormNav: { goPrev, goNext, activeIdx, total: formIdList.length },
        sessionId,
        formId: activeFormId,
        token,
        savedSignature,
        isSigned: signedForms.has(activeFormId),
        onSignApplied: (fid) => setSignedForms((prev) => /* @__PURE__ */ new Set([...prev, fid])),
        onOpenSignatureModal,
        clientFilledFields,
        onRefreshFields: refreshArqData,
        onSqsUpdate: (fid, newSqs, extras) => {
          setGeneratedForms((prev) => ({
            ...prev,
            [fid]: { ...prev[fid], sqs: newSqs }
          }));
          if (extras?.packageSqs) setPackageSqs(extras.packageSqs);
          if (Array.isArray(extras?.crossIssues)) setCrossIssues(extras.crossIssues);
        }
      }
    ))), step === "success" && /* @__PURE__ */ React.createElement("div", { style: { maxWidth: 480, margin: "0 auto", textAlign: "center", padding: "56px 24px" } }, /* @__PURE__ */ React.createElement("div", { style: { width: 80, height: 80, borderRadius: "50%", background: "linear-gradient(135deg, #E61B84, #C0157A)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 36, color: "#fff", margin: "0 auto 24px", boxShadow: "0 8px 28px rgba(230,0,122,0.3)", animation: "successPop 0.5s ease-out" } }, "\u2713"), /* @__PURE__ */ React.createElement("h2", { style: { fontSize: 26, fontWeight: 800, color: "#0f172a", marginBottom: 8 } }, "Download Complete!"), /* @__PURE__ */ React.createElement("p", { style: { fontSize: 15, color: "#64748b", marginBottom: 28, lineHeight: 1.6 } }, "Your filled ACORD forms have been downloaded successfully."), user && user.subscription_tier === "free" && /* @__PURE__ */ React.createElement("div", { style: { background: "rgba(230,0,122,0.05)", border: "1px solid rgba(230,0,122,0.15)", borderRadius: 10, padding: "12px 16px", marginBottom: 24, fontSize: 14, color: "#1e293b" } }, "You have ", /* @__PURE__ */ React.createElement("strong", { style: { color: "#E61B84" } }, Math.max(0, user.downloads_remaining)), " free download", user.downloads_remaining !== 1 ? "s" : "", " remaining"), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", flexDirection: "column", gap: 10, alignItems: "center" } }, /* @__PURE__ */ React.createElement(
      "button",
      {
        onClick: () => setStep("editor"),
        style: { minWidth: 260, padding: "12px 0", borderRadius: 10, border: "none", background: "#E61B84", color: "#fff", fontSize: 14, fontWeight: 700, cursor: "pointer", boxShadow: "0 4px 14px rgba(230,0,122,0.3)" },
        onMouseEnter: (e) => e.currentTarget.style.background = "#C0157A",
        onMouseLeave: (e) => e.currentTarget.style.background = "#E61B84"
      },
      "\u2190 Back to Form"
    ))));
  }
});
var AcordModal_default = AcordModal;
export {
  AcordModal_default as default
};
