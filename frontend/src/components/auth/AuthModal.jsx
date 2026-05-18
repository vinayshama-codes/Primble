import { useState } from "react";
import { GoogleLogin } from "@react-oauth/google";
import { useGoogleReCaptcha } from "react-google-recaptcha-v3";
import { API_BASE } from "../../config/constants";

function AuthLoadingOverlay({ label }) {
  return (
    <div style={{
      position: "fixed", inset: 0, background: "rgba(255,255,255,0.97)",
      display: "flex", flexDirection: "column", alignItems: "center",
      justifyContent: "center", zIndex: 99999, gap: 24,
    }}>
      <div style={{
        width: 52, height: 52, borderRadius: "50%",
        border: "4px solid #e2e8f0", borderTopColor: "#e61b84",
        animation: "spin 0.9s linear infinite",
      }} />
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <div style={{ width: 8, height: 8, borderRadius: "50%", background: "#e61b84" }} />
        <span style={{ fontSize: 16, fontWeight: 700, color: "#1e293b" }}>{label}</span>
      </div>
    </div>
  );
}

const extractError = (detail) =>
  Array.isArray(detail) ? detail.map((e) => e.msg || String(e)).join("; ") : (detail || "");

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
  const SIGNUP_STAGES = ["Verifying your email..."];

  const { executeRecaptcha } = useGoogleReCaptcha();

  const handleEmailAuth = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    if (mode === "signup") {
      if (!disclaimerChecked) { setError("You must accept the ACORD disclaimer to create an account."); setLoading(false); return; }
      if (!orgName.trim())    { setError("Organization or agency name is required."); setLoading(false); return; }
    }
    const endpoint = mode === "signup" ? "/api/auth/signup" : "/api/auth/login";

    let recaptcha_token = null;
    if (mode === "signup" && executeRecaptcha) {
      try { recaptcha_token = await executeRecaptcha("signup"); } catch { /* non-blocking */ }
    }

    const body     = mode === "signup"
      ? { email, password, full_name: fullName, organization_name: orgName.trim(), acord_disclaimer_accepted: disclaimerChecked, recaptcha_token }
      : { email, password };
    try {
      const res  = await fetch(`${API_BASE}${endpoint}`, { method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const data = await res.json();
      if (res.status === 202 && data.requires_verification) { setLoading(false); setNeedsVerify(true); }
      else if (res.ok && data.success) { setTransitioning(true); onSuccess(data.user); }
      else if (data.requires_verification) { setLoading(false); setNeedsVerify(true); }
      else { setLoading(false); setError(extractError(data.detail) || data.message || "Authentication failed"); }
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
      else { setLoading(false); setError(extractError(data.detail) || "Invalid code"); }
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
      else { setError(extractError(data.detail) || "Reset failed. Please try again."); }
    } catch { setError("Network error."); }
    finally { setLoading(false); }
  };

  const handleGoogleSuccess = async (credentialResponse) => {
    setLoading(true);
    try {
      const res  = await fetch(`${API_BASE}/api/auth/google`, { method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ credential: credentialResponse.credential }) });
      const data = await res.json();
      if (res.ok && data.success) {
        if (data.profile_incomplete) {
          onSuccess(data.user, true, data.pending_token || null);
        } else {
          setTransitioning(true);
          onSuccess(data.user, false, null);
        }
      }
      else { setLoading(false); setError(extractError(data.detail) || data.message || "Google authentication failed"); }
    } catch { setLoading(false); setError("Network error. Please try again."); }
  };

  if (needsVerify) {
    return (
      <div className="modal-overlay">
        <div className="modal-content auth-modal">
          <button className="modal-close" onClick={onClose}>✕</button>
          <div className="modal-inner">
            {transitioning ? (
              <AuthLoadingOverlay label="Signing you in..." />
            ) : (
              <>
                <h2 className="step-title">Verify Your Email</h2>
                <p className="step-subtitle">Enter the 6-digit code sent to {email}</p>
                {error && <div className="alert alert-error"><span>{error}</span></div>}
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
            {error    && <div className="alert alert-error"><span>{error}</span></div>}
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
            {error    && <div className="alert alert-error"><span>{error}</span></div>}
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
    return <AuthLoadingOverlay label="Signing you in..." />;
  }

  if (loading) {
    return <AuthLoadingOverlay label={mode === "signup" ? SIGNUP_STAGES[0] : "Signing you in..."} />;
  }

  return (
    <div className="modal-overlay">
      <div className="modal-content auth-modal">
        <button className="modal-close" onClick={onClose}>✕</button>
        <div className="modal-inner">
          <div className="auth-header">
            <div style={{ display: "flex", justifyContent: "center", marginBottom: "12px" }}>
              <img src="/primble-logo.webp" alt="Primble" style={{ height: "32px", width: "auto" }} />
            </div>
            <p className="step-subtitle">{mode === "signin" ? "Sign in to access your documents" : "Get started with 3 free downloads"}</p>
          </div>
          {error    && (<div className="alert alert-error"><span>{error}</span><button className="alert-close" onClick={() => setError("")}>✕</button></div>)}
          {resetMsg && <div className="alert alert-success"><span>✅ {resetMsg}</span></div>}
          <div className="auth-google">
            <div className="google-btn-wrapper">
              <button type="button" className="google-btn-custom" tabIndex={-1} aria-hidden="true">
                <svg width="20" height="20" viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg">
                  <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/>
                  <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/>
                  <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/>
                  <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.18 1.48-4.97 2.31-8.16 2.31-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/>
                  <path fill="none" d="M0 0h48v48H0z"/>
                </svg>
                <span>{mode === "signin" ? "Continue with Google" : "Sign up with Google"}</span>
              </button>
              <div className="google-btn-overlay">
                <GoogleLogin
                  onSuccess={handleGoogleSuccess}
                  onError={() => setError("Google sign-in failed")}
                  size="large"
                  text={mode === "signin" ? "signin_with" : "signup_with"}
                  shape="rectangular"
                  logo_alignment="left"
                  width={440}
                />
              </div>
            </div>
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
              <label>Email <span className="field-required">*</span></label>
              <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" required className="form-input" />
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
                  <span>By creating a Primble account, you acknowledge that <strong>ACORD Corporation</strong> requires a separate license to build and distribute <strong>ACORD Forms</strong> and agree to obtain such license.</span>
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
                <p style={{ marginBottom: "6px" }}>
                  <button style={{ color: "#64748b", fontSize: "13px", fontWeight: "normal" }} onClick={() => { setMode2("forgot"); setError(""); setResetMsg(""); }}>Forgot your password?</button>
                </p>
                <p>Don't have an account? <button onClick={() => { setMode("signup"); setDisclaimerChecked(false); setResetMsg(""); }}>Sign up</button></p>
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