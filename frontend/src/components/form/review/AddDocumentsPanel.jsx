import { useEffect, useRef, useState } from "react";
import {
  ACCEPT_UPLOAD, AFTER_FORMS_ADD_NOTE, addResultLines, documentsResultLines, errorText,
  fillStatusLines, firstNewSection, integrityRefusal, mergedOffers, newOnReviewText, offerText,
} from "../../../utils/addDocuments";

// After forms, the AI then reads the added document into the forms in the
// background (C103, backend `session_documents.run_new_document_fill`). The
// parent polls its status (it keeps going in the editor) and hands it here as
// `fill` with `newOnReview`; this panel keeps document changes locked while it
// runs and says what changed and what is new on the review page.
const FILL_LOCK_TEXT = "Your forms are being updated from a document you added - wait for it to finish.";

// "Add documents" on the package page's Documents section (Choice Electric #25,
// 7 Oct 2026). Before forms, the documents join the package and it is re-read.
// After forms, the server also re-stamps every generated box the new documents
// move (boxes a person typed are kept) and re-scores - see the backend's
// services/session_documents.py. A form a newly evidenced line needs is OFFERED
// here, never added on its own.
//
// Self-contained: it posts the files, polls the upload progress channel, shows
// errors and the result, and hands every successful answer to `onChanged` -
// the parent reloads the package page the way a refresh would.

const PINK = "#E61B84";
const box = { border: "1px solid #e2e8f0", borderRadius: 8, padding: "10px 12px", background: "#fff", marginTop: 10 };
const btn = (primary, disabled) => ({
  fontSize: 12, fontWeight: 600, padding: "5px 12px", borderRadius: 6,
  border: `1px solid ${primary ? PINK : "#cbd5e1"}`,
  background: primary ? (disabled ? "#f9a8d4" : PINK) : "#fff",
  color: primary ? "#fff" : "#334155",
  cursor: disabled ? "not-allowed" : "pointer",
});
const LINE_COLOR = { done: "#166534", info: "#334155", warn: "#92400e" };

const newToken = () => {
  try { return crypto.randomUUID(); } catch { return `t${Date.now()}${Math.random().toString(16).slice(2)}`; }
};

