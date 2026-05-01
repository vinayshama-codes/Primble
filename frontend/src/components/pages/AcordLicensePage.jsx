import { useState } from "react";

const FAQ_DATA = [
  {
    q: "Does my brokerage already have an ACORD license?",
    a: "Most licensed insurance brokerages, agencies, and carriers have an ACORD organizational license. If you're unsure, check with your compliance officer or contact ACORD directly at acord.org.",
  },
  {
    q: "What does the license actually permit?",
    a: "It grants the right to use ACORD form templates for insurance transaction purposes — populating, generating, and submitting completed forms. It does not permit redistribution of blank templates or use of ACORD branding outside the form context.",
  },
  {
    q: "Can I use Acordly without an ACORD license?",
    a: "You can create sessions, upload documents, and use AI extraction. However, ACORD-branded form generation and download is gated behind license confirmation. You cannot complete a package download without confirming your organization's license status.",
  },
  {
    q: "What if our license lapses?",
    a: "Form generation and download becomes unavailable until the license is renewed and re-confirmed in the app. Your session data is fully preserved throughout.",
  },
];

const GATE_STEPS = [
  {
    num: "1",
    title: "Account setup",
    desc: "During onboarding, you confirm your organization's ACORD license status before accessing form generation.",
  },
  {
    num: "2",
    title: "License confirmation gate",
    desc: "You confirm your organization holds a valid license. The confirmation is recorded and timestamped against your account.",
  },
  {
    num: "3",
    title: "Access unlocked",
    desc: "ACORD form generation and download is available. Confirmation remains active unless your subscription lapses or is explicitly revoked.",
  },
];

export default function AcordLicensePage() {
  const [openFaq, setOpenFaq] = useState(null);

  return (
    <main className="mkt-page">

      {/* HERO */}
      <section className="mkt-hero mkt-hero-compact">
        <div className="mkt-hero-eyebrow">ACORD License</div>
        <h1 className="mkt-hero-h1">
          This is a legal requirement.<br />
          <span className="mkt-hero-accent">Not a product feature.</span>
        </h1>
        <p className="mkt-hero-p">
          Using ACORD forms requires a valid organizational license from ACORD directly. This is a contractual requirement that exists independently of your Acordly subscription.
        </p>

        {/* Warning notice */}
        <div className="mkt-license-notice" style={{ marginTop: 32 }}>
          <div className="mkt-license-notice-icon">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
            </svg>
          </div>
          <p className="mkt-license-notice-text">
            <strong>Acordly does not sell ACORD licenses.</strong> The license must be obtained directly from ACORD by your organization before you can generate or download ACORD-branded forms.
          </p>
        </div>
      </section>

      {/* WHAT AN ACORD LICENSE IS + FAQ side by side */}
      <section className="mkt-section">
        <div className="mkt-section-inner">
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 48, alignItems: "start" }}>

            {/* Left: IP rights */}
            <div>
              <div className="mkt-eyebrow" style={{ marginBottom: 12 }}>What it is</div>
              <h2 className="mkt-section-h2" style={{ marginBottom: 32 }}>ACORD intellectual property rights</h2>
              <div className="mkt-license-explainer">
                <div className="mkt-license-point">
                  <div className="mkt-license-point-icon">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
                  </div>
                  <div>
                    <div className="mkt-license-point-title">ACORD owns IP rights to ACORD form templates</div>
                    <div className="mkt-license-point-desc">The Association for Cooperative Operations Research and Development (ACORD) holds intellectual property rights over the standardized insurance form templates that carry the ACORD name and format.</div>
                  </div>
                </div>
                <div className="mkt-license-point">
                  <div className="mkt-license-point-icon">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                  </div>
                  <div>
                    <div className="mkt-license-point-title">Using, reproducing, or distributing requires a license</div>
                    <div className="mkt-license-point-desc">Populating, generating, or submitting ACORD forms — including through software like Acordly — requires your organization to hold a valid license agreement with ACORD. This is true regardless of the tool you use to fill the forms.</div>
                  </div>
                </div>
                <div className="mkt-license-point">
                  <div className="mkt-license-point-icon">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
                  </div>
                  <div>
                    <div className="mkt-license-point-title">Separate from your Acordly subscription</div>
                    <div className="mkt-license-point-desc">The ACORD organizational license is a contractual agreement between your organization and ACORD. It is entirely separate from your Acordly account or subscription tier.</div>
                  </div>
                </div>
              </div>
            </div>

            {/* Right: FAQ */}
            <div>
              <div className="mkt-eyebrow" style={{ marginBottom: 12 }}>Common questions</div>
              <h2 className="mkt-section-h2" style={{ marginBottom: 32 }}>License FAQ</h2>
              <div className="mkt-license-faq">
                {FAQ_DATA.map((item, i) => (
                  <div key={i} className="mkt-license-faq-item">
                    <button
                      className="mkt-license-faq-q"
                      onClick={() => setOpenFaq(openFaq === i ? null : i)}
                      aria-expanded={openFaq === i}
                    >
                      <span>{item.q}</span>
                      <span className={`mkt-faq-chevron ${openFaq === i ? "mkt-faq-chevron-open" : ""}`}>
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="6 9 12 15 18 9"/></svg>
                      </span>
                    </button>
                    {openFaq === i && (
                      <div className="mkt-license-faq-a">{item.a}</div>
                    )}
                  </div>
                ))}
              </div>
            </div>

          </div>
        </div>
      </section>

      {/* HOW THE GATE WORKS + EXTERNAL LINK side by side */}
      <section className="mkt-section mkt-section-alt">
        <div className="mkt-section-inner">
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 48, alignItems: "start" }}>

            {/* Left: Gate steps */}
            <div>
              <div className="mkt-eyebrow" style={{ marginBottom: 12 }}>How it works in-app</div>
              <h2 className="mkt-section-h2" style={{ marginBottom: 8 }}>The license confirmation gate</h2>
              <p className="mkt-section-sub" style={{ textAlign: "left", margin: "0 0 32px" }}>Three steps from account setup to ACORD form access.</p>
              <div className="mkt-gate-steps">
                {GATE_STEPS.map((step, i) => (
                  <div key={i} className="mkt-gate-step">
                    <div className="mkt-gate-step-left">
                      <div className="mkt-gate-num">{step.num}</div>
                      {i < GATE_STEPS.length - 1 && <div className="mkt-gate-line" />}
                    </div>
                    <div className="mkt-gate-body">
                      <div className="mkt-gate-title">{step.title}</div>
                      <div className="mkt-gate-desc">{step.desc}</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Right: External link block */}
            <div style={{ display: "flex", flexDirection: "column", justifyContent: "center", height: "100%" }}>
              <div className="mkt-eyebrow" style={{ marginBottom: 12 }}>Get licensed</div>
              <h2 className="mkt-section-h2" style={{ marginBottom: 24 }}>Obtain your ACORD license</h2>
              <div className="mkt-license-link-block" style={{ margin: 0 }}>
                <div className="mkt-license-link-icon">
                  <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/>
                  </svg>
                </div>
                <div>
                  <div className="mkt-license-link-title">Get your ACORD license directly from ACORD</div>
                  <div className="mkt-license-link-desc">Visit the official ACORD forms licensing page to understand requirements and begin the licensing process for your organization.</div>
                  <a
                    href="https://www.acord.org/standards-architecture/acord-forms/forms-licensing"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="mkt-license-ext-btn"
                  >
                    ACORD Forms Licensing →
                  </a>
                </div>
              </div>
            </div>

          </div>
        </div>
      </section>

    </main>
  );
}
