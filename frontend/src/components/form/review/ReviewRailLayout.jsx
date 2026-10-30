import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { gradeColor, sqsGradeFromScore, lineLabel, scoreSoFar, sourceLabel } from "../../../utils/formatters";
import { formLabel } from "../../../utils/formInstances";
import KeyDetailsMissing, { KeyDetailsResolved } from "./KeyDetailsMissing";
import { screenPoints, screenPointsText, dismissedRowPointsText } from "../../../utils/screenPoints";
import { planAfterForms } from "../../../utils/editorPlanList";
import { openConflictFacts } from "../../../utils/dcFacts";
import Recommendations from "./Recommendations";
import useAttentionList from "./useAttentionList";
import { buildRecommendations, recommendationsText, considerText } from "../../../utils/recommendations";
import PoliciesTable from "./PoliciesTable";
import FormValuesLink from "./FormValuesLink";
import QuestionnairePage from "./QuestionnairePage";
import { QUESTIONNAIRE_TITLE, QUESTIONNAIRE_DESC, railSub, railBadge } from "../../../utils/questionnaire";
import {
  GEN_NONE, GEN_RUNNING, GEN_DONE, GEN_INTERRUPTED, documentsLockedReason, confirmLockedReason, continueLabel, scoreHeading,
  GENERATION_DIDNT_FINISH, GENERATION_DIDNT_FINISH_NEXT, GENERATION_RUNNING_TEXT, DOCUMENTS_AFTER_FORMS_NOTE,
  SKIP_TO_SELECTION, nextReviewStep,
} from "../../../utils/packageGeneration";
import { railCapNote } from "../../../utils/reviewedStops";
import {
  RESOLVED_LABELS, NO_LONGER_APPLIES, liveIdsOf, splitClusters, storedHandledRows, resolvedRows, reopenKind,
  pageProgress,
} from "../../../utils/resolvedIssues";
import { positiveScoreWording } from "../../../utils/positiveWording";
import { formsReady } from "../../../utils/scoreWithForms";
import { documentTypeTag, documentInsuredTag, INSURED_TAG_STYLE } from "../../../utils/addDocuments";
import { DOCUMENTS_REVIEW_NOTE } from "../../../utils/addDocuments";
import { lossRunDocNote } from "../../../utils/lossCoverage";
import {
  documentNeedsTypeReview, canConfirmDocumentType, CONFIRM_TYPE_LABEL, CONFIRM_TYPE_TIP,
} from "../../../utils/addDocuments";
import "./ReviewRailLayout.css";

// The "rail" layout of the pre-form Review step - the default layout
// (VITE_REVIEW_LAYOUT=classic brings back the original screen).
//
// Presentation only. Every number, rule and action comes from AcordModal: the
// same state, the same handlers (reclassify, confirm, resolve/dismiss, open to
// fix) and the same render closures the classic layout uses, so the two layouts
// can never disagree about the data. Module-level helpers that live in
// AcordModal.jsx (IssueLine, HoverTip, ...) arrive through `helpers` rather than
// an import, which would be circular.
//
// All sections stay mounted and inactive ones are hidden, so collapse
// choices, typed values and the Data Consistency jump target survive switching.

const FIX_GROUP = "Fix before selecting forms";
// Once forms exist (or are being generated) there is no form selection ahead
// of the producer, so the same group is named for what it still is.
const FIX_GROUP_AFTER_FORMS = "Needs your input";

const SECTIONS = [
  { id: "overview", label: "Overview", group: "Review" },
  { id: "documents", label: "Documents", group: "Review" },
  { id: "integrity", label: "Submission Integrity", group: FIX_GROUP },
  { id: "consistency", label: "Data Consistency", group: FIX_GROUP },
  { id: "hardstops", label: "Hard Stops", group: FIX_GROUP },
  { id: "warnings", label: "Warnings", group: FIX_GROUP },
  // Choice Electric #22 / #27 (7 Oct 2026): score raisers and what the forms
  // will need, addressable before (and after) the forms.
  { id: "recommendations", label: "Recommendations", group: FIX_GROUP },
  // The narrative questionnaire (owner, 23 Oct 2026): the last page before
  // form selection. "Skip to form selection" still skips it; it never blocks.
  { id: "questionnaire", label: "Questionnaire", group: FIX_GROUP },
];

// The backend tier ladder (sqs_service.tier_for_score) and the grade colour
// each tier's score range maps to (utils/formatters.gradeColor).
const TIER_LADDER = [
  { name: "Not Ready", color: "#ef4444" },
  { name: "Major Gaps", color: "#ef4444" },
  { name: "Needs Work", color: "#f59e0b" },
  { name: "Almost There", color: "#eab308" },
  { name: "Submission Ready", color: "#10b981" },
];

const WARNING_TIERS = ["required", "recommended", "binder_followup"];
const WARNING_TIER_FALLBACK_LABELS = {
  required: "Required before submission",
  recommended: "Recommended before quoting",
  binder_followup: "Binder / placement follow-up",
};

const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
const isHandled = (status) => status === "resolved" || status === "dismissed";

// ── Counting ──────────────────────────────────────────────────────────────────
// Same arithmetic as AcordModal's sectionProgress: a cluster contributes its
// `count`, and an item is handled once it is resolved or dismissed.
// An advice-only card (`score_neutral` - e.g. a requested coverage change) is
// drawn with the warnings but is no warning: never counted as one (owner,
// 29 Oct 2026; the backend counts it as `counts.info`).
const isInfoCluster = (c) => !!(c && c.score_neutral);
const warningClustersOnly = (clusters) => (clusters || []).filter((c) => !isInfoCluster(c));

function tallyClusters(clusters, issueStatuses, issueIdOf) {
  let total = 0;
  let done = 0;
  for (const c of warningClustersOnly(clusters)) {
    const items = Array.isArray(c.items) ? c.items : [];
    total += Number(c.count) || items.length;
    for (const it of items) {
      if (isHandled(issueStatuses?.get?.(issueIdOf(it))?.status)) done += 1;
    }
  }
  return { total, done, open: Math.max(0, total - done) };
}

// A stop that arrived as a bare string (no grouped view) is tracked under the
// same fallback id BareStopRow gives it.
function tallyBare(messages, issueStatuses, issueIdOf) {
  const list = Array.isArray(messages) ? messages : [];
  const done = list.filter((m) => isHandled(issueStatuses?.get?.(issueIdOf({ message: m, forms: [] }))?.status)).length;
  return { total: list.length, done, open: Math.max(0, list.length - done) };
}

function progressText({ open, done }) {
  if (open > 0) return `${plural(open, "item")} still need${open === 1 ? "s" : ""} attention${done > 0 ? ` · ${done} handled` : ""}`;
  return `All ${done} handled`;
}

// The live next-step sentence (AcordModal review step), verbatim.
// `afterForms`: forms exist or are being generated (Orbin item 1).
function nextStepText(openItemCount, hardStopCount, warningCount, afterForms = false) {
  const advisory = [
    hardStopCount > 0 ? plural(hardStopCount, "hard stop") : null,
    warningCount > 0 ? plural(warningCount, "warning") : null,
  ].filter(Boolean).join(" and ");
  const n = openItemCount;
  if (n > 0 && advisory) return `${plural(n, "item")} need${n === 1 ? "s" : ""} your input below, plus ${advisory} to review`;
  if (n > 0) return `${plural(n, "item")} need${n === 1 ? "s" : ""} your input below`;
  if (advisory) return `Review ${advisory} below before continuing`;
  return afterForms
    ? "Nothing needs your attention - continue where you left off"
    : "Nothing needs your attention - go to form selection";
}

// ── Small presentational pieces ───────────────────────────────────────────────
function CheckIcon({ size = 14 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M5 12.5l4.5 4.5L19 7.5" />
    </svg>
  );
}

function FileIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
      <path d="M14 3v5h5" />
    </svg>
  );
}

function ArrowIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M5 12h14M13 6l6 6-6 6" />
    </svg>
  );
}

// A turn-back arrow for "Open again" (the item returns to its list).
function ReopenIcon() {
  return (
    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M3 12a9 9 0 1 0 3-6.7" />
      <path d="M3 3v6h6" />
    </svg>
  );
}

function Spinner() {
  return <span className="rr-spinner" aria-hidden="true" />;
}

function Badge({ tone, children }) {
  return <span className={`rr-badge rr-badge--${tone}`}>{children}</span>;
}

function PageHead({ id, title, description, right, afterForms = false }) {
  const section = SECTIONS.find((s) => s.id === id);
  const group = afterForms && section.group === FIX_GROUP ? FIX_GROUP_AFTER_FORMS : section.group;
  return (
    <header className="rr-page-head">
      <div className="rr-page-head__text">
        <div className="rr-eyebrow">{group}</div>
        <h2 className="rr-page-title">{title}</h2>
        {description && <p className="rr-page-desc">{description}</p>}
      </div>
      {right && <div className="rr-page-head__right">{right}</div>}
    </header>
  );
}

