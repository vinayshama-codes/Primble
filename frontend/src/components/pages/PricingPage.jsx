import { useState } from "react";
import { API_BASE } from "../../config/constants";
import { PLANS } from "../billing/plans";

const BILLING_STATES = [
  {
    icon: "⚠️",
    title: "Payment failed (soft lock)",
    desc: "Banner appears in-app. You can view sessions but cannot start new ones or download. Resolves via billing portal.",
  },
  {
    icon: "🚫",
    title: "Subscription suspended (hard lock)",
    desc: "All generation and download blocked. Session history is readable. Resume via billing portal — restores immediately on successful retry.",
  },
  {
    icon: "📅",
    title: "Canceling / end of period",
    desc: "All features remain active until the cancellation date (shown as a countdown banner). You can reverse before the period ends.",
  },
  {
    icon: "🔄",
    title: "Upgrade or downgrade",
    desc: "Immediate via Stripe checkout. Upgrades pro-rate remaining days. Downgrades apply next billing cycle. Package limits update in real time.",
  },
];

export default function PricingPage({ onGetStarted, token, user, onError }) {
  const [annual, setAnnual]           = useState(false);
  const [loadingPlan, setLoadingPlan] = useState(null);

  const handleSelect = async (planId) => {
    if (planId === "enterprise") {
      window.location.href = "mailto:sales@acordly.ai?subject=Enterprise Plan Inquiry";
      return;
    }
    if (!token) {
      onGetStarted();
      return;
    }
    setLoadingPlan(planId);
    try {
      const res  = await fetch(`${API_BASE}/api/stripe/create-checkout`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
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
    <main className="mkt-page">

      {/* HERO */}
      <section className="mkt-hero" style={{ paddingBottom: 16 }}>
        <div className="mkt-hero-eyebrow">Pricing</div>
        <h1 className="mkt-hero-h1">
          Transparent pricing.<br />
          <span className="mkt-hero-accent">Clear mechanics.</span>
        </h1>
        <p className="mkt-hero-p">
          Plans based on monthly submission packages. No hidden metering, no per-form charges, no surprise overages.
        </p>
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

              return (
                <div key={plan.id} className={`mkt-plan-card ${plan.featured ? "mkt-plan-featured" : ""}`}>
                  {plan.badge && <div className="mkt-plan-badge">{plan.badge}</div>}
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

                  <div style={{ fontSize: 12, color: "var(--primary)", fontWeight: 600, margin: "6px 0 2px" }}>{plan.packageCount}</div>
                  <div style={{ fontSize: 11, color: "var(--text-tertiary)", marginBottom: 4 }}>Overage: {plan.overage}</div>

                  <button
                    className={plan.featured ? "btn-primary mkt-plan-cta" : "mkt-plan-cta mkt-plan-cta-outline"}
                    onClick={() => handleSelect(plan.id)}
                    disabled={anyLoading}
                    style={{ opacity: anyLoading && !isLoading ? 0.5 : 1, display: "flex", alignItems: "center", justifyContent: "center", gap: 8 }}
                    onMouseEnter={e => { if (!plan.featured) { e.currentTarget.style.background = "var(--primary)"; e.currentTarget.style.color = "#fff"; e.currentTarget.style.borderColor = "var(--primary)"; e.currentTarget.style.boxShadow = "0 4px 14px rgba(230,0,122,0.3)"; }}}
                    onMouseLeave={e => { if (!plan.featured) { e.currentTarget.style.background = "transparent"; e.currentTarget.style.color = "var(--text-primary)"; e.currentTarget.style.borderColor = "var(--light-gray)"; e.currentTarget.style.boxShadow = "none"; }}}
                  >
                    {isLoading ? (
                      <>
                        <span style={{ width: 13, height: 13, border: "2px solid currentColor", borderTopColor: "transparent", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" }} />
                        Opening cart…
                      </>
                    ) : plan.cta}
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

      {/* USAGE MECHANICS */}
      <section className="mkt-section mkt-section-alt">
        <div className="mkt-section-inner">
          <div className="mkt-section-header">
            <div className="mkt-eyebrow">Usage mechanics</div>
            <h2 className="mkt-section-h2">What counts as a package</h2>
          </div>
          <div className="mkt-mechanics-grid">
            <div className="mkt-mechanic-card">
              <div className="mkt-mechanic-icon">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/>
                </svg>
              </div>
              <h3 className="mkt-mechanic-title">What is a submission package?</h3>
              <p className="mkt-mechanic-desc">One complete submission: all forms in one session, downloaded together. Counts as 1 package regardless of how many forms are in the package.</p>
            </div>
            <div className="mkt-mechanic-card">
              <div className="mkt-mechanic-icon">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
                </svg>
              </div>
              <h3 className="mkt-mechanic-title">Overage behavior</h3>
              <p className="mkt-mechanic-desc">When your limit is reached, a warning banner appears in-app. Purchase a one-time overage block via Stripe checkout — no plan change required. Applied immediately. Does not roll over.</p>
            </div>
          </div>
        </div>
      </section>

      {/* BILLING STATE HANDLING */}
      <section className="mkt-section">
        <div className="mkt-section-inner">
          <div className="mkt-section-header">
            <div className="mkt-eyebrow">Billing state</div>
            <h2 className="mkt-section-h2">How billing states work</h2>
            <p className="mkt-section-sub">Four states that can affect your account. Each has a clear resolution path.</p>
          </div>
          <div className="mkt-billing-states">
            {BILLING_STATES.map((state, i) => (
              <div key={i} className="mkt-billing-state">
                <div className="mkt-billing-state-icon">{state.icon}</div>
                <div>
                  <div className="mkt-billing-state-title">{state.title}</div>
                  <div className="mkt-billing-state-desc">{state.desc}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

    </main>
  );
}
