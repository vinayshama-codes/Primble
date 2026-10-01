import { formSignatureLine, fmtDate } from "../../utils/applicantSignature";

// The producer's view of the applicant's signature (Orbin item 14, 1 Oct 2026):
// where each form stands. The client signs it as a question in the client
// questionnaire (arq/SignatureQuestion), with the pad the producer uses.

export function SignatureStatusList({ status, onRefresh }) {
  const forms = status?.forms || [];
  const pending = (status?.requests || []).find((r) => r.status === "pending" && !r.expired);
  if (!forms.length) return null;
  return (
    <div style={{ fontSize: 12 }}>
      {forms.map((f) => (
        <div key={f.form_id} style={{ display: "flex", gap: 8, padding: "5px 0", borderBottom: "1px solid #f1f5f9", alignItems: "baseline" }}>
          <span style={{ fontWeight: 600, color: "#1e293b", minWidth: 74 }}>{f.label}</span>
          <span style={{ color: f.state === "signed" ? "#15803d" : f.state === "stale" ? "#b45309" : "#64748b" }}>{formSignatureLine(f)}</span>
        </div>
      ))}
      {pending && (
        <div style={{ marginTop: 6, color: "#64748b" }}>
          Waiting for {pending.client_name || pending.email} (asked {fmtDate(pending.created_at)}).
        </div>
      )}
      {onRefresh && (
        <button type="button" onClick={onRefresh}
          style={{ marginTop: 6, background: "none", border: "none", padding: 0, color: "#94a3b8", textDecoration: "underline", cursor: "pointer", fontSize: 11 }}>
          Refresh
        </button>
      )}
    </div>
  );
}
