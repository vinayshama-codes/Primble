import { useState } from "react";
import { resetLicense } from "../../api/adminApi";
import { inputStyle, labelStyle, AdminMsg } from "./adminModalStyles";

export default function AdminResetLicenseModal({ onClose }) {
  const [email, setEmail] = useState("");
  const [resetting, setResetting] = useState(false);
  const [msg, setMsg] = useState(null);

  const doReset = async () => {
    const target = email.trim();
    if (!target) { setMsg({ ok: false, text: "Enter a user email first." }); return; }
    setResetting(true); setMsg(null);
    const { ok, status, data } = await resetLicense(target);
    setResetting(false);
    if (ok) {
      setMsg({ ok: true, text: `Done. ${data.email || target} will be asked to re-confirm the ACORD license on their next download.` });
      setEmail("");
    } else if (status === 404) {
      setMsg({ ok: false, text: `No user found with email ${target}.` });
    } else if (status === 403) {
      setMsg({ ok: false, text: "Admin access required." });
    } else {
      setMsg({ ok: false, text: (data && data.detail) || "Reset failed. Please try again." });
    }
  };

  return (
    <div className="modal-overlay" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal-content" style={{ maxWidth: 460 }} onClick={(e) => e.stopPropagation()}>
        <button className="modal-close" onClick={onClose}>✕</button>
        <div className="modal-inner">
          <h2 className="step-title" style={{ marginBottom: 6 }}>Reset License Confirmation</h2>
          <p className="step-subtitle" style={{ marginBottom: 20 }}>
            Clears a user's ACORD license confirmation so they must re-accept on their next download. Use after a license lapses or the wording changes.
          </p>

          <label style={labelStyle}>User email</label>
          <div style={{ display: "flex", gap: 8 }}>
            <input
              type="email" value={email} placeholder="user@example.com"
              onChange={(e) => setEmail(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !resetting) doReset(); }}
              style={{ ...inputStyle, flex: 1 }}
            />
            <button className="btn btn-modal-primary" onClick={doReset} disabled={resetting} style={{ whiteSpace: "nowrap" }}>
              {resetting ? "Resetting..." : "Reset"}
            </button>
          </div>
          <AdminMsg msg={msg} />
        </div>
      </div>
    </div>
  );
}
