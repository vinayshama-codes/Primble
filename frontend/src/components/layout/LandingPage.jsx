import { useState } from "react";

const FAQ_DATA = [
  { question: "What services do you offer?", answer: "AI-powered ACORD form automation. Upload any insurance document and we instantly extract, validate, and fill the right ACORD forms." },
  { question: "How do I get started?", answer: "Click 'Get Started for Free', create an account, upload your documents (multiple at once), and our AI handles extraction, form selection, and auto-fill automatically." },
  { question: "What makes you different?", answer: "Carrier-grade validation with hard stops, cross-form checks, and a 6-component SQS score. No more manual re-entry or underwriter back-and-forth." },
  { question: "What's your pricing model?", answer: "Free tier: 3 submission downloads. After that, upgrade to Pro for unlimited processing with priority support." },
];

export default function LandingPage({ user, onGetStarted }) {
  const [openFaq, setOpenFaq] = useState(null);

  return (
    <>
      <section className="hero">
        <h1 className="hero-h1">ACORD® made easy</h1>
        <p className="hero-p">Commercial insurance, without the paperwork. Instantly convert any insurance documents into completed ACORD forms.</p>
        <button className="btn-primary" onClick={onGetStarted}>
          {user ? "UPLOAD DOCUMENTS" : "GET STARTED FOR FREE"}
        </button>
        <a href="https://www.youtube.com/watch?v=dQw4w9WgXcQ" target="_blank" rel="noopener noreferrer" className="hero-link">See how it works →</a>
      </section>

      <section className="features">
        {[
          { img: "feature1.webp", title: "AI Infrastructure", desc: "Advanced AI processes your documents with 99% accuracy, reducing manual entry by 95%." },
          { img: "feature2.webp", title: "User Agnostic", desc: "Works for brokers, agents, and underwriters. No training required." },
          { img: "feature3.webp", title: "Transparent Pricing", desc: "3 free downloads. Clear pricing with no hidden fees after." },
        ].map((f, i) => (
          <div key={i} className="feature">
            <img src={f.img} alt={f.title} className="feature-image" />
            <h3 className="feature-h3">{f.title}</h3>
            <p className="feature-p">{f.desc}</p>
          </div>
        ))}
      </section>

      <section className="quote">
        <img src="quote-image.webp" alt="Quote" className="quote-image" />
        <blockquote className="blockquote">
          "Getting to underwriting shouldn't require retyping the same data five times in a row..."
          <span className="blockquote-span">— Michelle Smith, Co-Founder &amp; CIO</span>
        </blockquote>
      </section>

      <section className="banner">
        <h2 className="banner-h2">Innovation without compromise</h2>
        <img src="https://images.unsplash.com/photo-1451187580459-43490279c0fa?w=1200&h=500&fit=crop" alt="Innovation" className="banner-image" />
        <p className="banner-p">Cutting-edge technology that moves your business forward—securely, efficiently, and at scale.</p>
      </section>

      <section className="faq">
        <div>
          <h3 className="faq-h3">What is acordly.ai?</h3>
          <p className="faq-p">We bridge the gap between insurance documents and carrier-ready ACORD submissions.</p>
        </div>
        <div className="faq-list">
          {FAQ_DATA.map((item, i) => (
            <div key={i} className="faq-item-wrapper">
              <div className="faq-item" onClick={() => setOpenFaq(openFaq === i ? null : i)}>
                <span>{item.question}</span>
                <span className={`faq-icon ${openFaq === i ? "open" : ""}`}>+</span>
              </div>
              {openFaq === i && <div className="faq-answer">{item.answer}</div>}
            </div>
          ))}
        </div>
      </section>

      <footer className="footer">
        <div><h4 className="footer-h4">About Us</h4><p className="footer-p">123 Demo Street<br />New York, NY</p></div>
        <div><h4 className="footer-h4">Contact Us</h4><p className="footer-p">email@example.com<br />(555) 555-5555</p></div>
        <div>
          <h4 className="footer-h4">Follow Us</h4>
          <p className="footer-p">
            <a href="https://instagram.com" target="_blank" rel="noopener noreferrer">Instagram</a><br />
            <a href="https://twitter.com" target="_blank" rel="noopener noreferrer">Twitter</a><br />
            <a href="https://pinterest.com" target="_blank" rel="noopener noreferrer">Pinterest</a>
          </p>
        </div>
        <div>
          <h4 className="footer-h4">Newsletter</h4>
          <p className="footer-p">Join our mailing list for the latest insights and product updates.</p>
          <input className="footer-input" placeholder="Email Address" />
          <button className="footer-button">Sign Up</button>
        </div>
      </footer>
    </>
  );
}