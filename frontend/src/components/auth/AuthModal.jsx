import { useState } from "react";
import { GoogleLogin } from "@react-oauth/google";
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

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const PASS_UPPER_RE = /[A-Z]/;
const PASS_SPECIAL_RE = /[^a-zA-Z0-9]/;

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
  const [fieldErrors, setFieldErrors]             = useState({});
  const SIGNUP_STAGES = ["Verifying your email..."];

  const clearFieldError = (field) => setFieldErrors(prev => { const n = { ...prev }; delete n[field]; return n; });

  const handleEmailAuth = async (e) => {
    e.preventDefault();
    setError("");
    const errs = {};

    if (mode === "signup") {
      if (!fullName.trim()) {
        errs.fullName = "Please enter your full name.";
      } else if (!/^[a-zA-Z\s'\-\.]+$/.test(fullName.trim())) {
        errs.fullName = "Please enter a valid full name.";
      }
      if (!orgName.trim()) {
        errs.orgName = "Please enter your organization or agency name.";
      } else if (!/^[a-zA-Z0-9\s'\-\.,&]+$/.test(orgName.trim())) {
        errs.orgName = "Please enter a valid organization or agency name.";
      }
    }

    if (!email.trim() || !EMAIL_RE.test(email.trim())) {
      errs.email = "Please provide your valid email address.";
    }

    if (!password) {
      errs.password = mode === "signup" ? "Please create a password." : "Please enter your password.";
    } else if (password.length < 8) {
      errs.password = "Password must be at least 8 characters long.";
    } else if (mode === "signup" && (!PASS_UPPER_RE.test(password) || !PASS_SPECIAL_RE.test(password))) {
      errs.password = "Please enter a valid password.";
    }

    if (Object.keys(errs).length > 0) { setFieldErrors(errs); return; }
    setFieldErrors({});
    setLoading(true);

    if (mode === "signup") {
      if (!disclaimerChecked) { setError("You must accept the ACORD disclaimer to create an account."); setLoading(false); return; }
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
            <div style={{ display: "flex", justifyContent: "center", marginBottom: "6px" }}>
              <img src="/primble-logo.webp" alt="Primble" style={{ height: "32px", width: "auto" }} />
            </div>
            <p className="step-subtitle">{mode === "signin" ? "Sign in to access your packages" : "Get started with three free packages"}</p>
          </div>
          {error    && (<div className="alert alert-error"><span>{error}</span><button className="alert-close" onClick={() => setError("")}>✕</button></div>)}
          {resetMsg && <div className="alert alert-success"><span>✅ {resetMsg}</span></div>}
          <div className="auth-google">
            <div style={{ position: "relative", width: "100%" }}>
              <button className="google-btn-custom" type="button" style={{ pointerEvents: "none", position: "relative", zIndex: 2 }}>
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="18" height="18">
                  <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4"/>
                  <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
                  <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l3.66-2.84z" fill="#FBBC05"/>
                  <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
                </svg>
                <span>{mode === "signin" ? "Sign in with Google" : "Sign up with Google"}</span>
              </button>
              <div style={{ position: "absolute", inset: 0, zIndex: 1, overflow: "hidden", borderRadius: "12px" }}>
                <GoogleLogin onSuccess={handleGoogleSuccess} onError={() => setError("Google sign-in failed")} size="large" text={mode === "signin" ? "signin_with" : "signup_with"} shape="rectangular" logo_alignment="left" width={600} />
              </div>
            </div>
          </div>
          <div style={{ textAlign: "center", margin: "6px 0", color: "#64748b", fontSize: "13px" }}><b>or continue with email </b></div>
          <form onSubmit={handleEmailAuth} className="auth-form" noValidate>
            {mode === "signup" && (
              <>
                <div className="form-group">
                  <label>Full Name</label>
                  <input type="text" value={fullName} onChange={(e) => { setFullName(e.target.value); clearFieldError("fullName"); }} placeholder="Jane Smith" className={`form-input${fieldErrors.fullName ? " input-field-error" : ""}`} />
                  {fieldErrors.fullName && <span className="field-error-msg">{fieldErrors.fullName}</span>}
                </div>
                <div className="form-group">
                  <label>Organization / Agency Name</label>
                  <input type="text" value={orgName} onChange={(e) => { setOrgName(e.target.value); clearFieldError("orgName"); }} placeholder="Smith Insurance Agency LLC" className={`form-input${fieldErrors.orgName ? " input-field-error" : ""}`} />
                  {fieldErrors.orgName && <span className="field-error-msg">{fieldErrors.orgName}</span>}
                </div>
              </>
            )}
            <div className="form-group">
              <label>{mode === "signin" ? "Username (email)" : "Email"}</label>
              <input type="text" value={email} onChange={(e) => { setEmail(e.target.value); clearFieldError("email"); }} placeholder="you@example.com" className={`form-input${fieldErrors.email ? " input-field-error" : ""}`} />
              {fieldErrors.email && <span className="field-error-msg">{fieldErrors.email}</span>}
            </div>
            <div className="form-group">
              <label>Password</label>
              <div style={{ position: "relative", width: "100%", display: "block" }}>
                <input type={showPassword ? "text" : "password"} value={password} onChange={(e) => { setPassword(e.target.value); clearFieldError("password"); }} placeholder={mode === "signup" ? "Min 8 chars, 1 uppercase, 1 special" : "••••••••"} className={`form-input${fieldErrors.password ? " input-field-error" : ""}`} style={{ width: "100%", boxSizing: "border-box", paddingRight: "40px" }} />
                <button type="button" onClick={() => setShowPassword(v => !v)} style={{ position: "absolute", right: "10px", top: "50%", transform: "translateY(-50%)", background: "none", border: "none", cursor: "pointer", padding: "0", color: "#64748b", display: "flex", alignItems: "center", zIndex: 1 }} tabIndex={-1} aria-label={showPassword ? "Hide password" : "Show password"}>
                  {showPassword ? (
                    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"/><path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19"/><line x1="1" y1="1" x2="23" y2="23"/></svg>
                  ) : (
                    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
                  )}
                </button>
              </div>
              {fieldErrors.password && <span className="field-error-msg">{fieldErrors.password}</span>}
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