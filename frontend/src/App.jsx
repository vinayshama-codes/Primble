import { useState, useEffect } from "react";
import "./App.css";
import "./styles/injected.js";
import { GoogleOAuthProvider } from "@react-oauth/google";

import { GOOGLE_CLIENT_ID, API_BASE } from "./config/constants";
import { useAuth }            from "./hooks/useAuth";
import { useSignature }       from "./hooks/useSignature";
import { useUpgradePolling, useBillingReturnPolling } from "./hooks/useUpgradePolling";
import { applyOverage }       from "./api/stripeApi";

import UpgradeStageOverlay    from "./components/overlays/UpgradeStageOverlay";
import Header                 from "./components/layout/Header";
import LandingPage            from "./components/layout/LandingPage";
import AuthModal              from "./components/auth/AuthModal";
import CompleteProfileModal   from "./components/auth/CompleteProfileModal";
import AcordModal             from "./components/form/AcordModal";
import UpgradeModal           from "./components/billing/UpgradeModal";
import SignatureModal         from "./components/signature/SignatureModal";
import ClientQuestionnaire    from "./components/arq/ClientQuestionnaire";

export default function App() {
  const path = window.location.pathname;

  // Match BOTH /questionnaire/ and /client-questionnaire/ to handle both formats
  const qMatch = path.match(/^\/(?:client-)?questionnaire\/([^/]+)$/);
  if (qMatch) {
    return <ClientQuestionnaire token={qMatch[1]} />;
  }

  return (
    <GoogleOAuthProvider clientId={GOOGLE_CLIENT_ID}>
      <AppContent />
    </GoogleOAuthProvider>
  );
}