export default function AddDocumentsPanel({
  sessionId, apiBase, afterForms = false, lockedText = null,
  availableDocTypes = [], pendingOffers = [], result = null,
  onChanged, onError, onReview, fill = null, newOnReview = null,
}) {
  const [files, setFiles] = useState([]);
  const [docType, setDocType] = useState("");
  const [asSupporting, setAsSupporting] = useState(false);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState("");
  const [error, setError] = useState("");
  const [integrity, setIntegrity] = useState(null);
  const [offerBusy, setOfferBusy] = useState(null);
  const [offerNote, setOfferNote] = useState("");
  // The result box closes with its own x (owner, 14 Oct 2026); a new answer
  // opens it again. The forms it offers stay listed under Recommendations.
  const [resultClosed, setResultClosed] = useState(false);
  useEffect(() => { setResultClosed(false); }, [result]);
  const inputRef = useRef(null);
  const pollRef = useRef(null);

  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

  const stopPolling = () => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
  };

  const startPolling = (token) => {
    stopPolling();
    pollRef.current = setInterval(async () => {
      try {
        const r = await fetch(`${apiBase}/api/upload-progress/${token}`, { credentials: "include" });
        const d = r.ok ? await r.json() : null;
        if (d && d.found && d.active) setProgress(String(d.active));
      } catch { /* progress is cosmetic */ }
    }, 1500);
  };

  const fillRunning = !!fill && fill.state === "running";
  const lockText = lockedText || (fillRunning ? FILL_LOCK_TEXT : null);

  // `asEvidence` (owner, 14 Oct 2026): the second answer to "these documents
  // name a different insured" - keep the file, read nothing from it.
  const send = async (confirmSameInsured, asEvidence = false) => {
    if (!sessionId || !files.length || busy || lockText) return;
    setBusy(true); setError(""); setOfferNote("");
    if (!confirmSameInsured && !asEvidence) setIntegrity(null);
    setProgress(afterForms ? "Reading your documents - your forms update when they are read..." : "Reading your documents...");
    const token = newToken();
    startPolling(token);
    try {
      const body = new FormData();
      for (const f of files) body.append("files", f);
      body.append("progress_token", token);
      body.append("as_supporting", asSupporting ? "true" : "false");
      if (docType) body.append("doc_type", docType);
      body.append("confirm_same_insured", confirmSameInsured ? "true" : "false");
      body.append("as_evidence", asEvidence ? "true" : "false");
      const res = await fetch(`${apiBase}/api/session/${sessionId}/documents`, {
        method: "POST", credentials: "include", body,
      });
      const data = await res.json().catch(() => ({}));
      const refusal = integrityRefusal(res.status, data);
      if (refusal) { setIntegrity(refusal); return; }
      if (!res.ok || !data.success) {
        const msg = errorText(data, "Could not add the documents. Please try again.");
        setError(msg); if (onError) onError(msg);
        return;
      }
      setIntegrity(null); setFiles([]);
      if (inputRef.current) inputRef.current.value = "";
      if (onChanged) await onChanged(data);
    } catch (e) {
      setError("Could not add the documents: " + (e?.message || "network error"));
    } finally {
      stopPolling(); setBusy(false); setProgress("");
    }
  };

  const addOffered = async (offer) => {
    if (!sessionId || !offer?.form_id || offerBusy || lockText) return;
    setOfferBusy(offer.form_id); setOfferNote(""); setError("");
    try {
      const res = await fetch(`${apiBase}/api/session/${sessionId}/documents/add-form`, {
        method: "POST", credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ form_id: offer.form_id }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.success) {
        setError(errorText(data, "The form could not be added. Please try again."));
        return;
      }
      setOfferNote(`${offer.label || offer.form_id} was added to this package.`);
      if (onChanged) await onChanged({ ...data, __formAdded: offer.form_id });
    } catch (e) {
      setError("The form could not be added: " + (e?.message || "network error"));
    } finally {
      setOfferBusy(null);
    }
  };

  // An add after forms gets the result box ("Added a.pdf. Forms updated: ...",
  // the AI reading, what is new on the review page); every other answer (a
  // pre-form add, a document change) keeps its existing lines.
  const isAddAfterForms = !!(result && result.after_forms && Array.isArray(result.documents_added)
    && result.documents_added.length);
  const lines = isAddAfterForms
    ? [...addResultLines(result, fill), ...fillStatusLines(fill)]
    : documentsResultLines(result);
  const reviewText = isAddAfterForms && !fillRunning ? newOnReviewText(newOnReview) : "";
  const reviewSection = firstNewSection(newOnReview);
  // The offers the SERVER holds for this package (every package-page answer
  // carries them), so an offer whose form was added never lingers.
  const offers = mergedOffers(pendingOffers, []);
  const disabled = busy || !!lockText;

  return (
    <div style={box} data-testid="add-documents">
      {afterForms && (
        <div style={{ fontSize: 12, color: "#0c4a6e", background: "#f0f9ff", border: "1px solid #bae6fd", borderRadius: 6, padding: "6px 10px", marginBottom: 8 }}
          data-testid="add-documents-after-forms-note">
          {AFTER_FORMS_ADD_NOTE}
        </div>
      )}
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
        <span style={{ fontWeight: 700, fontSize: 13, color: "#1e293b" }}>Add documents</span>
        <span style={{ fontSize: 11.5, color: "#64748b" }}>
          {afterForms
            ? "A narrative, loss runs or any supporting document. Your forms are updated from what it shows; boxes you typed are kept."
            : "A narrative, loss runs or any supporting document. It joins this package and is read with the others."}
        </span>
      </div>
      {lockText && <div style={{ marginTop: 6, fontSize: 12, color: "#0c4a6e" }}>{lockText}</div>}
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginTop: 8 }}>
        <input
          ref={inputRef} type="file" multiple accept={ACCEPT_UPLOAD} disabled={disabled}
          aria-label="Choose documents to add"
          onChange={(e) => { setFiles(Array.from(e.target.files || [])); setError(""); setIntegrity(null); }}
          style={{ fontSize: 12, maxWidth: 260 }}
        />
        {availableDocTypes.length > 0 && (
          <select value={docType} disabled={disabled} onChange={(e) => setDocType(e.target.value)}
            aria-label="Document type" title="What these documents are"
            style={{ fontSize: 12, padding: "3px 6px", borderRadius: 6, border: "1px solid #cbd5e1", background: "#fff", color: "#334155" }}>
            <option value="">Type: detect automatically</option>
            {availableDocTypes.filter((t) => t.value !== "unknown").map((t) => (
              <option key={t.value} value={t.value}>{t.label}</option>
            ))}
          </select>
        )}
        <label style={{ display: "inline-flex", alignItems: "center", gap: 5, fontSize: 12, color: "#475569" }}
          title="Its facts count, but it is never treated as the main document">
          <input type="checkbox" checked={asSupporting} disabled={disabled} onChange={(e) => setAsSupporting(e.target.checked)} />
          Supporting only
        </label>
        <button type="button" style={btn(true, disabled || !files.length)} disabled={disabled || !files.length}
          onClick={() => send(false)}>
          {busy ? "Adding..." : files.length > 1 ? `Add ${files.length} documents` : "Add document"}
        </button>
        {/* Cancel what was picked before adding it (owner, 25 Oct 2026). Not
            while a read runs - the server is already merging the files. */}
        {files.length > 0 && !busy && (
          <button type="button" style={btn(false, false)} data-testid="add-documents-cancel"
            onClick={() => {
              setFiles([]); setDocType(""); setAsSupporting(false); setError(""); setIntegrity(null);
              if (inputRef.current) inputRef.current.value = "";
            }}>
            Cancel
          </button>
        )}
      </div>
      {busy && (
        <div style={{ marginTop: 8, display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: PINK, fontWeight: 600 }} role="status">
          <span style={{ width: 10, height: 10, border: "2px solid rgba(230,27,132,0.25)", borderTopColor: PINK, borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" }} />
          {progress || "Working..."}
        </div>
      )}
      {error && <div style={{ marginTop: 8, fontSize: 12, color: "#b91c1c" }} role="alert">{error}</div>}
      {integrity && (
        <div style={{ marginTop: 8, fontSize: 12, color: "#78350f", background: "#fffbeb", border: "1px solid #fde68a", borderRadius: 6, padding: "8px 10px" }} role="alert">
          <div>{integrity.message}</div>
          {integrity.canConfirm && (
            <>
              <div style={{ marginTop: 6 }}>
                Evidence only keeps {files.length === 1 ? "the file" : "the files"} with this package but reads nothing
                into your forms or your score. Use its values only if it is this insured.
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 6 }}>
                <button type="button" style={btn(false, busy)} disabled={busy} onClick={() => send(false, true)}
                  data-testid="add-as-evidence">
                  Add as evidence only
                </button>
                <button type="button" style={btn(true, busy)} disabled={busy} onClick={() => send(true)}
                  data-testid="add-same-insured">
                  It is this insured - use its values
                </button>
                <button type="button" style={btn(false, busy)} disabled={busy} onClick={() => setIntegrity(null)}>Cancel</button>
              </div>
            </>
          )}
        </div>
      )}
      {lines.length > 0 && !resultClosed && (
        <div style={{ position: "relative", marginTop: 8, display: "flex", flexDirection: "column", gap: 3, ...(isAddAfterForms ? { background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: 6, padding: "8px 28px 8px 10px" } : { paddingRight: 24 }) }}
          data-testid="add-documents-result">
          <button type="button" aria-label="Close" title="Close" data-testid="add-documents-result-close"
            onClick={() => { setResultClosed(true); setOfferNote(""); }}
            style={{ position: "absolute", top: 4, right: 6, width: 20, height: 20, display: "inline-flex", alignItems: "center", justifyContent: "center", border: "none", background: "transparent", color: "#64748b", fontSize: 15, lineHeight: 1, cursor: "pointer", borderRadius: 4, fontFamily: "inherit" }}>
            ×
          </button>
          {lines.map((l, i) => (
            <div key={i} style={{ fontSize: 12, color: LINE_COLOR[l.kind] || "#334155", display: "flex", alignItems: "center", gap: 6 }}>
              {isAddAfterForms && fillRunning && i === lines.length - 1 && (
                <span style={{ width: 9, height: 9, border: "2px solid rgba(230,27,132,0.25)", borderTopColor: PINK, borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite", flexShrink: 0 }} />
              )}
              <span>{l.text}</span>
            </div>
          ))}
          {reviewText && (
            <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginTop: 4, fontSize: 12, color: reviewSection ? "#92400e" : "#166534", fontWeight: 600 }}
              data-testid="add-documents-new-on-review">
              <span>{reviewText}</span>
              {reviewSection && typeof onReview === "function" && (
                <button type="button" style={btn(true, false)} onClick={() => onReview(reviewSection)}>
                  {reviewSection === "overview" ? "Open the review page" : "Review them"}
                </button>
              )}
            </div>
          )}
        </div>
      )}
      {offers.length > 0 && !resultClosed && (
        <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 6 }}>
          {offers.map((o) => (
            <div key={o.form_id} style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", fontSize: 12, color: "#334155" }}>
              <span>{offerText(o)}</span>
              <button type="button" style={btn(false, !!offerBusy || !!lockText)} disabled={!!offerBusy || !!lockText}
                onClick={() => addOffered(o)}>
                {offerBusy === o.form_id ? "Adding..." : `Add ${o.label || o.form_id}`}
              </button>
            </div>
          ))}
        </div>
      )}
      {offerNote && !resultClosed && <div style={{ marginTop: 6, fontSize: 12, color: "#166534" }}>{offerNote}</div>}
    </div>
  );
}
