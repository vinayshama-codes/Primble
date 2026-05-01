const _style = document.createElement("style");
_style.textContent = `
  .global-loading-overlay {
    position: fixed; inset: 0; background: rgba(255,255,255,0.95);
    display: flex; flex-direction: column; align-items: center;
    justify-content: center; z-index: 9999;
  }
  .payment-failed-badge {
    display: flex; align-items: center; gap: 6px;
    background: #fef2f2; color: #991b1b; font-size: 13px;
    font-weight: 600; padding: 4px 10px; border-radius: 6px;
    border: 1px solid #fca5a5;
  }
  .upgrade-modal-wide { max-width: 1160px !important; width: 96vw !important; }
  .upgrade-plan-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 18px; align-items: start; }
  @media (max-width: 900px) { .upgrade-plan-grid { grid-template-columns: repeat(2, 1fr); } }
  @media (max-width: 520px) { .upgrade-plan-grid { grid-template-columns: 1fr; } }
  @keyframes spin { to { transform: rotate(360deg); } }
  .payment-status-banner { padding:10px 16px; border-radius:8px; font-size:13px; font-weight:500; margin-bottom:10px; }
  .payment-status-banner a { color:inherit; font-weight:700; text-decoration:underline; }
  .payment-status-failed   { background:#fef3c7; color:#92400e; border:1px solid #fcd34d; }
  .payment-status-locked   { background:#fef9c3; color:#713f12; border:1px solid #fde047; }
  .payment-status-suspended{ background:#fee2e2; color:#7f1d1d; border:1px solid #fca5a5; }
  .payment-status-archived { background:#f1f5f9; color:#334155; border:1px solid #cbd5e1; }
  .upload-area-blocked { opacity:0.45; pointer-events:none; filter:grayscale(60%); }
  .upload-blocked-msg { background:#fee2e2; color:#7f1d1d; border:1px solid #fca5a5; border-radius:8px; padding:12px 16px; font-size:13px; font-weight:500; margin-bottom:12px; text-align:center; }
  .upload-blocked-msg a { color:#7f1d1d; font-weight:700; }
  .billing-toggle {
    display: flex; gap: 4px; background: #f1f5f9; border-radius: 8px;
    padding: 4px; margin: 12px auto 20px; width: fit-content;
  }
  .billing-option {
    padding: 6px 18px; border-radius: 6px; border: none; cursor: pointer;
    font-size: 14px; font-weight: 500; color: #64748b; background: transparent;
    transition: all 0.2s;
  }
  .billing-option.billing-active {
    background: #fff; color: #1e293b; font-weight: 600;
    box-shadow: 0 1px 4px rgba(0,0,0,0.12);
  }
  .billing-save {
    font-size: 11px; color: #16a34a; font-weight: 700;
    background: #dcfce7; padding: 1px 5px; border-radius: 4px; margin-left: 4px;
  }
  .plan-cards {
    display: flex; gap: 16px; align-items: stretch; margin: 0 0 16px;
    flex-wrap: wrap; justify-content: center;
  }
  .plan-card {
    flex: 1; min-width: 200px; max-width: 240px; border: 1.5px solid #e2e8f0;
    border-radius: 12px; padding: 20px 16px; position: relative;
    display: flex; flex-direction: column; gap: 6px; background: #fff;
  }
  .plan-card-highlight { border-color: #2563eb; box-shadow: 0 0 0 2px #dbeafe; }
  .plan-popular {
    position: absolute; top: -12px; left: 50%; transform: translateX(-50%);
    background: #2563eb; color: #fff; font-size: 11px; font-weight: 700;
    padding: 2px 12px; border-radius: 20px; white-space: nowrap;
  }
  .plan-name { font-size: 16px; font-weight: 700; color: #1e293b; }
  .plan-price { display: flex; align-items: baseline; gap: 2px; margin-top: 4px; }
  .plan-price-amount { font-size: 32px; font-weight: 800; color: #1e293b; }
  .plan-price-period { font-size: 14px; color: #64748b; }
  .plan-price-custom { font-size: 24px; font-weight: 700; color: #1e293b; }
  .plan-billed-note { font-size: 11px; color: #64748b; margin-top: -2px; }
  .plan-price-sub { font-size: 11px; color: #94a3b8; margin-top: 2px; }
  .plan-packages { font-size: 13px; font-weight: 600; color: #2563eb; margin-top: 4px; }
  .plan-overage { font-size: 11px; color: #94a3b8; }
  .plan-features { list-style: none; padding: 0; margin: 10px 0; flex: 1; }
  .plan-features li { font-size: 12px; color: #475569; padding: 2px 0; }
  .upgrade-footer-note { font-size: 11px; color: #94a3b8; text-align: center; }
  .upgrade-stage-overlay {
    position: fixed; inset: 0; background: rgba(255,255,255,0.97);
    display: flex; flex-direction: column; align-items: center;
    justify-content: center; z-index: 99999; gap: 24px;
  }
  .upgrade-stage-spinner {
    width: 56px; height: 56px; border: 4px solid #e2e8f0;
    border-top-color: #2563eb; border-radius: 50%;
    animation: spin 0.9s linear infinite;
  }
  .upgrade-stage-steps { display: flex; flex-direction: column; gap: 10px; align-items: center; }
  .upgrade-stage-step {
    font-size: 14px; font-weight: 500; color: #94a3b8;
    display: flex; align-items: center; gap: 8px; transition: all 0.4s;
  }
  .upgrade-stage-step.active { color: #1e293b; font-weight: 700; font-size: 16px; }
  .upgrade-stage-step.done { color: #10b981; }
  .upgrade-stage-dot { width: 8px; height: 8px; border-radius: 50%; background: #e2e8f0; flex-shrink: 0; }
  .upgrade-stage-step.active .upgrade-stage-dot { background: #2563eb; }
  .upgrade-stage-step.done .upgrade-stage-dot { background: #10b981; }
  .overage-inline-notice {
    background: #fefce8; border: 1px solid #fde047; border-radius: 8px;
    padding: 10px 14px; font-size: 12px; color: #713f12; margin-bottom: 10px;
    display: flex; align-items: center; gap: 8px;
  }
`;
if (!document.head.querySelector("#acordly-v12-styles")) {
  _style.id = "acordly-v12-styles";
  document.head.appendChild(_style);
}