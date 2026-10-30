import { useState } from "react";
import { API_BASE } from "../../../config/constants";

// "View values read from the form" (29 Oct 2026, ASG_TRANSCRIBER.md "Keep
// everything"): every box ACORD Transcriber read off an uploaded ACORD form is
// kept (encrypted) on the document. This link lists them in two groups: the
// values used in this package (each with what it feeds) and the rest, read from
// the form and kept, never scored. Display only - the server decides the groups.

async function fetchFormValues(sessionId, docId) {
  const res = await fetch(
    `${API_BASE}/api/session/${encodeURIComponent(sessionId)}/documents/${encodeURIComponent(docId)}/form-values`,
    { credentials: "include" });
  if (!res.ok) throw new Error(res.status === 404 ? "No values read from a form are kept for this document." : "Could not load the values.");
  return res.json();
}

const LINK_STYLE = {
  fontSize: 11, color: "#0f766e", fontWeight: 600, background: "none", border: "none",
  padding: 0, cursor: "pointer", textDecoration: "underline",
};

function confidenceText(c) {
  return typeof c === "number" ? `${Math.round(c)}%` : "";
}

function ValueRows({ rows, showUse }) {
  if (!rows.length) return <div style={{ fontSize: 12, color: "#64748b", padding: "4px 0" }}>None.</div>;
  return (
    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
      <thead>
        <tr style={{ textAlign: "left", color: "#475569" }}>
          <th style={{ padding: "4px 6px" }}>Box</th>
          <th style={{ padding: "4px 6px" }}>Value</th>
          {showUse && <th style={{ padding: "4px 6px" }}>Used for</th>}
          <th style={{ padding: "4px 6px" }}>Page</th>
          <th style={{ padding: "4px 6px" }}>Confidence</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={`${r.form_id}-${r.box}-${i}`} style={{ borderTop: "1px solid #e2e8f0", verticalAlign: "top" }}>
            <td style={{ padding: "4px 6px" }} title={r.box}>{r.label}</td>
            <td style={{ padding: "4px 6px", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{r.value}</td>
            {showUse && <td style={{ padding: "4px 6px", color: "#475569" }}>{r.used_for}</td>}
            <td style={{ padding: "4px 6px" }}>{r.page ?? ""}</td>
            <td style={{ padding: "4px 6px" }}>{confidenceText(r.confidence)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function FormValuesLink({ sessionId, doc }) {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  if (!sessionId || !doc?.doc_id || !doc?.reader_values) return null;

  const show = async () => {
    setOpen(true);
    if (data || loading) return;
    setLoading(true);
    setError("");
    try {
      setData(await fetchFormValues(sessionId, doc.doc_id));
    } catch (e) {
      setError(e.message || "Could not load the values.");
    } finally {
      setLoading(false);
    }
  };

  const forms = (data?.forms || []).filter((f) => !f.rejected);
  return (
    <>
      <button type="button" style={LINK_STYLE} onClick={show} data-testid="doc-form-values-link">
        View values read from the form
      </button>
      {open && (
        <div role="dialog" aria-modal="true" aria-label="Values read from the form"
             onClick={() => setOpen(false)}
             style={{ position: "fixed", inset: 0, background: "rgba(15,23,42,0.45)", zIndex: 2000,
                      display: "flex", alignItems: "center", justifyContent: "center", padding: 16 }}>
          <div onClick={(e) => e.stopPropagation()}
               style={{ background: "#fff", borderRadius: 10, width: "min(860px, 100%)", maxHeight: "85vh",
                        overflowY: "auto", padding: 18, boxShadow: "0 20px 50px rgba(15,23,42,0.25)" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
              <div style={{ fontWeight: 700, fontSize: 15, flex: 1 }}>Values read from the form</div>
              <button type="button" onClick={() => setOpen(false)}
                      style={{ border: "1px solid #cbd5e1", background: "#fff", borderRadius: 6, padding: "3px 10px", cursor: "pointer" }}>
                Close
              </button>
            </div>
            <div style={{ fontSize: 12, color: "#475569", marginBottom: 10 }}>
              {doc.filename}
              {forms.length > 0 && ` - ${forms.map((f) => `ACORD ${f.form_number}${f.edition ? ` (${f.edition})` : ""}`).join(", ")}`}
              . ACORD Transcriber read these boxes. Values are marked for verification.
            </div>
            {loading && <div style={{ fontSize: 12 }}>Loading...</div>}
            {error && <div style={{ fontSize: 12, color: "#b91c1c" }}>{error}</div>}
            {data && (
              <>
                <div style={{ fontWeight: 700, fontSize: 13, margin: "8px 0 4px" }}>
                  Used in this package ({data.used.length})
                </div>
                <ValueRows rows={data.used} showUse />
                <div style={{ fontWeight: 700, fontSize: 13, margin: "14px 0 2px" }}>
                  Read from the form ({data.read.length})
                </div>
                <div style={{ fontSize: 11, color: "#64748b", marginBottom: 4 }}>
                  Kept with the document for reference. These values are not used in the package or the score.
                </div>
                <ValueRows rows={data.read} />
                {data.unticked > 0 && (
                  <div style={{ fontSize: 11, color: "#64748b", marginTop: 8 }}>
                    {data.unticked} box{data.unticked === 1 ? "" : "es"} left unticked on the form.
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      )}
    </>
  );
}
