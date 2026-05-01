import { useState, useEffect, useRef } from "react";
import { API_BASE } from "../../config/constants";

const TIER_LABELS = {
  essentials: "Essentials",
  professional: "Professional",
  business: "Business",
  enterprise: "Enterprise",
  free: "Free",
};

export default function PlanModal({ user, token, onClose, onChangePlan, anchorRef }) {
  const [canceling, setCanceling]     = useState(false);
  const [cancelDone, setCancelDone]   = useState(false);
  const [cancelError, setCancelError] = useState("");
  const [confirmCancel, setConfirmCancel] = useState(false);
  const modalRef = useRef(null);

  const tier       = user?.subscription_tier || "free";
  const used       = user?.packages_used ?? 0;
  const limit      = user?.packages_limit ?? 0;
  const tierLabel  = TIER_LABELS[tier] || tier;
  const isFree     = tier === "free";
  const noPackages = isFree || limit === 0;
  const pct        = !noPackages ? Math.min(100, Math.round((used / limit) * 100)) : 0;
  const barColor   = pct >= 90 ? "#ef4444" : pct >= 70 ? "#f59e0b" : "#10b981";

  // Close on outside click
  useEffect(() => {
    const handler = (e) => {
      if (modalRef.current && !modalRef.current.contains(e.target) &&
          anchorRef?.current && !anchorRef.current.contains(e.target)) {
        onClose();
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [onClose, anchorRef]);

  const handleCancel = async () => {
    setCanceling(true); setCancelError("");
    try {
      const res  = await fetch(`${API_BASE}/api/stripe/cancel-subscription`, {
        method: "POST", headers: { Authorization: `Bearer ${token}` },
      });
      const data = await res.json();
      if (!res.ok) { setCancelError(data.detail || data.message || "Failed to cancel."); return; }
      setCancelDone(true); setConfirmCancel(false);
    } catch { setCancelError("Network error. Please try again."); }
    finally { setCanceling(false); }
  };

  return (
    <div ref={modalRef} style={{
      position: "absolute", top: 60, right: 0, zIndex: 1000,
      background: "#fff", border: "1px solid #e2e8f0", borderRadius: 12,
      boxShadow: "0 8px 32px rgba(15,23,42,0.12)", padding: "20px 22px",
      minWidth: 280, maxWidth: 320,
    }}>
      {/* Plan info */}
      <div style={{ marginBottom: 16 }}>
        <div style={{ fontSize: 11, fontWeight: 700, color: "#94a3b8", letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: 6 }}>Current Plan</div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 18, fontWeight: 800, color: "#0f172a" }}>{tierLabel}</span>
          {!isFree && (
            <span style={{ fontSize: 11, fontWeight: 600, background: "#f0fdf4", color: "#15803d", border: "1px solid #bbf7d0", borderRadius: 20, padding: "2px 8px" }}>
              {user?.billing_cycle === "annual" ? "Annual" : "Monthly"}
            </span>
          )}
        </div>
      </div>

      {/* Package usage */}
      {!noPackages && (
        <div style={{ marginBottom: 16 }}>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 5 }}>
            <span style={{ fontSize: 11, fontWeight: 700, color: "#94a3b8", letterSpacing: "0.06em", textTransform: "uppercase" }}>{tier === "essentials" ? "Scores Used" : "Packages Used"}</span>
            <span style={{ fontSize: 12, fontWeight: 700, color: "#0f172a" }}>{used} / {limit}</span>
          </div>
          <div style={{ background: "#f1f5f9", borderRadius: 999, height: 6, overflow: "hidden" }}>
            <div style={{ width: `${pct}%`, height: "100%", background: barColor, borderRadius: 999, transition: "width 0.4s ease" }} />
          </div>
          {pct >= 90 && (
            <div style={{ fontSize: 11, color: "#b45309", marginTop: 4, fontWeight: 600 }}>⚠️ Approaching limit</div>
          )}
        </div>
      )}


      <div style={{ height: 1, background: "#f1f5f9", margin: "4px 0 16px" }} />

      {/* Actions */}
      {cancelDone ? (
        <div style={{ fontSize: 13, color: "#15803d", fontWeight: 600, textAlign: "center", padding: "8px 0" }}>
          ✓ Subscription will cancel at end of billing period.
        </div>
      ) : confirmCancel ? (
        <div>
          <div style={{ fontSize: 13, color: "#0f172a", marginBottom: 12, fontWeight: 500 }}>
            Are you sure? You'll keep access until the end of your current billing period.
          </div>
          {cancelError && <div style={{ fontSize: 12, color: "#ef4444", marginBottom: 8 }}>{cancelError}</div>}
          <div style={{ display: "flex", gap: 8 }}>
            <button onClick={() => setConfirmCancel(false)} style={{ flex: 1, padding: "8px 0", borderRadius: 8, border: "1px solid #e2e8f0", background: "#fff", fontSize: 13, fontWeight: 600, cursor: "pointer", color: "#64748b" }}>
              Keep Plan
            </button>
            <button onClick={handleCancel} disabled={canceling} style={{ flex: 1, padding: "8px 0", borderRadius: 8, border: "1px solid #ef4444", background: "#ef4444", fontSize: 13, fontWeight: 600, cursor: canceling ? "wait" : "pointer", color: "#fff", opacity: canceling ? 0.7 : 1, display: "flex", alignItems: "center", justifyContent: "center", gap: 6 }}>
              {canceling ? <><span style={{ width: 11, height: 11, border: "2px solid #fff", borderTopColor: "transparent", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" }} />Canceling…</> : "Yes, Cancel"}
            </button>
          </div>
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <button onClick={() => { onClose(); onChangePlan(); }} style={{ width: "100%", padding: "9px 0", borderRadius: 8, border: "none", background: "#0f172a", color: "#fff", fontSize: 13, fontWeight: 700, cursor: "pointer" }}>
            Change Plan
          </button>
          {!isFree && tier !== "enterprise" && !cancelDone && user?.payment_status !== "canceling" && (
            <button onClick={() => setConfirmCancel(true)} style={{ width: "100%", padding: "9px 0", borderRadius: 8, border: "1px solid #e2e8f0", background: "#fff", color: "#64748b", fontSize: 13, fontWeight: 600, cursor: "pointer" }}>
              Cancel Subscription
            </button>
          )}
          {user?.payment_status === "canceling" && (
            <div style={{ fontSize: 12, color: "#64748b", textAlign: "center" }}>Subscription cancels at end of billing period.</div>
          )}
        </div>
      )}
    </div>
  );
}
