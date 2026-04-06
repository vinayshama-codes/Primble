import { API_BASE } from "../../config/constants";

export default function Header({
  user, savedSignature, token,
  onSignatureClick, onUpgradeClick, onLogout,
  openBillingPortal, upgradeChecking, upgradeFailed,
  setUpgradeFailed, setUpgradeChecking, setUser,
}) {
  const BillingSpinner = () => (
    <span style={{ width: 12, height: 12, border: "2px solid currentColor", borderTopColor: "transparent", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite", marginRight: 4 }} />
  );

  const billingPortalLoading = false;

  return (
    <header className="landing-header">
      <div className="header-left">
        <div className="logo">acordly</div>
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
              🔒 Account Disabled —&nbsp;
              <button onClick={openBillingPortal} disabled={billingPortalLoading} style={{ color: "#fcd34d", fontWeight: 700, background: "none", border: "none", cursor: billingPortalLoading ? "wait" : "pointer", padding: 0, textDecoration: "underline", display: "flex", alignItems: "center", gap: 4 }}>
                {billingPortalLoading && <BillingSpinner />}Update Billing
              </button>
            </span>
          ) : user.payment_status === "failed" ? (
            <span style={{ display: "flex", alignItems: "center", gap: 6, background: "#fef2f2", color: "#991b1b", fontSize: 13, fontWeight: 600, padding: "4px 10px", borderRadius: 6, border: "1px solid #fca5a5" }}>
              ⚠️ Payment overdue —&nbsp;
              <button onClick={openBillingPortal} disabled={billingPortalLoading} style={{ color: "#991b1b", fontWeight: 700, background: "none", border: "none", cursor: billingPortalLoading ? "wait" : "pointer", padding: 0, textDecoration: "underline", display: "flex", alignItems: "center", gap: 4 }}>
                {billingPortalLoading && <BillingSpinner />}Update billing
              </button>
            </span>
          ) : user.subscription_tier === "free" ? (
            <button className="btn-upgrade-header" onClick={onUpgradeClick}>⭐ Upgrade</button>
          ) : (
            <span className="pro-badge">
              ✅ {user.subscription_tier === "essentials" ? "Essentials"
                 : user.subscription_tier === "professional" ? "Professional"
                 : user.subscription_tier === "enterprise" ? "Enterprise"
                 : "Pro"}
            </span>
          )}
          <button className="btn-dark" onClick={onLogout}>Sign Out</button>
        </div>
      ) : null}
    </header>
  );
}