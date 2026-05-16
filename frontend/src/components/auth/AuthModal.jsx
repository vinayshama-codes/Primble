import { useState } from "react";
import { GoogleLogin } from "@react-oauth/google";
import { API_BASE } from "../../config/constants";
import { isPersonalEmail } from "../../utils/formatters";

export default function AuthModal({ onClose, onSuccess, initialMode = "signin" }) {
  const [mode, setMode]                           = useState(initialMode);
  const [email, setEmail]                         = useState("");
  const [password, setPassword]                   = useState("");
  const [fullName, setFullName]                   = useState("");
  const [orgName, setOrgName]                     = useState("");
  const [disclaimerChecked, setDisclaimerChecked] = useState(false);
  const [needsVerify, setNeedsVerify]             = useState(false);
  const [verifyCode, setVerifyCode]               = useState("");
  const [error, setError]                         = useState("");
  const [loading, setLoading]                     = useState(false);
  const [transitioning, setTransitioning]         = useState(false);
  const [mode2, setMode2]                         = useState("");
  const [resetCode, setResetCode]                 = useState("");
  const [newPass, setNewPass]                     = useState("");
  const [resetMsg, setResetMsg]                   = useState("");
  const [showPassword, setShowPassword]           = useState(false);
  const [showNewPass, setShowNewPass]             = useState(false);

  const handleEmailAuth = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    if (mode === "signup") {
      if (!disclaimerChecked) { setError("You must accept the ACORD disclaimer to create an account."); setLoading(false); return; }
      if (!orgName.trim())    { setError("Organization or agency name is required."); setLoading(false); return; }
      if (isPersonalEmail(email)) { setError("Please use a work email address. Personal email domains are not accepted."); setLoading(false); return; }
    }
    const endpoint = mode === "signup" ? "/api/auth/signup" : "/api/auth/login";
    const body     = mode === "signup"
      ? { email, password, full_name: fullName, organization_name: orgName.trim(), acord_disclaimer_accepted: disclaimerChecked }
      : { email, password };
    try {
      const res  = await fetch(`${API_BASE}${endpoint}`, { method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const data = await res.json();
      if (res.status === 202 && data.requires_verification) { setLoading(false); setNeedsVerify(true); }
      else if (res.ok && data.success) { setTransitioning(true); onSuccess(data.user); }
      else if (data.requires_verification) { setLoading(false); setNeedsVerify(true); }
      else { setLoading(false); setError(data.detail || data.message || "Authentication failed"); }
    } catch { setLoading(false); setError("Network error. Please try again."); }
  };

  const handleVerify = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res  = await fetch(`${API_BASE}/api/auth/verify-email`, { method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, code: verifyCode }) });
      const data = await res.json();
      if (res.ok && data.success) { setTransitioning(true); onSuccess(data.user); }
      else { setLoading(false); setError(data.detail || "Invalid code"); }
    } catch { setLoading(false); setError("Network error."); }
  };

  const handleForgotRequest = async (e) => {
    e.preventDefault();
    setError(""); setResetMsg(""); setLoading(true);
    try {
      await fetch(`${API_BASE}/api/auth/forgot-password`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email }) });
      setResetMsg("If that email is registered, a reset code has been sent.");
      setMode2("resetcode");
    } catch { setError("Network error. Please try again."); }
    finally { setLoading(false); }
  };

  const handleResetPassword = async (e) => {
    e.preventDefault();
    setError(""); setLoading(true);
    try {
      const res  = await fetch(`${API_BASE}/api/auth/reset-password`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, code: resetCode, new_password: newPass }) });
      const data = await res.json();
      if (res.ok) { setResetMsg("Password updated! You can now sign in."); setMode2(""); setMode("signin"); setPassword(""); }
      else { setError(data.detail || "Reset failed. Please try again."); }
    } catch { setError("Network error."); }
    finally { setLoading(false); }
  };

  const handleGoogleSuccess = async (credentialResponse) => {
    setLoading(true);
    try {
      const nonceRes = await fetch(`${API_BASE}/api/auth/google/nonce`, { credentials: "include" });
      if (!nonceRes.ok) { setLoading(false); setError("Failed to initialize Google login. Please try again."); return; }
      const { nonce } = await nonceRes.json();
      const res  = await fetch(`${API_BASE}/api/auth/google`, { method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ credential: credentialResponse.credential, nonce }) });
      const data = await res.json();
      if (res.ok && data.success) { setTransitioning(true); onSuccess(data.user, data.profile_incomplete === true); }
      else { setLoading(false); setError(data.detail || data.message || "Google authentication failed"); }
    } catch { setLoading(false); setError("Network error. Please try again."); }
  };

  if (needsVerify) {
    return (
      <div className="modal-overlay">
        <div className="modal-content auth-modal">
          <button className="modal-close" onClick={onClose}>✕</button>
          <div className="modal-inner">
            {transitioning ? (
              <div style={{ textAlign: "center", padding: "40px 0" }}>
                <div className="loading-spinner" style={{ margin: "0 auto 12px" }} />
                <p style={{ color: "#64748b", fontSize: "14px" }}>Signing you in...</p>
              </div>
            ) : (
              <>
                <h2 className="step-title">Verify Your Email</h2>
                <p className="step-subtitle">Enter the 6-digit code sent to {email}</p>
                {error && <div className="alert alert-error"><span>⚠️ {error}</span></div>}
                <form onSubmit={handleVerify} className="auth-form">
                  <div className="form-group">
                    <label>Verification Code</label>
                    <input type="text" value={verifyCode} onChange={(e) => setVerifyCode(e.target.value)} placeholder="123456" required className="form-input" maxLength={6} />
                  </div>
                  <button type="submit" className="btn btn-modal-primary btn-block" disabled={loading}>{loading ? "Verifying..." : "Verify Email"}</button>
                </form>
                <div className="auth-switch">
                  <button onClick={async () => { await fetch(`${API_BASE}/api/auth/resend-verification`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email }) }); }}>Resend code</button>
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    );
  }

  if (mode2 === "forgot") {
    return (
      <div className="modal-overlay">
        <div className="modal-content auth-modal">
          <button className="modal-close" onClick={onClose}>✕</button>
          <div className="modal-inner">
            <h2 className="step-title">Reset Your Password</h2>
            <p className="step-subtitle">Enter your email and we'll send a reset code</p>
            {error    && <div className="alert alert-error"><span>⚠️ {error}</span></div>}
            {resetMsg && <div className="alert alert-success"><span>✅ {resetMsg}</span></div>}
            <form onSubmit={handleForgotRequest} className="auth-form">
              <div className="form-group">
                <label>Email Address</label>
                <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@youragency.com" required className="form-input" />
              </div>
              <button type="submit" className="btn btn-modal-primary btn-block" disabled={loading}>{loading ? "Sending..." : "Send Reset Code"}</button>
            </form>
            <div className="auth-switch"><button onClick={() => { setMode2(""); setError(""); }}>← Back to Sign In</button></div>
          </div>
        </div>
      </div>
    );
  }

  if (mode2 === "resetcode") {
    return (
      <div className="modal-overlay">
        <div className="modal-content auth-modal">
          <button className="modal-close" onClick={onClose}>✕</button>
          <div className="modal-inner">
            <h2 className="step-title">Set New Password</h2>
            <p className="step-subtitle">Enter the code sent to {email} and your new password</p>
            {error    && <div className="alert alert-error"><span>⚠️ {error}</span></div>}
            {resetMsg && <div className="alert alert-success"><span>✅ {resetMsg}</span></div>}
            <form onSubmit={handleResetPassword} className="auth-form">
              <div className="form-group">
                <label>Reset Code</label>
                <input type="text" value={resetCode} onChange={(e) => setResetCode(e.target.value)} placeholder="123456" required className="form-input" maxLength={6} />
              </div>
              <div className="form-group">
                <label>New Password</label>
                <div style={{ position: "relative", width: "100%", display: "block" }}>
                  <input type={showNewPass ? "text" : "password"} value={newPass} onChange={(e) => setNewPass(e.target.value)} placeholder="Min 8 chars, 1 uppercase, 1 special" required className="form-input" style={{ width: "100%", boxSizing: "border-box", paddingRight: "40px" }} />
                  <button type="button" onClick={() => setShowNewPass(v => !v)} style={{ position: "absolute", right: "10px", top: "50%", transform: "translateY(-50%)", background: "none", border: "none", cursor: "pointer", padding: "0", color: "#64748b", display: "flex", alignItems: "center", zIndex: 1 }} tabIndex={-1} aria-label={showNewPass ? "Hide password" : "Show password"}>
                    {showNewPass ? (
                      <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"/><path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19"/><line x1="1" y1="1" x2="23" y2="23"/></svg>
                    ) : (
                      <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
                    )}
                  </button>
                </div>
              </div>
              <button type="submit" className="btn btn-modal-primary btn-block" disabled={loading}>{loading ? "Updating..." : "Set New Password"}</button>
            </form>
            <div className="auth-switch"><button onClick={() => { setMode2("forgot"); setError(""); }}>← Resend code</button></div>
          </div>
        </div>
      </div>
    );
  }

  if (transitioning) {
    return (
      <div className="modal-overlay">
        <div className="modal-content auth-modal" style={{ display: "flex", alignItems: "center", justifyContent: "center", minHeight: "200px" }}>
          <div style={{ textAlign: "center" }}>
            <div className="loading-spinner" style={{ margin: "0 auto 12px" }} />
            <p style={{ color: "#64748b", fontSize: "14px" }}>Signing you in...</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="modal-overlay">
      <div className="modal-content auth-modal">
        <button className="modal-close" onClick={onClose}>✕</button>
        <div className="modal-inner">
          <div className="auth-header">
            <h2 className="step-title">{mode === "signin" ? "Get started" : "Create Account"}</h2>
            <p className="step-subtitle">{mode === "signin" ? "Sign in to access your documents" : "Get started with 3 free downloads"}</p>
          </div>
          {error    && (<div className="alert alert-error"><span>⚠️ {error}</span><button className="alert-close" onClick={() => setError("")}>✕</button></div>)}
          {resetMsg && <div className="alert alert-success"><span>✅ {resetMsg}</span></div>}
          <div className="auth-google">
            <GoogleLogin onSuccess={handleGoogleSuccess} onError={() => setError("Google sign-in failed")} useOneTap size="large" text={mode === "signin" ? "signin_with" : "signup_with"} shape="pill" logo_alignment="left" />
          </div>
          <div style={{ textAlign: "center", margin: "12px 0", color: "#64748b", fontSize: "13px" }}><b>or continue with email </b></div>
          <form onSubmit={handleEmailAuth} className="auth-form">
            {mode === "signup" && (
              <>
                <div className="form-group">
                  <label>Full Name</label>
                  <input type="text" value={fullName} onChange={(e) => setFullName(e.target.value)} placeholder="Jane Smith" required className="form-input" />
                </div>
                <div className="form-group">
                  <label>Organization / Agency Name <span className="field-required">*</span></label>
                  <input type="text" value={orgName} onChange={(e) => setOrgName(e.target.value)} placeholder="Smith Insurance Agency LLC" required className="form-input" />
                </div>
              </>
            )}
            <div className="form-group">
              <label>Work Email <span className="field-required">*</span></label>
              <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@youragency.com" required className="form-input" />
              {mode === "signup" && isPersonalEmail(email) && email.length > 4 && (
                <span className="field-warning">⚠ Please use a work email address</span>
              )}
            </div>
            <div className="form-group">
              <label>Password</label>
              <div style={{ position: "relative", width: "100%", display: "block" }}>
                <input type={showPassword ? "text" : "password"} value={password} onChange={(e) => setPassword(e.target.value)} placeholder={mode === "signup" ? "Min 8 chars, 1 uppercase, 1 special" : "••••••••"} required className="form-input" style={{ width: "100%", boxSizing: "border-box", paddingRight: "40px" }} />
                <button type="button" onClick={() => setShowPassword(v => !v)} style={{ position: "absolute", right: "10px", top: "50%", transform: "translateY(-50%)", background: "none", border: "none", cursor: "pointer", padding: "0", color: "#64748b", display: "flex", alignItems: "center", zIndex: 1 }} tabIndex={-1} aria-label={showPassword ? "Hide password" : "Show password"}>
                  {showPassword ? (
                    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"/><path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19"/><line x1="1" y1="1" x2="23" y2="23"/></svg>
                  ) : (
                    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
                  )}
                </button>
              </div>
            </div>
            {mode === "signup" && (
              <div className="acord-disclaimer-box">
                <label className="acord-disclaimer-label">
                  <input type="checkbox" checked={disclaimerChecked} onChange={(e) => setDisclaimerChecked(e.target.checked)} className="acord-disclaimer-checkbox" />
                  <span>By creating an account, you acknowledge that <strong>ACORD® Forms require a separate license from ACORD Corporation</strong> and agree to obtain any required license before exporting or distributing those forms.</span>
                </label>
              </div>
            )}
            <button type="submit" className="btn btn-modal-primary btn-block" disabled={loading || (mode === "signup" && !disclaimerChecked)}>
              {loading ? "Please wait..." : mode === "signin" ? "Sign In" : "Create Account"}
            </button>
          </form>
          <div className="auth-switch">
            {mode === "signin" ? (
              <>
                <p>Don't have an account? <button onClick={() => { setMode("signup"); setDisclaimerChecked(false); setResetMsg(""); }}>Sign up</button></p>
                <p style={{ marginTop: "6px" }}>
                  <button style={{ color: "#64748b", fontSize: "13px" }} onClick={() => { setMode2("forgot"); setError(""); setResetMsg(""); }}>Forgot your password?</button>
                </p>
              </>
            ) : (
              <p>Already have an account? <button onClick={() => setMode("signin")}>Sign in</button></p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}