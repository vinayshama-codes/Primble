import { useState, useEffect } from "react";
import "./App.css";
import "./styles/injected.js";
import { GoogleOAuthProvider } from "@react-oauth/google";
import { GoogleReCaptchaProvider } from "react-google-recaptcha-v3";

import { GOOGLE_CLIENT_ID, API_BASE, RECAPTCHA_SITE_KEY } from "./config/constants";
import { useAuth }            from "./hooks/useAuth";
import { useSignature }       from "./hooks/useSignature";
import { useUpgradePolling, useBillingReturnPolling } from "./hooks/useUpgradePolling";
import { applyOverage }       from "./api/stripeApi";

import UpgradeStageOverlay    from "./components/overlays/UpgradeStageOverlay";
import Header                 from "./components/layout/Header";
import LandingPage            from "./components/layout/LandingPage";
import AboutPage              from "./components/pages/AboutPage";
import PlatformPage           from "./components/pages/PlatformPage";
import PricingPage            from "./components/pages/PricingPage";
import AcordLicensePage       from "./components/pages/AcordLicensePage";
import AuthModal              from "./components/auth/AuthModal";
import CompleteProfileModal   from "./components/auth/CompleteProfileModal";
import AcordModal             from "./components/form/AcordModal";
import UpgradeModal           from "./components/billing/UpgradeModal";
import SignatureModal         from "./components/signature/SignatureModal";
import ClientQuestionnaire    from "./components/arq/ClientQuestionnaire";
import ErrorBoundary          from "./components/layout/ErrorBoundary";
import AccountSettingsModal   from "./components/account/AccountSettingsModal";
import ContactModal           from "./components/account/ContactModal";

export default function App() {
  const path = window.location.pathname;

  const qMatch = path.match(/^\/(?:client-)?questionnaire\/([^/]+)$/);
  if (qMatch) {
    return <ErrorBoundary><ClientQuestionnaire token={qMatch[1]} /></ErrorBoundary>;
  }

  const inner = (
    <GoogleOAuthProvider clientId={GOOGLE_CLIENT_ID}>
      <AppContent />
    </GoogleOAuthProvider>
  );

  return (
    <ErrorBoundary>
      {RECAPTCHA_SITE_KEY
        ? <GoogleReCaptchaProvider reCaptchaKey={RECAPTCHA_SITE_KEY} scriptProps={{ async: true, defer: true }}>{inner}</GoogleReCaptchaProvider>
        : inner}
    </ErrorBoundary>
  );
}