function AppContent() {
  const { user, setUser, token, login, logout } = useAuth();
  const { savedSignature, updateSignature }      = useSignature(token, user);

  const _resumeFromUrl = () => {
    const p = new URLSearchParams(window.location.search);
    return p.get("resume_session") || null;
  };

  const [showModal,           setShowModal]           = useState(false);
  const [showAuthModal,       setShowAuthModal]       = useState(false);
  const [showCompleteProfile, setShowCompleteProfile] = useState(false);
  const [showUpgradeModal,    setShowUpgradeModal]    = useState(false);
  const [showSignatureModal,  setShowSignatureModal]  = useState(false);
  const [signingIn,           setSigningIn]           = useState(false);
  const [headerError,         setHeaderError]         = useState("");
  const [resumeSessionId,     setResumeSessionId]     = useState(null);
  const [upgradeChecking,     setUpgradeChecking]     = useState(false);
  const [upgradeFailed,       setUpgradeFailed]       = useState(false);
  const [overageToast,        setOverageToast]        = useState(null);

  useUpgradePolling(token, setUser, setUpgradeChecking, setUpgradeFailed);
  useBillingReturnPolling(token, setUser, setUpgradeChecking);

  // Step 1: on mount, capture resume_session param and clear URL
    useEffect(() => {
      const sid = _resumeFromUrl();
      if (!sid) return;
      window.history.replaceState({}, "", "/");
      sessionStorage.setItem("acordly_resume_after_login", sid);
    }, []); // eslint-disable-line

    // Step 2: once auth is ready, consume the stored resume session
    useEffect(() => {
      if (!token || !user) return;
      const sid = sessionStorage.getItem("acordly_resume_after_login");
      if (!sid) return;
      sessionStorage.removeItem("acordly_resume_after_login");
      setResumeSessionId(sid);
      setShowModal(true);
    }, [token, user]); // fires when auth resolves
    
  useEffect(() => {
    const params          = new URLSearchParams(window.location.search);
    if (params.get("overage_paid") !== "true") return;
    const qty             = params.get("qty") || "?";
    const stripeSessionId = params.get("stripe_session_id");
    const savedSid        = localStorage.getItem("acordly_overage_session");
    window.history.replaceState({}, "", "/");
    localStorage.removeItem("acordly_overage_session");
    localStorage.removeItem("acordly_prev_limit");
    if (!token || !stripeSessionId) return;
    applyOverage(token, stripeSessionId, parseInt(qty) || 1)
      .then(({ data }) => {
        fetch(`${API_BASE}/api/auth/me`, { headers: { Authorization: `Bearer ${token}` } })
          .then(r => r.ok ? r.json() : null).then(me => { if (me) setUser(me); });
        const applied = data.credited || data.already_applied;
        setOverageToast(applied
          ? `✅ ${qty} extra package${qty !== "1" ? "s" : ""} added!`
          : `⚠️ Could not verify payment. Contact support if packages were not credited.`);
        setTimeout(() => setOverageToast(null), 8000);
        if (savedSid && applied) { setResumeSessionId(savedSid); setShowModal(true); }
      })
      .catch(() => {
        setOverageToast("⚠️ Payment received but could not auto-credit. Please refresh.");
        setTimeout(() => setOverageToast(null), 8000);
        if (savedSid) { setResumeSessionId(savedSid); setShowModal(true); }
      });
  }, []); // eslint-disable-line

  const openBillingPortal = async () => {
    setUpgradeChecking(true);
    try {
      const res  = await fetch(`${API_BASE}/api/stripe/create-portal-session`, { method: "POST", headers: { Authorization: `Bearer ${token}` } });
      const data = await res.json();
      if (data.url) { window.location.href = data.url; }
      else { setUpgradeChecking(false); setHeaderError(data.detail || "Could not open billing portal."); }
    } catch { setUpgradeChecking(false); setHeaderError("Network error. Please try again."); }
  };

  const handleGetStarted = () => (user ? setShowModal(true) : setShowAuthModal(true));

  return (
    <div className="landing-container">
      {overageToast && (
        <div style={{ position: "fixed", bottom: 24, left: "50%", transform: "translateX(-50%)", background: "#10b981", color: "#fff", padding: "12px 24px", borderRadius: 10, fontWeight: 600, fontSize: 14, zIndex: 9999, boxShadow: "0 4px 20px rgba(0,0,0,0.18)" }}>
          {overageToast}
        </div>
      )}
      {upgradeChecking && <UpgradeStageOverlay />}
      {signingIn && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(255,255,255,0.97)", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", zIndex: 9999 }}>
          <div className="loading-spinner" style={{ width: 40, height: 40, marginBottom: 16 }} />
          <p style={{ color: "#64748b", fontSize: "15px", fontWeight: 500 }}>Signing you in...</p>
        </div>
      )}
      <Header
        user={user} token={token} savedSignature={savedSignature}
        onSignatureClick={() => setShowSignatureModal(true)}
        onUpgradeClick={() => setShowUpgradeModal(true)}
        onLogout={logout} openBillingPortal={openBillingPortal}
        upgradeChecking={upgradeChecking} upgradeFailed={upgradeFailed}
        setUpgradeFailed={setUpgradeFailed} setUpgradeChecking={setUpgradeChecking} setUser={setUser}
      />
      {headerError && (
        <div className="header-error-bar">⚠️ {headerError}<button onClick={() => setHeaderError("")}>✕</button></div>
      )}
      <LandingPage user={user} onGetStarted={handleGetStarted} />

      {showAuthModal && (
        <AuthModal
          onClose={() => setShowAuthModal(false)}
          onSuccess={(tok, usr, profileIncomplete) => {
            login(tok, usr);
            setShowAuthModal(false);
            setSigningIn(true);
            setTimeout(() => {
              setSigningIn(false);
              const pendingResume = sessionStorage.getItem("acordly_resume_after_login");
              sessionStorage.removeItem("acordly_resume_after_login");
              if (profileIncomplete)    { setShowCompleteProfile(true); }
              else if (pendingResume)   { setResumeSessionId(pendingResume); setShowModal(true); }
              else                      { setShowModal(true); }
            }, 80);
          }}
        />
      )}
      {showCompleteProfile && user && (
        <CompleteProfileModal token={token} user={user}
          onComplete={(u) => { setUser(u); setShowCompleteProfile(false); setShowModal(true); }}
        />
      )}
      {showModal && user && (
        <AcordModal
          onClose={() => { setShowModal(false); setResumeSessionId(null); }}
          user={user} token={token} onUserUpdate={setUser}
          onShowUpgrade={() => setShowUpgradeModal(true)}
          resumeSessionId={resumeSessionId}
          savedSignature={savedSignature}
          onOpenSignatureModal={() => setShowSignatureModal(true)}
          onOpenBillingPortal={openBillingPortal}
          billingPortalLoading={false}
        />
      )}
      {showUpgradeModal && (
        <UpgradeModal token={token} user={user}
          onClose={() => setShowUpgradeModal(false)}
          onError={(msg) => { setShowUpgradeModal(false); setHeaderError(msg); }}
        />
      )}
      {showSignatureModal && (
        <SignatureModal token={token} existingSignature={savedSignature}
          onClose={() => setShowSignatureModal(false)}
          onSaved={(sig) => { updateSignature(sig); setShowSignatureModal(false); }}
        />
      )}
    </div>
  );
}