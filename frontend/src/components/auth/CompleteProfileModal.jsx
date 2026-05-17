import { useState } from "react";
import { API_BASE } from "../../config/constants";

export default function CompleteProfileModal({ token, user, onComplete }) {
  const [orgName, setOrgName]                     = useState("");
  const [disclaimerChecked, setDisclaimerChecked] = useState(false);
  const [error, setError]                         = useState("");
  const [loading, setLoading]                     = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    if (!orgName.trim())    { setError("Organization or agency name is required."); setLoading(false); return; }
    if (!disclaimerChecked) { setError("You must accept the ACORD disclaimer to continue."); setLoading(false); return; }
    try {
      const res  = await fetch(`${API_BASE}/api/auth/complete-profile`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ organization_name: orgName.trim(), acord_disclaimer_accepted: true }),
      });
      const data = await res.json();
      if (res.ok && data.success) {
        onComplete({ ...user, organization_name: orgName.trim(), acord_disclaimer_accepted: true });
      } else {
        setError(data.detail || data.message || "Failed to save profile. Please try again.");
      }
    } catch { setError("Network error. Please try again."); }
    finally   { setLoading(false); }
  };

  return (
    <div className="modal-overlay">
      <div className="modal-content auth-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-inner">
          <div className="auth-header">
            <h2 className="step-title">Complete Your Profile</h2>
            <p className="step-subtitle">One more step before you get started.</p>
          </div>
          {error && (<div className="alert alert-error"><span>{error}</span><button className="alert-close" onClick={() => setError("")}>✕</button></div>)}
          <form onSubmit={handleSubmit} className="auth-form">
            <div className="form-group">
              <label>Organization / Agency Name <span className="field-required">*</span></label>
              <input type="text" value={orgName} onChange={(e) => setOrgName(e.target.value)} placeholder="Smith Insurance Agency LLC" required className="form-input" autoFocus />
              <span style={{ fontSize: "12px", color: "#64748b", marginTop: "4px", display: "block" }}>The legal name of the agency or organization that holds your ACORD license.</span>
            </div>
            <div className="acord-disclaimer-box">
              <label className="acord-disclaimer-label">
                <input type="checkbox" checked={disclaimerChecked} onChange={(e) => setDisclaimerChecked(e.target.checked)} className="acord-disclaimer-checkbox" />
                <span>By continuing, you acknowledge that <strong>ACORD® Forms require a separate license from ACORD Corporation</strong> and agree to obtain any required license before exporting or distributing those forms.</span>
              </label>
            </div>
            <button type="submit" className="btn btn-modal-primary btn-block" disabled={loading || !disclaimerChecked || !orgName.trim()}>
              {loading ? "Saving..." : "Save and Continue →"}
            </button>
          </form>
          <p style={{ fontSize: "11px", color: "#94a3b8", textAlign: "center", marginTop: "12px" }}>Signed in as {user?.email}</p>
        </div>
      </div>
    </div>
  );
}