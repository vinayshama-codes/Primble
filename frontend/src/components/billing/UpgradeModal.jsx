import { useState } from "react";
import { API_BASE } from "../../config/constants";
import { PLANS } from "./plans";

const CheckIcon = () => (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" style={{ color: "#059669", flexShrink: 0, marginTop: 2 }}>
    <polyline points="20 6 9 17 4 12"/>
  </svg>
);

const CrossIcon = () => (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ color: "#cbd5e1", flexShrink: 0, marginTop: 2 }}>
    <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
  </svg>
);

export default function UpgradeModal({ token, user, onClose, onError }) {
  const [billing, setBilling]         = useState("annual");
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
        credentials: "include",
        headers: { "Content-Type": "application/json" },
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

  const anyLoading = !!loadingPlan;

  return (
    <div className="modal-overlay">
      <div className="modal-content upgrade-modal upgrade-modal-wide" onClick={(e) => e.stopPropagation()}>
        <button className="modal-close" onClick={onClose} disabled={anyLoading}>✕</button>
        <div className="modal-inner" style={{ paddingTop: 48 }}>

          {/* Header */}
          <div style={{ textAlign: "center", marginBottom: 28 }}>
            <div style={{ display: "inline-block", fontSize: 13, fontWeight: 700, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--primary)", background: "rgba(230,0,122,0.08)", padding: "5px 14px", borderRadius: 999, marginBottom: 14 }}>
              Choose a plan
            </div>
            <h2 style={{ fontSize: 28, fontWeight: 700, color: "var(--text-primary)", letterSpacing: "-0.02em", marginBottom: 8 }}>
              Transparent pricing. Clear mechanics.
            </h2>
            {user?.subscription_tier === "free" && user?.downloads_remaining <= 0 && (
              <p style={{ fontSize: 15, color: "var(--text-secondary)", marginBottom: 0 }}>
                You've used all your free submissions. Upgrade to continue.
              </p>
            )}
          </div>

          {/* Billing toggle */}
          <div style={{ display: "flex", justifyContent: "center", marginBottom: 32 }}>
            <div style={{ display: "flex", background: "var(--light-bg)", borderRadius: 999, padding: 4, gap: 2 }}>
              <button
                onClick={() => setBilling("monthly")}
                disabled={anyLoading}
                style={{ padding: "9px 26px", borderRadius: 999, border: "none", fontSize: 14, fontWeight: 600, cursor: anyLoading ? "not-allowed" : "pointer", transition: "all 0.2s", background: billing === "monthly" ? "#fff" : "transparent", color: billing === "monthly" ? "var(--text-primary)" : "var(--text-secondary)", boxShadow: billing === "monthly" ? "0 2px 8px rgba(0,0,0,0.08)" : "none" }}
              >
                Monthly
              </button>
              <button
                onClick={() => setBilling("annual")}
                disabled={anyLoading}
                style={{ padding: "9px 26px", borderRadius: 999, border: "none", fontSize: 14, fontWeight: 600, cursor: anyLoading ? "not-allowed" : "pointer", transition: "all 0.2s", display: "flex", alignItems: "center", gap: 8, background: billing === "annual" ? "#fff" : "transparent", color: billing === "annual" ? "var(--text-primary)" : "var(--text-secondary)", boxShadow: billing === "annual" ? "0 2px 8px rgba(0,0,0,0.08)" : "none" }}
              >
                Annual
                <span style={{ fontSize: 11, fontWeight: 700, color: "#059669", background: "rgba(16,185,129,0.1)", padding: "2px 7px", borderRadius: 999 }}>Save ~23%</span>
              </button>
            </div>
          </div>

          {/* Plan cards — 4 in one row */}
          <div className="upgrade-plan-grid">
            {PLANS.map((plan) => {
              const isLoading = loadingPlan === plan.id;
              const price     = plan.monthlyPrice !== null ? (billing === "annual" ? plan.annualPrice : plan.monthlyPrice) : null;

              return (
                <div
                  key={plan.id}
                  style={{
                    background: "#fff",
                    border: plan.featured ? "1.5px solid var(--primary)" : "1.5px solid var(--light-gray)",
                    borderRadius: 18,
                    padding: "28px 22px",
                    position: "relative",
                    display: "flex",
                    flexDirection: "column",
                    boxShadow: plan.featured ? "0 4px 24px rgba(230,0,122,0.12)" : "none",
                    transition: "box-shadow 0.2s, transform 0.2s",
                  }}
                >
                  {plan.badge && (
                    <div style={{ position: "absolute", top: -13, left: "50%", transform: "translateX(-50%)", background: "var(--primary)", color: "#fff", fontSize: 11, fontWeight: 700, padding: "4px 14px", borderRadius: 999, whiteSpace: "nowrap" }}>
                      {plan.badge}
                    </div>
                  )}

                  <div style={{ fontSize: 16, fontWeight: 700, color: "var(--text-primary)", marginBottom: 14 }}>{plan.name}</div>

                  {price !== null ? (
                    <div style={{ display: "flex", alignItems: "baseline", gap: 2, marginBottom: 4 }}>
                      <span style={{ fontSize: 18, fontWeight: 700, color: "var(--text-primary)" }}>$</span>
                      <span style={{ fontSize: 40, fontWeight: 700, color: "var(--text-primary)", letterSpacing: "-0.03em", lineHeight: 1 }}>{price}</span>
                      <span style={{ fontSize: 14, color: "var(--text-secondary)", marginLeft: 2 }}>/mo</span>
                    </div>
                  ) : (
                    <div style={{ fontSize: 28, fontWeight: 700, color: "var(--text-primary)", marginBottom: 4 }}>Custom</div>
                  )}
                  {price !== null && billing === "annual" && (
                    <div style={{ fontSize: 12, color: "var(--text-tertiary)", marginBottom: 2 }}>Billed annually</div>
                  )}

                  <div style={{ fontSize: 12, color: "var(--primary)", fontWeight: 600, marginTop: 4, marginBottom: 2 }}>{plan.packageCount}</div>
                  <div style={{ fontSize: 11, color: "var(--text-tertiary)", marginBottom: 2 }}>Overage: {plan.overage}</div>

                  <button
                    onClick={() => handleSelect(plan.id)}
                    disabled={anyLoading}
                    onMouseEnter={e => { if (!plan.featured) { e.currentTarget.style.background = "var(--primary)"; e.currentTarget.style.color = "#fff"; e.currentTarget.style.borderColor = "var(--primary)"; e.currentTarget.style.boxShadow = "0 4px 14px rgba(230,0,122,0.3)"; }}}
                    onMouseLeave={e => { if (!plan.featured) { e.currentTarget.style.background = "transparent"; e.currentTarget.style.color = "var(--text-primary)"; e.currentTarget.style.borderColor = "var(--light-gray)"; e.currentTarget.style.boxShadow = "none"; }}}
                    style={{
                      width: "100%",
                      marginTop: 14,
                      padding: "11px 0",
                      borderRadius: 12,
                      border: plan.featured ? "none" : "1.5px solid var(--light-gray)",
                      background: plan.featured ? "var(--primary)" : "transparent",
                      color: plan.featured ? "#fff" : "var(--text-primary)",
                      fontSize: 14,
                      fontWeight: 700,
                      cursor: anyLoading ? "not-allowed" : "pointer",
                      opacity: anyLoading && !isLoading ? 0.5 : 1,
                      boxShadow: plan.featured ? "0 4px 14px rgba(230,0,122,0.3)" : "none",
                      transition: "all 0.2s",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      gap: 8,
                    }}
                  >
                    {isLoading ? (
                      <>
                        <span style={{ width: 13, height: 13, border: "2px solid currentColor", borderTopColor: "transparent", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" }} />
                        Opening cart…
                      </>
                    ) : plan.cta}
                  </button>

                  <div style={{ height: 1, background: "var(--light-gray)", margin: "18px 0" }} />

                  <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: 9, flex: 1 }}>
                    {plan.features.map((f, i) => (
                      <li key={i} style={{ display: "flex", alignItems: "flex-start", gap: 8, fontSize: 13, color: "var(--text-primary)", lineHeight: 1.4 }}>
                        <CheckIcon />{f}
                      </li>
                    ))}
                    {plan.missing.map((f, i) => (
                      <li key={i} style={{ display: "flex", alignItems: "flex-start", gap: 8, fontSize: 13, color: "var(--text-tertiary)", lineHeight: 1.4 }}>
                        <CrossIcon />{f}
                      </li>
                    ))}
                  </ul>
                </div>
              );
            })}
          </div>

          <p style={{ textAlign: "center", fontSize: 12, color: "var(--text-tertiary)", marginTop: 20 }}>
            No long-term contracts. Cancel anytime. Upgrades take effect immediately.
          </p>
        </div>
      </div>
    </div>
  );
}
