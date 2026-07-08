import { useState } from "react";
import { downloadLicenseAudit } from "../../api/adminApi";
import { inputStyle, labelStyle, AdminMsg } from "./adminModalStyles";

export default function AdminAuditExportModal({ onClose }) {
  const [org, setOrg] = useState("");
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const [exporting, setExporting] = useState(false);
  const [msg, setMsg] = useState(null);

  const doExport = async (format) => {
    setExporting(true); setMsg(null);
    const { ok, status } = await downloadLicenseAudit({
      format, organization: org.trim(), since: since.trim(), until: until.trim(),
    });
    setExporting(false);
    if (ok) setMsg({ ok: true, text: `Export downloaded (${format.toUpperCase()}).` });
    else setMsg({ ok: false, text: status === 403 ? "Admin access required." : "Export failed. Please try again." });
  };

  return (
    <div className="modal-overlay" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal-content" style={{ maxWidth: 460 }} onClick={(e) => e.stopPropagation()}>
        <button className="modal-close" onClick={onClose}>✕</button>
        <div className="modal-inner">
          <h2 className="step-title" style={{ marginBottom: 6 }}>Audit Export</h2>
          <p className="step-subtitle" style={{ marginBottom: 20 }}>
            Download every ACORD license confirmation and reset event for compliance. Filters are optional.
          </p>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 16 }}>
            <div style={{ gridColumn: "1 / -1" }}>
              <label style={labelStyle}>Organization (optional)</label>
              <input type="text" value={org} placeholder="Any organization" onChange={(e) => setOrg(e.target.value)} style={inputStyle} />
            </div>
            <div>
              <label style={labelStyle}>Since (optional)</label>
              <input type="date" value={since} onChange={(e) => setSince(e.target.value)} style={inputStyle} />
            </div>
            <div>
              <label style={labelStyle}>Until (optional)</label>
              <input type="date" value={until} onChange={(e) => setUntil(e.target.value)} style={inputStyle} />
            </div>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <button className="btn btn-modal-primary btn-block" onClick={() => doExport("csv")} disabled={exporting}>
              {exporting ? "Preparing..." : "Download CSV"}
            </button>
            <button className="btn btn-modal-secondary btn-block" onClick={() => doExport("json")} disabled={exporting}>
              Download JSON
            </button>
          </div>
          <AdminMsg msg={msg} />
        </div>
      </div>
    </div>
  );
}
