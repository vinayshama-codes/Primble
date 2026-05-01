const WORKFLOW_STEPS = [
  {
    num: "01",
    title: "Upload source documents",
    desc: "Upload PDFs, images, or zip archives containing any insurance documents. Batch upload supported — drop everything at once.",
    tags: ["upload endpoint", "multi-file", "zip support"],
  },
  {
    num: "02",
    title: "AI extraction and form recommendation",
    desc: "The AI extracts structured data from your documents and recommends the appropriate ACORD forms. You confirm the selection before generation begins.",
    tags: ["AI extraction", "select-forms-bulk", "recommended forms UI"],
  },
  {
    num: "03",
    title: "Generate, preview, and edit",
    desc: "Forms are generated from the extracted data. Live PDF preview lets you inspect every field. Inline editing lets you correct specific fields before finalizing.",
    tags: ["PDF preview", "inline edit", "field-level correction"],
  },
  {
    num: "04",
    title: "SQS quality check",
    desc: "Runs automatically before download. Hard stops block download on critical issues. Soft stops surface warnings — 'download anyway' logs the override to the audit trail.",
    tags: ["SQS per-form", "package-level", "hard/soft stops", "preflight modal"],
  },
  {
    num: "05",
    title: "Sign and download package",
    desc: "Add your digital signature. Download all forms as a single delivery-ready archive. One click, one zip, complete package.",
    tags: ["signature modal", "download-all", "packaged output"],
  },
];

