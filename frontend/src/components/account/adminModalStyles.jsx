// Shared inline styles for admin modals (AdminResetLicenseModal, AdminAuditExportModal,
// and any future admin sections added to the AdminNavDropdown).
export const inputStyle = {
  width: "100%", padding: "9px 11px", fontSize: 14, border: "1px solid #d1d5db",
  borderRadius: 8, outline: "none", boxSizing: "border-box",
};
export const labelStyle = { fontSize: 12, fontWeight: 600, color: "#64748b", marginBottom: 5, display: "block" };

export function AdminMsg({ msg }) {
  if (!msg) return null;
  return (
    <div style={{
      marginTop: 10, fontSize: 13, padding: "8px 10px", borderRadius: 8,
      background: msg.ok ? "#ecfdf5" : "#fef2f2",
      color: msg.ok ? "#065f46" : "#991b1b",
      border: `1px solid ${msg.ok ? "#a7f3d0" : "#fecaca"}`,
    }}>
      {msg.text}
    </div>
  );
}
