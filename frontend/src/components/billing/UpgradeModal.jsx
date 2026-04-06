import { useState } from "react";
import { API_BASE } from "../../config/constants";

const PLANS = [
  {
    id: "essentials", name: "Essentials", monthly: 129, annual: 99,
    packages: 100, overage: "$1.50/package", highlight: false, cta: "Get Essentials",
    features: ["All core ACORD forms","SQS scoring & routing","Cross-form validation","Email support"],
  },
  {
    id: "professional", name: "Professional", monthly: 449, annual: 399,
    packages: 400, overage: "$1.25/package", highlight: true, cta: "Get Professional",
    features: ["All Essentials features","Priority support","Advanced reporting & insights","Team collaboration tools","Dedicated onboarding"],
  },
  {
    id: "enterprise", name: "Enterprise", monthly: 1199, annual: 1199,
    packages: "Custom", overage: "Custom", highlight: false, cta: "Contact Sales",
    features: ["All Professional features","Dedicated account manager","SLA guarantees","On-premise deployment"],
  },
];

export default function UpgradeModal({ token, user, onClose, onError }) {
  const [billing, setBilling]       = useState("annual");
  const [loadingPlan, setLoadingPlan] = useState(null);

  const handleSelect = async (planId) => {
    if (planId === "enterprise") {
      window.location.href = "mailto:sales@acordly.ai?subject=Enterprise Plan Inquiry";
      return;
    }
    setLoadingPlan(planId);
    try {
      const res  = await fetch(`${API_BASE}/api/stripe/create-checkout`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ plan: planId, billing_cycle: billing }),
      });
      const data = await res.json();
      if (data.checkout_url) {
        window.location.href = data.checkout_url;
      } else {
        setLoadingPlan(null);
        onError(data.detail || "Failed to start checkout. Please try again.");
      }
    } catch { setLoadingPlan(null); onError("Network error. Please try again."); }
  };

  return (
    <div className="modal-overlay">
      <div className="modal-content upgrade-modal upgrade-modal-wide" onClick={(e) => e.stopPropagation()}>
        <button className="modal-close" onClick={onClose} disabled={!!loadingPlan}>✕</button>
        <div className="modal-inner">
          <div className="upgrade-icon">🚀</div>
          <h2 className="upgrade-title">Choose Your Plan</h2>
          {user?.downloads_remaining <= 0 && (
            <p className="upgrade-message">You've used all 3 free downloads. Upgrade to continue.</p>
          )}
          <div className="billing-toggle">
            <button className={`billing-option ${billing === "monthly" ? "billing-active" : ""}`} onClick={() => setBilling("monthly")} disabled={!!loadingPlan}>Monthly</button>
            <button className={`billing-option ${billing === "annual" ? "billing-active" : ""}`} onClick={() => setBilling("annual")} disabled={!!loadingPlan}>Annual <span className="billing-save">Save ~23%</span></button>
          </div>
          <div className="plan-cards">
            {PLANS.map((plan) => {
              const isThisLoading = loadingPlan === plan.id;
              const anyLoading    = !!loadingPlan;
              const isEnterprise  = plan.id === "enterprise";
              return (
                <div key={plan.id} className={`plan-card ${plan.highlight ? "plan-card-highlight" : ""}`}>
                  {plan.highlight && <div className="plan-popular">Most Popular</div>}
                  <div className="plan-name">{plan.name}</div>
                  <div className="plan-price">
                    {isEnterprise ? (
                      <span className="plan-price-custom">from $1,199<span style={{ fontSize: 14, fontWeight: 400, color: "#64748b" }}>/mo</span></span>
                    ) : (
                      <>
                        <span className="plan-price-amount">${billing === "annual" ? plan.annual : plan.monthly}</span>
                        <span className="plan-price-period">/mo</span>
                      </>
                    )}
                  </div>
                  {isEnterprise ? (
                    <div className="plan-price-sub">Volume-based pricing, no per-user fees</div>
                  ) : billing === "annual" ? (
                    <div className="plan-billed-note">(billed annually)</div>
                  ) : null}
                  <div className="plan-packages">{plan.packages} packages/mo</div>
                  <div className="plan-overage">Overage: {plan.overage}</div>
                  <ul className="plan-features">
                    {plan.features.map((f, i) => <li key={i}>✓ {f}</li>)}
                  </ul>
                  <button
                    className={`btn btn-block ${plan.highlight ? "btn-modal-primary" : "btn-modal-secondary"}`}
                    onClick={() => handleSelect(plan.id)}
                    disabled={anyLoading}
                    style={{ opacity: anyLoading && !isThisLoading ? 0.5 : 1 }}
                  >
                    {isThisLoading ? (
                      <span style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 8 }}>
                        <span style={{ width: 14, height: 14, border: "2px solid currentColor", borderTopColor: "transparent", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" }} />
                        Opening cart…
                      </span>
                    ) : plan.cta}
                  </button>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}