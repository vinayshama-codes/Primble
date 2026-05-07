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
        <div className="mkt-hero-eyebrow" style={{ fontSize: "1rem" }}>About Acordly</div>
        <h1 className="mkt-hero-h1">
          Source document to ACORD package<br />
          <span className="mkt-hero-accent">No manual re-entry</span>
        </h1>
        <p className="mkt-hero-p">
          Built for brokers, independent agents, and underwriting teams who spend hours manually filling ACORD forms from Dec Page documents - now it’s done in just one click.
        </p>
      </section>


      {/* STATS ROW */}
      <section className="mkt-stats">
        <div className="mkt-stats-inner">
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

      {/* FORM AVAILABILITY TABLE */}
      <section className="mkt-section">
        <div className="mkt-section-inner">
          <div className="mkt-section-header">
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
