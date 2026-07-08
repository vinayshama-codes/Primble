import { useState, useEffect } from "react";
import { listAdmins, addAdmin, removeAdmin } from "../../api/adminApi";
import { inputStyle, labelStyle, AdminMsg } from "./adminModalStyles";

export default function AdminManageAdminsModal({ onClose }) {
  const [admins, setAdmins] = useState([]);
  const [loading, setLoading] = useState(true);
  const [email, setEmail] = useState("");
  const [adding, setAdding] = useState(false);
  const [removingEmail, setRemovingEmail] = useState(null);
  const [msg, setMsg] = useState(null);

  const load = async () => {
    setLoading(true);
    const { ok, admins } = await listAdmins();
    if (ok) setAdmins(admins);
    setLoading(false);
  };

  useEffect(() => { load(); }, []);

  const doAdd = async () => {
    const target = email.trim();
    if (!target) { setMsg({ ok: false, text: "Enter an email first." }); return; }
    setAdding(true); setMsg(null);
    const { ok, status, data } = await addAdmin(target);
    setAdding(false);
    if (ok) {
      setMsg({ ok: true, text: data.note || `${data.email || target} is now an admin.` });
      setEmail("");
      load();
    } else if (status === 403) {
      setMsg({ ok: false, text: "Admin access required." });
    } else {
      setMsg({ ok: false, text: (data && data.detail) || "Could not add admin. Please try again." });
    }
  };

  const doRemove = async (targetEmail) => {
    setRemovingEmail(targetEmail); setMsg(null);
    const { ok, status, data } = await removeAdmin(targetEmail);
    setRemovingEmail(null);
    if (ok) {
      setMsg({ ok: true, text: `${targetEmail} is no longer an admin.` });
      load();
    } else if (status === 400) {
      setMsg({ ok: false, text: (data && data.detail) || `${targetEmail} is set via ADMIN_EMAILS and cannot be removed here.` });
    } else {
      setMsg({ ok: false, text: (data && data.detail) || "Could not remove admin. Please try again." });
    }
  };

  return (
    <div className="modal-overlay" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal-content" style={{ maxWidth: 480 }} onClick={(e) => e.stopPropagation()}>
        <button className="modal-close" onClick={onClose}>✕</button>
        <div className="modal-inner">
          <h2 className="step-title" style={{ marginBottom: 6 }}>Manage Admins</h2>
          <p className="step-subtitle" style={{ marginBottom: 20 }}>
            Grant or revoke admin access. Env-set admins (ADMIN_EMAILS) are permanent and cannot be removed here.
          </p>

          <label style={labelStyle}>Add admin by email</label>
          <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
            <input
              type="email" value={email} placeholder="user@example.com"
              onChange={(e) => setEmail(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !adding) doAdd(); }}
              style={{ ...inputStyle, flex: 1 }}
            />
            <button className="btn btn-modal-primary" onClick={doAdd} disabled={adding} style={{ whiteSpace: "nowrap" }}>
              {adding ? "Adding..." : "Add"}
            </button>
          </div>
          <AdminMsg msg={msg} />

          <div style={{ marginTop: 18, fontSize: 12, fontWeight: 700, color: "#94a3b8", letterSpacing: "0.05em", textTransform: "uppercase" }}>
            Current admins
          </div>
          {loading ? (
            <div style={{ padding: "16px 0", color: "#94a3b8", fontSize: 13 }}>Loading...</div>
          ) : admins.length === 0 ? (
            <div style={{ padding: "16px 0", color: "#94a3b8", fontSize: 13 }}>No admins found.</div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 8 }}>
              {admins.map((a) => (
                <div
                  key={a.email}
                  style={{
                    display: "flex", alignItems: "center", justifyContent: "space-between",
                    padding: "8px 10px", background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: 8,
                  }}
                >
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontSize: 13.5, fontWeight: 600, color: "#0f172a", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {a.email}
                    </div>
                    <div style={{ fontSize: 11, color: "#94a3b8" }}>
                      {a.source === "env" ? "Set via ADMIN_EMAILS (permanent)" : "Added via database"}
                    </div>
                  </div>
                  {a.source === "database" && (
                    <button
                      className="btn-stub"
                      style={{ opacity: 1, cursor: "pointer", background: "#fff1f2", color: "#dc2626", flexShrink: 0 }}
                      onClick={() => doRemove(a.email)}
                      disabled={removingEmail === a.email}
                    >
                      {removingEmail === a.email ? "Removing..." : "Remove"}
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
