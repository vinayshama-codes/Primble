import { useState } from "react";
import { API_BASE } from "../../config/constants";
import SignaturePad from "./SignaturePad";

// The producer's saved signature. The pad (draw or upload) is shared with the
// client's signing page (SignaturePad, Orbin item 14).
// The server takes a data URL of up to 5,000,000 characters
// (signature_routes.save_signature): about 3.7 MB of picture.
const PRODUCER_MAX_BYTES = 3_700_000;

export default function SignatureModal({ token, onClose, onSaved, existingSignature }) {
  const [signature, setSignature]             = useState(null);
  const [saving, setSaving]                   = useState(false);
  const [error, setError]                     = useState("");
  const [clearingSignature, setClearingSignature] = useState(false);

  const handleSave = async () => {
    setSaving(true);
    setError("");
    if (!signature) { setError("Please draw your signature or upload a signature image."); setSaving(false); return; }
    const base64 = signature;
    try {
      const res  = await fetch(`${API_BASE}/api/auth/save-signature`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ signature_data: base64 }),
      });
      const data = await res.json();
      if (res.ok && data.success) {
        onSaved(base64);
      } else if (res.status === 401) {
        setError("Session expired - please sign out and sign back in, then try again.");
      } else {
        setError(data.detail || "Failed to save signature.");
      }
    } catch { setError("Network error. Please try again."); }
    finally   { setSaving(false); }
  };

  const handleClear = async () => {
    setClearingSignature(true);
    try {
      const res = await fetch(`${API_BASE}/api/auth/save-signature`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ signature_data: null }),
      });
      if (res.ok) {
        localStorage.removeItem("acordly_signature");
        onSaved(null);
      } else if (res.status === 401) {
        setError("Session expired - please sign out and sign back in.");
      } else {
        setError("Failed to remove signature.");
      }
    } catch { setError("Network error."); }
    finally   { setClearingSignature(false); }
  };

  return (
    <div className="modal-overlay">
      <div className="modal-content" style={{ maxWidth: 520 }} onClick={(e) => e.stopPropagation()}>
        <button className="modal-close" onClick={onClose}>✕</button>
        <div className="modal-inner">
          <h2 className="step-title" style={{ marginBottom: 6 }}>Your Signature</h2>
          <p className="step-subtitle" style={{ marginBottom: 20 }}>
            Saved once, auto-applied to ACORD forms when you choose to sign.
          </p>
          {existingSignature && (
            <div style={{ marginBottom: 12, padding: "10px 12px", background: "#f8fafc", borderRadius: 8, border: "1px solid #e2e8f0" }}>
              <div style={{ fontSize: 11, color: "#94a3b8", marginBottom: 6 }}>Current saved signature:</div>
              <img src={existingSignature} alt="Saved signature" style={{ maxHeight: 50, maxWidth: "100%", objectFit: "contain" }} />
              <button
                onClick={handleClear}
                disabled={clearingSignature}
                style={{ display: "flex", alignItems: "center", gap: 5, marginTop: 6, fontSize: 11, color: "#ef4444", background: "none", border: "none", cursor: clearingSignature ? "wait" : "pointer", textDecoration: "underline", opacity: clearingSignature ? 0.7 : 1 }}
              >
                {clearingSignature && (
                  <span style={{ width: 10, height: 10, border: "2px solid #ef4444", borderTopColor: "transparent", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" }} />
                )}
                {clearingSignature ? "Removing..." : "Remove saved signature"}
              </button>
            </div>
          )}
          <SignaturePad onChange={setSignature} maxBytes={PRODUCER_MAX_BYTES} />
          {error && <div className="alert alert-error" style={{ marginTop: 12 }}><span>{error}</span></div>}
          <div style={{ display: "flex", gap: 10, marginTop: 20 }}>
            <button className="btn btn-modal-primary" style={{ flex: 1 }} onClick={handleSave} disabled={saving}>
              {saving ? (
                <span style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 8 }}>
                  <span style={{ width: 14, height: 14, border: "2px solid currentColor", borderTopColor: "transparent", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" }} />
                  Saving...
                </span>
              ) : "Save Signature"}
            </button>
            <button className="btn btn-modal-secondary" onClick={onClose}>Cancel</button>
          </div>
        </div>
      </div>
    </div>
  );
}