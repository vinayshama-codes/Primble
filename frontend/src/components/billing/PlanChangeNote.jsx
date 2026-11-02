import { useState } from "react";
import { CHANGE_PLAN_NOTE, needsBillingFix } from "../../utils/billing";
import { usePageRestore } from "../../hooks/usePageRestore";

function useBillingButton(openBillingPortal) {
  const [opening, setOpening] = useState(false);
  // Back from Stripe restores this page frozen mid-redirect - clear the spinner.
  usePageRestore(() => setOpening(false));
  const open = async () => {
    if (!openBillingPortal || opening) return;
    setOpening(true);
    try { await openBillingPortal(); }
    finally { setOpening(false); }
  };
  return [opening, open];
}

const linkBtn = {
  background: "none", border: "none", padding: 0, color: "var(--primary)",
  fontWeight: 600, cursor: "pointer", fontSize: 13, textDecoration: "underline",
};

// A user who already pays never starts a checkout (2 Nov 2026): plan changes go
// through support, and Manage billing covers the card, invoices and cancelling.
export function PlanChangeNote({ openBillingPortal, style }) {
  const [opening, open] = useBillingButton(openBillingPortal);
  return (
    <p style={{ fontSize: 13, color: "var(--text-secondary)", margin: 0, ...style }}>
      {CHANGE_PLAN_NOTE}
      {openBillingPortal && (
        <>
          {" "}
          <button type="button" onClick={open} disabled={opening} style={linkBtn}>
            {opening ? "Opening…" : "Manage billing"}
          </button>
        </>
      )}
    </p>
  );
}

// A checkout the server refused (409 / 503): its own words, never a stuck spinner.
// An unpaid last invoice is fixed in Manage billing, so that one offers it.
export function CheckoutError({ error, openBillingPortal, style }) {
  const [opening, open] = useBillingButton(openBillingPortal);
  if (!error || !error.message) return null;
  return (
    <div role="alert" style={{ background: "#fef2f2", border: "1px solid #fecaca", borderRadius: 10, padding: "10px 14px", fontSize: 13, color: "#b91c1c", textAlign: "center", ...style }}>
      {error.message}
      {needsBillingFix(error.code) && openBillingPortal && (
        <>
          {" "}
          <button type="button" onClick={open} disabled={opening} style={{ ...linkBtn, color: "inherit", fontWeight: 700 }}>
            {opening ? "Opening…" : "Manage billing"}
          </button>
        </>
      )}
    </div>
  );
}