function Panel({ title, meta, right, children, bodyClassName = "rr-panel__body", className = "" }) {
  return (
    <section className={`rr-panel ${className}`.trim()}>
      {(title || right) && (
        <div className="rr-panel__head">
          <div className="rr-panel__head-text">
            {title && <div className="rr-panel__title">{title}</div>}
            {meta && <div className="rr-panel__meta">{meta}</div>}
          </div>
          {right && <div className="rr-panel__right">{right}</div>}
        </div>
      )}
      <div className={bodyClassName}>{children}</div>
    </section>
  );
}

function EmptyState({ title, sub }) {
  return (
    <section className="rr-panel">
      <div className="rr-empty">
        <span className="rr-empty__icon"><CheckIcon size={20} /></span>
        <div className="rr-empty__title">{title}</div>
        {sub && <div className="rr-empty__sub">{sub}</div>}
      </div>
    </section>
  );
}

// A disclosure header with the app's own chevron glyph (CollapsibleSection's ▶).
function FoldButton({ open, onToggle, className, children }) {
  return (
    <button type="button" className={className} aria-expanded={open} onClick={onToggle}>
      <span className="rr-tri" aria-hidden="true">▶</span>
      {children}
    </button>
  );
}

function Gauge({ tierIndex }) {
  const cx = 120, cy = 118, r = 96, gap = 3, span = 180 / TIER_LADDER.length;
  const pt = (a) => {
    const rad = (a * Math.PI) / 180;
    return `${(cx + r * Math.cos(rad)).toFixed(2)} ${(cy + r * Math.sin(rad)).toFixed(2)}`;
  };
  return (
    <svg viewBox="0 0 240 132" className="rr-gauge__svg" aria-hidden="true">
      {TIER_LADDER.map((t, i) => {
        const a0 = 180 + i * span + (i ? gap / 2 : 0);
        const a1 = 180 + (i + 1) * span - (i < TIER_LADDER.length - 1 ? gap / 2 : 0);
        return (
          <path key={t.name} d={`M ${pt(a0)} A ${r} ${r} 0 0 1 ${pt(a1)}`} stroke={t.color} strokeWidth="18" fill="none"
            opacity={tierIndex >= 0 && i <= tierIndex ? 1 : 0.16} />
        );
      })}
    </svg>
  );
}

