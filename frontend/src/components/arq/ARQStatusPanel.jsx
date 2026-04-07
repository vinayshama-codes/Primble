import { useState } from "react";
import { sendArqReminder } from "../../api/arqApi";

export default function ARQStatusPanel({ arqSessions, token, onRefresh }) {
  const [reminding, setReminding] = useState(null);

  const handleRemind = async (arq_id) => {
    setReminding(arq_id);
    const { ok, data } = await sendArqReminder(token, arq_id);
    setReminding(null);
    if (ok && data.success) {
      onRefresh();
    }
  };

  const statusColor = {
    pending:   { bg: "#fef9c3", color: "#854d0e", border: "#fde047" },
    submitted: { bg: "#dcfce7", color: "#166534", border: "#86efac" },
    expired:   { bg: "#f1f5f9", color: "#64748b", border: "#cbd5e1" },
  };

  const formatDate = (iso) => {
    if (!iso) return "—";
    return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  };

  if (!arqSessions || arqSessions.length === 0) return null;

  return (
    <div style={{ marginTop: 12 }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: "#64748b", marginBottom: 8 }}>
        📧 Sent Questionnaires
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {arqSessions.map((arq) => {
          const now     = new Date();
          const expires = new Date(arq.expires_at);
          const isExpired = now > expires && arq.status !== "submitted";
          const displayStatus = isExpired ? "expired" : arq.status;
          const sc = statusColor[displayStatus] || statusColor.pending;

          return (
            <div key={arq.id} style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: 8, padding: "10px 12px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 8 }}>
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: "#1e293b", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {arq.client_name ? `${arq.client_name} (${arq.email})` : arq.email}
                  </div>
                  <div style={{ fontSize: 11, color: "#94a3b8", marginTop: 2 }}>
                    Sent {formatDate(arq.created_at)}
                    {arq.submitted_at && ` · Submitted ${formatDate(arq.submitted_at)}`}
                  </div>
                </div>
                <span style={{ fontSize: 11, fontWeight: 600, padding: "2px 8px", borderRadius: 12, border: `1px solid ${sc.border}`, background: sc.bg, color: sc.color, flexShrink: 0 }}>
                  {displayStatus === "submitted" ? "✓ Submitted" : displayStatus === "expired" ? "Expired" : "⏳ Pending"}
                </span>
              </div>

              {arq.status === "pending" && !isExpired && (
                <button
                  onClick={() => handleRemind(arq.id)}
                  disabled={reminding === arq.id}
                  style={{ marginTop: 8, fontSize: 11, fontWeight: 600, color: "#4f7cff", background: "none", border: "1px solid #4f7cff", borderRadius: 6, padding: "3px 10px", cursor: reminding === arq.id ? "wait" : "pointer", opacity: reminding === arq.id ? 0.6 : 1 }}
                >
                  {reminding === arq.id ? "Sending…" : "🔔 Send Reminder"}
                  {arq.reminder_count > 0 && ` (${arq.reminder_count} sent)`}
                </button>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}