export default function PlatformPage({ onGetStarted, onNavigate }) {
  return (
    <main className="mkt-page">

      {/* HERO */}
      <section className="mkt-hero">
        <div className="mkt-hero-eyebrow">Platform</div>
        <h1 className="mkt-hero-h1">
          Source document to signed package.<br />
          <span className="mkt-hero-accent">No re-keying required.</span>
        </h1>
        <p className="mkt-hero-p">
          Every step from document upload to final package download is handled in one session. Here's exactly how it works.
        </p>
      </section>

      {/* CORE WORKFLOW */}
      <section className="mkt-section">
        <div className="mkt-section-inner">
          <div className="mkt-section-header">
            <div className="mkt-eyebrow">Core workflow</div>
            <h2 className="mkt-section-h2">Five steps from upload to delivery</h2>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 48px" }}>
            {WORKFLOW_STEPS.map((step, i) => (
              <div key={i} className="mkt-workflow-step">
                <div className="mkt-workflow-left">
                  <div className="mkt-workflow-num">{step.num}</div>
                  <div className="mkt-workflow-line" style={{ minHeight: 32 }} />
                </div>
                <div className="mkt-workflow-body">
                  <h3 className="mkt-workflow-title">{step.title}</h3>
                  <p className="mkt-workflow-desc">{step.desc}</p>
                  <div className="mkt-workflow-tags">
                    {step.tags.map((tag, j) => (
                      <span key={j} className="mkt-tag">{tag}</span>
                    ))}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* SQS */}
      <section className="mkt-section mkt-section-alt">
        <div className="mkt-section-inner">
          <div className="mkt-section-header">
            <div className="mkt-eyebrow">Submission Quality Score</div>
            <h2 className="mkt-section-h2">Quality gates before every download</h2>
            <p className="mkt-section-sub">SQS isn't a report — it's a preflight check that runs before you can complete a download.</p>
          </div>
          <div className="mkt-sqs-grid">
            <div className="mkt-sqs-card">
              <div className="mkt-sqs-icon">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/>
                </svg>
              </div>
              <h3 className="mkt-sqs-title">Per-form scoring</h3>
              <ul className="mkt-sqs-list">
                <li>Required field completeness %</li>
                <li>Data type validation per field</li>
                <li>Cross-form consistency checks</li>
                <li>Insured name + policy date alignment</li>
              </ul>
            </div>
            <div className="mkt-sqs-card">
              <div className="mkt-sqs-icon">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
                </svg>
              </div>
              <h3 className="mkt-sqs-title">Package-level preflight</h3>
              <ul className="mkt-sqs-list">
                <li>Hard stops block the download modal</li>
                <li>Soft stops: acknowledge + proceed with logged reason</li>
                <li>Full preflight audit trail per session</li>
                <li>Override decisions recorded and reviewable</li>
              </ul>
            </div>
            <div className="mkt-sqs-card">
              <div className="mkt-sqs-icon">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>
                </svg>
              </div>
              <h3 className="mkt-sqs-title">Audit trail</h3>
              <ul className="mkt-sqs-list">
                <li>Every SQS decision logged</li>
                <li>Override reason captured at time of action</li>
                <li>Timestamped and tied to session</li>
                <li>Exportable on Business plan</li>
              </ul>
            </div>
          </div>
        </div>
      </section>

      {/* ARQ */}
      <section className="mkt-section">
        <div className="mkt-section-inner">
          <div className="mkt-section-header">
            <div className="mkt-eyebrow">Agent Report Questionnaire</div>
            <h2 className="mkt-section-h2">Close missing field gaps without leaving the session</h2>
            <p className="mkt-section-sub">When extraction leaves fields empty, ARQ lets you send a targeted questionnaire directly to the client — no login required on their end.</p>
          </div>
          <div className="mkt-arq-flow">
            <div className="mkt-arq-col">
              <div className="mkt-arq-section-label">Sending &amp; tracking</div>
              <div className="mkt-arq-item">
                <div className="mkt-arq-dot" />
                <div>
                  <div className="mkt-arq-item-title">Send targeted questionnaire</div>
                  <div className="mkt-arq-item-desc">Only asks for fields that are actually missing. No full-form re-entry.</div>
                </div>
              </div>
              <div className="mkt-arq-item">
                <div className="mkt-arq-dot" />
                <div>
                  <div className="mkt-arq-item-title">Track status in-session</div>
                  <div className="mkt-arq-item-desc">Sent / opened / completed — visible from within the session without switching tools.</div>
                </div>
              </div>
              <div className="mkt-arq-item">
                <div className="mkt-arq-dot" />
                <div>
                  <div className="mkt-arq-item-title">Reminder scheduling</div>
                  <div className="mkt-arq-item-desc">Set follow-up reminders. No manual tracking in a separate calendar or email client.</div>
                </div>
              </div>
              <div className="mkt-arq-tags">
                <span className="mkt-tag">ARQ send/remind/status</span>
                <span className="mkt-tag">client-facing questionnaire</span>
                <span className="mkt-tag">no client login required</span>
              </div>
            </div>
            <div className="mkt-arq-col">
              <div className="mkt-arq-section-label">When the client responds</div>
              <div className="mkt-arq-item">
                <div className="mkt-arq-dot" />
                <div>
                  <div className="mkt-arq-item-title">Answers map directly into open fields</div>
                  <div className="mkt-arq-item-desc">Client responses are matched field-by-field. No copy-paste, no re-entry.</div>
                </div>
              </div>
              <div className="mkt-arq-item">
                <div className="mkt-arq-dot" />
                <div>
                  <div className="mkt-arq-item-title">Review before applying</div>
                  <div className="mkt-arq-item-desc">Confirmation step shows exactly what will change. Session state is preserved throughout the ARQ loop.</div>
                </div>
              </div>
              <div className="mkt-arq-item">
                <div className="mkt-arq-dot" />
                <div>
                  <div className="mkt-arq-item-title">Regenerate with new data</div>
                  <div className="mkt-arq-item-desc">Confirm the mapped fields, then regenerate the affected forms. SQS re-runs on the updated package.</div>
                </div>
              </div>
              <div className="mkt-arq-tags">
                <span className="mkt-tag">field-level response mapping</span>
                <span className="mkt-tag">session state preserved</span>
                <span className="mkt-tag">confirmation step</span>
              </div>
            </div>
          </div>
        </div>
      </section>


      {/* OPERATIONAL CONTROLS */}
      <section className="mkt-section mkt-section-alt">
        <div className="mkt-section-inner">
          <div className="mkt-section-header">
            <div className="mkt-eyebrow">Operational controls</div>
            <h2 className="mkt-section-h2">Session management, billing, and signatures</h2>
          </div>
          <div className="mkt-ops-grid">
            <div className="mkt-ops-card">
              <h3 className="mkt-ops-title">Session history</h3>
              <p className="mkt-ops-desc">Every submission saved as a named session. Restore, continue, or delete from within the app. Persists across logins.</p>
              <div className="mkt-ops-features">
                <span className="mkt-tag">session APIs</span>
                <span className="mkt-tag">named sessions + timestamp</span>
                <span className="mkt-tag">status tracking</span>
                <span className="mkt-tag">bulk delete</span>
              </div>
            </div>
            <div className="mkt-ops-card">
              <h3 className="mkt-ops-title">Billing state + signature</h3>
              <p className="mkt-ops-desc">Payment state shown as banners and soft locks. Signature modal supports draw, upload, or type. Billing portal accessible from within the app.</p>
              <div className="mkt-ops-features">
                <span className="mkt-tag">payment-state banners</span>
                <span className="mkt-tag">soft-locked/suspended/canceling</span>
                <span className="mkt-tag">signature modal</span>
                <span className="mkt-tag">billing portal link</span>
              </div>
            </div>
          </div>
        </div>
      </section>


    </main>
  );
}
