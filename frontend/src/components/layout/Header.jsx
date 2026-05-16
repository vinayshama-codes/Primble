import { API_BASE } from "../../config/constants";
import { useState, useRef, useEffect } from "react";

const ChevronDown = ({ rotated }) => (
  <svg width="12" height="12" viewBox="0 0 12 12" fill="none"
    style={{ flexShrink: 0, transition: "transform 0.2s", transform: rotated ? "rotate(180deg)" : "none" }}>
    <path d="M2 4l4 4 4-4" stroke="#94a3b8" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);


const SignOutIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"
    strokeLinecap="round" strokeLinejoin="round">
    <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
    <polyline points="16 17 21 12 16 7" />
    <line x1="21" y1="12" x2="9" y2="12" />
  </svg>
);

const TIER_LABELS = {
  essentials: "Essentials",
  professional: "Professional",
  business: "Business",
  enterprise: "Enterprise",
  free: "Free",
};

function InlinePlanPanel({ user, onChangePlan, onBillingPortal }) {
  const [canceling, setCanceling] = useState(false);
  const [cancelDone, setCancelDone] = useState(false);
  const [cancelError, setCancelError] = useState("");
  const [confirmCancel, setConfirmCancel] = useState(false);

  const tier = user?.subscription_tier || "free";
  const used = user?.packages_used ?? 0;
  const limit = user?.packages_limit ?? 0;
  const tierLabel = TIER_LABELS[tier] || tier;
  const isFree = tier === "free";
  const noPackages = isFree || limit === 0;
  const pct = !noPackages ? Math.min(100, Math.round((used / limit) * 100)) : 0;
  const barColor = pct >= 90 ? "#ef4444" : pct >= 70 ? "#f59e0b" : "#10b981";

  const handleCancel = async () => {
    setCanceling(true); setCancelError("");
    try {
      const res = await fetch(`${API_BASE}/api/stripe/cancel-subscription`, {
        method: "POST", credentials: "include",
      });
      const data = await res.json();
      if (!res.ok) { setCancelError(data.detail || data.message || "Failed to cancel."); return; }
      setCancelDone(true); setConfirmCancel(false);
    } catch { setCancelError("Network error. Please try again."); }
    finally { setCanceling(false); }
  };

  return (
    <div className="udrop-plan-panel">
      {/* Plan name + billing cycle */}
      <div className="udrop-plan-header">
        <span className="udrop-plan-tier">{tierLabel}</span>
        {!isFree && (
          <span className="udrop-plan-cycle">
            {user?.billing_cycle === "annual" ? "Annual" : "Monthly"}
          </span>
        )}
      </div>

      {/* Usage bar */}
      {!noPackages && (
        <div className="udrop-plan-usage">
          <div className="udrop-plan-usage-row">
            <span className="udrop-plan-usage-label">
              {tier === "essentials" ? "Scores Used" : "Packages Used"}
            </span>
            <span className="udrop-plan-usage-count">{used} / {limit}</span>
          </div>
          <div className="udrop-plan-bar-track">
            <div className="udrop-plan-bar-fill" style={{ width: `${pct}%`, background: barColor }} />
          </div>
          {pct >= 90 && (
            <div className="udrop-plan-usage-warn">⚠️ Approaching limit</div>
          )}
        </div>
      )}

      <div className="udrop-plan-divider" />

      {/* Actions */}
      {cancelDone ? (
        <div className="udrop-plan-cancel-done">✓ Subscription will cancel at end of billing period.</div>
      ) : confirmCancel ? (
        <div>
          <div className="udrop-plan-confirm-text">
            Are you sure? You'll keep access until the end of your current billing period.
          </div>
          {cancelError && <div className="udrop-plan-error">{cancelError}</div>}
          <div className="udrop-plan-action-row">
            <button onClick={() => setConfirmCancel(false)} className="udrop-plan-btn udrop-plan-btn--secondary">
              Keep Plan
            </button>
            <button onClick={handleCancel} disabled={canceling} className="udrop-plan-btn udrop-plan-btn--danger">
              {canceling
                ? <><span className="udrop-spinner udrop-spinner--white" />Canceling…</>
                : "Yes, Cancel"}
            </button>
          </div>
        </div>
      ) : (
        <div className="udrop-plan-actions">
          <button onClick={onChangePlan} className="udrop-plan-btn udrop-plan-btn--primary">
            Change Plan
          </button>
          {!isFree && tier !== "enterprise" && !cancelDone && user?.payment_status !== "canceling" && (
            <button onClick={() => setConfirmCancel(true)} className="udrop-plan-btn udrop-plan-btn--secondary">
              Cancel Subscription
            </button>
          )}
          {user?.payment_status === "canceling" && (
            <div className="udrop-plan-canceling-note">Subscription cancels at end of billing period.</div>
          )}
        </div>
      )}
    </div>
  );
}

