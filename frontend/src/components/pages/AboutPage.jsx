import { useState } from "react";

const FORMS_DATA = [
  { form: "ACORD 25", name: "Certificate of Liability Insurance", status: "available" },
  { form: "ACORD 125", name: "Commercial Insurance Application", status: "available" },
  { form: "ACORD 126", name: "Commercial General Liability Section", status: "available" },
  { form: "ACORD 140", name: "Property Section", status: "available" },
  { form: "Additional forms", name: "Expanded template library", status: "coming" },
];

export default function AboutPage({ onGetStarted, onNavigate }) {
  const [hoveredRow, setHoveredRow] = useState(null);

  return (
    <main className="mkt-page">

      {/* HERO */}
      <section className="mkt-hero">
        <div className="mkt-hero-eyebrow">About Acordly</div>
        <h1 className="mkt-hero-h1">
          Source document to ACORD package.<br />
          <span className="mkt-hero-accent">No manual re-entry.</span>
        </h1>
        <p className="mkt-hero-p">
          Built for brokers, independent agents, and underwriting teams who spend hours re-keying data that already exists in documents they've already received.
        </p>
        <div className="mkt-hero-ctas">
          <button className="btn-primary" style={{ padding: "18px 48px", fontSize: 17 }} onClick={() => onNavigate("pricing")}>
            View plans
          </button>
        </div>
      </section>


      {/* STATS ROW */}
      <section className="mkt-stats">
        <div className="mkt-stats-inner">
          <div className="mkt-stat">
            <div className="mkt-stat-number">4</div>
            <div className="mkt-stat-label">ACORD forms in production</div>
            <div className="mkt-stat-sub">25 · 125 · 126 · 140</div>
          </div>
          <div className="mkt-stat-divider" />
          <div className="mkt-stat">
            <div className="mkt-stat-number">SQS</div>
            <div className="mkt-stat-label">Submission Quality Score</div>
            <div className="mkt-stat-sub">Per-form and package-level scoring</div>
          </div>
          <div className="mkt-stat-divider" />
          <div className="mkt-stat">
            <div className="mkt-stat-number">ARQ</div>
            <div className="mkt-stat-label">Client questionnaire loop</div>
            <div className="mkt-stat-sub">Send · remind · auto-populate</div>
          </div>
        </div>

        {/* Ticker strip */}
        <div className="mkt-ticker-wrap">
          <div className="mkt-ticker-inner">
            {[
              "Upload any document format",
              "AI field extraction",
              "ACORD 25",
              "ACORD 125",
              "ACORD 126",
              "ACORD 140",
              "SQS hard stops",
              "Soft-stop overrides logged",
              "ARQ client questionnaire",
              "Digital signature",
              "Packaged ZIP download",
              "Full audit trail",
              "Upload any document format",
              "AI field extraction",
              "ACORD 25",
              "ACORD 125",
              "ACORD 126",
              "ACORD 140",
              "SQS hard stops",
              "Soft-stop overrides logged",
              "ARQ client questionnaire",
              "Digital signature",
              "Packaged ZIP download",
              "Full audit trail",
            ].map((item, i) => (
              <span key={i} className="mkt-ticker-item">
                <span className="mkt-ticker-dot" />
                <strong>{item}</strong>
              </span>
            ))}
          </div>
        </div>
      </section>

      {/* WHO IT'S FOR */}
      <section className="mkt-section">
        <div className="mkt-section-inner">
          <div className="mkt-section-header">
            <div className="mkt-eyebrow">Who it's for</div>
            <h2 className="mkt-section-h2">Two workflows. One platform.</h2>
          </div>
          <div className="mkt-audience-grid">
            <div className="mkt-audience-card">
              <div className="mkt-audience-icon">
                <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>
                </svg>
              </div>
              <h3 className="mkt-audience-title">Brokers &amp; Independent Agents</h3>
              <p className="mkt-audience-desc">
                You receive messy source documents from clients — loss runs, prior policies, applications filled in different formats. Re-keying that data into ACORD forms wastes hours per account.
              </p>
              <ul className="mkt-audience-list">
                <li>Upload any document format</li>
                <li>AI extracts structured fields automatically</li>
                <li>Generate complete ACORD packages in minutes</li>
              </ul>
            </div>
            <div className="mkt-audience-card">
              <div className="mkt-audience-icon">
                <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/>
                </svg>
              </div>
              <h3 className="mkt-audience-title">Underwriters &amp; Underwriting Assistants</h3>
              <p className="mkt-audience-desc">
                Submissions arrive with missing fields, inconsistent data, and no quality visibility. By the time issues surface at carrier review, days have been lost.
              </p>
              <ul className="mkt-audience-list">
                <li>SQS scoring surfaces issues before download</li>
                <li>Hard stops block incomplete submissions</li>
                <li>Full audit trail per session</li>
              </ul>
            </div>
          </div>
        </div>
      </section>

      {/* PROBLEM vs RELIABILITY */}
      <section className="mkt-section mkt-section-alt">
        <div className="mkt-section-inner">
          <div className="mkt-section-header">
            <div className="mkt-eyebrow">The gap we close</div>
            <h2 className="mkt-section-h2">Manual submission failures — and how we handle them</h2>
          </div>
          <div className="mkt-two-col">
            <div className="mkt-problem-col">
              <div className="mkt-col-label mkt-col-label-red">Three failure points in manual submission</div>
              <div className="mkt-problem-item">
                <div className="mkt-problem-number">01</div>
                <div>
                  <div className="mkt-problem-title">Re-keying from source documents</div>
                  <div className="mkt-problem-desc">Transcription errors multiply per form. Every field re-entered manually is a field that can be entered differently.</div>
                </div>
              </div>
              <div className="mkt-problem-item">
                <div className="mkt-problem-number">02</div>
                <div>
                  <div className="mkt-problem-title">Back-and-forth for missing fields</div>
                  <div className="mkt-problem-desc">Email threads for data that could be auto-populated. Client follow-up delays that compound across accounts.</div>
                </div>
              </div>
              <div className="mkt-problem-item">
                <div className="mkt-problem-number">03</div>
                <div>
                  <div className="mkt-problem-title">Quality issues found too late</div>
                  <div className="mkt-problem-desc">Only flagged at carrier review — not at your desk. By then, it's a submission rejection, not a quick fix.</div>
                </div>
              </div>
            </div>
            <div className="mkt-reliability-col">
              <div className="mkt-col-label mkt-col-label-green">Validation gates, not just extraction</div>
              <div className="mkt-reliability-item">
                <div className="mkt-reliability-icon">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
                </div>
                <div>
                  <div className="mkt-reliability-title">Tier checks before generation</div>
                  <div className="mkt-reliability-desc">Extracted fields validated against completeness thresholds before any form is generated. Missing critical data is surfaced immediately.</div>
                </div>
              </div>
              <div className="mkt-reliability-item">
                <div className="mkt-reliability-icon">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
                </div>
                <div>
                  <div className="mkt-reliability-title">Hard stops block critical failures</div>
                  <div className="mkt-reliability-desc">SQS hard stops prevent download when critical fields are missing. Soft stops surface warnings with an override option that logs the decision.</div>
                </div>
              </div>
              <div className="mkt-reliability-item">
                <div className="mkt-reliability-icon">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
                </div>
                <div>
                  <div className="mkt-reliability-title">Full recommendation resolution logging</div>
                  <div className="mkt-reliability-desc">Every SQS decision — override, acknowledge, or block — is recorded for post-submission review. Audit trail per session.</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* FORM AVAILABILITY TABLE */}
      <section className="mkt-section">
        <div className="mkt-section-inner">
          <div className="mkt-section-header">
            <div className="mkt-eyebrow">Current availability</div>
            <h2 className="mkt-section-h2">What's in production today</h2>
            <p className="mkt-section-sub">No inflated claims. This is exactly what's wired in and working.</p>
          </div>
          <div className="mkt-forms-table">
            <div className="mkt-forms-thead">
              <span>Form</span>
              <span>Description</span>
              <span>Status</span>
            </div>
            <div className="mkt-forms-body">
              {FORMS_DATA.map((row, i) => (
                <div
                  key={i}
                  className={`mkt-forms-row ${hoveredRow === i ? "mkt-forms-row-hover" : ""}`}
                  onMouseEnter={() => setHoveredRow(i)}
                  onMouseLeave={() => setHoveredRow(null)}
                >
                  <span className="mkt-forms-form">{row.form}</span>
                  <span className="mkt-forms-name">{row.name}</span>
                  <span className={`mkt-forms-badge ${row.status === "available" ? "mkt-badge-green" : "mkt-badge-gray"}`}>
                    {row.status === "available" ? "✓ Available" : "Coming soon"}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

    </main>
  );
}
