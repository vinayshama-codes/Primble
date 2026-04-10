import { API_BASE } from "../../config/constants";
import { useState, useRef } from "react";
import PlanModal from "../billing/PlanModal";

function LogoutButton({ onLogout }) {
  const [loggingOut, setLoggingOut] = useState(false);
  const handleClick = async () => {
    if (loggingOut) return;
    setLoggingOut(true);
    await new Promise(r => setTimeout(r, 60));
    onLogout();
  };
  return loggingOut ? (
    <div style={{ display: "flex", alignItems: "center", gap: 7, padding: "8px 18px", borderRadius: 999, background: "#0b0b0b", color: "#fff", fontSize: 14, fontWeight: 600, minWidth: 110, justifyContent: "center" }}>
      <span style={{ width: 13, height: 13, border: "2px solid rgba(255,255,255,0.3)", borderTopColor: "#fff", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" }} />
      Logging out…
    </div>
  ) : (
    <button className="btn-dark" onClick={handleClick}>Sign Out</button>
  );
}

export default function Header({
  user, savedSignature, token,
  onSignatureClick, onUpgradeClick, onLogout, onHome, onSignUp, onLogIn,
  openBillingPortal, upgradeChecking, upgradeFailed,
  setUpgradeFailed, setUpgradeChecking, setUser,
}) {
  const [showPlanModal, setShowPlanModal] = useState(false);
  const planBtnRef = useRef(null);

  const BillingSpinner = () => (
    <span style={{ width: 12, height: 12, border: "2px solid currentColor", borderTopColor: "transparent", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite", marginRight: 4 }} />
  );

  const billingPortalLoading = false;

  return (
    <header className="landing-header">
      <div className="header-left">
        <div className="logo" onClick={() => onHome ? onHome() : (window.location.href = "/")} style={{ cursor: "pointer" }}>acordly</div>
        <nav className="nav">
          <a href="#about">About</a>
          <a href="#platform">Platform</a>
          <a href="#pricing">Pricing</a>
          <a href="#acord">ACORD®</a>
        </nav>
      </div>

      {user ? (
        <div className="user-menu">
          <span className="user-email">{user.email}</span>

          <button
            className="btn-signature-header"
            onClick={onSignatureClick}
            title={savedSignature ? "Manage your saved signature" : "Set up your signature"}
          >
            {savedSignature ? "✍️ Signature" : "✍️ Add Signature"}
          </button>

          {upgradeChecking ? (
            <span className="upgrade-checking">⏳ Activating plan...</span>
          ) : upgradeFailed ? (
            <span className="upgrade-failed" title="Payment received but activation pending. Click to retry.">
              ⚠️ Activation pending
              <button
                className="btn-retry-upgrade"
                onClick={() => {
                  setUpgradeFailed(false);
                  setUpgradeChecking(true);
                  fetch(`${API_BASE}/api/stripe/verify-upgrade`, { method: "POST", headers: { Authorization: `Bearer ${token}` } })
                    .then((r) => (r.ok ? r.json() : null))
                    .then((data) => {
                      if (data && data.subscription_tier && data.subscription_tier !== "free") {
                        fetch(`${API_BASE}/api/auth/me`, { headers: { Authorization: `Bearer ${token}` } })
                          .then((r) => (r.ok ? r.json() : null))
                          .then((me) => { if (me) setUser(me); });
                        setUpgradeChecking(false);
                      } else { setUpgradeFailed(true); setUpgradeChecking(false); }
                    })
                    .catch(() => { setUpgradeFailed(true); setUpgradeChecking(false); });
                }}
              >Retry</button>
              <a href="mailto:support@acordly.ai" className="upgrade-support-link">Contact support</a>
            </span>
          ) : user.payment_status === "archived" ? (
            <span style={{ display: "flex", alignItems: "center", gap: 6, background: "#f1f5f9", color: "#64748b", fontSize: 13, fontWeight: 600, padding: "4px 10px", borderRadius: 6, border: "1px solid #cbd5e1" }}>
              🗄️ Account archived —&nbsp;<a href="mailto:support@acordly.ai" style={{ color: "#64748b", fontWeight: 700 }}>Contact support</a>
            </span>
          ) : user.payment_status === "suspended" ? (
            <span style={{ display: "flex", alignItems: "center", gap: 6, background: "#7f1d1d", color: "#fca5a5", fontSize: 13, fontWeight: 600, padding: "4px 10px", borderRadius: 6, border: "1px solid #991b1b" }}>
              🚫 Account suspended —&nbsp;
              <button onClick={openBillingPortal} disabled={billingPortalLoading} style={{ color: "#fca5a5", fontWeight: 700, background: "none", border: "none", cursor: billingPortalLoading ? "wait" : "pointer", padding: 0, textDecoration: "underline", display: "flex", alignItems: "center", gap: 4 }}>
                {billingPortalLoading && <BillingSpinner />}Restore billing
              </button>
            </span>
          ) : user.payment_status === "soft_locked" ? (
            <span style={{ display: "flex", alignItems: "center", gap: 6, background: "#78350f", color: "#fcd34d", fontSize: 13, fontWeight: 600, padding: "4px 10px", borderRadius: 6, border: "1px solid #92400e" }}>
              🔒 Account Disabled — Please&nbsp;
              <button onClick={openBillingPortal} disabled={billingPortalLoading} style={{ color: "#fcd34d", fontWeight: 700, background: "none", border: "none", cursor: billingPortalLoading ? "wait" : "pointer", padding: 0, textDecoration: "underline", display: "flex", alignItems: "center", gap: 4 }}>
                {billingPortalLoading && <BillingSpinner />}update your billing
              </button>
              &nbsp;to restore access.
            </span>
          ) : user.payment_status === "failed" ? (
            user.payment_failed_at && Math.floor((Date.now() - new Date(user.payment_failed_at).getTime()) / 86400000) >= 7 ? (
              <span style={{ display: "flex", alignItems: "center", gap: 5, background: "#7f1d1d", color: "#fca5a5", fontSize: 11, fontWeight: 700, padding: "3px 8px", borderRadius: 6, border: "1px solid #991b1b", whiteSpace: "nowrap" }}>
                🚨 Payment still overdue — account will be restricted soon.&nbsp;
                <button onClick={openBillingPortal} disabled={billingPortalLoading} style={{ color: "#fca5a5", fontWeight: 700, background: "none", border: "none", cursor: billingPortalLoading ? "wait" : "pointer", padding: 0, textDecoration: "underline", display: "flex", alignItems: "center", gap: 4, fontSize: 11 }}>
                  {billingPortalLoading && <BillingSpinner />}Update billing now
                </button>
              </span>
            ) : (
              <span style={{ display: "flex", alignItems: "center", gap: 6, background: "#fef2f2", color: "#991b1b", fontSize: 13, fontWeight: 600, padding: "4px 10px", borderRadius: 6, border: "1px solid #fca5a5" }}>
                ⚠️ Payment overdue —&nbsp;
                <button onClick={openBillingPortal} disabled={billingPortalLoading} style={{ color: "#991b1b", fontWeight: 700, background: "none", border: "none", cursor: billingPortalLoading ? "wait" : "pointer", padding: 0, textDecoration: "underline", display: "flex", alignItems: "center", gap: 4 }}>
                  {billingPortalLoading && <BillingSpinner />}Update billing
                </button>
              </span>
            )
          ) : user.subscription_tier === "free" ? (
            <button className="btn-upgrade-header" onClick={onUpgradeClick}>⭐ Upgrade</button>
          ) : (
            <div style={{ position: "relative" }}>
              <button
                ref={planBtnRef}
                onClick={() => setShowPlanModal(p => !p)}
                style={{ padding: "7px 14px", borderRadius: 8, border: "1px solid #e2e8f0", background: "#fff", fontSize: 13, fontWeight: 700, color: "#0f172a", cursor: "pointer", display: "flex", alignItems: "center", gap: 6 }}
              >
                ✅ My Plan
              </button>
              {showPlanModal && (
                <PlanModal
                  user={user}
                  token={token}
                  onClose={() => setShowPlanModal(false)}
                  onChangePlan={onUpgradeClick}
                  anchorRef={planBtnRef}
                />
              )}
            </div>
          )}
          <LogoutButton onLogout={onLogout} />
        </div>
      ) : (
        <div className="user-menu" style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <button onClick={onSignUp} style={{ background: "none", border: "none", cursor: "pointer", fontSize: 16, fontWeight: 600, color: "#0f172a", padding: "10px 18px" }}>Sign up</button>
          <button onClick={onLogIn} style={{ background: "#e6007a", border: "none", cursor: "pointer", fontSize: 16, fontWeight: 600, color: "#fff", padding: "10px 26px", borderRadius: 999 }}>Log in</button>
        </div>
      )}
    </header>
  );
}