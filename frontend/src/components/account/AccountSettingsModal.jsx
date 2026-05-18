import { useState } from "react";
import { API_BASE } from "../../config/constants";

export default function AccountSettingsModal({ user, onClose, onUserUpdate, openBillingPortal }) {
  const [fullName, setFullName] = useState(user?.full_name || "");
  const [orgName, setOrgName] = useState(user?.organization_name || "");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [portalLoading, setPortalLoading] = useState(false);

  const handleSave = async (e) => {
    e.preventDefault();
    setSaving(true);
    setSaveError("");
    setSaveSuccess(false);
    try {
      const res = await fetch(`${API_BASE}/api/auth/update-profile`, {
        method: "PATCH",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          full_name: fullName.trim() || null,
          organization_name: orgName.trim() || null,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        setSaveError(data.detail || "Failed to save changes.");
        return;
      }
      onUserUpdate({ ...user, ...data });
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
    } catch {
      setSaveError("Network error. Please try again.");
    } finally {
      setSaving(false);
    }
  };

  const handleBillingPortal = async () => {
    setPortalLoading(true);
    await openBillingPortal();
    setPortalLoading(false);
  };

  const isFree = !user?.subscription_tier || user.subscription_tier === "free";
  const tierLabel = {
    essentials: "Essentials",
    professional: "Professional",
    business: "Business",
    enterprise: "Enterprise",
    free: "Free",
  }[user?.subscription_tier] || "Free";

  return (
    <div className="modal-overlay" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal-content" style={{ maxWidth: 500 }} onClick={(e) => e.stopPropagation()}>
        <button className="modal-close" onClick={onClose}>✕</button>
        <div className="modal-inner">

          <h2 className="step-title" style={{ marginBottom: 6 }}>Account Settings</h2>
          <p className="step-subtitle" style={{ marginBottom: 28 }}>
            Manage your personal details and billing information.
          </p>

          {/* Personal Details */}
          <section style={{ marginBottom: 28 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: "#94a3b8", textTransform: "uppercase", letterSpacing: "0.07em", marginBottom: 14 }}>
              Personal Details
            </div>
            <form onSubmit={handleSave} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
              <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
                <label style={{ fontSize: 12.5, fontWeight: 700, color: "#475569" }}>Full Name</label>
                <input
                  className="acct-input"
                  type="text"
                  value={fullName}
                  onChange={e => setFullName(e.target.value)}
                  placeholder="Your full name"
                />
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
                <label style={{ fontSize: 12.5, fontWeight: 700, color: "#475569" }}>Email</label>
                <input
                  className="acct-input acct-input--readonly"
                  type="email"
                  value={user?.email || ""}
                  readOnly
                />
                <span style={{ fontSize: 11.5, color: "#94a3b8", fontWeight: 500 }}>Email cannot be changed.</span>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
                <label style={{ fontSize: 12.5, fontWeight: 700, color: "#475569" }}>Organization</label>
                <input
                  className="acct-input"
                  type="text"
                  value={orgName}
                  onChange={e => setOrgName(e.target.value)}
                  placeholder="Your organization name"
                />
              </div>
              {saveError && (
                <div className="alert alert-error"><span>{saveError}</span></div>
              )}
              {saveSuccess && (
                <div className="alert" style={{ background: "rgba(16,185,129,0.1)", border: "1px solid #6ee7b7", borderRadius: 8, padding: "10px 14px", fontSize: 13, color: "#065f46", fontWeight: 600 }}>
                  Changes saved successfully.
                </div>
              )}
              <div style={{ display: "flex", gap: 10 }}>
                <button
                  type="submit"
                  className="btn btn-modal-primary"
                  style={{ flex: 1 }}
                  disabled={saving}
                >
                  {saving ? (
                    <span style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 8 }}>
                      <span style={{ width: 14, height: 14, border: "2px solid currentColor", borderTopColor: "transparent", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" }} />
                      Saving…
                    </span>
                  ) : "Save Changes"}
                </button>
                <button type="button" className="btn btn-modal-secondary" onClick={onClose}>Cancel</button>
              </div>
            </form>
          </section>

          {/* Divider */}
          <div style={{ height: 1, background: "rgba(230,27,132,0.12)", margin: "0 0 24px" }} />

          {/* Subscription & Billing */}
          <section>
            <div style={{ fontSize: 11, fontWeight: 700, color: "#94a3b8", textTransform: "uppercase", letterSpacing: "0.07em", marginBottom: 14 }}>
              Subscription &amp; Billing
            </div>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "12px 14px", background: "rgba(230,27,132,0.04)", border: "1px solid rgba(230,27,132,0.15)", borderRadius: 12, marginBottom: 14 }}>
              <div>
                <div style={{ fontSize: 14, fontWeight: 700, color: "#0f172a" }}>{tierLabel} Plan</div>
                {!isFree && (
                  <div style={{ fontSize: 12, color: "#64748b", marginTop: 2 }}>
                    {user?.billing_cycle === "annual" ? "Annual billing" : "Monthly billing"}
                  </div>
                )}
              </div>
              <span style={{
                fontSize: 11, fontWeight: 700, padding: "3px 10px", borderRadius: 20,
                background: isFree ? "#f1f5f9" : "rgba(16,185,129,0.1)",
                color: isFree ? "#475569" : "#065f46",
                border: `1px solid ${isFree ? "#e2e8f0" : "#6ee7b7"}`,
              }}>
                {isFree ? "Free" : "Active"}
              </span>
            </div>
            <button
              className="btn btn-modal-secondary"
              style={{ width: "100%", opacity: (portalLoading || isFree) ? 0.5 : 1, cursor: (portalLoading || isFree) ? "not-allowed" : "pointer" }}
              onClick={handleBillingPortal}
              disabled={portalLoading || isFree}
            >
              {portalLoading ? (
                <span style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 8 }}>
                  <span style={{ width: 14, height: 14, border: "2px solid currentColor", borderTopColor: "transparent", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" }} />
                  Opening…
                </span>
              ) : "Update Payment Method"}
            </button>
            {isFree && (
              <p style={{ fontSize: 11.5, color: "#94a3b8", fontWeight: 500, marginTop: 8, textAlign: "center" }}>
                Upgrade to a paid plan to manage billing.
              </p>
            )}
          </section>

        </div>
      </div>
    </div>
  );
}
