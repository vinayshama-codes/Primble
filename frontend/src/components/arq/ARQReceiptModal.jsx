// ARQReceiptModal.jsx - Figure 21: read-only client response receipt.
//
// Renders the immutable record of what a client submitted. Deliberately has NO
// editing affordance of any kind: no inputs, no save, no delete. The producer's
// working copy of these values lives on the form; this is the record of what
// was said, and a record you can edit is not a record.
import { useEffect, useState } from "react";
import { getArqReceipt } from "../../api/arqApi";

const KIND_STYLE = {
  answer:   { label: "",                  color: "#0f172a", bg: "transparent" },
  schedule: { label: "Table",             color: "#0f172a", bg: "transparent" },
  not_sure: { label: "Not sure",          color: "#92400e", bg: "#fffbeb" },
  blank:    { label: "Not answered",      color: "#94a3b8", bg: "transparent" },
};

const formatDate = (iso) => {
  if (!iso) return "-";
  const d = new Date(iso);
  return isNaN(d) ? "-" : d.toLocaleString("en-US", {
    month: "short", day: "numeric", year: "numeric", hour: "2-digit", minute: "2-digit",
  });
};

export default function ARQReceiptModal({ arqId, clientLabel, onClose }) {
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState("");
  const [receipt, setReceipt] = useState(null);
  const [reason, setReason]   = useState("");
  // Blank questions are kept in the payload (they are part of the record: the
  // client WAS asked) but hidden by default so the useful rows are not buried.
  const [showBlanks, setShowBlanks] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const { ok, data } = await getArqReceipt(arqId);
        if (cancelled) return;
        if (!ok || !data.success) {
          setError(data?.detail || "Could not load the receipt.");
        } else if (!data.receipt) {
          setReason(data.reason || "no_receipt");
        } else {
          setReceipt(data.receipt);
        }
      } catch {
        if (!cancelled) setError("Network error loading the receipt.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [arqId]);

  const items = receipt?.items || [];
  const shown = showBlanks ? items : items.filter((i) => i.kind !== "blank");
  const blankCount = items.filter((i) => i.kind === "blank").length;

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed", inset: 0, background: "rgba(15,23,42,0.45)",
        zIndex: 2000, display: "flex", alignItems: "center", justifyContent: "center",
        padding: 16,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "#fff", borderRadius: 14, width: "min(680px, 100%)",
          maxHeight: "85vh", display: "flex", flexDirection: "column",
          boxShadow: "0 20px 60px rgba(0,0,0,0.25)", overflow: "hidden",
        }}
      >
        {/* Header */}
        <div style={{ padding: "16px 20px", borderBottom: "1px solid #e2e8f0", display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12 }}>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: 15, fontWeight: 700, color: "#0f172a" }}>Client Response Receipt</div>
            <div style={{ fontSize: 12, color: "#64748b", marginTop: 2 }}>
              {receipt
                ? `${receipt.client_name || receipt.client_email || clientLabel} · Submitted ${formatDate(receipt.submitted_at)}`
                : clientLabel}
            </div>
            {receipt?.receipt_ref && (
              <div style={{ fontSize: 11, color: "#94a3b8", marginTop: 3, fontFamily: "monospace" }}>
                Ref {receipt.receipt_ref}
              </div>
            )}
          </div>
          <button
            onClick={onClose}
            aria-label="Close receipt"
            style={{ background: "none", border: "none", fontSize: 20, lineHeight: 1, color: "#94a3b8", cursor: "pointer", padding: "2px 6px" }}
          >
            ✕
          </button>
        </div>

        {/* Body */}
        <div style={{ padding: "14px 20px", overflowY: "auto", flex: 1 }}>
          {loading && <div style={{ fontSize: 13, color: "#64748b" }}>Loading receipt...</div>}

          {!loading && error && (
            <div style={{ fontSize: 13, color: "#991b1b", background: "#fef2f2", border: "1px solid #fecaca", borderRadius: 8, padding: "10px 12px" }}>
              {error}
            </div>
          )}

          {!loading && !error && !receipt && (
            <div style={{ fontSize: 13, color: "#475569", background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: 8, padding: "12px 14px", lineHeight: 1.55 }}>
              {reason === "not_submitted"
                ? "This questionnaire has not been submitted yet, so there is nothing to receipt."
                : "No receipt was recorded for this submission. Questionnaires submitted before response receipts were introduced do not have one - the answers themselves are still on the form."}
            </div>
          )}

          {!loading && receipt?.unreadable && (
            <div style={{ fontSize: 13, color: "#92400e", background: "#fffbeb", border: "1px solid #fde68a", borderRadius: 8, padding: "10px 12px", lineHeight: 1.55 }}>
              This receipt exists but could not be decrypted, which usually means the
              encryption key changed since it was written. Nothing was lost - contact
              support before rotating keys again.
            </div>
          )}

          {!loading && receipt && !receipt.unreadable && (
            <>
              <div style={{ display: "flex", gap: 14, flexWrap: "wrap", fontSize: 12, color: "#475569", marginBottom: 12 }}>
                <span><strong style={{ color: "#0f172a" }}>{receipt.answered_count}</strong> answered</span>
                <span><strong style={{ color: "#0f172a" }}>{receipt.item_count}</strong> asked</span>
                {receipt.not_sure_count > 0 && (
                  <span style={{ color: "#92400e" }}><strong>{receipt.not_sure_count}</strong> not sure</span>
                )}
                {receipt.review_count > 0 && (
                  <span style={{ color: "#9a3412" }}><strong>{receipt.review_count}</strong> worth confirming</span>
                )}
              </div>

              {shown.map((it, i) => {
                const st = KIND_STYLE[it.kind] || KIND_STYLE.answer;
                return (
                  <div
                    key={`${it.field_name}-${i}`}
                    style={{
                      padding: "9px 10px", borderRadius: 7, background: st.bg,
                      borderBottom: i < shown.length - 1 ? "1px solid #f1f5f9" : "none",
                    }}
                  >
                    <div style={{ fontSize: 11, color: "#64748b", lineHeight: 1.45, marginBottom: 3 }}>
                      {it.question || it.field_name}
                    </div>

                    {it.kind === "schedule" ? (
                      <div style={{ fontSize: 12.5, color: "#0f172a", fontWeight: 600 }}>
                        {it.row_count} row{it.row_count !== 1 ? "s" : ""} provided
                        {it.rows_truncated && (
                          <span style={{ fontWeight: 400, color: "#92400e" }}> (first {it.rows?.length} shown)</span>
                        )}
                        <div style={{ marginTop: 5, fontSize: 11, color: "#475569", fontWeight: 400, maxHeight: 120, overflowY: "auto" }}>
                          {(it.rows || []).map((r, ri) => (
                            <div key={ri} style={{ lineHeight: 1.5 }}>
                              {ri + 1}. {Object.values(r || {}).filter(Boolean).join(" · ") || "(empty)"}
                            </div>
                          ))}
                        </div>
                      </div>
                    ) : (
                      <div style={{ fontSize: 12.5, color: st.color, fontWeight: it.kind === "answer" ? 600 : 500, wordBreak: "break-word", lineHeight: 1.45 }}>
                        {it.kind === "answer" ? it.value : st.label}
                      </div>
                    )}

                    {it.review_reason && (
                      <div style={{ fontSize: 11, color: "#9a3412", marginTop: 3 }}>
                        Worth confirming - {it.review_reason}
                      </div>
                    )}
                  </div>
                );
              })}

              {blankCount > 0 && (
                <button
                  onClick={() => setShowBlanks((v) => !v)}
                  style={{ marginTop: 10, fontSize: 11, fontWeight: 600, color: "#4f7cff", background: "none", border: "1px solid #cbd5e1", borderRadius: 6, padding: "4px 10px", cursor: "pointer" }}
                >
                  {showBlanks ? "Hide" : "Show"} {blankCount} unanswered question{blankCount !== 1 ? "s" : ""}
                </button>
              )}
            </>
          )}
        </div>

        {/* Footer */}
        <div style={{ padding: "10px 20px", borderTop: "1px solid #e2e8f0", display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: 10.5, color: "#94a3b8" }}>
            Read-only record - cannot be edited or deleted
          </span>
          <button
            onClick={onClose}
            style={{ fontSize: 12, fontWeight: 600, color: "#fff", background: "#0f172a", border: "none", borderRadius: 7, padding: "7px 16px", cursor: "pointer" }}
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
