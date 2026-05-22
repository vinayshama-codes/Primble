import { useState } from "react";
import { API_BASE } from "../../config/constants";
import { PLANS } from "../billing/plans";
import ContactModal from "../account/ContactModal";

const PLAN_ORDER = ["essentials", "professional", "business", "enterprise"];

export default function PricingPage({ onGetStarted, token, user, onError, openBillingPortal }) {
  const [annual, setAnnual]           = useState(false);
  const [loadingPlan, setLoadingPlan] = useState(null);
  const [portalLoading, setPortalLoading] = useState(false);
  const [showContactSales, setShowContactSales] = useState(false);

  const handleManageBilling = async () => {
    if (!openBillingPortal) return;
    setPortalLoading(true);
    try { await openBillingPortal(); }
    finally { setPortalLoading(false); }
  };

  const currentTier = user?.subscription_tier || "free";
  const currentIdx  = PLAN_ORDER.indexOf(currentTier);

  const getPlanState = (planId) => {
    if (planId === currentTier) return "current";
    const planIdx = PLAN_ORDER.indexOf(planId);
    if (currentIdx === -1 || planIdx === -1) return "upgrade";
    return planIdx > currentIdx ? "upgrade" : "downgrade";
  };

  const getCtaLabel = (plan) => {
    if (plan.id === "enterprise") return "Contact sales";
    if (!token) return "Select";
    const state = getPlanState(plan.id);
    if (state === "current") return "Current plan";
    if (currentTier === "free" || currentIdx === -1) return "Select";
    return "Upgrade";
  };

  const handleSelect = async (planId) => {
    if (planId === "enterprise") {
      setShowContactSales(true);
      return;
    }
    if (!token) {
      onGetStarted(planId, annual ? "annual" : "monthly");
      return;
    }
    if (planId === currentTier) return;
    setLoadingPlan(planId);
    try {
      const res  = await fetch(`${API_BASE}/api/stripe/create-checkout`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ plan: planId, billing_cycle: annual ? "annual" : "monthly" }),
      });
      const data = await res.json();
      if (data.checkout_url) {
        window.location.href = data.checkout_url;
      } else {
        setLoadingPlan(null);
        if (onError) onError(data.detail || "Failed to start checkout. Please try again.");
      }
    } catch {
      setLoadingPlan(null);
      if (onError) onError("Network error. Please try again.");
    }
  };

  const anyLoading = !!loadingPlan;

  return (
    <>
    <main className="mkt-page">

      {/* HERO */}
      <section className="mkt-hero" style={{ paddingTop: 64, paddingBottom: 0 }}>
        <h1 className="pricing-section-h1">Choose the Plan That Fits Your Business</h1>
        {token && user?.subscription_tier && user.subscription_tier !== "free" && openBillingPortal && (
          <p style={{ fontSize: 13, color: "#64748b", marginTop: 8 }}>
            Need to update your payment method?{" "}
            <button
              onClick={handleManageBilling}
              disabled={portalLoading}
              style={{ background: "none", border: "none", padding: 0, color: "#E61B84", fontWeight: 600, cursor: "pointer", fontSize: 13, textDecoration: "underline" }}
            >
              {portalLoading ? "Opening…" : "Manage billing"}
            </button>
          </p>
        )}
      </section>


      {/* BILLING TOGGLE + PLANS */}
      <section className="mkt-section" style={{ paddingTop: 24 }}>
        <div className="mkt-section-inner">
          <div className="mkt-billing-toggle">
            <button
              className={`mkt-toggle-btn ${!annual ? "mkt-toggle-active" : ""}`}
              onClick={() => setAnnual(false)}
            >
              Monthly
            </button>
            <button
              className={`mkt-toggle-btn ${annual ? "mkt-toggle-active" : ""}`}
              onClick={() => setAnnual(true)}
            >
              Annual <span className="mkt-toggle-save">Save ~23%</span>
            </button>
          </div>

          <div className="mkt-plans-grid">
            {PLANS.map((plan) => {
              const isLoading = loadingPlan === plan.id;
              const price     = plan.monthlyPrice !== null ? (annual ? plan.annualPrice : plan.monthlyPrice) : null;

              const planState  = getPlanState(plan.id);
              const ctaLabel   = getCtaLabel(plan);
              const isCurrent  = token && planState === "current";
              const isDisabled = anyLoading || isCurrent;

              return (
                <div key={plan.id} className={`mkt-plan-card ${plan.featured ? "mkt-plan-featured" : ""} ${isCurrent ? "mkt-plan-current" : ""}`}>
                  {isCurrent
                    ? <div className="mkt-plan-badge mkt-plan-badge-current">Your plan</div>
                    : plan.badge && <div className="mkt-plan-badge">{plan.badge}</div>
                  }
                  <div className="mkt-plan-name">{plan.name}</div>

                  {price !== null ? (
                    <div className="mkt-plan-price">
                      <span className="mkt-plan-dollar">$</span>
                      <span className="mkt-plan-amount">{price}</span>
                      <span className="mkt-plan-period">/mo</span>
                    </div>
                  ) : (
                    <div className="mkt-plan-price">
                      <span className="mkt-plan-custom">Custom</span>
                    </div>
                  )}
                  {price !== null && annual && (
                    <div className="mkt-plan-billed">Billed annually</div>
                  )}

                  <div style={{ fontSize: 12, color: "var(--primary)", fontWeight: 600, margin: "6px 0 8px" }}>{plan.packageCount}</div>

                  <button
                    className={plan.featured ? "btn-primary mkt-plan-cta" : "mkt-plan-cta mkt-plan-cta-outline"}
                    onClick={() => handleSelect(plan.id)}
                    disabled={isDisabled}
                    style={{
                      opacity: (anyLoading && !isLoading) || isCurrent ? 0.6 : 1,
                      cursor: isCurrent ? "default" : "pointer",
                      display: "flex", alignItems: "center", justifyContent: "center", gap: 8,
                    }}
                    onMouseEnter={e => { if (!plan.featured && !isCurrent) { e.currentTarget.style.background = "var(--primary)"; e.currentTarget.style.color = "#fff"; e.currentTarget.style.borderColor = "var(--primary)"; e.currentTarget.style.boxShadow = "0 4px 14px rgba(230,0,122,0.3)"; }}}
                    onMouseLeave={e => { if (!plan.featured && !isCurrent) { e.currentTarget.style.background = "transparent"; e.currentTarget.style.color = "var(--text-primary)"; e.currentTarget.style.borderColor = "var(--light-gray)"; e.currentTarget.style.boxShadow = "none"; }}}
                  >
                    {isLoading ? (
                      <>
                        <span style={{ width: 13, height: 13, border: "2px solid currentColor", borderTopColor: "transparent", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" }} />
                        Opening cart…
                      </>
                    ) : ctaLabel}
                  </button>

                  <div className="mkt-plan-divider" />

                  <ul className="mkt-plan-features">
                    {plan.features.map((f, i) => (
                      <li key={i} className="mkt-plan-feature mkt-feature-yes">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
                        {f}
                      </li>
                    ))}
                    {plan.missing.map((f, i) => (
                      <li key={i} className="mkt-plan-feature mkt-feature-no">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                        {f}
                      </li>
                    ))}
                  </ul>
                </div>
              );
            })}
          </div>
        </div>
      </section>

    </main>
    {showContactSales && (
      <ContactModal user={user} onClose={() => setShowContactSales(false)} />
    )}
  </>
  );
}
