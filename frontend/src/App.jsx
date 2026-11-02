import { useState, useEffect, useRef } from "react";
import "./App.css";
import "./styles/injected.js";
import { GoogleOAuthProvider } from "@react-oauth/google";

import { GOOGLE_CLIENT_ID, API_BASE, PRIVACY_POLICY_URL, TERMS_OF_SERVICE_URL } from "./config/constants";
import AnnouncementBar from "./components/layout/AnnouncementBar";
import { useAuth }            from "./hooks/useAuth";
import { useSignature }       from "./hooks/useSignature";
import { useUpgradePolling, useBillingReturnPolling } from "./hooks/useUpgradePolling";
import { useToasts }         from "./hooks/useToasts";
import { usePageRestore }    from "./hooks/usePageRestore";
import { startCheckout }      from "./api/stripeApi";
import { hasPaidPlan, apiErrorMessage, needsBillingFix, OPEN_BILLING_PARAM, OPEN_BILLING_KEY } from "./utils/billing";

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
import ActivityLogModal       from "./components/account/ActivityLogModal";
import AdminResetLicenseModal from "./components/account/AdminResetLicenseModal";
import AdminAuditExportModal  from "./components/account/AdminAuditExportModal";
import AdminManageAdminsModal from "./components/account/AdminManageAdminsModal";
import { checkAdmin }         from "./api/adminApi";

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
      <div><h4 className="footer-h4">Contact Us</h4><p className="footer-p">support@primble.ai</p>
        <p className="footer-p">
          <a href={PRIVACY_POLICY_URL} target="_blank" rel="noopener noreferrer">Privacy Policy</a>
          <a href={TERMS_OF_SERVICE_URL} target="_blank" rel="noopener noreferrer">Terms of Service</a>
        </p>
      </div>
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
  const { user, setUser, token, authLoading, login, logout } = useAuth();
  const { savedSignature, updateSignature }      = useSignature(token, user);

  const _resumeFromUrl = () => {
    const p = new URLSearchParams(window.location.search);
    return p.get("resume_session") || null;
  };

  const _hasResume = !!new URLSearchParams(window.location.search).get("resume_session");
  const [showModal,           setShowModal]           = useState(false);
  const [modalStep,           setModalStep]           = useState(null);
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
  const [showActivityLog,     setShowActivityLog]     = useState(false);
  const [showResetLicense,    setShowResetLicense]    = useState(false);
  const [showAuditExport,     setShowAuditExport]     = useState(false);
  const [showManageAdmins,    setShowManageAdmins]    = useState(false);
  const [isAdmin,             setIsAdmin]             = useState(false);
  const [signingIn,           setSigningIn]           = useState(false);
  const [headerError,         setHeaderError]         = useState("");
  const [resumeSessionId,     setResumeSessionId]     = useState(null);
  const [upgradeChecking,     setUpgradeChecking]     = useState(false);
  const [upgradeFailed,       setUpgradeFailed]       = useState(false);
  // UI-10: same door as AcordModal's job toasts. This one had the MIRROR
  // defect - it auto-dismissed at 8s but had no close button, and its bare
  // setTimeout was never cleared, so it fired setState into an unmounted
  // component if the user navigated away first.
  const { toasts: overageToasts, dismiss: dismissOverageToast } = useToasts();
  const [marketingPage,       setMarketingPage]       = useState(null);
  const [portalRedirecting,   setPortalRedirecting]   = useState(false);
  const acordModalRef = useRef(null);

  // Back from Stripe (checkout or billing portal) restores the page frozen with
  // the full-screen "Redirecting to Stripe…" overlay still up - take it down.
  usePageRestore(() => setPortalRedirecting(false));

  // Detect platform-admin (email in ADMIN_EMAILS) to gate admin-only UI.
  // Server-side _require_admin is the real gate; this only shows/hides controls.
  useEffect(() => {
    if (!user) { setIsAdmin(false); return; }
    let alive = true;
    checkAdmin().then((ok) => { if (alive) setIsAdmin(ok); });
    return () => { alive = false; };
  }, [user?.id]);

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

  // The extra-package checkout and its return handler were retired on 2 Nov 2026
  // (the endpoints are gone); overage is billed on the next invoice.

  const openBillingPortal = async () => {
    setPortalRedirecting(true);
    try {
      const res  = await fetch(`${API_BASE}/api/stripe/create-portal-session`, { method: "POST", credentials: "include" });
      const data = await res.json().catch(() => ({}));
      if (res.ok && data.url) { window.location.href = data.url; return; }
      // e.g. 400 no_billing_account: "There's no billing account to manage yet."
      setPortalRedirecting(false);
      setHeaderError(apiErrorMessage(data, "Could not open billing portal."));
    } catch { setPortalRedirecting(false); setHeaderError("Network error. Please try again."); }
  };

  // Billing e-mails link to /?open=billing (2 Nov 2026): open Manage billing once.
  // Signed out, the intent waits through sign-in (sessionStorage, and memory when
  // storage is blocked); closing the sign-in window drops it. It is cleared BEFORE
  // the portal opens, so a failure (no billing account yet) never loops.
  const [billingIntent, setBillingIntent] = useState(() => {
    let wanted = false;
    try {
      const url = new URL(window.location.href);
      if (url.searchParams.get("open") === OPEN_BILLING_PARAM) {
        wanted = true;
        url.searchParams.delete("open");
        window.history.replaceState(window.history.state, "", `${url.pathname}${url.search}${url.hash}`);
      }
    } catch { /* an unreadable URL carries no intent */ }
    try {
      if (wanted) sessionStorage.setItem(OPEN_BILLING_KEY, "1");
      else wanted = sessionStorage.getItem(OPEN_BILLING_KEY) === "1";
    } catch { /* storage blocked: the in-memory flag still carries this load */ }
    return wanted;
  });
  const billingOpenedRef     = useRef(false);
  const billingSignInAskedRef = useRef(false);
  const dropBillingIntent = () => {
    try { sessionStorage.removeItem(OPEN_BILLING_KEY); } catch { /* storage blocked */ }
    setBillingIntent(false);
  };

  useEffect(() => {
    if (!billingIntent || authLoading) return;
    if (!user) {
      if (!billingSignInAskedRef.current) {
        billingSignInAskedRef.current = true;
        setAuthModalMode("signin");
        setShowAuthModal(true);
      }
      return;
    }
    if (billingOpenedRef.current) return;
    billingOpenedRef.current = true;
    dropBillingIntent();
    openBillingPortal();
  }, [billingIntent, authLoading, user]);

  const handleGetStarted = (planId, billingCycle, authMode) => {
    if (planId) {
      sessionStorage.setItem("acordly_pending_plan", planId);
      sessionStorage.setItem("acordly_pending_billing_cycle", billingCycle || "monthly");
    }
    setMarketingPage(null);
    if (user) {
      if (planId) {
        triggerPendingCheckout(user);
      } else {
        setShowModal(true);
        window.history.pushState({ acordly: true }, "");
      }
    } else {
      setAuthModalMode(authMode === "signup" ? "signup" : "signin");
      setShowAuthModal(true);
    }
  };

  // `forUser` is the account that just signed in (or the signed-in one): the
  // state `user` is not updated yet inside the sign-in callbacks.
  const triggerPendingCheckout = async (forUser) => {
    const planId       = sessionStorage.getItem("acordly_pending_plan");
    const billingCycle = sessionStorage.getItem("acordly_pending_billing_cycle") || "monthly";
    if (!planId) return false;
    sessionStorage.removeItem("acordly_pending_plan");
    sessionStorage.removeItem("acordly_pending_billing_cycle");
    // A paying user never starts a second subscription (2 Nov 2026): show their
    // plan and how to change it instead.
    if (hasPaidPlan(forUser)) { setShowUpgradeModal(true); return false; }
    setPortalRedirecting(true);
    const result = await startCheckout(planId, billingCycle);
    if (result.url) { window.location.href = result.url; return true; }
    setPortalRedirecting(false);
    // 409 payment_due is fixed in Manage billing, so that one offers it.
    setHeaderError(needsBillingFix(result.code) ? { message: result.message, billing: true } : result.message);
    window.scrollTo({ top: 0, behavior: "smooth" });   // the bar sits under the header
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
      {/* Live region stays mounted even when empty: a screen reader only reliably
          announces additions to a region that was already in the DOM. */}
      <div
          role="status"
          aria-live="polite"
          aria-atomic="false"
          style={{
            position: "fixed",
            // Pinned edges instead of `left: 50%` + translate: the old pill could
            // not shrink, so a long message overhung the viewport on a phone.
            left: "max(16px, env(safe-area-inset-left))",
            right: "max(16px, env(safe-area-inset-right))",
            bottom: "calc(max(24px, env(safe-area-inset-bottom)) + var(--rr-footer-h, 0px))",
            zIndex: 9999,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            gap: 10,
            pointerEvents: "none",
          }}>
          {overageToasts.map(t => (
            <div key={t.id}
              onClick={() => dismissOverageToast(t.id)}
              style={{
                pointerEvents: "auto",
                position: "relative",
                maxWidth: "min(420px, 100%)",
                background: "#10b981",
                color: "#fff",
                padding: "12px 40px",
                borderRadius: 10,
                fontWeight: 600,
                fontSize: 14,
                textAlign: "center",
                boxShadow: "0 4px 20px rgba(0,0,0,0.18)",
                cursor: "pointer",
                WebkitTapHighlightColor: "transparent",
                touchAction: "manipulation",
              }}>
              {t.body}
              <button
                type="button"
                aria-label="Dismiss notification"
                onClick={(e) => { e.stopPropagation(); dismissOverageToast(t.id); }}
                style={{
                  position: "absolute",
                  top: "50%",
                  right: 6,
                  transform: "translateY(-50%)",
                  width: 30,
                  height: 30,
                  border: "none",
                  borderRadius: "50%",
                  background: "transparent",
                  color: "#fff",
                  fontSize: 16,
                  lineHeight: "20px",
                  cursor: "pointer",
                  padding: 0,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  WebkitTapHighlightColor: "transparent",
                  touchAction: "manipulation",
                }}>×</button>
            </div>
          ))}
      </div>

      {upgradeChecking && <UpgradeStageOverlay />}

      {portalRedirecting && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(255,255,255,0.97)", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", zIndex: 9999 }}>
          <div className="loading-spinner" style={{ width: 40, height: 40, marginBottom: 16 }} />
          <p style={{ color: "#64748b", fontSize: 15, fontWeight: 500 }}>Redirecting to Stripe…</p>
        </div>
      )}

      {resumeLoading && <AppLoadingOverlay label="Restoring your session..." />}

      {signingIn && <AppLoadingOverlay label="Signing you in..." />}

      {/* The public pages and the dashboard only - never over the package work. */}
      {(!(showModal && user) || modalStep === "dashboard") && <AnnouncementBar />}

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
        onActivityLog={() => setShowActivityLog(true)}
        isAdmin={isAdmin}
        onResetLicense={() => setShowResetLicense(true)}
        onAuditExport={() => setShowAuditExport(true)}
        onManageAdmins={() => setShowManageAdmins(true)}
        onDashboard={user ? () => {
          if (acordModalRef.current) {
            acordModalRef.current.goToDashboard();
          } else {
            setShowModal(true);
          }
        } : undefined}
      />
      {headerError && (
        <div className="header-error-bar">
          <span>
            {typeof headerError === "string" ? headerError : headerError.message}
            {headerError.billing && (
              <>
                {" "}
                <button type="button" onClick={() => { setHeaderError(""); openBillingPortal(); }}
                  style={{ fontSize: 13, fontWeight: 700, textDecoration: "underline", padding: 0 }}>
                  Manage billing
                </button>
              </>
            )}
          </span>
          <button onClick={() => setHeaderError("")}>✕</button>
        </div>
      )}

      {/* Page content — switches between landing, marketing pages, and app */}
      {showModal && user ? (
        <AcordModal
          ref={acordModalRef}
          onStepChange={setModalStep}
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
          onClose={() => { setShowAuthModal(false); if (billingIntent) dropBillingIntent(); }}
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
                if (hasPendingPlan)   { await triggerPendingCheckout(usr); }
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
            if (hasPendingPlan) { await triggerPendingCheckout(u); } else { setShowModal(true); }
          }}
        />
      )}

      {showUpgradeModal && (
        <UpgradeModal user={user}
          onClose={() => setShowUpgradeModal(false)}
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

      {showActivityLog && user && (
        <ActivityLogModal
          onClose={() => setShowActivityLog(false)}
        />
      )}

      {showResetLicense && user && isAdmin && (
        <AdminResetLicenseModal
          onClose={() => setShowResetLicense(false)}
        />
      )}

      {showAuditExport && user && isAdmin && (
        <AdminAuditExportModal
          onClose={() => setShowAuditExport(false)}
        />
      )}

      {showManageAdmins && user && isAdmin && (
        <AdminManageAdminsModal
          onClose={() => setShowManageAdmins(false)}
        />
      )}
    </div>
  );
}