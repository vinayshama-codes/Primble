import { useState, useEffect, useRef } from "react";
import { API_BASE } from "../../config/constants";

export default function SignatureModal({ token, onClose, onSaved, existingSignature }) {
  const canvasRef                             = useRef(null);
  const [mode, setMode]                       = useState("draw");
  const [drawing, setDrawing]                 = useState(false);
  const [hasDrawn, setHasDrawn]               = useState(false);
  const [uploadPreview, setUploadPreview]     = useState(null);
  const [saving, setSaving]                   = useState(false);
  const [error, setError]                     = useState("");
  const [clearingSignature, setClearingSignature] = useState(false);

  useEffect(() => {
    if (mode !== "draw") return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#fff";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.strokeStyle = "#0f172a";
    ctx.lineWidth   = 2.5;
    ctx.lineCap     = "round";
    ctx.lineJoin    = "round";
  }, [mode]);

  const getPos = (e, canvas) => {
    const r   = canvas.getBoundingClientRect();
    const src = e.touches ? e.touches[0] : e;
    return { x: src.clientX - r.left, y: src.clientY - r.top };
  };

  const startDraw = (e) => {
    e.preventDefault();
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const pos = getPos(e, canvas);
    ctx.beginPath();
    ctx.moveTo(pos.x, pos.y);
    setDrawing(true);
  };

  const draw = (e) => {
    e.preventDefault();
    if (!drawing) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const pos = getPos(e, canvas);
    ctx.lineTo(pos.x, pos.y);
    ctx.stroke();
    setHasDrawn(true);
  };

  const stopDraw = () => setDrawing(false);

  const clearCanvas = () => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#fff";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    setHasDrawn(false);
  };

  const handleUpload = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => setUploadPreview(ev.target.result);
    reader.readAsDataURL(file);
  };

  const handleSave = async () => {
    setSaving(true);
    setError("");
    let base64 = null;
    if (mode === "draw") {
      if (!hasDrawn) { setError("Please draw your signature first."); setSaving(false); return; }
      base64 = canvasRef.current.toDataURL("image/png");
    } else {
      if (!uploadPreview) { setError("Please upload a signature image."); setSaving(false); return; }
      base64 = uploadPreview;
    }
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
        setError("Session expired — please sign out and sign back in, then try again.");
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
        setError("Session expired — please sign out and sign back in.");
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
          <h2 className="step-title" style={{ marginBottom: 6 }}>✍️ Your Signature</h2>
          <p className="step-subtitle" style={{ marginBottom: 20 }}>
            Saved once, auto-applied to ACORD forms when you choose to sign.
          </p>
          <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
            {["draw", "upload"].map((m) => (
              <button
                key={m}
                onClick={() => { setMode(m); setUploadPreview(null); }}
                style={{
                  flex: 1, padding: "8px", borderRadius: 8, border: "1.5px solid",
                  borderColor: mode === m ? "#E61B84" : "#e2e8f0",
                  background: mode === m ? "rgba(230,0,122,0.06)" : "#fff",
                  color: mode === m ? "#E61B84" : "#64748b",
                  fontWeight: mode === m ? 700 : 500, fontSize: 13, cursor: "pointer",
                }}
              >
                {m === "draw" ? "✏️ Draw" : "📁 Upload Image"}
              </button>
            ))}
          </div>
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
          {mode === "draw" && (
            <div>
              <div style={{ fontSize: 12, color: "#64748b", marginBottom: 8 }}>Draw your signature below:</div>
              <canvas
                ref={canvasRef} width={440} height={140}
                onMouseDown={startDraw} onMouseMove={draw} onMouseUp={stopDraw} onMouseLeave={stopDraw}
                onTouchStart={startDraw} onTouchMove={draw} onTouchEnd={stopDraw}
                style={{ width: "100%", height: 140, border: "1.5px solid #e2e8f0", borderRadius: 8, cursor: "crosshair", touchAction: "none", background: "#fff", boxShadow: "inset 0 1px 4px rgba(0,0,0,0.06)" }}
              />
              <button onClick={clearCanvas} style={{ marginTop: 6, fontSize: 12, color: "#94a3b8", background: "none", border: "none", cursor: "pointer", textDecoration: "underline" }}>
                Clear
              </button>
            </div>
          )}
          {mode === "upload" && (
            <div>
              <div style={{ fontSize: 12, color: "#64748b", marginBottom: 8 }}>Upload a PNG or JPG of your signature:</div>
              <input type="file" accept="image/png,image/jpeg,image/jpg" onChange={handleUpload} style={{ fontSize: 13, marginBottom: 12 }} />
              {uploadPreview && (
                <div style={{ background: "#f8fafc", borderRadius: 8, padding: 12, border: "1px solid #e2e8f0", textAlign: "center" }}>
                  <img src={uploadPreview} alt="Preview" style={{ maxHeight: 80, maxWidth: "100%", objectFit: "contain" }} />
                </div>
              )}
            </div>
          )}
          {error && <div className="alert alert-error" style={{ marginTop: 12 }}><span>⚠️ {error}</span></div>}
          <div style={{ display: "flex", gap: 10, marginTop: 20 }}>
            <button className="btn btn-modal-primary" style={{ flex: 1 }} onClick={handleSave} disabled={saving}>
              {saving ? (
                <span style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 8 }}>
                  <span style={{ width: 14, height: 14, border: "2px solid currentColor", borderTopColor: "transparent", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" }} />
                  Saving...
                </span>
              ) : "💾 Save Signature"}
            </button>
            <button className="btn btn-modal-secondary" onClick={onClose}>Cancel</button>
          </div>
        </div>
      </div>
    </div>
  );
}