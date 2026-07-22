import { useState } from "react";
import { sendArqReminder } from "../../api/arqApi";
import ARQReceiptModal from "./ARQReceiptModal";

// §6.2: post-remediation status vocabulary (7 states)
const REMEDIATION_LABEL = {
  resolved:                     { text: "Resolved",                   bg: "#dcfce7", color: "#166534", border: "#86efac" },
  improved:                     { text: "Score Improved",             bg: "#dcfce7", color: "#166534", border: "#86efac" },
  pending_validation:           { text: "Pending Validation",         bg: "#eff6ff", color: "#1e40af", border: "#bfdbfe" },
  user_provided_only:           { text: "User Provided",              bg: "#eff6ff", color: "#1e40af", border: "#bfdbfe" },
  conflicting_evidence_remains: { text: "Conflicting Evidence",       bg: "#fffbeb", color: "#92400e", border: "#fde68a" },
  requires_supporting_document: { text: "Supporting Doc Required",    bg: "#fffbeb", color: "#92400e", border: "#fde68a" },
  still_missing:                { text: "Still Missing",              bg: "#f1f5f9", color: "#475569", border: "#cbd5e1" },
};

export default function ARQStatusPanel({ arqSessions, token, onRefresh }) {
  const [reminding, setReminding] = useState(null);
  // Figure 21: which submitted questionnaire's response receipt is open.
  const [receiptFor, setReceiptFor] = useState(null);

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
    if (!iso) return "-";
    return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  };

  if (!arqSessions || arqSessions.length === 0) return null;

  return (
    <div style={{ marginTop: 12 }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: "#64748b", marginBottom: 8 }}>
        Sent Questionnaires
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {arqSessions.map((arq) => {
          const now     = new Date();
          const expires = new Date(arq.expires_at);
          const isExpired = now > expires && arq.status !== "submitted";
          const displayStatus = isExpired ? "expired" : arq.status;
          const sc = statusColor[displayStatus] || statusColor.pending;
          const remStatus = arq.remediation_status ? REMEDIATION_LABEL[arq.remediation_status] : null;
          const fieldsCount = arq.fields_answered_count || 0;
          // Questions the client explicitly answered "I'm not sure" on. Distinct
          // from questions they never reached - these need producer follow-up.
          const notSureList  = Array.isArray(arq.not_sure_fields) ? arq.not_sure_fields : [];
          const notSureCount = arq.not_sure_count ?? notSureList.length;
          // Figure 18: answers the client DID give that we could not normalize
          // (an unreadable date, a NAICS code of the wrong width). These are
          // saved on the form as-is - they need a confirming glance, not a
          // re-ask, which is why they are kept separate from the list above.
          const reviewList   = Array.isArray(arq.review_fields) ? arq.review_fields : [];
          const reviewCount  = arq.review_count ?? reviewList.length;

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

                  {displayStatus === "submitted" && (
                    <div style={{ marginTop: 6, display: "flex", flexDirection: "column", gap: 4 }}>
                      {/* §6.2: post-remediation status chip */}
                      {remStatus && (
                        <span style={{
                          display: "inline-flex", alignItems: "center", gap: 4,
                          fontSize: 10, fontWeight: 700, padding: "2px 8px", borderRadius: 10,
                          border: `1px solid ${remStatus.border}`,
                          background: remStatus.bg, color: remStatus.color,
                          alignSelf: "flex-start",
                        }}>
                          {remStatus.text}
                        </span>
                      )}

                      {/* §6.2 / Req 2: client-filled fields notification */}
                      {fieldsCount > 0 && (
                        <div style={{ fontSize: 11, color: "#047857", display: "flex", alignItems: "center", gap: 4 }}>
                          <span style={{ width: 9, height: 9, background: "rgb(187,247,208)", border: "1px solid #86efac", borderRadius: 2, display: "inline-block", flexShrink: 0 }} />
                          {fieldsCount} field{fieldsCount !== 1 ? "s" : ""} filled by client - highlighted in green on the form
                        </div>
                      )}

                      {/* Client explicitly could not answer these - follow up */}
                      {notSureCount > 0 && (
                        <div style={{ fontSize: 11, color: "#92400e", background: "#fffbeb", border: "1px solid #fde68a", borderRadius: 6, padding: "6px 8px" }}>
                          <div style={{ fontWeight: 700, marginBottom: notSureList.length ? 4 : 0 }}>
                            {notSureCount} question{notSureCount !== 1 ? "s" : ""} the client wasn't sure about - needs your follow-up
                          </div>
                          {notSureList.slice(0, 5).map((item, i) => (
                            <div key={i} style={{ color: "#b45309", lineHeight: 1.45 }}>
                              • {typeof item === "string" ? item : (item.question || item.field_name)}
                            </div>
                          ))}
                          {notSureList.length > 5 && (
                            <div style={{ color: "#b45309", marginTop: 2 }}>
                              + {notSureList.length - 5} more
                            </div>
                          )}
                        </div>
                      )}

                      {/* Saved, but the format was unexpected - confirm these */}
                      {reviewCount > 0 && (
                        <div style={{ fontSize: 11, color: "#9a3412", background: "#fff7ed", border: "1px solid #fed7aa", borderRadius: 6, padding: "6px 8px" }}>
                          <div style={{ fontWeight: 700, marginBottom: reviewList.length ? 4 : 0 }}>
                            {reviewCount} answer{reviewCount !== 1 ? "s" : ""} saved but worth confirming
                          </div>
                          {reviewList.slice(0, 5).map((item, i) => (
                            <div key={i} style={{ color: "#c2410c", lineHeight: 1.45 }}>
                              • {item.question || item.field_name}
                              {item.value ? ` - client entered "${item.value}"` : ""}
                              {item.reason ? ` (${item.reason})` : ""}
                            </div>
                          ))}
                          {reviewList.length > 5 && (
                            <div style={{ color: "#c2410c", marginTop: 2 }}>
                              + {reviewList.length - 5} more
                            </div>
                          )}
                        </div>
                      )}

                      {!remStatus && fieldsCount === 0 && notSureCount === 0 && reviewCount === 0 && (
                        <div style={{ fontSize: 11, color: "#047857" }}>
                          Scores and form data updated - reload session to view changes
                        </div>
                      )}
                    </div>
                  )}
                </div>
                <span style={{ fontSize: 11, fontWeight: 600, padding: "2px 8px", borderRadius: 12, border: `1px solid ${sc.border}`, background: sc.bg, color: sc.color, flexShrink: 0 }}>
                  {displayStatus === "submitted" ? "✓ Submitted" : displayStatus === "expired" ? "Expired" : "Pending"}
                </span>
              </div>

              {/* Figure 21: the producer's read-only view of exactly what the
                  client sent. Previously there was no way to see the answers
                  themselves anywhere in this panel - only the follow-up lists. */}
              {displayStatus === "submitted" && (
                <button
                  onClick={() => setReceiptFor(arq)}
                  style={{ marginTop: 8, fontSize: 11, fontWeight: 600, color: "#0f172a", background: "none", border: "1px solid #cbd5e1", borderRadius: 6, padding: "3px 10px", cursor: "pointer" }}
                >
                  View response receipt
                </button>
              )}

              {arq.status === "pending" && !isExpired && (
                <button
                  onClick={() => handleRemind(arq.id)}
                  disabled={reminding === arq.id}
                  style={{ marginTop: 8, fontSize: 11, fontWeight: 600, color: "#4f7cff", background: "none", border: "1px solid #4f7cff", borderRadius: 6, padding: "3px 10px", cursor: reminding === arq.id ? "wait" : "pointer", opacity: reminding === arq.id ? 0.6 : 1 }}
                >
                  {reminding === arq.id ? "Sending…" : "Send Reminder"}
                  {arq.reminder_count > 0 && ` (${arq.reminder_count} sent)`}
                </button>
              )}
            </div>
          );
        })}
      </div>

      {receiptFor && (
        <ARQReceiptModal
          arqId={receiptFor.id}
          clientLabel={receiptFor.client_name ? `${receiptFor.client_name} (${receiptFor.email})` : receiptFor.email}
          onClose={() => setReceiptFor(null)}
        />
      )}
    </div>
  );
}
