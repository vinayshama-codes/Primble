//AcordModal.jsx
import { useState, useEffect, useRef, forwardRef, useImperativeHandle } from "react";
import { API_BASE } from "../../config/constants";
import { gradeColor, barColor, sqsGradeFromScore } from "../../utils/formatters";
import ProcessStageOverlay from "../overlays/ProcessStageOverlay";
import UploadProgressOverlay from "../overlays/UploadProgressOverlay";
import PDFJsViewer from "./PDFJsViewer";

const SQS_LABELS = {
  structural_completeness: "Structural Completeness",
  exposure_consistency:    "Exposure Consistency",
  property_integrity:      "Property Integrity",
  loss_history_alignment:  "Loss History",
  umbrella_limit_adequacy: "Umbrella Adequacy",
  narrative_quality:       "Narrative Quality",
};
const SQS_WEIGHTS = {
  structural_completeness: 25, exposure_consistency: 25,
  property_integrity: 15,      loss_history_alignment: 15,
  umbrella_limit_adequacy: 10, narrative_quality: 10,
};

const PACKAGE_PILLAR_LABELS = {
  // Spec-compliant pillar keys returned by calculate_package_sqs.
  structural_completeness: "Structural Completeness",
  exposure_consistency:    "Exposure Consistency",
  property_integrity:      "Property Integrity",
  loss_history_alignment:  "Loss History",
  umbrella_limit_adequacy: "Umbrella Adequacy",
  narrative_quality:       "Narrative Quality",
  // Figure 11: producer-friendly label for the synthetic hard-stops row (client wording).
  hard_stops_present:      "Hard stops need attention",
  // Legacy keys (older session payloads) kept for backward-compat display.
  data_integrity: "Data Integrity",
  exposure_cope:  "Exposure & COPE",
  consistency:    "Cross-Form Consistency",
  loss_history:   "Loss History",
  narrative:      "Narrative Quality",
};

// ── §6 SQS transparency: category breakdown, evidence, umbrella states ──────
const CAT_STATUS_COLOR = {
  ok: "#10b981", consistent: "#10b981", partial: "#f59e0b",
  review_recommended: "#f59e0b", needs_review: "#f59e0b",
  missing: "#ef4444", not_found: "#94a3b8", conflict_found: "#ef4444",
  insufficient: "#ef4444", not_applicable: "#94a3b8", computed_separately: "#94a3b8",
};
// Sub-row completeness label - replaces raw percentages on the expandable pillar
// detail so users read a status word (and never try to average the %s into the
// weighted headline). Scoring is unchanged; this is display-only.
function catCompleteness(score) {
  if (score === null || score === undefined) return { label: "Not applicable", color: "#94a3b8" };
  if (score >= 90) return { label: "Complete", color: "#10b981" };
  if (score >= 75) return { label: "Strong",   color: "#10b981" };
  if (score >= 50) return { label: "Partial",  color: "#f59e0b" };
  if (score >= 25) return { label: "Limited",  color: "#f59e0b" };
  if (score >= 1)  return { label: "Minimal",  color: "#ef4444" };
  return { label: "Missing", color: "#ef4444" };
}

const EVIDENCE_LABEL_DISPLAY = {
  extracted_from_source: "Extracted from document",
  confirmed_by_user: "Confirmed by user",
  stated_in_narrative: "Stated in narrative",
  inferred: "Inferred from business class",
  not_found: "Not found",
  conflicting: "Conflicting",
  not_applicable: "Not applicable",
  requires_supporting_doc: "Requires supporting doc",
};
// Only the "notable" (non-default) evidence labels get a chip - Extracted/Not found
// are already implied by the score bars, so surfacing them would just add noise.
const EVIDENCE_LABEL_COLOR = {
  confirmed_by_user:       { bg: "#ecfdf5", fg: "#047857" },
  stated_in_narrative:     { bg: "#eff6ff", fg: "#1d4ed8" },
  conflicting:             { bg: "#fef2f2", fg: "#dc2626" },
  requires_supporting_doc: { bg: "#fffbeb", fg: "#b45309" },
  inferred:                { bg: "#f5f3ff", fg: "#6d28d9" },
};

// ── Figure 10 score provenance ───────────────────────────────────────────────
// Click a credited positive signal to see WHY it helped the score. Option (a):
// Source + Confidence + Rule, no "how to strengthen" line. `sourceFact` (when set)
// is a scored fact key used to look up the fact's confidence in evidence_labels;
// it is only set where the signal is driven by exactly that one fact, so the
// confidence can never contradict the signal. Display-only; no scoring impact.
const SIGNAL_PROVENANCE = {
  narrative_attached:      { source: "A narrative document is attached", rule: "A narrative gives underwriters account context and lifts Narrative Quality." },
  operations_description:  { sourceFact: "operations_description", source: "Operations description provided", rule: "A clear operations description supports exposure and classification." },
  no_losses_stated:        { source: "No known losses stated", rule: "A no-loss statement lifts Loss History. Corroborate with loss runs or a signed no-known-loss letter for full credit." },
  loss_runs_attached:      { source: "Loss runs uploaded", rule: "Uploaded loss runs corroborate loss history - stronger than a narrative statement." },
  years_in_business:       { sourceFact: "years_in_business", source: "Years in business stated", rule: "Time in business is a positive underwriting signal." },
  prior_carrier:           { sourceFact: "prior_carrier", source: "Prior carrier identified", rule: "A named prior carrier strengthens the underwriting picture." },
  coverage_limits:         { source: "Coverage limits identified", rule: "Identified limits support exposure and umbrella checks." },
  locations_identified:    { sourceFact: "locations", source: "Locations identified", rule: "Location detail supports property and exposure scoring." },
  emod_xmod:               { sourceFact: "wc_xmod", source: "EMOD / XMOD provided", rule: "The experience modifier is a key Workers Comp underwriting input." },
  wc_payroll_breakdown:    { sourceFact: "total_payroll", source: "Payroll by WC class code provided", rule: "Payroll by class code supports Workers Comp rating." },
  contractor_coverages:    { source: "Contractor-specific coverages discussed", rule: "Contractor coverage detail improves exposure completeness." },
  existing_program:        { sourceFact: "prior_carrier", source: "Existing insurance program described", rule: "An existing program gives renewal context." },
  submission_urgency:      { source: "Deadline / urgency provided", rule: "Timing context helps prioritize the submission." },
  experienced_management:  { source: "Experienced management (from narrative)", rule: "Management experience is a positive narrative signal." },
  risk_controls_described: { source: "Risk controls described (from narrative)", rule: "Documented risk controls lift Narrative Quality." },
  safety_manual:           { source: "Employer handbook / safety manual (from narrative)", rule: "Safety documentation is a positive risk signal." },
};
// Evidence-basis chip → rule + how-to-improve, keyed by the backend evidence label.
const EVIDENCE_PROV = {
  confirmed_by_user:       { rule: "Confirmed by the user via the questionnaire - the strongest provenance." },
  stated_in_narrative:     { rule: "Asserted in the narrative - a statement, not a corroborated document.", remediation: "Attach a document (loss runs, policy, or schedule) to raise confidence." },
  requires_supporting_doc: { rule: "Not yet corroborated by a document.", remediation: "Attach the supporting document (loss runs, policy, or schedule) to credit this." },
  conflicting:             { rule: "Documents disagree on this value.", remediation: "Resolve the conflict between the source documents before submission." },
  inferred:                { rule: "Inferred by AI from the business class - not read directly from a document.", remediation: "Confirm the value, or upload a document that states it." },
};
// Loss-history state → rule + how-to-improve, keyed by the backend loss_history_state.
const LOSS_STATE_PROV = {
  no_information:                  { direction: "reduced", rule: "No loss-run evidence or attestation on file - Loss History cannot be credited.", remediation: "Request loss runs, or have the client confirm No Known Losses (a signed no-known-loss letter corroborates it)." },
  user_states_no_losses:          { direction: "info",     rule: "The insured attests No Known Losses - credited, but not yet corroborated by a document.", remediation: "Attach loss runs or a signed no-known-loss letter to fully confirm." },
  narrative_states_no_losses:     { direction: "info",     rule: "No losses are stated in the narrative - an assertion, weaker than an attestation.", remediation: "Confirm with the insured, or attach loss runs / a signed no-known-loss letter to corroborate." },
  loss_runs_pending:              { direction: "info",     rule: "Loss runs are requested / pending - the score updates when they arrive.", remediation: "Upload the loss runs once received." },
  loss_runs_uploaded:             { direction: "info",     rule: "Loss runs uploaded - claim years not yet confirmed.", remediation: "Confirm claim years and the valuation date to finalize." },
  loss_runs_parsed:               { direction: "increased", rule: "Loss runs parsed - claim years extracted from the documents." },
  loss_runs_match_insured:        { direction: "increased", rule: "Loss runs match the insured - corroborated evidence." },
  loss_runs_do_not_match:         { direction: "reduced",  rule: "Loss runs do not match the insured - not creditable for this submission.", remediation: "Verify the runs belong to this insured (name + FEIN / policy number)." },
  loss_data_reconciled:           { direction: "increased", rule: "Loss data reconciled - the strongest loss-history evidence." },
  loss_history_conflicting:       { direction: "reduced",  rule: "A no-loss statement is contradicted by actual loss-run claims.", remediation: "Reconcile the attestation with the loss runs before submission." },
  loss_history_pending_validation:{ direction: "info",     rule: "Loss runs parsed but ownership not fully verified.", remediation: "Confirm ownership with a FEIN or policy number." },
};
// Umbrella state → rule + how-to-improve, keyed by the backend umbrella_state.
const UMBRELLA_STATE_PROV = {
  unknown:                        { direction: "reduced",  rule: "Underlying limits not found - umbrella adequacy cannot be confirmed.", remediation: "Provide underlying GL / Auto / EL limits and a schedule of underlying insurance." },
  insufficient_information:       { direction: "reduced",  rule: "Not enough information to confirm umbrella adequacy.", remediation: "Provide underlying limits and the schedule of underlying insurance." },
  umbrella_coverage_present:      { direction: "info",     rule: "Umbrella coverage present - adequacy partially supported." },
  umbrella_coverage_needs_review: { direction: "reduced",  rule: "Umbrella needs review - underlying limits or schedule may be short.", remediation: "Confirm underlying limits meet umbrella attachment, and attach the schedule of underlying insurance." },
  adequately_supported:           { direction: "increased", rule: "Umbrella adequately supported by the underlying limits." },
};

// Build the provenance card data for one clicked score component. Pure; returns
// null when the component has nothing to show. Referenced label maps are declared
// below and resolved at call time (render), never at module init.
function buildProvenance(group, key, pkg) {
  if (!pkg) return null;
  if (group === "signal") {
    const sig = (pkg.positive_signals || []).find(s => s.key === key);
    if (!sig) return null;
    const meta = SIGNAL_PROVENANCE[key] || {};
    let confidence = null;
    if (meta.sourceFact) {
      const lbl = pkg.evidence_labels?.[meta.sourceFact];
      if (lbl && lbl !== "not_found" && lbl !== "not_applicable") confidence = EVIDENCE_LABEL_DISPLAY[lbl] || null;
    }
    return { title: sig.label || key, direction: "increased", source: meta.source || sig.label || key, confidence, rule: meta.rule };
  }
  if (group === "narrative") {
    if (!(key in (pkg.narrative_components || {}))) return null;
    const present = pkg.narrative_components[key];
    const label = NARRATIVE_COMPONENT_LABELS[key] || key;
    return present
      ? { title: label, direction: "increased", source: "Covered in the narrative", rule: "Found in the submitted narrative - credits Narrative Quality." }
      : { title: label, direction: "reduced", rule: "Not found in the narrative - reduces Narrative Quality.", remediation: `Add ${label} to the narrative, or request it from the client via the questionnaire.` };
  }
  if (group === "evidence") {
    const lbl = pkg.evidence_labels?.[key];
    if (!lbl) return null;
    const p = EVIDENCE_PROV[lbl] || {};
    return { title: key.replace(/_/g, " "), direction: lbl === "confirmed_by_user" ? "increased" : "reduced", source: key.replace(/_/g, " "), confidence: EVIDENCE_LABEL_DISPLAY[lbl] || lbl, rule: p.rule, remediation: p.remediation };
  }
  if (group === "loss_history") {
    const st = pkg.loss_history_state;
    if (!st) return null;
    const p = LOSS_STATE_PROV[st] || {};
    return { title: "Loss History", direction: p.direction || "info", confidence: LOSS_HISTORY_STATE_LABEL[st] || st, rule: p.rule, remediation: p.remediation };
  }
  if (group === "umbrella") {
    const st = pkg.umbrella_state;
    if (!st) return null;
    const p = UMBRELLA_STATE_PROV[st] || {};
    return { title: "Umbrella", direction: p.direction || "info", confidence: UMBRELLA_STATE_LABEL[st] || st, rule: p.rule, remediation: p.remediation };
  }
  return null;
}

// Fixed-position provenance popover. Mirrors InfoTip: computed from the trigger's
// rect so it is never clipped by the sidebar's overflow, and works identically on
// iOS / Android / desktop. Closes on the "X", on Escape, on scroll/resize, and on
// any pointer-down outside the popover AND outside a provenance trigger (so a click
// on another chip switches straight to that chip's card instead of just closing).
function ProvenancePopover({ data, pos, onClose }) {
  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    const onScroll = () => onClose();
    const onDown = (e) => {
      const t = e.target;
      if (t && t.closest && (t.closest("[data-provpop]") || t.closest("[data-provtrigger]"))) return;
      onClose();
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", onScroll);
    window.addEventListener("pointerdown", onDown, true);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", onScroll);
      window.removeEventListener("pointerdown", onDown, true);
    };
  }, [onClose]);
  if (!data) return null;
  const accent = data.direction === "increased" ? "#10b981" : data.direction === "reduced" ? "#f59e0b" : "#94a3b8";
  const rows = [
    ["Source", data.source],
    ["Confidence", data.confidence],
    ["Rule", data.rule],
    ["To improve", data.remediation],
  ].filter(([, v]) => v);
  return (
    <div data-provpop="1" role="dialog" style={{ position: "fixed", top: pos.top, left: pos.left, width: pos.width, zIndex: 100001, background: "#fff", border: "1px solid #e2e8f0", borderLeft: `3px solid ${accent}`, borderRadius: 8, boxShadow: "0 8px 24px rgba(15,23,42,0.18)", padding: "8px 10px" }}>
      <div style={{ display: "flex", alignItems: "flex-start", gap: 8, marginBottom: rows.length ? 5 : 0 }}>
        <span style={{ flex: 1, fontSize: 10, fontWeight: 700, color: "#0f172a", lineHeight: 1.3 }}>{data.title}</span>
        <span role="button" tabIndex={0} aria-label="Close"
          onClick={onClose}
          onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onClose(); } }}
          style={{ cursor: "pointer", color: "#94a3b8", fontSize: 14, fontWeight: 700, lineHeight: 1, flexShrink: 0, padding: "0 2px", userSelect: "none" }}>×</span>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
        {rows.map(([label, val]) => (
          <div key={label} style={{ display: "flex", gap: 6, fontSize: 9, lineHeight: 1.45 }}>
            <span style={{ fontWeight: 700, color: "#64748b", minWidth: 62, flexShrink: 0 }}>{label}</span>
            <span style={{ color: "#334155" }}>{val}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

const UMBRELLA_STATE_LABEL = {
  not_applicable:                 "Not applicable - no umbrella in submission",
  unknown:                        "Unknown - underlying limits not found",
  insufficient_information:       "Insufficient information",
  umbrella_coverage_present:      "Umbrella coverage present",
  umbrella_coverage_needs_review: "Umbrella coverage needs review",
  adequately_supported:           "Adequately supported",
};
// §6.4: loss-history evidence states (mirror backend LOSS_HISTORY_STATE_LABELS).
const LOSS_HISTORY_STATE_LABEL = {
  no_information:                  "No loss information provided",
  user_states_no_losses:          "User states No Known Losses",
  narrative_states_no_losses:     "Narrative states no losses",
  loss_runs_pending:              "Loss runs requested / pending",
  loss_runs_uploaded:             "Loss runs uploaded - years not yet confirmed",
  loss_runs_parsed:               "Loss runs parsed - claim years extracted",
  loss_runs_match_insured:        "Loss runs match insured",
  loss_runs_do_not_match:         "Loss runs do not match insured",
  loss_data_reconciled:           "Loss data reconciled",
  loss_history_conflicting:       "Conflicting - attested no losses but loss runs show claims",
  loss_history_pending_validation: "Loss history pending validation",
};
// §6.3: narrative component labels (must mirror backend NARRATIVE_COMPONENT_LABELS).
const NARRATIVE_COMPONENT_LABELS = {
  account_overview:    "Account Overview",
  operations:          "Operations Description",
  years_in_business:   "Years in Business",
  management:          "Management Experience",
  risk_controls:       "Risk Controls",
  loss_history:        "Loss History Discussion",
  coverage_discussion: "Coverage Discussion",
  carrier_market:      "Prior Carrier / Marketing Reason",
  location_exposure:   "Location Details",
  employee_practices:  "Employee / Payroll Context",
  growth_trends:       "WC Payroll / Class Code Context",
  target_markets:      "EMOD / XMOD Information",
};

// Neutral (white/grey) cards: recommendations live in the "rest" zone, which the
// client wants pink-free. Pink is reserved for the current-form sections.
const REC_TYPE_STYLE = {
  hard_stop:    { bg: "#fff", border: "#e2e8f0", color: "#000" },
  soft_warning: { bg: "#fff", border: "#e2e8f0", color: "#000" },
  missing_field:{ bg: "#fff", border: "#e2e8f0", color: "#000" },
  suggestion:   { bg: "#fff", border: "#e2e8f0", color: "#000" },
};

// ── Single severity model (Figure 2 feedback) ───────────────────────────────
// No MEDIUM/HIGH/LOW token anywhere. Submission Integrity's status maps onto:
//   low    -> hard_stop    (high risk - only reached on the separate review
//                           screen; this banner never shows LOW, see below)
//   medium -> warning      (medium risk - review recommended, non-blocking)
//   high, with resolved formatting differences present -> resolved_formatting_difference
//   high, nothing at all to note -> no chip. A fully clean submission is
//                           no-risk, not "low risk" - there is nothing left
//                           to advise about, so "Advisory" never renders here.
const INTEGRITY_SEVERITY_META = {
  hard_stop:                    { label: "Hard stop",                    color: "#9d0f5a", bg: "rgba(230,27,132,0.12)", border: "rgba(230,27,132,0.4)" },
  warning:                      { label: "Warning",                      color: "#92400e", bg: "#fffbeb",               border: "#fcd34d" },
  resolved_formatting_difference: { label: "Resolved formatting difference", color: "#0369a1", bg: "#f0f9ff",           border: "#bae6fd" },
};

function IntegritySeverityChip({ severity }) {
  const m = INTEGRITY_SEVERITY_META[severity];
  if (!m) return null;
  return (
    <span style={{ display: "inline-block", fontSize: 10, fontWeight: 800, letterSpacing: 0.3, textTransform: "uppercase", color: m.color, background: m.bg, border: `1px solid ${m.border}`, borderRadius: 6, padding: "1px 7px", flexShrink: 0 }}>
      {m.label}
    </span>
  );
}

// Fields tracked by BOTH the Submission Integrity soft-divergence check and the
// Data Consistency picker (underwriting_consistency.RECONCILABLE_FIELDS). When
// the SAME field is already an open conflict in Data Consistency, its Submission
// Integrity reason is redundant (Data Consistency shows it with source,
// confidence, suggested value, and apply-to-all) - suppressed here, display-only,
// so the underlying data/scoring is untouched. The exact phrase match is safe
// because these are fixed constant strings, never interpolated with values.
const INTEGRITY_REASON_TO_FACT_KEY = {
  "DBA / trade name differs across documents": "dba_name",
  "Entity type differs across documents":      "entity_type",
  "Mailing address differs across documents":  "mailing_address",
  "Location address differs across documents": "physical_address",
  "Effective dates differ across documents":   "effective_date",
  "Multiple carriers referenced across documents": "carrier_name",
  // Policy number / operations / account description are NOT tracked by Data
  // Consistency at all - always shown here, no dedup possible or needed.
};

// ── Suggested-value confidence (Figure 3 feedback) ──────────────────────────
// Discrete High / Medium / Low, ALWAYS rendered with the "Confidence:" prefix so
// it is never confused with the other high/medium/low signals on screen (document
// classification match, submission integrity). A numeric % is deliberately avoided
// - it would imply precision the heuristic can't honestly back.
const CONFIDENCE_META = {
  high:   { label: "High",   color: "#16a34a", bg: "#f0fdf4", border: "#bbf7d0" },
  medium: { label: "Medium", color: "#b45309", bg: "#fffbeb", border: "#fde68a" },
  low:    { label: "Low",    color: "#64748b", bg: "#f1f5f9", border: "#e2e8f0" },
};

const FALLBACK_CHAT_REPLY = "I'm not sure about that. Please contact your agent or broker for assistance.";

// ── Form recommendation tiers (Beta Report §7) ──────────────────────────────
// Groups the recommendation list by underwriting priority. Tier is set by the
// backend (form_service); match % / confidence is unchanged and still shown.
const TIER_ORDER = ["required", "recommended", "optional", "needs_confirmation"];
const TIER_META = {
  required:           { label: "Required",           color: "#dc2626", bg: "rgba(220,38,38,0.08)", hint: "Core forms for this submission" },
  recommended:        { label: "Recommended",        color: "#2563eb", bg: "rgba(37,99,235,0.08)", hint: "Supporting forms based on detected exposures" },
  optional:           { label: "Optional",           color: "#0891b2", bg: "rgba(8,145,178,0.08)", hint: "Include if the exposure applies" },
  needs_confirmation: { label: "Needs Confirmation", color: "#b45309", bg: "rgba(217,119,6,0.10)", hint: "Confirm relevance before generating" },
};

// ── "Why are you marketing this account?" options (DOUBTS-Workstream4 / Brent) ─
// Producer-answerable reason captured on the recommendation screen. Must match
// the backend _CARRIER_MARKETING_OPTIONS list; the adverse reasons there drive
// ACORD 101 to its correct tier when selected.
const MARKETING_REASON_OPTIONS = [
  "Shopping for better pricing",
  "Seeking broader coverage",
  "Voluntary carrier change",
  "Broker change",
  "Carrier nonrenewal",
  "Carrier cancellation",
  "Carrier declined renewal",
  "Carrier exited market",
  "Coverage restrictions imposed by carrier",
  "Coverage concerns",
  "New venture",
  "Other",
];

// Reasons that indicate a meaningful underwriting concern - selecting one of
// these adds ACORD 101 to the recommended list. Mirrors the backend
// _ADVERSE_CARRIER_REASONS set so the UI note matches what actually happens.
const MARKETING_ADVERSE_REASONS = new Set([
  "Carrier nonrenewal",
  "Carrier cancellation",
  "Carrier declined renewal",
  "Carrier exited market",
  "Coverage restrictions imposed by carrier",
  "Coverage concerns",
]);

// ── Dismiss-reason controlled list (individual issues) ─────────────────────
// Figure 6 engineering note: "reason codes as structured metadata on the
// package AND on individual issues... controlled list for reporting, allow
// free-text notes." The package side already has this (MARKETING_REASON_
// OPTIONS above); this is the same pattern applied to dismissing a single
// hard stop / warning. Sent as one string (the option, or "Other: <text>")
// into the EXISTING override_reason field - no backend/schema change, so
// dismiss-credit and the audit export both keep working unmodified.
const DISMISS_REASON_OPTIONS = [
  "Confirmed accurate - no correction needed",
  "Not applicable to this submission",
  "Client will provide before binding",
  "Broker/underwriter accepted as-is",
  "Will resolve in a follow-up submission",
  "Duplicate or already addressed elsewhere",
  "Other",
];

// ── Workstream 6 §9.1 - package status → corner-notification {title, body} ────
// Maps the live package state (integrity review / hard stops / warnings / clean)
// to a precise status so a notification never announces a bare "Ready" while
// blocking issues remain. Counts come from the same arrays the on-screen banners
// use, so the toast and the screen always agree.
function packageStatusNotice({ integrityReviewRequired, hardStopCount, warningCount }) {
  if (integrityReviewRequired) {
    return { title: "Primble - Documents Processed", body: "Submission Integrity Review Needed" };
  }
  // Both present → "Review Required - X hard stops and Y warnings" (client's example).
  if (hardStopCount > 0 && warningCount > 0) {
    return {
      title: "Primble - Review Required",
      body: `${hardStopCount} hard stop${hardStopCount !== 1 ? "s" : ""} and ${warningCount} warning${warningCount !== 1 ? "s" : ""} require review`,
    };
  }
  // Hard stops only → "Hard Stops Present - N items require review".
  if (hardStopCount > 0) {
    return { title: "Primble - Hard Stops Present", body: `${hardStopCount} item${hardStopCount !== 1 ? "s" : ""} require review` };
  }
  // Warnings only → "Review Required - N warnings found".
  if (warningCount > 0) {
    return { title: "Primble - Review Required", body: `${warningCount} warning${warningCount !== 1 ? "s" : ""} found` };
  }
  // Clean → "Ready for Generation - No blocking hard stops found".
  return { title: "Primble - Ready for Generation", body: "No blocking hard stops found" };
}

// ── Workstream 6 §9.1 - small "what to do next" banner shown per screen ───────
// Deliberately tiny and self-contained so it drops into existing layouts without
// touching spacing/responsiveness. tone: "ready" (green) | "caution" (amber).
function NextStepBanner({ text }) {
  // Same light-magenta surface as the DOCUMENTS PROCESSED / hard-stops / warnings
  // sections so every status block on a screen reads as one consistent family.
  return (
    <div style={{
      background: "rgba(230, 27, 132, 0.07)",
      border: "1.5px solid rgba(230, 27, 132, 0.25)",
      borderRadius: 10,
      padding: "10px 14px",
      fontSize: 13, fontWeight: 600, color: "#1e293b",
    }}>
      {text}
    </div>
  );
}

// ── Reusable info tooltip (tap/click, mobile-safe, no clipping) ──────────────
// Renders a small "i" that toggles a fixed-position popover computed from the
// icon's rect, so it is never clipped by the sidebar's overflow. Closes on an
// outside tap or Escape; stops propagation so it never toggles a parent row.
function InfoTip({ text }) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState({ top: 0, left: 0, width: 220 });
  // Laptops/desktops (a hover-capable, fine pointer) show on hover; phones/tablets
  // keep tap-to-toggle. Computed once - hover capability doesn't change mid-session.
  const [canHover] = useState(() =>
    typeof window !== "undefined" && typeof window.matchMedia === "function"
      && window.matchMedia("(hover: hover) and (pointer: fine)").matches
  );
  useEffect(() => {
    if (!open) return;
    const onKey = (e) => { if (e.key === "Escape") setOpen(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);
  const place = (target) => {
    const r = target.getBoundingClientRect();
    const width = Math.min(220, window.innerWidth - 16);
    let left = r.left + r.width / 2 - width / 2;
    left = Math.max(8, Math.min(left, window.innerWidth - width - 8));
    setPos({ top: r.bottom + 6, left, width });
  };
  const doToggle = (target) => { if (!open) place(target); setOpen(o => !o); };
  // Click: on touch this toggles; on hover devices hover controls visibility, so the
  // click is a no-op here - but we still stop propagation so a parent section header
  // (which the icon may sit inside) is never toggled by tapping the icon.
  const onClick = (e) => { e.stopPropagation(); e.preventDefault(); if (!canHover) doToggle(e.currentTarget); };
  const onKeyDown = (e) => {
    if (e.key === "Enter" || e.key === " ") { e.stopPropagation(); e.preventDefault(); doToggle(e.currentTarget); }
    else if (e.key === "Escape") setOpen(false);
  };
  const hoverProps = canHover ? {
    onMouseEnter: (e) => { place(e.currentTarget); setOpen(true); },
    onMouseLeave: () => setOpen(false),
  } : {};
  return (
    <>
      <span role="button" tabIndex={0} aria-label="More information"
        onClick={onClick} onKeyDown={onKeyDown} {...hoverProps}
        style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", width: 13, height: 13, borderRadius: "50%", border: "1px solid #cbd5e1", color: "#94a3b8", fontSize: 9, fontWeight: 700, lineHeight: 1, cursor: "pointer", flexShrink: 0, fontStyle: "normal", textTransform: "none", userSelect: "none" }}>
        i
      </span>
      {open && (
        <>
          {/* Outside-tap catcher only needed in tap mode; on hover devices mouseleave closes it. */}
          {!canHover && <div onClick={(e) => { e.stopPropagation(); setOpen(false); }} style={{ position: "fixed", inset: 0, zIndex: 100000 }} />}
          <div role="tooltip" style={{ position: "fixed", top: pos.top, left: pos.left, width: pos.width, zIndex: 100001, background: "#1e293b", color: "#fff", fontSize: 11, fontWeight: 500, lineHeight: 1.45, letterSpacing: 0, textTransform: "none", padding: "7px 10px", borderRadius: 8, boxShadow: "0 8px 24px rgba(15,23,42,0.28)" }}>
            {text}
          </div>
        </>
      )}
    </>
  );
}

// ── Reusable collapsible section (chevron header + optional tooltip). Resets to
// its default (collapsed) whenever resetKey changes, e.g. on active-form switch. ─
function CollapsibleSection({ title, tooltip, titleRight, defaultOpen = false, resetKey, headerColor = "#94a3b8", titleSize = 10, children }) {
  const [open, setOpen] = useState(defaultOpen);
  useEffect(() => { setOpen(defaultOpen); }, [resetKey]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div style={{ marginBottom: 10 }}>
      <button type="button" onClick={() => setOpen(o => !o)} aria-expanded={open}
        style={{ display: "flex", alignItems: "center", gap: 6, width: "100%", background: "none", border: "none", padding: "3px 0", cursor: "pointer", fontFamily: "inherit", textAlign: "left" }}>
        <span style={{ fontSize: 8, color: "#94a3b8", transform: open ? "rotate(90deg)" : "none", transition: "transform 0.15s", display: "inline-block", flexShrink: 0 }}>▶</span>
        <span style={{ fontSize: titleSize, fontWeight: 700, color: headerColor, textTransform: "uppercase", letterSpacing: "0.05em", display: "inline-flex", alignItems: "center", gap: 3, minWidth: 0 }}>
          {title}
          {tooltip && <InfoTip text={tooltip} />}
        </span>
        {titleRight != null && <span style={{ marginLeft: "auto", display: "inline-flex", alignItems: "center", gap: 6, flexShrink: 0 }}>{titleRight}</span>}
      </button>
      {open && <div style={{ marginTop: 6 }}>{children}</div>}
    </div>
  );
}

// ── One hard-stop/warning line: bullet point, with any trailing "Fix: ..."
// remediation hint broken onto its own line and bolded so it stands out from
// the descriptive part of the message. Messages without a "Fix: " segment
// (e.g. raw cross-document conflict text) render as a plain bulleted line. ─
const _issueBullet = <span style={{ fontWeight: 700, fontSize: "1.3em", lineHeight: 0, position: "relative", top: "1px" }}>•</span>;

function IssueLine({ message, className }) {
  const fixIdx = message.indexOf("Fix: ");
  if (fixIdx === -1) {
    return <div className={className}>{_issueBullet} {message}</div>;
  }
  const before = message.slice(0, fixIdx).trimEnd();
  const afterLabel = message.slice(fixIdx + "Fix: ".length);
  return (
    <div className={className}>
      {_issueBullet} {before}
      <br />
      <strong>Fix:</strong> {afterLabel}
    </div>
  );
}

// ── Durable issue-id fallback (only used when the backend didn't stamp one, e.g.
//    alias-stamp cross issues). Read + write both go through issueIdOf, so the
//    id stays consistent within the client even without a backend id. ──────────
function _fallbackIssueId(message, forms) {
  const base = (message || "").trim() + "|" +
    (Array.isArray(forms) ? [...forms].sort().join(",") : "");
  let h = 0;
  for (let i = 0; i < base.length; i++) h = (Math.imul(h, 31) + base.charCodeAt(i)) | 0;
  return "issf_" + (h >>> 0).toString(16);
}
function issueIdOf(iss) {
  return (iss && iss.issue_id) || _fallbackIssueId(iss && iss.message, iss && iss.forms);
}

// ── Issue-rail resolution status control (Open / Resolved / Dismissed) ────────
// Compact and wraps on small screens. Purely a work-tracking marker: setting a
// status never changes the SQS score (its endpoint is isolated from scoring).
const _ISSUE_STATUS_BADGE = {
  open:      { t: "Open",      bg: "#f1f5f9", fg: "#475569", bd: "#e2e8f0" },
  resolved:  { t: "Resolved",  bg: "#dcfce7", fg: "#166534", bd: "#86efac" },
  dismissed: { t: "Dismissed", bg: "#fef3c7", fg: "#92400e", bd: "#fde68a" },
};
function IssueStatusControl({ issueId, meta, status, onSet }) {
  const st = status || "open";
  const badge = _ISSUE_STATUS_BADGE[st] || _ISSUE_STATUS_BADGE.open;
  const btn = { fontSize: 10, fontWeight: 600, padding: "2px 8px", borderRadius: 5, cursor: "pointer", border: "1px solid #e2e8f0", background: "#fff", color: "#475569", whiteSpace: "nowrap", fontFamily: "inherit" };
  return (
    <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 5, marginTop: 5 }}>
      <span style={{ fontSize: 9.5, fontWeight: 700, padding: "1px 7px", borderRadius: 10, background: badge.bg, color: badge.fg, border: `1px solid ${badge.bd}`, whiteSpace: "nowrap" }}>{badge.t}</span>
      {st === "open" ? (
        <>
          <button type="button" onMouseDown={e => { e.preventDefault(); onSet(issueId, "resolved", meta); }} style={btn}>Resolve</button>
          <button type="button" onMouseDown={e => { e.preventDefault(); onSet(issueId, "dismissed", meta); }} style={btn}>Dismiss</button>
        </>
      ) : (
        <button type="button" onMouseDown={e => { e.preventDefault(); onSet(issueId, "open", meta); }} style={{ ...btn, color: "#94a3b8" }}>Reopen</button>
      )}
    </div>
  );
}

// ── Delete Confirm Modal ───────────────────────────────────────────────────
function DeleteConfirmModal({ onConfirm, onCancel }) {
  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(15,23,42,0.7)", backdropFilter: "blur(6px)", zIndex: 99999, display: "flex", alignItems: "center", justifyContent: "center", padding: 20 }}>
      <div style={{ background: "#fff", borderRadius: 16, padding: "32px 28px", maxWidth: 400, width: "100%", boxShadow: "0 24px 60px rgba(0,0,0,0.25)", animation: "slideUp 0.2s ease-out" }}>
        <div style={{ width: 52, height: 52, borderRadius: "50%", background: "#fef2f2", border: "2px solid #fecaca", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 22, margin: "0 auto 18px" }}></div>
        <h3 style={{ textAlign: "center", fontSize: 18, fontWeight: 700, color: "#0f172a", marginBottom: 8 }}>Delete Session?</h3>
        <p style={{ textAlign: "center", fontSize: 14, color: "#64748b", lineHeight: 1.6, marginBottom: 24 }}>This submission package will be permanently deleted and cannot be recovered.</p>
        <div style={{ display: "flex", gap: 10 }}>
          <button onClick={onCancel} style={{ flex: 1, padding: "10px 0", borderRadius: 8, border: "1px solid #e2e8f0", background: "#f8fafc", color: "#475569", fontSize: 14, fontWeight: 600, cursor: "pointer" }}>Cancel</button>
          <button onClick={onConfirm} style={{ flex: 1, padding: "10px 0", borderRadius: 8, border: "none", background: "#dc2626", color: "#fff", fontSize: 14, fontWeight: 600, cursor: "pointer" }}>Delete</button>
        </div>
      </div>
    </div>
  );
}

// ── ARQ curation taxonomy - exact client spec language (Beta Report §8) ─────
const ARQ_TOPIC_ORDER = [
  "applicant_information", "operations", "locations", "property",
  "general_liability", "auto", "workers_compensation", "umbrella",
  "loss_history", "producer_review", "other",
];
const ARQ_TOPIC_LABELS = {
  applicant_information: "Applicant Information", operations: "Operations",
  locations: "Locations", property: "Property", general_liability: "General Liability",
  auto: "Auto", workers_compensation: "Workers Compensation", umbrella: "Umbrella",
  loss_history: "Loss History", producer_review: "Producer Review", other: "Other",
};

// Priority labels - exact names from §8.2 item 2
const ARQ_PRIORITY_RANK = { critical: 0, important: 1, optional: 2, internal: 3, suppressed: 4 };
const ARQ_PRIORITY_META = {
  critical:  { label: "Critical",       bg: "#fef2f2", fg: "#dc2626", bd: "#fecaca" },
  important: { label: "Important",      bg: "#fffbeb", fg: "#b45309", bd: "#fde68a" },
  optional:  { label: "Optional",       bg: "#f1f5f9", fg: "#475569", bd: "#e2e8f0" },
  internal:  { label: "Internal only",  bg: "#f8fafc", fg: "#64748b", bd: "#e2e8f0" },
  suppressed:{ label: "Suppressed",     bg: "#f8fafc", fg: "#94a3b8", bd: "#e2e8f0" },
};

// Audience labels - exact names from §8.2 item 1
const ARQ_AUDIENCE_META = {
  client:      { label: "Client-facing",             bg: "#ecfdf5", fg: "#047857", bd: "#a7f3d0" },
  producer:    { label: "Producer-facing",            bg: "#fefce8", fg: "#854d0e", bd: "#fef08a" },
  internal:    { label: "Internal",                   bg: "#f1f5f9", fg: "#475569", bd: "#cbd5e1" },
  carrier:     { label: "Carrier/underwriter review", bg: "#f0f9ff", fg: "#0369a1", bd: "#bae6fd" },
  do_not_send: { label: "Do not send",                bg: "#fef2f2", fg: "#991b1b", bd: "#fecaca" },
};

// Coarse 3-bucket view (client / agency / underwriting) with a fallback derived
// from the finer audience, so ARQs stored before the bucket field still group.
const _AUDIENCE_TO_BUCKET = {
  client: "client", producer: "agency", carrier: "underwriting",
  internal: "underwriting", do_not_send: "do_not_send",
};
const bucketOf = (q) => q.bucket || _AUDIENCE_TO_BUCKET[q.audience] || (q.audience ? "underwriting" : "client");

// Client-facing = Client bucket and not suppressed (already-answered / narrative).
const isClientFacing = (q) => bucketOf(q) === "client" && !q.suppressed;
// "Never send" row - non-selectable (producer fax etc.).
const isNeverSend = (q) => bucketOf(q) === "do_not_send";
// Agency bucket (producer / CSR / account manager answers).
const isAgency = (q) => !isClientFacing(q) && !isNeverSend(q) && bucketOf(q) === "agency";
// Underwriting / Internal Review - cross-form flags, internal items, plus any
// suppressed client items (already answered / stated in narrative).
const isUnderwriting = (q) => !isClientFacing(q) && !isNeverSend(q) && !isAgency(q);

function ScoreImpactBadges({ q }) {
  const si = q.score_impact || {};
  const badges = [];
  if (si.hard_stop_resolution) badges.push({ t: "Resolves hard stop", bg: "#fef2f2", fg: "#dc2626" });
  if (si.sqs) badges.push({ t: "SQS ↑", bg: "#ecfdf5", fg: "#047857" });
  if (si.submission_readiness) badges.push({ t: "Submission ↑", bg: "#eff6ff", fg: "#1d4ed8" });
  if (!badges.length && si.form_completion) badges.push({ t: "Form completion", bg: "#f1f5f9", fg: "#475569" });
  if (!badges.length) return null;
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 5 }}>
      {badges.map((b, i) => (
        <span key={i} style={{ fontSize: 9.5, fontWeight: 700, color: b.fg, background: b.bg, padding: "1px 6px", borderRadius: 10 }}>{b.t}</span>
      ))}
    </div>
  );
}

// ── ARQ Modal ─────────────────────────────────────────────────────────────
function ARQModal({ sessionId, token, questions, summary, onClose, onSuccess }) {
  const [clientEmail, setClientEmail] = useState("");
  const [clientName, setClientName] = useState("");
  const [selectedQuestions, setSelectedQuestions] = useState({});
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [emailTouched, setEmailTouched] = useState(false);
  const [showAgency, setShowAgency] = useState(false);
  const [showUnderwriting, setShowUnderwriting] = useState(false);
  const [showNeverSend, setShowNeverSend] = useState(false);

  // Legacy payloads have no taxonomy - fall back to the old "select all".
  const hasTaxonomy = questions.some(q => q.audience);

  useEffect(() => {
    const init = {};
    questions.forEach(q => {
      init[q.field_name] = hasTaxonomy ? !!q.default_selected : true;
    });
    setSelectedQuestions(init);
  }, [questions, hasTaxonomy]);

  // Split into the client's 3 buckets + the non-selectable "Never send" row.
  const clientQuestions       = questions.filter(isClientFacing);
  const agencyQuestions       = questions.filter(isAgency);
  const underwritingQuestions = questions.filter(isUnderwriting);
  const neverSendQuestions    = questions.filter(isNeverSend);

  const groupedClient = ARQ_TOPIC_ORDER
    .map(topic => ({
      topic,
      label: ARQ_TOPIC_LABELS[topic] || "Other",
      items: clientQuestions
        .filter(q => (q.topic_group || "other") === topic)
        .sort((a, b) => (ARQ_PRIORITY_RANK[a.priority] ?? 2) - (ARQ_PRIORITY_RANK[b.priority] ?? 2)),
    }))
    .filter(g => g.items.length);

  const handleToggle = fn => setSelectedQuestions(prev => ({ ...prev, [fn]: !prev[fn] }));

  const applySelection = (predicate) => {
    const updated = { ...selectedQuestions };
    questions.forEach(q => { updated[q.field_name] = predicate(q); });
    setSelectedQuestions(updated);
  };
  const selectCriticalOnly = () => applySelection(q => isClientFacing(q) && q.priority === "critical");
  const selectRecommended  = () => applySelection(q => isClientFacing(q) && (q.priority === "critical" || q.priority === "important"));
  const selectAllClient    = () => applySelection(q => isClientFacing(q));
  const deselectAll        = () => applySelection(() => false);

  const sanitizeEmail = val => val.trim().toLowerCase().slice(0, 254);
  const selectedCount = Object.values(selectedQuestions).filter(Boolean).length;
  // Track how many non-client items are included so we can warn the producer.
  const nonClientSelected = [...agencyQuestions, ...underwritingQuestions]
    .filter(q => selectedQuestions[q.field_name]).length;
  const isEmailValid = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(clientEmail);
  const canSend = isEmailValid && selectedCount > 0;

  const handleSend = async () => {
    if (!canSend) return;
    setEmailTouched(true);
    setSending(true); setError("");
    const selectedList = questions.filter(q => selectedQuestions[q.field_name]);
    try {
      const res = await fetch(`${API_BASE}/api/arq/send`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          client_email: sanitizeEmail(clientEmail),
          client_name: clientName.trim().slice(0, 100),
          questions: selectedList,
        }),
      });
      const data = await res.json();
      if (res.ok && data.success) onSuccess(data);
      else setError(data.detail || data.message || "Failed to send questionnaire.");
    } catch (e) { setError("Network error: " + e.message); }
    finally { setSending(false); }
  };

  // showAudienceBadge = true when row is inside a non-client sub-panel (agency/underwriting/never-send).
  // disabled = true for the non-selectable "Never send" row.
  const renderRow = (q, idx, dimmed, showAudienceBadge = false, disabled = false) => {
    const sel = !disabled && !!selectedQuestions[q.field_name];
    const pm  = ARQ_PRIORITY_META[q.priority] || ARQ_PRIORITY_META.optional;
    const am  = showAudienceBadge ? (ARQ_AUDIENCE_META[q.audience] || null) : null;
    const toggle = disabled ? undefined : () => handleToggle(q.field_name);
    return (
      <div key={`${q.field_name}-${idx}`} onClick={toggle}
        style={{ border: `1.5px solid ${sel ? "#E61B84" : "#e2e8f0"}`, borderRadius: 10, padding: "10px 14px", cursor: disabled ? "default" : "pointer", background: sel ? "rgba(230,0,122,0.03)" : "#fafafa", display: "flex", alignItems: "flex-start", gap: 10, opacity: disabled ? 0.6 : (sel ? 1 : (dimmed ? 0.55 : 0.7)), transition: "all 0.15s" }}>
        <input type="checkbox" checked={sel} disabled={disabled} onChange={toggle} onClick={e => e.stopPropagation()} style={{ marginTop: 3, width: 15, height: 15, cursor: disabled ? "not-allowed" : "pointer", accentColor: "#E61B84", flexShrink: 0 }} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center", marginBottom: 4 }}>
            {q.forms && <span style={{ fontSize: 10, fontWeight: 700, color: "#E61B84", background: "#fdf2f8", padding: "1px 7px", borderRadius: 20 }}>ACORD {q.forms}</span>}
            {/* Audience badge - shown in non-client sub-panels using exact §8.2 item 1 labels */}
            {am && <span style={{ fontSize: 9.5, fontWeight: 700, color: am.fg, background: am.bg, border: `1px solid ${am.bd}`, padding: "1px 6px", borderRadius: 10 }}>{am.label}</span>}
            {/* Cross-form conflict whose fix is a client-answerable fact - producer can tick to add it to the client send */}
            {q.escalatable_to_client && <span style={{ fontSize: 9.5, fontWeight: 700, color: "#047857", background: "#ecfdf5", border: "1px solid #a7f3d0", padding: "1px 6px", borderRadius: 10 }}>Add to client</span>}
            {/* Priority chip - exact §8.2 item 2 labels */}
            {hasTaxonomy && q.priority && ARQ_PRIORITY_META[q.priority] && !showAudienceBadge && (
              <span style={{ fontSize: 9.5, fontWeight: 700, color: pm.fg, background: pm.bg, border: `1px solid ${pm.bd}`, padding: "1px 6px", borderRadius: 10 }}>{pm.label}</span>
            )}
            {/* "Suggested" nudge - for Important questions that are shown but not pre-selected */}
            {q.suggested && <span style={{ fontSize: 9.5, fontWeight: 700, color: "#b45309", background: "#fffbeb", padding: "1px 6px", borderRadius: 10 }}>Suggested</span>}
            {/* §6.3 item 2/3 - the narrative already answers this, so it isn't auto-sent to the client */}
            {q.suppressed_reason === "stated_in_narrative" && <span style={{ fontSize: 9.5, fontWeight: 700, color: "#1d4ed8", background: "#eff6ff", padding: "1px 6px", borderRadius: 10 }}>Stated in narrative</span>}
          </div>
          <p style={{ margin: 0, fontSize: 13, fontWeight: 600, color: "#0f172a", lineHeight: 1.45 }}>{q.question}</p>
          {q.current_value && <p style={{ margin: "3px 0 0", fontSize: 11, color: "#94a3b8" }}>Current: {q.current_value}</p>}
          <ScoreImpactBadges q={q} />
        </div>
      </div>
    );
  };

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(15,23,42,0.75)", backdropFilter: "blur(8px)", zIndex: 99999, display: "flex", alignItems: "center", justifyContent: "center", padding: "16px" }}>
      <div onClick={e => e.stopPropagation()} style={{ background: "#fff", borderRadius: 20, width: "100%", maxWidth: 640, maxHeight: "92vh", overflow: "hidden", display: "flex", flexDirection: "column", boxShadow: "0 32px 80px rgba(0,0,0,0.2)" }}>
        <div style={{ padding: "24px 28px 0", flexShrink: 0 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 20 }}>
            <div>
              <div style={{ fontSize: 11, fontWeight: 700, color: "#E61B84", marginBottom: 4, letterSpacing: "0.05em", textTransform: "uppercase" }}>Client Questionnaire</div>
              <h2 style={{ fontSize: 22, fontWeight: 700, color: "#0f172a", margin: 0 }}>Send to Client</h2>
              <p style={{ fontSize: 13, color: "#64748b", marginTop: 4 }}>Only critical client questions are pre-selected. Answers auto-populate your ACORD forms.</p>
            </div>
            <button onClick={onClose} style={{ width: 32, height: 32, borderRadius: "50%", border: "1px solid #E61B84", background: "rgba(230,0,122,0.08)", color: "#E61B84", fontSize: 16, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0, transition: "all 0.2s" }}
              onMouseEnter={e => { e.currentTarget.style.background = "#E61B84"; e.currentTarget.style.color = "#fff"; }}
              onMouseLeave={e => { e.currentTarget.style.background = "rgba(230,0,122,0.08)"; e.currentTarget.style.color = "#E61B84"; }}>✕</button>
          </div>
          {error && <div style={{ background: "#fef2f2", border: "1px solid #fecaca", borderRadius: 8, padding: "10px 14px", marginBottom: 16, color: "#dc2626", fontSize: 13 }}>{error}</div>}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 16 }}>
            <div>
              <label style={{ display: "block", fontSize: 12, fontWeight: 600, color: "#374151", marginBottom: 6 }}>Client Email <span style={{ color: "#E61B84" }}>*</span></label>
              <input type="email" value={clientEmail}
                onChange={e => { setClientEmail(e.target.value); setEmailTouched(true); }}
                onBlur={e => { setEmailTouched(true); e.target.style.borderColor = "#e2e8f0"; }}
                onFocus={e => e.target.style.borderColor = "#E61B84"}
                placeholder="client@company.com" maxLength={254}
                style={{ width: "100%", padding: "9px 12px", border: "1px solid #e2e8f0", borderRadius: 8, fontSize: 13, outline: "none", boxSizing: "border-box" }} />
              {emailTouched && clientEmail && !isEmailValid && (
                <p style={{ fontSize: 11, color: "#ef4444", marginTop: 4 }}>Please enter a valid email address.</p>
              )}
            </div>
            <div>
              <label style={{ display: "block", fontSize: 12, fontWeight: 600, color: "#374151", marginBottom: 6 }}>First Name <span style={{ color: "#94a3b8", fontWeight: 400 }}>(optional)</span></label>
              <input type="text" value={clientName} onChange={e => setClientName(e.target.value)} placeholder="e.g. John" maxLength={100}
                style={{ width: "100%", padding: "9px 12px", border: "1px solid #e2e8f0", borderRadius: 8, fontSize: 13, outline: "none", boxSizing: "border-box" }}
                onFocus={e => e.target.style.borderColor = "#E61B84"} onBlur={e => e.target.style.borderColor = "#e2e8f0"} />
            </div>
          </div>
          {/*
            Quick-select controls - these four buttons implement the
            "Default to a curated question set" requirement (§8.2 item 3):

              • "Critical only"        → "Critical client-answerable questions selected"
              • "Critical + Important" → applies both: Critical selected + Important suggested
              • "All client-facing"    → selects all Client-facing audience questions
              • "Clear all"            → "Producer/internal items deselected" starting state

            The audience split (Client-facing / Producer-facing / Internal /
            Carrier/underwriter review / Do not send) comes from §8.2 item 1.
            The priority split (Critical / Important / Optional / Internal only /
            Suppressed) comes from §8.2 item 2.
          */}
          {/* ARQ metrics (client spec): Client / Agency / Critical / Optional counts + duplicates merged. */}
          {hasTaxonomy && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center", marginBottom: 10 }}>
              {[
                { t: `${clientQuestions.length} Client`, bg: "#ecfdf5", fg: "#047857" },
                { t: `${agencyQuestions.length} Agency`, bg: "#fefce8", fg: "#854d0e" },
                { t: `${clientQuestions.filter(q => q.priority === "critical").length} Critical`, bg: "#fef2f2", fg: "#dc2626" },
                { t: `${clientQuestions.filter(q => q.priority === "optional").length} Optional`, bg: "#f1f5f9", fg: "#475569" },
                ...((summary && summary.merged_removed) ? [{ t: `${summary.merged_removed} duplicates merged`, bg: "#eff6ff", fg: "#1d4ed8" }] : []),
              ].map((c, i) => (
                <span key={i} style={{ fontSize: 10.5, fontWeight: 700, color: c.fg, background: c.bg, padding: "2px 8px", borderRadius: 20 }}>{c.t}</span>
              ))}
            </div>
          )}
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center", marginBottom: 10, paddingBottom: 10, borderBottom: "1px solid #f1f5f9" }}>
            <span style={{ fontSize: 13, fontWeight: 600, color: "#1e293b", marginRight: "auto" }}>
              {selectedCount} selected <span style={{ color: "#94a3b8", fontWeight: 400 }}>· {clientQuestions.length} client-facing</span>
            </span>
            {hasTaxonomy && <button onClick={selectCriticalOnly} style={qsBtn}>Critical only</button>}
            {hasTaxonomy && <button onClick={selectRecommended}  style={qsBtn}>Recommended</button>}
            <button onClick={selectAllClient} style={qsBtn}>All client-facing</button>
            <button onClick={deselectAll}     style={qsBtn}>Clear all</button>
          </div>
        </div>

        <div style={{ flex: 1, overflowY: "auto", padding: "0 28px 4px" }}>
          {/* Contextual hint when nothing is pre-selected */}
          {hasTaxonomy && selectedCount === 0 && clientQuestions.length > 0 && (() => {
            const hasCritical = clientQuestions.some(q => q.priority === "critical");
            return (
              <div style={{ background: hasCritical ? "#fffbeb" : "rgba(230,27,132,0.07)", border: `1px solid ${hasCritical ? "#fde68a" : "rgba(230,27,132,0.25)"}`, borderRadius: 8, padding: "8px 12px", marginBottom: 12, fontSize: 12, color: hasCritical ? "#92400e" : "#9d174d" }}>
                {hasCritical
                  ? "Critical questions are available - click \"Critical only\" to pre-select them, or choose individual questions below."
                  : "All critical fields were already answered from your uploaded documents. Select any additional questions to confirm or clarify with the client."}
              </div>
            );
          })()}
          {/* Client-facing questions, grouped by topic */}
          {groupedClient.map(group => (
            <div key={group.topic} style={{ marginBottom: 14 }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: "#475569", textTransform: "uppercase", letterSpacing: "0.04em", margin: "4px 0 8px" }}>
                {group.label} <span style={{ color: "#cbd5e1" }}>· {group.items.length}</span>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {group.items.map((q, idx) => renderRow(q, idx, false))}
              </div>
            </div>
          ))}

          {clientQuestions.length === 0 && (
            <p style={{ fontSize: 13, color: "#64748b", textAlign: "center", padding: "16px 0" }}>
              No client-answerable questions found - everything was either resolved or is internal.
            </p>
          )}

          {/* ── Bucket 2: Agency (producer / CSR / account manager answers) ── */}
          {agencyQuestions.length > 0 && (
            <div style={{ marginTop: 10, border: "1px dashed #fde68a", borderRadius: 10, background: "#fffdf5" }}>
              <button onClick={() => setShowAgency(s => !s)}
                style={{ width: "100%", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, padding: "10px 14px", background: "none", border: "none", cursor: "pointer", textAlign: "left" }}>
                <span style={{ fontSize: 12, fontWeight: 700, color: "#854d0e" }}>
                  Agency
                  <span style={{ color: "#b45309", fontWeight: 400 }}> ({agencyQuestions.length})</span>
                </span>
                <span style={{ fontSize: 12, color: "#b45309", flexShrink: 0 }}>{showAgency ? "Hide ▲" : "Show ▼"}</span>
              </button>
              {showAgency && (
                <div style={{ padding: "0 14px 12px" }}>
                  <p style={{ fontSize: 11, color: "#b45309", margin: "0 0 10px" }}>
                    The <strong>producer / CSR / account manager</strong> answers these (carrier info, policy numbers, prior carrier, ACORD edition, submission strategy). Deselected by default - add one only if you want the client to answer it.
                  </p>
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    {agencyQuestions.map((q, idx) => renderRow(q, idx, true, true))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* ── Bucket 3: Underwriting / Internal Review (flags, not auto-sent) ── */}
          {underwritingQuestions.length > 0 && (
            <div style={{ marginTop: 8, border: "1px dashed #bae6fd", borderRadius: 10, background: "#f0f9ff" }}>
              <button onClick={() => setShowUnderwriting(s => !s)}
                style={{ width: "100%", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, padding: "10px 14px", background: "none", border: "none", cursor: "pointer", textAlign: "left" }}>
                <span style={{ fontSize: 12, fontWeight: 700, color: "#0369a1" }}>
                  Underwriting / Internal Review
                  <span style={{ color: "#38bdf8", fontWeight: 400 }}> ({underwritingQuestions.length})</span>
                </span>
                <span style={{ fontSize: 12, color: "#0369a1", flexShrink: 0 }}>{showUnderwriting ? "Hide ▲" : "Show ▼"}</span>
              </button>
              {showUnderwriting && (
                <div style={{ padding: "0 14px 12px" }}>
                  <p style={{ fontSize: 11, color: "#0369a1", margin: "0 0 10px" }}>
                    Internal flags - <strong>cross-form conflicts</strong>, coverage-gap and reconciliation items. These are not sent to the client automatically. Items marked <strong>"Add to client"</strong> have a client-answerable fix you can tick to include.
                  </p>
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    {underwritingQuestions.map((q, idx) => renderRow(q, idx, true, true))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* ── Never send (non-selectable): fax numbers, barcodes, system IDs ── */}
          {neverSendQuestions.length > 0 && (
            <div style={{ marginTop: 8, border: "1px dashed #fca5a5", borderRadius: 10, background: "#fff5f5" }}>
              <button onClick={() => setShowNeverSend(s => !s)}
                style={{ width: "100%", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, padding: "10px 14px", background: "none", border: "none", cursor: "pointer", textAlign: "left" }}>
                <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                  <span style={{ fontSize: 12, fontWeight: 700, color: "#991b1b" }}>
                    Never send
                    <span style={{ color: "#fca5a5", fontWeight: 400 }}> ({neverSendQuestions.length})</span>
                  </span>
                  <span style={{ fontSize: 10, color: "#fca5a5" }}>Fields never appropriate for a client questionnaire</span>
                </div>
                <span style={{ fontSize: 12, color: "#dc2626", flexShrink: 0 }}>{showNeverSend ? "Hide ▲" : "Show ▼"}</span>
              </button>
              {showNeverSend && (
                <div style={{ padding: "0 14px 12px" }}>
                  <p style={{ fontSize: 11, color: "#fca5a5", margin: "0 0 10px" }}>
                    Flagged <strong>"Never send"</strong> - examples: producer fax numbers, barcodes, system identifiers. Shown for completeness only; they cannot be added to a client questionnaire.
                  </p>
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    {neverSendQuestions.map((q, idx) => renderRow(q, idx, true, true, true))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        <div style={{ padding: "16px 28px 24px", flexShrink: 0, borderTop: "1px solid #f1f5f9", marginTop: 8 }}>
          <button onClick={handleSend} disabled={!canSend || sending}
            style={{ width: "100%", padding: "12px 0", borderRadius: 10, border: "none", background: canSend && !sending ? "#E61B84" : "#e2e8f0", color: canSend && !sending ? "#fff" : "#94a3b8", fontSize: 14, fontWeight: 700, cursor: canSend && !sending ? "pointer" : "not-allowed", display: "flex", alignItems: "center", justifyContent: "center", gap: 8, minHeight: 46 }}>
            {sending ? <><span style={{ width: 14, height: 14, border: "2px solid rgba(255,255,255,0.4)", borderTopColor: "#fff", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" }} />Sending…</> : `Send ${selectedCount} Question${selectedCount !== 1 ? "s" : ""} to Client`}
          </button>
          {nonClientSelected > 0 && (
            <p style={{ fontSize: 11, color: "#b45309", textAlign: "center", marginTop: 8 }}>
              {nonClientSelected} non-client item{nonClientSelected !== 1 ? "s" : ""} selected (Agency / Underwriting) - confirm these are appropriate before sending.
            </p>
          )}
          <p style={{ fontSize: 11, color: "#94a3b8", textAlign: "center", marginTop: 10 }}>Client receives a secure link valid for 72 hours.</p>
        </div>
      </div>
    </div>
  );
}

const qsBtn = { fontSize: 11, fontWeight: 600, color: "#4f7cff", background: "rgba(79,124,255,0.06)", border: "1px solid rgba(79,124,255,0.2)", borderRadius: 6, padding: "3px 10px", cursor: "pointer" };

// ── ARQ Status Panel ───────────────────────────────────────────────────────
const _ARQ_REMEDIATION_LABEL = {
  resolved:                     { text: "Resolved",                bg: "#dcfce7", color: "#166534", border: "#86efac" },
  improved:                     { text: "Score Improved",          bg: "#dcfce7", color: "#166534", border: "#86efac" },
  pending_validation:           { text: "Pending Validation",      bg: "#eff6ff", color: "#1e40af", border: "#bfdbfe" },
  user_provided_only:           { text: "User Provided",           bg: "#eff6ff", color: "#1e40af", border: "#bfdbfe" },
  conflicting_evidence_remains: { text: "Conflicting Evidence",    bg: "#fffbeb", color: "#92400e", border: "#fde68a" },
  requires_supporting_document: { text: "Supporting Doc Required", bg: "#fffbeb", color: "#92400e", border: "#fde68a" },
  still_missing:                { text: "Still Missing",           bg: "#f1f5f9", color: "#475569", border: "#cbd5e1" },
};

function ARQStatusPanel({ arqSessions, token, onRefresh, scoreImprovement, hideTitle }) {
  const [reminding, setReminding] = useState(null);
  const handleRemind = async (arq_id) => {
    setReminding(arq_id);
    try { await fetch(`${API_BASE}/api/arq/remind/${arq_id}`, { method: "POST", credentials: "include" }); onRefresh(); } catch (_) {}
    setReminding(null);
  };
  const fmtDate = iso => iso ? new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "-";
  const dotStyle = { width: 9, height: 9, background: "rgb(187,247,208)", border: "1px solid #86efac", borderRadius: 2, display: "inline-block", flexShrink: 0 };
  if (!arqSessions || arqSessions.length === 0) return null;
  return (
    <div style={{ marginTop: 8 }}>
      {!hideTitle && <div style={{ fontSize: 10, fontWeight: 700, color: "#94a3b8", letterSpacing: "0.06em", marginBottom: 5, textTransform: "uppercase" }}>Sent Questionnaires</div>}
      <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
        {arqSessions.map(arq => {
          const isExpired = new Date() > new Date(arq.expires_at) && arq.status !== "submitted";
          const status = isExpired ? "expired" : arq.status;
          const sc = { submitted: { bg: "#dcfce7", color: "#166534", border: "#86efac", label: "Done" }, expired: { bg: "#f1f5f9", color: "#64748b", border: "#cbd5e1", label: "Expired" }, pending: { bg: "#fef9c3", color: "#854d0e", border: "#fde047", label: "Pending" } }[status] || {};
          const remLabel = _ARQ_REMEDIATION_LABEL[arq.remediation_status];
          const fieldsCount = arq.fields_answered_count || 0;
          return (
            <div key={arq.id} style={{ background: "#fff", border: "1px solid #e2e8f0", borderRadius: 8, padding: "7px 10px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div style={{ fontSize: 11, fontWeight: 600, color: "#1e293b", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{arq.client_name ? `${arq.client_name} (${arq.email})` : arq.email}</div>
                  <div style={{ fontSize: 10, color: "#94a3b8", marginTop: 1 }}>{fmtDate(arq.created_at)}{arq.submitted_at && ` - Submitted ${fmtDate(arq.submitted_at)}`}</div>
                </div>
                <span style={{ fontSize: 10, fontWeight: 700, padding: "2px 7px", borderRadius: 20, border: `1px solid ${sc.border}`, background: sc.bg, color: sc.color, flexShrink: 0 }}>{sc.label}</span>
              </div>
              {status === "submitted" && (
                <div style={{ marginTop: 5, display: "flex", flexDirection: "column", gap: 4 }}>
                  {remLabel && (
                    <span style={{ display: "inline-flex", alignItems: "center", fontSize: 10, fontWeight: 700, padding: "2px 8px", borderRadius: 10, border: `1px solid ${remLabel.border}`, background: remLabel.bg, color: remLabel.color, alignSelf: "flex-start" }}>
                      {remLabel.text}
                    </span>
                  )}
                  {fieldsCount > 0 && (
                    <div style={{ fontSize: 11, color: "#047857", display: "flex", alignItems: "center", gap: 4 }}>
                      <span style={dotStyle} />
                      {fieldsCount} answer{fieldsCount !== 1 ? "s" : ""} submitted by client
                    </div>
                  )}
                  {scoreImprovement > 0 && (
                    <div style={{ fontSize: 11, color: "#047857", display: "flex", alignItems: "center", gap: 4 }}>
                      <span style={dotStyle} />
                      Submission score improved +{scoreImprovement} pts after questionnaire
                    </div>
                  )}
                </div>
              )}
              {arq.status === "pending" && !isExpired && (
                <div style={{ marginTop: 5, display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                  <button onClick={() => handleRemind(arq.id)} disabled={reminding === arq.id}
                    style={{ fontSize: 10, fontWeight: 600, color: "#4f7cff", background: "rgba(79,124,255,0.06)", border: "1px solid rgba(79,124,255,0.2)", borderRadius: 5, padding: "2px 8px", cursor: reminding === arq.id ? "wait" : "pointer", opacity: reminding === arq.id ? 0.6 : 1 }}>
                    {reminding === arq.id ? "Sending…" : "Remind"}{arq.reminder_count > 0 && ` (${arq.reminder_count})`}
                  </button>
                  {/* Compact status chip: where the client is in the questionnaire */}
                  <span style={{ fontSize: 10, fontWeight: 700, color: "#4f7cff", background: "rgba(79,124,255,0.1)", borderRadius: 20, padding: "2px 8px", whiteSpace: "nowrap" }}>
                    {arq.has_draft ? "In progress" : arq.viewed_at ? "Opened" : "Not opened"}
                  </span>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Producer-answer outcome label (Fig 13): plain-language before/after + status.
// House style: no em-dashes; the → arrow is already used elsewhere in the UI.
function answerResultLabel(r) {
  if (!r) return "Answer recorded.";
  const before = r.score_before, after = r.score_after, delta = r.delta;
  const arrow = (before != null && after != null) ? ` SQS ${before} → ${after}` : "";
  const d = (typeof delta === "number" && delta !== 0) ? ` (${delta > 0 ? "+" : ""}${delta})` : "";
  switch (r.status) {
    case "resolved":
    case "improved":                     return `Updated -${arrow}${d}`;
    case "pending_validation":           return `Recorded - pending review${arrow}${d}`;
    case "requires_supporting_document": return "Recorded - attach a supporting document to fully credit";
    case "conflicting_evidence_remains": return "Recorded - conflicts remain, review needed";
    case "user_provided_only":           return `Saved to the package${arrow}`;
    case "still_missing":                return "Recorded";
    default:                             return `Answer recorded${arrow}${d}`;
  }
}

// ── Side panel recommendation row - own local state avoids shared-state race ──
function SidePanelRec({ rec, index, sqsScore, onDismiss, onAnswer }) {
  const [reason, setReason] = useState("");
  const [otherReason, setOtherReason] = useState("");
  const [busy, setBusy]     = useState(false);
  const [result, setResult] = useState(null);
  const [errMsg, setErrMsg] = useState("");
  const isObj  = typeof rec === "object" && rec !== null;
  const msg    = isObj ? rec.message : rec;
  const impact = isObj ? rec.score_impact : null;
  const recId  = isObj ? rec.rec_id : `legacy_${index}`;
  const recType = isObj ? rec.type : "suggestion";
  const st = REC_TYPE_STYLE[recType] || REC_TYPE_STYLE.suggestion;
  // Answerable = the recommendation resolves to a fillable field. Only these route
  // "Submit" to the producer-answer flow; every other rec keeps the exact prior
  // dismiss-with-reason (waiver) behavior, so nothing regresses.
  const answerable = isObj && !!rec.field && typeof onAnswer === "function";
  // Dismiss-reason (waiver) path only: `reason` holds the picked controlled option;
  // "Other" reveals a free-text field whose value is folded into one string on
  // submit. The answerable path is untouched - there `reason` is the typed answer.
  const dismissReasonValue = reason === "Other"
    ? (otherReason.trim() ? `Other: ${otherReason.trim()}` : "")
    : reason;

  const submitAnswer = async () => {
    if (busy) return;
    setErrMsg(""); setBusy(true);
    let out;
    try { out = await onAnswer(rec, reason); }
    catch (_) { out = { ok: false }; }
    finally { setBusy(false); }
    if (out?.ok) setResult(out.impact || { status: "user_provided_only" });
    else setErrMsg(out?.error || "Could not apply answer.");
  };
  // Submit: answer the gap (answerable) or the legacy waiver-with-reason otherwise.
  const submit  = answerable ? submitAnswer : (() => onDismiss(rec, sqsScore, dismissReasonValue));
  const dismiss = () => onDismiss(rec, sqsScore, "");

  return (
    <div style={{ background: st.bg, border: `1px solid ${st.border}`, borderRadius: 8, padding: "8px 10px" }}>
      <div style={{ display: "flex", alignItems: "flex-start", gap: 7 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 11, color: st.color, fontWeight: 600, lineHeight: 1.4 }}>{msg}</div>
          {impact > 0 && <div style={{ fontSize: 10, color: "#000", fontWeight: 700, marginTop: 2 }}>up to +{impact} pts</div>}
        </div>
        <span style={{ flexShrink: 0, fontSize: 9, fontWeight: 700, padding: "1px 7px", borderRadius: 10, whiteSpace: "nowrap", ...(result ? { background: "#dcfce7", color: "#166534", border: "1px solid #86efac" } : { background: "#f1f5f9", color: "#475569", border: "1px solid #e2e8f0" }) }}>{result ? "Resolved" : "Open"}</span>
      </div>
      {result ? (
        <div style={{ marginTop: 7, fontSize: 10, fontWeight: 700, color: "#065f46", background: "#ecfdf5", border: "1px solid #a7f3d0", borderRadius: 5, padding: "4px 7px" }}>
          {answerResultLabel(result)}
        </div>
      ) : isObj && (
        <>
          <div style={{ marginTop: 7, display: "flex", gap: 5, alignItems: "center" }}>
            {answerable ? (
              <input
                placeholder="Type your answer…"
                value={reason}
                onChange={e => { setReason(e.target.value); if (errMsg) setErrMsg(""); }}
                onKeyDown={e => { if (e.key === "Enter") submit(); }}
                disabled={busy}
                style={{ flex: 1, fontSize: 10, padding: "3px 7px", border: "1px solid #e2e8f0", borderRadius: 5, outline: "none", fontFamily: "inherit", minWidth: 0 }}
              />
            ) : (
              <select
                value={reason}
                onChange={e => { setReason(e.target.value); setOtherReason(""); if (errMsg) setErrMsg(""); }}
                disabled={busy}
                style={{ flex: 1, fontSize: 10, padding: "3px 7px", border: "1px solid #e2e8f0", borderRadius: 5, outline: "none", fontFamily: "inherit", minWidth: 0, background: "#fff", color: reason ? "#0f172a" : "#94a3b8" }}
              >
                <option value="">Select a reason (optional)…</option>
                {DISMISS_REASON_OPTIONS.map(o => <option key={o} value={o}>{o}</option>)}
              </select>
            )}
            {!answerable && reason === "Other" && (
              <input
                placeholder="Describe why…"
                value={otherReason}
                onChange={e => { setOtherReason(e.target.value); if (errMsg) setErrMsg(""); }}
                onKeyDown={e => { if (e.key === "Enter") submit(); }}
                disabled={busy}
                style={{ flex: 1, fontSize: 10, padding: "3px 7px", border: "1px solid #e2e8f0", borderRadius: 5, outline: "none", fontFamily: "inherit", minWidth: 0 }}
              />
            )}
            {(answerable ? reason.trim() : dismissReasonValue.trim()) && (
              <button
                disabled={busy}
                onMouseDown={e => { e.preventDefault(); submit(); }}
                style={{ padding: "3px 8px", borderRadius: 5, border: "1px solid #6366f1", background: "#6366f1", fontSize: 10, fontWeight: 600, color: "#fff", cursor: busy ? "default" : "pointer", whiteSpace: "nowrap", opacity: busy ? 0.7 : 1 }}>
                {busy ? "…" : "Submit"}
              </button>
            )}
            <button
              onMouseDown={e => { e.preventDefault(); dismiss(); }}
              style={{ padding: "3px 8px", borderRadius: 5, border: "1px solid #e2e8f0", background: "#f8fafc", fontSize: 10, fontWeight: 600, color: "#64748b", cursor: "pointer", whiteSpace: "nowrap" }}>
              Dismiss
            </button>
          </div>
          {errMsg && (
            <div style={{ marginTop: 5, fontSize: 10, fontWeight: 600, color: "#b91c1c" }}>{errMsg}</div>
          )}
        </>
      )}
    </div>
  );
}

// ── Download Pre-flight Modal ──────────────────────────────────────────────
function DownloadPreflightModal({ openRecs, narrative, overrideReason, onOverrideChange, onProceed, onCancel, loading, hasHardBlock }) {
  // Hard-block items (placeholder values / required COPE-style fields, Figure 35
  // client feedback) still 409 server-side unless the request explicitly carries a
  // typed reason (services/field_qa.py's "hardblock_" rec_id marker), but the
  // display is deliberately UNIFIED with the ordinary Hard Stops box - same title,
  // same box, same "Download Anyway" label - so this doesn't read as a new/
  // different feature to the producer.
  const hardBlockItems = openRecs.filter(r => (r.rec_id || "").includes("hardblock_"));
  const hardRecs = openRecs.filter(r => r.recommendation_type === "hard_stop" && !(r.rec_id || "").includes("hardblock_"));
  const softRecs = openRecs.filter(r => r.recommendation_type !== "hard_stop" && !(r.rec_id || "").includes("hardblock_"));
  const allHardRecs = [...hardBlockItems, ...hardRecs];
  const reasonRequired = hasHardBlock && !overrideReason.trim();
  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(15,23,42,0.75)", backdropFilter: "blur(6px)", zIndex: 99999, display: "flex", alignItems: "center", justifyContent: "center", padding: 20 }}>
      <div style={{ background: "#fff", borderRadius: 16, padding: "28px 28px 24px", maxWidth: 520, width: "100%", boxShadow: "0 24px 60px rgba(0,0,0,0.22)", display: "flex", flexDirection: "column", gap: 0, maxHeight: "88vh", overflow: "hidden" }}>
        <div style={{ flexShrink: 0 }}>
          <div style={{ marginBottom: 14 }}>
            <div style={{ fontSize: 16, fontWeight: 700, color: "#0f172a" }}>SQS Review</div>
            <div style={{ fontSize: 12, color: "#64748b" }}>{openRecs.length > 0 ? `${openRecs.length} item${openRecs.length !== 1 ? "s" : ""} flagged - review before downloading` : "All clear - review the SQS summary below"}</div>
          </div>
        </div>
        <div style={{ flex: 1, overflowY: "auto", marginBottom: 16 }}>
          {allHardRecs.length > 0 && (
            <div style={{ background: "#fef2f2", border: "1px solid #fca5a5", borderRadius: 8, padding: "10px 12px", marginBottom: 10 }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: "#991b1b", marginBottom: 6 }}>Hard Stops ({allHardRecs.length})</div>
              {allHardRecs.map((r, i) => (
                <div key={i} style={{ fontSize: 12, color: "#7f1d1d", padding: "2px 0" }}>• {r.message}{r.score_impact ? <span style={{ color: "#dc2626", fontWeight: 700 }}> (–{r.score_impact} pts)</span> : ""}</div>
              ))}
            </div>
          )}
          {softRecs.length > 0 && (
            <div style={{ background: "#fffbeb", border: "1px solid #fde68a", borderRadius: 8, padding: "10px 12px", marginBottom: 10 }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: "#92400e", marginBottom: 6 }}>Open Recommendations ({softRecs.length})</div>
              {softRecs.map((r, i) => (
                <div key={i} style={{ fontSize: 12, color: "#78350f", padding: "2px 0" }}>• {r.message}{r.score_impact > 0 ? <span style={{ color: "#d97706", fontWeight: 600 }}> (up to +{r.score_impact} pts)</span> : ""}</div>
              ))}
            </div>
          )}
          {narrative && (
            <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: 10, padding: "16px 18px", marginTop: softRecs.length > 0 || hardRecs.length > 0 ? 10 : 0 }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: "#94a3b8", letterSpacing: "0.05em", textTransform: "uppercase", marginBottom: 10 }}>SQS Analysis Summary</div>
              <p style={{ fontSize: 13, color: "#334155", lineHeight: 1.75, margin: 0 }}>{narrative.replace(/\n+/g, " ").trim()}</p>
            </div>
          )}
        </div>
        <div style={{ flexShrink: 0 }}>
          <div style={{ marginBottom: 12 }}>
            <label style={{ display: "block", fontSize: 12, fontWeight: 600, color: "#374151", marginBottom: 5 }}>
              Override Note <span style={{ color: "#94a3b8", fontWeight: 400 }}>(recommended for E&O record)</span>
            </label>
            <textarea
              value={overrideReason}
              onChange={e => onOverrideChange(e.target.value)}
              placeholder="e.g. Client acknowledged gaps and approved submission as-is"
              rows={2}
              style={{ width: "100%", padding: "8px 10px", border: "1px solid #e2e8f0", borderRadius: 8, fontSize: 12, resize: "vertical", outline: "none", fontFamily: "inherit", boxSizing: "border-box" }}
              onFocus={e => e.target.style.borderColor = "#E61B84"}
              onBlur={e => e.target.style.borderColor = "#e2e8f0"}
            />
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <button onClick={onCancel} style={{ flex: 1, padding: "9px 0", borderRadius: 8, border: "1px solid #e2e8f0", background: "#f8fafc", color: "#475569", fontSize: 13, fontWeight: 600, cursor: "pointer" }}>
              Cancel
            </button>
            <button
              onClick={onProceed}
              disabled={loading}
              style={{ flex: 2, padding: "9px 0", borderRadius: 8, border: "none", background: !loading ? "#E61B84" : "#e2e8f0", color: !loading ? "#fff" : "#94a3b8", fontSize: 13, fontWeight: 700, cursor: !loading ? "pointer" : "not-allowed", display: "flex", alignItems: "center", justifyContent: "center", gap: 6 }}>
              {loading ? <><span style={{ width: 11, height: 11, border: "2px solid rgba(255,255,255,0.5)", borderTopColor: "#fff", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" }} />Processing…</> : "Download Anyway"}
            </button>
          </div>
          {reasonRequired && (
            <div style={{ fontSize: 11, color: "#991b1b", marginTop: 8 }}>
              Add a note above before proceeding - required for the items in Hard Stops.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Dashboard Assistant (in-app chatbot, mirrors the ARQ client chat) ────────
function DashboardAssistant() {
  const FALLBACK = "Sorry, I couldn't process that just now. Please try again in a moment.";
  const [messages, setMessages] = useState([
    { role: "assistant", content: "Hi! I'm Primble Assistant. Ask me anything about preparing your submission." },
  ]);
  const [input, setInput] = useState("");
  const [busy, setBusy]   = useState(false);
  const bottomRef         = useRef(null);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages, busy]);

  const send = async () => {
    const msg = input.trim();
    if (!msg || busy) return;
    // Basic sanitization - strip tags, cap length (matches ARQ client chat).
    const sanitized = msg.replace(/<[^>]*>/g, "").slice(0, 800);
    const history   = messages.filter(m => m.role !== "system");
    setMessages(prev => [...prev, { role: "user", content: sanitized }]);
    setInput("");
    setBusy(true);
    try {
      const res   = await fetch(`${API_BASE}/api/assistant/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ message: sanitized, history }),
      });
      const data  = res.ok ? await res.json() : null;
      const reply = (data?.reply || "").trim() || FALLBACK;
      setMessages(prev => [...prev, { role: "assistant", content: reply }]);
    } catch {
      setMessages(prev => [...prev, { role: "assistant", content: FALLBACK }]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="db-sidebar-card db-assistant-card">
      <div className="db-sidebar-card-title">Primble Assistant</div>
      <div className="db-assistant-messages">
        {messages.map((m, i) => (
          <div key={i} className={`db-assistant-row ${m.role === "user" ? "is-user" : "is-bot"}`}>
            <div className="db-assistant-bubble">{m.content}</div>
          </div>
        ))}
        {busy && (
          <div className="db-assistant-row is-bot">
            <div className="db-assistant-bubble db-assistant-typing"><span /><span /><span /></div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>
      <div className="db-assistant-input-row">
        <input
          className="db-assistant-input"
          type="text"
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
          placeholder="What can I help you with?"
          maxLength={800}
          aria-label="Message Primble Assistant"
        />
        <button className="db-assistant-send" onClick={send} disabled={busy || !input.trim()} aria-label="Send message">↑</button>
      </div>
    </div>
  );
}

// ── Dashboard Step ─────────────────────────────────────────────────────────
function DashboardStep({ token, onResume, onNewPackage }) {
  const [sessions, setSessions] = useState([]);
  const [stats, setStats] = useState({ total_packages: 0, total_forms: 0, avg_sqs_score: null });
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);
  const [deleteTarget, setDeleteTarget] = useState(null);
  // Server-side pagination: 10 packages per page, every page reachable.
  const PAGE_SIZE = 10;
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [statsLoaded, setStatsLoaded] = useState(false);
  // Keyword search (server-side, debounced) - coexists with pagination.
  const [search, setSearch]       = useState("");
  const [query, setQuery]         = useState("");
  const [searching, setSearching] = useState(false);

  const fetchStats = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/sessions/stats`, { credentials: "include" });
      const statsData = res.ok ? await res.json() : null;
      if (statsData) setStats({ total_packages: statsData.total_packages ?? 0, total_forms: statsData.total_forms ?? 0, avg_sqs_score: statsData.avg_sqs_score ?? null });
    } catch { /* stats are non-critical - leave prior values */ }
    finally { setStatsLoaded(true); }
  };

  // overlay=true drives the full-screen loader (initial load + pagination,
  // unchanged). overlay=false is the quiet path used by keyword search so it
  // doesn't flash the whole screen on each keystroke.
  const fetchSessions = async (pg, { overlay = true } = {}) => {
    if (overlay) setLoading(true); else setSearching(true);
    setLoadError(null);
    try {
      const qs   = query ? `&search=${encodeURIComponent(query)}` : "";
      const res  = await fetch(`${API_BASE}/api/sessions?page=${pg}&page_size=${PAGE_SIZE}${qs}`, { credentials: "include" });
      const data = res.ok ? await res.json() : null;
      if (data?.success) { setSessions(data.sessions || []); setTotal(data.total ?? 0); }
      else setLoadError("Could not load your sessions. Please refresh.");
    } catch {
      setLoadError("Network error loading sessions. Please refresh.");
    } finally {
      if (overlay) setLoading(false); else setSearching(false);
    }
  };

  useEffect(() => { fetchStats(); }, []);
  // Initial load + pagination: full-screen loader (unchanged behavior).
  useEffect(() => { fetchSessions(page); }, [page]); // eslint-disable-line
  // Debounce the search box into the query that fetchSessions actually sends.
  useEffect(() => {
    const t = setTimeout(() => setQuery(search.trim()), 350);
    return () => clearTimeout(t);
  }, [search]);
  // On a new query: reset to page 1 (the [page] effect refetches) or, if already
  // on page 1, do a quiet in-place fetch so search doesn't flash the full overlay.
  const firstQueryRun = useRef(true);
  useEffect(() => {
    if (firstQueryRun.current) { firstQueryRun.current = false; return; }
    if (page !== 1) setPage(1);
    else fetchSessions(1, { overlay: false });
  }, [query]); // eslint-disable-line

  const handleDelete = async sid => {
    setDeleteTarget(null);
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/sessions/${sid}`, { method: "DELETE", credentials: "include" });
      if (!res.ok) throw new Error("Delete failed");
    } catch {
      setLoading(false);
      setLoadError("Failed to delete session. Please try again.");
      return;
    }
    fetchStats();
    // If that was the last card on a page beyond the first, step back a page
    // (the [page] effect refetches); otherwise refresh the current page.
    if (sessions.length === 1 && page > 1) setPage(p => p - 1);
    else fetchSessions(page);
  };

  const fmtDate = iso => {
    if (!iso) return "-";
    const d = new Date(iso);
    const diffDays = Math.floor((Date.now() - d) / 86400000);
    if (diffDays === 0) return "Today";
    if (diffDays === 1) return "Yesterday";
    if (diffDays < 7) return `${diffDays}d ago`;
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: diffDays > 300 ? "numeric" : undefined });
  };

  const avgSqs = sqsMap => {
    const scores = Object.values(sqsMap || {}).map(s => s?.sqs_score).filter(n => n != null);
    return scores.length ? Math.round(scores.reduce((a, b) => a + b, 0) / scores.length) : null;
  };
  // Decision_Tree.txt §522-527: A≥90 (green), B≥80 (yellow), C≥70 (orange),
  // D≥60 (red), F<60 (red). Per client confirmation, C/D are visually combined
  // into a single "needs attention" band but use distinct grade letters.
  const sqsColor  = v => v >= 80 ? "#10b981" : v >= 70 ? "#f59e0b" : "#ef4444";
  const sqsBg     = v => v >= 80 ? "rgba(16,185,129,0.1)" : v >= 70 ? "rgba(245,158,11,0.1)" : "rgba(239,68,68,0.1)";
  const sqsGrade  = v => v >= 90 ? "A" : v >= 80 ? "B" : v >= 70 ? "C" : v >= 60 ? "D" : "F";

  // Workflow status shown per session. AWAITING_CLIENT mirrors a still-open ARQ
  // (the client's "Waiting on client questions"); the rest map the download /
  // progress lifecycle to friendly labels.
  const STATUS_META = {
    AWAITING_CLIENT: { label: "Waiting on client questions", color: "#b45309", bg: "rgba(245,158,11,0.14)" },
    COMPLETED:       { label: "Completed",                    color: "#047857", bg: "rgba(16,185,129,0.14)" },
    IN_PROGRESS:     { label: "In progress",                  color: "#1d4ed8", bg: "rgba(59,130,246,0.14)" },
    NOT_STARTED:     { label: "New",                          color: "#64748b", bg: "rgba(100,116,139,0.14)" },
  };
  const statusMeta = st => STATUS_META[st] || STATUS_META.NOT_STARTED;
  // Readiness: "Quote Ready" at package SQS 90+, matching the app's existing
  // "Ready to Send Submission" boundary. Only meaningful once an SQS exists.
  const readinessOf = avg => (avg == null ? null : (avg >= 90 ? { label: "Quote Ready", ready: true } : { label: "Not Quote Ready", ready: false }));

  const totalForms = stats.total_forms;
  const globalAvg  = stats.avg_sqs_score;

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  // Compact windowed page list, e.g. 1 … 5 6 7 … 72 (ellipsis as a string token).
  const pageList = () => {
    const delta = 1, range = [], out = [];
    for (let i = Math.max(1, page - delta); i <= Math.min(totalPages, page + delta); i++) range.push(i);
    if (range[0] > 1) { out.push(1); if (range[0] > 2) out.push("…"); }
    out.push(...range);
    if (range[range.length - 1] < totalPages) { if (range[range.length - 1] < totalPages - 1) out.push("…"); out.push(totalPages); }
    return out;
  };

  const tips = [
    "Upload client documents, applications, loss runs, schedules, or other submission materials.",
    "Let Primble extract key data and check the package for missing or inconsistent information.",
    "Resolve quality findings with guided client follow-up before finalizing the package.",
    "Download underwriting-ready forms, supporting materials, and/or a submission brief once the package is complete.",
  ];

  return (
    <>
    {loading && (
      <div className="loading-overlay">
        <div className="loading-spinner" />
        <p className="loading-text">Loading sessions…</p>
      </div>
    )}
    <div className="dashboard-shell">
      {deleteTarget && <DeleteConfirmModal onConfirm={() => handleDelete(deleteTarget)} onCancel={() => setDeleteTarget(null)} />}

      {loadError && (
        <div className="db-error-banner">
          {loadError}
        </div>
      )}

      {/* ── Header ── */}
      <div className="db-header">
        <div>
          <div className="db-header-eyebrow">Submissions</div>
          <h2 className="db-header-title">Recent Packages</h2>
          <p className="db-header-sub">Pick up where you left off or start a new submission.</p>
        </div>
        <button onClick={onNewPackage} className="db-primary-btn">+ Upload New Package</button>
      </div>

      {/* ── Two-column body ── */}
      <div className="dashboard-body">

        {/* ── Main: package list ── */}
        <div className="dashboard-main">

          {/* ── Stat band (relocated from the sidebar Overview card) ── */}
          <div className="db-statband">
            {[
              { label: "Total Packages",  value: statsLoaded ? stats.total_packages : "-" },
              { label: "Forms Generated", value: statsLoaded ? totalForms : "-" },
              { label: "Average Score",   value: statsLoaded ? (globalAvg != null ? `${globalAvg}%` : "-") : "-" },
            ].map((item, i) => (
              <div key={i} className="db-stat">
                <div className="db-stat-label">{item.label}</div>
                <div className="db-stat-value">{item.value}</div>
              </div>
            ))}
          </div>

          {/* ── Keyword search (server-side, coexists with pagination) ── */}
          {(sessions.length > 0 || query) && (
            <div className="db-search-wrap">
              <svg className="db-search-icon" width="17" height="17" viewBox="0 0 24 24" fill="none"><circle cx="11" cy="11" r="7" stroke="currentColor" strokeWidth="2"/><path d="M21 21l-4.3-4.3" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/></svg>
              <input
                className="db-search-input"
                type="text"
                value={search}
                onChange={e => setSearch(e.target.value)}
                placeholder="Search by Keyword"
                maxLength={100}
                aria-label="Search packages by keyword"
              />
              {searching && <span className="db-search-spinner" />}
              {search && (
                <button className="db-search-clear" onClick={() => setSearch("")} aria-label="Clear search">✕</button>
              )}
            </div>
          )}

          {loading ? null : sessions.length === 0 ? (
            query ? (
              <div className="db-no-results">
                <p className="db-no-results-title">No packages match "{query}"</p>
                <button className="db-no-results-btn" onClick={() => setSearch("")}>Clear search</button>
              </div>
            ) : (
            <div className="db-empty-state">
              <div className="db-empty-topbar" />
              <p className="db-empty-title">No packages yet</p>
              <p className="db-empty-desc">Upload your first submission package to extract key data, check submission quality, and prepare underwriting-ready forms and materials.</p>
              <div className="db-empty-steps">
                {[["Upload docs", "Check quality", "Fix issues", "Generate forms"]].flat().map((label, i, arr) => (
                  <div key={i} style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    <div className="db-empty-step-pill">{label}</div>
                    {i < arr.length - 1 && <span className="db-empty-step-arrow">→</span>}
                  </div>
                ))}
              </div>
              <button onClick={onNewPackage} className="db-primary-btn">
                Start First Package
              </button>
            </div>
            )
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
              <div className="db-list-count">
                {total} Package{total !== 1 ? "s" : ""}{totalPages > 1 ? ` · Page ${page} of ${totalPages}` : ""}
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {sessions.map(s => {
                  const avg   = avgSqs(s.sqs);
                  const color = avg != null ? sqsColor(avg) : "#94a3b8";
                  const bg    = avg != null ? sqsBg(avg)    : "rgba(148,163,184,0.08)";
                  const grade = avg != null ? sqsGrade(avg) : null;
                  const formCount = s.form_ids?.length || 0;
                  const meta      = statusMeta(s.status);
                  const rd        = readinessOf(avg);
                  return (
                    <div key={s.session_id} className="session-card"
                      onClick={() => onResume(s.session_id)}
                      style={{ background: "#fff", border: "1.5px solid #e0e0e0", borderRadius: 18, cursor: "pointer", display: "flex", alignItems: "stretch", transition: "all 0.18s", position: "relative", boxShadow: "0 2px 8px rgba(0,0,0,0.06)", overflow: "hidden" }}
                      onMouseEnter={e => { e.currentTarget.style.borderColor = "#E61B84"; e.currentTarget.style.boxShadow = "0 8px 32px rgba(230,0,122,0.12)"; e.currentTarget.style.transform = "translateY(-1px)"; }}
                      onMouseLeave={e => { e.currentTarget.style.borderColor = "#e0e0e0"; e.currentTarget.style.boxShadow = "0 2px 8px rgba(0,0,0,0.06)"; e.currentTarget.style.transform = "none"; }}>

                      <div style={{ width: 4, background: "#E61B84", flexShrink: 0 }} />

                      <div style={{ flex: 1, padding: "18px 22px", display: "flex", alignItems: "center", gap: 16, minWidth: 0 }}>

                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ fontWeight: 700, fontSize: 15, color: "#0b0b0b", marginBottom: 6, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                            {s.applicant || "Unnamed Package"}
                          </div>
                          <div style={{ display: "flex", gap: 5, flexWrap: "wrap", alignItems: "center" }}>
                            {formCount > 0 && (
                              <span className="db-badge db-badge-pink">
                                {formCount} form{formCount !== 1 ? "s" : ""}
                              </span>
                            )}
                            {s.form_ids?.slice(0, 4).map(fid => (
                              <span key={fid} className="db-badge db-badge-gray">{fid.replace(/_/g, " ")}</span>
                            ))}
                            {(s.form_ids?.length || 0) > 4 && <span style={{ fontSize: 11, color: "#b5b5b5" }}>+{s.form_ids.length - 4}</span>}
                            {s.lines?.length > 0 && (
                              <span style={{ fontSize: 11, color: "#b5b5b5" }}>· {s.lines.slice(0, 2).join(", ")}{s.lines.length > 2 ? ` +${s.lines.length - 2}` : ""}</span>
                            )}
                          </div>
                          {/* Created date, workflow status, and quote readiness. The
                              last-updated date is shown prominently in the right column. */}
                          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", marginTop: 8 }}>
                            <span style={{ fontSize: 11, color: "#94a3b8" }}>Created {fmtDate(s.created_at)}</span>
                            <span style={{ fontSize: 10.5, fontWeight: 700, color: meta.color, background: meta.bg, borderRadius: 20, padding: "2px 9px" }}>{meta.label}</span>
                            {rd && (
                              <span style={{ fontSize: 10.5, fontWeight: 700, color: rd.ready ? "#047857" : "#b45309", background: rd.ready ? "rgba(16,185,129,0.14)" : "rgba(245,158,11,0.14)", borderRadius: 20, padding: "2px 9px" }}>{rd.label}</span>
                            )}
                          </div>
                        </div>

                        <div style={{ flexShrink: 0, textAlign: "right", marginRight: 4 }}>
                          <div style={{ fontSize: 9.5, fontWeight: 700, color: "#b5b5b5", textTransform: "uppercase", letterSpacing: "0.04em" }}>Updated</div>
                          <div style={{ fontSize: 12, fontWeight: 600, color: "#6a6a6a" }}>{fmtDate(s.updated_at)}</div>
                        </div>

                        <div style={{ width: 54, height: 54, borderRadius: "50%", background: avg != null ? "rgba(230,0,122,0.08)" : "rgba(148,163,184,0.08)", border: `2px solid ${avg != null ? "#E61B8455" : "#94a3b855"}`, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                          {avg != null ? (
                            <>
                              <span style={{ fontSize: 15, fontWeight: 800, color: "#E61B84", lineHeight: 1 }}>{avg}</span>
                              <span style={{ fontSize: 9, fontWeight: 700, color: "#E61B84", opacity: 0.8, marginTop: 1 }}>{grade}</span>
                            </>
                          ) : (
                            <span style={{ fontSize: 9, color: "#b5b5b5", fontWeight: 600, textAlign: "center", lineHeight: 1.3 }}>{"SQS\n-"}</span>
                          )}
                        </div>

                        <div style={{ color: "#e0e0e0", flexShrink: 0, display: "flex", alignItems: "center" }}>
                          <svg width="16" height="16" viewBox="0 0 24 24" fill="none"><path d="M9 18l6-6-6-6" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"/></svg>
                        </div>

                        <button className="session-delete-btn" onClick={e => { e.stopPropagation(); setDeleteTarget(s.session_id); }} title="Delete session" style={{ position: "absolute", top: 10, right: 10 }}>✕</button>
                      </div>
                    </div>
                  );
                })}
              </div>
              {totalPages > 1 && (
                <div className="db-pagination" style={{ display: "flex", flexWrap: "wrap", gap: 6, justifyContent: "center", alignItems: "center", marginTop: 16 }}>
                  <button
                    onClick={() => setPage(p => Math.max(1, p - 1))}
                    disabled={page <= 1 || loading}
                    style={{ background: "#fff", border: "1.5px solid #e0e0e0", borderRadius: 9, padding: "7px 14px", fontSize: 13, fontWeight: 700, color: page <= 1 ? "#c4c4c4" : "#E61B84", cursor: page <= 1 ? "default" : "pointer" }}
                  >
                    Prev
                  </button>
                  {pageList().map((p, i) => (
                    p === "…"
                      ? <span key={`e${i}`} style={{ fontSize: 13, color: "#b5b5b5", padding: "0 2px" }}>…</span>
                      : (
                        <button
                          key={p}
                          onClick={() => setPage(p)}
                          disabled={loading}
                          aria-current={p === page ? "page" : undefined}
                          style={{
                            minWidth: 36, background: p === page ? "#E61B84" : "#fff",
                            border: `1.5px solid ${p === page ? "#E61B84" : "#e0e0e0"}`, borderRadius: 9,
                            padding: "7px 11px", fontSize: 13, fontWeight: 700,
                            color: p === page ? "#fff" : "#4a4a4a", cursor: p === page ? "default" : "pointer",
                          }}
                        >
                          {p}
                        </button>
                      )
                  ))}
                  <button
                    onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                    disabled={page >= totalPages || loading}
                    style={{ background: "#fff", border: "1.5px solid #e0e0e0", borderRadius: 9, padding: "7px 14px", fontSize: 13, fontWeight: 700, color: page >= totalPages ? "#c4c4c4" : "#E61B84", cursor: page >= totalPages ? "default" : "pointer" }}
                  >
                    Next
                  </button>
                </div>
              )}
            </div>
          )}
        </div>

        {/* ── Right sidebar ── */}
        <aside className="dashboard-sidebar">

          {/* Tips card */}
          <div className="db-sidebar-card">
            <div className="db-sidebar-card-title">Tips</div>
            <ol className="db-tips-list">
              {tips.map((tip, i) => (
                <li key={i} className="db-tip-item">{tip}</li>
              ))}
            </ol>
          </div>

          {/* Primble Assistant chatbot */}
          <DashboardAssistant />

        </aside>
      </div>
    </div>
    </>
  );
}

// ── Main AcordModal ────────────────────────────────────────────────────────
const AcordModal = forwardRef(function AcordModal({
  onClose, user, token, onUserUpdate, onShowUpgrade,
  resumeSessionId, savedSignature, onOpenSignatureModal,
  onOpenBillingPortal, billingPortalLoading,
  fullPage = false,
}, ref) {
  const fileInputRef = useRef(null);
  const [files, setFiles] = useState([]);
  const [dragging, setDragging] = useState(false);
  const [loading, setLoading] = useState(false);
  const [processingStage, setProcessingStage] = useState("");
  const [step, setStep] = useState(resumeSessionId ? "resuming" : "dashboard");
  const [showUploadOverlay, setShowUploadOverlay] = useState(false);
  // Figure 1: token that keys the live per-file upload progress side-channel.
  const [uploadProgressToken, setUploadProgressToken] = useState(null);
  const [resumingUpload, setResumingUpload] = useState(false);
  const [showSlowUploadMsg, setShowSlowUploadMsg] = useState(false);
  const [jobToasts, setJobToasts] = useState([]);

  useEffect(() => {
    if (step === "editor") {
      document.body.style.overflow = "hidden";
      window.scrollTo(0, 0);
    } else {
      document.body.style.overflow = "";
    }
    return () => { document.body.style.overflow = ""; };
  }, [step]);

  useEffect(() => {
    if (!showUploadOverlay) { setShowSlowUploadMsg(false); return; }
    const t = setTimeout(() => setShowSlowUploadMsg(true), 5000);
    return () => clearTimeout(t);
  }, [showUploadOverlay]);

  const [error, setError] = useState(null);
  const [sessionId, setSessionId] = useState(resumeSessionId || null);
  const [docSummary, setDocSummary] = useState([]);
  const [flags, setFlags] = useState({});
  const [hardStops, setHardStops] = useState([]);
  const [canProceedWithWarning, setCanProceedWithWarning] = useState(false);
  const [warningStops, setWarningStops] = useState([]);
  const [softStops, setSoftStops] = useState([]);
  // Figures 4/5: clustered + tiered view of hardStops/softStops (grouped_issues
  // from the backend). Purely presentational - never affects SQS capping.
  const [groupedIssues, setGroupedIssues] = useState(null);
  const [tier2Score, setTier2Score] = useState(null);
  const [tier2Missing, setTier2Missing] = useState([]);
  const [recommendations, setRecommendations] = useState([]);
  const [accountProfile, setAccountProfile] = useState(null);
  const [allAvailableForms, setAllAvailableForms] = useState([]);
  // "Why are you marketing this account?" (DOUBTS-Workstream4 / Brent) - answering
  // re-runs recommendations so ACORD 101 escalates to its correct tier.
  const [marketingReason, setMarketingReason] = useState("");
  const [marketingOther, setMarketingOther] = useState("");
  const [marketingBusy, setMarketingBusy] = useState(false);
  // Submission Integrity Validation (Beta Report §4.1)
  const [integrity, setIntegrity] = useState(null);
  const [integrityBusy, setIntegrityBusy] = useState(false);
  const [removeDocIds, setRemoveDocIds] = useState(new Set());
  // Document classification correction (Beta Report §4.2)
  const [availableDocTypes, setAvailableDocTypes] = useState([]);
  const [reclassDocId, setReclassDocId] = useState(null); // doc_id currently being reclassified
  const [reclassBusyBtn, setReclassBusyBtn] = useState(null); // which button triggered it: "toggle" | "supporting" | "type"
  const [reviewData, setReviewData] = useState(null);     // "Review extracted data" payload (Beta Report §4.2)
  const [reviewLoadingId, setReviewLoadingId] = useState(null); // doc_id whose extracted data is loading
  // Normalization notices: values that differed in format but were treated as equivalent (§5.1)
  const [normalizedDiffs, setNormalizedDiffs] = useState([]);
  // Core Underwriting Data Consistency - Gross Sales reconciliation (Beta Report §4.3)
  const [underwriting, setUnderwriting] = useState(null);
  const [underwritingBusy, setUnderwritingBusy] = useState(null); // fact_key currently confirming
  const [underwritingPicks, setUnderwritingPicks] = useState({});  // {fact_key: chosen/typed value}

  // Figure 3: pre-select the suggested value for HIGH-confidence, non-hard-stop
  // conflicts (the backend sets f.preselect). Only seeds a field the user has NOT
  // already picked/typed, so a re-fetch (e.g. after confirming another field)
  // never clobbers an in-progress choice, and hard-stop identity fields (name,
  // FEIN, dates) are never auto-checked.
  useEffect(() => {
    const fields = underwriting?.fields;
    if (!Array.isArray(fields)) return;
    setUnderwritingPicks(prev => {
      let next = prev;
      for (const f of fields) {
        if (f.status === "conflict" && f.preselect && f.suggested_value != null
            && (prev[f.fact_key] === undefined || prev[f.fact_key] === "")) {
          if (next === prev) next = { ...prev };
          next[f.fact_key] = f.suggested_value;
        }
      }
      return next;
    });
  }, [underwriting]);
  const [checkedFormIds, setCheckedFormIds] = useState(new Set());
  const [showAddForms, setShowAddForms] = useState(false);
  const [generatedForms, setGeneratedForms] = useState({});
  const [activeFormId, setActiveFormId] = useState(null);
  // Figure 10: close any open provenance popover when the active form changes.
  useEffect(() => { setProvCard(null); }, [activeFormId]);
  const [crossIssues, setCrossIssues] = useState([]);
  // Durable-issue-id -> { status, reason } for the rail's resolution status.
  // Work-tracking only; never affects the SQS score.
  const [issueStatuses, setIssueStatuses] = useState(new Map());
  const [pdfLoading, setPdfLoading] = useState({});
  const [pkgStatusMsg, setPkgStatusMsg] = useState("");
  const [pkgStatusType, setPkgStatusType] = useState("");
  const [signedForms, setSignedForms] = useState(new Set());
  const [showGenerateOverlay, setShowGenerateOverlay] = useState(false);
  // Fig 8: when a session is reopened mid-generation, this holds the remaining
  // seconds (recomputed from the server's start time) so the same progress
  // overlay resumes its countdown instead of restarting from a full estimate.
  const [resumeGenEta, setResumeGenEta] = useState(null);
  const [showDownloadOverlay, setShowDownloadOverlay] = useState(false);
  const [showAcordModal, setShowAcordModal] = useState(false);
  const [acordModalAction, setAcordModalAction] = useState(null);
  const [acordLicenseChecked, setAcordLicenseChecked] = useState(false);
  const [acordModalLoading, setAcordModalLoading] = useState(false);
  const [epicLoading, setEpicLoading] = useState(false);
  const [epicSuccess, setEpicSuccess] = useState(false);
  const [vertaforeLoading, setVertaforeLoading] = useState(false);
  const [vertaforeSuccess, setVertaforeSuccess] = useState(false);
  const [showARQModal, setShowARQModal] = useState(false);
  const [arqQuestions, setArqQuestions] = useState([]);
  const [arqSummary, setArqSummary] = useState(null);
  const [arqLoadingQ, setArqLoadingQ] = useState(false);
  const [arqSessions, setArqSessions] = useState([]);
  const [arqNotifCount, setArqNotifCount] = useState(0);
  const [clientFilledFields, setClientFilledFields] = useState([]);
  const [actionsOpen, setActionsOpen] = useState(false);
  const [generatedFormsOpen, setGeneratedFormsOpen] = useState(false);
  const [integrationsExpanded, setIntegrationsExpanded] = useState(false);
  const [downloadExpanded, setDownloadExpanded] = useState(false);
  const [showEnterprisePopup, setShowEnterprisePopup] = useState(false);
  const [enterprisePopupPos, setEnterprisePopupPos] = useState({ top: 0, left: 0 });
  const [liteSqsData, setLiteSqsData] = useState(null);
  const [liteGenerating, setLiteGenerating] = useState(false);
  const [liteCoverLoading, setLiteCoverLoading] = useState(false);
  const [auditExportLoading, setAuditExportLoading] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(() => window.innerWidth > 900);

  // ── SQS enhancement state ──────────────────────────────────────────────────
  const [packageSqs, setPackageSqs] = useState(null);
  // §6.1: which package pillars are expanded to show their 15-category detail.
  const [expandedPillars, setExpandedPillars] = useState(() => new Set());
  // Figure 10: which score component's provenance popover is open, and where.
  // { group, key, pos } or null. Clicking the same trigger again closes it.
  const [provCard, setProvCard] = useState(null);
  const openProv = (group, key, target) => {
    const r = target.getBoundingClientRect();
    const width = Math.min(240, window.innerWidth - 16);
    let left = r.left + r.width / 2 - width / 2;
    left = Math.max(8, Math.min(left, window.innerWidth - width - 8));
    const pos = { top: r.bottom + 6, left, width };
    setProvCard(p => (p && p.group === group && p.key === key) ? null : { group, key, pos });
  };
  const closeProv = () => setProvCard(null);
  const [dismissedRecs, setDismissedRecs] = useState(new Set());
  const [dismissedRecDetails, setDismissedRecDetails] = useState(new Map());
  const [showDownloadPreflight, setShowDownloadPreflight] = useState(false);
  const [preflightRecs, setPreflightRecs] = useState([]);
  const [preflightHardBlock, setPreflightHardBlock] = useState(false);
  const [preflightOverrideReason, setPreflightOverrideReason] = useState("");
  const [preflightCallback, setPreflightCallback] = useState(null);
  const [sqsNarrative, setSqsNarrative] = useState("");
  const [downloadPreflightLoading, setDownloadPreflightLoading] = useState(false);

  useEffect(() => {
    if (step !== "lite" || !sessionId) return;

    // Generate the top recommended form and compute accurate SQS + ARQ in one call.
    // Both buttons stay disabled until this completes so the user always sees
    // form-based SQS and has ARQ questions ready the moment they click.
    setLiteGenerating(true);
    setLiteSqsData(null);
    fetch(`${API_BASE}/api/lite/generate-internal/${sessionId}`, { method: "POST", credentials: "include" })
      .then(r => r.ok ? r.json() : null)
      .then(d => {
        if (d?.success) setLiteSqsData(d);
        else setError("Could not score submission. Please try again.");
      })
      .catch(() => setError("Could not score submission. Please try again."))
      .finally(() => setLiteGenerating(false));
  }, [step, sessionId]); // eslint-disable-line

  // Usage counting (client 2026-07-01): professional/business consume one package
  // the moment the form-recommendations screen is shown - the point at which the
  // submission has been analysed - rather than waiting for a download. The call
  // is idempotent per session server-side (a no-op for other tiers, an already
  // counted session, or one still pending integrity review), so it is safe to
  // fire on every visit to this step. We refresh the user afterwards so any usage
  // display reflects the new count.
  useEffect(() => {
    if (step !== "recommendations" || !sessionId) return;
    const tier = user?.subscription_tier;
    if (tier !== "professional" && tier !== "business") return;
    fetch(`${API_BASE}/api/session/${sessionId}/count-usage`, { method: "POST", credentials: "include" })
      .then(r => (r.ok ? r.json() : null))
      .then(d => { if (d?.counted) refreshUser().catch(() => {}); })
      .catch(() => {});
  }, [step, sessionId]); // eslint-disable-line

  // Restore a session that has NOT generated forms yet — i.e. one paused at the
  // Submission Integrity review or sitting on the recommendations / SQS step.
  // Lets users reopen in-progress submissions (including the extra ones created
  // by "Create separate submissions") instead of being bounced to the dashboard
  // (Beta Report §4.1). Returns true on success. Works for all non-essentials
  // tiers; essentials always lands on the "lite" SQS step separately.
  const _restoreFromExtraction = async (sid, signal) => {
    try {
      const res = await fetch(`${API_BASE}/api/session/${sid}/extraction-result`, { credentials: "include", signal });
      const data = res.ok ? await res.json() : null;
      if (!data?.success) return false;
      setSessionId(sid);
      setDocSummary(data.doc_summary || []); setFlags(data.flags || {});
      setAvailableDocTypes(data.available_doc_types || []);
      setHardStops(data.hard_stops || []); setSoftStops(data.soft_stops || []); setNormalizedDiffs(data.normalized_differences || []);
      setGroupedIssues(data.grouped_issues || null);
      setCanProceedWithWarning(!!data.can_proceed_with_warning);
      setWarningStops(data.warning_stops || []);
      setTier2Score(data.tier2_score ?? null); setTier2Missing(data.tier2_missing || []);
      setRecommendations(data.recommendations || []); setAllAvailableForms(data.all_available_forms || []);
      setAccountProfile(data.account_profile || null);
      setCheckedFormIds(new Set());
      setUnderwriting(data.underwriting_consistency || null); setUnderwritingPicks({});
      setIntegrity(data.integrity || null);
      if (data.integrity_review_required) {
        setRemoveDocIds(new Set());
        setStep("integrity_review");
      } else {
        setStep("recommendations");
      }
      return true;
    } catch {
      return false;
    }
  };

  // ── Figure 1 resume ──────────────────────────────────────────────────────
  // If the tab was refreshed OR closed mid-upload, a progress token is still in
  // localStorage (durable across tab close, unlike sessionStorage). Re-attach the
  // overlay to the in-flight run (the server keeps processing regardless of the
  // client) and reload the finished submission when the poll reports done - or, if
  // the user reopens too soon, keep showing the loader until it finishes. Skipped
  // when an explicit resumeSessionId is opening.
  const handleUploadResumeDone = async (data) => {
    const sid = data?.session_id;
    const ok = sid ? await _restoreFromExtraction(sid) : false;
    if (!ok) setError("We couldn't reopen your previous upload automatically. Please check your submissions or try again.");
    setResumingUpload(false); setShowUploadOverlay(false); setLoading(false);
    setUploadProgressToken(null);
    try { localStorage.removeItem("primble_upload_token"); } catch { /* private mode */ }
  };

  const handleUploadResumeMissing = () => {
    // Token expired / run not found → drop the overlay quietly; the user can
    // reopen a finished submission from history or re-upload.
    setResumingUpload(false); setShowUploadOverlay(false); setLoading(false);
    setUploadProgressToken(null);
    try { localStorage.removeItem("primble_upload_token"); } catch { /* private mode */ }
  };

  useEffect(() => {
    if (resumeSessionId) return;   // explicit session resume takes precedence
    let token = null;
    try { token = localStorage.getItem("primble_upload_token"); } catch { /* private mode */ }
    if (!token) return;
    setUploadProgressToken(token);
    setResumingUpload(true);
    setShowUploadOverlay(true);
    setLoading(true);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!resumeSessionId) return;
    setLoading(true); setProcessingStage("Restoring your session...");
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 20000);
    fetch(`${API_BASE}/api/session/${resumeSessionId}`, { credentials: "include", signal: ctrl.signal })
      .then(r => r.ok ? r.json() : null)
      .then(async data => {
        const isEssentials = user?.subscription_tier === "essentials";
        if (isEssentials && data?.session_id) {
          setSessionId(resumeSessionId); setStep("lite");
        } else if (!isEssentials && data && data.generated_forms && Object.keys(data.generated_forms).length > 0) {
          setGeneratedForms(data.generated_forms); setCrossIssues(data.cross_issues || []);
          if (data.package_sqs) setPackageSqs(data.package_sqs);
          const firstId = Object.keys(data.generated_forms)[0]; setActiveFormId(firstId);
          const readyMap = {}; Object.keys(data.generated_forms).forEach(fid => { readyMap[fid] = false; });
          setPdfLoading(readyMap); setStep("editor");
        } else if (!isEssentials && data && data.generation_job_id) {
          // Reopened mid-generation (forms not persisted yet): resume the same
          // progress overlay with the remaining time and poll until the server
          // finishes (Fig 8). Fall back to the recommendations restore if the
          // run already failed while we were away.
          const done = await _resumeGeneration(resumeSessionId, data);
          if (!done) {
            const ok = await _restoreFromExtraction(resumeSessionId, ctrl.signal);
            if (!ok) { setStep("dashboard"); setSessionId(null); }
          }
        } else if (!isEssentials && data) {
          // In-progress submission (no forms yet) → land on the integrity review
          // or the recommendations/SQS step rather than dropping to the dashboard.
          const ok = await _restoreFromExtraction(resumeSessionId, ctrl.signal);
          if (!ok) { setStep("dashboard"); setSessionId(null); }
        } else { setStep("dashboard"); setSessionId(null); }
      })
      .catch(() => { setError("Could not restore session. Please try again."); setStep("dashboard"); setSessionId(null); })
      .finally(() => { clearTimeout(timer); setLoading(false); setProcessingStage(""); });
  }, [resumeSessionId]); // eslint-disable-line

  const handleDragOver = e => { e.preventDefault(); setDragging(true); };
  const handleDragLeave = () => setDragging(false);
  const handleDrop = e => {
    e.preventDefault(); setDragging(false);
    const uploaded = Array.from(e.dataTransfer.files).filter(f => f.type === "application/pdf" || f.name.toLowerCase().endsWith(".zip") || f.name.toLowerCase().endsWith(".txt") || f.type.startsWith("image/"));
    setFiles(prev => [...prev, ...uploaded]);
  };

  const loadDismissedRecs = async (sid) => {
    if (!sid) return;
    try {
      const r = await fetch(`${API_BASE}/api/audit/dismissed/${sid}`, { credentials: "include" });
      const d = r.ok ? await r.json() : null;
      if (!d?.success) return;
      const next = new Map();
      for (const rec of (d.dismissed_recommendations || [])) {
        // "No reason provided" is the sentinel sent for a plain dismiss (no typed
        // reason). The backend credits the score only when a real reason was given,
        // so treat the sentinel as empty and suppress the +pts badge in that case -
        // keeping this consistent with the optimistic local update on dismiss.
        const hasReason = rec.override_reason && rec.override_reason !== "No reason provided";
        next.set(rec.rec_id, {
          message: rec.message,
          reason:  hasReason ? rec.override_reason : "",
          formId:  rec.form_id,
          impact:  hasReason ? rec.score_impact : 0,
        });
      }
      setDismissedRecs(new Set(next.keys()));
      setDismissedRecDetails(next);
    } catch { /* non-fatal */ }
  };

  // Load per-issue resolution statuses for the session's issue rail.
  const loadIssueStatuses = async (sid) => {
    if (!sid) return;
    try {
      const r = await fetch(`${API_BASE}/api/issues/status/${sid}`, { credentials: "include" });
      const d = r.ok ? await r.json() : null;
      if (!d?.success) return;
      const next = new Map();
      for (const s of (d.issue_statuses || [])) next.set(s.issue_id, { status: s.status, reason: s.reason });
      setIssueStatuses(next);
    } catch { /* non-fatal */ }
  };

  // Optimistically set an issue's status, then persist. On failure we keep the
  // optimistic value (non-fatal) - a reload re-syncs from the DB.
  const setIssueStatus = async (issueId, status, meta = {}) => {
    if (!issueId || !sessionId) return;
    setIssueStatuses(prev => { const n = new Map(prev); n.set(issueId, { status, reason: "" }); return n; });
    try {
      await fetch(`${API_BASE}/api/issues/status`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          issue_id: issueId,
          status,
          form_id:     meta.form_id     ?? null,
          field:       meta.field       ?? null,
          rule_code:   meta.rule_code   ?? null,
          source_fact: meta.source_fact ?? null,
          message:     meta.message     ?? null,
        }),
      });
    } catch { /* keep optimistic value; non-fatal */ }
  };

  // One compact status control for a grouped-issue cluster (banner hard-stops /
  // warnings). Cluster carries a durable issue_id from the backend.
  const clusterStatusControl = (c) => {
    const iid = c.issue_id || _fallbackIssueId(c.primary_message, c.forms);
    return (
      <IssueStatusControl
        issueId={iid}
        status={issueStatuses.get(iid)?.status}
        meta={{ form_id: Array.isArray(c.forms) ? c.forms[0] : null, rule_code: c.items?.[0]?.code, message: c.primary_message }}
        onSet={setIssueStatus}
      />
    );
  };

  useEffect(() => {
    if ((step !== "editor" && step !== "lite") || !sessionId) return;
    refreshArqData();
    loadDismissedRecs(sessionId);
    loadIssueStatuses(sessionId);
  }, [step, sessionId]); // eslint-disable-line

  const refreshArqData = async () => {
    if (!sessionId) return [];
    // Await the ARQ list so we can detect submitted sessions before deciding
    // whether to re-fetch session scores (§6.2 live score update requirement).
    let arqList = [];
    try {
      const arqR = await fetch(`${API_BASE}/api/arq/list/${sessionId}`, { credentials: "include" });
      const arqD = arqR.ok ? await arqR.json() : null;
      if (arqD?.success) { arqList = arqD.arq_sessions || []; setArqSessions(arqList); }
    } catch { /* non-fatal */ }
    fetch(`${API_BASE}/api/arq/notifications`, { credentials: "include" })
      .then(r => r.ok ? r.json() : null).then(d => { if (d?.notifications) setArqNotifCount(d.notifications.filter(n => !n.read_status).length); }).catch(() => {});
    // §6.2: if any ARQ was submitted, pull fresh SQS + package scores from the
    // session endpoint so the producer sees the updated scores without a reload.
    if (arqList.some(a => a.status === "submitted")) {
      try {
        const sessR = await fetch(`${API_BASE}/api/session/${sessionId}`, { credentials: "include" });
        const sessD = sessR.ok ? await sessR.json() : null;
        if (sessD?.generated_forms) {
          setGeneratedForms(prev => {
            const next = { ...prev };
            for (const [fid, fdata] of Object.entries(sessD.generated_forms)) {
              if (next[fid] && fdata.sqs) next[fid] = { ...next[fid], sqs: fdata.sqs };
            }
            return next;
          });
        }
        if (sessD?.package_sqs != null) setPackageSqs(sessD.package_sqs);
        if (Array.isArray(sessD?.cross_issues)) setCrossIssues(sessD.cross_issues);
      } catch { /* non-fatal */ }
    }
    try {
      const r = await fetch(`${API_BASE}/api/arq/client-filled/${sessionId}`, { credentials: "include" });
      const d = r.ok ? await r.json() : null;
      const fields = d?.client_filled_fields || [];
      setClientFilledFields(fields); return fields;
    } catch { return []; }
  };

  const handleOpenARQ = async () => {
    if (!sessionId) return;
    setArqLoadingQ(true);
    try {
      const res = await fetch(`${API_BASE}/api/arq/generate/${sessionId}`, { credentials: "include" });
      const data = await res.json();
      if (res.ok && data.success) { setArqQuestions(data.questions || []); setArqSummary(data.selection_summary || null); setShowARQModal(true); }
      else setError(data.detail || "Failed to generate questions.");
    } catch (e) { setError("Network error: " + e.message); }
    finally { setArqLoadingQ(false); }
  };

  const _resetSqsState = () => {
    setPackageSqs(null);
    setDismissedRecs(new Set()); setDismissedRecDetails(new Map()); setShowDownloadPreflight(false);
    setPreflightRecs([]); setPreflightHardBlock(false); setPreflightOverrideReason(""); setPreflightCallback(null);
    setSqsNarrative("");
  };

  const resetToUpload = () => {
    setFiles([]); setSessionId(null); setStep("upload"); setError(null);
    setDocSummary([]); setFlags({}); setHardStops([]); setSoftStops([]); setGroupedIssues(null);
    setCanProceedWithWarning(false); setWarningStops([]);
    setTier2Score(null); setTier2Missing([]); setRecommendations([]); setAccountProfile(null);
    setAllAvailableForms([]); setCheckedFormIds(new Set());
    setGeneratedForms({}); setActiveFormId(null); setCrossIssues([]); setIssueStatuses(new Map());
    setPdfLoading({}); setEpicLoading(false); setEpicSuccess(false);
    setSignedForms(new Set()); setShowUploadOverlay(false); setShowGenerateOverlay(false); setShowDownloadOverlay(false);
    setArqQuestions([]); setArqSessions([]); setClientFilledFields([]); setArqNotifCount(0);
    _resetSqsState();
  };

  const goToDashboard = () => {
    setFiles([]); setSessionId(null); setStep("dashboard"); setError(null);
    setDocSummary([]); setFlags({}); setHardStops([]); setSoftStops([]); setGroupedIssues(null);
    setTier2Score(null); setTier2Missing([]); setRecommendations([]); setAccountProfile(null);
    setAllAvailableForms([]); setCheckedFormIds(new Set());
    setGeneratedForms({}); setActiveFormId(null); setCrossIssues([]); setIssueStatuses(new Map());
    setPdfLoading({}); setEpicLoading(false); setEpicSuccess(false);
    setSignedForms(new Set()); setShowUploadOverlay(false); setShowGenerateOverlay(false); setShowDownloadOverlay(false);
    setArqQuestions([]); setArqSessions([]); setClientFilledFields([]); setArqNotifCount(0);
    _resetSqsState();
  };

  useImperativeHandle(ref, () => ({ goToDashboard }));

  const handleResumeSession = sid => {
    setLoading(true); setProcessingStage("Restoring session…"); setSessionId(sid);
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 20000);
    fetch(`${API_BASE}/api/session/${sid}`, { credentials: "include", signal: ctrl.signal })
      .then(r => r.ok ? r.json() : null)
      .then(async data => {
        const isEssentials = user?.subscription_tier === "essentials";
        if (!isEssentials && data && data.generated_forms && Object.keys(data.generated_forms).length > 0) {
          setGeneratedForms(data.generated_forms); setCrossIssues(data.cross_issues || []);
          if (data.package_sqs) setPackageSqs(data.package_sqs);
          const firstId = Object.keys(data.generated_forms)[0]; setActiveFormId(firstId);
          const readyMap = {}; Object.keys(data.generated_forms).forEach(fid => { readyMap[fid] = false; });
          setPdfLoading(readyMap); setStep("editor");
        } else if (isEssentials && data?.session_id) {
          setSessionId(sid); setStep("lite");
        } else if (!isEssentials && data && data.generation_job_id) {
          // Reopened mid-generation (forms not persisted yet): resume the same
          // progress overlay with the remaining time and poll until the server
          // finishes (Fig 8). Fall back to the recommendations restore if the
          // run already failed while we were away.
          const done = await _resumeGeneration(sid, data);
          if (!done) {
            const ok = await _restoreFromExtraction(sid, ctrl.signal);
            if (!ok) { setStep("upload"); setSessionId(null); }
          }
        } else if (!isEssentials && data) {
          // In-progress submission (no forms yet) → land on the integrity review
          // or the recommendations/SQS step rather than dropping to upload.
          const ok = await _restoreFromExtraction(sid, ctrl.signal);
          if (!ok) { setStep("upload"); setSessionId(null); }
        } else { setStep("upload"); setSessionId(null); }
      })
      .catch(() => { setError("Could not load session. Please try again."); setStep("upload"); setSessionId(null); })
      .finally(() => { clearTimeout(timer); setLoading(false); setProcessingStage(""); });
  };

  const handleSendToEpic = async formId => {
    if (!formId || !sessionId) return;
    setEpicLoading(true); setEpicSuccess(false);
    try {
      const res = await fetch(`${API_BASE}/api/send-to-epic/${sessionId}/${formId}`, { credentials: "include" });
      const data = await res.json();
      if (res.ok && data.success) { setEpicSuccess(true); setTimeout(() => setEpicSuccess(false), 3500); }
      else setError(data.detail || "Failed to send to EPIC.");
    } catch (e) { setError("EPIC send failed: " + e.message); }
    finally { setEpicLoading(false); }
  };

  const triggerEnterprisePopup = (buttonEl) => {
    const rect = buttonEl.getBoundingClientRect();
    const popupWidth = 210;
    const spaceRight = window.innerWidth - rect.right - 12;
    const left = spaceRight >= popupWidth
      ? rect.right + 12
      : Math.max(8, rect.left - popupWidth - 4);
    const top = Math.min(rect.top, window.innerHeight - 110);
    setEnterprisePopupPos({ top, left });
    setShowEnterprisePopup(true);
  };

  const handleSendToVertafore = async formId => {
    if (!formId || !sessionId) return;
    setVertaforeLoading(true); setVertaforeSuccess(false);
    try {
      const res = await fetch(`${API_BASE}/api/send-to-vertafore/${sessionId}/${formId}`, { credentials: "include" });
      const data = await res.json();
      if (res.ok && data.success) { setVertaforeSuccess(true); setTimeout(() => setVertaforeSuccess(false), 3500); }
      else setError(data.detail || "Failed to send to Vertafore.");
    } catch (e) { setError("Vertafore send failed: " + e.message); }
    finally { setVertaforeLoading(false); }
  };

  const _doDownloadOneNoSummary = async (formId, draftOpts = {}) => {
    setLoading(true); setShowDownloadOverlay(true);
    try {
      const qs = draftOpts.draft
        ? `?include_cover=false&draft=true&override_reason=${encodeURIComponent(draftOpts.overrideReason || "")}`
        : `?include_cover=false`;
      const res = await fetch(`${API_BASE}/api/download-pdf/${sessionId}/${formId}${qs}`, { credentials: "include" });
      if (res.status === 403) { const d = await res.json().catch(() => ({})); if (d.payment_locked) { setError("Account payment overdue."); return; } if (d.upgrade_required) { onShowUpgrade(); return; } setError(d.message || "Download blocked"); return; }
      if (res.status === 409) { const d = await res.json().catch(() => ({})); setError(d.detail?.message || "This package has unresolved required fields. Please review and try again."); return; }
      if (!res.ok) { const d = await res.json().catch(() => ({})); setError(d.detail?.message || d.message || "Download failed"); return; }
      const isDraft = res.headers.get("X-Download-Draft") === "true";
      const pkgStatus = res.headers.get("X-Package-Status") || ""; const pkgMsg = res.headers.get("X-Package-Message") || "";
      const blob = await res.blob(); const url = URL.createObjectURL(blob);
      const a = document.createElement("a"); a.href = url; a.download = isDraft ? `${formId}_Package_DRAFT.zip` : `${formId}_Package.zip`;
      document.body.appendChild(a); a.click(); document.body.removeChild(a); URL.revokeObjectURL(url);
      await refreshUser();
      if (pkgStatus) { setPkgStatusMsg(pkgMsg); setPkgStatusType(pkgStatus); setTimeout(() => setPkgStatusMsg(""), 12000); }
      setStep("success");
    } catch (err) { setError("Download failed: " + err.message); }
    finally { setLoading(false); setShowDownloadOverlay(false); }
  };

  const handleDownloadOneNoSummary = formId => gatedDownload(() => _runPreflightThenDownload(draftOpts => _doDownloadOneNoSummary(formId, draftOpts)));

  const gatedDownload = action => {
    if (user?.acord_license_confirmed) { action(); return; }
    setAcordLicenseChecked(false); setAcordModalAction(() => action); setShowAcordModal(true);
  };

  const handleAcordConfirm = async () => {
    if (!acordLicenseChecked) return;
    setAcordModalLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/acord/confirm-license`, { method: "POST", credentials: "include" });
      if (res.ok) { onUserUpdate({ ...user, acord_license_confirmed: true }); setShowAcordModal(false); if (acordModalAction) acordModalAction(); }
      else setError("License confirmation failed. Please try again.");
    } catch { setError("Network error during license confirmation."); }
    finally { setAcordModalLoading(false); }
  };

  const _doDownloadOne = async (formId, draftOpts = {}) => {
    setLoading(true); setShowDownloadOverlay(true);
    try {
      const qs = draftOpts.draft
        ? `?draft=true&override_reason=${encodeURIComponent(draftOpts.overrideReason || "")}`
        : "";
      const res = await fetch(`${API_BASE}/api/download-pdf/${sessionId}/${formId}${qs}`, { credentials: "include" });
      if (res.status === 403) { const d = await res.json().catch(() => ({})); if (d.payment_locked) { setError("Account payment overdue."); return; } if (d.upgrade_required) { onShowUpgrade(); return; } setError(d.message || "Download blocked"); return; }
      if (res.status === 409) { const d = await res.json().catch(() => ({})); setError(d.detail?.message || "This package has unresolved required fields. Please review and try again."); return; }
      if (!res.ok) { const d = await res.json().catch(() => ({})); setError(d.detail?.message || d.message || "Download failed"); return; }
      const isDraft = res.headers.get("X-Download-Draft") === "true";
      const pkgStatus = res.headers.get("X-Package-Status") || ""; const pkgMsg = res.headers.get("X-Package-Message") || "";
      const blob = await res.blob(); const url = URL.createObjectURL(blob);
      const a = document.createElement("a"); a.href = url; a.download = isDraft ? `${formId}_Package_DRAFT.zip` : `${formId}_Package.zip`;
      document.body.appendChild(a); a.click(); document.body.removeChild(a); URL.revokeObjectURL(url);
      await refreshUser();
      if (pkgStatus) { setPkgStatusMsg(pkgMsg); setPkgStatusType(pkgStatus); setTimeout(() => setPkgStatusMsg(""), 12000); }
      setStep("success");
    } catch (err) { setError("Download failed: " + err.message); }
    finally { setLoading(false); setShowDownloadOverlay(false); }
  };

  const _doDownloadAll = async (draftOpts = {}) => {
    setLoading(true); setShowDownloadOverlay(true);
    try {
      const qs = draftOpts.draft
        ? `?draft=true&override_reason=${encodeURIComponent(draftOpts.overrideReason || "")}`
        : "";
      const res = await fetch(`${API_BASE}/api/download-all/${sessionId}${qs}`, { credentials: "include" });
      if (res.status === 403) { const d = await res.json().catch(() => ({})); if (d.payment_locked) { setError("Account payment overdue."); return; } if (d.upgrade_required) { onShowUpgrade(); return; } setError(d.message || "Download blocked"); return; }
      if (res.status === 409) { const d = await res.json().catch(() => ({})); setError(d.detail?.message || "This package has unresolved required fields. Please review and try again."); return; }
      if (!res.ok) { const d = await res.json().catch(() => ({})); setError(d.detail?.message || d.message || "Download failed"); return; }
      const isDraft = res.headers.get("X-Download-Draft") === "true";
      const pkgStatus = res.headers.get("X-Package-Status") || ""; const pkgMsg = res.headers.get("X-Package-Message") || "";
      const blob = await res.blob(); const url = URL.createObjectURL(blob);
      const a = document.createElement("a"); a.href = url; a.download = isDraft ? "ACORD_Package_Primble_DRAFT.zip" : "ACORD_Package_Primble.zip";
      document.body.appendChild(a); a.click(); document.body.removeChild(a); URL.revokeObjectURL(url);
      await refreshUser();
      if (pkgStatus) { setPkgStatusMsg(pkgMsg); setPkgStatusType(pkgStatus); setTimeout(() => setPkgStatusMsg(""), 12000); }
      setStep("success");
    } catch (err) { setError("Download failed: " + err.message); }
    finally { setLoading(false); setShowDownloadOverlay(false); }
  };

  const refreshUser = async () => {
    const res = await fetch(`${API_BASE}/api/auth/me`, { credentials: "include" });
    if (res.ok) { const data = await res.json(); onUserUpdate(data); }
  };

  // ── Walk-away workflow helpers ────────────────────────────────────────────
  // Persist active job so we can resume polling after a page reload, and notify
  // the user (browser notification + tab-title badge) when the job completes
  // while the tab is hidden.
  const _ACTIVE_JOB_KEY = "primble_active_job";
  const _persistActiveJob = (jobId, kind) => {
    try { localStorage.setItem(_ACTIVE_JOB_KEY, JSON.stringify({ jobId, kind, ts: Date.now() })); } catch {}
  };
  const _clearActiveJob = () => {
    try { localStorage.removeItem(_ACTIVE_JOB_KEY); } catch {}
  };
  // Permission is prompted lazily on first user gesture (upload/generate).
  // SW registration is bootstrapped globally in main.jsx via window.__primbleSwReady,
  // so this helper only handles the Notification permission prompt.
  const _notifPermissionAsked = useRef(false);
  const _permissionWarnedThisSession = useRef(false);
  // Tracks whether the tab was hidden at ANY point between the moment a job
  // started and the moment it finished. Without this, _notifyJobDone would only
  // fire an OS notification if `document.hidden` is true at the exact tick the
  // job completes - but users often glance back at the tab to check progress
  // (or switch back just as the job finishes), so the "hidden right now" check
  // misses the common case. Reset to false on every job start.
  const _wasHiddenDuringJob = useRef(false);
  const _markJobStart = () => {
    _wasHiddenDuringJob.current = (typeof document !== "undefined" && document.hidden) || false;
  };
  const _requestNotificationPermission = async () => {
    if (_notifPermissionAsked.current) return;
    _notifPermissionAsked.current = true;
    try {
      if (typeof Notification === "undefined") {
        console.info("[primble-notify] Notification API unavailable");
        return;
      }
      if (Notification.permission === "default") {
        // Must be awaited so the first _notifyJobDone after this resolves with
        // the real permission state instead of racing the OS prompt.
        const result = await Notification.requestPermission().catch(() => "default");
        console.info("[primble-notify] permission ->", result);
      }
      // If permission still isn't granted, show ONE diagnostic toast so the
      // user understands why OS-level alerts in background tabs aren't firing.
      // This is the single most common production-only failure mode: per-origin
      // permission didn't carry over from localhost, and Chrome's "quieter UI"
      // bell icon is easy to miss / dismiss.
      if (Notification.permission !== "granted" && !_permissionWarnedThisSession.current) {
        _permissionWarnedThisSession.current = true;
        _pushJobToast(
          "Background alerts are off",
          "Click the lock or bell icon in your browser's address bar to allow notifications, then reload.",
          false
        );
      }
    } catch (err) {
      console.warn("[primble-notify] permission request threw:", err && err.message ? err.message : err);
    }
  };

  // Resolve a working SW registration, with three fallbacks:
  //   1. The global bootstrap promise from main.jsx (normal path).
  //   2. navigator.serviceWorker.getRegistration("/") (root scope lookup).
  //   3. Just-in-time register() (covers the case where the global bootstrap
  //      hadn't run yet, e.g. instant resume-after-reload).
  // Returns null only when all three fail; in that case the caller must NOT
  // call new Notification(...) on Chromium because it silently no-ops in
  // background tabs. Returning null is honest about "we cannot notify".
  const _resolveSwRegistration = async () => {
    if (!("serviceWorker" in navigator)) return null;
    try {
      if (window.__primbleSwReady) {
        const reg = await window.__primbleSwReady;
        if (reg && typeof reg.showNotification === "function") return reg;
      }
    } catch (err) {
      console.warn("[primble-notify] __primbleSwReady failed:", err && err.message ? err.message : err);
    }
    try {
      const existing = await navigator.serviceWorker.getRegistration("/");
      if (existing && typeof existing.showNotification === "function") return existing;
    } catch (err) {
      console.warn("[primble-notify] getRegistration failed:", err && err.message ? err.message : err);
    }
    try {
      const reg = await navigator.serviceWorker.register("/notification-sw.js", { scope: "/" });
      await navigator.serviceWorker.ready;
      if (reg && typeof reg.showNotification === "function") return reg;
    } catch (err) {
      console.error("[primble-notify] just-in-time register failed:", err && err.message ? err.message : err);
    }
    return null;
  };
  const _setTitleBadge = (on) => {
    try {
      const base = document.title.replace(/^\(\d+\)\s*/, "");
      document.title = on ? `(1) ${base}` : base;
    } catch {}
  };
  const _pushJobToast = (title, body, ok) => {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
    setJobToasts(prev => [...prev, { id, title, body, ok }]);
  };
  const _notifyJobDone = async (kind, ok, statusOverride = null) => {
    // Workstream 6 §9.1 - never announce a bare "Ready". When the caller knows the
    // live package state it passes a precise {title, body} via statusOverride;
    // otherwise fall back to a neutral, state-appropriate default (the background
    // job-restore poll has no issue counts to work with).
    let title, body;
    if (!ok) {
      title = "Primble - Action needed";
      body = "There was an issue with your submission. Please reopen to review.";
    } else if (statusOverride && statusOverride.title) {
      title = statusOverride.title;
      body = statusOverride.body || "";
    } else if (kind === "generate") {
      title = "Primble - Forms Generated";
      body = "Your ACORD forms are ready for review.";
    } else {
      title = "Primble - Documents Processed";
      body = "Processing complete.";
    }
    console.info("[primble-notify] _notifyJobDone fired", {
      kind, ok,
      hidden: typeof document !== "undefined" ? document.hidden : "n/a",
      wasAwayDuringJob: _wasHiddenDuringJob.current,
      permission: typeof Notification !== "undefined" ? Notification.permission : "n/a",
    });
    // Always show in-page toast (every event, regardless of tab state).
    _pushJobToast(title, body, ok);
    // Title-badge runs even if the OS path fails, so a hidden tab still gets
    // a visible "(1) Primble - …" hint when the user returns.
    if (typeof document !== "undefined" && document.hidden) _setTitleBadge(true);
    // Reset the "was away" flag for the next job. We no longer gate the OS
    // notification on it: trying to predict whether the user "needs" an alert
    // based on visibility timing kept missing edge cases (tabbing back briefly,
    // job finishing during the glance, OS race conditions). Slack/Gmail/Discord
    // all fire OS notifications unconditionally on job completion - the in-page
    // toast is the foreground signal, the OS banner is the away signal, and
    // showing both when the user is on the page is harmless redundancy.
    _wasHiddenDuringJob.current = false;
    if (typeof Notification === "undefined") {
      console.info("[primble-notify] skip: Notification API unavailable");
      return;
    }
    if (Notification.permission !== "granted") {
      console.info("[primble-notify] skip: permission=", Notification.permission);
      return;
    }
    const tag = `primble-${kind}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
    const reg = await _resolveSwRegistration();
    if (!reg) {
      console.error("[primble-notify] no SW registration available, OS notification skipped");
      return;
    }
    // Stripped-down primary path: many browsers (Brave, Edge with enterprise
    // policy, Chrome under strict privacy) silently drop notifications when the
    // icon URL 404s or when certain optional flags are set. The spec only
    // requires `title`; `body` and `tag` are safe extras. Everything else
    // (icon/badge/requireInteraction/silent/actions) is optional and has been
    // observed to cause silent suppression in the field. We rely on the SW
    // registration path (NOT `new Notification()`) because Chromium silently
    // no-ops the constructor path in backgrounded tabs.
    try {
      await reg.showNotification(title, { body, tag });
      console.info("[primble-notify] showNotification ok, tag=", tag);
      return;
    } catch (err) {
      console.warn("[primble-notify] showNotification rejected, trying SW postMessage:", err && err.message ? err.message : err);
    }
    // Fallback: ask the SW to display from its own context via postMessage.
    // event.waitUntil() inside the SW keeps it alive long enough to show the
    // notification even if the page-side call path hit a quirk.
    try {
      const target = reg.active || reg.waiting || reg.installing;
      if (target && target.postMessage) {
        target.postMessage({ type: "SHOW_NOTIFICATION", title, body, tag });
        console.info("[primble-notify] postMessage to SW ok (fallback), tag=", tag);
      } else {
        console.error("[primble-notify] no SW worker target available for postMessage fallback");
      }
    } catch (err) {
      console.error("[primble-notify] postMessage to SW failed:", err && err.message ? err.message : err);
    }
  };

  // Diagnostic helper exposed on window so you can verify OS-level
  // notification delivery independently of the upload/generate flow.
  // Usage from DevTools console:
  //     window.__primbleTestNotification(5)
  // Fires a notification 5 seconds later - switch tabs/apps in that window
  // and observe whether the OS banner appears. If this does NOT appear when
  // the tab is hidden, the issue is OS-level (Focus/DND mode, Chrome quieter
  // messaging, Brave shields) - NOT a bug in Primble's notification code.
  useEffect(() => {
    window.__primbleTestNotification = async (delaySec = 3) => {
      const ms = Math.max(0, Number(delaySec) * 1000);
      console.info("[primble-notify] TEST scheduled in", ms, "ms - switch tabs now");
      console.info("[primble-notify] TEST state at schedule:", {
        hidden: typeof document !== "undefined" ? document.hidden : "n/a",
        permission: typeof Notification !== "undefined" ? Notification.permission : "n/a",
        hasSW: "serviceWorker" in navigator,
      });
      await new Promise(r => setTimeout(r, ms));
      console.info("[primble-notify] TEST firing now - hidden=", document.hidden);
      if (typeof Notification === "undefined" || Notification.permission !== "granted") {
        console.error("[primble-notify] TEST aborted: no permission");
        return;
      }
      const reg = await _resolveSwRegistration();
      if (!reg) {
        console.error("[primble-notify] TEST aborted: no SW registration");
        return;
      }
      const tag = `primble-test-${Date.now()}`;
      try {
        await reg.showNotification("Primble - Test", { body: "If you see this banner, OS-level notifications work.", tag });
        console.info("[primble-notify] TEST showNotification resolved. If no banner appeared, the OS/browser is suppressing it.");
      } catch (err) {
        console.error("[primble-notify] TEST showNotification rejected:", err && err.message ? err.message : err);
      }
    };
    return () => { try { delete window.__primbleTestNotification; } catch {} };
  }, []);

  // Clear the title badge when the user returns to the tab, and track every
  // hide event so _notifyJobDone knows whether the user tabbed away during the
  // job (even if they happen to be on the Primble tab at the exact instant the
  // job completes).
  useEffect(() => {
    const onVis = () => {
      if (document.hidden) {
        _wasHiddenDuringJob.current = true;
      } else {
        _setTitleBadge(false);
      }
    };
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, []);

  // Poll /api/jobs/{jobId}/status until completed or failed. Throws on failure or timeout.
  // iOS Safari aggressively drops fetch when the tab backgrounds or the
  // cellular link blips. Treat transient network/5xx errors as "skip this
  // tick" rather than aborting the whole flow - the backend job is still
  // running. Only definitive errors (401/403/404, job=failed) terminate.
  const _pollJobStatus = async (jobId, maxAttempts = 100, interval = 3000) => {
    let consecutiveErrors = 0;
    const MAX_CONSECUTIVE_ERRORS = 8;  // ~24s of network blips tolerated
    for (let i = 0; i < maxAttempts; i++) {
      await new Promise(r => setTimeout(r, interval));
      let res;
      try {
        res = await fetch(`${API_BASE}/api/jobs/${jobId}/status`, { credentials: "include" });
      } catch (e) {
        consecutiveErrors++;
        if (consecutiveErrors >= MAX_CONSECUTIVE_ERRORS) throw e;
        continue;
      }
      if (res.status === 401 || res.status === 403) throw new Error("Session expired during processing. Please sign in again.");
      if (res.status === 404) throw new Error("Job not found");
      if (!res.ok) {
        consecutiveErrors++;
        if (consecutiveErrors >= MAX_CONSECUTIVE_ERRORS) throw new Error(`Job poll failed: ${res.status}`);
        continue;
      }
      consecutiveErrors = 0;
      const job = await res.json();
      if (job.status === "completed") return job;
      if (job.status === "failed") throw new Error(job.error || "Processing failed on the server");
    }
    throw new Error("Processing timed out. Please try again.");
  };

  // Fig 8: reopened a session whose forms are still generating on the server.
  // Show the same progress overlay with the REMAINING time (recomputed from the
  // server's start timestamp), poll the job to completion, then load the forms.
  // Returns true when the editor was reached; false → caller restores the
  // recommendations screen (e.g. the run failed while we were away).
  // Constants mirror the generation-overlay estimate below; files are unknown on
  // resume so the forms-only fallback the overlay already documents is used.
  const _GEN_FILL_BASE = 20;
  const _GEN_FILL_PER_FORM = 65;
  const _resumeGeneration = async (sid, data) => {
    const formCount = Math.max(1, Number(data.generation_form_count) || 1);
    const startedAt = Number(data.generation_started_at) || 0;  // epoch seconds
    const totalEta  = _GEN_FILL_BASE + formCount * _GEN_FILL_PER_FORM;
    const elapsed   = startedAt ? Math.max(0, (Date.now() / 1000) - startedAt) : 0;
    setResumeGenEta(Math.max(30, Math.round(totalEta - elapsed)));
    setShowGenerateOverlay(true);
    try {
      if (data.generation_job_id) await _pollJobStatus(data.generation_job_id);
      const r = await fetch(`${API_BASE}/api/session/${sid}`, { credentials: "include" });
      const d = r.ok ? await r.json() : null;
      if (d && d.generated_forms && Object.keys(d.generated_forms).length > 0) {
        setGeneratedForms(d.generated_forms); setCrossIssues(d.cross_issues || []);
        if (d.package_sqs) setPackageSqs(d.package_sqs);
        const firstId = Object.keys(d.generated_forms)[0]; setActiveFormId(firstId);
        const readyMap = {}; Object.keys(d.generated_forms).forEach(fid => { readyMap[fid] = false; });
        setPdfLoading(readyMap); setStep("editor");
        return true;
      }
      return false;
    } catch {
      return false;
    } finally {
      setShowGenerateOverlay(false); setResumeGenEta(null);
    }
  };

  // Resume polling for an active job left in localStorage after a page reload.
  // Silent: doesn't show overlays - when the job finishes we notify via browser
  // notification + tab-title badge so the user knows to come back.
  useEffect(() => {
    let cancelled = false;
    try {
      const raw = localStorage.getItem(_ACTIVE_JOB_KEY);
      if (!raw) return;
      const { jobId, kind, ts } = JSON.parse(raw) || {};
      if (!jobId) { _clearActiveJob(); return; }
      // Drop stale entries (>30 min old) - covers crashed/timed-out jobs
      if (ts && (Date.now() - ts) > 30 * 60 * 1000) { _clearActiveJob(); return; }
      (async () => {
        try {
          await _pollJobStatus(jobId);
          if (cancelled) return;
          _notifyJobDone(kind || "upload", true);
        } catch {
          if (cancelled) return;
          _notifyJobDone(kind || "upload", false);
        } finally {
          if (!cancelled) _clearActiveJob();
        }
      })();
    } catch {}
    return () => { cancelled = true; };
  }, []); // eslint-disable-line

  const handleUpload = async () => {
    if (!files.length) { setError("Select at least one file"); return; }
    await _requestNotificationPermission();
    _markJobStart();
    // Figure 1: a client-generated token keys the live progress side-channel. The
    // backend writes each file's phase under it; the overlay polls it. Persisted in
    // localStorage so a mid-upload tab refresh OR close-and-reopen can re-attach to
    // the in-flight run (see resume effect). Cleared once the upload settles below.
    const _progressToken = (crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`);
    try { localStorage.setItem("primble_upload_token", _progressToken); } catch { /* private mode */ }
    setUploadProgressToken(_progressToken);
    setLoading(true); setError(null); setShowUploadOverlay(true);
    const fd = new FormData(); files.forEach(f => fd.append("files", f));
    fd.append("progress_token", _progressToken);
    try {
      const res = await fetch(`${API_BASE}/api/upload-declaration`, { method: "POST", credentials: "include", body: fd });
      if (res.status === 401) { setError("Session expired. Please sign in again."); setTimeout(() => { try { localStorage.removeItem("acordly_tk"); sessionStorage.removeItem("acordly_tk"); } catch {} window.location.reload(); }, 2000); return; }
      if (res.status === 403) { const d = await res.json().catch(() => ({})); if (d.upgrade_required) { onShowUpgrade(); return; } const msg = d.detail || d.message || "Access blocked."; if (msg.includes("suspended")) setError("Your account is suspended."); else if (msg.includes("archived")) setError("Account archived. Contact support."); else if (msg.includes("soft_locked") || msg.includes("locked")) setError("Account Disabled - please update billing."); else setError(msg); return; }
      if (res.status === 429) { setError("Server busy - too many concurrent uploads. Please wait 30 seconds and try again."); return; }
      if (res.status >= 500) { setError("Server error during upload. Please try again. If this persists, the file may be too large or complex."); return; }
      let data;
      if (res.status === 202) {
        const queued = await res.json();
        _persistActiveJob(queued.job_id, "upload");
        let job;
        try { job = await _pollJobStatus(queued.job_id); }
        finally { _clearActiveJob(); }
        _notifyJobDone("upload", true);
        const sid = job.result?.session_id || queued.session_id;
        const extRes = await fetch(`${API_BASE}/api/session/${sid}/extraction-result`, { credentials: "include" });
        if (!extRes.ok) { setError("Upload processing failed. Please try again."); return; }
        data = await extRes.json();
      } else {
        data = await res.json();
      }
      if (!data.success) {
        // tier1_fail is no longer returned - backend now surfaces missing
        // ACORD 125 fields as soft warnings on the recommendations / lite SQS
        // screens. Keep a tolerant fallback in case an old backend responds.
        if (data.gate === "tier1_fail") {
          setSoftStops((data.missing_fields || []).map(m => `ACORD 125 minimum field missing: ${m}`));
          setHardStops([]);
          setRecommendations(data.recommendations || []);
          setStep(user?.subscription_tier === "essentials" ? "lite" : "recommendations");
          return;
        }
        setError(data.message || "Upload failed");
        return;
      }
      _notifyJobDone("upload", true, packageStatusNotice({
        integrityReviewRequired: !!data.integrity_review_required,
        hardStopCount: (data.hard_stops || []).length,
        warningCount: (data.soft_stops || []).length,
      }));
      setSessionId(data.session_id); setDocSummary(data.doc_summary || []); setFlags(data.flags || {});
      setAvailableDocTypes(data.available_doc_types || []);
      setHardStops(data.hard_stops || []); setSoftStops(data.soft_stops || []); setNormalizedDiffs(data.normalized_differences || []);
      setGroupedIssues(data.grouped_issues || null);
      setCanProceedWithWarning(!!data.can_proceed_with_warning);
      setWarningStops(data.warning_stops || []);
      setTier2Score(data.tier2_score ?? null); setTier2Missing(data.tier2_missing || []);
      setRecommendations(data.recommendations || []); setAllAvailableForms(data.all_available_forms || []);
      setAccountProfile(data.account_profile || null);
      setCheckedFormIds(new Set());
      setUnderwriting(data.underwriting_consistency || null); setUnderwritingPicks({});
      // Submission Integrity Validation (Beta Report §4.1): pause for review
      // BEFORE form selection/generation when the package may hold multiple insureds.
      setIntegrity(data.integrity || null);
      if (data.integrity_review_required) {
        setRemoveDocIds(new Set());
        setStep("integrity_review");
        return;
      }
      setStep(user?.subscription_tier === "essentials" ? "lite" : "recommendations");
    } catch (e) {
      if (e.message === "Failed to fetch" || e.name === "TypeError") {
        setError("Upload failed: could not reach the server. Check your connection, or the file may be too large. Please try again.");
      } else {
        setError("Upload failed: " + e.message);
      }
    }
    finally {
      setLoading(false); setShowUploadOverlay(false);
      // Upload settled (success or failure) → tear down the progress channel.
      setUploadProgressToken(null);
      try { localStorage.removeItem("primble_upload_token"); } catch { /* private mode */ }
    }
  };

  // Submission Integrity Validation (Beta Report §4.1) - resolve a pending review.
  // action: "remove_documents" (drop selected docs, re-assess) | "continue_anyway".
  const handleResolveIntegrity = async (action) => {
    if (!sessionId) return;
    if (action === "remove_documents" && removeDocIds.size === 0) {
      setError("Select at least one document to remove."); return;
    }
    setIntegrityBusy(true); setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/submission-integrity/resolve`, {
        method: "POST", credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          action,
          remove_doc_ids: action === "remove_documents" ? Array.from(removeDocIds) : [],
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.success) {
        setError(data.detail || data.message || "Could not resolve the submission integrity review.");
        return;
      }
      setIntegrity(data.integrity || null);
      setHardStops(data.hard_stops || []); setSoftStops(data.soft_stops || []); setNormalizedDiffs(data.normalized_differences || []);
      setGroupedIssues(data.grouped_issues || null);
      setCanProceedWithWarning(!!data.can_proceed_with_warning);
      setDocSummary(data.doc_summary || docSummary);
      if (data.available_doc_types) setAvailableDocTypes(data.available_doc_types);
      // Still flagged after removing documents → stay on the review step.
      if (data.integrity_review_required) {
        setRemoveDocIds(new Set());
        return;
      }
      setRecommendations(data.recommendations || []);
      setAllAvailableForms(data.all_available_forms || []);
      setAccountProfile(data.account_profile || null);
      setCheckedFormIds(new Set());
      setUnderwriting(data.underwriting_consistency || null);
      // Readiness number was withheld while the review was pending; restore it now
      // that the package is cleared so the bar shows on the recommendations screen.
      setTier2Score(data.tier2_score ?? null); setTier2Missing(data.tier2_missing || []);
      // Workstream 6 §9.1 - integrity resolved → announce the now-current status
      // (hard stops / warnings / ready) as the user lands on the recommendations
      // screen, so they immediately know what to do next. When the package was
      // split (§4.1 "Create separate submissions") tell the user how many
      // submissions were created and which one they're continuing with.
      const _created = data.created_submissions || [];
      const _resolveNotice =
        action === "create_separate_submissions" && _created.length > 1
          ? {
              title: "Primble - Submissions Split",
              body: `Created ${_created.length} separate submissions. Continuing with "${_created[0]?.label || "the first"}"; the others are saved to your submissions.`,
            }
          : packageStatusNotice({
              integrityReviewRequired: false,
              hardStopCount: (data.hard_stops || []).length,
              warningCount: (data.soft_stops || []).length,
            });
      _notifyJobDone("upload", true, _resolveNotice);
      setStep(user?.subscription_tier === "essentials" ? "lite" : "recommendations");
    } catch (e) {
      setError("Could not resolve the submission integrity review: " + (e?.message || "network error"));
    } finally {
      setIntegrityBusy(false);
    }
  };

  // Document classification correction (Beta Report §4.2). action:
  // "set_type" (with newType) | "exclude" | "include". Re-runs scoring server-side.
  const handleReclassify = async (docId, action, newType = null, busyBtn = null) => {
    if (!sessionId || !docId) return;
    setReclassDocId(docId); setReclassBusyBtn(busyBtn); setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/document/reclassify`, {
        method: "POST", credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, doc_id: docId, action, new_doc_type: newType }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.success) {
        setError(data.detail || data.message || "Could not update the document type.");
        return;
      }
      // Corrected classification re-runs downstream scoring + recommendations.
      setDocSummary(data.doc_summary || docSummary);
      if (data.available_doc_types) setAvailableDocTypes(data.available_doc_types);
      setRecommendations(data.recommendations || []);
      if (data.account_profile) setAccountProfile(data.account_profile);
      setHardStops(data.hard_stops || []); setSoftStops(data.soft_stops || []); setNormalizedDiffs(data.normalized_differences || []);
      setGroupedIssues(data.grouped_issues || null);
      setCanProceedWithWarning(!!data.can_proceed_with_warning);
      setWarningStops(data.warning_stops || []);
      setFlags(data.flags || flags);
      // Refresh the live Submission Readiness score + missing items so the
      // corrected classification visibly updates downstream scoring (§4.2).
      if (data.tier2_score !== undefined) setTier2Score(data.tier2_score);
      if (data.tier2_missing) setTier2Missing(data.tier2_missing);
      // Recomputed Submission Readiness (SQS) returned by the reclassify call
      // (§4.2 item #5) — keep the package score in sync so it is never stale.
      if (data.package_sqs) setPackageSqs(data.package_sqs);
      if (data.integrity) setIntegrity(data.integrity);
      if (data.underwriting_consistency) setUnderwriting(data.underwriting_consistency);
    } catch (e) {
      setError("Could not update the document type: " + (e?.message || "network error"));
    } finally {
      setReclassDocId(null); setReclassBusyBtn(null);
    }
  };

  // "Why are you marketing this account?" answer (DOUBTS-Workstream4 / Brent).
  // Re-runs form recommendations live so ACORD 101 moves to its correct tier; the
  // answer also persists into the session so it flows into later SQS scoring.
  const handleMarketingReason = async (reason) => {
    if (!sessionId || !reason) return;
    setMarketingBusy(true); setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/session/${sessionId}/marketing-reason`, {
        method: "POST", credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.success) {
        setError(data.detail || data.message || "Could not update recommendations.");
        return;
      }
      setRecommendations(data.recommendations || recommendations);
      if (data.account_profile) setAccountProfile(data.account_profile);
      if (data.all_available_forms) setAllAvailableForms(data.all_available_forms);
      if (data.flags) setFlags(data.flags);
    } catch (e) {
      setError("Could not update recommendations: " + (e?.message || "network error"));
    } finally {
      setMarketingBusy(false);
    }
  };

  // "Review extracted data" (Beta Report §4.2 item #6): fetch what Primble pulled
  // from a single document and show it in a read-only panel.
  const handleReviewData = async (docId) => {
    if (!sessionId || !docId) return;
    setReviewLoadingId(docId); setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/session/${sessionId}/document/${docId}/extracted-data`, { credentials: "include" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.success) {
        setError(data.detail || data.message || "Could not load the extracted data for this document.");
        return;
      }
      setReviewData(data);
    } catch (e) {
      setError("Could not load the extracted data: " + (e?.message || "network error"));
    } finally {
      setReviewLoadingId(null);
    }
  };

  // Submission Integrity status banner (Beta Report §4.1). Pink to match the
  // other sections. HIGH / MEDIUM are surfaced here on the recommendations/SQS
  // screen (they never pause); LOW pauses and is shown on the dedicated
  // "Submission Integrity Review Needed" screen instead. Informational only.
  const renderIntegrityStatus = () => {
    const st = integrity?.status;
    if (!st) return null;
    const rawReasons = integrity?.reasons || [];
    const entities = integrity?.detected_entities || [];

    // Dedup: drop any reason whose field is already an open conflict in Data
    // Consistency (shown there with source/confidence/suggestion/apply-to-all -
    // repeating it here as a bare sentence would be pure duplication).
    const openConsistencyFields = new Set(
      (underwriting?.fields || []).filter(f => f.status === "conflict").map(f => f.fact_key)
    );
    const reasons = rawReasons.filter(r => {
      const fk = INTEGRITY_REASON_TO_FACT_KEY[r];
      return !(fk && openConsistencyFields.has(fk));
    });

    const title = { high: "Documents verified", medium: "Review recommended", low: "Possible multiple submissions" }[st];
    if (!title) return null;
    const desc = st === "high"
      ? "The uploaded documents appear to belong to the same submission."
      : st === "low"
        ? "These documents may belong to different insureds. You can continue, or separate them into individual submissions."
        : "Some submission details differ across the uploaded documents. You can continue, but a quick review is recommended.";

    // Single severity model: LOW -> hard stop, MEDIUM -> warning, HIGH with
    // resolved formatting differences -> that label, HIGH with nothing at all
    // to note -> no label. A fully clean submission isn't "low risk" (Advisory),
    // it's no-risk - there is nothing left to advise about, so no chip renders.
    const severity = st === "low" ? "hard_stop"
      : st === "medium" ? "warning"
        : normalizedDiffs.length > 0 ? "resolved_formatting_difference"
          : null;

    return (
      <div style={{ marginBottom: 14, background: "rgba(230,27,132,0.07)", border: "1.5px solid rgba(230,27,132,0.25)", borderRadius: 12, padding: "14px 18px" }}>
        <div style={{ fontSize: 11, fontWeight: 700, color: "#9d0f5a", textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 4 }}>Submission integrity</div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <IntegritySeverityChip severity={severity} />
          <span style={{ fontWeight: 700, color: "#9d0f5a", fontSize: 13.5 }}>{title}</span>
        </div>
        <div style={{ fontSize: 12.5, color: "#b01868", lineHeight: 1.5, marginTop: 4 }}>{desc}</div>
        {entities.length > 0 && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 8 }}>
            {entities.map((e, i) => (
              <span key={i} style={{ background: "rgba(230,27,132,0.08)", color: "#9d0f5a", border: "1px solid rgba(230,27,132,0.22)", borderRadius: 999, padding: "3px 12px", fontSize: 12.5, fontWeight: 600 }}>{e}</span>
            ))}
          </div>
        )}
        {reasons.length > 0 && (
          <ul style={{ margin: "8px 0 0", paddingLeft: 18 }}>
            {reasons.map((r, i) => (
              <li key={i} style={{ fontSize: 12.5, color: "#b01868", padding: "1px 0" }}>{r}</li>
            ))}
          </ul>
        )}
        {normalizedDiffs.length > 0 && (
          <div style={{ marginTop: 10, paddingTop: 10, borderTop: "1px solid rgba(230,27,132,0.2)" }}>
            <div style={{ fontWeight: 700, fontSize: 12, color: "#1e293b", marginBottom: 4 }}>
              Resolved formatting difference
            </div>
            <div style={{ fontSize: 12, color: "#1e293b", marginBottom: 5 }}>
              These values appeared in different formats across your documents but refer to the same thing. No action needed.
            </div>
            {normalizedDiffs.map((s, i) => (
              <div key={i} style={{ fontSize: 12, color: "#1e293b", padding: "2px 0" }}>
                <span style={{ fontWeight: 600 }}>{s.split(":")[0]}:</span>
                <span>{s.includes(":") ? s.slice(s.indexOf(":") + 1) : ""}</span>
                <span style={{ fontStyle: "italic" }}> - treated as equivalent</span>
              </div>
            ))}
          </div>
        )}
      </div>
    );
  };

  // Core Underwriting Data Consistency (Beta Report §4.3): confirm the correct
  // Gross Sales (or similar) value when documents disagree. The server applies
  // it across every relevant form and re-runs scoring.
  const handleConfirmUnderwriting = async (factKey, value) => {
    if (!sessionId || !factKey) return;
    const v = (value ?? "").toString().trim();
    if (!v) { setError("Enter or select a value to confirm."); return; }
    setUnderwritingBusy(factKey); setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/underwriting/confirm-value`, {
        method: "POST", credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, fact_key: factKey, value: v }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.success) {
        setError(data.detail || data.message || "Could not confirm the value.");
        return;
      }
      setUnderwriting(data.underwriting_consistency || null);
      setRecommendations(data.recommendations || recommendations);
      if (data.account_profile) setAccountProfile(data.account_profile);
      setAllAvailableForms(data.all_available_forms || allAvailableForms);
      setHardStops(data.hard_stops || []); setSoftStops(data.soft_stops || []); setNormalizedDiffs(data.normalized_differences || []);
      setGroupedIssues(data.grouped_issues || null);
      setCanProceedWithWarning(!!data.can_proceed_with_warning);
      setWarningStops(data.warning_stops || []);
      setTier2Score(data.tier2_score ?? tier2Score); setTier2Missing(data.tier2_missing || tier2Missing);
      setFlags(data.flags || flags);
    } catch (e) {
      setError("Could not confirm the value: " + (e?.message || "network error"));
    } finally {
      setUnderwritingBusy(null);
    }
  };

  const handleGenerateAll = async () => {
    const ids = Array.from(checkedFormIds);
    if (!ids.length) { setError("Select at least one form"); return; }
    await _requestNotificationPermission();
    _markJobStart();
    setLoading(true); setError(null); setShowGenerateOverlay(true);
    try {
      const res = await fetch(`${API_BASE}/api/select-forms-bulk`, { method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session_id: sessionId, form_ids: ids }) });
      if (res.status === 403) {
        const d = await res.json().catch(() => ({}));
        const msg = d.detail || d.message || "";
        if (msg.toLowerCase().includes("lite")) { setStep("lite"); return; }
        setError(msg || "Access blocked. Please update your billing."); return;
      }
      // Submission Integrity gate (Beta Report §4.1): the server refuses to
      // generate forms while a multi-insured review is pending. Route the user
      // back to the review step rather than failing silently.
      if (res.status === 409) {
        const d = await res.json().catch(() => ({}));
        const detail = d.detail || {};
        if (detail.error === "submission_integrity_review_required" || detail.integrity) {
          setIntegrity(detail.integrity || null);
          setRemoveDocIds(new Set());
          setStep("integrity_review");
          return;
        }
        // Building-value review gate (client Property Integrity): the server
        // refuses to generate forms while building values conflict across
        // documents. Route back to the recommendations step where the Data
        // Consistency picker lets the broker confirm the correct value.
        if (detail.error === "building_value_review_required") {
          if (detail.underwriting_consistency) setUnderwriting(detail.underwriting_consistency);
          setUnderwritingPicks({});
          setStep("recommendations");
          setError(detail.message || "Building values differ across the submitted documents. Confirm the correct value before generating forms.");
          return;
        }
        setError(detail.message || "Submission cannot proceed. Please review your documents."); return;
      }
      let data;
      if (res.status === 202) {
        const queued = await res.json();
        _persistActiveJob(queued.job_id, "generate");
        try { await _pollJobStatus(queued.job_id); }
        finally { _clearActiveJob(); }
        _notifyJobDone("generate", true);
        const sessRes = await fetch(`${API_BASE}/api/session/${sessionId}`, { credentials: "include" });
        if (!sessRes.ok) { setError("Form generation failed. Please try again."); return; }
        const sessData = await sessRes.json();
        data = { success: true, generated: sessData.generated_forms, form_ids: Object.keys(sessData.generated_forms || {}), cross_issues: sessData.cross_issues, package_sqs: sessData.package_sqs || null };
      } else {
        data = await res.json();
      }
      if (!data.success) { setError(data.detail || data.message || "Form generation failed"); return; }
      _notifyJobDone("generate", true);
      setGeneratedForms(data.generated || {}); setCrossIssues(data.cross_issues || []);
      if (data.package_sqs) setPackageSqs(data.package_sqs);
      const firstId = data.form_ids?.[0] || null; setActiveFormId(firstId); setStep("editor");
      const readyMap = {}; (data.form_ids || []).forEach(fid => { readyMap[fid] = false; }); setPdfLoading(readyMap);
      // Generating forms now consumes a credit for the free tier (client
      // 2026-07-01: count at generation, not only at download), so refresh the
      // user to keep the remaining-usage display accurate.
      refreshUser().catch(() => {});
    } catch (e) {
      if (e.message === "Failed to fetch" || e.name === "TypeError") {
        setError("Generation failed: could not reach the server. Your documents are still loaded - click Generate again to retry.");
      } else {
        setError("Generation failed: " + e.message + " - click Generate again to retry.");
      }
    }
    finally { setLoading(false); setShowGenerateOverlay(false); }
  };

  const formIdList = Object.keys(generatedForms);
  const activeIdx = formIdList.indexOf(activeFormId);
  const goNext = () => { if (activeIdx < formIdList.length - 1) setActiveFormId(formIdList[activeIdx + 1]); };
  const goPrev = () => { if (activeIdx > 0) setActiveFormId(formIdList[activeIdx - 1]); };
  const toggleForm = formId => { setCheckedFormIds(prev => { const next = new Set(prev); if (next.has(formId)) next.delete(formId); else next.add(formId); return next; }); };

  const recommendedIds = new Set(recommendations.map(r => r.form_id));
  const extraForms = allAvailableForms.filter(f => !recommendedIds.has(f.form_id));
  // Group recommendations by tier for display (Beta Report §7). Order within a
  // tier is preserved from the backend (confidence-sorted). Any recommendation
  // without a known tier falls back to "recommended" so nothing is dropped.
  const tierOf = (r) => (TIER_ORDER.includes(r.tier) ? r.tier : "recommended");
  const groupedRecs = TIER_ORDER
    .map(t => ({ tier: t, items: recommendations.filter(r => tierOf(r) === t) }))
    .filter(g => g.items.length > 0);
  const activeSqs = activeFormId && generatedForms[activeFormId]?.sqs;
  const pkgsUsed = user?.packages_used || 0;
  const pkgsLimit = user?.packages_limit || 0;
  const softBuffer = user?.packages_soft_buffer || 0;
  const inOverage = user?.subscription_tier !== "free" && pkgsLimit > 0 && pkgsUsed >= pkgsLimit + softBuffer;
  const freeExhausted = user?.subscription_tier === "free" && user?.downloads_remaining === 0;

  const handleNewPackage = () => {
    if (freeExhausted) { onShowUpgrade(); return; }
    resetToUpload();
  };

  const BillingBtnSpinner = () => (
    <span style={{ width: 11, height: 11, border: "2px solid currentColor", borderTopColor: "transparent", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite", marginRight: 4 }} />
  );

  // Producer answers a recommendation (Fig 13): send the typed value to the
  // answer endpoint, which writes it as a producer-provenance fact, re-runs the
  // rules, and returns the before/after impact. Updates the per-form + package
  // SQS in place (same shape as dismiss) and hands the impact back to the card
  // for its inline result. Returns { ok, impact } / { ok:false, error }.
  const handleAnswerRec = async (rec, answerText) => {
    const id = rec?.rec_id;
    if (!id) return { ok: false, error: "Missing recommendation id." };
    const field = rec?.field;
    if (!field) return { ok: false, error: "This item can't be answered directly." };
    const trimmed = (answerText || "").trim();
    if (!trimmed) return { ok: false, error: "Please enter an answer." };
    const formIdAtAnswer = activeFormId;
    const scoreAtAction = (formIdAtAnswer && generatedForms[formIdAtAnswer]?.sqs?.sqs_score) ?? 0;
    try {
      const res = await fetch(`${API_BASE}/api/audit/answer`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          rec_id: id,
          field,
          answer: trimmed,
          sqs_score_at_action: scoreAtAction,
          form_id: formIdAtAnswer ?? null,
        }),
      });
      const data = await res.json();
      if (!data.success) {
        return { ok: false, error: data.validation_error || data.message || "Could not apply answer." };
      }
      // Update per-form SQS from the recomputed scores (same shape as dismiss credit).
      if (data.updated_forms && Object.keys(data.updated_forms).length > 0) {
        setGeneratedForms(prev => {
          const next = { ...prev };
          for (const [fid, upd] of Object.entries(data.updated_forms)) {
            const form = next[fid];
            if (!form?.sqs) continue;
            next[fid] = {
              ...form,
              sqs: {
                ...form.sqs,
                sqs_score:  upd.new_sqs_score,
                grade:      upd.new_grade      ?? form.sqs.grade,
                tier:       upd.new_tier       ?? form.sqs.tier,
                tier_color: upd.new_tier_color ?? form.sqs.tier_color,
              },
            };
          }
          return next;
        });
      }
      if (data.new_package_sqs_score != null) {
        setPackageSqs(prev => {
          if (!prev) return prev;
          return {
            ...prev,
            package_sqs_score: data.new_package_sqs_score,
            tier: data.new_package_tier ?? prev.tier,
          };
        });
      }
      return { ok: true, impact: data.impact || null };
    } catch (e) {
      return { ok: false, error: "Network error. Please try again." };
    }
  };

  const handleDismissRec = async (rec, currentScore, reason = "") => {
    const id = rec?.rec_id;
    if (!id) return;
    // Capture form id now — user may switch forms before the await resolves
    const formIdAtDismiss = activeFormId;
    const trimmedReason = reason.trim();
    // Remove from dismissedRecs set (for filter) and record details for the dismissed
    // panel so it appears immediately, without waiting on the backend refetch. The
    // credit is only applied (and the +pts badge only shown) when a real reason was
    // typed - matching the backend credit gate.
    setDismissedRecs(prev => {
      const next = new Set(prev);
      next.add(id);
      return next;
    });
    setDismissedRecDetails(prev => {
      const next = new Map(prev);
      next.set(id, {
        message: rec.message,
        reason:  trimmedReason,
        formId:  formIdAtDismiss,
        impact:  trimmedReason ? (rec.score_impact || 0) : 0,
      });
      return next;
    });
    // Also remove directly from generatedForms so rec doesn't reappear on re-render
    if (formIdAtDismiss) {
      setGeneratedForms(prev => {
        const form = prev[formIdAtDismiss];
        if (!form?.sqs?.recommendations) return prev;
        return {
          ...prev,
          [formIdAtDismiss]: {
            ...form,
            sqs: {
              ...form.sqs,
              recommendations: form.sqs.recommendations.filter(r =>
                (typeof r === "object" ? r.rec_id : r) !== id
              ),
            },
          },
        };
      });
    }
    try {
      const res = await fetch(`${API_BASE}/api/audit/dismiss`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          rec_id: id,
          override_reason: reason.trim() || "No reason provided",
          sqs_score_at_action: currentScore ?? 0,
          message: rec.message ?? null,
          field: rec.field ?? null,
          component: rec.component ?? null,
          score_impact: rec.score_impact ?? null,
          form_id: formIdAtDismiss ?? null,
        }),
      });
      const data = await res.json();
      // Credit: update every form the backend identified as carrying this rec_id,
      // plus the package. For a single-form rec only that form changes; for a
      // multi-form rec all affected forms change; for a package-only rec
      // updated_forms is empty and only the package score moves.
      if (data.updated_forms && Object.keys(data.updated_forms).length > 0) {
        setGeneratedForms(prev => {
          const next = { ...prev };
          for (const [fid, upd] of Object.entries(data.updated_forms)) {
            const form = next[fid];
            if (!form?.sqs) continue;
            next[fid] = {
              ...form,
              sqs: {
                ...form.sqs,
                sqs_score:  upd.new_sqs_score,
                grade:      upd.new_grade      ?? form.sqs.grade,
                tier:       upd.new_tier       ?? form.sqs.tier,
                tier_color: upd.new_tier_color ?? form.sqs.tier_color,
              },
            };
          }
          return next;
        });
      }
      if (data.new_package_sqs_score != null) {
        setPackageSqs(prev => {
          if (!prev) return prev;
          return {
            ...prev,
            package_sqs_score: data.new_package_sqs_score,
            tier: data.new_package_tier ?? prev.tier,
          };
        });
      }
      // Refresh dismissed panel from DB so it persists across reloads
      loadDismissedRecs(sessionId);
    } catch (_) {}
  };

  const _runPreflightThenDownload = async (downloadFn) => {
    setDownloadPreflightLoading(true);
    try {
      const [recsRes, narrativeRes] = await Promise.allSettled([
        fetch(`${API_BASE}/api/audit/open/${sessionId}`, { credentials: "include" }),
        fetch(`${API_BASE}/api/sqs/narrative/${sessionId}`, { credentials: "include" }),
      ]);
      const recsData = recsRes.status === "fulfilled" && recsRes.value.ok ? await recsRes.value.json() : null;
      const openRecs = recsData?.open_recommendations || [];
      const narrativeData = narrativeRes.status === "fulfilled" && narrativeRes.value.ok ? await narrativeRes.value.json() : null;
      if (narrativeData?.narrative) setSqsNarrative(narrativeData.narrative);
      // Keep the post-download checklist in sync with the current package, even when
      // nothing is flagged, so a previously-flagged package can't leave stale items behind.
      setPreflightRecs(openRecs);
      // "hardblock" items (placeholder values / required COPE-style fields, Figure 35
      // client feedback) are a DIFFERENT class from every other soft/advisory rec here:
      // they cannot be waved through with the ordinary "Download Anyway" - the server
      // will 409 unless the request explicitly asks for a watermarked draft with a
      // reason. Identified by the "hardblock_" marker services.field_qa.
      // to_recommendation_rows puts in rec_id - see backend/services/field_qa.py.
      const hasHardBlock = openRecs.some(r => (r.rec_id || "").includes("hardblock_"));
      setPreflightHardBlock(hasHardBlock);
      if (openRecs.length === 0) { downloadFn({}); return; }
      setPreflightOverrideReason("");
      setPreflightCallback(() => downloadFn);
      setShowDownloadPreflight(true);
    } catch (_) { downloadFn({}); }
    finally { setDownloadPreflightLoading(false); }
  };

  const handlePreflightProceed = () => {
    const reason = preflightOverrideReason.trim();
    // The button always reads "Download Anyway" and is never grayed out (Hard
    // Stops display identically to every other hard stop) - but a hard-block item
    // still requires a typed note before it can actually proceed, since the server
    // will 409 without one. A no-op click here (with the inline hint already
    // visible) is safer than round-tripping to the server just to show the same
    // message back.
    if (preflightHardBlock && !reason) return;
    setShowDownloadPreflight(false);
    if (preflightHardBlock) {
      // The server re-verifies independently and returns a watermarked, clearly-
      // labeled draft PDF - this is never silently the same as a clean download.
      if (preflightCallback) preflightCallback({ draft: true, overrideReason: reason });
      return;
    }
    // Ordinary soft recs: fire the existing advisory audit log in background - don't
    // block the download.
    fetch(`${API_BASE}/api/audit/download-anyway`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, override_reason: reason }),
    }).catch(() => {});
    if (preflightCallback) preflightCallback({});
  };

  const handleDownloadOne = formId => gatedDownload(() => _runPreflightThenDownload(draftOpts => _doDownloadOne(formId, draftOpts)));
  const handleDownloadAll = () => gatedDownload(() => _runPreflightThenDownload(draftOpts => _doDownloadAll(draftOpts)));

  const handleLiteCoverSheet = async () => {
    setLiteCoverLoading(true); setShowDownloadOverlay(true);
    try {
      const res = await fetch(`${API_BASE}/api/lite/cover-sheet/${sessionId}`, { credentials: "include" });
      if (res.status === 403) { onShowUpgrade(); return; }
      if (!res.ok) { setError("Failed to generate cover sheet."); return; }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a"); a.href = url; a.download = "Primble_SQS_Cover_Sheet.pdf";
      document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
    } catch { setError("Download failed. Please try again."); }
    finally { setLiteCoverLoading(false); setShowDownloadOverlay(false); }
  };

  // E&O audit record (Figure 6 client clarification, 2026-07-17): not pushed to
  // underwriters - just a plain-text export of every reason the producer gave
  // on this submission (marketing reason + dismissed items + issue overrides +
  // download-anyway notes), downloadable on demand. Never gated by open
  // recommendations - it's most useful exactly when there are open items.
  const handleDownloadAuditRecord = async () => {
    if (!sessionId) return;
    setAuditExportLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/audit/export/${sessionId}`, { credentials: "include" });
      if (!res.ok) { setError("Failed to generate audit record."); return; }
      const d = await res.json();
      const lines = [];
      lines.push("PRIMBLE - SUBMISSION AUDIT RECORD");
      lines.push(`Session: ${sessionId}`);
      lines.push(`Generated: ${new Date().toISOString()}`);
      lines.push("");
      lines.push("WHY THIS ACCOUNT IS BEING MARKETED");
      if (d.marketing_reason) {
        lines.push(`  Reason: ${d.marketing_reason.reason_code}`);
        if (d.marketing_reason.reason_note) lines.push(`  Note: ${d.marketing_reason.reason_note}`);
        lines.push(`  Recorded: ${d.marketing_reason.updated_at}`);
      } else {
        lines.push("  (none recorded)");
      }
      lines.push("");
      lines.push("DISMISSED ITEMS");
      if (d.dismissed_recommendations?.length) {
        for (const r of d.dismissed_recommendations) {
          lines.push(`  - ${r.message}`);
          lines.push(`    Reason: ${r.override_reason || "(none given)"}`);
          lines.push(`    Form: ${r.form_id || "-"}  |  Dismissed: ${r.action_at}`);
        }
      } else {
        lines.push("  (none)");
      }
      lines.push("");
      lines.push("ISSUE STATUS OVERRIDES");
      if (d.issue_status_overrides?.length) {
        for (const s of d.issue_status_overrides) {
          lines.push(`  - ${s.message || s.issue_id} [${s.status}]`);
          lines.push(`    Reason: ${s.reason}`);
          lines.push(`    Updated: ${s.updated_at}`);
        }
      } else {
        lines.push("  (none)");
      }
      lines.push("");
      lines.push("DOWNLOADED WITH OPEN ITEMS");
      if (d.download_anyway_log?.length) {
        for (const dl of d.download_anyway_log) {
          lines.push(`  - ${dl.override_note || "(no note given)"}  (${dl.open_rec_count} open at the time)`);
          lines.push(`    Downloaded: ${dl.downloaded_at}`);
        }
      } else {
        lines.push("  (none)");
      }
      const blob = new Blob([lines.join("\n")], { type: "text/plain" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a"); a.href = url; a.download = `Primble_Audit_Record_${sessionId}.txt`;
      document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
    } catch { setError("Failed to generate audit record."); }
    finally { setAuditExportLoading(false); }
  };

  return (
    <div className={step === "editor" ? "acord-modal-editor-root" : undefined} style={{
      background: "#f8fafc", width: "100%",
      ...(step === "editor"
        ? { height: "calc(100vh - 81px)", display: "flex", flexDirection: "column", overflow: "hidden" }
        : { minHeight: "calc(100vh - 81px)" })
    }}>
      <div style={{
        padding: step === "editor" ? 0 : "32px 40px",
        ...(step === "editor" && { flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", minHeight: 0 })
      }}>
        {renderContent()}
      </div>
      {showEnterprisePopup && (
        <div style={{ position: "fixed", top: enterprisePopupPos.top, left: enterprisePopupPos.left, zIndex: 9999, width: 210, borderRadius: 10, background: "#fdf2f8", border: "1px solid #f9a8d4", boxShadow: "0 6px 24px rgba(230,0,122,0.15), 0 2px 8px rgba(230,0,122,0.08)", overflow: "hidden", animation: "slideDown 0.18s ease-out" }}>
          {/* left-pointing caret */}
          <div style={{ position: "absolute", top: 14, left: -6, width: 11, height: 11, background: "#fdf2f8", border: "1px solid #f9a8d4", borderRight: "none", borderTop: "none", transform: "rotate(45deg)" }} />
          <div style={{ padding: "10px 10px 10px 14px", display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 6 }}>
            <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
              <span style={{ fontSize: 12, fontWeight: 700, color: "#be185d" }}>Enterprise only for now</span>
              <span style={{ fontSize: 11, color: "#9d174d", lineHeight: 1.45 }}>Join the waitlist to get early access.</span>
            </div>
            <button onClick={() => setShowEnterprisePopup(false)} style={{ flexShrink: 0, background: "none", border: "none", cursor: "pointer", color: "#be185d", fontSize: 15, lineHeight: 1, padding: "1px 3px", opacity: 0.6 }} onMouseEnter={e => e.currentTarget.style.opacity = "1"} onMouseLeave={e => e.currentTarget.style.opacity = "0.6"}>×</button>
          </div>
          <div style={{ height: 3, background: "linear-gradient(90deg, #f9a8d4, #E61B84)" }} />
        </div>
      )}
      {showAcordModal && renderAcordLicenseModal()}
      {showARQModal && <ARQModal sessionId={sessionId} token={token} questions={arqQuestions} summary={arqSummary} onClose={() => setShowARQModal(false)} onSuccess={() => { setShowARQModal(false); refreshArqData(); }} />}
      {/* "Review extracted data" panel (Beta Report §4.2 item #6) */}
      {reviewData && (
        <div
          onClick={() => setReviewData(null)}
          style={{ position: "fixed", inset: 0, zIndex: 1000, background: "rgba(15,23,42,0.55)", display: "flex", alignItems: "center", justifyContent: "center", padding: 16 }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{ background: "#fff", borderRadius: 14, width: "100%", maxWidth: 560, maxHeight: "85vh", display: "flex", flexDirection: "column", boxShadow: "0 20px 60px rgba(0,0,0,0.25)", overflow: "hidden" }}
          >
            <div style={{ padding: "16px 20px", borderBottom: "1px solid #e2e8f0", display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12 }}>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 15, fontWeight: 700, color: "#1e293b" }}>Extracted data</div>
                <div style={{ fontSize: 12.5, color: "#64748b", marginTop: 2, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {reviewData.doc_type_label} · {reviewData.filename}
                </div>
              </div>
              <button type="button" onClick={() => setReviewData(null)} aria-label="Close" style={{ background: "none", border: "none", fontSize: 20, lineHeight: 1, color: "#64748b", cursor: "pointer", flexShrink: 0 }}>✕</button>
            </div>
            <div style={{ padding: "12px 20px", overflowY: "auto" }}>
              {(reviewData.fields || []).length === 0 ? (
                <div style={{ fontSize: 13, color: "#64748b", padding: "12px 0" }}>
                  No structured data was extracted from this document.
                </div>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  {reviewData.fields.map((f) => (
                    <div key={f.key} style={{ display: "flex", flexDirection: "column", gap: 2, paddingBottom: 8, borderBottom: "1px solid #f1f5f9" }}>
                      <span style={{ fontSize: 11, fontWeight: 600, color: "#64748b", textTransform: "uppercase", letterSpacing: "0.03em" }}>{f.label}</span>
                      <span style={{ fontSize: 13.5, color: "#1e293b", wordBreak: "break-word" }}>{f.value}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
            <div style={{ padding: "12px 20px", borderTop: "1px solid #e2e8f0", textAlign: "right" }}>
              <button type="button" onClick={() => setReviewData(null)} className="btn btn-modal-secondary" style={{ fontSize: 13 }}>Close</button>
            </div>
          </div>
        </div>
      )}
      {downloadPreflightLoading && <ProcessStageOverlay stages={["Checking recommendations", "Loading SQS summary"]} advanceAfter={1800} />}
      {showDownloadPreflight && (
        <DownloadPreflightModal
          openRecs={preflightRecs}
          narrative={sqsNarrative}
          overrideReason={preflightOverrideReason}
          onOverrideChange={setPreflightOverrideReason}
          onProceed={handlePreflightProceed}
          onCancel={() => { setShowDownloadPreflight(false); setPreflightCallback(null); }}
          loading={loading}
          hasHardBlock={preflightHardBlock}
        />
      )}
      {jobToasts.length > 0 && (
        <div style={{
          position: "fixed",
          right: "max(16px, env(safe-area-inset-right))",
          bottom: "max(16px, env(safe-area-inset-bottom))",
          zIndex: 10000,
          display: "flex",
          flexDirection: "column",
          gap: 10,
          maxWidth: "calc(100vw - 32px)",
          width: 340,
          pointerEvents: "none",
        }}>
          {jobToasts.map(t => (
            <div key={t.id}
              onClick={() => setJobToasts(prev => prev.filter(x => x.id !== t.id))}
              style={{
                pointerEvents: "auto",
                position: "relative",
                background: "#ffffff",
                border: `1px solid ${t.ok ? "#f9a8d4" : "#fecaca"}`,
                borderLeft: `4px solid ${t.ok ? "#e6007a" : "#dc2626"}`,
                borderRadius: 10,
                boxShadow: "0 10px 30px rgba(15,23,42,0.18), 0 2px 8px rgba(15,23,42,0.08)",
                padding: "12px 30px 12px 14px",
                cursor: "pointer",
                animation: "slideDown 0.18s ease-out",
              }}>
              <button
                type="button"
                aria-label="Dismiss notification"
                onClick={(e) => { e.stopPropagation(); setJobToasts(prev => prev.filter(x => x.id !== t.id)); }}
                style={{
                  position: "absolute",
                  top: 6,
                  right: 6,
                  width: 22,
                  height: 22,
                  border: "none",
                  borderRadius: "50%",
                  background: "transparent",
                  color: "#64748b",
                  fontSize: 16,
                  lineHeight: "20px",
                  cursor: "pointer",
                  padding: 0,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                }}>×</button>
              <div style={{ fontSize: 13, fontWeight: 700, color: "#0f172a", marginBottom: 4 }}>{t.title}</div>
              <div style={{ fontSize: 13, color: "#475569", lineHeight: 1.4 }}>{t.body}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );

  function renderAcordLicenseModal() {
    return (
      <div className="modal-overlay">
        <div className="modal-content acord-license-modal" onClick={e => e.stopPropagation()}>
          <button className="modal-close" onClick={() => { setShowAcordModal(false); setAcordLicenseChecked(false); }}>✕</button>
          <div className="modal-inner">
            <div className="acord-license-icon"></div>
            <h2 className="acord-license-title">ACORD® License Confirmation</h2>
            <div className="acord-license-body">
              <p>ACORD® Forms are copyrighted material owned by ACORD Corporation and are licensed, not sold. By continuing, you confirm that you or your organization maintain a valid ACORD license permitting the use of these forms.</p>
              <p>If your organization does not currently have an ACORD license, you can obtain one{" "}<a href="https://www.acord.org/forms-pages/forms-participation-programs/forms-end-user-licenses" target="_blank" rel="noopener noreferrer" className="acord-license-link">HERE</a>.</p>
              <p className="acord-license-note"><strong>Note:</strong> Primble does not sell, grant, or provide ACORD licenses. Confirming here only attests that your organization already holds a valid license obtained directly from ACORD.</p>
            </div>
            <label className="acord-confirm-checkbox-label" style={{ display: "flex", alignItems: "center", gap: 10, cursor: "pointer" }}>
              <input type="checkbox" checked={acordLicenseChecked} onChange={e => setAcordLicenseChecked(e.target.checked)} className="acord-confirm-checkbox" style={{ flexShrink: 0, width: 16, height: 16, marginTop: 0, cursor: "pointer" }} />
              <span>My organization holds a valid ACORD license.</span>
            </label>
            <button className="btn btn-modal-primary btn-block" onClick={handleAcordConfirm} disabled={!acordLicenseChecked || acordModalLoading}>
              {acordModalLoading ? <span style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 8 }}><span style={{ width: 14, height: 14, border: "2px solid currentColor", borderTopColor: "transparent", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" }} />Confirming...</span> : "Confirm and Download"}
            </button>
            <div className="acord-stub-actions">
              <span className="acord-stub-label">Coming soon:</span>
              <button className="btn-stub" disabled>Email</button>
              <button className="btn-stub" disabled>Share</button>
              <button className="btn-stub" disabled>Fax</button>
            </div>
            <button className="btn btn-modal-secondary btn-block" onClick={() => { setShowAcordModal(false); setAcordLicenseChecked(false); }}>Cancel</button>
          </div>
        </div>
      </div>
    );
  }

  function renderContent() {
    return (
      <>
        {showUploadOverlay && (
          uploadProgressToken ? (
            <UploadProgressOverlay
              token={uploadProgressToken}
              apiBase={API_BASE}
              onDone={resumingUpload ? handleUploadResumeDone : undefined}
              onMissing={resumingUpload ? handleUploadResumeMissing : undefined}
              tagline={<><span style={{ color: "#e61b84" }}>Quality takes a little time.</span><br />Doing this manually would take a lot more.</>}
              note={<>You can leave this page during processing, but do <strong>not</strong> close it. Enable<br />your browser notifications, and we'll let you know as soon as it's ready.</>}
            />
          ) : (
            <ProcessStageOverlay
              stages={["Reading your documents…", "Extracting facts…"]}
              advanceAfter={3500}
              tagline={<><span style={{ color: "#e61b84" }}>Quality takes a little time.</span><br />Doing this manually would take a lot more.</>}
              note={<>You can leave this page during processing, but do <strong>not</strong> close it. Enable<br />your browser notifications, and we'll let you know as soon as it's ready.</>}
            />
          )
        )}
        {showGenerateOverlay && (() => {
          // Workstream 6 §9.3 - generalized, client-approved progress stages plus a
          // rough ETA. Forms aren't generated strictly one-by-one (shared LLM pass),
          // so these describe the real phases instead of faking "form 1 of N". The
          // overlay holds on the last stage until the response lands.
          const _stages = [
            "Preparing Form Package",
            "Gathering Submission Data",
            "Mapping ACORD Fields",
            "Validating Data",
            "Generating Forms",
            "Performing Quality Checks",
            "Preparing Download Package",
          ];
          // ETA for the GENERATION phase only — OCR + fact extraction already ran
          // at form-select time, so this estimates the gap-fill work that remains.
          // Two drivers, each a proxy for the number of LLM gap-fill calls:
          //   • forms — each selected form ≈ 3-4 LLM calls (~17s each) once its
          //     unmatched fields are batched; FILL_PER_FORM bakes in a ~15% buffer
          //     for OpenAI TPM throttling when parallel chunks collide.
          //   • document size — total MB of uploaded files is the best available
          //     proxy for raw text volume; more text means more chunks per batch,
          //     i.e. more LLM calls. ~8s/MB after de-duping the TPM cost already
          //     in FILL_PER_FORM. Falls back to forms-only when files is empty
          //     (session resume path), which is correct.
          // Calibrated against a 2-form (ACORD 125+126, ~803 fields), 271-page run
          // that took ~3.5 min: this estimates ~4.1 min — deliberately slightly
          // high so we never bottom out and look stalled before the response lands.
          const FILL_BASE     = 20;   // fixed setup overhead (seconds)
          const FILL_PER_FORM = 65;   // per selected form
          const TEXT_PER_MB   = 8;    // per MB of uploaded documents
          const _totalMB = files.reduce((sum, f) => sum + f.size, 0) / (1024 * 1024);
          const _formCount = Math.max(1, checkedFormIds.size);
          // Fig 8: on a mid-generation resume, use the remaining time carried over
          // from the server's start timestamp instead of a fresh full estimate.
          const _eta = resumeGenEta != null
            ? resumeGenEta
            : Math.max(45, FILL_BASE + _formCount * FILL_PER_FORM + Math.round(_totalMB * TEXT_PER_MB));
          // Spread the stages evenly across the WHOLE ETA so the final stage is
          // reached near the end, not minutes early. Each stage takes an equal
          // slice (_eta / stage count); a small floor keeps short jobs from
          // flickering. No upper cap — a longer ETA simply lets each stage breathe
          // longer, which is what keeps them in step with the countdown.
          const _adv = Math.max(2000, Math.round((_eta * 1000) / _stages.length));
          return (
            <ProcessStageOverlay
              stages={_stages}
              advanceAfter={_adv}
              etaSeconds={_eta}
              windowSize={2}
              tagline={<><span style={{ color: "#e61b84" }}>Quality takes a little time.</span><br />Doing this manually would take a lot more.</>}
              note={<>You can leave this page during processing, but do <strong>not</strong> close it. Enable<br />your browser notifications, and we'll let you know as soon as it's ready.</>}
            />
          );
        })()}
        {showDownloadOverlay && <ProcessStageOverlay stages={["Preparing your form…", "Packaging for download…"]} advanceAfter={2000} />}

        {loading && !showUploadOverlay && !showGenerateOverlay && !showDownloadOverlay && step !== "editor" && (
          <div className="loading-overlay"><div className="loading-spinner" /><p className="loading-text">{processingStage || "Processing..."}</p></div>
        )}

        {user && user.subscription_tier === "free" && user.downloads_remaining === 0 && step !== "upload" && step !== "dashboard" && (
          <div className="freemium-banner freemium-depleted">
            <span className="freemium-text">Free limit reached - upgrade to continue</span>
            <button className="freemium-upgrade-btn" onClick={onShowUpgrade}>Upgrade Now</button>
          </div>
        )}

        {inOverage && (
          <div style={{ background: "#fff7ed", border: "1px solid #fed7aa", borderRadius: 8, padding: "9px 14px", fontSize: 12, color: "#92400e", marginBottom: 8, display: "flex", alignItems: "center", gap: 8 }}>
            <span>You're in overage territory - each additional download will be billed on your next invoice.</span>
          </div>
        )}

        {user && user.subscription_tier !== "free" && (() => {
          const ps = user.payment_status;
          if (ps === "archived") return <div className="payment-status-banner payment-status-archived">🗄️ Account archived - <a href="mailto:support@primble.ai">Contact support</a> to restore.</div>;
          if (ps === "suspended") return <div className="payment-status-banner payment-status-suspended">Account suspended.{" "}<button onClick={onOpenBillingPortal} disabled={billingPortalLoading} style={{ color: "inherit", fontWeight: 700, textDecoration: "underline", background: "none", border: "none", cursor: billingPortalLoading ? "wait" : "pointer", padding: 0, display: "inline-flex", alignItems: "center", gap: 4 }}>{billingPortalLoading && <BillingBtnSpinner />}Restore billing</button></div>;
          if (ps === "soft_locked") return <div className="payment-status-banner payment-status-locked">Account Disabled - Please{" "}<button onClick={onOpenBillingPortal} disabled={billingPortalLoading} style={{ color: "inherit", fontWeight: 700, textDecoration: "underline", background: "none", border: "none", cursor: billingPortalLoading ? "wait" : "pointer", padding: 0, display: "inline-flex", alignItems: "center", gap: 4 }}>{billingPortalLoading && <BillingBtnSpinner />}update your billing</button>{" "}to restore access.</div>;
          if (ps === "failed") {
            const daysFailed = user.payment_failed_at ? Math.floor((Date.now() - new Date(user.payment_failed_at).getTime()) / 86400000) : 0;
            if (daysFailed >= 7) return <div className="payment-status-banner payment-status-failed" style={{ background: "#fef2f2", borderColor: "#fca5a5", fontWeight: 700, display: "flex", alignItems: "center", gap: 8, flexWrap: "nowrap" }}>Payment still overdue - account will be restricted soon.{" "}<button onClick={onOpenBillingPortal} disabled={billingPortalLoading} style={{ color: "inherit", fontWeight: 700, textDecoration: "underline", background: "none", border: "none", cursor: billingPortalLoading ? "wait" : "pointer", padding: 0, flexShrink: 0, display: "inline-flex", alignItems: "center", gap: 4 }}>{billingPortalLoading && <BillingBtnSpinner />}Update billing now</button></div>;
            return <div className="payment-status-banner payment-status-failed">Payment overdue -{" "}<button onClick={onOpenBillingPortal} disabled={billingPortalLoading} style={{ color: "inherit", fontWeight: 700, textDecoration: "underline", background: "none", border: "none", cursor: billingPortalLoading ? "wait" : "pointer", padding: 0, display: "inline-flex", alignItems: "center", gap: 4 }}>{billingPortalLoading && <BillingBtnSpinner />}update billing</button></div>;
          }
          return null;
        })()}

        {pkgStatusMsg && (
          <div className="overage-inline-notice" style={{ background: pkgStatusType === "overage" ? "#fefce8" : "#f0fdf4", borderColor: pkgStatusType === "overage" ? "#fde047" : "#86efac", color: pkgStatusType === "overage" ? "#713f12" : "#14532d" }}>
            <span></span>
            <span>{pkgStatusMsg}{" "}<button onClick={() => setPkgStatusMsg("")} style={{ background: "none", border: "none", cursor: "pointer", color: "inherit", fontWeight: 700, fontSize: 12, textDecoration: "underline" }}>Dismiss</button></span>
          </div>
        )}

        {error && (
          <div className="alert alert-error" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
            <span style={{ flex: 1 }}>{error}</span>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              {step === "recommendations" && checkedFormIds.size > 0 && (
                <button
                  onClick={() => { setError(null); handleGenerateAll(); }}
                  style={{ padding: "5px 14px", background: "#E61B84", color: "#fff", border: "none", borderRadius: 6, fontSize: 12, fontWeight: 700, cursor: "pointer", whiteSpace: "nowrap" }}
                >
                  Retry Generation
                </button>
              )}
              <button className="alert-close" onClick={() => setError(null)}>✕</button>
            </div>
          </div>
        )}

        {step === "dashboard" && <DashboardStep token={token} onResume={handleResumeSession} onNewPackage={handleNewPackage} />}

        {step === "lite" && (() => {
          const sqs = liteSqsData?.sqs;
          const liteReady = !liteGenerating && !!sqs;
          const liteGradeColor = g => ({ A: "#10b981", B: "#eab308", C: "#f59e0b", D: "#ef4444", F: "#ef4444" }[g] || "#94a3b8");
          const liteGradeBg = g => ({ A: "rgba(16,185,129,0.08)", B: "rgba(234,179,8,0.08)", C: "rgba(245,158,11,0.08)", D: "rgba(239,68,68,0.08)", F: "rgba(239,68,68,0.08)" }[g] || "rgba(148,163,184,0.08)");
          // Unified routing ladder (both per-form and package):
          //   auto_quote > 85 | priority_review >= 70 | standard_review >= 50 | hold
          const routingLabel = {
            auto_quote:       "Auto-Route to Quoting",
            priority_review:  "Priority Review",
            standard_review:  "Standard Review",
            hold:             "Hold - Remediation Required",
          };
          const routingStyle = {
            auto_quote:      { bg: "#dcfce7", color: "#166534", border: "#86efac" },
            priority_review: { bg: "#fef9c3", color: "#854d0e", border: "#fde047" },
            standard_review: { bg: "#fef3c7", color: "#92400e", border: "#fcd34d" },
            hold:            { bg: "#fee2e2", color: "#991b1b", border: "#fca5a5" },
          };
          const rd = sqs?.routing_decision;
          const rs = routingStyle[rd] || { bg: "#f1f5f9", color: "#475569", border: "#e2e8f0" };
          return (
            <div style={{ maxWidth: 960, margin: "0 auto", padding: "0 16px" }}>

              {/* Submission Integrity status (Beta Report §4.1): advisory banner,
                  all statuses, mirrored from the recommendations step. */}
              {renderIntegrityStatus()}

              {/* ── Page header ── */}
              <div style={{ marginBottom: 28 }}>
                <div style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 13, fontWeight: 700, color: "#E61B84", letterSpacing: "0.08em", textTransform: "uppercase", background: "rgba(230,0,122,0.07)", padding: "3px 10px", borderRadius: 20, marginBottom: 10 }}>
                  Essentials
                </div>
                <h2 style={{ fontSize: 26, fontWeight: 700, color: "#0f172a", margin: "0 0 6px", letterSpacing: "-0.3px" }}>Submission Analysis</h2>
                <p style={{ fontSize: 13.5, color: "#64748b", margin: 0 }}>{liteGenerating ? "Carefully analyzing your submission to generate a submission quality score and identify critical gaps." : "Your SQS score is ready. Use the tools below to complete your workflow."}</p>
              </div>

              {/* ── SQS hero card ── */}
              <div style={{ background: "#fff", border: "1.5px solid #e2e8f0", borderRadius: 20, padding: "28px 36px", marginBottom: 16, boxShadow: "0 2px 8px rgba(0,0,0,0.05)" }}>
                {!sqs ? (
                  <div style={{ display: "flex", flexDirection: "column", alignItems: "center", padding: "24px 0", gap: 14 }}>
                    <span style={{ width: 40, height: 40, border: "3px solid #e2e8f0", borderTopColor: "#E61B84", borderRadius: "50%", display: "inline-block", animation: "spin 0.8s linear infinite" }} />
                    <div style={{ fontSize: 14, color: "#64748b", fontWeight: 500 }}>Generating your full analysis…</div>
                    <div style={{ fontSize: 12, color: "#94a3b8" }}>Calculating SQS and pre-building client questionnaire…</div>
                  </div>
                ) : (
                  <div>
                    <div style={{ fontSize: 15, fontWeight: 800, color: "#94a3b8", letterSpacing: "0.07em", textTransform: "uppercase", marginBottom: 20 }}>Submission Quality Score</div>
                    <div style={{ display: "flex", alignItems: "center", gap: 28, marginBottom: 20, flexWrap: "wrap" }}>

                      {/* Score circle */}
                      <div style={{ position: "relative", flexShrink: 0 }}>
                        <div style={{ width: 120, height: 120, borderRadius: "50%", background: liteGradeBg(sqs.grade), border: `3px solid ${liteGradeColor(sqs.grade)}`, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center" }}>
                          <span style={{ fontSize: 42, fontWeight: 900, color: liteGradeColor(sqs.grade), lineHeight: 1 }}>{sqs.sqs_score ?? "-"}</span>
                          <span style={{ fontSize: 12, fontWeight: 700, color: liteGradeColor(sqs.grade), opacity: 0.75, marginTop: 2 }}>/100</span>
                        </div>
                        <div style={{ position: "absolute", bottom: -4, right: -4, width: 32, height: 32, borderRadius: "50%", background: liteGradeColor(sqs.grade), display: "flex", alignItems: "center", justifyContent: "center", fontSize: 14, fontWeight: 800, color: "#fff", boxShadow: "0 2px 6px rgba(0,0,0,0.2)" }}>
                          {sqs.grade}
                        </div>
                      </div>

                      {/* Score details */}
                      <div style={{ flex: 1, minWidth: 200 }}>
                        <div style={{ fontSize: 18, fontWeight: 700, color: "#0f172a", marginBottom: 6 }}>{sqs.tier || "Submission Scored"}</div>
                        {rd && (
                          <div style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "5px 12px", borderRadius: 20, border: `1px solid ${rs.border}`, background: rs.bg, color: rs.color, fontSize: 12, fontWeight: 700, marginBottom: 12 }}>
                            {routingLabel[rd] || rd}
                          </div>
                        )}
                        {/* Breakdown pillars */}
                        {sqs.breakdown && Object.keys(sqs.breakdown).length > 0 && (
                          <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 4 }}>
                            {Object.entries(sqs.breakdown).slice(0, 4).map(([key, val]) => (
                              <div key={key}>
                                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, marginBottom: 2 }}>
                                  <span style={{ color: "#64748b" }}>{SQS_LABELS[key] || key}</span>
                                  <span style={{ fontWeight: 700, color: barColor(val) }}>{val}%</span>
                                </div>
                                <div style={{ height: 4, background: "#f1f5f9", borderRadius: 2, overflow: "hidden" }}>
                                  <div style={{ height: "100%", width: `${val}%`, background: barColor(val), borderRadius: 2, transition: "width 0.6s ease" }} />
                                </div>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>

                    {/* Stops - side by side on desktop, stacked on mobile */}
                    {(liteSqsData?.hard_stops?.length > 0 || liteSqsData?.soft_stops?.length > 0) && (
                      <div style={{ borderTop: "1px solid #f1f5f9", paddingTop: 16 }}>
                        <div className="lite-stops-grid">
                          {liteSqsData?.hard_stops?.length > 0 && (
                            <div style={{ background: "#fef2f2", border: "1px solid #fecaca", borderRadius: 10, padding: "12px 16px" }}>
                              <div style={{ fontSize: 11, fontWeight: 700, color: "#991b1b", marginBottom: 7 }}>Hard Stops - Caps Your Score at 60</div>
                              {liteSqsData.hard_stops.map((s, i) => (
                                <div key={i} style={{ fontSize: 12, color: "#7f1d1d", padding: "2px 0", display: "flex", gap: 6 }}>
                                  <span style={{ flexShrink: 0 }}>•</span><span>{s}</span>
                                </div>
                              ))}
                            </div>
                          )}
                          {liteSqsData?.soft_stops?.length > 0 && (
                            <div style={{ background: "#fffbeb", border: "1px solid #fde68a", borderRadius: 10, padding: "12px 16px" }}>
                              <div style={{ fontSize: 11, fontWeight: 700, color: "#92400e", marginBottom: 7 }}>Warnings - Will Cap Your Score at 85</div>
                              {liteSqsData.soft_stops.map((s, i) => (
                                <div key={i} style={{ fontSize: 12, color: "#78350f", padding: "2px 0", display: "flex", gap: 6 }}>
                                  <span style={{ flexShrink: 0 }}>•</span><span>{s}</span>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>

              {/* ── Action cards ── */}
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, marginBottom: 24 }}>

                {/* Send to Client (ARQ) */}
                <div style={{ background: "#fff", border: "1.5px solid #e2e8f0", borderRadius: 16, padding: "22px 24px 20px", display: "flex", flexDirection: "column", boxShadow: "0 1px 4px rgba(0,0,0,0.04)" }}>
                  <div style={{ width: 40, height: 40, borderRadius: 10, background: "rgba(230,0,122,0.08)", display: "flex", alignItems: "center", justifyContent: "center", marginBottom: 12 }}>
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#E61B84" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg>
                  </div>
                  <div style={{ fontSize: 14, fontWeight: 700, color: "#0f172a", marginBottom: 4 }}>Send to Client</div>
                  <div style={{ fontSize: 12, color: "#64748b", marginBottom: 16, lineHeight: 1.55, flex: 1 }}>Client-in-the-Loop™ - send a targeted questionnaire to fill gaps and improve your score.</div>
                  <button onClick={handleOpenARQ} disabled={!liteReady || arqLoadingQ}
                    style={{ width: "100%", padding: "11px 14px", borderRadius: 10, border: "none", background: (!liteReady || arqLoadingQ) ? "#e2e8f0" : "#E61B84", color: (!liteReady || arqLoadingQ) ? "#94a3b8" : "#fff", fontSize: 13, fontWeight: 700, cursor: (!liteReady || arqLoadingQ) ? "not-allowed" : "pointer", fontFamily: "inherit", display: "flex", alignItems: "center", justifyContent: "center", gap: 6, transition: "background 0.15s, box-shadow 0.15s", boxShadow: (!liteReady || arqLoadingQ) ? "none" : "0 4px 12px rgba(230,0,122,0.25)" }}
                    onMouseEnter={e => { if (liteReady && !arqLoadingQ) { e.currentTarget.style.background = "#C0157A"; e.currentTarget.style.boxShadow = "0 6px 18px rgba(230,0,122,0.35)"; } }}
                    onMouseLeave={e => { if (liteReady && !arqLoadingQ) { e.currentTarget.style.background = "#E61B84"; e.currentTarget.style.boxShadow = "0 4px 12px rgba(230,0,122,0.25)"; } }}>
                    {liteGenerating ? <><span style={{ width: 11, height: 11, border: "2px solid #94a3b8", borderTopColor: "#475569", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" }} /> Preparing…</> : arqLoadingQ ? <><span style={{ width: 11, height: 11, border: "2px solid #94a3b8", borderTopColor: "#475569", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" }} /> Loading…</> : "Send to Client"}
                  </button>
                  <ARQStatusPanel arqSessions={arqSessions} token={token} onRefresh={refreshArqData} scoreImprovement={(() => { const _base = packageSqs?.sqs_history?.find(h => h?.stage === "initial_extract") || packageSqs?.sqs_history?.[0]; const _arq = packageSqs?.sqs_history?.find(h => h?.stage === "arq_remediated"); return (_base?.score != null && _arq?.score != null) ? _arq.score - _base.score : null; })()} />
                </div>

                {/* Cover Summary */}
                <div style={{ background: "#fff", border: "1.5px solid #e2e8f0", borderRadius: 16, padding: "22px 24px 20px", display: "flex", flexDirection: "column", boxShadow: "0 1px 4px rgba(0,0,0,0.04)" }}>
                  <div style={{ width: 40, height: 40, borderRadius: 10, background: "rgba(230,0,122,0.08)", display: "flex", alignItems: "center", justifyContent: "center", marginBottom: 12 }}>
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#E61B84" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>
                  </div>
                  <div style={{ fontSize: 14, fontWeight: 700, color: "#0f172a", marginBottom: 4 }}>Submission Brief</div>
                  <div style={{ fontSize: 12, color: "#64748b", marginBottom: 16, lineHeight: 1.55, flex: 1 }}>Complete submission quality narrative - easy to read for both human review and AI intake engines.</div>
                  <button onClick={handleLiteCoverSheet} disabled={!liteReady || liteCoverLoading}
                    style={{ width: "100%", padding: "11px 14px", borderRadius: 10, border: "none", background: (!liteReady || liteCoverLoading) ? "#e2e8f0" : "#E61B84", color: (!liteReady || liteCoverLoading) ? "#94a3b8" : "#fff", fontSize: 13, fontWeight: 700, cursor: (!liteReady || liteCoverLoading) ? "not-allowed" : "pointer", fontFamily: "inherit", display: "flex", alignItems: "center", justifyContent: "center", gap: 6, transition: "background 0.15s, box-shadow 0.15s", boxShadow: (!liteReady || liteCoverLoading) ? "none" : "0 4px 12px rgba(230,0,122,0.25)" }}
                    onMouseEnter={e => { if (liteReady && !liteCoverLoading) { e.currentTarget.style.background = "#C0157A"; e.currentTarget.style.boxShadow = "0 6px 18px rgba(230,0,122,0.35)"; } }}
                    onMouseLeave={e => { if (liteReady && !liteCoverLoading) { e.currentTarget.style.background = "#E61B84"; e.currentTarget.style.boxShadow = "0 4px 12px rgba(230,0,122,0.25)"; } }}>
                    {liteGenerating ? <><span style={{ width: 11, height: 11, border: "2px solid #94a3b8", borderTopColor: "#475569", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" }} /> Preparing…</> : liteCoverLoading ? <><span style={{ width: 11, height: 11, border: "2px solid #94a3b8", borderTopColor: "#475569", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" }} /> Generating…</> : "Download Brief"}
                  </button>
                </div>
              </div>

              {/* ── Footer nav ── */}
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", paddingTop: 4, gap: 12 }}>
                <button onClick={() => { resetToUpload(); }}
                  style={{ padding: "10px 22px", borderRadius: 10, border: "1.5px solid #fecaca", background: "#fef2f2", color: "#991b1b", fontSize: 13, fontWeight: 600, cursor: "pointer", fontFamily: "inherit", boxShadow: "0 2px 8px rgba(0,0,0,0.07)", transition: "box-shadow 0.15s, transform 0.15s, border-color 0.15s" }}
                  onMouseEnter={e => { e.currentTarget.style.boxShadow = "0 4px 16px rgba(0,0,0,0.12)"; e.currentTarget.style.transform = "translateY(-1px)"; e.currentTarget.style.borderColor = "#fca5a5"; }}
                  onMouseLeave={e => { e.currentTarget.style.boxShadow = "0 2px 8px rgba(0,0,0,0.07)"; e.currentTarget.style.transform = "none"; e.currentTarget.style.borderColor = "#fecaca"; }}>
                  ← New Submission
                </button>
                <button onClick={onShowUpgrade}
                  style={{ padding: "10px 22px", borderRadius: 10, border: "1.5px solid #fecaca", background: "#fef2f2", color: "#991b1b", fontSize: 13, fontWeight: 700, cursor: "pointer", fontFamily: "inherit", boxShadow: "0 2px 8px rgba(0,0,0,0.07)", transition: "box-shadow 0.15s, transform 0.15s, background 0.15s, border-color 0.15s" }}
                  onMouseEnter={e => { e.currentTarget.style.background = "#fee2e2"; e.currentTarget.style.boxShadow = "0 4px 16px rgba(0,0,0,0.12)"; e.currentTarget.style.transform = "translateY(-1px)"; e.currentTarget.style.borderColor = "#fca5a5"; }}
                  onMouseLeave={e => { e.currentTarget.style.background = "#fef2f2"; e.currentTarget.style.boxShadow = "0 2px 8px rgba(0,0,0,0.07)"; e.currentTarget.style.transform = "none"; e.currentTarget.style.borderColor = "#fecaca"; }}>
                  Unlock Full Forms
                </button>
              </div>
            </div>
          );
        })()}

        {step === "upload" && (() => {
          if (freeExhausted) {
            return (
              <div style={{ maxWidth: 560, margin: "0 auto", textAlign: "center", padding: "60px 24px" }}>
                <div style={{ width: 72, height: 72, borderRadius: 20, background: "rgba(230,0,122,0.08)", display: "flex", alignItems: "center", justifyContent: "center", margin: "0 auto 20px" }}>
                  <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#E61B84" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><polyline points="17 11 12 6 7 11"/><line x1="12" y1="6" x2="12" y2="18"/></svg>
                </div>
                <h2 style={{ fontSize: 26, fontWeight: 700, color: "#0f172a", marginBottom: 10 }}>Free Limit Reached</h2>
                <p style={{ fontSize: 15, color: "#64748b", marginBottom: 28, lineHeight: 1.6 }}>You've used all your free downloads. Upgrade to keep generating ACORD packages.</p>
                <button onClick={onShowUpgrade}
                  style={{ padding: "13px 36px", background: "#E61B84", color: "#fff", border: "none", borderRadius: 10, fontSize: 15, fontWeight: 700, cursor: "pointer", boxShadow: "0 4px 14px rgba(230,0,122,0.3)" }}
                  onMouseEnter={e => { e.currentTarget.style.background = "#C0157A"; e.currentTarget.style.transform = "translateY(-1px)"; }}
                  onMouseLeave={e => { e.currentTarget.style.background = "#E61B84"; e.currentTarget.style.transform = "none"; }}>
                  Upgrade Now
                </button>
                <div style={{ marginTop: 16 }}>
                  <button onClick={goToDashboard} style={{ background: "none", border: "none", color: "#94a3b8", fontSize: 13, cursor: "pointer", textDecoration: "underline" }}>Back to Dashboard</button>
                </div>
              </div>
            );
          }
          const ps = user?.payment_status;
          const uploadBlocked = ps === "soft_locked" || ps === "suspended" || ps === "archived";
          const blockMsg = ps === "archived" ? "Account archived - contact support to restore." : ps === "suspended" ? "Account suspended - restore billing to continue." : ps === "soft_locked" ? "Account Disabled - please update your billing." : null;
          const activeBtn = files.length && !loading && !uploadBlocked;
          return (
            <div style={{ maxWidth: 640, margin: "0 auto", padding: "0 4px" }}>
              {/* Header */}
              <div style={{ textAlign: "center", marginBottom: 28 }}>
                <div style={{ display: "inline-block", fontSize: 10, fontWeight: 700, color: "#991b1b", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 10, padding: "3px 10px", background: "#fef2f2", border: "1px solid #fecaca", borderRadius: 20 }}>New Submission</div>
                <h2 style={{ fontSize: 26, fontWeight: 700, color: "#0f172a", margin: "0 0 6px", letterSpacing: "-0.3px" }}>Upload Documents</h2>
                <p style={{ fontSize: 13.5, color: "#64748b", margin: 0, lineHeight: 1.5 }}>Dec pages, loss runs, schedules, quotes - PDFs, images, or ZIP archives</p>
              </div>

              {/* Blocked banner */}
              {uploadBlocked && (
                <div style={{ background: "#fef2f2", border: "1px solid #fecaca", borderRadius: 10, padding: "11px 16px", marginBottom: 20, fontSize: 13, color: "#dc2626", textAlign: "center" }}>{blockMsg}</div>
              )}

              {/* Drop zone card */}
              <div style={{
                background: "#fff",
                borderRadius: 20,
                boxShadow: "0 2px 8px rgba(0,0,0,0.06), 0 8px 32px rgba(0,0,0,0.09), 0 0 0 1px rgba(0,0,0,0.04)",
                overflow: "hidden",
                padding: "8px",
              }}>
                {/* Drop target */}
                <input ref={fileInputRef} type="file" accept=".pdf,.zip,.jpg,.jpeg,.png,.bmp,.tiff,.webp,.txt,application/pdf,application/zip,image/*,text/plain" multiple disabled={uploadBlocked} onChange={e => setFiles(prev => [...prev, ...Array.from(e.target.files)])} style={{ position: "absolute", width: 1, height: 1, opacity: 0, overflow: "hidden", clip: "rect(0,0,0,0)", whiteSpace: "nowrap" }} />
                <label
                  onDragOver={handleDragOver}
                  onDragLeave={handleDragLeave}
                  onDrop={handleDrop}
                  onClick={() => { if (!uploadBlocked) fileInputRef.current?.click(); }}
                  style={{
                    display: "block",
                    position: "relative",
                    padding: dragging ? "52px 32px" : "44px 32px",
                    border: `2px dashed ${dragging ? "#E61B84" : "#e2e8f0"}`,
                    borderRadius: 14,
                    background: dragging ? "rgba(230,0,122,0.03)" : "#fafbfc",
                    transition: "all 0.18s ease",
                    cursor: uploadBlocked ? "not-allowed" : "pointer",
                    textAlign: "center",
                  }}
                >
                  {/* Upload icon - SVG, no emoji */}
                  <div style={{ marginBottom: 16, display: "flex", justifyContent: "center" }}>
                    <svg width="44" height="44" viewBox="0 0 44 44" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ opacity: dragging ? 1 : 0.55, transition: "opacity 0.18s" }}>
                      <rect width="44" height="44" rx="12" fill={dragging ? "rgba(230,0,122,0.1)" : "#f1f5f9"} />
                      <path d="M22 28V18M22 18L18 22M22 18L26 22" stroke={dragging ? "#E61B84" : "#64748b"} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                      <path d="M14 31h16" stroke={dragging ? "#E61B84" : "#64748b"} strokeWidth="2" strokeLinecap="round"/>
                    </svg>
                  </div>

                  <p style={{ fontSize: 15, fontWeight: 600, color: "#1e293b", margin: "0 0 4px" }}>
                    Drag & drop files
                  </p>
                  <p style={{ fontSize: 13.5, color: "#64748b", margin: "0 0 12px" }}>
                    or <span style={{ color: "#E61B84", fontWeight: 600, textDecoration: "underline" }}>click to browse</span>
                  </p>
                  <p style={{ fontSize: 11.5, color: "#94a3b8", margin: 0, letterSpacing: "0.01em" }}>
                    PDFs · Images (JPG, PNG, BMP, TIFF) · ZIP archives
                  </p>
                </label>

                {/* File list */}
                {files.length > 0 && (
                  <div style={{ padding: "0 16px 16px", marginTop: -4 }}>
                    <div style={{ display: "flex", flexDirection: "column", gap: 6, maxHeight: 196, overflowY: "auto", paddingRight: 2 }}>
                      {files.map((f, i) => {
                        const isZip = f.name.toLowerCase().endsWith(".zip");
                        const isImg = f.type?.startsWith("image/");
                        const ext = f.name.split(".").pop()?.toUpperCase() || "FILE";
                        return (
                          <div key={i} style={{ display: "flex", alignItems: "center", gap: 10, padding: "9px 12px", background: "#f8fafc", border: "1px solid #e9edf2", borderRadius: 9, fontSize: 13 }}>
                            {/* Type badge */}
                            <span style={{
                              flexShrink: 0, width: 32, height: 32, borderRadius: 7,
                              background: isZip ? "#fef3c7" : isImg ? "#ede9fe" : "#dbeafe",
                              color: isZip ? "#92400e" : isImg ? "#6d28d9" : "#1d4ed8",
                              fontSize: 9, fontWeight: 800, letterSpacing: "0.04em",
                              display: "flex", alignItems: "center", justifyContent: "center",
                            }}>{isZip ? "ZIP" : isImg ? ext : "PDF"}</span>
                            <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "#1e293b", fontWeight: 500 }}>{f.name}</span>
                            <span style={{ fontSize: 11, color: "#94a3b8", flexShrink: 0 }}>{(f.size / 1024).toFixed(0)} KB</span>
                            <button
                              onClick={() => setFiles(prev => prev.filter((_, j) => j !== i))}
                              style={{ background: "none", border: "none", cursor: "pointer", color: "#cbd5e1", fontSize: 14, padding: "2px 4px", lineHeight: 1, borderRadius: 4, transition: "color 0.15s" }}
                              onMouseEnter={e => e.currentTarget.style.color = "#E61B84"}
                              onMouseLeave={e => e.currentTarget.style.color = "#cbd5e1"}
                              title="Remove file"
                            >✕</button>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}

                {/* CTA */}
                <div style={{ padding: "8px 8px 8px" }}>
                  <button
                    onClick={handleUpload}
                    disabled={!files.length || loading || uploadBlocked}
                    style={{
                      width: "100%",
                      padding: "13px 0",
                      borderRadius: 12,
                      border: "none",
                      background: loading ? "#cc006e" : "#E61B84",
                      color: "#fff",
                      fontSize: 14.5,
                      fontWeight: 700,
                      cursor: activeBtn ? "pointer" : "not-allowed",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      gap: 10,
                      boxShadow: "0 4px 18px rgba(230,0,122,0.32)",
                      transition: "all 0.18s ease",
                      letterSpacing: "0.01em",
                      opacity: uploadBlocked ? 0.6 : 1,
                    }}
                    onMouseEnter={e => { if (!loading) e.currentTarget.style.background = "#cc006e"; }}
                    onMouseLeave={e => { if (!loading) e.currentTarget.style.background = "#E61B84"; }}
                  >
                    {loading && (
                      <svg width="16" height="16" viewBox="0 0 16 16" fill="none" style={{ animation: "spin 0.8s linear infinite", flexShrink: 0 }}>
                        <circle cx="8" cy="8" r="6" stroke="rgba(255,255,255,0.35)" strokeWidth="2.5"/>
                        <path d="M8 2a6 6 0 0 1 6 6" stroke="#fff" strokeWidth="2.5" strokeLinecap="round"/>
                      </svg>
                    )}
                    {loading ? "Analyzing..." : files.length > 0 ? `Analyze ${files.length > 1 ? files.length + " Files" : "File"}` : "Analyze File"}
                  </button>
                </div>
              </div>
            </div>
          );
        })()}

        {step === "stopped" && (
          <div className="modal-step">
            <div className="stop-banner stop-hard">
              <div className="stop-icon"></div>
              <h2 className="stop-title">Submission Blocked - Minimum Fields Missing</h2>
              <p className="stop-subtitle">ACORD 125 cannot be generated. Missing:</p>
            </div>
            <div className="stop-fields">{hardStops.map((f, i) => <div key={i} className="stop-field-item"><span className="stop-field-icon"></span><span>{f}</span></div>)}</div>
            <p className="stop-advice">Upload documents that include these fields, then try again.</p>
            <button className="btn btn-modal-primary" onClick={resetToUpload}>← Upload New Documents</button>
          </div>
        )}

        {integrityBusy && (
          <ProcessStageOverlay
            stages={["Reviewing your documents...", "Re-assessing submission package..."]}
            advanceAfter={2000}
            tagline="Checking which documents belong together."
          />
        )}

        {step === "integrity_review" && integrity && !integrityBusy && (
          <div className="modal-step modal-step-wide">
            {/* Workstream 6 9.1 - next-step guidance for the integrity review screen. */}
            <div style={{ marginBottom: 14 }}>
              <NextStepBanner text="Ready to Review Documents" />
            </div>
            {/* ── Banner - light magenta to match the homepage hero ── */}
            <div style={{
              background: "rgba(230,27,132,0.07)",
              border: "1.5px solid rgba(230,27,132,0.25)",
              borderRadius: 12,
              padding: "18px 22px",
              marginBottom: 20,
            }}>
              <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700, color: "#9d0f5a" }}>
                Submission Integrity Review Needed
              </h2>
              <div style={{ display: "flex", alignItems: "center", gap: 8, margin: "8px 0 0" }}>
                <IntegritySeverityChip severity="hard_stop" />
                <span style={{ fontWeight: 700, fontSize: 13.5, color: "#9d0f5a" }}>Possible multiple submissions</span>
              </div>
              <p style={{ margin: "6px 0 0", fontSize: 13.5, color: "#b01868", lineHeight: 1.55 }}>
                These documents may belong to different insureds. You can continue, or separate them into individual submissions.
              </p>
            </div>

            {integrity.detected_entities?.length > 0 && (
              <div style={{ marginBottom: 16 }}>
                <div style={{ fontWeight: 600, color: "#1e293b", marginBottom: 6, fontSize: 13 }}>Detected entities</div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                  {integrity.detected_entities.map((e, i) => (
                    <span key={i} style={{ background: "rgba(230,27,132,0.08)", color: "#9d0f5a", border: "1px solid rgba(230,27,132,0.22)", borderRadius: 999, padding: "4px 14px", fontSize: 13, fontWeight: 600 }}>{e}</span>
                  ))}
                </div>
              </div>
            )}

            {integrity.reasons?.length > 0 && (
              <div style={{ marginBottom: 16, background: "#fff", border: "1px solid #e2e8f0", borderRadius: 8, padding: "12px 16px" }}>
                <div style={{ fontWeight: 600, color: "#334155", marginBottom: 6, fontSize: 13 }}>Why this was flagged</div>
                {integrity.reasons.map((r, i) => (
                  <div key={i} style={{ color: "#475569", fontSize: 13, padding: "2px 0" }}>• {r}</div>
                ))}
              </div>
            )}

            <div style={{ marginBottom: 8 }}>
              <div style={{ fontWeight: 600, color: "#1e293b", marginBottom: 10, fontSize: 13 }}>
                Uploaded documents - check any that don't belong, then remove them
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {(integrity.documents || []).map((d) => {
                  const checked = removeDocIds.has(d.doc_id);
                  return (
                    <label key={d.doc_id} style={{
                      display: "flex", alignItems: "center", gap: 12,
                      background: checked ? "rgba(230,27,132,0.07)" : "#fff",
                      border: `1.5px solid ${checked ? "rgba(230,27,132,0.35)" : "#e2e8f0"}`,
                      borderRadius: 9, padding: "10px 14px", cursor: "pointer",
                      transition: "background 0.15s, border-color 0.15s",
                    }}>
                      <input
                        type="checkbox"
                        checked={checked}
                        disabled={integrityBusy}
                        onChange={() => {
                          setRemoveDocIds((prev) => {
                            const next = new Set(prev);
                            if (next.has(d.doc_id)) next.delete(d.doc_id); else next.add(d.doc_id);
                            return next;
                          });
                        }}
                      />
                      <span style={{ background: "#eef2ff", color: "#4338ca", borderRadius: 6, padding: "2px 8px", fontSize: 11, fontWeight: 600, textTransform: "uppercase", flexShrink: 0 }}>
                        {String(d.doc_type || "unknown").replace(/_/g, " ")}
                      </span>
                      <span style={{ flex: 1, minWidth: 0 }}>
                        <span style={{ display: "block", fontWeight: 600, color: "#1e293b", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{d.filename}</span>
                        <span style={{ display: "block", fontSize: 12, color: "#64748b" }}>Insured: {d.applicant}{d.fein ? ` · FEIN ••${d.fein}` : ""}</span>
                      </span>
                    </label>
                  );
                })}
              </div>
            </div>

            {/* ── Actions ── all buttons equal width, single row (no wrap) ── */}
            <div style={{ display: "flex", flexWrap: "nowrap", gap: 10, marginTop: 24, alignItems: "stretch" }}>
              <button
                className={`btn ${removeDocIds.size > 0 ? "btn-modal-primary" : "btn-modal-secondary"}`}
                disabled={integrityBusy || removeDocIds.size === 0}
                onClick={() => handleResolveIntegrity("remove_documents")}
                style={{ flex: "1 1 0", minWidth: 0, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}
              >
                {`Remove selected${removeDocIds.size ? ` (${removeDocIds.size})` : ""}`}
              </button>
              <button
                className="btn btn-modal-primary"
                disabled={integrityBusy}
                onClick={() => handleResolveIntegrity("continue_anyway")}
                style={{ flex: "1 1 0", minWidth: 0, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}
              >
                Continue anyway
              </button>
              {(integrity?.detected_entities?.length || 0) > 1 && (
                <button
                  className="btn btn-modal-primary"
                  disabled={integrityBusy}
                  onClick={() => handleResolveIntegrity("create_separate_submissions")}
                  title="Split these documents into one submission per insured"
                  style={{ flex: "1 1 0", minWidth: 0, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}
                >
                  Create separate submissions
                </button>
              )}
              <button
                className="btn btn-modal-primary"
                disabled={integrityBusy}
                onClick={resetToUpload}
                style={{ flex: "1 1 0", minWidth: 0, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}
              >
                Upload new documents
              </button>
            </div>

            <p style={{ fontSize: 12, color: "#94a3b8", marginTop: 14, lineHeight: 1.5 }}>
              "Continue anyway" records your acknowledgment and proceeds with all documents as a single submission.
              {(integrity?.detected_entities?.length || 0) > 1 && " “Create separate submissions” splits the documents into one submission per insured and continues with the first. Each is saved and counted as a separate submission."}
            </p>
          </div>
        )}

        {step === "recommendations" && (
          <div className="modal-step modal-step-wide">
            <div className="step-header">
              <h2 className="step-title" style={{ color: "#1e293b" }}>Select Forms to Generate</h2>
              <p className="step-subtitle">Select the forms you need, then generate all at once.</p>
            </div>
            {/* Workstream 6 §9.1 - "what to do next" guidance. Never says "Ready"
                while hard stops remain (acceptance criteria). */}
            <div style={{ marginBottom: 14 }}>
              {(() => {
                // Reflects the live hard-stop + warning counts (they update as the
                // user reclassifies/excludes docs). Only "Ready" once both are zero.
                const h = hardStops.length, w = softStops.length;
                let text;
                if (h > 0 && w > 0) text = `Review ${h} hard stop${h !== 1 ? "s" : ""} and ${w} warning${w !== 1 ? "s" : ""} below before generating forms`;
                else if (h > 0)     text = `Review ${h} hard stop${h !== 1 ? "s" : ""} below before generating forms`;
                else if (w > 0)     text = `Review ${w} warning${w !== 1 ? "s" : ""} below before generating forms`;
                else                text = "Ready to Generate Forms";
                return <NextStepBanner text={text} />;
              })()}
            </div>
            {/* Submission Integrity status (Beta Report §4.1): advisory banner for
                all statuses (HIGH / MEDIUM / LOW). LOW/MEDIUM expose an on-demand
                "Review / separate documents" action; nothing is force-paused. */}
            {renderIntegrityStatus()}
            <div className="doc-summary">
              <div className="doc-summary-title">DOCUMENTS PROCESSED</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {docSummary.map((d, i) => {
                  const docType = d.doc_type || "unknown";
                  const label = d.doc_type_label || docType.replace(/_/g, " ");
                  const conf = d.doc_type_confidence || "";
                  const isUnknown = docType === "unknown";
                  const needsReview = isUnknown || conf === "low" || d.doc_type_source === "filename";
                  const excluded = !!d.excluded;
                  const supportingOnly = !!d.supporting_only;
                  const busy = reclassDocId && reclassDocId === d.doc_id;
                  // Any in-flight reclassify re-runs _finalize_pipeline and persists
                  // the whole session. Concurrent calls for different docs both load
                  // the same snapshot before either persists → last-write-wins drops
                  // the first change. Block other docs' controls while one is active.
                  const anyReclassBusy = reclassDocId !== null;
                  const reviewBusy = reviewLoadingId === d.doc_id;
                  const confColor = conf === "high" ? "#16a34a" : conf === "medium" ? "#d97706" : "#dc2626";
                  // Figure 3 relabel: this pill answers "how sure are we about the
                  // document TYPE" - a different question from issue severity or
                  // suggested-value confidence. Give it its own words so a bare
                  // "HIGH/MEDIUM/LOW" can never be mistaken for one of those.
                  const confLabel = conf === "high" ? "Strong match" : conf === "medium" ? "Likely match" : "Needs review";
                  return (
                    <div key={d.doc_id || i} style={{
                      display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap",
                      padding: "8px 12px", borderRadius: 8,
                      border: `1px solid ${needsReview ? "rgba(230,27,132,0.35)" : "rgba(230,27,132,0.15)"}`,
                      background: excluded ? "#f8fafc" : (needsReview ? "rgba(230,27,132,0.05)" : "#fff"),
                      opacity: excluded ? 0.6 : 1,
                    }}>
                      <span className="doc-type-badge" style={{ textTransform: "capitalize" }}>{label}</span>
                      {d.doc_type_overridden
                        ? <span title="You set this type" style={{ fontSize: 10, color: "#2563eb", fontWeight: 600 }}>you set this</span>
                        : conf && <span title={`How confident Primble is about this document's type: ${confLabel}`} style={{ fontSize: 10, color: confColor, fontWeight: 700 }}>{confLabel}</span>}
                      <span className="doc-filename" style={{ flex: 1, minWidth: 120, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{d.filename}</span>
                      {excluded && <span style={{ fontSize: 10, color: "#64748b", fontStyle: "italic" }}>excluded from scoring</span>}
                      {supportingOnly && !excluded && <span title="Facts contribute, but this document is never treated as the primary source" style={{ fontSize: 10, color: "#64748b", fontStyle: "italic" }}>supporting only</span>}

                      {/* Manual correction (Beta Report §4.2): change type, exclude/include */}
                      {availableDocTypes.length > 0 && !excluded && (
                        <div style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                          <select
                            value={docType}
                            disabled={anyReclassBusy}
                            onChange={(e) => { if (e.target.value && e.target.value !== docType) handleReclassify(d.doc_id, "set_type", e.target.value, "type"); }}
                            title="Correct the document type"
                            style={{ fontSize: 12, padding: "3px 6px", borderRadius: 6, border: `1px solid ${busy && reclassBusyBtn === "type" ? "#E61B84" : "#cbd5e1"}`, background: "#fff", color: "#334155", cursor: anyReclassBusy ? "wait" : "pointer", opacity: busy && reclassBusyBtn === "type" ? 0.7 : 1 }}
                          >
                            {availableDocTypes.map((t) => (
                              <option key={t.value} value={t.value}>{t.label}</option>
                            ))}
                          </select>
                          {busy && reclassBusyBtn === "type" && (
                            <span style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 11, color: "#E61B84", fontWeight: 600 }}>
                              <span style={{ width: 10, height: 10, border: "2px solid rgba(230,27,132,0.25)", borderTopColor: "#E61B84", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite", flexShrink: 0 }} />
                              Updating...
                            </span>
                          )}
                        </div>
                      )}
                      <button
                        type="button"
                        disabled={anyReclassBusy}
                        onClick={() => handleReclassify(d.doc_id, excluded ? "include" : "exclude", null, "toggle")}
                        title={excluded ? "Include this document in scoring" : "Exclude this document from scoring"}
                        style={{ fontSize: 11, padding: "3px 8px", borderRadius: 6, border: "1px solid #cbd5e1", background: "#fff", color: "#475569", cursor: anyReclassBusy ? "wait" : "pointer", display: "inline-flex", alignItems: "center", gap: 4, minWidth: 58, justifyContent: "center" }}
                      >
                        {busy && reclassBusyBtn === "toggle"
                          ? <><span style={{ width: 10, height: 10, border: "2px solid #cbd5e1", borderTopColor: "#E61B84", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" }} />{excluded ? "Include" : "Exclude"}</>
                          : (excluded ? "Include" : "Exclude")}
                      </button>
                      {/* "Include as supporting document only" (Beta Report §4.2 item #6) */}
                      {!excluded && (
                        <button
                          type="button"
                          disabled={anyReclassBusy}
                          onClick={() => handleReclassify(d.doc_id, supportingOnly ? "include" : "supporting_only", null, "supporting")}
                          title={supportingOnly ? "Use this document as a normal source again" : "Include facts but never treat as the primary source"}
                          style={{ fontSize: 11, padding: "3px 8px", borderRadius: 6, border: `1px solid ${supportingOnly ? "#E61B84" : "#cbd5e1"}`, background: supportingOnly ? "rgba(230,27,132,0.06)" : "#fff", color: supportingOnly ? "#9d0f5a" : "#475569", cursor: anyReclassBusy ? "wait" : "pointer", display: "inline-flex", alignItems: "center", gap: 4, justifyContent: "center" }}
                        >
                          {busy && reclassBusyBtn === "supporting"
                            ? <><span style={{ width: 10, height: 10, border: "2px solid #cbd5e1", borderTopColor: "#E61B84", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" }} />{supportingOnly ? "Supporting only ✓" : "Supporting only"}</>
                            : (supportingOnly ? "Supporting only ✓" : "Supporting only")}
                        </button>
                      )}
                      {/* "Review extracted data" (Beta Report §4.2 item #6) */}
                      <button
                        type="button"
                        disabled={reviewBusy}
                        onClick={() => handleReviewData(d.doc_id)}
                        title="See the data Primble extracted from this document"
                        style={{ fontSize: 11, padding: "3px 8px", borderRadius: 6, border: "1px solid #cbd5e1", background: "#fff", color: "#475569", cursor: reviewBusy ? "wait" : "pointer", display: "inline-flex", alignItems: "center", gap: 4, justifyContent: "center" }}
                      >
                        {reviewBusy
                          ? <><span style={{ width: 10, height: 10, border: "2px solid #cbd5e1", borderTopColor: "#E61B84", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" }} />Review data</>
                          : "Review data"}
                      </button>
                    </div>
                  );
                })}
              </div>
              {docSummary.some(d => (d.doc_type || "unknown") === "unknown" || d.doc_type_confidence === "low") && (
                <div style={{ fontSize: 11, color: "#92400e", marginTop: 6 }}>
                  Some documents need review. Set the correct type so scoring and form recommendations use them - or exclude documents that don't belong.
                </div>
              )}
            </div>

            {/* Cross-document value reconciliation picker (Beta Report §4.3 + §5).
                Surfaces every materially-different value between documents — Gross
                Sales plus identity/policy fields (name, FEIN, dates, entity type,
                address, carrier) — with each document's value as a choice plus a
                custom-value option. Consistent fields are silent (no action). */}
            {underwriting?.fields?.some(f => f.status === "conflict" || f.status === "confirmed") && (
              <div className="doc-summary" style={{ marginTop: 12 }}>
                <div className="doc-summary-title">DATA CONSISTENCY</div>
                {underwritingBusy !== null && (
                  <div style={{ fontSize: 11, color: "#64748b", marginBottom: 6 }}>
                    Applying your confirmation and updating the forms - please confirm the next item once this finishes.
                  </div>
                )}
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  {underwriting.fields.filter(f => f.status === "conflict" || f.status === "confirmed").map((f) => {
                    const isConflict = f.status === "conflict";
                    const isConfirmed = f.status === "confirmed";
                    const busy = underwritingBusy === f.fact_key;
                    // Any in-flight confirm blocks every row's controls. Each
                    // confirm re-runs the pipeline server-side and replaces the
                    // whole underwriting object; letting a second row fire while
                    // the first is still applying raced the responses and dropped
                    // confirmations (the "click multiple, none applied" lag).
                    const rowDisabled = busy || underwritingBusy !== null;
                    const picked = underwritingPicks[f.fact_key] ?? "";
                    const formsLabel = (f.forms || []).map(x => x.replace("ACORD_", "ACORD ")).join(", ");
                    return (
                      <div key={f.fact_key} style={{
                        padding: "10px 12px", borderRadius: 8,
                        border: "1px solid rgba(230,27,132,0.2)",
                        background: "rgba(230,27,132,0.04)",
                      }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                          <span style={{ fontWeight: 600, color: "#1e293b", fontSize: 13 }}>{f.label}</span>
                          {isConflict && <span style={{ fontSize: 10, fontWeight: 700, color: "#b45309", textTransform: "uppercase" }}>Values differ - confirm</span>}
                          {isConflict && f.confidence && CONFIDENCE_META[f.confidence] && (
                            <span style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.3, color: CONFIDENCE_META[f.confidence].color, background: CONFIDENCE_META[f.confidence].bg, border: `1px solid ${CONFIDENCE_META[f.confidence].border}`, borderRadius: 6, padding: "1px 7px" }}>
                              Confidence: {CONFIDENCE_META[f.confidence].label}
                            </span>
                          )}
                          {isConfirmed && <span style={{ fontSize: 11, fontWeight: 600, color: "#16a34a" }}>Confirmed: {f.confirmed_value}{formsLabel ? ` - applied to ${formsLabel}` : ""}</span>}
                          {f.status === "consistent" && <span style={{ fontSize: 11, color: "#16a34a" }}>Consistent: {f.values?.[0]?.display}</span>}
                        </div>

                        {/* Source attribution: which document each value came from (§4.3 item 4) */}
                        {(isConflict || f.status === "consistent") && (
                          <div style={{ marginTop: 6, display: "flex", flexDirection: "column", gap: 4 }}>
                            {f.values.map((v, vi) => (
                              <div key={vi} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: "#475569", flexWrap: "wrap" }}>
                                {isConflict && (
                                  <input
                                    type="radio"
                                    name={`uw-${f.fact_key}`}
                                    checked={picked === v.display}
                                    onChange={() => setUnderwritingPicks(p => ({ ...p, [f.fact_key]: v.display }))}
                                    disabled={rowDisabled}
                                  />
                                )}
                                <span style={{ fontWeight: 600, color: "#0f172a" }}>{v.display}</span>
                                <span style={{ color: "#94a3b8" }}>from</span>
                                <span style={{ color: "#334155" }}>
                                  {v.sources.map(s => s.filename).join(", ")}
                                </span>
                                {isConflict && f.suggested_value != null && v.display === f.suggested_value && (
                                  <span style={{ fontSize: 9.5, fontWeight: 700, color: "#0369a1", background: "#f0f9ff", border: "1px solid #bae6fd", borderRadius: 10, padding: "1px 7px" }}>Suggested</span>
                                )}
                              </div>
                            ))}
                          </div>
                        )}

                        {/* Figure 3 "apply to all": another field shows the exact same
                            disagreement from the exact same documents - confirming
                            here resolves it there too, so the producer only has to
                            answer once instead of repeating the same address/value. */}
                        {isConflict && f.linked_fields?.length > 0 && (
                          <div style={{ marginTop: 6, fontSize: 11, color: "#0369a1", fontStyle: "italic" }}>
                            Also applies to: {f.linked_fields.map(l => l.label).join(", ")}
                          </div>
                        )}

                        {/* Confirm control (§4.3 item 5) */}
                        {isConflict && (
                          <div style={{ marginTop: 8, display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                            <input
                              type="text"
                              value={picked}
                              disabled={rowDisabled}
                              placeholder="…or type a value"
                              onChange={(e) => setUnderwritingPicks(p => ({ ...p, [f.fact_key]: e.target.value }))}
                              style={{ fontSize: 12, padding: "4px 8px", borderRadius: 6, border: "1px solid #cbd5e1", width: 160 }}
                            />
                            <button
                              type="button"
                              disabled={rowDisabled || !picked}
                              onClick={() => handleConfirmUnderwriting(f.fact_key, picked)}
                              style={{ fontSize: 12, fontWeight: 600, padding: "5px 12px", borderRadius: 6, border: "none", background: picked && !rowDisabled ? "#2563eb" : "#cbd5e1", color: "#fff", cursor: picked && !rowDisabled ? "pointer" : "not-allowed" }}
                            >
                              {busy ? "Applying…" : "Confirm & apply to forms"}
                            </button>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {(hardStops.length > 0 || softStops.length > 0) && (
              <div className="stops-row">
                {hardStops.length > 0 && (
                  <div className="stops-banner stops-hard">
                    <div className="stops-title">Hard Stops - Required Before Submission - Caps Your SQS at 60</div>
                    {groupedIssues?.hard_stops?.length > 0 ? (
                      groupedIssues.hard_stops.map((c, i) => (
                        c.count > 1 ? (
                          // Cluster header - same size/color as a Warnings cluster
                          // header (10.5px, muted), since a cluster is a cluster
                          // regardless of which banner it sits under.
                          <div key={i}>
                            <CollapsibleSection title={`${c.cluster} (${c.count})`} defaultOpen titleSize={10.5} headerColor="#64748b">
                              {c.items.map((it, j) => <IssueLine key={j} message={it.message} className="stop-item stop-item-hard" />)}
                            </CollapsibleSection>
                            {clusterStatusControl(c)}
                          </div>
                        ) : (
                          <div key={i}>
                            <IssueLine message={c.primary_message} className="stop-item stop-item-hard" />
                            {clusterStatusControl(c)}
                          </div>
                        )
                      ))
                    ) : (
                      hardStops.map((s, i) => <IssueLine key={i} message={s} className="stop-item stop-item-hard" />)
                    )}
                  </div>
                )}
                {softStops.length > 0 && (
                  <div className="stops-banner stops-soft">
                    <div className="stops-title">Warnings - Caps Your SQS at 85</div>
                    {groupedIssues?.important?.length > 0 && (
                      <div className="warning-tier-section warning-important-section">
                        <div className="warning-important-label">Important</div>
                        {groupedIssues.important.map((c, i) => (
                          <IssueLine
                            key={i}
                            message={c.count > 1 ? `${c.primary_message} (+${c.count - 1} related)` : c.primary_message}
                            className="stop-item stop-item-soft"
                          />
                        ))}
                      </div>
                    )}
                    {groupedIssues?.warnings ? (
                      ["required", "recommended", "binder_followup"].map((tier) => {
                        const clusters = groupedIssues.warnings[tier] || [];
                        if (!clusters.length) return null;
                        const totalCount = clusters.reduce((n, c) => n + c.count, 0);
                        return (
                          <div key={tier} className="warning-tier-section">
                            {/* Level 2: tier header - the most prominent label inside the
                                Warnings banner (12px), clearly smaller than the 13px
                                banner title above it, but clearly bigger than the
                                cluster headers nested inside it. */}
                            <CollapsibleSection
                              title={`${groupedIssues.tier_labels[tier]} (${totalCount})`}
                              defaultOpen={tier === "required"}
                              titleSize={12}
                              headerColor="#0f172a"
                            >
                              {clusters.map((c, i) => (
                                c.count > 1 ? (
                                  // Level 3: cluster header - the short category name
                                  // (e.g. "Financial figure conflicts"), never the raw
                                  // issue sentence, so it stays a compact label instead
                                  // of a wall of upper-cased text. Sized clearly below
                                  // the 12px tier header above it.
                                  <div key={i}>
                                    <CollapsibleSection title={`${c.cluster} (${c.count})`} titleSize={10.5} headerColor="#64748b">
                                      {c.items.map((it, j) => <IssueLine key={j} message={it.message} className="stop-item stop-item-soft" />)}
                                    </CollapsibleSection>
                                    {clusterStatusControl(c)}
                                  </div>
                                ) : (
                                  <div key={i}>
                                    <IssueLine message={c.primary_message} className="stop-item stop-item-soft" />
                                    {clusterStatusControl(c)}
                                  </div>
                                )
                              ))}
                            </CollapsibleSection>
                          </div>
                        );
                      })
                    ) : (
                      softStops.map((s, i) => <IssueLine key={i} message={s} className="stop-item stop-item-soft" />)
                    )}
                  </div>
                )}
              </div>
            )}
            {canProceedWithWarning && warningStops.length > 0 && (
              <div className="stops-banner stops-warning" style={{ margin: "8px 0", padding: "12px 16px", background: "rgba(230,27,132,0.07)", border: "1.5px solid rgba(230,27,132,0.25)", borderRadius: 8 }}>
                <div className="stops-title" style={{ color: "#9d0f5a", fontWeight: 600, marginBottom: 6 }}>
                  Incomplete Submission - Review Before Generating
                </div>
                {warningStops.map((s, i) => (
                  <div key={i} className="stop-item" style={{ color: "#b01868", fontSize: 13, marginBottom: 2 }}>- {s}</div>
                ))}
                <div style={{ marginTop: 10, fontSize: 13, color: "#9d0f5a" }}>
                  This submission is missing information typically required for property coverage. Forms can still be generated, but the underwriter may request additional data.
                </div>
              </div>
            )}
            {/* DOUBTS-Workstream4 (Brent): producer-answerable "Why are you
                marketing this account?" - answering re-runs recommendations so
                ACORD 101 escalates to its correct tier; the answer also flows
                into later SQS scoring. Optional / non-blocking. Same magenta
                surface as the panels above; fully fluid for mobile/iOS. */}
            {recommendations.length > 0 && (
              <div style={{ margin: "8px 0", padding: "12px 16px", background: "rgba(230,27,132,0.07)", border: "1.5px solid rgba(230,27,132,0.25)", borderRadius: 8 }}>
                <div style={{ color: "#9d0f5a", fontWeight: 600, fontSize: 13.5, marginBottom: 10 }}>
                  Why are you marketing this account? (optional)
                </div>
                <select
                  value={marketingReason}
                  disabled={marketingBusy}
                  onChange={(e) => {
                    const v = e.target.value;
                    setMarketingReason(v);
                    setMarketingOther("");
                    if (v) handleMarketingReason(v);
                  }}
                  style={{ width: "100%", maxWidth: 420, boxSizing: "border-box", padding: "9px 12px", fontSize: 13, color: "#1e293b", background: "#fff", border: "1px solid rgba(230,27,132,0.3)", borderRadius: 8, cursor: marketingBusy ? "default" : "pointer" }}
                >
                  <option value="">Select a reason...</option>
                  {MARKETING_REASON_OPTIONS.map((o) => <option key={o} value={o}>{o}</option>)}
                </select>
                {MARKETING_ADVERSE_REASONS.has(marketingReason) && (
                  <div style={{ marginTop: 8, fontSize: 12, color: "#9d0f5a", lineHeight: 1.45 }}>
                    Adds ACORD 101 (Additional Remarks) to your recommended forms for an underwriter narrative.
                  </div>
                )}
                {marketingReason === "Other" && (
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 8, maxWidth: 420 }}>
                    <input
                      type="text"
                      value={marketingOther}
                      disabled={marketingBusy}
                      onChange={(e) => setMarketingOther(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" && marketingOther.trim()) {
                          e.preventDefault();
                          handleMarketingReason(`Other: ${marketingOther.trim()}`);
                        }
                      }}
                      placeholder="Please explain..."
                      style={{ flex: "1 1 200px", minWidth: 0, boxSizing: "border-box", padding: "7px 11px", fontSize: 12.5, color: "#1e293b", background: "#fff", border: "1px solid rgba(230,27,132,0.3)", borderRadius: 7, outline: "none" }}
                    />
                    <button
                      type="button"
                      disabled={marketingBusy || !marketingOther.trim()}
                      onClick={() => handleMarketingReason(`Other: ${marketingOther.trim()}`)}
                      style={{ flexShrink: 0, padding: "7px 16px", fontSize: 12.5, fontWeight: 600, color: "#fff", border: "none", borderRadius: 7, background: (marketingBusy || !marketingOther.trim()) ? "#e9a8cb" : "#E61B84", cursor: (marketingBusy || !marketingOther.trim()) ? "default" : "pointer" }}
                    >
                      Save
                    </button>
                  </div>
                )}
                {marketingBusy && (
                  <div style={{ marginTop: 8, fontSize: 12, color: "#9d0f5a", display: "flex", alignItems: "center", gap: 7 }}>
                    <span style={{ width: 11, height: 11, border: "2px solid rgba(230,27,132,0.25)", borderTopColor: "#E61B84", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite", flexShrink: 0 }} />
                    Updating recommendations...
                  </div>
                )}
              </div>
            )}
            {tier2Score !== null && (
              <div className="tier2-bar">
                <div className="tier2-header"><span className="tier2-label">Submission Readiness</span><span className="tier2-score" style={{ color: barColor(tier2Score) }}>{tier2Score}%</span></div>
                <div className="metric-bar"><div className="metric-fill" style={{ width: `${tier2Score}%`, background: barColor(tier2Score) }} /></div>
                {tier2Missing.length > 0 && <div className="tier2-missing">Missing: {tier2Missing.join(" · ")}</div>}
              </div>
            )}
            <div className="form-selection-list" style={{ opacity: marketingBusy ? 0.55 : 1, transition: "opacity 0.18s ease" }}>
              <div className="form-selection-header">
                <span style={{ display: "inline-flex", alignItems: "center" }}>
                  <span className="form-selection-title">Recommended Forms</span>
                  {marketingBusy && (
                    <span style={{ display: "inline-flex", alignItems: "center", gap: 5, marginLeft: 8, fontSize: 11, fontWeight: 600, color: "#9d0f5a" }}>
                      <svg width="13" height="13" viewBox="0 0 16 16" fill="none" style={{ animation: "spin 0.8s linear infinite", flexShrink: 0 }}>
                        <circle cx="8" cy="8" r="6" stroke="rgba(230,27,132,0.25)" strokeWidth="2.5" />
                        <path d="M8 2a6 6 0 0 1 6 6" stroke="#E61B84" strokeWidth="2.5" strokeLinecap="round" />
                      </svg>
                      Updating...
                    </span>
                  )}
                </span>
                <span className="form-selection-hint">{checkedFormIds.size} selected</span>
              </div>
              {/* Account context (Beta Report §7.2 item 5): business class /
                  account type / coverage goals that the list is filtered by. */}
              {accountProfile && (accountProfile.business_class_label || accountProfile.coverage_goals?.length > 0) && (
                <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 6, margin: "0 2px 10px", fontSize: 11, color: "#64748b" }}>
                  <span style={{ fontWeight: 600, color: "#475569" }}>Tailored for:</span>
                  {accountProfile.business_class_label && (
                    <span style={{ padding: "2px 9px", borderRadius: 20, background: "rgba(230,27,132,0.07)", color: "#be185d", fontWeight: 600 }}>{accountProfile.business_class_label}</span>
                  )}
                  {accountProfile.account_type_label && (
                    <span style={{ padding: "2px 9px", borderRadius: 20, background: "#f1f5f9", color: "#475569", fontWeight: 600 }}>{accountProfile.account_type_label}</span>
                  )}
                  {accountProfile.transaction_type && (
                    <span style={{ padding: "2px 9px", borderRadius: 20, background: "#f1f5f9", color: "#475569", fontWeight: 600 }}>{accountProfile.transaction_type === "renewal" ? "Renewal" : "New Business"}</span>
                  )}
                  {accountProfile.coverage_goals?.length > 0 && (
                    <span>Lines: {accountProfile.coverage_goals.join(" · ")}</span>
                  )}
                </div>
              )}
              {groupedRecs.map((group) => {
                const meta = TIER_META[group.tier] || TIER_META.recommended;
                return (
                  <div key={group.tier} className="form-tier-group" style={{ marginTop: 12 }}>
                    {/* Tier header (Required / Recommended / Optional / Needs Confirmation) */}
                    <div style={{ display: "flex", alignItems: "center", gap: 8, margin: "0 2px 7px", flexWrap: "wrap" }}>
                      <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: "0.04em", textTransform: "uppercase", color: meta.color, background: meta.bg, padding: "2px 10px", borderRadius: 20 }}>{meta.label}</span>
                      <span style={{ fontSize: 11, color: "#94a3b8" }}>{group.items.length} form{group.items.length !== 1 ? "s" : ""} · {meta.hint}</span>
                    </div>
                    {group.items.map((rec) => {
                      const pct = Math.round((rec.confidence || 0) * 100);
                      return (
                        <div key={rec.form_id} className={`form-select-row ${checkedFormIds.has(rec.form_id) ? "form-row-checked" : ""}`}>
                          <label className="form-select-checkbox-label">
                            <input type="checkbox" checked={checkedFormIds.has(rec.form_id)} onChange={() => toggleForm(rec.form_id)} className="form-select-checkbox" />
                            <div className="form-select-info" style={rec.profile_relevant === false ? { opacity: 0.82 } : undefined}>
                              <div className="form-select-name">{rec.form_name}</div>
                              <div className="form-select-meta">
                                <span
                                  className="confidence-badge"
                                  title={rec.fields_total > 0
                                    ? `Match ${pct}% · ${rec.fields_filled} of ${rec.fields_total} required fields found in your documents`
                                    : `Match score: how strongly your documents indicate this form is relevant`}
                                  style={{ cursor: "help" }}
                                >
                                  Match {pct}%
                                </span>
                                <span className="form-select-reason">{rec.reason_label || rec.reason || rec.trigger_reason}</span>
                                {rec.relevance_label && (
                                  <span style={{ fontSize: 11, fontWeight: 600, fontStyle: "normal", color: "#be185d", background: "rgba(230,27,132,0.07)", padding: "1px 8px", borderRadius: 20 }}>
                                    {rec.relevance_label}
                                  </span>
                                )}
                              </div>
                              {rec.is_source_document && (
                                <div style={{ fontSize: 11, color: "#b45309", marginTop: 3 }}>
                                  Source document detected - generate a clean copy only if you need one.
                                </div>
                              )}
                              {rec.profile_relevant === false && rec.relevance_reason && (
                                <div style={{ fontSize: 11, color: "#64748b", marginTop: 3 }}>
                                  {rec.relevance_reason}
                                </div>
                              )}
                            </div>
                          </label>
                        </div>
                      );
                    })}
                  </div>
                );
              })}
            </div>
            {extraForms.length > 0 && (
              <div className="add-forms-section">
                <button className="btn btn-modal-secondary btn-small" onClick={() => setShowAddForms(v => !v)}>
                  {showAddForms ? "▲ Hide" : "▼ Add more ACORD forms"} ({extraForms.length} available)
                </button>
                {showAddForms && (
                  <div className="extra-forms-list">
                    {extraForms.map(f => {
                      const pct = Math.round((f.confidence || 0) * 100);
                      const tooltipText = f.fields_total > 0
                        ? `${f.fields_filled} of ${f.fields_total} required fields found in your document`
                        : f.description || "";
                      return (
                        <div key={f.form_id} className={`form-select-row ${checkedFormIds.has(f.form_id) ? "form-row-checked" : ""}`}>
                          <label className="form-select-checkbox-label">
                            <input type="checkbox" checked={checkedFormIds.has(f.form_id)} onChange={() => toggleForm(f.form_id)} className="form-select-checkbox" />
                            <div className="form-select-info">
                              <div className="form-select-name">{f.form_name}</div>
                              <div className="form-select-meta">
                                {pct > 0 && (
                                  <span
                                    className="confidence-badge confidence-badge--extra"
                                    title={tooltipText}
                                    style={{ cursor: "help" }}
                                  >
                                    Match {pct}%
                                  </span>
                                )}
                                {(f.reason || f.description) && (
                                  <span className="form-select-reason">{f.reason || f.description}</span>
                                )}
                              </div>
                            </div>
                          </label>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            )}
            <button className="btn btn-modal-primary btn-block btn-large" onClick={handleGenerateAll} disabled={loading || checkedFormIds.size === 0}>
{loading ? "Generating..." : `Generate ${checkedFormIds.size} Form${checkedFormIds.size !== 1 ? "s" : ""} Now`}
            </button>
          </div>
        )}

        {step === "editor" && (
          <div className={`editor-layout editor-layout-fullpage${!sidebarOpen ? " sidebar-closed" : ""}`}>
            <div className="editor-sidebar" style={{ background: "#fff", borderRight: "1px solid #e2e8f0", padding: 0, gap: 0 }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "10px 14px", borderBottom: "1px solid #f1f5f9", background: "#fafbfc" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 9, minWidth: 0 }}>
                  <span style={{ display: "flex", alignItems: "center", justifyContent: "center", width: 32, height: 32, borderRadius: 9, background: "rgba(230,27,132,0.1)", flexShrink: 0 }}>
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#E61B84" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                      <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
                    </svg>
                  </span>
                  <div style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
                    <span style={{ fontSize: 12, fontWeight: 700, color: "#1e293b", letterSpacing: "0.01em" }}>SQS &amp; Actions</span>
                    {/* Workstream 6 9.1 - next-step status, dynamic: flips to "Ready to
                        Send Submission" (green) at package SQS 90+, else "Ready to Download". */}
                    <span style={{ fontSize: 11, fontWeight: 600, lineHeight: 1.3, color: (packageSqs?.package_sqs_score ?? 0) >= 90 ? "#059669" : "#94a3b8", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {(packageSqs?.package_sqs_score ?? 0) >= 90 ? "Ready to Send Submission" : "Ready to Download Forms"}
                    </span>
                  </div>
                </div>
                <button className="sidebar-close-btn" onClick={() => setSidebarOpen(false)} title="Hide panel">✕</button>
              </div>
              <div style={{ padding: "14px 14px 6px" }}>
                {(() => {
                  // Shared row renderer so the collapsed (current only) and expanded
                  // (all forms) views render identically. Prev/Next removed - navigation
                  // is via this list plus the PDF viewer's «Form 1/2» arrows.
                  const renderRow = (fid) => {
                    const fd = generatedForms[fid]; const sq = fd?.sqs;
                    const isActive = activeFormId === fid;
                    return (
                      <div key={fid} onClick={() => setActiveFormId(fid)}
                        style={{ padding: "7px 9px", borderRadius: 7, cursor: "pointer", border: `1px solid ${isActive ? "#E61B84" : "transparent"}`, background: isActive ? "rgba(230,0,122,0.05)" : "transparent", transition: "all 0.15s" }}
                        onMouseEnter={e => { if (!isActive) e.currentTarget.style.background = "#f8fafc"; }}
                        onMouseLeave={e => { if (!isActive) e.currentTarget.style.background = "transparent"; }}>
                        <div style={{ fontSize: 12, fontWeight: 600, color: isActive ? "#E61B84" : "#1e293b" }}>
                          {fd?.form_name || fid}
                          {signedForms.has(fid) && <span style={{ color: "#10b981", fontSize: 10 }}> (signed)</span>}
                          {pdfLoading[fid] && <span style={{ color: "#f59e0b", fontSize: 10 }}> (loading)</span>}
                        </div>
                        {sq && <div style={{ display: "flex", gap: 6, marginTop: 2 }}><span style={{ fontSize: 10, fontWeight: 700, color: gradeColor(sq.grade) }}>{sq.sqs_score} {sq.grade}</span><span style={{ fontSize: 10, color: "#94a3b8" }}>{sq.tier}</span></div>}
                      </div>
                    );
                  };
                  return (
                    <>
                      <button type="button" onClick={() => setGeneratedFormsOpen(o => !o)} aria-expanded={generatedFormsOpen}
                        style={{ display: "flex", alignItems: "center", gap: 6, width: "100%", background: "none", border: "none", padding: "3px 0", marginBottom: 6, cursor: "pointer", fontFamily: "inherit", textAlign: "left" }}>
                        <span style={{ fontSize: 8, color: "#94a3b8", transform: generatedFormsOpen ? "rotate(90deg)" : "none", transition: "transform 0.15s", display: "inline-block", flexShrink: 0 }}>▶</span>
                        <span style={{ fontSize: 10, fontWeight: 700, color: "#94a3b8", letterSpacing: "0.06em", textTransform: "uppercase", display: "inline-flex", alignItems: "center", gap: 3 }}>
                          Generated Forms
                          <InfoTip text="The ACORD forms generated for this submission. Click a form to open it." />
                        </span>
                        <span style={{ marginLeft: "auto", fontSize: 11, fontWeight: 700, color: "#E61B84", background: "rgba(230,0,122,0.08)", padding: "1px 7px", borderRadius: 20, flexShrink: 0 }}>{formIdList.length}</span>
                      </button>
                      {generatedFormsOpen ? (
                        <div style={{ display: "flex", flexDirection: "column", gap: 2, maxHeight: 220, overflowY: "auto" }}>
                          {formIdList.map(renderRow)}
                        </div>
                      ) : (
                        activeFormId && renderRow(activeFormId)
                      )}
                    </>
                  );
                })()}
              </div>

              {activeSqs && (
                <>
                  <div style={{ padding: "0 14px 12px" }}>

                    {/* ── Pinned Individual Form Score: only this card stays pinned to the top
                        of the panel while it scrolls. The sticky wrapper is white so content
                        scrolling under blends into the side gutters; the pink card sits inside.
                        Works in the mobile drawer and on iOS Safari (sticky, no prefix). ── */}
                    <div style={{ position: "sticky", top: 0, zIndex: 5, background: "#fff", paddingTop: 6, paddingBottom: 8, marginBottom: 10, borderBottom: "1px solid #f1f5f9", boxShadow: "0 6px 6px -6px rgba(15,23,42,0.08)" }}>
                      <div style={{ background: "#fff", border: "1px solid #e2e8f0", borderRadius: 8, padding: "10px 12px" }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                          <div style={{ width: 44, height: 44, borderRadius: "50%", background: gradeColor(activeSqs.grade), display: "flex", alignItems: "center", justifyContent: "center", fontSize: 20, fontWeight: 800, color: "#fff", flexShrink: 0 }}>{activeSqs.grade}</div>
                          <div style={{ flex: 1, minWidth: 0 }}>
                            <div style={{ display: "flex", alignItems: "baseline", gap: 4, flexWrap: "wrap" }}>
                              <span style={{ fontSize: 28, fontWeight: 800, lineHeight: 1, color: gradeColor(activeSqs.grade) }}>{activeSqs.sqs_score}</span>
                              <span style={{ fontSize: 11, color: "#94a3b8" }}>/100</span>
                              <span style={{ fontSize: 10, fontWeight: 700, padding: "2px 7px", borderRadius: 20, color: "#fff", marginLeft: 4, background: { green: "#10b981", yellow: "#f59e0b", orange: "#f97316", red: "#ef4444" }[activeSqs.tier_color] || "#94a3b8" }}>{activeSqs.tier}</span>
                            </div>
                            <div style={{ fontSize: 10, color: "#94a3b8", marginTop: 2, textTransform: "uppercase", letterSpacing: "0.04em", fontWeight: 600 }}>Individual Form Score</div>
                          </div>
                        </div>
                      </div>
                    </div>

                    {/* ── Form Completion (current-form, pink; bold black %, right-justified) ── */}
                    {activeSqs.match_score != null && (
                      <div style={{ background: "#fff", border: "1px solid #e2e8f0", borderRadius: 7, padding: "7px 10px", marginBottom: 10 }}>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                          <span style={{ fontSize: 11, fontWeight: 700, color: "#000", display: "inline-flex", alignItems: "center", gap: 3 }}>Form Completion<InfoTip text="Share of this form's fields filled from your documents." /></span>
                          <span style={{ fontSize: 12, fontWeight: 800, color: "#000" }}>{activeSqs.match_score}%</span>
                        </div>
                      </div>
                    )}

                    {/* ── Quality Fill Rate (current-form, pink; bar + % black, hint in tooltip) ── */}
                    {activeSqs.confidence_fill_rate != null && (
                      <div style={{ background: "#fff", border: "1px solid #e2e8f0", borderRadius: 7, padding: "7px 10px", marginBottom: 10 }}>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
                          <span style={{ fontSize: 11, fontWeight: 700, color: "#000", display: "inline-flex", alignItems: "center", gap: 3 }}>Quality Fill Rate<InfoTip text="Filled fields weighted by confidence. Producer edits = 100%, AI high = 85%, AI low = 50%." /></span>
                          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                            {activeSqs.fill_rate != null && activeSqs.fill_rate !== activeSqs.confidence_fill_rate && (
                              <span style={{ fontSize: 10, color: "#94a3b8", textDecoration: "line-through" }}>{activeSqs.fill_rate}%</span>
                            )}
                            <span style={{ fontSize: 12, fontWeight: 800, color: "#000" }}>{activeSqs.confidence_fill_rate}%</span>
                          </div>
                        </div>
                        <div style={{ height: 4, background: "#e2e8f0", borderRadius: 2, overflow: "hidden" }}>
                          <div style={{ height: "100%", width: `${activeSqs.confidence_fill_rate}%`, background: "#000", borderRadius: 2, transition: "width 0.6s ease" }} />
                        </div>
                      </div>
                    )}

                    {/* ── Session delta ── */}
                    {packageSqs && packageSqs.sqs_history?.length > 1 && (() => {
                      // Prefer the genuine initial_extract baseline (matches
                      // backend delta computation); fall back to first entry.
                      const baseline = packageSqs.sqs_history.find(h => h?.stage === "initial_extract")
                        || packageSqs.sqs_history[0];
                      // §6.2: detect an arq_remediated stage in history so we can
                      // show fill rate before/after for form completion tracking.
                      const arqEntry = packageSqs.sqs_history.find(h => h?.stage === "arq_remediated");
                      const fillBefore = baseline?.avg_fill_rate;
                      const fillAfter  = arqEntry?.avg_fill_rate;
                      const fillDelta  = (fillBefore != null && fillAfter != null) ? fillAfter - fillBefore : null;
                      return (
                        <div style={{ background: "#fff", border: "1px solid #e2e8f0", borderRadius: 7, padding: "6px 10px", marginBottom: 10 }}>
                          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                            <span style={{ fontSize: 14 }}></span>
                            <div>
                              <span style={{ fontSize: 11, fontWeight: 700, color: packageSqs.delta_this_session >= 0 ? "#059669" : "#dc2626" }}>
                                {packageSqs.delta_this_session >= 0 ? "+" : ""}{packageSqs.delta_this_session} pts this session
                              </span>
                              <div style={{ fontSize: 10, color: "#94a3b8" }}>
                                Started at {baseline?.score ?? "-"} → now {packageSqs.package_sqs_score}
                              </div>
                            </div>
                          </div>
                          {/* §6.2 / Req 4: form completion delta after ARQ remediation */}
                          {fillDelta != null && (
                            <div style={{ marginTop: 5, paddingTop: 5, borderTop: "1px solid #e2e8f0", display: "flex", alignItems: "center", gap: 4 }}>
                              <span style={{ width: 9, height: 9, background: "rgb(187,247,208)", border: "1px solid #86efac", borderRadius: 2, display: "inline-block", flexShrink: 0 }} />
                              <span style={{ fontSize: 10, color: "#047857", fontWeight: 600 }}>
                                Quality Fill Rate: {fillBefore}% → {fillAfter}%
                                {fillDelta > 0 ? ` (+${fillDelta}% after client answers)` : " (unchanged after client answers)"}
                              </span>
                            </div>
                          )}
                        </div>
                      );
                    })()}

                    {/* ── Per-form breakdown bars ── */}
                    {/* doc-sourced = driven by uploaded documents, not form field edits */}
                    {(() => {
                      const docSourced = new Set(["property_integrity", "loss_history_alignment", "narrative_quality"]);
                      return (
                        <div style={{ background: "#fff", border: "1px solid #e2e8f0", borderRadius: 8, padding: "10px 12px", marginBottom: 10, display: "flex", flexDirection: "column", gap: 8 }}>
                          {Object.entries(activeSqs.breakdown || {}).map(([key, val]) => {
                            // umbrella_limit_adequacy is null when no umbrella is in the
                            // submission (§6.5 - N/A, not a perfect score).
                            const isNA = val === null || val === undefined;
                            // Weight (and the doc-sourced note) moved off the row into the tooltip.
                            const tip = `Weight: ${SQS_WEIGHTS[key] || 0}% of the score.${docSourced.has(key) ? " Sourced from uploaded documents - editing form fields won't change this." : ""}`;
                            return (
                            <div key={key}>
                              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, marginBottom: 3 }}>
                                <span style={{ color: "#000", display: "inline-flex", alignItems: "center", gap: 3 }}>
                                  {SQS_LABELS[key] || key}
                                  <InfoTip text={tip} />
                                </span>
                                {isNA
                                  ? <span style={{ fontWeight: 700, color: "#94a3b8", fontSize: 10 }}>N/A</span>
                                  : <span style={{ fontWeight: 700, color: barColor(val) }}>{val}%</span>}
                              </div>
                              <div style={{ height: 5, background: "#e2e8f0", borderRadius: 3, overflow: "hidden" }}>
                                {!isNA && <div style={{ height: "100%", width: `${val}%`, background: barColor(val), borderRadius: 3, transition: "width 0.6s ease" }} />}
                              </div>
                            </div>
                            );
                          })}
                        </div>
                      );
                    })()}

                    {/* ── TOTAL PACKAGE SCORE (collapsible, white; score + LOB shown in header) ── */}
                    {packageSqs && (
                      <CollapsibleSection
                        resetKey={activeFormId}
                        title="Total Package Score"
                        tooltip="Rates the whole submission - all forms, documents, and cross-form checks. A weighted sum of the 6 pillars, not an average of form scores, so it can differ from any single form's score."
                        titleRight={<>
                          {packageSqs.lob && packageSqs.lob !== "generic" && (
                            <span style={{ fontSize: 9, fontWeight: 700, background: "rgba(230,0,122,0.08)", color: "#E61B84", borderRadius: 20, padding: "1px 6px", textTransform: "capitalize" }}>{packageSqs.lob}</span>
                          )}
                          <span style={{ fontSize: 16, fontWeight: 800, color: gradeColor(packageSqs.package_sqs_score >= 90 ? "A" : packageSqs.package_sqs_score >= 80 ? "B" : packageSqs.package_sqs_score >= 70 ? "C" : packageSqs.package_sqs_score >= 60 ? "D" : "F") }}>{packageSqs.package_sqs_score}</span>
                          <span style={{ fontSize: 9, color: "#94a3b8" }}>/100</span>
                        </>}
                      >
                        {/* §6.1: distinguish SQS from per-form Match % (shown directly, no "hints" label) */}
                        <div style={{ fontSize: 9, background: "rgba(0,0,0,0.035)", borderRadius: 5, padding: "5px 7px", marginBottom: 8, display: "flex", flexDirection: "column", gap: 3 }}>
                          <div style={{ display: "flex", gap: 6 }}>
                            <span style={{ fontWeight: 700, color: "#475569", minWidth: 44, flexShrink: 0 }}>SQS</span>
                            <span style={{ color: "#94a3b8", lineHeight: 1.4 }}>Submission completeness and underwriting readiness</span>
                          </div>
                          <div style={{ display: "flex", gap: 6 }}>
                            <span style={{ fontWeight: 700, color: "#475569", minWidth: 44, flexShrink: 0 }}>Match %</span>
                            <span style={{ color: "#94a3b8", lineHeight: 1.4 }}>How strongly uploaded documents fit each form (shown per form, not here)</span>
                          </div>
                          <div style={{ display: "flex", gap: 6 }}>
                            <span style={{ fontWeight: 700, color: "#475569", minWidth: 44, flexShrink: 0 }}>Score</span>
                            <span style={{ color: "#94a3b8", lineHeight: 1.4 }}>Weighted sum of the 6 pillars - not a plain average. Weights shown as (%) on each row below.</span>
                          </div>
                          {/* Category-label explainer shown once here, not repeated under each pillar. */}
                          <div style={{ color: "#94a3b8", lineHeight: 1.4, marginTop: 6, paddingTop: 6, borderTop: "1px solid rgba(0,0,0,0.09)", fontStyle: "italic" }}>
                            Labels show how complete each category is based on available information. The overall pillar score may also include data quality, conflicts, and validation rules.
                          </div>
                        </div>
                        <div style={{ display: "flex", flexDirection: "column", gap: 5, marginBottom: 18 }}>
                          {Object.entries(packageSqs.pillars || {}).map(([key, val]) => {
                            // umbrella_limit_adequacy is null when not applicable (§6.5).
                            const isNA = val === null || val === undefined;
                            const catsRaw = packageSqs.category_breakdown?.[key];
                            // _rollup (if present from an older payload) is metadata, not a sub-row.
                            const cats = catsRaw
                              ? Object.fromEntries(Object.entries(catsRaw).filter(([k]) => k !== "_rollup"))
                              : null;
                            const hasCats = cats && Object.keys(cats).length > 0;
                            const expanded = expandedPillars.has(key);
                            const toggle = () => setExpandedPillars(prev => {
                              const n = new Set(prev);
                              n.has(key) ? n.delete(key) : n.add(key);
                              return n;
                            });
                            return (
                            <div key={key}>
                              <div onClick={hasCats ? toggle : undefined} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 10, marginBottom: 2, cursor: hasCats ? "pointer" : "default" }}>
                                <span style={{ color: "#000", display: "inline-flex", alignItems: "center", gap: 3 }}>
                                  {hasCats && <span style={{ display: "inline-block", width: 9, fontSize: 7, color: "#94a3b8", transform: expanded ? "rotate(90deg)" : "none", transition: "transform 0.15s" }}>▶</span>}
                                  {PACKAGE_PILLAR_LABELS[key] || key}
                                  <InfoTip text={`Weight: ${SQS_WEIGHTS[key] || 0}% of the package score.`} />
                                </span>
                                {isNA
                                  ? <span title="No umbrella in this submission" style={{ fontWeight: 700, color: "#94a3b8", fontSize: 9 }}>N/A</span>
                                  : <span style={{ fontWeight: 700, color: barColor(val) }}>{val}%</span>}
                              </div>
                              <div style={{ height: 3, background: "#e2e8f0", borderRadius: 2, overflow: "hidden" }}>
                                {!isNA && <div style={{ height: "100%", width: `${val}%`, background: barColor(val), borderRadius: 2 }} />}
                              </div>
                              {expanded && hasCats && (
                                <div style={{ margin: "4px 0 6px 12px", display: "flex", flexDirection: "column", gap: 3 }}>
                                  {Object.entries(cats).map(([ck, cv]) => {
                                    // Status word instead of a raw % so users don't try to
                                    // average sub-rows into the weighted pillar headline.
                                    const comp = catCompleteness(cv?.score);
                                    return (
                                      <div key={ck} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 9.5, gap: 8 }}>
                                        <span style={{ color: "#475569" }}>{cv?.label || ck}</span>
                                        <span style={{ color: comp.color, fontWeight: 700, whiteSpace: "nowrap" }}>{comp.label}</span>
                                      </div>
                                    );
                                  })}
                                </div>
                              )}
                            </div>
                            );
                          })}
                        </div>

                        {/* §6.1 item 4 - positive scoring signals credited (collapsible, hide when empty) */}
                        {packageSqs.positive_signals?.length > 0 && (
                          <CollapsibleSection resetKey={activeFormId} titleSize={9} title="Positive Signals" tooltip="Strengths detected that support underwriting readiness.">
                            <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                              {packageSqs.positive_signals.map((s, i) => {
                                const active = provCard?.group === "signal" && provCard.key === s.key;
                                return (
                                  <span key={i} role="button" tabIndex={0} data-provtrigger="1"
                                    onClick={(e) => openProv("signal", s.key, e.currentTarget)}
                                    onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openProv("signal", s.key, e.currentTarget); } }}
                                    style={{ fontSize: 9.5, fontWeight: 600, color: "#047857", background: "#ecfdf5", border: `1px solid ${active ? "#047857" : "#a7f3d0"}`, borderRadius: 10, padding: "1px 7px", cursor: "pointer" }}>{s.label || s.key}</span>
                                );
                              })}
                            </div>
                          </CollapsibleSection>
                        )}

                        {/* §6.3 - narrative quality broken down by component (collapsible, hide when empty) */}
                        {packageSqs.narrative_components && Object.keys(packageSqs.narrative_components).length > 0 && (
                          <CollapsibleSection resetKey={activeFormId} titleSize={9} title="Narrative Components" tooltip="Narrative elements detected as present or missing in the submission.">
                            <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                              {Object.entries(packageSqs.narrative_components).map(([ck, present]) => {
                                const active = provCard?.group === "narrative" && provCard.key === ck;
                                return (
                                  <span key={ck} role="button" tabIndex={0} data-provtrigger="1"
                                    onClick={(e) => openProv("narrative", ck, e.currentTarget)}
                                    onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openProv("narrative", ck, e.currentTarget); } }}
                                    style={{
                                      fontSize: 9, fontWeight: 600, borderRadius: 10, padding: "1px 7px", cursor: "pointer",
                                      color: present ? "#047857" : "#64748b",
                                      background: present ? "#ecfdf5" : "#ffffff",
                                      border: `1px solid ${active ? (present ? "#047857" : "#64748b") : (present ? "#a7f3d0" : "#cbd5e1")}`,
                                    }}>
                                    {NARRATIVE_COMPONENT_LABELS[ck] || ck}
                                  </span>
                                );
                              })}
                            </div>
                          </CollapsibleSection>
                        )}

                        {/* §6.5 - umbrella state, follow-form, underlying-limit warnings (collapsible) */}
                        {packageSqs.umbrella_state && packageSqs.umbrella_state !== "not_applicable" && (
                          <CollapsibleSection resetKey={activeFormId} titleSize={9} title="Umbrella" tooltip="Umbrella/excess status, follow-form and underlying-limit notes.">
                            <div role="button" tabIndex={0} data-provtrigger="1"
                              onClick={(e) => openProv("umbrella", "state", e.currentTarget)}
                              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openProv("umbrella", "state", e.currentTarget); } }}
                              style={{ fontSize: 9.5, fontWeight: 600, color: "#334155", marginBottom: 3, cursor: "pointer", textDecoration: provCard?.group === "umbrella" ? "underline" : "none", width: "fit-content" }}>{UMBRELLA_STATE_LABEL[packageSqs.umbrella_state] || packageSqs.umbrella_state}</div>
                            {/* §6.5 item 4: follow-form status - green when confirmed, amber when unknown. */}
                            {packageSqs.follow_form?.message && (
                              packageSqs.follow_form.status === "follow_form_confirmed" ? (
                                <div style={{ fontSize: 9.5, color: "#15803d", lineHeight: 1.4 }}>{packageSqs.follow_form.message}</div>
                              ) : (
                                <div style={{ fontSize: 9.5, color: "#b45309", background: "#fffbeb", border: "1px solid #fde68a", borderRadius: 5, padding: "2px 6px", lineHeight: 1.4 }}>{packageSqs.follow_form.message}</div>
                              )
                            )}
                            {packageSqs.umbrella_warnings?.map((w, i) => (
                              <div key={i} style={{ fontSize: 9.5, color: "#b45309", background: "#fffbeb", border: "1px solid #fde68a", borderRadius: 5, padding: "2px 6px", marginTop: 3, lineHeight: 1.4 }}>{w}</div>
                            ))}
                            {/* §6.5 item 5: persistent review items, de-duplicated against the follow-form line. */}
                            {packageSqs.review_items?.filter((it) => it?.action && it.action !== packageSqs.follow_form?.message).map((it, i) => (
                              <div key={`ri-${i}`} style={{ fontSize: 9.5, color: "#b45309", background: "#fffbeb", border: "1px solid #fde68a", borderRadius: 5, padding: "2px 6px", marginTop: 3, lineHeight: 1.4 }}>{it.action}</div>
                            ))}
                          </CollapsibleSection>
                        )}

                        {/* §6.4 - loss-history evidence state (collapsible; state + note on expand) */}
                        {packageSqs.loss_history_state && (
                          <CollapsibleSection resetKey={activeFormId} titleSize={9} title="Loss History" tooltip="Loss-run evidence state for this submission.">
                            <div role="button" tabIndex={0} data-provtrigger="1"
                              onClick={(e) => openProv("loss_history", "state", e.currentTarget)}
                              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openProv("loss_history", "state", e.currentTarget); } }}
                              style={{ fontSize: 9.5, fontWeight: 600, cursor: "pointer", width: "fit-content", textDecoration: provCard?.group === "loss_history" ? "underline" : "none", color: packageSqs.loss_history_state === "loss_history_conflicting" || packageSqs.loss_history_state === "loss_runs_do_not_match" ? "#dc2626" : (packageSqs.loss_history_state === "no_information" ? "#b45309" : "#334155") }}>{LOSS_HISTORY_STATE_LABEL[packageSqs.loss_history_state] || packageSqs.loss_history_state}</div>
                            {packageSqs.loss_history_state_client_label && (
                              <div style={{ fontSize: 8.5, color: "#94a3b8", marginTop: 2, textTransform: "uppercase", letterSpacing: 0.3 }}>{packageSqs.loss_history_state_client_label}</div>
                            )}
                            {packageSqs.loss_history_state === "no_information" && (
                              <div style={{ fontSize: 9.5, color: "#64748b", marginTop: 3, lineHeight: 1.4 }}>Request loss runs or have the client confirm via the questionnaire.</div>
                            )}
                          </CollapsibleSection>
                        )}

                        {/* §6.1 item 3 / §6.2 - evidence basis for notable facts (collapsible, hide when empty) */}
                        {packageSqs.evidence_labels && (() => {
                          const notable = Object.entries(packageSqs.evidence_labels).filter(([, lbl]) => EVIDENCE_LABEL_COLOR[lbl]);
                          if (!notable.length) return null;
                          return (
                            <CollapsibleSection resetKey={activeFormId} titleSize={9} title="Evidence Basis" tooltip="Where key facts came from - documents, narrative, or form entry.">
                              <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                                {notable.map(([fk, lbl]) => {
                                  const c = EVIDENCE_LABEL_COLOR[lbl];
                                  const active = provCard?.group === "evidence" && provCard.key === fk;
                                  return (
                                    <span key={fk} role="button" tabIndex={0} data-provtrigger="1"
                                      onClick={(e) => openProv("evidence", fk, e.currentTarget)}
                                      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openProv("evidence", fk, e.currentTarget); } }}
                                      style={{ fontSize: 9, fontWeight: 600, color: c.fg, background: c.bg, boxShadow: active ? `inset 0 0 0 1px ${c.fg}` : "none", borderRadius: 10, padding: "1px 7px", cursor: "pointer" }}>
                                      {fk.replace(/_/g, " ")}: {EVIDENCE_LABEL_DISPLAY[lbl] || lbl}
                                    </span>
                                  );
                                })}
                              </div>
                            </CollapsibleSection>
                          );
                        })()}
                        {/* Tier as a display-only "button"-styled pill (no click). */}
                        {packageSqs.tier && (
                          <div style={{ marginTop: 8, padding: "5px 8px", borderRadius: 7, fontSize: 10, fontWeight: 700, textAlign: "center", border: "1px solid #e2e8f0", background: "#fff", color: gradeColor(packageSqs.package_sqs_score >= 90 ? "A" : packageSqs.package_sqs_score >= 80 ? "B" : packageSqs.package_sqs_score >= 70 ? "C" : packageSqs.package_sqs_score >= 60 ? "D" : "F") }}>
                            {packageSqs.tier}
                          </div>
                        )}
                        {/* Figure 10: one fixed-position provenance popover for whichever
                            score component was clicked. Renders nothing when there is no
                            data to show. Escapes the sidebar overflow (position: fixed). */}
                        {provCard && (() => {
                          const data = buildProvenance(provCard.group, provCard.key, packageSqs);
                          return data ? <ProvenancePopover data={data} pos={provCard.pos} onClose={closeProv} /> : null;
                        })()}
                      </CollapsibleSection>
                    )}

                    {/* ── RECOMMENDATIONS (collapsible, white): Key Issues → Best Solutions →
                        active recommendation cards. Each sub-part hides itself when empty. ── */}
                    {(activeSqs.issues?.length > 0
                      || packageSqs?.top_recommendations?.length > 0
                      || activeSqs.risk_drivers?.length > 0
                      || activeSqs.recommendations?.length > 0) && (
                      <CollapsibleSection resetKey={activeFormId} title="Recommendations" tooltip="Prioritized issues and suggested fixes to raise the score.">

                        {/* Key Issues (renamed from Issues) - bullet list, hidden when empty */}
                        {activeSqs.issues?.length > 0 && (
                          <div style={{ marginBottom: 8 }}>
                            <div style={{ fontSize: 10, fontWeight: 700, color: "#000", marginBottom: 3 }}>Key Issues</div>
                            {activeSqs.issues.map((s, i) => <div key={i} style={{ fontSize: 11, color: "#000", padding: "1px 0" }}>• {s}</div>)}
                          </div>
                        )}

                        {/* Best Solutions (renamed from Top Recommendations) - numbered list */}
                        {packageSqs?.top_recommendations?.length > 0 && (
                          <div style={{ marginBottom: 8 }}>
                            <div style={{ fontSize: 10, fontWeight: 700, color: "#000", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 6 }}>Best Solutions</div>
                            {packageSqs.top_recommendations.map((r, i) => {
                              if (!r) return null;
                              // Backend may return either dict (package) or string (legacy).
                              if (typeof r === "string") {
                                return (
                                  <div key={i} style={{ display: "flex", alignItems: "flex-start", gap: 6, padding: "3px 0" }}>
                                    <span style={{ fontSize: 10, fontWeight: 700, color: "#E61B84", width: 16 }}>{i + 1}</span>
                                    <span style={{ flex: 1, fontSize: 11, color: "#000" }}>{r}</span>
                                  </div>
                                );
                              }
                              // Humanize any unmapped key. Mapped keys (incl. hard_stops_present) use PACKAGE_PILLAR_LABELS.
                              const pillarLabel = PACKAGE_PILLAR_LABELS[r.pillar] || (r.pillar ? String(r.pillar).replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase()) : "");
                              return (
                                <div key={i} style={{ padding: "4px 0", borderBottom: i < packageSqs.top_recommendations.length - 1 ? "1px solid #f1f5f9" : "none" }}>
                                  <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                                    <span style={{ fontSize: 10, fontWeight: 700, color: "#E61B84", width: 16 }}>{i + 1}</span>
                                    <span style={{ flex: 1, fontSize: 11, fontWeight: 700, color: "#000" }}>{pillarLabel}</span>
                                    {typeof r.score === "number" && r.pillar !== "hard_stops_present" && (
                                      <span style={{ fontSize: 11, fontWeight: 700, color: barColor(r.score) }}>{r.score}%</span>
                                    )}
                                  </div>
                                  {r.action && (
                                    <div style={{ fontSize: 11, color: "#334155", marginLeft: 22, marginTop: 2 }}>{r.action}</div>
                                  )}
                                </div>
                              );
                            })}
                          </div>
                        )}

                        {/* Best Solutions fallback (per-form risk drivers when no package top-recs) */}
                        {activeSqs.risk_drivers?.length > 0 && !packageSqs?.top_recommendations?.length && (
                          <div style={{ marginBottom: 8 }}>
                            <div style={{ fontSize: 10, fontWeight: 700, color: "#000", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 6 }}>Best Solutions</div>
                            {activeSqs.risk_drivers.map((d, i) => (
                              <div key={i} style={{ display: "flex", alignItems: "center", gap: 6, padding: "3px 0", borderBottom: i < activeSqs.risk_drivers.length - 1 ? "1px solid #f1f5f9" : "none" }}>
                                <span style={{ fontSize: 10, fontWeight: 700, color: "#E61B84", width: 16 }}>{i + 1}</span>
                                <span style={{ flex: 1, fontSize: 11, color: "#000" }}>{d.component}</span>
                                <span style={{ fontSize: 11, fontWeight: 700, color: barColor(d.score) }}>{d.score}%</span>
                              </div>
                            ))}
                          </div>
                        )}

                        {/* Active recommendation cards (fill-in / dismiss), below Best Solutions */}
                        {activeSqs.recommendations?.length > 0 && (
                          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                            {activeSqs.recommendations
                              .filter(r => !dismissedRecs.has(typeof r === "string" ? r : r.rec_id))
                              .map((rec, i) => (
                                <SidePanelRec
                                  key={typeof rec === "object" && rec !== null ? rec.rec_id : `legacy_${i}`}
                                  rec={rec}
                                  index={i}
                                  sqsScore={activeSqs.sqs_score}
                                  onDismiss={handleDismissRec}
                                  onAnswer={handleAnswerRec}
                                />
                              ))}
                          </div>
                        )}
                      </CollapsibleSection>
                    )}

                    {/* Cross-Form Validation - now in the same flow so its gap matches the sections above. */}
                    {crossIssues.length > 0 && (
                      <CollapsibleSection resetKey={activeFormId} title="Cross-Form Validation" tooltip="Checks that data agrees across the different ACORD forms.">
                        {/* Each validation is its own numbered row with the form chip(s) it affects. */}
                        {crossIssues.map((iss, i) => (
                          <div key={i} style={{ display: "flex", alignItems: "flex-start", gap: 6, padding: "5px 0", borderBottom: i < crossIssues.length - 1 ? "1px solid #f1f5f9" : "none" }}>
                            <span style={{ fontSize: 10, fontWeight: 700, color: "#E61B84", width: 16, flexShrink: 0, lineHeight: 1.5 }}>{i + 1}</span>
                            <div style={{ flex: 1, minWidth: 0 }}>
                              {Array.isArray(iss.forms) && iss.forms.length > 0 && (
                                <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginBottom: 3 }}>
                                  {iss.forms.map((f, fi) => (
                                    <span key={fi} style={{ fontSize: 9, fontWeight: 700, color: "#9d174d", background: "#fce7f3", border: "1px solid #f9a8d4", borderRadius: 10, padding: "0 6px", whiteSpace: "nowrap" }}>{String(f).replace(/_/g, " ")}</span>
                                  ))}
                                </div>
                              )}
                              <div style={{ fontSize: 12, color: "#000", lineHeight: 1.4 }}>{iss.message}</div>
                              {(() => { const iid = issueIdOf(iss); return (
                                <IssueStatusControl
                                  issueId={iid}
                                  status={issueStatuses.get(iid)?.status}
                                  meta={{ form_id: Array.isArray(iss.forms) ? iss.forms[0] : null, rule_code: iss.code, message: iss.message }}
                                  onSet={setIssueStatus}
                                />
                              ); })()}
                            </div>
                          </div>
                        ))}
                      </CollapsibleSection>
                    )}

                    {/* REVIEWED (renamed from Dismissed): session-wide answered/dismissed recs. Hidden when empty. */}
                    {dismissedRecDetails.size > 0 && (
                      <CollapsibleSection resetKey={activeFormId} title={`Reviewed (${dismissedRecDetails.size})`} tooltip="Recommendations you've already answered or dismissed.">
                        <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
                          {Array.from(dismissedRecDetails.entries()).map(([rid, d]) => (
                            <div key={rid} style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: 8, padding: "7px 10px" }}>
                              <div style={{ display: "flex", alignItems: "flex-start", gap: 6 }}>
                                <span style={{ fontSize: 11, color: "#475569", fontWeight: 600, lineHeight: 1.4, flex: 1, minWidth: 0, textDecoration: "line-through", textDecorationColor: "#cbd5e1" }}>{d.message}</span>
                                {d.impact > 0 && <span style={{ fontSize: 9.5, fontWeight: 700, color: "#10b981", background: "#dcfce7", border: "1px solid #86efac", borderRadius: 10, padding: "1px 6px", flexShrink: 0, whiteSpace: "nowrap" }}>+{d.impact} pts credited</span>}
                              </div>
                              {d.reason ? (
                                <div style={{ marginTop: 4, fontSize: 10, color: "#64748b", display: "flex", alignItems: "flex-start", gap: 4 }}>
                                  <span style={{ flexShrink: 0, color: "#94a3b8" }}>Reason:</span>
                                  <span style={{ fontStyle: "italic" }}>{d.reason}</span>
                                </div>
                              ) : (
                                <div style={{ marginTop: 4, fontSize: 10, color: "#94a3b8" }}>Dismissed without reason</div>
                              )}
                            </div>
                          ))}
                        </div>
                      </CollapsibleSection>
                    )}

                    {/* SENT QUESTIONNAIRES - moved under Reviewed so Send to Client and More
                        Actions sit together in the actions area below. Hidden when none. */}
                    {arqSessions?.length > 0 && (
                      <CollapsibleSection resetKey={activeFormId} title="Sent Questionnaires" tooltip="Client questionnaires you've sent and their responses.">
                        <ARQStatusPanel hideTitle arqSessions={arqSessions} token={token} onRefresh={refreshArqData} scoreImprovement={(() => { const _base = packageSqs?.sqs_history?.find(h => h?.stage === "initial_extract") || packageSqs?.sqs_history?.[0]; const _arq = packageSqs?.sqs_history?.find(h => h?.stage === "arq_remediated"); return (_base?.score != null && _arq?.score != null) ? _arq.score - _base.score : null; })()} />
                      </CollapsibleSection>
                    )}

                  </div>
                </>
              )}

              <div style={{ height: 1, background: "#f1f5f9", margin: "0 14px" }} />
              <div style={{ padding: "12px 14px 16px", display: "flex", flexDirection: "column", gap: 8 }}>

                {/* Primary CTA - Client-in-the-Loop™ */}
                <button onClick={handleOpenARQ} disabled={arqLoadingQ}
                  style={{ width: "100%", padding: "12px 16px", borderRadius: 14, border: "none", background: "linear-gradient(135deg, #E61B84 0%, #C0157A 100%)", color: "#fff", fontSize: 13, fontWeight: 700, cursor: arqLoadingQ ? "wait" : "pointer", fontFamily: "inherit", display: "flex", alignItems: "center", justifyContent: "center", gap: 8, opacity: arqLoadingQ ? 0.7 : 1, boxShadow: "0 4px 16px rgba(230,0,122,0.35), 0 1px 3px rgba(230,0,122,0.2)", letterSpacing: "0.02em", transition: "all 0.2s" }}
                  onMouseEnter={e => { if (!arqLoadingQ) { e.currentTarget.style.background = "linear-gradient(135deg, #C0157A 0%, #a30055 100%)"; e.currentTarget.style.boxShadow = "0 6px 20px rgba(230,0,122,0.45), 0 1px 3px rgba(230,0,122,0.2)"; e.currentTarget.style.transform = "translateY(-1px)"; } }}
                  onMouseLeave={e => { e.currentTarget.style.background = "linear-gradient(135deg, #E61B84 0%, #C0157A 100%)"; e.currentTarget.style.boxShadow = "0 4px 16px rgba(230,0,122,0.35), 0 1px 3px rgba(230,0,122,0.2)"; e.currentTarget.style.transform = "translateY(0)"; }}>
                  {arqLoadingQ
                    ? <><span style={{ width: 12, height: 12, border: "2px solid rgba(255,255,255,0.5)", borderTopColor: "#fff", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" }} /> Loading…</>
                    : <>Send to Client{arqNotifCount > 0 && <span style={{ background: "#fff", color: "#E61B84", borderRadius: 10, fontSize: 10, padding: "2px 7px", fontWeight: 800, marginLeft: 2 }}>{arqNotifCount}</span>}</>
                  }
                </button>

                {/* Collapsible secondary actions */}
                <div style={{ borderRadius: 14, overflow: "hidden", border: actionsOpen ? "1.5px solid #f9a8d4" : "1.5px solid #fce7f3", boxShadow: actionsOpen ? "0 8px 28px rgba(230,0,122,0.18)" : "0 2px 8px rgba(230,0,122,0.08)", transition: "box-shadow 0.25s, border-color 0.25s" }}>
                  {/* Toggle header */}
                  <button
                    onClick={() => setActionsOpen(o => !o)}
                    style={{ width: "100%", padding: "12px 16px", background: "linear-gradient(135deg, #E61B84 0%, #C0157A 100%)", border: "none", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", fontFamily: "inherit", fontSize: 13, fontWeight: 700, color: "#fff", letterSpacing: "0.02em", transition: "background 0.2s", gap: 0 }}
                    onMouseEnter={e => { e.currentTarget.style.background = "linear-gradient(135deg, #C0157A 0%, #a30055 100%)"; }}
                    onMouseLeave={e => { e.currentTarget.style.background = "linear-gradient(135deg, #E61B84 0%, #C0157A 100%)"; }}>
                    <span style={{ width: 13, flexShrink: 0 }} />
                    <span style={{ flex: 1, textAlign: "center" }}>More Actions</span>
                    <svg width="13" height="13" viewBox="0 0 14 14" fill="none" style={{ transition: "transform 0.25s cubic-bezier(0.4,0,0.2,1)", transform: actionsOpen ? "rotate(180deg)" : "rotate(0deg)", flexShrink: 0 }}>
                      <path d="M2.5 5L7 9.5L11.5 5" stroke="rgba(255,255,255,0.9)" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
                    </svg>
                  </button>

                  {/* Drawer */}
                  {actionsOpen && (
                    <div style={{ background: "#fff", borderTop: "1px solid #fce7f3", padding: "8px 8px 10px", display: "flex", flexDirection: "column", gap: 4, animation: "slideDown 0.18s ease-out" }}>

                      {/* ── Integrations group ── */}
                      <div style={{ position: "relative" }}>
                        <div style={{ borderRadius: 9, overflow: "hidden", border: "1px solid #fce7f3" }}>
                          <button
                            onClick={() => setIntegrationsExpanded(o => !o)}
                            style={{ display: "flex", alignItems: "center", justifyContent: "space-between", width: "100%", padding: "8px 12px", border: "none", background: "linear-gradient(135deg, #E61B84 0%, #C0157A 100%)", color: "#fff", fontSize: 12, fontWeight: 600, cursor: "pointer", fontFamily: "inherit", transition: "all 0.15s", textAlign: "left" }}
                            onMouseEnter={e => { e.currentTarget.style.background = "linear-gradient(135deg, #C0157A 0%, #a30055 100%)"; }}
                            onMouseLeave={e => { e.currentTarget.style.background = "linear-gradient(135deg, #E61B84 0%, #C0157A 100%)"; }}>
                            <span>Integrations</span>
                            <svg width="11" height="11" viewBox="0 0 14 14" fill="none" style={{ transition: "transform 0.2s", transform: integrationsExpanded ? "rotate(180deg)" : "rotate(0deg)", flexShrink: 0 }}>
                              <path d="M2.5 5L7 9.5L11.5 5" stroke="rgba(255,255,255,0.85)" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
                            </svg>
                          </button>

                          {integrationsExpanded && (
                            <div style={{ background: "#fdf2f8", padding: "6px 8px", display: "flex", flexDirection: "column", gap: 4 }}>
                              {/* Share to Epic */}
                              <button
                                onClick={e => {
                                  if (user?.subscription_tier === "enterprise") { handleSendToEpic(activeFormId); }
                                  else { triggerEnterprisePopup(e.currentTarget); }
                                }}
                                disabled={epicLoading}
                                style={{ width: "100%", padding: "7px 10px", borderRadius: 7, border: "1px solid #f9a8d4", background: epicSuccess ? "rgba(34,197,94,0.1)" : "#fce7f3", color: epicSuccess ? "#16a34a" : "#9d174d", fontSize: 11, fontWeight: 600, cursor: epicLoading ? "wait" : "pointer", fontFamily: "inherit", transition: "all 0.15s", textAlign: "center", display: "flex", alignItems: "center", justifyContent: "center", gap: 6 }}
                                onMouseEnter={e => { if (!epicSuccess && !epicLoading) e.currentTarget.style.background = "#f9a8d4"; }}
                                onMouseLeave={e => { if (!epicSuccess) e.currentTarget.style.background = "#fce7f3"; }}>
                                <span>{epicSuccess ? "Sent to Epic" : epicLoading ? "Sending…" : "Share to Epic"}</span>
                                {epicLoading && <span style={{ width: 9, height: 9, border: "2px solid #f9a8d4", borderTopColor: "#be185d", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" }} />}
                              </button>

                              {/* Share to Vertafore */}
                              <button
                                onClick={e => {
                                  if (user?.subscription_tier === "enterprise") { handleSendToVertafore(activeFormId); }
                                  else { triggerEnterprisePopup(e.currentTarget); }
                                }}
                                disabled={vertaforeLoading}
                                style={{ width: "100%", padding: "7px 10px", borderRadius: 7, border: "1px solid #f9a8d4", background: vertaforeSuccess ? "rgba(34,197,94,0.1)" : "#fce7f3", color: vertaforeSuccess ? "#16a34a" : "#9d174d", fontSize: 11, fontWeight: 600, cursor: vertaforeLoading ? "wait" : "pointer", fontFamily: "inherit", transition: "all 0.15s", textAlign: "center", display: "flex", alignItems: "center", justifyContent: "center", gap: 6 }}
                                onMouseEnter={e => { if (!vertaforeSuccess && !vertaforeLoading) e.currentTarget.style.background = "#f9a8d4"; }}
                                onMouseLeave={e => { if (!vertaforeSuccess) e.currentTarget.style.background = "#fce7f3"; }}>
                                <span>{vertaforeSuccess ? "Sent to Vertafore" : vertaforeLoading ? "Sending…" : "Share to Vertafore"}</span>
                                {vertaforeLoading && <span style={{ width: 9, height: 9, border: "2px solid #f9a8d4", borderTopColor: "#be185d", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" }} />}
                              </button>
                            </div>
                          )}
                        </div>

                      </div>

                      {/* ── Download group ── */}
                      <div style={{ borderRadius: 9, overflow: "hidden", border: "1px solid #fce7f3" }}>
                        <button
                          onClick={() => setDownloadExpanded(o => !o)}
                          style={{ display: "flex", alignItems: "center", justifyContent: "space-between", width: "100%", padding: "8px 12px", border: "none", background: "linear-gradient(135deg, #E61B84 0%, #C0157A 100%)", color: "#fff", fontSize: 12, fontWeight: 600, cursor: "pointer", fontFamily: "inherit", transition: "all 0.15s", textAlign: "left" }}
                          onMouseEnter={e => { e.currentTarget.style.background = "linear-gradient(135deg, #C0157A 0%, #a30055 100%)"; }}
                          onMouseLeave={e => { e.currentTarget.style.background = "linear-gradient(135deg, #E61B84 0%, #C0157A 100%)"; }}>
                          <span>Download</span>
                          <svg width="11" height="11" viewBox="0 0 14 14" fill="none" style={{ transition: "transform 0.2s", transform: downloadExpanded ? "rotate(180deg)" : "rotate(0deg)", flexShrink: 0 }}>
                            <path d="M2.5 5L7 9.5L11.5 5" stroke="rgba(255,255,255,0.85)" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
                          </svg>
                        </button>

                        {downloadExpanded && (
                          <div style={{ background: "#fdf2f8", padding: "6px 8px", display: "flex", flexDirection: "column", gap: 4 }}>
                            {/* This Form - no summary */}
                            <button
                              onClick={() => handleDownloadOneNoSummary(activeFormId)}
                              disabled={!activeFormId}
                              style={{ width: "100%", padding: "7px 10px", borderRadius: 7, border: "1px solid #f9a8d4", background: "#fce7f3", color: "#9d174d", fontSize: 11, fontWeight: 600, cursor: activeFormId ? "pointer" : "not-allowed", opacity: activeFormId ? 1 : 0.5, fontFamily: "inherit", transition: "all 0.15s", textAlign: "center" }}
                              onMouseEnter={e => { if (activeFormId) e.currentTarget.style.background = "#f9a8d4"; }}
                              onMouseLeave={e => { e.currentTarget.style.background = "#fce7f3"; }}>
                              This Form
                            </button>

                            {/* Entire Package - all forms + summary */}
                            <button
                              onClick={() => handleDownloadAll()}
                              style={{ width: "100%", padding: "7px 10px", borderRadius: 7, border: "1px solid #f9a8d4", background: "#fce7f3", color: "#9d174d", fontSize: 11, fontWeight: 600, cursor: "pointer", fontFamily: "inherit", transition: "all 0.15s", textAlign: "center" }}
                              onMouseEnter={e => { e.currentTarget.style.background = "#f9a8d4"; }}
                              onMouseLeave={e => { e.currentTarget.style.background = "#fce7f3"; }}>
                              Entire Package
                            </button>

                            {/* Submission Brief - summary only */}
                            <button
                              onClick={() => handleLiteCoverSheet()}
                              disabled={liteCoverLoading}
                              style={{ width: "100%", padding: "7px 10px", borderRadius: 7, border: "1px solid #f9a8d4", background: "#fce7f3", color: "#9d174d", fontSize: 11, fontWeight: 600, cursor: liteCoverLoading ? "wait" : "pointer", opacity: liteCoverLoading ? 0.6 : 1, fontFamily: "inherit", transition: "all 0.15s", textAlign: "center", display: "flex", alignItems: "center", justifyContent: "center", gap: 6 }}
                              onMouseEnter={e => { if (!liteCoverLoading) e.currentTarget.style.background = "#f9a8d4"; }}
                              onMouseLeave={e => { e.currentTarget.style.background = "#fce7f3"; }}>
                              <span>{liteCoverLoading ? "Generating…" : "Submission Brief"}</span>
                              {liteCoverLoading && <span style={{ width: 9, height: 9, border: "2px solid #f9a8d4", borderTopColor: "#be185d", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" }} />}
                            </button>

                            {/* Audit Record - E&O record of every reason given on this submission */}
                            <button
                              onClick={handleDownloadAuditRecord}
                              disabled={auditExportLoading}
                              title="Download a record of the marketing reason and every dismissed/overridden item's reason, for your own E&amp;O records"
                              style={{ width: "100%", padding: "7px 10px", borderRadius: 7, border: "1px solid #f9a8d4", background: "#fce7f3", color: "#9d174d", fontSize: 11, fontWeight: 600, cursor: auditExportLoading ? "wait" : "pointer", opacity: auditExportLoading ? 0.6 : 1, fontFamily: "inherit", transition: "all 0.15s", textAlign: "center", display: "flex", alignItems: "center", justifyContent: "center", gap: 6 }}
                              onMouseEnter={e => { if (!auditExportLoading) e.currentTarget.style.background = "#f9a8d4"; }}
                              onMouseLeave={e => { e.currentTarget.style.background = "#fce7f3"; }}>
                              <span>{auditExportLoading ? "Generating…" : "Audit Record"}</span>
                              {auditExportLoading && <span style={{ width: 9, height: 9, border: "2px solid #f9a8d4", borderTopColor: "#be185d", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" }} />}
                            </button>
                          </div>
                        )}
                      </div>

                    </div>
                  )}
                </div>


              </div>
            </div>

            <div className="editor-main">
              {!sidebarOpen && (
                <button className="sidebar-open-btn" onClick={() => setSidebarOpen(true)} title="Show SQS &amp; Actions">
                  <span className="sidebar-open-label">SQS &amp; ACTIONS</span>
                </button>
              )}
              <PDFJsViewer
                key={activeFormId}
                pdfUrl={`${API_BASE}/api/get-pdf/${sessionId}/${activeFormId}`}
                formName={activeFormId ? (generatedForms[activeFormId]?.form_name || activeFormId) : ""}
                onFormNav={{ goPrev, goNext, activeIdx, total: formIdList.length }}
                sessionId={sessionId} formId={activeFormId} token={token}
                savedSignature={savedSignature}
                isSigned={signedForms.has(activeFormId)}
                onSignApplied={fid => setSignedForms(prev => new Set([...prev, fid]))}
                onOpenSignatureModal={onOpenSignatureModal}
                clientFilledFields={clientFilledFields}
                onRefreshFields={refreshArqData}
                onSqsUpdate={(fid, newSqs, extras) => {
                  setGeneratedForms(prev => ({
                    ...prev,
                    [fid]: { ...prev[fid], sqs: newSqs }
                  }));
                  if (extras?.packageSqs) setPackageSqs(extras.packageSqs);
                  if (Array.isArray(extras?.crossIssues)) setCrossIssues(extras.crossIssues);
                }}
              />
            </div>
          </div>
        )}

        {step === "success" && (
          <div style={{ maxWidth: 480, margin: "0 auto", textAlign: "center", padding: "56px 24px" }}>
            <div style={{ width: 80, height: 80, borderRadius: "50%", background: "linear-gradient(135deg, #E61B84, #C0157A)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 36, color: "#fff", margin: "0 auto 24px", boxShadow: "0 8px 28px rgba(230,0,122,0.3)", animation: "successPop 0.5s ease-out" }}>✓</div>
            <h2 style={{ fontSize: 26, fontWeight: 800, color: "#0f172a", marginBottom: 8 }}>Download Complete!</h2>
            <p style={{ fontSize: 15, color: "#64748b", marginBottom: 28, lineHeight: 1.6 }}>Your filled ACORD forms have been downloaded successfully.</p>
            {user && user.subscription_tier === "free" && (
              <div style={{ background: "rgba(230,0,122,0.05)", border: "1px solid rgba(230,0,122,0.15)", borderRadius: 10, padding: "12px 16px", marginBottom: 24, fontSize: 14, color: "#1e293b" }}>
                You have <strong style={{ color: "#E61B84" }}>{Math.max(0, user.downloads_remaining)}</strong> free download{user.downloads_remaining !== 1 ? "s" : ""} remaining
              </div>
            )}
            <div style={{ display: "flex", flexDirection: "column", gap: 10, alignItems: "center" }}>
              <button onClick={() => setStep("editor")}
                style={{ minWidth: 260, padding: "12px 0", borderRadius: 10, border: "none", background: "#E61B84", color: "#fff", fontSize: 14, fontWeight: 700, cursor: "pointer", boxShadow: "0 4px 14px rgba(230,0,122,0.3)" }}
                onMouseEnter={e => e.currentTarget.style.background = "#C0157A"}
                onMouseLeave={e => e.currentTarget.style.background = "#E61B84"}>
                ← Back to Form
              </button>
            </div>

            {/* Post-download checklist: a successful download does not mean the package
                is clean. Surface unresolved issues + next actions so nothing is assumed. */}
            {(() => {
              const recs     = preflightRecs || [];
              const hardRecs = recs.filter(r => r.recommendation_type === "hard_stop");
              const softRecs = recs.filter(r => r.recommendation_type !== "hard_stop");
              const hasIssues = recs.length > 0;
              const score = packageSqs?.package_sqs_score;
              const nextAction = (sqsNarrative || "").replace(/\n+/g, " ").trim();
              return (
                <div style={{ marginTop: 30, textAlign: "left", background: "#fff", border: "1px solid #e2e8f0", borderRadius: 12, padding: "18px 20px", boxShadow: "0 2px 10px rgba(15,23,42,0.05)" }}>
                  <div style={{ background: hasIssues ? "#fffbeb" : "#f0fdf4", border: `1px solid ${hasIssues ? "#fde68a" : "#bbf7d0"}`, borderLeft: `3px solid ${hasIssues ? "#f59e0b" : "#22c55e"}`, borderRadius: 8, padding: "10px 12px", marginBottom: hasIssues || score != null ? 14 : 0 }}>
                    <div style={{ fontSize: 13, fontWeight: 700, color: hasIssues ? "#92400e" : "#166534" }}>
                      {hasIssues ? "Downloaded does not mean fully reviewed" : "No unresolved issues"}
                    </div>
                    <div style={{ fontSize: 11.5, color: hasIssues ? "#78350f" : "#15803d", marginTop: 3, lineHeight: 1.5 }}>
                      {hasIssues
                        ? "Your file downloaded, but the items below are still open. Resolve them before sending this package to a carrier."
                        : "This package downloaded with no open recommendations. It is ready to send."}
                    </div>
                  </div>

                  {score != null && (
                    <div style={{ fontSize: 12, color: "#475569", marginBottom: hasIssues ? 14 : 0 }}>
                      Score at download: <strong style={{ color: "#0f172a" }}>{score}/100</strong>
                    </div>
                  )}

                  {hasIssues && (
                    <>
                      <div style={{ fontSize: 11, fontWeight: 700, color: "#64748b", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 8 }}>
                        Unresolved items ({recs.length})
                      </div>
                      {hardRecs.map((r, i) => (
                        <div key={`h${i}`} style={{ display: "flex", gap: 8, fontSize: 12.5, color: "#7f1d1d", padding: "4px 0", lineHeight: 1.5 }}>
                          <span style={{ color: "#dc2626", fontWeight: 700 }}>☐</span>
                          <span>{r.message}{r.score_impact ? <span style={{ color: "#dc2626", fontWeight: 700 }}> (-{r.score_impact} pts)</span> : ""}</span>
                        </div>
                      ))}
                      {softRecs.map((r, i) => (
                        <div key={`s${i}`} style={{ display: "flex", gap: 8, fontSize: 12.5, color: "#334155", padding: "4px 0", lineHeight: 1.5 }}>
                          <span style={{ color: "#94a3b8", fontWeight: 700 }}>☐</span>
                          <span>{r.message}{r.score_impact > 0 ? <span style={{ color: "#d97706", fontWeight: 600 }}> (up to +{r.score_impact} pts)</span> : ""}</span>
                        </div>
                      ))}
                      {nextAction && (
                        <div style={{ marginTop: 14, background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: 8, padding: "10px 12px" }}>
                          <div style={{ fontSize: 10.5, fontWeight: 700, color: "#94a3b8", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 }}>Recommended next action</div>
                          <div style={{ fontSize: 12, color: "#334155", lineHeight: 1.6 }}>{nextAction}</div>
                        </div>
                      )}
                    </>
                  )}
                </div>
              );
            })()}
          </div>
        )}
      </>
    );
  }
});

export default AcordModal;