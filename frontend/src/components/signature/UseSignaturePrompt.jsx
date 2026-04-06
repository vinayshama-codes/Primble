export default function UseSignaturePrompt({ signature, onApply, onManage, onClose }) {
  return (
    <div className="modal-overlay">
      <div className="modal-content" style={{ maxWidth: 400 }} onClick={(e) => e.stopPropagation()}>
        <button className="modal-close" onClick={onClose}>✕</button>
        <div className="modal-inner" style={{ textAlign: "center" }}>
          <div style={{ fontSize: 36, marginBottom: 8 }}>✍️</div>
          <h2 className="step-title" style={{ marginBottom: 8 }}>Apply Your Signature?</h2>
          <p style={{ fontSize: 13, color: "#64748b", marginBottom: 20 }}>
            Your saved signature will be applied to all signature fields in this form.
          </p>
          {signature && (
            <div style={{ background: "#f8fafc", borderRadius: 8, padding: 12, border: "1px solid #e2e8f0", marginBottom: 20 }}>
              <img src={signature} alt="Your signature" style={{ maxHeight: 60, maxWidth: "100%", objectFit: "contain" }} />
            </div>
          )}
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <button className="btn btn-modal-primary btn-block" onClick={onApply}>✅ Yes, Apply Signature</button>
            <button className="btn btn-modal-secondary btn-block" onClick={onClose}>No, Skip</button>
            <button onClick={onManage} style={{ fontSize: 12, color: "#94a3b8", background: "none", border: "none", cursor: "pointer", textDecoration: "underline", marginTop: 4 }}>
              Manage / Update Signature
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}