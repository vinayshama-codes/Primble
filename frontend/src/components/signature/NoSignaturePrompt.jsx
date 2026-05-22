export default function NoSignaturePrompt({ onSetup, onClose }) {
  return (
    <div className="modal-overlay">
      <div className="modal-content" style={{ maxWidth: 380 }} onClick={(e) => e.stopPropagation()}>
        <button className="modal-close" onClick={onClose}>✕</button>
        <div className="modal-inner" style={{ textAlign: "center" }}>
          <div style={{ fontSize: 36, marginBottom: 8 }}></div>
          <h2 className="step-title" style={{ marginBottom: 8 }}>No Signature Saved</h2>
          <p style={{ fontSize: 13, color: "#64748b", marginBottom: 20 }}>
            Set up your signature once and it will be available to apply to all your ACORD forms.
          </p>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <button className="btn btn-modal-primary btn-block" onClick={onSetup}>Set Up Signature</button>
            <button className="btn btn-modal-secondary btn-block" onClick={onClose}>Maybe Later</button>
          </div>
        </div>
      </div>
    </div>
  );
}