import { useState, useEffect, useRef } from "react";

const ChevronDown = ({ rotated }) => (
  <svg width="12" height="12" viewBox="0 0 12 12" fill="none"
    style={{ flexShrink: 0, marginLeft: 4, transition: "transform 0.2s", transform: rotated ? "rotate(180deg)" : "none" }}>
    <path d="M2 4l4 4 4-4" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

// Top-nav "Admin" button + dropdown, shown only to platform admins (email in
// ADMIN_EMAILS - see Header.jsx isAdmin gating). New admin sections should be
// added here as additional items, each opening its own focused modal, rather
// than growing one combined modal.
export default function AdminNavDropdown({ onResetLicense, onAuditExport, onManageAdmins }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    function handleClickOutside(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  return (
    <div className="udrop-root" ref={ref}>
      <button
        className="header-dashboard-btn admin-nav-btn"
        onClick={() => setOpen(o => !o)}
      >
        Admin
        <ChevronDown rotated={open} />
      </button>

      {open && (
        <div className="udrop-panel">
          <div className="udrop-section">
            <div className="udrop-actions">
              <button
                className="udrop-item"
                onClick={() => { setOpen(false); onResetLicense(); }}
              >
                <span className="udrop-item-label">Reset License Confirmation</span>
              </button>
              <button
                className="udrop-item"
                onClick={() => { setOpen(false); onAuditExport(); }}
              >
                <span className="udrop-item-label">Audit Export</span>
              </button>
              <button
                className="udrop-item"
                onClick={() => { setOpen(false); onManageAdmins(); }}
              >
                <span className="udrop-item-label">Manage Admins</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
