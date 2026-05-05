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

export default function App() {
  const path = window.location.pathname;

  const qMatch = path.match(/^\/(?:client-)?questionnaire\/([^/]+)$/);
  if (qMatch) {
    return <ErrorBoundary><ClientQuestionnaire token={qMatch[1]} /></ErrorBoundary>;
  }

  return (
    <ErrorBoundary>
      <GoogleOAuthProvider clientId={GOOGLE_CLIENT_ID}>
        <AppContent />
      </GoogleOAuthProvider>
    </ErrorBoundary>
  );
}

function MarketingFooter() {
  return (
    <footer className="footer">
      <div><h4 className="footer-h4">About Us</h4><p className="footer-p">Acordly automates ACORD form processing for insurance brokers and underwriting teams.</p></div>
      <div><h4 className="footer-h4">Contact Us</h4><p className="footer-p">support@acordly.ai</p></div>
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
  const [showUpgradeModal,    setShowUpgradeModal]    = useState(false);
  const [showSignatureModal,  setShowSignatureModal]  = useState(false);
  const [signingIn,           setSigningIn]           = useState(false);
  const [headerError,         setHeaderError]         = useState("");
  const [resumeSessionId,     setResumeSessionId]     = useState(null);
  const [upgradeChecking,     setUpgradeChecking]     = useState(false);
  const [upgradeFailed,       setUpgradeFailed]       = useState(false);
  const [overageToast,        setOverageToast]        = useState(null);
  const [marketingPage,       setMarketingPage]       = useState(null);

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
      const res  = await fetch(`${API_BASE}/api/stripe/create-portal-session`, { method: "POST", credentials: "include" });
      const data = await res.json();
      if (data.url) { window.location.href = data.url; }
      else { setUpgradeChecking(false); setHeaderError(data.detail || "Could not open billing portal."); }
    } catch { setUpgradeChecking(false); setHeaderError("Network error. Please try again."); }
  };

  const handleGetStarted = (planId, billingCycle) => {
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
      setShowAuthModal(true);
    }
  };

  const triggerPendingCheckout = async () => {
    const planId       = sessionStorage.getItem("acordly_pending_plan");
    const billingCycle = sessionStorage.getItem("acordly_pending_billing_cycle") || "monthly";
    if (!planId) return false;
    sessionStorage.removeItem("acordly_pending_plan");
    sessionStorage.removeItem("acordly_pending_billing_cycle");
    setUpgradeChecking(true);
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
      setUpgradeChecking(false);
      setHeaderError(data.detail || "Failed to start checkout. Please try again.");
    } catch {
      setUpgradeChecking(false);
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

      {resumeLoading && (
        <div style={{ position: "fixed", inset: 0, background: "#fff", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", zIndex: 9999 }}>
          <div className="loading-spinner" style={{ width: 40, height: 40, marginBottom: 16 }} />
          <p style={{ color: "#64748b", fontSize: 15, fontWeight: 500 }}>Restoring your session...</p>
        </div>
      )}

      {signingIn && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(255,255,255,0.97)", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", zIndex: 9999 }}>
          <div className="loading-spinner" style={{ width: 40, height: 40, marginBottom: 16 }} />
          <p style={{ color: "#64748b", fontSize: "15px", fontWeight: 500 }}>Signing you in...</p>
        </div>
      )}

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
      />
      {headerError && (
        <div className="header-error-bar">⚠️ {headerError}<button onClick={() => setHeaderError("")}>✕</button></div>
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
        <><PricingPage onGetStarted={handleGetStarted} onNavigate={handleNavigate} token={token} user={user} onError={(msg) => setHeaderError(msg)} /><MarketingFooter /></>
      ) : marketingPage === "acord-license" ? (
        <><AcordLicensePage /><MarketingFooter /></>
      ) : (
        <LandingPage user={user} onGetStarted={handleGetStarted} />
      )}

      {showAuthModal && (
        <AuthModal
          initialMode={authModalMode}
          onClose={() => setShowAuthModal(false)}
          onSuccess={(usr, profileIncomplete) => {
            login(usr);
            setShowAuthModal(false);
            setSigningIn(true);
            setTimeout(async () => {
              setSigningIn(false);
              const pendingResume = sessionStorage.getItem("acordly_resume_after_login");
              sessionStorage.removeItem("acordly_resume_after_login");
              const hasPendingPlan = !!sessionStorage.getItem("acordly_pending_plan");
              if (profileIncomplete)       { setShowCompleteProfile(true); }
              else if (hasPendingPlan)     { await triggerPendingCheckout(); }
              else if (pendingResume)      { setResumeSessionId(pendingResume); setShowModal(true); }
              else                         { setShowModal(true); }
            }, 80);
          }}
        />
      )}

      {showCompleteProfile && user && (
        <CompleteProfileModal token={token} user={user}
          onComplete={async (u) => {
            setUser(u); setShowCompleteProfile(false);
            const hasPendingPlan = !!sessionStorage.getItem("acordly_pending_plan");
            if (hasPendingPlan) { await triggerPendingCheckout(); } else { setShowModal(true); }
          }}
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