// ── Main component ────────────────────────────────────────────────────────────
export default function ReviewRailLayout(props) {
  const {
    section, onSectionChange, banners, helpers,
    packageSqs, keyDetails, integrity, renderIntegrityStatus,
    docSummary, docsNeedingReview, availableDocTypes, reclassDocId, reclassBusyBtn, reviewLoadingId,
    onReclassify, onReviewData, renderAddDocuments, lossCoverageNote = "",
    underwriting, openConflicts, underwritingPicks, setUnderwritingPicks, underwritingBusy, onConfirmUnderwriting,
    dcHighlight, dcSectionRef,
    groupedIssues, hardStops, softStops, issueStatuses, reviewIssueCounts, hasHardStops, hasWarnings,
    renderItemActions, renderClusterRollup,
    issueDiff, canProceedWithWarning, warningStops,
    openItemCount, onContinue, onFixKeyDetail,
    packageGen, policyTable,
    // "Before you generate" (Choice Electric #27): the form checks, pre-form.
    dryRun, dryRunSessionId, dryRunFormIds, onDryRunUpdate, onFixDryRunItem,
    // Recommendations section (#22): a score row's fix; a form (and box) to open;
    // a form to tick before generation (a form choice, 13 Oct 2026).
    onFixScoreItem, onOpenFormAt, onAddForm, formOffers, onAddOffer,
    // The Resolved section (8 Oct 2026): "Open again" and its in-flight state.
    onReopenIssue, reopeningIds, reopenNotices,
    // Recommendations' own Resolved list (13 Oct 2026): "Open again" there.
    onReopenRecommendation, onReopenKeyDetail,
    // The Questionnaire page (23 Oct 2026): its data (useQuestionnaire), the
    // question a narrative card's deep link opens, and the score / issue merge
    // a saved answer's reply goes through.
    questionnaire, questionnaireFocus, onQuestionnaireApplied,
  } = props;
  const {
    IssueLine, BareStopRow, HoverTip, RemediationDiffBand, IntegritySeverityChip,
    CONFIDENCE_META, DOC_ACTION_TIPS, clusterIdOf, issueIdOf,
  } = helpers;

  const [folds, setFolds] = useState({});
  const [warnTab, setWarnTab] = useState("all");
  const layoutRef = useRef(null);
  const navRef = useRef(null);
  const footerRef = useRef(null);

  const foldOpen = (key, fallback) => (Object.prototype.hasOwnProperty.call(folds, key) ? folds[key] : fallback);
  const toggleFold = (key, fallback) => setFolds((f) => ({
    ...f,
    [key]: !(Object.prototype.hasOwnProperty.call(f, key) ? f[key] : fallback),
  }));

  // Keep the rail under the app header (which hides on scroll down), and keep
  // keyboard focus and the job toasts clear of the header and the pinned footer.
  // The header's state is applied to this layout only; the footer height and the
  // page scroll padding are set while the layout is mounted and removed after.
  useLayoutEffect(() => {
    const root = document.documentElement;
    const layout = layoutRef.current;
    const footer = footerRef.current;
    const phone = window.matchMedia("(max-width: 900px)");
    const header = { height: 0, hidden: false };
    let headerOffset = -1;
    let frame = 0;
    const applyScrollPadding = () => {
      root.style.scrollPaddingTop = `${Math.max(0, headerOffset) + (phone.matches ? 68 : 12)}px`;
      root.style.scrollPaddingBottom = `${(footer ? footer.offsetHeight : 0) + 12}px`;
    };
    // Where the header's bottom edge actually is. A hidden header still takes its
    // space at the top of the page, so near the top the rail must start below it
    // even while the header is flagged hidden.
    const applyHeaderOffset = () => {
      frame = 0;
      if (!layout) return;
      const next = header.hidden ? Math.max(0, header.height - window.scrollY) : header.height;
      if (next === headerOffset) return;
      headerOffset = next;
      layout.style.setProperty("--rr-header-offset", `${next}px`);
      applyScrollPadding();
    };
    const onHeader = (e) => {
      const { height, hidden } = e.detail || {};
      if (!layout || typeof height !== "number") return;
      header.height = height;
      header.hidden = !!hidden;
      layout.style.setProperty("--rr-header-h", `${height}px`);
      applyHeaderOffset();
    };
    const onScroll = () => {
      if (header.hidden && !frame) frame = window.requestAnimationFrame(applyHeaderOffset);
    };
    const onFooter = () => {
      if (footer) root.style.setProperty("--rr-footer-h", `${footer.offsetHeight}px`);
      applyScrollPadding();
    };
    window.addEventListener("app-header:change", onHeader);
    window.addEventListener("scroll", onScroll, { passive: true });
    window.dispatchEvent(new Event("app-header:request"));
    onFooter();
    const ro = typeof ResizeObserver !== "undefined" && footer ? new ResizeObserver(onFooter) : null;
    if (ro) ro.observe(footer);
    phone.addEventListener("change", applyScrollPadding);
    return () => {
      window.removeEventListener("app-header:change", onHeader);
      window.removeEventListener("scroll", onScroll);
      if (frame) window.cancelAnimationFrame(frame);
      if (ro) ro.disconnect();
      phone.removeEventListener("change", applyScrollPadding);
      root.style.removeProperty("--rr-footer-h");
      root.style.removeProperty("scroll-padding-top");
      root.style.removeProperty("scroll-padding-bottom");
    };
  }, []);

  // On the phone tab bar, bring the active section into view by scrolling the
  // bar only (scrollIntoView would also move the page) - when the section changes
  // and when the layout switches into the tab bar (a tablet rotating, a resize).
  useEffect(() => {
    const centreActive = () => {
      const bar = navRef.current;
      if (!bar || bar.scrollWidth <= bar.clientWidth) return;
      const active = bar.querySelector('[aria-current="page"]');
      if (active) bar.scrollLeft = Math.max(0, active.offsetLeft - (bar.clientWidth - active.offsetWidth) / 2);
    };
    centreActive();
    const phone = window.matchMedia("(max-width: 900px)");
    const onChange = () => window.requestAnimationFrame(centreActive);
    phone.addEventListener("change", onChange);
    return () => phone.removeEventListener("change", onChange);
  }, [section]);

  // ── Derived numbers (one place, used by the rail, the Overview and the footer) ─
  const fields = underwriting?.fields || [];
  // Every number on the review screen is a share of one total (15 Oct 2026).
  const screenPts = screenPoints(packageSqs, groupedIssues, keyDetails, openConflictFacts(underwriting));
  const confirmedCount = fields.filter((f) => f.status === "confirmed").length;
  // A value the documents say CHANGED on a stated date (the umbrella cut from
  // $3,000,000 to $1,000,000 effective 7/25/25) is NOT shown here (owner, 27 Sep
  // 2026): the client asked for it not to be a conflict, never for a note about
  // it. The backend keeps it - the forms print the current value and no
  // conflict is raised. The policies table stays; the line-scoped ("not a
  // conflict") rows are not drawn since Brent #10 (7 Oct 2026), so they no
  // longer count as content - the empty state shows above the table.
  const dcHasContent = fields.some((f) => ["conflict", "confirmed"].includes(f.status));
  const dcNeedsConfirm = fields.some((f) => ["conflict", "confirmed"].includes(f.status));

  const groupedHard = groupedIssues?.hard_stops?.length > 0 ? groupedIssues.hard_stops : null;
  const hardTally = groupedHard ? tallyClusters(groupedHard, issueStatuses, issueIdOf) : tallyBare(hardStops, issueStatuses, issueIdOf);
  const warningClusters = groupedIssues?.warnings ? WARNING_TIERS.flatMap((t) => groupedIssues.warnings[t] || []) : null;
  const warnTally = warningClusters ? tallyClusters(warningClusters, issueStatuses, issueIdOf) : tallyBare(softStops, issueStatuses, issueIdOf);
  // (hardOpen / warnOpen are set below, from the progress that also counts the
  // Resolved rows.)

  // ── The Resolved section (8 Oct 2026) ────────────────────────────────────────
  // A dismissed item, and an item fixed through "Open to fix" that no longer
  // fires, leaves its list and sits under a collapsed "Resolved (n)" on its own
  // page - the editor's "Reviewed" tuck (see utils/resolvedIssues).
  const statusOf = (iid) => issueStatuses?.get?.(iid)?.status;
  const liveIssueIds = liveIdsOf(
    [groupedHard || [], ...WARNING_TIERS.map((t) => groupedIssues?.warnings?.[t] || [])], issueIdOf);
  [
    ...(!groupedHard ? (hardStops || []) : []),
    ...(!groupedIssues?.warnings ? (softStops || []) : []),
  ].forEach((m) => liveIssueIds.add(issueIdOf({ message: m, forms: [] })));
  const statusEntries = issueStatuses?.entries ? Array.from(issueStatuses.entries()) : [];
  const hardSplit = groupedHard ? splitClusters(groupedHard, { idOf: issueIdOf, statusOf }) : null;
  const warnSplit = {};
  for (const t of WARNING_TIERS) {
    warnSplit[t] = splitClusters(groupedIssues?.warnings?.[t] || [], { idOf: issueIdOf, statusOf });
  }
  const hardResolved = resolvedRows(hardSplit ? hardSplit.handled : [],
    storedHandledRows(statusEntries, { liveIds: liveIssueIds, page: "hard" }));
  const warnResolved = resolvedRows(WARNING_TIERS.flatMap((t) => warnSplit[t].handled),
    storedHandledRows(statusEntries, { liveIds: liveIssueIds, page: "warning" }));
  const openCountOf = (clusters) => warningClustersOnly(clusters).reduce((n, c) => n + (Number(c.count) || 0), 0);
  const openWarnTotal = WARNING_TIERS.reduce((n, t) => n + openCountOf(warnSplit[t].open), 0);
  // Advice-only cards still on the page (drawn, not counted as warnings).
  const openInfoTotal = WARNING_TIERS.reduce(
    (n, t) => n + (warnSplit[t].open || []).filter(isInfoCluster).length, 0);

  // ── "x of y handled" (owner, 13 Oct 2026) ─────────────────────────────────
  // y = every blocker this package has had: what is still listed PLUS the
  // page's Resolved rows (dismissed, and fixed items that stopped firing,
  // rebuilt from their stored status). x = the Resolved rows. Counting only
  // what is still listed printed "0 of 0 handled" once every warning was
  // fixed, and "0 of 1" with one hard stop left.
  const hardProg = groupedHard
    ? pageProgress(hardSplit.open, hardResolved)
    : { open: hardTally.open, done: hardTally.done + hardResolved.length, total: hardTally.total + hardResolved.length };
  const warnProg = groupedIssues?.warnings
    ? pageProgress(warningClustersOnly(WARNING_TIERS.flatMap((t) => warnSplit[t].open)), warnResolved)
    : { open: warnTally.open, done: warnTally.done + warnResolved.length, total: warnTally.total + warnResolved.length };

  // Locked once forms exist or are generating (Orbin item 1): a document or a
  // value that cannot be acted on here is not an item "needing your input".
  const preFormLocked = packageGen?.state === "done" || packageGen?.state === "running";
  const docsOpen = preFormLocked ? 0 : docsNeedingReview.length;
  // Confirming a value stays open once forms exist (5 Oct 2026) - only a run
  // in progress locks it.
  const conflictsOpen = packageGen?.state === "running" ? 0 : openConflicts.length;
  const hardOpen = hardProg.open;
  const warnOpen = warnProg.open;
  const totalItems = docsOpen + conflictsOpen + confirmedCount + hardProg.total + warnProg.total;
  const handledItems = confirmedCount + hardProg.done + warnProg.done;
  const openItems = Math.max(0, totalItems - handledItems);
  const progressPct = totalItems > 0 ? Math.round((handledItems / totalItems) * 100) : 100;

  const tierName = packageSqs?.tier || null;
  const tierIndex = tierName ? TIER_LADDER.findIndex((t) => t.name === tierName) : -1;
  // The tier's own colour (19 Oct 2026): the chip is coloured by the tier it
  // prints, never re-derived from the number beside it.
  const tierColor = tierIndex >= 0 ? TIER_LADDER[tierIndex].color
    : tierName ? gradeColor(sqsGradeFromScore(packageSqs.package_sqs_score)) : "#64748b";
  // The package SQS before forms (Orbin item 2, 29 Sep 2026): the one door's number,
  // printed with the gauge and in the rail footer. Null means "Not scored yet".
  const soFar = scoreSoFar(packageSqs);

  // Orbin item 1 (1 Oct 2026): the package page is reachable after generation.
  // Once forms exist the number IS the Total Package Score (the backend returns
  // the editor's persisted score) and the button goes back to where the
  // producer left off. Documents stay editable after forms (Choice Electric
  // #25, 7 Oct 2026 - a change re-stamps the forms); only a run in progress
  // locks them.
  const genState = packageGen?.state || GEN_NONE;
  const formsExist = genState === GEN_DONE;
  const afterForms = formsExist || genState === GEN_RUNNING;
  const docLockText = documentsLockedReason(genState);
  const dcLockText = confirmLockedReason(genState);
  const genForms = formsExist && Array.isArray(packageGen?.forms) ? packageGen.forms : [];
  // The footer (Choice Electric #2): the page the main button opens next, or
  // null when it is the continue button (see utils/packageGeneration).
  const step = nextReviewStep(SECTIONS, section, genState);

  // Recommendations (Choice Electric #22 / #27): one model feeds the section,
  // its rail badge and the Overview's link, so the three counts agree. After
  // forms the forms group reads the editor's needs-attention list, re-read
  // whenever the producer comes back to Overview / Recommendations or the
  // score moves.
  const recAttention = useAttentionList(dryRunSessionId, formsExist,
    `${section === "overview" || section === "recommendations"}|${packageSqs?.package_sqs_score ?? ""}|${packageSqs?.timestamp ?? ""}`);
  const recModel = buildRecommendations({
    packageSqs, groupedIssues, keyDetails, dryRun, attention: recAttention, formsExist,
    tickedFormIds: dryRunFormIds || [], formOffers,
  });
  // The rows only a document lifts sit in the same "Raise your score" list
  // (23 Oct 2026), so every count of that list - this rail badge, the section's
  // pill, the Overview link - counts them too.
  const recDocRows = formsExist && !planAfterForms(packageSqs) ? 0
    : (screenPts.unanswerable || []).filter((u) => u && u.action === "add_documents").length;
  if (recDocRows) { recModel.count += recDocRows; recModel.docRows = recDocRows; }
  const recChecking = !formsExist && genState !== GEN_RUNNING && dryRun?.status === "pending";
  // The "Forms ready" meter (Brent, 23 Oct 2026): what the generated forms still
  // need, off the same needs-attention list. The score never moves with it.
  const formsMeter = formsExist ? formsReady(recAttention) : null;

  const integrityStatus = integrity?.status;
  const integrityContent = renderIntegrityStatus();

  const applicantField = fields.find((f) => f.fact_key === "applicant_name");
  const packageName = applicantField?.confirmed_value
    || applicantField?.values?.[0]?.display
    || (integrity?.documents || []).find((d) => d.applicant)?.applicant
    || "Current submission";
  const lineRecords = fields.map((f) => f.line_records).find((r) => (r || []).length > 0) || [];
  // The rail counts the rows the policies table renders (Brent #9, "9 policies,
  // not 10"). `line_records` carries no id and no layer, so an umbrella and the
  // excess layer above it - two policies, both line "umbrella", both unnumbered
  // on redacted decs - keyed as one, and the rail said 9 beside a 10-row table
  // (owner's run 805049a7, 8 Oct 2026).
  const tableRows = Array.isArray(underwriting?.policy_lines) ? underwriting.policy_lines : null;
  const policyCount = tableRows
    ? tableRows.length
    : new Set(lineRecords.map((r) => r.policy_number || r.id
      || [r.line, r.layer, r.carrier_name].map((v) => v || "").join("|"))).size;

  // ── Rail ──────────────────────────────────────────────────────────────────────
  const navItems = [
    // "x of y handled" while something is left; nothing left: no count (owner).
    { id: "overview", sub: openItems > 0 ? `${handledItems} of ${totalItems} handled` : totalItems > 0 ? "All handled" : "Nothing to handle", badge: null },
    {
      id: "documents",
      sub: docsOpen > 0 ? `${plural(docsOpen, "document")} to review` : `${plural(docSummary.length, "document")} · All clear`,
      badge: docsOpen > 0 ? docsOpen : "done",
    },
    {
      id: "integrity",
      sub: integrityStatus === "low" ? "Hard stop · review" : integrityStatus === "medium" ? "Warning · review" : integrityStatus === "high" ? "Verified" : "Not checked",
      badge: integrityStatus === "low" || integrityStatus === "medium" ? "!" : integrityStatus === "high" ? "done" : null,
    },
    {
      id: "consistency",
      sub: openConflicts.length > 0 ? `${plural(openConflicts.length, "value")} to confirm` : dcNeedsConfirm ? "All confirmed" : "Nothing to confirm",
      badge: openConflicts.length > 0 ? openConflicts.length : "done",
    },
    {
      id: "hardstops",
      sub: hardOpen > 0 ? `${hardOpen} need${hardOpen === 1 ? "s" : ""} attention` : hardProg.done > 0 ? "All handled" : "None",
      badge: hardOpen > 0 ? hardOpen : "done",
    },
    {
      id: "warnings",
      sub: warnOpen > 0 ? `${warnOpen} to review` : warnProg.done > 0 ? "All handled" : "None",
      badge: warnOpen > 0 ? warnOpen : "done",
    },
    {
      id: "recommendations",
      sub: recModel.count > 0 ? `${recModel.count} to consider` : recChecking ? "Checking your forms..." : "Nothing to add",
      badge: recModel.count > 0 ? recModel.count : recChecking ? null : "done",
    },
    {
      id: "questionnaire",
      sub: railSub(questionnaire?.model, questionnaire?.error),
      badge: railBadge(questionnaire?.model),
    },
  ];

  const renderNavBadge = (badge) => {
    if (badge === null || badge === undefined) return null;
    if (badge === "done") return <span className="rr-count rr-count--done" aria-label="Done"><CheckIcon size={12} /></span>;
    return <span className="rr-count">{badge}</span>;
  };

  const renderNavItem = (item) => {
    const s = SECTIONS.find((x) => x.id === item.id);
    const active = section === item.id;
    return (
      <button key={item.id} type="button" className={`rr-nav-item${active ? " is-active" : ""}`}
        aria-current={active ? "page" : undefined} onClick={() => onSectionChange(item.id)}>
        <span className="rr-nav-item__text">
          <span className="rr-nav-item__label">{s.label}</span>
          <span className="rr-nav-item__sub">{item.sub}</span>
        </span>
        {renderNavBadge(item.badge)}
      </button>
    );
  };

  // ── Issue cluster card (Hard Stops and Warnings) ──────────────────────────────
  const renderCluster = (c, tone) => {
    const multi = c.count > 1;
    const key = `cluster:${tone}:${clusterIdOf(c)}`;
    const fallbackOpen = tone === "hard" ? true : !multi;
    const open = foldOpen(key, fallbackOpen);
    return (
      <section className="rr-panel" key={clusterIdOf(c)}>
        <FoldButton className="rr-panel__head rr-panel__head--button" open={open} onToggle={() => toggleFold(key, fallbackOpen)}>
          <span className="rr-panel__title">
            {c.cluster}
            {multi && <span className="issue-count">{c.count}</span>}
          </span>
          <span className="rr-panel__right">{renderClusterRollup(c)}</span>
        </FoldButton>
        {open && (
          <div className="rr-rows">
            {multi ? (
              (c.items || []).map((it, j) => (
                <div className="rr-issue" key={j}>
                  <IssueLine message={it.message} className={`stop-item stop-item-${tone} rr-issue__line`} />
                  {renderItemActions(it, c.forms, tone)}
                </div>
              ))
            ) : (
              <div className="rr-issue">
                <IssueLine message={c.primary_message} className={`stop-item stop-item-${tone} rr-issue__line`} />
                {renderItemActions({
                  ...(c.items?.[0] || { issue_id: c.issue_id, message: c.primary_message, forms: c.forms }),
                  score_neutral: c.score_neutral,
                }, c.forms, tone)}
              </div>
            )}
          </div>
        )}
      </section>
    );
  };

  // The collapsed Resolved list - closed by default, like the editor's Reviewed.
  // It takes the look of the headings around it (owner, 9 Oct 2026): on
  // Warnings a page-level heading like the tiers ("REQUIRED BEFORE SUBMISSION"
  // ...) with the rows in one card under it; on Hard Stops, which has no tiers,
  // a card like the hard-stop cards beside it. "Open again" is the same chip as
  // "Dismiss", with a turn-back arrow.
  const renderResolved = (rows, tone) => {
    if (!rows || rows.length === 0) return null;
    const key = `resolved:${tone}`;
    const open = foldOpen(key, false);
    const list = (
      <div className="rr-rows">
        {rows.map((r) => {
          const busy = !!reopeningIds?.has?.(r.iid);
          const note = reopenNotices?.get?.(r.iid);
          return (
            <div className="rr-issue" key={r.iid}>
              <IssueLine message={r.item.message} className={`stop-item stop-item-${tone} rr-issue__line`} />
              <div className="rr-resolved__actions">
                <span className={`rr-resolved__label rr-resolved__label--${r.status}`}>
                  {RESOLVED_LABELS[r.status] || RESOLVED_LABELS.resolved}
                </span>
                {dismissedRowPointsText(r, screenPts.cards) && (
                  <span style={{ fontSize: 10, fontWeight: 700, color: "#be185d", whiteSpace: "nowrap" }}>
                    {dismissedRowPointsText(r, screenPts.cards)}
                  </span>
                )}
                {reopenKind(r) === "none" ? (
                  <span className="rr-resolved__gone">{NO_LONGER_APPLIES}</span>
                ) : (
                  <button type="button" className="issue-status-btn rr-resolved__open"
                    disabled={busy || !onReopenIssue}
                    onClick={() => onReopenIssue && onReopenIssue(r, reopenKind(r), tone)}>
                    {!busy && <ReopenIcon />}
                    {busy ? "Opening..." : "Open again"}
                  </button>
                )}
              </div>
              {note && <div className="rr-resolved__note">{note}</div>}
            </div>
          );
        })}
      </div>
    );
    if (tone === "hard") {
      return (
        <section className="rr-panel rr-resolved">
          <FoldButton className="rr-panel__head rr-panel__head--button" open={open} onToggle={() => toggleFold(key, false)}>
            <span className="rr-panel__title">
              Resolved
              <span className="issue-count">{rows.length}</span>
            </span>
          </FoldButton>
          {open && list}
        </section>
      );
    }
    return (
      <div className="rr-tier rr-resolved">
        <FoldButton className="rr-tier__head" open={open} onToggle={() => toggleFold(key, false)}>
          Resolved
          <span className="issue-count">{rows.length}</span>
        </FoldButton>
        {open && <section className="rr-panel">{list}</section>}
      </div>
    );
  };

  const renderBareStops = (messages, tone) => (
    <section className="rr-panel">
      <div className="rr-rows">
        {messages.map((m, i) => (
          <div className="rr-issue" key={i}>
            <BareStopRow message={m} className={`stop-item stop-item-${tone} rr-issue__line`} renderActions={renderItemActions} />
          </div>
        ))}
      </div>
    </section>
  );

  // ── Sections ──────────────────────────────────────────────────────────────────
  const overview = (
    <>
      <PageHead id="overview" title="Review Your Submission"
        description={formsExist
          ? "Your forms are generated. Open one below to make changes."
          : genState === GEN_RUNNING ? GENERATION_RUNNING_TEXT
          : "Resolve what needs your input, then continue to form selection."}
        right={openItems > 0 ? <Badge tone="blue">In Progress</Badge> : <Badge tone="green">All handled</Badge>} />
      <div className="rr-stack">
        {genState === GEN_RUNNING && <div className="rr-note rr-note--blue rr-gen-note">{GENERATION_RUNNING_TEXT}</div>}
        {genState === GEN_INTERRUPTED && (
          <div className="rr-note rr-note--amber rr-gen-note"><strong>{GENERATION_DIDNT_FINISH}.</strong> {GENERATION_DIDNT_FINISH_NEXT}</div>
        )}
        <div className="rr-overview-grid">
          <Panel title="Submission Readiness" right={<span className="rr-panel__meta rr-panel__meta--inline">Updates as you fix items</span>}>
            <div className="rr-ready">
              <div className="rr-gauge">
                <Gauge tierIndex={tierIndex} />
                {soFar && (
                  <div className="rr-gauge__score" style={{ color: tierColor }}>
                    {soFar.score}<span className="rr-gauge__of"> / 100</span>
                  </div>
                )}
                <div className="rr-gauge__tier" style={{ color: tierColor }}>{tierName || "Not scored yet"}</div>
              </div>
              <div className="rr-ready__copy">
                {(keyDetails?.satisfied || keyDetails?.missing) && (
                  <div className="rr-ready__big">
                    {(keyDetails?.satisfied || []).length} of {(keyDetails?.satisfied || []).length + (keyDetails?.missing || []).length} key details in place
                  </div>
                )}
                {soFar && (formsExist
                  ? <div className="rr-ready__note">Total Package Score</div>
                  : <div className="rr-ready__note">Submission Quality Score. Scored from your documents and answers - no forms needed.</div>)}
                {/* Forms ready (Brent, 23 Oct 2026): one score before and after forms;
                    the forms' own to-dos are this meter. "Confirm all" moves it. */}
                {formsMeter && (
                  <div className="rr-ready__note" data-forms-ready="review">
                    <strong>{formsMeter.overall.text}</strong>
                  </div>
                )}
                {(() => {
                  const capNote = railCapNote(packageSqs, {
                    hardOpen, hardTotal: hasHardStops ? hardTally.total : 0,
                    warnOpen, warnTotal: hasWarnings ? warnTally.total : 0,
                    hiddenWarnings: Number(groupedIssues?.hidden_warnings || 0),
                  });
                  return capNote ? <div className="rr-note rr-note--amber" data-still-capped="review">{capNote}</div> : null;
                })()}
                <div className="rr-ladder">
                  {TIER_LADDER.map((t, i) => (
                    <div key={t.name} className={`rr-ladder__row${i === tierIndex ? " is-current" : ""}`}>
                      <i className={tierIndex >= 0 && i <= tierIndex ? "is-on" : ""} />{t.name}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </Panel>
          <Panel title="Your Progress" meta={nextStepText(openItemCount, reviewIssueCounts.hardStopCount, reviewIssueCounts.warningCount, afterForms)}>
            {/* "x of y handled" only while something is left (owner, 13 Oct
                2026): y counts the handled blockers too, so fixing an item
                moves x instead of shrinking y. */}
            {openItems > 0 && (
              <>
                <div className="rr-progress" data-testid="overview-progress">
                  <b>{handledItems} of {totalItems}</b><span>items handled</span>
                </div>
                <div className="rr-bar"><i style={{ width: `${progressPct}%` }} /></div>
              </>
            )}
            <div className="rr-stats">
              {docsOpen > 0 && (
                <button type="button" className="rr-stat" onClick={() => onSectionChange("documents")}>
                  <i />{plural(docsOpen, "document")} to review<span className="rr-stat__go"><ArrowIcon /></span>
                </button>
              )}
              <button type="button" className={`rr-stat${hardOpen ? "" : " is-done"}`}
                onClick={() => onSectionChange("hardstops")}
                data-testid="overview-hard-stops-line">
                <i />{hardOpen ? `${plural(hardOpen, "blocker")} left` : "No blockers left"}<span className="rr-stat__go"><ArrowIcon /></span>
              </button>
              <button type="button" className={`rr-stat${conflictsOpen ? "" : " is-done"}`} onClick={() => onSectionChange("consistency")}>
                <i />{conflictsOpen ? `${plural(conflictsOpen, "value")} to confirm` : (preFormLocked && openConflicts.length ? "Waiting for the forms" : "All values confirmed")}<span className="rr-stat__go"><ArrowIcon /></span>
              </button>
              <button type="button" className={`rr-stat${warnOpen ? "" : " is-done"}`} onClick={() => onSectionChange("warnings")}>
                <i />{warnOpen ? `${plural(warnOpen, "warning")} to review` : "All warnings handled"}<span className="rr-stat__go"><ArrowIcon /></span>
              </button>
              {/* Choice Electric #22 / #27: the one Overview line for the
                  Recommendations section; its count is the section's items. */}
              <button type="button" className={`rr-stat${recModel.count ? "" : " is-done"}`} onClick={() => onSectionChange("recommendations")}
                data-testid="overview-recommendations-link">
                <i />{recModel.count
                  ? `${recommendationsText(recModel.count)} - see Recommendations`
                  : recChecking ? "Checking your forms..." : "No recommendations"}<span className="rr-stat__go"><ArrowIcon /></span>
              </button>
            </div>
          </Panel>
        </div>
        {(keyDetails?.satisfied?.length > 0 || keyDetails?.missing?.length > 0) && (
          <Panel title="Key details" right={<span className="rr-panel__meta rr-panel__meta--inline">Used to calculate readiness</span>}>
            {keyDetails?.satisfied?.length > 0 && <div className="tier2-detail tier2-detail-ok rr-key-line">Key details in place: {keyDetails.satisfied.join(" · ")}</div>}
            <KeyDetailsMissing keyDetails={keyDetails} onFix={onFixKeyDetail} onShowSection={onSectionChange} className="tier2-missing rr-key-line"
              points={screenPts.details} />
            <KeyDetailsResolved keyDetails={keyDetails} issueStatuses={issueStatuses} onReopen={onReopenKeyDetail}
              reopeningIds={reopeningIds} reopenNotices={reopenNotices} />
          </Panel>
        )}
        {genForms.length > 0 && (
          <Panel title="Your forms" right={<span className="rr-panel__meta rr-panel__meta--inline">Each form&apos;s own score</span>} bodyClassName="rr-rows">
            {genForms.map((f) => (
              <div key={f.formId} className="rr-form-row">
                <span className="rr-form-row__name">{f.label}</span>
                <span className="rr-form-row__score" style={{ color: f.score != null ? gradeColor(f.grade || sqsGradeFromScore(f.score)) : "#94a3b8" }}>
                  {f.score != null ? `${f.score}${f.grade ? ` ${f.grade}` : ""}` : "Not scored"}
                </span>
                <span className="rr-form-row__tier">{f.tier || ""}</span>
                {(() => {
                  // This form's part of the Forms ready meter (Brent, 23 Oct 2026).
                  const r = (formsMeter?.forms || []).find((x) => x.form_id === f.formId);
                  return r ? (
                    <span className="rr-form-row__ready" data-forms-ready-form={f.formId}>
                      {r.verify || r.missing ? `${r.verify} to confirm · ${r.missing} to fill` : "Ready"}
                    </span>
                  ) : null;
                })()}
                <button type="button" className="rr-form-row__open" onClick={() => packageGen?.onOpenForm?.(f.formId)}>Open</button>
              </div>
            ))}
          </Panel>
        )}
        <RemediationDiffBand diff={issueDiff} />
        {canProceedWithWarning && warningStops.length > 0 && !afterForms && (
          <div className="stops-banner stops-warning rr-incomplete">
            <div className="stops-title rr-incomplete__title">Incomplete Submission - Review Before Generating</div>
            {warningStops.map((s, i) => (
              <div key={i} className="stop-item rr-incomplete__item">- {positiveScoreWording(s)}</div>
            ))}
            <div className="rr-incomplete__text">
              This submission is missing information typically required for property coverage. Forms can still be generated, but the underwriter may request additional data.
            </div>
          </div>
        )}
      </div>
    </>
  );

  const documents = (
    <>
      <PageHead id="documents" title="Documents"
        description="Check how each document was classified. Exclude files that don't belong, or keep one as supporting only."
        right={docsOpen > 0 ? <Badge tone="pink">{docsOpen} to fix</Badge> : <Badge tone="green">All clear</Badge>} />
      <div className="rr-stack">
        {docLockText
          ? <div className="rr-note rr-note--blue rr-gen-note">{docLockText}</div>
          : formsExist && <div className="rr-note rr-note--blue rr-gen-note">{DOCUMENTS_AFTER_FORMS_NOTE}</div>}
        {/* Brent, 17 Oct 2026 (item 2): the review sentence sits under the
            list's title, in pink - shown while a document still needs its type
            confirmed (`docsNeedingReview`, as in the classic layout: an
            excluded document is done). */}
        <Panel title={`Documents Processed (${docSummary.length})`} bodyClassName="rr-rows"
          meta={<>
            Type, insured and how each file is used
            {docsNeedingReview.length > 0 && (
              <div className="rr-doc-note-review" data-testid="doc-review-note">{DOCUMENTS_REVIEW_NOTE}</div>
            )}
            {lossCoverageNote && (
              <div role="status" data-testid="loss-coverage-note" style={{ marginTop: 4, color: "#166534", fontWeight: 600 }}>{lossCoverageNote}</div>
            )}
          </>}>
          {docSummary.length === 0 && (
            <div className="rr-doc-empty">No document details are available for this submission.</div>
          )}
          {docSummary.map((d, i) => {
            const docType = d.doc_type || "unknown";
            const label = d.doc_type_label || docType.replace(/_/g, " ");
            // The pink row is the counted row (one rule, utils/addDocuments).
            const needsReview = documentNeedsTypeReview(d);
            const excluded = !!d.excluded;
            const supportingOnly = !!d.supporting_only;
            const busy = reclassDocId && reclassDocId === d.doc_id;
            const anyReclassBusy = reclassDocId !== null;
            const reviewBusy = reviewLoadingId === d.doc_id;
            // Two tags, two questions (14 Oct 2026, utils/addDocuments): how sure
            // we are of the TYPE, and - only for another insured's document -
            // whose it is (decided by the server, `insured_status`).
            const typeTag = documentTypeTag(d);
            const insuredTag = documentInsuredTag(d);
            return (
              <div key={d.doc_id || i} className={`rr-doc${needsReview ? " is-review" : ""}${excluded ? " is-excluded" : ""}`}>
                <span className="rr-doc__icon"><FileIcon /></span>
                <div className="rr-doc__main">
                  <div className="rr-doc__name" title={d.filename}>{d.filename}</div>
                  <div className="rr-doc__meta">
                    <span className="doc-type-badge" style={{ textTransform: "capitalize" }}>{label}</span>
                    {typeTag && <span title={typeTag.title} className="rr-doc__conf" style={{ color: typeTag.color }} data-testid="doc-type-tag">{typeTag.label}</span>}
                    {d.reader === "transcriber" && (
                      // An outside ACORD form read by ASG's Transcriber (29 Oct 2026,
                      // ASG_TRANSCRIBER.md): its values are "please verify", like AI values.
                      <span title="ACORD Solutions Group's Transcriber read this form's boxes. Its values are marked for verification."
                            className="rr-doc__conf" style={{ color: "#0f766e" }} data-testid="doc-reader-tag">
                        Read by ACORD Transcriber{d.reader_accuracy != null ? ` - ${Math.round(d.reader_accuracy)}%` : ""}
                      </span>
                    )}
                    <FormValuesLink sessionId={dryRunSessionId} doc={d} />
                    {insuredTag && <span title={insuredTag.title} style={INSURED_TAG_STYLE} data-testid="doc-insured-tag">{insuredTag.label}</span>}
                    {lossRunDocNote(packageSqs?.loss_coverage, d.doc_id) && (
                      <span className="rr-doc__note" data-testid="doc-loss-years">{lossRunDocNote(packageSqs?.loss_coverage, d.doc_id)}</span>
                    )}
                    {excluded && <span className="rr-doc__note">excluded from scoring</span>}
                    {supportingOnly && !excluded && <span className="rr-doc__note" title="Facts contribute, but this document is never treated as the primary source">supporting only</span>}
                  </div>
                </div>
                <div className="rr-doc__actions">
                  {availableDocTypes.length > 0 && !excluded && (
                    <span className="rr-doc__type">
                      <select
                        value={docType}
                        disabled={anyReclassBusy || !!docLockText}
                        onChange={(e) => { if (e.target.value && e.target.value !== docType) onReclassify(d.doc_id, "set_type", e.target.value, "type"); }}
                        title="Correct the document type"
                        aria-label={`Document type for ${d.filename}`}
                        className={`rr-select${busy && reclassBusyBtn === "type" ? " is-busy" : ""}${docLockText ? " is-locked" : ""}`}
                      >
                        {availableDocTypes.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
                      </select>
                      {busy && reclassBusyBtn === "type" && <span className="rr-busy"><Spinner />Updating...</span>}
                    </span>
                  )}
                  {/* "Confirm their document type" (Brent's sentence): the type
                      shown, as it is (22 Oct 2026, as in the classic layout). */}
                  {canConfirmDocumentType(d, availableDocTypes) && (
                    <HoverTip text={CONFIRM_TYPE_TIP} style={{ width: "auto", display: "inline-flex" }}>
                      <button type="button" className={`rr-mini-btn${docLockText ? " is-locked" : ""}`} disabled={anyReclassBusy || !!docLockText}
                        onClick={() => onReclassify(d.doc_id, "set_type", docType, "confirm")} data-testid="doc-confirm-type">
                        {busy && reclassBusyBtn === "confirm" && <Spinner />}{CONFIRM_TYPE_LABEL}
                      </button>
                    </HoverTip>
                  )}
                  <HoverTip text={excluded ? DOC_ACTION_TIPS.include : DOC_ACTION_TIPS.exclude} style={{ width: "auto", display: "inline-flex" }}>
                    <button type="button" className={`rr-mini-btn rr-mini-btn--wide${docLockText ? " is-locked" : ""}`} disabled={anyReclassBusy || !!docLockText}
                      onClick={() => onReclassify(d.doc_id, excluded ? "include" : "exclude", null, "toggle")}>
                      {busy && reclassBusyBtn === "toggle" && <Spinner />}{excluded ? "Include" : "Exclude"}
                    </button>
                  </HoverTip>
                  {!excluded && (
                    <HoverTip text={supportingOnly ? DOC_ACTION_TIPS.supporting_undo : DOC_ACTION_TIPS.supporting_only} style={{ width: "auto", display: "inline-flex" }}>
                      <button type="button" className={`rr-mini-btn${supportingOnly ? " is-on" : ""}${docLockText ? " is-locked" : ""}`} disabled={anyReclassBusy || !!docLockText}
                        onClick={() => onReclassify(d.doc_id, supportingOnly ? "include" : "supporting_only", null, "supporting")}>
                        {busy && reclassBusyBtn === "supporting" && <Spinner />}{supportingOnly ? "Supporting only ✓" : "Supporting only"}
                      </button>
                    </HoverTip>
                  )}
                  <HoverTip text={DOC_ACTION_TIPS.review} style={{ width: "auto", display: "inline-flex" }}>
                    <button type="button" className="rr-mini-btn" disabled={reviewBusy} onClick={() => onReviewData(d.doc_id)}>
                      {reviewBusy && <Spinner />}Review data
                    </button>
                  </HoverTip>
                </div>
              </div>
            );
          })}
        </Panel>
        {typeof renderAddDocuments === "function" && renderAddDocuments()}
      </div>
    </>
  );

  const integritySection = (
    <>
      <PageHead id="integrity" afterForms={afterForms} title="Submission Integrity"
        description="Checks that every uploaded document belongs to the same insured."
        right={integrityStatus === "low" ? <IntegritySeverityChip severity="hard_stop" />
          : integrityStatus === "medium" ? <IntegritySeverityChip severity="warning" />
          : integrityStatus === "high" ? <Badge tone="green">Verified</Badge> : null} />
      <div className="rr-stack rr-integrity">
        {integrityContent || <EmptyState title="No integrity check for this submission." />}
      </div>
    </>
  );

  const consistency = (
    <>
      <PageHead id="consistency" afterForms={afterForms} title="Data Consistency"
        description={openConflicts.length > 0
          ? "Your documents disagree on these values. Confirm the correct one and it is used on every form."
          : dcNeedsConfirm
            ? "Every value your documents disagreed on has been confirmed."
            : "Your documents agree - there is nothing to confirm."}
        right={openConflicts.length > 0 ? <Badge tone="pink">{openConflicts.length} to fix</Badge>
          : <Badge tone="green">{dcNeedsConfirm ? "All confirmed" : "Nothing to confirm"}</Badge>} />
      <div className="rr-stack" ref={dcSectionRef}>
        {dcLockText && openConflicts.length > 0 && <div className="rr-note rr-note--blue rr-gen-note">{dcLockText}</div>}
        {formsExist && openConflicts.length > 0 && (
          <div className="rr-note rr-note--blue rr-gen-note">Confirming a value updates every generated form that prints it and re-scores the package.</div>
        )}
        {!dcHasContent && <EmptyState title="Your documents agree." sub="There are no values to confirm." />}
        {underwritingBusy !== null && (
          <div className="rr-busy-note">
            Confirming and updating everything this value affects - you can prepare any other item, confirming it will apply once this finishes.
          </div>
        )}
        {fields.some((f) => f.status === "conflict" || f.status === "confirmed") && (
          <Panel title="Values to confirm" meta={`${confirmedCount} of ${openConflicts.length + confirmedCount} confirmed`} bodyClassName="rr-rows" className="rr-conf-panel">
            {fields.filter((f) => f.status === "conflict" || f.status === "confirmed").map((f) => {
              const isConflict = f.status === "conflict";
              const isConfirmed = f.status === "confirmed";
              const busy = underwritingBusy === f.fact_key;
              const rowDisabled = busy || !!dcLockText;
              const anyConfirmInFlight = underwritingBusy !== null;
              const picked = underwritingPicks[f.fact_key] ?? "";
              const lineScope = (f.conflict_scope || []).length === 1 ? f.conflict_scope[0] : null;
              const lineScopeLabel = lineScope ? lineLabel(lineScope, lineRecords) : null;
              const formsLabel = (f.forms || []).map((x) => formLabel(x)).join(", ");
              const highlighted = dcHighlight === f.fact_key;
              const confidence = isConflict && f.confidence ? CONFIDENCE_META[f.confidence] : null;
              return (
                <div key={f.fact_key} id={`dc-field-${f.fact_key}`}
                  className={`rr-conf${isConfirmed ? " is-done" : ""}${highlighted ? " is-highlight" : ""}`}>
                  <div className="rr-conf__side">
                    <div className="rr-conf__label">{f.label}</div>
                    {isConflict && <div className="rr-conf__tag">Values differ - confirm</div>}
                    {isConflict && f.row_level && <div className="rr-conf__why">One schedule row - your pick changes only this value on this row.</div>}
                    {isConflict && screenPointsText(screenPts.dc.get(f.fact_key)) && (
                      <div style={{ fontSize: 10, fontWeight: 700, color: "#be185d", marginTop: 2 }}>
                        {screenPointsText(screenPts.dc.get(f.fact_key))}
                      </div>
                    )}
                    {isConflict && f.conflict_reason && <div className="rr-conf__why">{f.conflict_reason}</div>}
                    {confidence && (
                      <span className="rr-conf__pill" style={{ color: confidence.color, background: confidence.bg, borderColor: confidence.border }}>
                        Confidence: {confidence.label}
                      </span>
                    )}
                  </div>
                  <div className="rr-conf__main">
                    {isConfirmed && (
                      <span className="rr-conf__ok"><CheckIcon />Confirmed: {f.confirmed_value}{formsExist && formsLabel ? ` - available for ${formsLabel}` : ""}</span>
                    )}
                    {isConflict && (
                      <>
                        <div className="rr-opts" role="radiogroup" aria-label={f.label}>
                          {(f.values || []).map((v, vi) => (
                            <label key={vi} className={`rr-opt${picked === v.display ? " is-selected" : ""}${rowDisabled ? " is-disabled" : ""}`}>
                              <input
                                type="radio"
                                name={`uw-${f.fact_key}`}
                                checked={picked === v.display}
                                onChange={() => setUnderwritingPicks((p) => ({ ...p, [f.fact_key]: v.display }))}
                                disabled={rowDisabled}
                              />
                              <span className="rr-opt__value">{v.display}</span>
                              <span className="rr-opt__source">
                                <span className="rr-opt__from">from</span> {(v.sources || []).map(sourceLabel).join(", ")}
                                {f.suggested_value != null && v.display === f.suggested_value && <span className="rr-suggested">Suggested</span>}
                              </span>
                            </label>
                          ))}
                        </div>
                        {f.narrative_note && (
                          <div className="rr-note rr-note--amber"><strong>From the submission: </strong>{f.narrative_note}</div>
                        )}
                        {f.linked_fields?.length > 0 && (
                          <div className="rr-linked">Also applies to: {f.linked_fields.map((l) => l.label).join(", ")}</div>
                        )}
                        <div className="rr-conf__actions">
                          <input
                            type="text"
                            className="rr-conf__input"
                            value={picked}
                            disabled={rowDisabled}
                            placeholder="…or type a value"
                            aria-label={`Type a value for ${f.label}`}
                            onChange={(e) => setUnderwritingPicks((p) => ({ ...p, [f.fact_key]: e.target.value }))}
                          />
                          <button type="button" className="rr-conf__btn" disabled={anyConfirmInFlight || !picked || !!dcLockText}
                            onClick={() => onConfirmUnderwriting(f.fact_key, picked, lineScope)}>
                            {busy ? "Confirming…" : (lineScopeLabel ? `Confirm for ${lineScopeLabel}` : "Confirm")}
                          </button>
                        </div>
                      </>
                    )}
                  </div>
                </div>
              );
            })}
          </Panel>
        )}
        {(() => {
          // Editable since 7 Oct 2026 (Brent #9) - `PoliciesTable`; a payload
          // without `policy_lines` keeps the read-only multi-policy table.
          const editableRows = Array.isArray(underwriting?.policy_lines) ? underwriting.policy_lines : null;
          const recs = fields.map((f) => f.line_records).find((r) => (r || []).length > 1) || [];
          // With a session the table reads its rows from the server when the
          // stored assessment predates them, so it is always editable.
          const canEdit = !!editableRows || !!policyTable?.sessionId;
          if (!canEdit && recs.length < 2) return null;
          return (
            <Panel title="Policies in this submission"
              meta={canEdit
                ? "Each coverage line keeps its own carrier and policy number. Correct any value, or add a policy the documents do not show."
                : "Each coverage line keeps its own carrier and policy number. Different numbers across different lines are expected and are not a conflict."}
              bodyClassName="rr-table-wrap">
              <PoliciesTable rows={editableRows} legacyRecs={recs}
                unmatched={underwriting?.unmatched_policy_edits || []}
                sessionId={policyTable?.sessionId} lockText={dcLockText} afterForms={formsExist}
                onBeforeChange={policyTable?.onBeforeChange} onApplied={policyTable?.onApplied}
                lineLabel={(ln) => lineLabel(ln, lineRecords)} />
            </Panel>
          );
        })()}
        {/* Brent #10 (7 Oct 2026): no "N policies, M values - not a conflict"
            blocks for line-scoped values (status "scoped") - they repeated the
            table above. Each policy's carrier is in the table and its own limit
            in the table's Limit column. The backend still computes "scoped"
            (other readers use it); only the display is gone. */}
      </div>
    </>
  );

  const hardStopsSection = (
    <>
      <PageHead id="hardstops" afterForms={afterForms} title="Hard Stops"
        description="Required before submission - fulfill to increase your Submission Quality Score (SQS)™"
        right={hardProg.total > 0
          ? <Badge tone={hardProg.open > 0 ? "pink" : "green"}>{progressText(hardProg)}</Badge>
          : <Badge tone="green">Clear</Badge>} />
      <div className="rr-stack">
        {/* NO "1 warning becomes a hard stop when forms are generated" line
            (owner, 8 Oct 2026). Brent's item 18 ASKED why hard stops appeared
            after generation; he did not ask for the answer to be printed on
            screen. A sentence announcing a future problem, in the one section
            where nothing can be done about it, is not the fix - the fix is
            that the item is actionable BEFORE generation, which is what the
            Recommendations section now carries. (A check now keeps one
            status before and after forms, 14 Oct 2026.) */}
        {/* Positive wording throughout (Choice Electric #16, 9 Oct 2026). */}
        {!hasHardStops && <EmptyState title="No hard stops." sub="Your Submission Quality Score (SQS)™ is clear of hard stops." />}
        {hasHardStops && (groupedHard
          ? (hardSplit.open.length
            ? hardSplit.open.map((c) => renderCluster(c, "hard"))
            : <EmptyState title="No open hard stops."
                sub={hardSplit.handled.length
                  ? "Fix a dismissed hard stop's value to increase your Submission Quality Score (SQS)™."
                  : "Everything here has been handled."} />)
          : renderBareStops(hardStops, "hard"))}
        {renderResolved(hardResolved, "hard")}
      </div>
    </>
  );

  // No "Important" tab or preview (client, 22 Sep, item 3): it repeated the
  // top clusters of the tiers below and read as duplicate items. The backend
  // still sends `important`; nothing here renders it.
  const warningTabs = hasWarnings && groupedIssues?.warnings
    ? [
      { id: "all", label: "All", count: openWarnTotal },
      ...WARNING_TIERS
        .filter((t) => warnSplit[t].open.length > 0)
        .map((t) => ({
          id: t,
          label: groupedIssues.tier_labels?.[t] || WARNING_TIER_FALLBACK_LABELS[t],
          count: openCountOf(warnSplit[t].open),
        })),
    ]
    : [];
  const activeWarnTab = warningTabs.some((t) => t.id === warnTab) ? warnTab : "all";
  // A tab that disappears (its last item dismissed) is forgotten, so it does
  // not re-select itself when an item comes back under it.
  const warnTabIds = warningTabs.map((t) => t.id).join(",");
  useEffect(() => {
    if (warnTab !== "all" && !warnTabIds.split(",").includes(warnTab)) setWarnTab("all");
  }, [warnTab, warnTabIds]);

  const renderTier = (tier, fallbackOpen) => {
    const clusters = warnSplit[tier]?.open || [];
    if (clusters.length === 0) return null;
    const total = openCountOf(clusters);
    const key = `tier:${activeWarnTab}:${tier}`;
    const open = foldOpen(key, fallbackOpen);
    return (
      <div className="rr-tier" key={tier}>
        <FoldButton className="rr-tier__head" open={open} onToggle={() => toggleFold(key, fallbackOpen)}>
          {groupedIssues.tier_labels?.[tier] || WARNING_TIER_FALLBACK_LABELS[tier]}
          <span className="issue-count">{total}</span>
        </FoldButton>
        {open && clusters.map((c) => renderCluster(c, "soft"))}
      </div>
    );
  };

  const warningsSection = (
    <>
      <PageHead id="warnings" afterForms={afterForms} title="Warnings" description="Fulfill to increase your Submission Quality Score (SQS)™"
        right={warnProg.total > 0
          ? <Badge tone={warnProg.open > 0 ? "pink" : "green"}>{progressText(warnProg)}</Badge>
          : <Badge tone="green">Clear</Badge>} />
      {warningTabs.length > 1 && (
        <div className="rr-tabs" role="group" aria-label="Warning groups">
          {warningTabs.map((t) => (
            <button key={t.id} type="button" className={`rr-tab${activeWarnTab === t.id ? " is-active" : ""}`}
              aria-pressed={activeWarnTab === t.id} onClick={() => setWarnTab(t.id)}>
              {t.label}<span className="issue-count">{t.count}</span>
            </button>
          ))}
        </div>
      )}
      <div className="rr-stack">
        {!hasWarnings && <EmptyState title="No warnings." sub="Your Submission Quality Score (SQS)™ is clear of warnings." />}
        {hasWarnings && !groupedIssues?.warnings && renderBareStops(softStops, "soft")}
        {hasWarnings && groupedIssues?.warnings && openWarnTotal === 0 && openInfoTotal === 0 && (
          <EmptyState title="No open warnings."
            sub={WARNING_TIERS.some((t) => warnSplit[t].handled.length)
              ? "Fix a dismissed warning's value to increase your Submission Quality Score (SQS)™."
              : "Everything here has been handled."} />
        )}
        {hasWarnings && groupedIssues?.warnings && (openWarnTotal > 0 || openInfoTotal > 0) && (
          activeWarnTab === "all"
            ? WARNING_TIERS.map((t) => renderTier(t, t === "required"))
            : renderTier(activeWarnTab, true)
        )}
        {renderResolved(warnResolved, "soft")}
      </div>
    </>
  );

  // Choice Electric #22 / #27 (7 Oct 2026): what raises the score and what the
  // forms will need, before (and independently of) the forms.
  const recommendationsSection = (
    <>
      <PageHead id="recommendations" afterForms={afterForms} title="Recommendations"
        description="Optional to-dos that raise your score or complete your forms. None of them stops you."
        right={recModel.count > 0 ? <Badge tone="blue">{considerText(recModel)}</Badge>
          : recChecking ? null : <Badge tone="green">Nothing to add</Badge>} />
      <div className="rr-stack">
        <Recommendations model={recModel} attention={recAttention} packageSqs={packageSqs}
          screenUnanswerable={screenPts.unanswerable}
          onAddDocuments={() => onSectionChange("documents")}
          dryRun={dryRun} sessionId={dryRunSessionId} tickedFormIds={dryRunFormIds || []}
          onDryRunUpdate={onDryRunUpdate} onOpenDryRunFix={onFixDryRunItem}
          onOpenScoreFix={onFixScoreItem} onAddForm={onAddForm} formOffers={formOffers} onAddOffer={onAddOffer}
          onOpenForm={onOpenFormAt || (packageGen?.onOpenForm ? (formId) => packageGen.onOpenForm(formId) : undefined)}
          formsExist={formsExist} generating={genState === GEN_RUNNING}
          issueStatuses={issueStatuses} onReopenResolved={onReopenRecommendation}
          reopeningIds={reopeningIds} reopenNotices={reopenNotices} />
      </div>
    </>
  );

  // The narrative questionnaire (owner, 23 Oct 2026): what the documents
  // say, to confirm, and what is missing, to answer - before and after forms.
  const questionnaireSection = (
    <>
      <PageHead id="questionnaire" afterForms={afterForms} title={QUESTIONNAIRE_TITLE}
        description={QUESTIONNAIRE_DESC} />
      <QuestionnairePage sessionId={dryRunSessionId} model={questionnaire?.model || null}
        error={!!questionnaire?.error} onReload={questionnaire?.reload}
        active={section === "questionnaire"} focus={questionnaireFocus || null}
        onAnswered={questionnaire?.applyQuestion || (() => {})}
        onNarrative={questionnaire?.applyNarrative || (() => {})}
        onApplied={onQuestionnaireApplied} lockedText={dcLockText} />
    </>
  );

  const sectionBodies = {
    overview,
    documents,
    integrity: integritySection,
    consistency,
    hardstops: hardStopsSection,
    warnings: warningsSection,
    recommendations: recommendationsSection,
    questionnaire: questionnaireSection,
  };

  return (
    <div className="rr-layout" ref={layoutRef}>
      <aside className="rr-rail" aria-label="Review sections" data-header-autohide="off">
        <div className="rr-package">
          <div className="rr-package__label">Package</div>
          <div className="rr-package__name" title={packageName}>{packageName}</div>
          <div className="rr-package__meta">
            {plural(docSummary.length, "document")}{policyCount > 0 ? ` · ${policyCount} ${policyCount === 1 ? "policy" : "policies"}` : ""}
          </div>
        </div>
        <nav className="rr-nav" ref={navRef}>
          <div className="rr-nav__group">Review</div>
          {navItems.slice(0, 2).map(renderNavItem)}
          <div className="rr-nav__group">{afterForms ? FIX_GROUP_AFTER_FORMS : FIX_GROUP}</div>
          {navItems.slice(2).map(renderNavItem)}
        </nav>
        <div className="rr-rail-foot">
          <div className="rr-rail-foot__label">{scoreHeading(genState)}</div>
          <div className="rr-rail-foot__tier" style={{ color: soFar ? tierColor : "#a1a1aa" }}>{soFar ? soFar.text : "Not scored yet"}</div>
          {/* Under 100 with only optional rows left, the footer says so - never
              "Everything handled" beside an 88 (owner, 24 Oct 2026). */}
          <div className="rr-rail-foot__sub">{openItems > 0 ? `${plural(openItems, "item")} to go`
            : recModel.count > 0 ? considerText(recModel) : "Everything handled"}</div>
          <div className="rr-rail-foot__bar"><i style={{ width: `${progressPct}%` }} /></div>
        </div>
      </aside>

      <div className="rr-main">
        <div className="rr-content">
          {banners}
          {SECTIONS.map((s) => (
            <div key={s.id} className="rr-section" hidden={section !== s.id} data-section={s.id}>
              {sectionBodies[s.id]}
            </div>
          ))}
        </div>
        <div className="rr-footer" ref={footerRef}>
          <div className="rr-footer__inner">
            {openItems > 0 && (
              <span className="step-footer-note">
                {plural(openItems, "item")} still need{openItems === 1 ? "s" : ""} your input. You can continue and come back.
              </span>
            )}
            {/* Before forms the main button walks the pages in rail order and
                only the last page's goes to form selection; "Skip to form
                selection" sits beside it until then (Choice Electric #2). The
                row is the form-selection footer's own (step-footer-*): the skip
                is sized and coloured like its "Back to review", the main button
                takes the rest (owner, 9 Oct 2026). The skip slot comes first,
                so the main button stays the same element from page to page and
                keeps keyboard focus. */}
            <div className="step-footer-buttons rr-footer__buttons">
              {step && (
                <button type="button" className="btn btn-modal-primary step-footer-back rr-footer__skip"
                  onClick={(e) => { if (e.detail > 1) return; onContinue(); }}>
                  {SKIP_TO_SELECTION}
                </button>
              )}
              {/* One page per press: the second click of a double-click (detail
                  2) is ignored - it would land on the NEXT page's button, and
                  from Warnings leave the review before Recommendations showed.
                  A key press has detail 0 and always counts. */}
              <button type="button" className="btn btn-modal-primary btn-large step-footer-primary rr-footer__next"
                onClick={(e) => { if (e.detail > 1) return; if (step) onSectionChange(step.id); else onContinue(); }}>
                {step ? <>{step.label}<ArrowIcon /></> : continueLabel(genState)}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
