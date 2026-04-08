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

// ── Inline ARQ Modal ───────────────────────────────────────────────────────
function ARQModal({ sessionId, token, questions, onClose, onSuccess }) {
  const [clientEmail,       setClientEmail]       = useState("");
  const [clientName,        setClientName]        = useState("");
  const [selectedQuestions, setSelectedQuestions] = useState({});
  const [sending,           setSending]           = useState(false);
  const [error,             setError]             = useState("");
  const [selectAll,         setSelectAll]         = useState(true);

  useEffect(() => {
    const init = {};
    questions.forEach(q => { init[q.field_name] = true; });
    setSelectedQuestions(init);
  }, [questions]);

  const handleToggle = (fn) => setSelectedQuestions(prev => ({ ...prev, [fn]: !prev[fn] }));

  const handleSelectAll = () => {
    const next = !selectAll; setSelectAll(next);
    const updated = {};
    questions.forEach(q => { updated[q.field_name] = next; });
    setSelectedQuestions(updated);
  };

  const selectedCount = Object.values(selectedQuestions).filter(Boolean).length;
  const isEmailValid  = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(clientEmail);
  const canSend       = isEmailValid && selectedCount > 0;

  const handleSend = async () => {
    if (!canSend) return;
    setSending(true); setError("");
    const selectedList = questions.filter(q => selectedQuestions[q.field_name]);
    try {
      const res  = await fetch(`${API_BASE}/api/arq/send`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ session_id: sessionId, client_email: clientEmail, client_name: clientName, questions: selectedList }),
      });
      const data = await res.json();
      if (res.ok && data.success) { onSuccess(data); }
      else { setError(data.detail || data.message || "Failed to send questionnaire."); }
    } catch (e) { setError("Network error: " + e.message); }
    finally { setSending(false); }
  };

  return (
    <div className="modal-overlay">
      <div className="modal-content arq-modal" onClick={e => e.stopPropagation()} style={{ maxWidth: 640 }}>
        <button className="modal-close" onClick={onClose}>✕</button>
        <div className="modal-inner">
          <div style={{ fontSize: 36, textAlign: "center", marginBottom: 8 }}>📧</div>
          <h2 className="step-title" style={{ textAlign: "center" }}>Send Questionnaire to Client</h2>
          <p className="step-subtitle" style={{ textAlign: "center" }}>Select questions — client answers will auto-populate your forms.</p>

          {error && <div className="alert alert-error" style={{ marginBottom: 16 }}>⚠️ {error}</div>}

          <div className="form-group" style={{ marginBottom: 16 }}>
            <label>Client Email <span className="field-required">*</span></label>
            <input type="email" value={clientEmail} onChange={e => setClientEmail(e.target.value)}
              placeholder="client@company.com" className="form-input" />
          </div>
          <div className="form-group" style={{ marginBottom: 20 }}>
            <label>Client First Name <span style={{ color: "#94a3b8", fontWeight: 400 }}>(optional)</span></label>
            <input type="text" value={clientName} onChange={e => setClientName(e.target.value)}
              placeholder="e.g. John" className="form-input" />
          </div>

          <div style={{ borderTop: "1px solid #e2e8f0", paddingTop: 16 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
              <span style={{ fontWeight: 600, fontSize: 14, color: "#1e293b" }}>
                Questions ({selectedCount}/{questions.length} selected)
              </span>
              <button onClick={handleSelectAll} style={{ background: "none", border: "1px solid #e2e8f0", borderRadius: 6, padding: "4px 12px", fontSize: 12, cursor: "pointer", color: "#4f7cff", fontWeight: 500 }}>
                {selectAll ? "Deselect All" : "Select All"}
              </button>
            </div>
            <div style={{ maxHeight: 320, overflowY: "auto", display: "flex", flexDirection: "column", gap: 8 }}>
              {questions.map((q, idx) => (
                <div key={idx} onClick={() => handleToggle(q.field_name)}
                  style={{ border: `1px solid ${selectedQuestions[q.field_name] ? "#e6007a" : "#e2e8f0"}`, borderRadius: 8, padding: "10px 14px", cursor: "pointer", background: selectedQuestions[q.field_name] ? "rgba(230,0,122,0.04)" : "#fff", display: "flex", alignItems: "flex-start", gap: 10, opacity: selectedQuestions[q.field_name] ? 1 : 0.5, transition: "all 0.15s" }}>
                  <input type="checkbox" checked={!!selectedQuestions[q.field_name]} onChange={() => handleToggle(q.field_name)}
                    onClick={e => e.stopPropagation()}
                    style={{ marginTop: 3, width: 16, height: 16, cursor: "pointer", accentColor: "#e6007a", flexShrink: 0 }} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <span style={{ fontSize: 11, fontWeight: 600, color: "#e6007a", background: "#fdf2f8", padding: "1px 8px", borderRadius: 20, display: "inline-block", marginBottom: 4 }}>
                      ACORD: {q.forms}
                    </span>
                    <p style={{ margin: 0, fontSize: 13, fontWeight: 600, color: "#0f172a", lineHeight: 1.4 }}>{q.question}</p>
                    {q.current_value && <p style={{ margin: "4px 0 0", fontSize: 11, color: "#94a3b8" }}>Current: {q.current_value}</p>}
                  </div>
                </div>
              ))}
            </div>
          </div>

          <button className="btn btn-modal-primary btn-block" onClick={handleSend} disabled={!canSend || sending}
            style={{ marginTop: 20, opacity: (!canSend || sending) ? 0.6 : 1, cursor: (!canSend || sending) ? "not-allowed" : "pointer" }}>
            {sending
              ? <span style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 8 }}><span style={{ width: 14, height: 14, border: "2px solid white", borderTopColor: "transparent", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" }} />Sending…</span>
              : `📧 Send ${selectedCount} Question${selectedCount !== 1 ? "s" : ""} to Client`}
          </button>
          {!isEmailValid && clientEmail && <p style={{ fontSize: 11, color: "#ef4444", textAlign: "center", marginTop: 8 }}>Please enter a valid email address.</p>}
          <p style={{ fontSize: 11, color: "#94a3b8", textAlign: "center", marginTop: 14 }}>
            Client receives a secure link. Answers auto-populate your forms.
          </p>
        </div>
      </div>
    </div>
  );
}

// ── Inline ARQ Status Panel ────────────────────────────────────────────────
function ARQStatusPanel({ arqSessions, token, onRefresh }) {
  const [reminding, setReminding] = useState(null);

  const handleRemind = async (arq_id) => {
    setReminding(arq_id);
    try {
      await fetch(`${API_BASE}/api/arq/remind/${arq_id}`, { method: "POST", headers: { Authorization: `Bearer ${token}` } });
      onRefresh();
    } catch (_) {}
    setReminding(null);
  };

  const fmtDate = iso => iso ? new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "—";

  if (!arqSessions || arqSessions.length === 0) return null;

  return (
    <div style={{ marginTop: 10 }}>
      <div style={{ fontSize: 11, fontWeight: 600, color: "#64748b", marginBottom: 6 }}>📧 Sent Questionnaires</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {arqSessions.map(arq => {
          const isExpired = new Date() > new Date(arq.expires_at) && arq.status !== "submitted";
          const status    = isExpired ? "expired" : arq.status;
          const sc = { submitted: { bg: "#dcfce7", color: "#166534", border: "#86efac" }, expired: { bg: "#f1f5f9", color: "#64748b", border: "#cbd5e1" }, pending: { bg: "#fef9c3", color: "#854d0e", border: "#fde047" } }[status] || {};
          return (
            <div key={arq.id} style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: 8, padding: "8px 10px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 8 }}>
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div style={{ fontSize: 11, fontWeight: 600, color: "#1e293b", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {arq.client_name ? `${arq.client_name} (${arq.email})` : arq.email}
                  </div>
                  <div style={{ fontSize: 10, color: "#94a3b8", marginTop: 2 }}>Sent {fmtDate(arq.created_at)}</div>
                </div>
                <span style={{ fontSize: 10, fontWeight: 600, padding: "2px 7px", borderRadius: 10, border: `1px solid ${sc.border}`, background: sc.bg, color: sc.color, flexShrink: 0 }}>
                  {status === "submitted" ? "✓ Done" : status === "expired" ? "Expired" : "⏳ Pending"}
                </span>
              </div>
              {arq.status === "pending" && !isExpired && (
                <button onClick={() => handleRemind(arq.id)} disabled={reminding === arq.id}
                  style={{ marginTop: 6, fontSize: 10, fontWeight: 600, color: "#4f7cff", background: "none", border: "1px solid #4f7cff", borderRadius: 5, padding: "2px 8px", cursor: reminding === arq.id ? "wait" : "pointer", opacity: reminding === arq.id ? 0.6 : 1 }}>
                  {reminding === arq.id ? "Sending…" : "🔔 Remind"}
                  {arq.reminder_count > 0 && ` (${arq.reminder_count})`}
                </button>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Main AcordModal ────────────────────────────────────────────────────────
export default function AcordModal({
  onClose, user, token, onUserUpdate, onShowUpgrade,
  resumeSessionId, savedSignature, onOpenSignatureModal,
  onOpenBillingPortal, billingPortalLoading,
}) {
  const dropRef = useRef(null);

  const [files, setFiles]                         = useState([]);
  const [dragging, setDragging]                   = useState(false);
  const [loading, setLoading]                     = useState(false);
  const [processingStage, setProcessingStage]     = useState("");
  const [step, setStep]                           = useState(resumeSessionId ? "resuming" : "upload");
  const [error, setError]                         = useState(null);
  const [sessionId, setSessionId]                 = useState(resumeSessionId || null);
  const [docSummary, setDocSummary]               = useState([]);
  const [flags, setFlags]                         = useState({});
  const [hardStops, setHardStops]                 = useState([]);
  const [softStops, setSoftStops]                 = useState([]);
  const [tier2Score, setTier2Score]               = useState(null);
  const [tier2Missing, setTier2Missing]           = useState([]);
  const [recommendations, setRecommendations]     = useState([]);
  const [allAvailableForms, setAllAvailableForms] = useState([]);
  const [checkedFormIds, setCheckedFormIds]       = useState(new Set());
  const [showAddForms, setShowAddForms]           = useState(false);
  const [generatedForms, setGeneratedForms]       = useState({});
  const [activeFormId, setActiveFormId]           = useState(null);
  const [crossIssues, setCrossIssues]             = useState([]);
  const [pdfLoading, setPdfLoading]               = useState({});
  const [pkgStatusMsg, setPkgStatusMsg]           = useState("");
  const [pkgStatusType, setPkgStatusType]         = useState("");
  const [signedForms, setSignedForms]             = useState(new Set());
  const [showUploadOverlay, setShowUploadOverlay]     = useState(false);
  const [showGenerateOverlay, setShowGenerateOverlay] = useState(false);
  const [showDownloadOverlay, setShowDownloadOverlay] = useState(false);
  const [showAcordModal, setShowAcordModal]           = useState(false);
  const [acordModalAction, setAcordModalAction]       = useState(null);
  const [acordLicenseChecked, setAcordLicenseChecked] = useState(false);
  const [acordModalLoading, setAcordModalLoading]     = useState(false);
  const [epicLoading, setEpicLoading]                 = useState(false);
  const [epicSuccess, setEpicSuccess]                 = useState(false);

  // ARQ state
  const [showARQModal,       setShowARQModal]       = useState(false);
  const [arqQuestions,       setArqQuestions]       = useState([]);
  const [arqLoadingQ,        setArqLoadingQ]        = useState(false);
  const [arqSessions,        setArqSessions]        = useState([]);
  const [arqNotifCount,      setArqNotifCount]      = useState(0);
  const [clientFilledFields, setClientFilledFields] = useState([]);

  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = prev; };
  }, []);

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
        } else { setStep("upload"); setSessionId(null); }
      })
      .catch(() => { setStep("upload"); setSessionId(null); })
      .finally(() => { setLoading(false); setProcessingStage(""); });
  }, [resumeSessionId]); // eslint-disable-line

  useEffect(() => {
    const el = dropRef.current; if (!el) return;
    const over  = e => { e.preventDefault(); setDragging(true); };
    const leave = () => setDragging(false);
    const drop  = e => {
      e.preventDefault(); setDragging(false);
      const uploaded = Array.from(e.dataTransfer.files).filter(f => f.type === "application/pdf" || f.name.toLowerCase().endsWith(".zip") || f.type.startsWith("image/"));
      setFiles(prev => [...prev, ...uploaded]);
    };
    el.addEventListener("dragover", over); el.addEventListener("dragleave", leave); el.addEventListener("drop", drop);
    return () => { el.removeEventListener("dragover", over); el.removeEventListener("dragleave", leave); el.removeEventListener("drop", drop); };
  }, []);

  // Load ARQ data when entering editor
  useEffect(() => {
    if (step !== "editor" || !sessionId || !token) return;
    refreshArqData();
  }, [step, sessionId]); // eslint-disable-line

  const refreshArqData = async () => {
  if (!sessionId || !token) return [];
  
  // ARQ sessions + notifications fire-and-forget
  fetch(`${API_BASE}/api/arq/list/${sessionId}`, { headers: { Authorization: `Bearer ${token}` } })
    .then(r => r.ok ? r.json() : null)
    .then(d => { if (d?.success) setArqSessions(d.arq_sessions || []); })
    .catch(() => {});
  fetch(`${API_BASE}/api/arq/notifications`, { headers: { Authorization: `Bearer ${token}` } })
    .then(r => r.ok ? r.json() : null)
    .then(d => { if (d?.notifications) setArqNotifCount(d.notifications.filter(n => !n.read_status).length); })
    .catch(() => {});

  // Client-filled fields — awaited so caller gets the value immediately
  try {
    const r      = await fetch(`${API_BASE}/api/arq/client-filled/${sessionId}`, { headers: { Authorization: `Bearer ${token}` } });
    const d      = r.ok ? await r.json() : null;
    const fields = d?.client_filled_fields || [];
    setClientFilledFields(fields);
    return fields;
  } catch { return []; }
};

  const handleOpenARQ = async () => {
    if (!sessionId) return;
    setArqLoadingQ(true);
    try {
      const res  = await fetch(`${API_BASE}/api/arq/generate/${sessionId}`, { headers: { Authorization: `Bearer ${token}` } });
      const data = await res.json();
      if (res.ok && data.success) { setArqQuestions(data.questions || []); setShowARQModal(true); }
      else { setError(data.detail || "Failed to generate questions."); }
    } catch (e) { setError("Network error: " + e.message); }
    finally { setArqLoadingQ(false); }
  };

  const reset = () => {
    setFiles([]); setSessionId(null); setStep("upload"); setError(null);
    setDocSummary([]); setFlags({}); setHardStops([]); setSoftStops([]);
    setTier2Score(null); setTier2Missing([]); setRecommendations([]);
    setAllAvailableForms([]); setCheckedFormIds(new Set());
    setGeneratedForms({}); setActiveFormId(null); setCrossIssues([]);
    setPdfLoading({}); setEpicLoading(false); setEpicSuccess(false);
    setSignedForms(new Set()); setShowUploadOverlay(false); setShowGenerateOverlay(false); setShowDownloadOverlay(false);
    setArqQuestions([]); setArqSessions([]); setClientFilledFields([]); setArqNotifCount(0);
  };

  const handleSendToEpic = async (formId) => {
    if (!formId || !sessionId) return;
    setEpicLoading(true); setEpicSuccess(false);
    try {
      const res  = await fetch(`${API_BASE}/api/send-to-epic/${sessionId}/${formId}`, { headers: { Authorization: `Bearer ${token}` } });
      const data = await res.json();
      if (res.ok && data.success) { setEpicSuccess(true); setTimeout(() => setEpicSuccess(false), 3500); }
      else { setError(data.detail || "Failed to send to EPIC."); }
    } catch (e) { setError("EPIC send failed: " + e.message); }
    finally { setEpicLoading(false); }
  };

  const gatedDownload = (action) => {
    if (user?.acord_license_confirmed) { action(); return; }
    setAcordLicenseChecked(false); setAcordModalAction(() => action); setShowAcordModal(true);
  };

  const handleAcordConfirm = async () => {
    if (!acordLicenseChecked) return;
    setAcordModalLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/acord/confirm-license`, { method: "POST", headers: { Authorization: `Bearer ${token}` } });
      if (res.ok) { onUserUpdate({ ...user, acord_license_confirmed: true }); setShowAcordModal(false); if (acordModalAction) acordModalAction(); }
      else { setError("License confirmation failed. Please try again."); }
    } catch { setError("Network error during license confirmation."); }
    finally { setAcordModalLoading(false); }
  };

  const _doDownloadOne = async (formId) => {
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
    const fd = new FormData();
    files.forEach(f => fd.append("files", f));
    try {
      const res  = await fetch(`${API_BASE}/api/upload-declaration`, { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: fd });
      const data = await res.json();
      if (res.status === 401) { setError("Session expired. Please sign in again."); setTimeout(() => { localStorage.removeItem("acordly_token"); window.location.reload(); }, 2000); return; }
      if (res.status === 403) { const msg = data.detail || data.message || "Access blocked."; if (msg.includes("suspended")) setError("🚫 Your account is suspended."); else if (msg.includes("archived")) setError("🗄️ Account archived. Contact support."); else if (msg.includes("soft_locked") || msg.includes("locked")) setError("🔒 Account Disabled — please update billing."); else setError(msg); return; }
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
      const res  = await fetch(`${API_BASE}/api/select-forms-bulk`, { method: "POST", headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` }, body: JSON.stringify({ session_id: sessionId, form_ids: ids }) });
      const data = await res.json();
      if (res.status === 403) { setError("🔒 " + (data.detail || "Access blocked.") + " Please update your billing."); return; }
      if (!data.success) { setError("Form generation failed"); return; }
      setGeneratedForms(data.generated || {}); setCrossIssues(data.cross_issues || []);
      const firstId = data.form_ids?.[0] || null; setActiveFormId(firstId); setStep("editor");
      const readyMap = {}; (data.form_ids || []).forEach(fid => { readyMap[fid] = false; }); setPdfLoading(readyMap);
    } catch (e) { setError("Generation failed: " + e.message); }
    finally { setLoading(false); setShowGenerateOverlay(false); }
  };

  const formIdList = Object.keys(generatedForms);
  const activeIdx  = formIdList.indexOf(activeFormId);
  const goNext     = () => { if (activeIdx < formIdList.length - 1) setActiveFormId(formIdList[activeIdx + 1]); };
  const goPrev     = () => { if (activeIdx > 0) setActiveFormId(formIdList[activeIdx - 1]); };
  const toggleForm = (formId) => { setCheckedFormIds(prev => { const next = new Set(prev); if (next.has(formId)) next.delete(formId); else next.add(formId); return next; }); };

  const recommendedIds = new Set(recommendations.map(r => r.form_id));
  const extraForms     = allAvailableForms.filter(f => !recommendedIds.has(f.form_id));
  const activeSqs      = activeFormId && generatedForms[activeFormId]?.sqs;
  const pkgsUsed       = user?.packages_used  || 0;
  const pkgsLimit      = user?.packages_limit || 0;
  const softBuffer     = user?.packages_soft_buffer || 0;
  const inOverage      = user?.subscription_tier !== "free" && pkgsLimit > 0 && pkgsUsed >= pkgsLimit + softBuffer;

  const BillingBtnSpinner = () => (
    <span style={{ width: 11, height: 11, border: "2px solid currentColor", borderTopColor: "transparent", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite", marginRight: 4 }} />
  );

  const handleDownloadOne = (formId) => gatedDownload(() => _doDownloadOne(formId));
  const handleDownloadAll = () => gatedDownload(() => _doDownloadAll());

  return (
    <div className="modal-overlay">
      <div className="modal-content" onClick={e => e.stopPropagation()}>
        <button className="modal-close" onClick={onClose}>✕</button>
        <div className="modal-inner">

          {showUploadOverlay   && <ProcessStageOverlay stages={["Reading your documents…", "Extracting facts with AI…"]} advanceAfter={3500} />}
          {showGenerateOverlay && <ProcessStageOverlay stages={[`Selecting ${checkedFormIds.size} form${checkedFormIds.size !== 1 ? "s" : ""}…`, "Generating with AI…"]} advanceAfter={3000} />}
          {showDownloadOverlay && <ProcessStageOverlay stages={["Preparing your form…", "Packaging for download…"]} advanceAfter={2000} />}

          {loading && !showUploadOverlay && !showGenerateOverlay && !showDownloadOverlay && (
            <div className="loading-overlay"><div className="loading-spinner" /><p className="loading-text">{processingStage || "Processing..."}</p></div>
          )}

          {user && user.subscription_tier === "free" && step !== "upload" && (
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
            if (ps === "archived")    return <div className="payment-status-banner payment-status-archived">🗄️ Account archived — <a href="mailto:support@acordly.ai">Contact support</a> to restore.</div>;
            if (ps === "suspended")   return <div className="payment-status-banner payment-status-suspended">🚫 Account suspended.{" "}<button onClick={onOpenBillingPortal} disabled={billingPortalLoading} style={{ color: "inherit", fontWeight: 700, textDecoration: "underline", background: "none", border: "none", cursor: billingPortalLoading ? "wait" : "pointer", padding: 0, display: "inline-flex", alignItems: "center", gap: 4 }}>{billingPortalLoading && <BillingBtnSpinner />}Restore billing</button></div>;
            if (ps === "soft_locked") return <div className="payment-status-banner payment-status-locked">🔒 Account Disabled —{" "}<button onClick={onOpenBillingPortal} disabled={billingPortalLoading} style={{ color: "inherit", fontWeight: 700, textDecoration: "underline", background: "none", border: "none", cursor: billingPortalLoading ? "wait" : "pointer", padding: 0, display: "inline-flex", alignItems: "center", gap: 4 }}>{billingPortalLoading && <BillingBtnSpinner />}update billing</button>{" "}to restore.</div>;
            if (ps === "failed")      return <div className="payment-status-banner payment-status-failed">⚠️ Payment overdue —{" "}<button onClick={onOpenBillingPortal} disabled={billingPortalLoading} style={{ color: "inherit", fontWeight: 700, textDecoration: "underline", background: "none", border: "none", cursor: billingPortalLoading ? "wait" : "pointer", padding: 0, display: "inline-flex", alignItems: "center", gap: 4 }}>{billingPortalLoading && <BillingBtnSpinner />}update billing</button></div>;
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

          {/* UPLOAD */}
          {step === "upload" && (() => {
            const ps = user?.payment_status;
            const uploadBlocked = ps === "soft_locked" || ps === "suspended" || ps === "archived";
            const blockMsg = ps === "archived" ? "🗄️ Account archived — contact support to restore." : ps === "suspended" ? "🚫 Account suspended — restore billing to continue." : ps === "soft_locked" ? "🔒 Account Disabled — please update your billing." : null;
            return (
              <div className="modal-step">
                <div className="step-header">
                  <h2 className="step-title">Upload Documents</h2>
                  <p className="step-subtitle">Dec pages, loss runs, schedules, quotes — upload PDFs, images (JPG/PNG), or ZIP archives</p>
                </div>
                {uploadBlocked && <div className="upload-blocked-msg">{blockMsg}</div>}
                <div ref={dropRef} className={`upload-area ${dragging ? "dragging" : ""} ${uploadBlocked ? "upload-area-blocked" : ""}`}>
                  <div className="upload-icon">📁</div>
                  <input type="file" id="file-upload" accept=".pdf,.zip,.jpg,.jpeg,.png,.bmp,.tiff,.webp,application/pdf,application/zip,image/*" multiple disabled={uploadBlocked} onChange={e => setFiles(prev => [...prev, ...Array.from(e.target.files)])} className="file-input" />
                  <label htmlFor="file-upload" className="upload-label">Drag &amp; drop or <span className="upload-link">browse files</span></label>
                  <p className="upload-hint">PDFs, Images (JPG, PNG, BMP, TIFF) and ZIP archives supported</p>
                </div>
                {files.length > 0 && (
                  <div className="file-list">
                    {files.map((f, i) => (
                      <div key={i} className="file-chip">
                        <span className="file-icon">{f.name.endsWith(".zip") ? "📦" : f.type?.startsWith("image/") ? "🖼️" : "📄"}</span>
                        <span className="file-name">{f.name}</span>
                        <button className="file-remove" onClick={() => setFiles(prev => prev.filter((_, j) => j !== i))}>✕</button>
                      </div>
                    ))}
                  </div>
                )}
                <button className="btn btn-modal-primary btn-block" onClick={handleUpload} disabled={!files.length || loading || uploadBlocked}>
                  <span className="btn-icon">🚀</span>
                  {loading ? "Analyzing..." : `Analyze ${files.length > 1 ? files.length + " Files" : "File"}`}
                </button>
              </div>
            );
          })()}

          {/* STOPPED */}
          {step === "stopped" && (
            <div className="modal-step">
              <div className="stop-banner stop-hard">
                <div className="stop-icon">🚫</div>
                <h2 className="stop-title">Submission Blocked — Minimum Fields Missing</h2>
                <p className="stop-subtitle">ACORD 125 cannot be generated. Missing:</p>
              </div>
              <div className="stop-fields">{hardStops.map((f, i) => <div key={i} className="stop-field-item"><span className="stop-field-icon">✗</span><span>{f}</span></div>)}</div>
              <p className="stop-advice">Upload documents that include these fields, then try again.</p>
              <button className="btn btn-modal-primary" onClick={reset}>← Upload New Documents</button>
            </div>
          )}

          {/* RECOMMENDATIONS */}
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
              <button className="btn btn-modal-secondary" onClick={reset} style={{ marginBottom: "12px" }}>← Start Over</button>
            </div>
          )}

          {/* EDITOR */}
          {step === "editor" && (
            <div className="editor-layout">
              <div className="editor-sidebar">
                <div className="form-navigator">
                  <div className="form-nav-header"><span className="form-nav-title">Generated Forms</span><span className="form-nav-count">{formIdList.length} form{formIdList.length !== 1 ? "s" : ""}</span></div>
                  <div className="form-nav-list">
                    {formIdList.map(fid => {
                      const fd = generatedForms[fid]; const sq = fd?.sqs;
                      return (
                        <div key={fid} className={`form-nav-item ${activeFormId === fid ? "form-nav-active" : ""}`} onClick={() => setActiveFormId(fid)}>
                          <div className="form-nav-name">{fd?.form_name || fid}{signedForms.has(fid) && <span style={{ color: "#10b981", fontSize: 11 }}> ✍</span>}{pdfLoading[fid] ? <span className="form-nav-loading"> ⏳</span> : <span className="form-nav-ready"> ✓</span>}</div>
                          {sq && <div className="form-nav-meta"><span className="form-nav-score" style={{ color: gradeColor(sq.grade) }}>{sq.sqs_score} {sq.grade}</span><span className={`form-nav-tier tier-${sq.tier_color}`}>{sq.tier}</span></div>}
                        </div>
                      );
                    })}
                  </div>
                  <div className="form-nav-arrows">
                    <button className="btn btn-modal-secondary btn-small" onClick={goPrev} disabled={activeIdx <= 0}>← Prev</button>
                    <span className="form-nav-pos">{activeIdx + 1} / {formIdList.length}</span>
                    <button className="btn btn-modal-secondary btn-small" onClick={goNext} disabled={activeIdx >= formIdList.length - 1}>Next →</button>
                  </div>
                </div>

                {activeSqs && (
                  <div className="sqs-display">
                    <div className="sqs-header"><span className="sqs-label">SQS — {generatedForms[activeFormId]?.form_name}</span><div className="sqs-grade" style={{ background: gradeColor(activeSqs.grade) }}>{activeSqs.grade}</div></div>
                    <div className="sqs-score-row"><span className="sqs-score-large" style={{ color: gradeColor(activeSqs.grade) }}>{activeSqs.sqs_score}</span><span className={`sqs-tier-badge tier-${activeSqs.tier_color}`}>{activeSqs.tier}</span></div>
                    {activeSqs.routing_decision && (
                      <div style={{ margin: "8px 0 12px 0", padding: "8px 12px", borderRadius: "6px", fontSize: "12px", fontWeight: "600", textAlign: "center", background: { auto_quote: "#dcfce7", review: "#fef9c3", full_review: "#ffedd5", hold: "#fee2e2" }[activeSqs.routing_decision] || "#f1f5f9", color: { auto_quote: "#166534", review: "#854d0e", full_review: "#9a3412", hold: "#991b1b" }[activeSqs.routing_decision] || "#374151", border: `1px solid ${{ auto_quote: "#86efac", review: "#fde047", full_review: "#fdba74", hold: "#fca5a5" }[activeSqs.routing_decision] || "#e2e8f0"}` }}>
                        {{ auto_quote: "✅ Auto-Route to Quoting", review: "🔍 Light Review", full_review: "📋 Full Underwriter Review", hold: "🚫 Hold — Remediation Required" }[activeSqs.routing_decision] || activeSqs.routing_decision}
                      </div>
                    )}
                    <div className="sqs-breakdown">
                      {Object.entries(activeSqs.breakdown || {}).map(([key, val]) => (
                        <div key={key} className="sqs-metric">
                          <div className="metric-header"><span className="metric-name">{SQS_LABELS[key] || key}<span className="metric-weight"> ({SQS_WEIGHTS[key] || 0}%)</span></span><span className="metric-value">{val}%</span></div>
                          <div className="metric-bar"><div className="metric-fill" style={{ width: `${val}%`, background: barColor(val) }} /></div>
                        </div>
                      ))}
                    </div>
                    {activeSqs.risk_drivers?.length > 0 && <div className="sqs-drivers"><div className="drivers-title">⚡ Top Risk Drivers</div>{activeSqs.risk_drivers.map((d, i) => <div key={i} className="driver-item"><span className="driver-rank">#{i + 1}</span><span className="driver-name">{d.component}</span><span className="driver-score" style={{ color: barColor(d.score) }}>{d.score}%</span></div>)}</div>}
                    {activeSqs.issues?.length > 0 && <div className="sqs-alerts"><div className="alerts-title">⚠️ Issues</div><ul className="alerts-list">{activeSqs.issues.map((s, i) => <li key={i}>{s}</li>)}</ul></div>}
                    {activeSqs.recommendations?.length > 0 && <div className="sqs-tips"><div className="tips-title">💡 Remediation Steps</div><ul className="tips-list">{activeSqs.recommendations.map((s, i) => <li key={i}>{s}</li>)}</ul></div>}
                  </div>
                )}

                {crossIssues.length > 0 && (
                  <div className="cross-issues">
                    <div className="cross-title">🔗 Cross-Form Validation</div>
                    {crossIssues.map((iss, i) => <div key={i} className={`cross-item cross-${iss.type}`}>{iss.type === "hard_stop" ? "🚫" : "⚠️"} {iss.message}</div>)}
                  </div>
                )}

                {/* ── Send to Client (ARQ) ── */}
                <div style={{ padding: "12px 0 4px" }}>
                  <button
                    onClick={handleOpenARQ}
                    disabled={arqLoadingQ}
                    style={{ width: "100%", padding: "9px 14px", borderRadius: 8, border: "1px solid #4f7cff", background: "rgba(79,124,255,0.08)", color: "#4f7cff", fontSize: 13, fontWeight: 600, cursor: arqLoadingQ ? "wait" : "pointer", fontFamily: "inherit", display: "flex", alignItems: "center", justifyContent: "center", gap: 6, opacity: arqLoadingQ ? 0.7 : 1, marginBottom: 4 }}
                  >
                    {arqLoadingQ
                      ? <><span style={{ width: 12, height: 12, border: "2px solid #4f7cff", borderTopColor: "transparent", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" }} /> Loading questions…</>
                      : <>📧 Send to Client {arqNotifCount > 0 && <span style={{ background: "#e6007a", color: "#fff", borderRadius: 10, fontSize: 10, padding: "1px 6px", fontWeight: 700 }}>{arqNotifCount}</span>}</>
                    }
                  </button>
                  <ARQStatusPanel arqSessions={arqSessions} token={token} onRefresh={refreshArqData} />
                </div>

                <div className="download-actions">
                  <button onClick={() => handleSendToEpic(activeFormId)} disabled={!activeFormId || epicLoading}
                    style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 6, width: "100%", padding: "8px 14px", borderRadius: 9, marginBottom: 6, border: epicSuccess ? "1px solid #22c55e" : "1px solid #2a3047", background: epicSuccess ? "rgba(34,197,94,0.08)" : "#0f172a", color: epicSuccess ? "#22c55e" : "#94a3b8", fontSize: 13, fontWeight: 600, cursor: epicLoading ? "wait" : "pointer", fontFamily: "inherit", transition: "all 0.18s", opacity: (!activeFormId || epicLoading) ? 0.55 : 1 }}>
                    {epicSuccess ? "✅ Sent to EPIC" : epicLoading ? <><span style={{ width: 12, height: 12, border: "2px solid currentColor", borderTopColor: "transparent", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" }} /> Sending...</> : "🔗 Send to EPIC"}
                  </button>
                  <button className="btn btn-modal-primary btn-block" onClick={() => handleDownloadOne(activeFormId)} disabled={!activeFormId}>⬇ Download This Form</button>
                  {formIdList.length > 1 && <button className="btn btn-modal-secondary btn-block" onClick={handleDownloadAll}>📦 Download All Forms ({formIdList.length} forms)</button>}
                  <button className="btn btn-modal-secondary btn-block" onClick={reset} style={{ marginBottom: 2 }}>Start Over</button>
                </div>
              </div>

              <div className="editor-main">
                <PDFJsViewer
                  key={activeFormId}
                  pdfUrl={`${API_BASE}/api/get-pdf/${sessionId}/${activeFormId}?token=${token}`}
                  formName={activeFormId ? (generatedForms[activeFormId]?.form_name || activeFormId) : ""}
                  onFormNav={{ goPrev, goNext, activeIdx, total: formIdList.length }}
                  sessionId={sessionId}
                  formId={activeFormId}
                  token={token}
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
            <div className="modal-step" style={{ textAlign: "center", padding: "48px 24px" }}>
              <div className="success-animation"><div className="success-icon">✓</div></div>
              <h2 className="success-title">Your Download is Complete!</h2>
              <p className="success-message">Your filled ACORD forms have been downloaded successfully.</p>
              {user && user.subscription_tier === "free" && (
                <div className="success-remaining">
                  <p>You have <strong>{Math.max(0, user.downloads_remaining)}</strong> free download{user.downloads_remaining !== 1 ? "s" : ""} remaining</p>
                </div>
              )}
              <div className="success-actions" style={{ display: "flex", flexDirection: "column", gap: 10, alignItems: "center", marginTop: 24 }}>
                <button className="btn btn-modal-primary" style={{ minWidth: 240 }} onClick={() => setStep("editor")}>
                  ← Back to Form — Download Again or Make Changes
                </button>
                <button className="btn btn-modal-secondary" style={{ minWidth: 240 }} onClick={reset}>
                  Upload Another Document
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ACORD License Gate */}
      {showAcordModal && (
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
                <button className="btn-stub" disabled title="Email — coming soon">✉ Email</button>
                <button className="btn-stub" disabled title="Share — coming soon">🔗 Share</button>
                <button className="btn-stub" disabled title="Fax — coming soon">📠 Fax</button>
              </div>
              <button className="btn btn-modal-secondary btn-block" onClick={() => { setShowAcordModal(false); setAcordLicenseChecked(false); }}>Cancel</button>
            </div>
          </div>
        </div>
      )}

      {/* ARQ Modal */}
      {showARQModal && (
        <ARQModal
          sessionId={sessionId}
          token={token}
          questions={arqQuestions}
          onClose={() => setShowARQModal(false)}
          onSuccess={() => { setShowARQModal(false); refreshArqData(); }}
        />
      )}
    </div>
  );
}