function UserDropdown({
  user, token,
  savedSignature,
  onSignatureClick,
  onUpgradeClick,
  onLogout,
  openBillingPortal,
  upgradeChecking,
  upgradeFailed,
  setUpgradeFailed,
  setUpgradeChecking,
  setUser,
}) {
  const [open, setOpen] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);
  const [showPlan, setShowPlan] = useState(false);
  const dropdownRef = useRef(null);

  useEffect(() => {
    function handleClickOutside(e) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target)) {
        setOpen(false);
        setShowPlan(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  useEffect(() => { if (!open) setShowPlan(false); }, [open]);

  const handleLogout = async () => {
    if (loggingOut) return;
    setLoggingOut(true);
    await new Promise(r => setTimeout(r, 60));
    onLogout();
  };

  const initials = user.email ? user.email[0].toUpperCase() : "U";

  const billingPortalLoading = false;
  const BillingSpinner = () => (
    <span className="udrop-spinner" />
  );

  const statusBadge = (() => {
    if (upgradeChecking) return (
      <div className="udrop-status udrop-status--warning">⏳ Activating plan…</div>
    );
    if (upgradeFailed) return (
      <div className="udrop-status udrop-status--error">
        ⚠️ Activation pending
        <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
          <button className="udrop-link" onClick={() => {
            setUpgradeFailed(false);
            setUpgradeChecking(true);
            fetch(`${API_BASE}/api/stripe/verify-upgrade`, { method: "POST", credentials: "include" })
              .then(r => r.ok ? r.json() : null)
              .then(data => {
                if (data?.subscription_tier && data.subscription_tier !== "free") {
                  fetch(`${API_BASE}/api/auth/me`, { credentials: "include" })
                    .then(r => r.ok ? r.json() : null)
                    .then(me => { if (me) setUser(me); });
                  setUpgradeChecking(false);
                } else { setUpgradeFailed(true); setUpgradeChecking(false); }
              })
              .catch(() => { setUpgradeFailed(true); setUpgradeChecking(false); });
          }}>Retry</button>
          <a href="mailto:support@primble.ai" className="udrop-link">Contact support</a>
        </div>
      </div>
    );
    if (user.payment_status === "archived") return (
      <div className="udrop-status udrop-status--muted">
        🗄️ Account archived — <a href="mailto:support@primble.ai" className="udrop-link">Contact support</a>
      </div>
    );
    if (user.payment_status === "suspended") return (
      <div className="udrop-status udrop-status--error">
        🚫 Account suspended —{" "}
        <button onClick={openBillingPortal} disabled={billingPortalLoading} className="udrop-link">
          {billingPortalLoading && <BillingSpinner />}Restore billing
        </button>
      </div>
    );
    if (user.payment_status === "soft_locked") return (
      <div className="udrop-status udrop-status--warning">
        🔒 Account disabled — please{" "}
        <button onClick={openBillingPortal} disabled={billingPortalLoading} className="udrop-link">
          {billingPortalLoading && <BillingSpinner />}update billing
        </button>
      </div>
    );
    if (user.payment_status === "failed") {
      const daysOverdue = user.payment_failed_at
        ? Math.floor((Date.now() - new Date(user.payment_failed_at).getTime()) / 86400000)
        : 0;
      return (
        <div className={`udrop-status ${daysOverdue >= 7 ? "udrop-status--error" : "udrop-status--warning"}`}>
          {daysOverdue >= 7 ? "🚨 Payment still overdue — account will be restricted soon." : "⚠️ Payment overdue —"}{" "}
          <button onClick={openBillingPortal} disabled={billingPortalLoading} className="udrop-link">
            {billingPortalLoading && <BillingSpinner />}{daysOverdue >= 7 ? "Update billing now" : "Update billing"}
          </button>
        </div>
      );
    }
    return null;
  })();

  return (
    <div className="udrop-root" ref={dropdownRef}>
      {/* Trigger pill */}
      <button className="udrop-trigger" onClick={() => setOpen(p => !p)}>
        <span className="udrop-avatar">{initials}</span>
        <span className="udrop-trigger-text">
          <span className="udrop-trigger-initial">{initials}</span>
          <span className="udrop-email-preview">{user.email}</span>
        </span>
        <ChevronDown rotated={open} />
      </button>

      {open && (
        <div className="udrop-panel">

          {/* ── Header: avatar + email ── */}
          <div className="udrop-header">
            <span className="udrop-avatar udrop-avatar--lg">{initials}</span>
            <div className="udrop-header-info">
              <span className="udrop-header-initial">{initials}</span>
              <span className="udrop-header-email">{user.email}</span>
            </div>
          </div>

          {statusBadge && <div className="udrop-section">{statusBadge}</div>}

          <div className="udrop-divider" />

          {/* ── Actions ── */}
          <div className="udrop-section udrop-actions">

            {/* Signature */}
            <button
              className="udrop-item"
              onClick={() => { setOpen(false); onSignatureClick(); }}
            >
              <span className="udrop-item-icon">✍️</span>
              <span className="udrop-item-label">{savedSignature ? "Manage Signature" : "Add Signature"}</span>
            </button>

            {/* Plan */}
            {user.subscription_tier === "free" ? (
              <button
                className="udrop-item udrop-item--upgrade"
                onClick={() => { setOpen(false); onUpgradeClick(); }}
              >
                <span className="udrop-item-icon">⭐</span>
                <span className="udrop-item-label">Select Plan</span>
              </button>
            ) : (
              <>
                <button
                  className={`udrop-item udrop-item--submenu ${showPlan ? "udrop-item--active" : ""}`}
                  onClick={() => setShowPlan(p => !p)}
                >
                  <span className="udrop-item-icon">✅</span>
                  <span className="udrop-item-label">My Plan</span>
                  <ChevronDown rotated={showPlan} />
                </button>

                {/* Inline accordion expansion */}
                {showPlan && (
                  <InlinePlanPanel
                    user={user}
                    onChangePlan={() => { setShowPlan(false); setOpen(false); onUpgradeClick(); }}
                    onBillingPortal={openBillingPortal}
                  />
                )}
              </>
            )}
          </div>

          <div className="udrop-divider" />

          {/* ── Sign out ── */}
          <div className="udrop-section">
            <button
              className="udrop-item udrop-item--danger"
              onClick={handleLogout}
              disabled={loggingOut}
            >
              {loggingOut ? (
                <>
                  <span className="udrop-item-icon" style={{ display: "flex", alignItems: "center" }}>
                    <span style={{ width: 14, height: 14, border: "2px solid #dc2626", borderTopColor: "transparent", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" }} />
                  </span>
                  <span className="udrop-item-label">Signing out…</span>
                </>
              ) : (
                <>
                  <span className="udrop-item-icon" style={{ display: "flex", alignItems: "center" }}><SignOutIcon /></span>
                  <span className="udrop-item-label">Sign Out</span>
                </>
              )}
            </button>
          </div>

        </div>
      )}
    </div>
  );
}

export default function Header({
  user, savedSignature, token,
  onSignatureClick, onUpgradeClick, onLogout, onHome, onSignUp, onLogIn,
  openBillingPortal, upgradeChecking, upgradeFailed,
  setUpgradeFailed, setUpgradeChecking, setUser,
  onNavigate,
}) {
  return (
    <header className="landing-header">
      <div className="header-left">
        <div className="logo" onClick={() => onHome ? onHome() : (window.location.href = "/")} style={{ cursor: "pointer" }}>
          <img src="/primble-logo.webp" alt="Primble" style={{ height: "28px", width: "auto", display: "block" }} />
        </div>
        <nav className="nav" style={{ display: "none" }}>
          <a onClick={() => onNavigate && onNavigate("about")} style={{ cursor: "pointer" }}>About</a>
          <a onClick={() => onNavigate && onNavigate("platform")} style={{ cursor: "pointer" }}>Platform</a>
          <a onClick={() => onNavigate && onNavigate("pricing")} style={{ cursor: "pointer" }}>Pricing</a>
          <a onClick={() => onNavigate && onNavigate("acord-license")} style={{ cursor: "pointer" }}>ACORD License</a>
        </nav>
      </div>

      {user ? (
        <UserDropdown
          user={user}
          token={token}
          savedSignature={savedSignature}
          onSignatureClick={onSignatureClick}
          onUpgradeClick={onUpgradeClick}
          onLogout={onLogout}
          openBillingPortal={openBillingPortal}
          upgradeChecking={upgradeChecking}
          upgradeFailed={upgradeFailed}
          setUpgradeFailed={setUpgradeFailed}
          setUpgradeChecking={setUpgradeChecking}
          setUser={setUser}
        />
      ) : (
        <div className="user-menu" style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <button className="header-btn-login" onClick={onLogIn} style={{ background: "none", border: "1.5px solid #e0e0e0", cursor: "pointer", fontSize: 15, fontWeight: 600, color: "#0f172a", padding: "9px 22px", borderRadius: 999, transition: "all 0.2s" }} onMouseEnter={e => { e.currentTarget.style.borderColor = "#E61B84"; e.currentTarget.style.color = "#E61B84"; }} onMouseLeave={e => { e.currentTarget.style.borderColor = "#e0e0e0"; e.currentTarget.style.color = "#0f172a"; }}>Log in</button>
          <button className="header-btn-signup" onClick={onSignUp} style={{ background: "#E61B84", border: "none", cursor: "pointer", fontSize: 15, fontWeight: 600, color: "#fff", padding: "10px 26px", borderRadius: 999, boxShadow: "0 4px 14px rgba(230,27,132,0.3)", transition: "all 0.2s" }} onMouseEnter={e => { e.currentTarget.style.background = "#C0157A"; e.currentTarget.style.transform = "translateY(-1px)"; }} onMouseLeave={e => { e.currentTarget.style.background = "#E61B84"; e.currentTarget.style.transform = "none"; }}>Upgrade</button>
        </div>
      )}
    </header>
  );
}
