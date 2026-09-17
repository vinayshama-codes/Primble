import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { gradeColor, sqsGradeFromScore } from "../../../utils/formatters";
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
// All six sections stay mounted and inactive ones are hidden, so collapse
// choices, typed values and the Data Consistency jump target survive switching.

const SECTIONS = [
  { id: "overview", label: "Overview", group: "Review" },
  { id: "documents", label: "Documents", group: "Review" },
  { id: "integrity", label: "Submission Integrity", group: "Fix before selecting forms" },
  { id: "consistency", label: "Data Consistency", group: "Fix before selecting forms" },
  { id: "hardstops", label: "Hard Stops", group: "Fix before selecting forms" },
  { id: "warnings", label: "Warnings", group: "Fix before selecting forms" },
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
function tallyClusters(clusters, issueStatuses, issueIdOf) {
  let total = 0;
  let done = 0;
  for (const c of clusters || []) {
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
function nextStepText(openItemCount, hardStopCount, warningCount) {
  const advisory = [
    hardStopCount > 0 ? plural(hardStopCount, "hard stop") : null,
    warningCount > 0 ? plural(warningCount, "warning") : null,
  ].filter(Boolean).join(" and ");
  const n = openItemCount;
  if (n > 0 && advisory) return `${plural(n, "item")} need${n === 1 ? "s" : ""} your input below, plus ${advisory} to review`;
  if (n > 0) return `${plural(n, "item")} need${n === 1 ? "s" : ""} your input below`;
  if (advisory) return `Review ${advisory} below before continuing`;
  return "Nothing needs your attention - continue to form selection";
}

// Live Data Consistency date normaliser: one format per table.
function normaliseDate(s) {
  const t = String(s || "").trim();
  let m = /^(\d{1,2})[/.-](\d{1,2})[/.-](\d{2}|\d{4})$/.exec(t);
  if (m) {
    const y = m[3].length === 2 ? `${Number(m[3]) > 69 ? "19" : "20"}${m[3]}` : m[3];
    return `${m[1].padStart(2, "0")}/${m[2].padStart(2, "0")}/${y}`;
  }
  m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(t);
  return m ? `${m[2]}/${m[3]}/${m[1]}` : s;
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

function Spinner() {
  return <span className="rr-spinner" aria-hidden="true" />;
}

function Badge({ tone, children }) {
  return <span className={`rr-badge rr-badge--${tone}`}>{children}</span>;
}

function PageHead({ id, title, description, right }) {
  const section = SECTIONS.find((s) => s.id === id);
  return (
    <header className="rr-page-head">
      <div className="rr-page-head__text">
        <div className="rr-eyebrow">{section.group}</div>
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
    onReclassify, onReviewData,
    underwriting, openConflicts, underwritingPicks, setUnderwritingPicks, underwritingBusy, onConfirmUnderwriting,
    dcHighlight, dcSectionRef,
    groupedIssues, hardStops, softStops, issueStatuses, reviewIssueCounts, hasHardStops, hasWarnings,
    renderItemActions, renderClusterRollup,
    issueDiff, canProceedWithWarning, warningStops,
    openItemCount, onContinue,
  } = props;
  const {
    IssueLine, BareStopRow, HoverTip, ScoreNeutralNote, RemediationDiffBand, IntegritySeverityChip,
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
    let headerOffset = 0;
    const applyScrollPadding = () => {
      root.style.scrollPaddingTop = `${headerOffset + (phone.matches ? 68 : 12)}px`;
      root.style.scrollPaddingBottom = `${(footer ? footer.offsetHeight : 0) + 12}px`;
    };
    const onHeader = (e) => {
      const { height, hidden } = e.detail || {};
      if (!layout || typeof height !== "number") return;
      headerOffset = hidden ? 0 : height;
      layout.style.setProperty("--rr-header-h", `${height}px`);
      layout.style.setProperty("--rr-header-offset", `${headerOffset}px`);
      applyScrollPadding();
    };
    const onFooter = () => {
      if (footer) root.style.setProperty("--rr-footer-h", `${footer.offsetHeight}px`);
      applyScrollPadding();
    };
    window.addEventListener("app-header:change", onHeader);
    window.dispatchEvent(new Event("app-header:request"));
    onFooter();
    const ro = typeof ResizeObserver !== "undefined" && footer ? new ResizeObserver(onFooter) : null;
    if (ro) ro.observe(footer);
    phone.addEventListener("change", applyScrollPadding);
    return () => {
      window.removeEventListener("app-header:change", onHeader);
      if (ro) ro.disconnect();
      phone.removeEventListener("change", applyScrollPadding);
      root.style.removeProperty("--rr-footer-h");
      root.style.removeProperty("scroll-padding-top");
      root.style.removeProperty("scroll-padding-bottom");
    };
  }, []);

  // On the phone tab bar, bring the active section into view by scrolling the
  // bar only (scrollIntoView would also move the page).
  useEffect(() => {
    const bar = navRef.current;
    if (!bar || bar.scrollWidth <= bar.clientWidth) return;
    const active = bar.querySelector('[aria-current="page"]');
    if (active) bar.scrollLeft = Math.max(0, active.offsetLeft - (bar.clientWidth - active.offsetWidth) / 2);
  }, [section]);

  // ── Derived numbers (one place, used by the rail, the Overview and the footer) ─
  const fields = underwriting?.fields || [];
  const confirmedCount = fields.filter((f) => f.status === "confirmed").length;
  const dcHasContent = fields.some((f) => ["conflict", "confirmed", "scoped", "changed"].includes(f.status));

  const groupedHard = groupedIssues?.hard_stops?.length > 0 ? groupedIssues.hard_stops : null;
  const hardTally = groupedHard ? tallyClusters(groupedHard, issueStatuses, issueIdOf) : tallyBare(hardStops, issueStatuses, issueIdOf);
  const warningClusters = groupedIssues?.warnings ? WARNING_TIERS.flatMap((t) => groupedIssues.warnings[t] || []) : null;
  const warnTally = warningClusters ? tallyClusters(warningClusters, issueStatuses, issueIdOf) : tallyBare(softStops, issueStatuses, issueIdOf);
  const hardOpen = hasHardStops ? hardTally.open : 0;
  const warnOpen = hasWarnings ? warnTally.open : 0;

  const docsOpen = docsNeedingReview.length;
  const totalItems = docsOpen + openConflicts.length + confirmedCount + (hasHardStops ? hardTally.total : 0) + (hasWarnings ? warnTally.total : 0);
  const handledItems = confirmedCount + (hasHardStops ? hardTally.done : 0) + (hasWarnings ? warnTally.done : 0);
  const openItems = Math.max(0, totalItems - handledItems);
  const progressPct = totalItems > 0 ? Math.round((handledItems / totalItems) * 100) : 100;

  const tierName = packageSqs?.tier || null;
  const tierIndex = tierName ? TIER_LADDER.findIndex((t) => t.name === tierName) : -1;
  const tierColor = tierName ? gradeColor(sqsGradeFromScore(packageSqs.package_sqs_score)) : "#64748b";

  const integrityStatus = integrity?.status;
  const integrityContent = renderIntegrityStatus();

  const applicantField = fields.find((f) => f.fact_key === "applicant_name");
  const packageName = applicantField?.confirmed_value
    || applicantField?.values?.[0]?.display
    || (integrity?.documents || []).find((d) => d.applicant)?.applicant
    || "Current submission";
  const lineRecords = fields.map((f) => f.line_records).find((r) => (r || []).length > 0) || [];
  const policyCount = new Set(lineRecords.map((r) => r.policy_number || r.id || r.line)).size;

  // ── Rail ──────────────────────────────────────────────────────────────────────
  const navItems = [
    { id: "overview", sub: `${handledItems} of ${totalItems} handled`, badge: null },
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
      sub: openConflicts.length > 0 ? `${plural(openConflicts.length, "value")} to confirm` : dcHasContent ? "All confirmed" : "Nothing to confirm",
      badge: openConflicts.length > 0 ? openConflicts.length : "done",
    },
    {
      id: "hardstops",
      sub: !hasHardStops ? "None" : hardOpen > 0 ? `${hardOpen} need${hardOpen === 1 ? "s" : ""} attention` : "All handled",
      badge: hardOpen > 0 ? hardOpen : "done",
    },
    {
      id: "warnings",
      sub: !hasWarnings ? "None" : warnOpen > 0 ? `${warnOpen} to review` : "All handled",
      badge: warnOpen > 0 ? warnOpen : "done",
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
                  {renderItemActions(it, c.forms)}
                </div>
              ))
            ) : (
              <div className="rr-issue">
                <IssueLine message={c.primary_message} className={`stop-item stop-item-${tone} rr-issue__line`} />
                {renderItemActions({
                  ...(c.items?.[0] || { issue_id: c.issue_id, message: c.primary_message, forms: c.forms }),
                  score_neutral: c.score_neutral,
                }, c.forms)}
              </div>
            )}
          </div>
        )}
      </section>
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
        description="Resolve what needs your input, then continue to form selection."
        right={openItems > 0 ? <Badge tone="blue">In Progress</Badge> : <Badge tone="green">All handled</Badge>} />
      <div className="rr-stack">
        <div className="rr-overview-grid">
          <Panel title="Submission Readiness" right={<span className="rr-panel__meta rr-panel__meta--inline">Updates as you fix items</span>}>
            <div className="rr-ready">
              <div className="rr-gauge">
                <Gauge tierIndex={tierIndex} />
                <div className="rr-gauge__tier" style={{ color: tierColor }}>{tierName || "Not scored yet"}</div>
              </div>
              <div className="rr-ready__copy">
                {(keyDetails?.satisfied || keyDetails?.missing) && (
                  <div className="rr-ready__big">
                    {(keyDetails?.satisfied || []).length} of {(keyDetails?.satisfied || []).length + (keyDetails?.missing || []).length} key details in place
                  </div>
                )}
                <div className="rr-ready__note">Your Submission Quality Score is calculated after forms are generated.</div>
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
          <Panel title="Your Progress" meta={nextStepText(openItemCount, reviewIssueCounts.hardStopCount, reviewIssueCounts.warningCount)}>
            <div className="rr-progress">
              <b>{handledItems} of {totalItems}</b><span>items handled</span>
            </div>
            <div className="rr-bar"><i style={{ width: `${progressPct}%` }} /></div>
            <div className="rr-stats">
              {docsOpen > 0 && (
                <button type="button" className="rr-stat" onClick={() => onSectionChange("documents")}>
                  <i />{plural(docsOpen, "document")} to review<span className="rr-stat__go"><ArrowIcon /></span>
                </button>
              )}
              <button type="button" className={`rr-stat${hardOpen ? "" : " is-done"}`} onClick={() => onSectionChange("hardstops")}>
                <i />{hardOpen ? `${plural(hardOpen, "blocker")} left` : "No blockers left"}<span className="rr-stat__go"><ArrowIcon /></span>
              </button>
              <button type="button" className={`rr-stat${openConflicts.length ? "" : " is-done"}`} onClick={() => onSectionChange("consistency")}>
                <i />{openConflicts.length ? `${plural(openConflicts.length, "value")} to confirm` : "All values confirmed"}<span className="rr-stat__go"><ArrowIcon /></span>
              </button>
              <button type="button" className={`rr-stat${warnOpen ? "" : " is-done"}`} onClick={() => onSectionChange("warnings")}>
                <i />{warnOpen ? `${plural(warnOpen, "warning")} to review` : "All warnings handled"}<span className="rr-stat__go"><ArrowIcon /></span>
              </button>
            </div>
          </Panel>
        </div>
        {(keyDetails?.satisfied?.length > 0 || keyDetails?.missing?.length > 0) && (
          <Panel title="Key details" right={<span className="rr-panel__meta rr-panel__meta--inline">Used to calculate readiness</span>}>
            {keyDetails?.satisfied?.length > 0 && <div className="tier2-detail tier2-detail-ok rr-key-line">Key details in place: {keyDetails.satisfied.join(" · ")}</div>}
            {keyDetails?.missing?.length > 0 && <div className="tier2-missing rr-key-line">Key details missing: {keyDetails.missing.join(" · ")}</div>}
          </Panel>
        )}
        <RemediationDiffBand diff={issueDiff} />
        {canProceedWithWarning && warningStops.length > 0 && (
          <div className="stops-banner stops-warning rr-incomplete">
            <div className="stops-title rr-incomplete__title">Incomplete Submission - Review Before Generating</div>
            {warningStops.map((s, i) => (
              <div key={i} className="stop-item rr-incomplete__item">- {s}</div>
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
        <Panel title={`Documents Processed (${docSummary.length})`} meta="Type, match strength and how each file is used" bodyClassName="rr-rows">
          {docSummary.length === 0 && (
            <div className="rr-doc-empty">No document details are available for this submission.</div>
          )}
          {docSummary.map((d, i) => {
            const docType = d.doc_type || "unknown";
            const label = d.doc_type_label || docType.replace(/_/g, " ");
            const conf = d.doc_type_confidence || "";
            const isUnknown = docType === "unknown";
            const needsReview = isUnknown || conf === "low" || d.doc_type_source === "filename";
            const excluded = !!d.excluded;
            const supportingOnly = !!d.supporting_only;
            const busy = reclassDocId && reclassDocId === d.doc_id;
            const anyReclassBusy = reclassDocId !== null;
            const reviewBusy = reviewLoadingId === d.doc_id;
            const confColor = conf === "high" ? "#16a34a" : conf === "medium" ? "#d97706" : "#dc2626";
            const confLabel = conf === "high" ? "Strong match" : conf === "medium" ? "Likely match" : "Needs review";
            return (
              <div key={d.doc_id || i} className={`rr-doc${needsReview ? " is-review" : ""}${excluded ? " is-excluded" : ""}`}>
                <span className="rr-doc__icon"><FileIcon /></span>
                <div className="rr-doc__main">
                  <div className="rr-doc__name" title={d.filename}>{d.filename}</div>
                  <div className="rr-doc__meta">
                    <span className="doc-type-badge" style={{ textTransform: "capitalize" }}>{label}</span>
                    {d.doc_type_overridden
                      ? <span title="You set this type" className="rr-doc__conf" style={{ color: "#2563eb", fontWeight: 600 }}>you set this</span>
                      : conf && <span title={`How confident Primble is about this document's type: ${confLabel}`} className="rr-doc__conf" style={{ color: confColor }}>{confLabel}</span>}
                    {excluded && <span className="rr-doc__note">excluded from scoring</span>}
                    {supportingOnly && !excluded && <span className="rr-doc__note" title="Facts contribute, but this document is never treated as the primary source">supporting only</span>}
                  </div>
                </div>
                <div className="rr-doc__actions">
                  {availableDocTypes.length > 0 && !excluded && (
                    <span className="rr-doc__type">
                      <select
                        value={docType}
                        disabled={anyReclassBusy}
                        onChange={(e) => { if (e.target.value && e.target.value !== docType) onReclassify(d.doc_id, "set_type", e.target.value, "type"); }}
                        title="Correct the document type"
                        aria-label={`Document type for ${d.filename}`}
                        className={`rr-select${busy && reclassBusyBtn === "type" ? " is-busy" : ""}`}
                      >
                        {availableDocTypes.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
                      </select>
                      {busy && reclassBusyBtn === "type" && <span className="rr-busy"><Spinner />Updating...</span>}
                    </span>
                  )}
                  <HoverTip text={excluded ? DOC_ACTION_TIPS.include : DOC_ACTION_TIPS.exclude} style={{ width: "auto", display: "inline-flex" }}>
                    <button type="button" className="rr-mini-btn rr-mini-btn--wide" disabled={anyReclassBusy}
                      onClick={() => onReclassify(d.doc_id, excluded ? "include" : "exclude", null, "toggle")}>
                      {busy && reclassBusyBtn === "toggle" && <Spinner />}{excluded ? "Include" : "Exclude"}
                    </button>
                  </HoverTip>
                  {!excluded && (
                    <HoverTip text={supportingOnly ? DOC_ACTION_TIPS.supporting_undo : DOC_ACTION_TIPS.supporting_only} style={{ width: "auto", display: "inline-flex" }}>
                      <button type="button" className={`rr-mini-btn${supportingOnly ? " is-on" : ""}`} disabled={anyReclassBusy}
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
        {docSummary.some((d) => (d.doc_type || "unknown") === "unknown" || d.doc_type_confidence === "low") && (
          <div className="rr-doc-note-review">
            Some documents need review. Set the correct type so scoring and form recommendations use them - or exclude documents that don't belong.
          </div>
        )}
      </div>
    </>
  );

  const integritySection = (
    <>
      <PageHead id="integrity" title="Submission Integrity"
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
      <PageHead id="consistency" title="Data Consistency"
        description="Your documents disagree on these values. Confirm the correct one and it is used on every form."
        right={openConflicts.length > 0 ? <Badge tone="pink">{openConflicts.length} to fix</Badge> : <Badge tone="green">All confirmed</Badge>} />
      <div className="rr-stack" ref={dcSectionRef}>
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
              const rowDisabled = busy;
              const anyConfirmInFlight = underwritingBusy !== null;
              const picked = underwritingPicks[f.fact_key] ?? "";
              const lineScope = (f.conflict_scope || []).length === 1 ? f.conflict_scope[0] : null;
              const lineScopeLabel = lineScope ? lineScope.replace(/_/g, " ") : null;
              const formsLabel = (f.forms || []).map((x) => x.replace("ACORD_", "ACORD ")).join(", ");
              const highlighted = dcHighlight === f.fact_key;
              const confidence = isConflict && f.confidence ? CONFIDENCE_META[f.confidence] : null;
              return (
                <div key={f.fact_key} id={`dc-field-${f.fact_key}`}
                  className={`rr-conf${isConfirmed ? " is-done" : ""}${highlighted ? " is-highlight" : ""}`}>
                  <div className="rr-conf__side">
                    <div className="rr-conf__label">{f.label}</div>
                    {isConflict && <div className="rr-conf__tag">Values differ - confirm</div>}
                    {isConflict && f.conflict_reason && <div className="rr-conf__why">{f.conflict_reason}</div>}
                    {confidence && (
                      <span className="rr-conf__pill" style={{ color: confidence.color, background: confidence.bg, borderColor: confidence.border }}>
                        Confidence: {confidence.label}
                      </span>
                    )}
                  </div>
                  <div className="rr-conf__main">
                    {isConfirmed && (
                      <span className="rr-conf__ok"><CheckIcon />Confirmed: {f.confirmed_value}{formsLabel ? ` - available for ${formsLabel}` : ""}</span>
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
                                <span className="rr-opt__from">from</span> {(v.sources || []).map((s) => s.filename).join(", ")}
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
                          <button type="button" className="rr-conf__btn" disabled={anyConfirmInFlight || !picked}
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
          const recs = fields.map((f) => f.line_records).find((r) => (r || []).length > 1) || [];
          if (recs.length < 2) return null;
          return (
            <Panel title="Policies in this submission"
              meta="Each coverage line keeps its own carrier and policy number. Different numbers across different lines are expected and are not a conflict."
              bodyClassName="rr-table-wrap">
              <table className="rr-table">
                <thead>
                  <tr><th>Line</th><th>Carrier</th><th>NAIC</th><th>Policy number</th><th>Term</th><th>Source</th></tr>
                </thead>
                <tbody>
                  {recs.map((r, i) => (
                    <tr key={i}>
                      <td>{r.line_printed || (r.line || "").replace(/_/g, " ")}</td>
                      <td>{r.carrier_name || "-"}</td>
                      <td>{r.carrier_naic || "-"}</td>
                      <td>{r.policy_number || "-"}</td>
                      <td>{r.effective_date || r.expiration_date ? `${normaliseDate(r.effective_date) || "?"} - ${normaliseDate(r.expiration_date) || "?"}` : "-"}</td>
                      <td className="rr-table__source">{[...new Set(r.sources || [])].join(", ") || "-"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Panel>
          );
        })()}
        {fields.filter((f) => f.status === "scoped").map((f) => {
          const vals = f.values || [];
          const lines = new Set(vals.flatMap((v) => (Array.isArray(v.scope) ? v.scope : [])));
          const allRecs = fields.map((x) => x.line_records).find((r) => (r || []).length) || [];
          const recs = allRecs.filter((r) => lines.has(r.line));
          const contracts = recs.length ? new Set(recs.map((r) => r.policy_number || r.id || r.line)).size : lines.size;
          const policies = contracts + vals.filter((v) => !(Array.isArray(v.scope) && v.scope.length)).length;
          return (
            <Panel key={`scoped-${f.fact_key}`}
              title={<>{f.label}<span className="rr-scope-tag">{`${policies} ${policies === 1 ? "policy" : "policies"}, ${vals.length} ${vals.length === 1 ? "value" : "values"} - not a conflict`}</span></>}
              meta={Object.keys(f.confirmed_scopes || {}).length > 0
                ? <span className="rr-scope-confirmed">Confirmed: {Object.entries(f.confirmed_scopes).map(([ln, val]) => `${ln.replace(/_/g, " ")} - ${val}`).join("; ")}</span>
                : null}
              bodyClassName="rr-rows">
              {vals.map((v, vi) => (
                <div key={vi} className="rr-scoped">
                  <span className="rr-scoped__value">{v.display}</span>
                  {(v.scope || []).length > 0
                    ? <span className="rr-scope-chip">{v.scope.join(" / ").replace(/_/g, " ")}</span>
                    : <span className="rr-scope-chip rr-scope-chip--unmatched">not matched to a coverage line</span>}
                  <span className="rr-scoped__source">{[...new Set((v.sources || []).map((sr) => sr.filename).filter(Boolean))].join(", ")}</span>
                </div>
              ))}
            </Panel>
          );
        })}
        {fields.filter((f) => f.status === "changed").map((f) => (
          <Panel key={`changed-${f.fact_key}`}
            title={<>{f.label}<span className="rr-scope-tag">Changed during the policy term - not a conflict</span></>}>
            {f.change && (
              <div className="rr-changed">
                <div>
                  <span className="rr-changed__now">Now: {f.change.current}</span>
                  {f.change.as_of ? ` - effective ${f.change.as_of}` : ""}
                  {f.change.document ? <span className="rr-muted">{` (${f.change.document})`}</span> : null}
                </div>
                <div>
                  Before: {f.change.prior}
                  {(f.change.prior_documents || []).length > 0 ? <span className="rr-muted">{` (${f.change.prior_documents.join(", ")})`}</span> : null}
                </div>
              </div>
            )}
            {f.narrative_note && (
              <div className="rr-note rr-note--blue"><strong>From the submission: </strong>{f.narrative_note}</div>
            )}
          </Panel>
        ))}
      </div>
    </>
  );

  const hardStopsSection = (
    <>
      <PageHead id="hardstops" title="Hard Stops"
        description="Required before submission - Caps your Submission Quality Score (SQS) at 60"
        right={hasHardStops
          ? <Badge tone={hardTally.open > 0 ? "pink" : "green"}>{progressText(hardTally)}</Badge>
          : <Badge tone="green">Clear</Badge>} />
      <div className="rr-stack">
        {!hasHardStops && <EmptyState title="No hard stops." sub="Nothing is holding your score at 60." />}
        {hasHardStops && (groupedHard
          ? groupedHard.map((c) => renderCluster(c, "hard"))
          : renderBareStops(hardStops, "hard"))}
      </div>
    </>
  );

  const importantClusters = groupedIssues?.important || [];
  const warningTabs = hasWarnings && groupedIssues?.warnings
    ? [
      { id: "all", label: "All", count: reviewIssueCounts.warningCount },
      ...(importantClusters.length > 0 ? [{ id: "important", label: "Important", count: importantClusters.length }] : []),
      ...WARNING_TIERS
        .filter((t) => (groupedIssues.warnings[t] || []).length > 0)
        .map((t) => ({
          id: t,
          label: groupedIssues.tier_labels?.[t] || WARNING_TIER_FALLBACK_LABELS[t],
          count: groupedIssues.warnings[t].reduce((n, c) => n + (Number(c.count) || 0), 0),
        })),
    ]
    : [];
  const activeWarnTab = warningTabs.some((t) => t.id === warnTab) ? warnTab : "all";

  const renderImportant = () => {
    if (importantClusters.length === 0) return null;
    const key = "important";
    const open = foldOpen(key, true);
    return (
      <section className="rr-panel">
        <FoldButton className="rr-panel__head rr-panel__head--button" open={open} onToggle={() => toggleFold(key, true)}>
          <span className="rr-panel__head-text">
            <span className="rr-panel__title rr-panel__title--pink">Important</span>
            <span className="rr-panel__meta">The warnings to look at first. Their actions are in the groups below.</span>
          </span>
        </FoldButton>
        {open && (
          <div className="rr-rows">
            {importantClusters.map((c, i) => (
              <div className="rr-issue" key={i}>
                <IssueLine
                  message={c.count > 1 ? `${c.primary_message} (+${c.count - 1} related)` : c.primary_message}
                  className="stop-item stop-item-soft rr-issue__line"
                />
                <ScoreNeutralNote show={c.score_neutral} />
              </div>
            ))}
          </div>
        )}
      </section>
    );
  };

  const renderTier = (tier, fallbackOpen) => {
    const clusters = groupedIssues.warnings[tier] || [];
    if (clusters.length === 0) return null;
    const total = clusters.reduce((n, c) => n + (Number(c.count) || 0), 0);
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
      <PageHead id="warnings" title="Warnings" description="Caps your Submission Quality Score (SQS) at 85"
        right={hasWarnings
          ? <Badge tone={warnTally.open > 0 ? "pink" : "green"}>{progressText(warnTally)}</Badge>
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
        {!hasWarnings && <EmptyState title="No warnings." sub="Nothing is holding your score at 85." />}
        {hasWarnings && !groupedIssues?.warnings && renderBareStops(softStops, "soft")}
        {hasWarnings && groupedIssues?.warnings && (
          activeWarnTab === "all" ? (
            <>
              {renderImportant()}
              {WARNING_TIERS.map((t) => renderTier(t, t === "required"))}
            </>
          ) : activeWarnTab === "important" ? renderImportant() : renderTier(activeWarnTab, true)
        )}
      </div>
    </>
  );

  const sectionBodies = {
    overview,
    documents,
    integrity: integritySection,
    consistency,
    hardstops: hardStopsSection,
    warnings: warningsSection,
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
          <div className="rr-nav__group">Fix before selecting forms</div>
          {navItems.slice(2).map(renderNavItem)}
        </nav>
        <div className="rr-rail-foot">
          <div className="rr-rail-foot__label">Submission readiness</div>
          <div className="rr-rail-foot__tier" style={{ color: tierName ? tierColor : "#a1a1aa" }}>{tierName || "Not scored yet"}</div>
          <div className="rr-rail-foot__sub">{openItems > 0 ? `${plural(openItems, "item")} to go` : "Everything handled"}</div>
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
            <button type="button" className="btn btn-modal-primary btn-block btn-large" onClick={onContinue}>
              Continue to form selection
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