function AppLoadingOverlay({ label }) {
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

function MarketingFooter() {
  return (
    <footer className="footer">
      <div><h4 className="footer-h4">About Us</h4><p className="footer-p">Primble automates ACORD form processing for insurance brokers and underwriting teams.</p></div>
      <div><h4 className="footer-h4">Contact Us</h4><p className="footer-p">support@primble.ai</p></div>
      <div>
        <h4 className="footer-h4">Follow Us</h4>
        <p className="footer-p">
          <a href="https://twitter.com" target="_blank" rel="noopener noreferrer">Twitter</a>
          <a href="https://linkedin.com" target="_blank" rel="noopener noreferrer">LinkedIn</a>
        </p>
      </div>
      <div>
        <h4 className="footer-h4">Newsletter</h4>
        <p className="footer-p">Product updates and insurance workflow insights.</p>
        <input className="footer-input" placeholder="Email Address" />
        <button className="footer-button">Sign Up</button>
      </div>
    </footer>
  );
}

function AppContent() {
  const { user, setUser, token, login, logout } = useAuth();
  const { savedSignature, updateSignature }      = useSignature(token, user);

  const _resumeFromUrl = () => {
    const p = new URLSearchParams(window.location.search);
    return p.get("resume_session") || null;
  };

  const _hasResume = !!new URLSearchParams(window.location.search).get("resume_session");
  const [showModal,           setShowModal]           = useState(false);
  const [resumeLoading,       setResumeLoading]       = useState(_hasResume);
  const [showAuthModal,       setShowAuthModal]       = useState(false);
  const [authModalMode,       setAuthModalMode]       = useState("signin");
  const [showCompleteProfile, setShowCompleteProfile] = useState(false);
  const [pendingGoogleToken,  setPendingGoogleToken]  = useState(null);
  const [pendingGoogleUser,   setPendingGoogleUser]   = useState(null);
  const [showUpgradeModal,    setShowUpgradeModal]    = useState(false);
  const [showSignatureModal,  setShowSignatureModal]  = useState(false);
  const [showAccountSettings, setShowAccountSettings] = useState(false);
  const [showContactModal,    setShowContactModal]    = useState(false);
  const [signingIn,           setSigningIn]           = useState(false);
  const [headerError,         setHeaderError]         = useState("");
  const [resumeSessionId,     setResumeSessionId]     = useState(null);
  const [upgradeChecking,     setUpgradeChecking]     = useState(false);
  const [upgradeFailed,       setUpgradeFailed]       = useState(false);
  const [overageToast,        setOverageToast]        = useState(null);
  const [marketingPage,       setMarketingPage]       = useState(null);
  const [portalRedirecting,   setPortalRedirecting]   = useState(false);

  // Parse Stripe redirect params once at mount; clear them from the URL immediately
  // so the hook is driven by confirmed Stripe redirects only, not arbitrary URL visits.
  const [stripeRedirect] = useState(() => {
    const params = new URLSearchParams(window.location.search);
    const upgraded = params.get("upgraded") === "true";
    if (!upgraded) return null;
    window.history.replaceState({}, "", "/");
    return {
      shouldPoll:      true,
      expectedPlan:    params.get("plan") || null,
      stripeSessionId: params.get("session_id") || null,
    };
  });

  useUpgradePolling(
    stripeRedirect?.shouldPoll ?? false,
    setUser,
    setUpgradeChecking,
    setUpgradeFailed,
    stripeRedirect?.expectedPlan ?? null,
    stripeRedirect?.stripeSessionId ?? null,
  );
  useBillingReturnPolling(token, setUser, setUpgradeChecking);

  useEffect(() => {
    const sid = _resumeFromUrl();
    if (!sid) return;
    window.history.replaceState({}, "", "/");
    sessionStorage.setItem("acordly_resume_after_login", sid);
  }, []); // eslint-disable-line

  useEffect(() => {
    if (!user) return;
    const sid = sessionStorage.getItem("acordly_resume_after_login");
    if (!sid) { setResumeLoading(false); return; }
    sessionStorage.removeItem("acordly_resume_after_login");
    setResumeSessionId(sid);
    setResumeLoading(false);
    setShowModal(true);
  }, [user]);

  useEffect(() => {
    const params          = new URLSearchParams(window.location.search);
    if (params.get("overage_paid") !== "true") return;
    const qty             = params.get("qty") || "?";
    const stripeSessionId = params.get("stripe_session_id");
    const savedSid        = localStorage.getItem("acordly_overage_session");
    window.history.replaceState({}, "", "/");
    localStorage.removeItem("acordly_overage_session");
    localStorage.removeItem("acordly_prev_limit");
    if (!stripeSessionId) return;
    applyOverage(stripeSessionId, parseInt(qty) || 1)
      .then(({ data }) => {
        fetch(`${API_BASE}/api/auth/me`, { credentials: "include" })
          .then(r => r.ok ? r.json() : null).then(me => { if (me) setUser(me); });
        const applied = data.credited || data.already_applied;
        setOverageToast(applied
          ? `✅ ${qty} extra package${qty !== "1" ? "s" : ""} added!`
          : `Could not verify payment. Contact support if packages were not credited.`);
        setTimeout(() => setOverageToast(null), 8000);
        if (savedSid && applied) { setResumeSessionId(savedSid); setShowModal(true); }
      })
      .catch(() => {
        setOverageToast("Payment received but could not auto-credit. Please refresh.");
        setTimeout(() => setOverageToast(null), 8000);
        if (savedSid) { setResumeSessionId(savedSid); setShowModal(true); }
      });
  }, []); // eslint-disable-line

  const openBillingPortal = async () => {
    setPortalRedirecting(true);
    try {
      const res  = await fetch(`${API_BASE}/api/stripe/create-portal-session`, { method: "POST", credentials: "include" });
      const data = await res.json();
      if (data.url) { window.location.href = data.url; }
      else { setPortalRedirecting(false); setHeaderError(data.detail || "Could not open billing portal."); }
    } catch { setPortalRedirecting(false); setHeaderError("Network error. Please try again."); }
  };

  const handleGetStarted = (planId, billingCycle, authMode) => {
    if (planId) {
      sessionStorage.setItem("acordly_pending_plan", planId);
      sessionStorage.setItem("acordly_pending_billing_cycle", billingCycle || "monthly");
    }
    setMarketingPage(null);
    if (user) {
      if (planId) {
        triggerPendingCheckout();
      } else {
        setShowModal(true);
        window.history.pushState({ acordly: true }, "");
      }
    } else {
      setAuthModalMode(authMode === "signup" ? "signup" : "signin");
      setShowAuthModal(true);
    }
  };

  const triggerPendingCheckout = async () => {
    const planId       = sessionStorage.getItem("acordly_pending_plan");
    const billingCycle = sessionStorage.getItem("acordly_pending_billing_cycle") || "monthly";
    if (!planId) return false;
    sessionStorage.removeItem("acordly_pending_plan");
    sessionStorage.removeItem("acordly_pending_billing_cycle");
    setPortalRedirecting(true);
    try {
      const res  = await fetch(`${API_BASE}/api/stripe/create-checkout`, {
        method: "POST", credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ plan: planId, billing_cycle: billingCycle }),
      });
      const data = await res.json();
      if (data.checkout_url) {
        window.location.href = data.checkout_url;
        return true;
      }
      setPortalRedirecting(false);
      setHeaderError(data.detail || "Failed to start checkout. Please try again.");
    } catch {
      setPortalRedirecting(false);
      setHeaderError("Network error. Please try again.");
    }
    return false;
  };

  const handleNavigate = (page) => {
    setMarketingPage(page);
    setShowModal(false);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  useEffect(() => {
    const handlePop = () => {
      if (showModal) { setShowModal(false); setResumeSessionId(null); }
    };
    window.addEventListener("popstate", handlePop);
    return () => window.removeEventListener("popstate", handlePop);
  }, [showModal]);

 return (
    <div className="landing-container">
      {overageToast && (
        <div style={{ position: "fixed", bottom: 24, left: "50%", transform: "translateX(-50%)", background: "#10b981", color: "#fff", padding: "12px 24px", borderRadius: 10, fontWeight: 600, fontSize: 14, zIndex: 9999, boxShadow: "0 4px 20px rgba(0,0,0,0.18)" }}>
          {overageToast}
        </div>
      )}

      {upgradeChecking && <UpgradeStageOverlay />}

      {portalRedirecting && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(255,255,255,0.97)", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", zIndex: 9999 }}>
          <div className="loading-spinner" style={{ width: 40, height: 40, marginBottom: 16 }} />
          <p style={{ color: "#64748b", fontSize: 15, fontWeight: 500 }}>Redirecting to Stripe…</p>
        </div>
      )}

      {resumeLoading && <AppLoadingOverlay label="Restoring your session..." />}

      {signingIn && <AppLoadingOverlay label="Signing you in..." />}

      {/* Persistent header — always visible */}
      <Header
        user={user} token={token} savedSignature={savedSignature}
        onSignatureClick={() => setShowSignatureModal(true)}
        onUpgradeClick={() => setShowUpgradeModal(true)}
        onLogout={logout} openBillingPortal={openBillingPortal}
        upgradeChecking={upgradeChecking} upgradeFailed={upgradeFailed}
        setUpgradeFailed={setUpgradeFailed} setUpgradeChecking={setUpgradeChecking} setUser={setUser}
        onSignUp={() => { setAuthModalMode("signup"); setShowAuthModal(true); }}
        onLogIn={() => { setAuthModalMode("signin"); setShowAuthModal(true); }}
        onNavigate={handleNavigate}
        onHome={() => { setMarketingPage(null); setShowModal(false); }}
        onAccountSettings={() => setShowAccountSettings(true)}
        onContactPrimble={() => setShowContactModal(true)}
      />
      {headerError && (
        <div className="header-error-bar">{headerError}<button onClick={() => setHeaderError("")}>✕</button></div>
      )}

      {/* Page content — switches between landing, marketing pages, and app */}
      {showModal && user ? (
        <AcordModal
          onClose={() => { setShowModal(false); setResumeSessionId(null); }}
          user={user} token={token} onUserUpdate={setUser}
          onShowUpgrade={() => setShowUpgradeModal(true)}
          resumeSessionId={resumeSessionId}
          savedSignature={savedSignature}
          onOpenSignatureModal={() => setShowSignatureModal(true)}
          onOpenBillingPortal={openBillingPortal}
          billingPortalLoading={false}
          fullPage={false}
        />
      ) : marketingPage === "about" ? (
        <><AboutPage onGetStarted={handleGetStarted} onNavigate={handleNavigate} /><MarketingFooter /></>
      ) : marketingPage === "platform" ? (
        <><PlatformPage onGetStarted={handleGetStarted} onNavigate={handleNavigate} /><MarketingFooter /></>
      ) : marketingPage === "pricing" ? (
        <><PricingPage onGetStarted={handleGetStarted} onNavigate={handleNavigate} token={token} user={user} onError={(msg) => setHeaderError(msg)} openBillingPortal={openBillingPortal} /><MarketingFooter /></>
      ) : marketingPage === "acord-license" ? (
        <><AcordLicensePage /><MarketingFooter /></>
      ) : (
        <LandingPage user={user} onGetStarted={handleGetStarted} token={token} onError={(msg) => setHeaderError(msg)} openBillingPortal={openBillingPortal} />
      )}

      {showAuthModal && (
        <AuthModal
          initialMode={authModalMode}
          onClose={() => setShowAuthModal(false)}
          onSuccess={(usr, profileIncomplete, pendingToken) => {
            setShowAuthModal(false);
            if (profileIncomplete) {
              setPendingGoogleToken(pendingToken || null);
              setPendingGoogleUser(usr || null);
              setShowCompleteProfile(true);
            } else {
              login(usr);
              setSigningIn(true);
              setTimeout(async () => {
                setSigningIn(false);
                const pendingResume = sessionStorage.getItem("acordly_resume_after_login");
                sessionStorage.removeItem("acordly_resume_after_login");
                const hasPendingPlan = !!sessionStorage.getItem("acordly_pending_plan");
                if (hasPendingPlan)   { await triggerPendingCheckout(); }
                else if (pendingResume) { setResumeSessionId(pendingResume); setShowModal(true); }
                else                  { setShowModal(true); }
              }, 80);
            }
          }}
        />
      )}

      {showCompleteProfile && (
        <CompleteProfileModal
          pendingToken={pendingGoogleToken}
          user={user || pendingGoogleUser}
          onComplete={async (u) => {
            login(u);
            setShowCompleteProfile(false);
            setPendingGoogleToken(null);
            setPendingGoogleUser(null);
            const hasPendingPlan = !!sessionStorage.getItem("acordly_pending_plan");
            if (hasPendingPlan) { await triggerPendingCheckout(); } else { setShowModal(true); }
          }}
        />
      )}

      {showUpgradeModal && (
        <UpgradeModal token={token} user={user}
          onClose={() => setShowUpgradeModal(false)}
          onError={(msg) => { setShowUpgradeModal(false); setHeaderError(msg); }}
          openBillingPortal={openBillingPortal}
        />
      )}

      {showSignatureModal && (
        <SignatureModal token={token} existingSignature={savedSignature}
          onClose={() => setShowSignatureModal(false)}
          onSaved={(sig) => { updateSignature(sig); setShowSignatureModal(false); }}
        />
      )}

      {showAccountSettings && user && (
        <AccountSettingsModal
          user={user}
          onClose={() => setShowAccountSettings(false)}
          onUserUpdate={setUser}
          openBillingPortal={openBillingPortal}
        />
      )}

      {showContactModal && user && (
        <ContactModal
          user={user}
          onClose={() => setShowContactModal(false)}
        />
      )}
    </div>
  );
}