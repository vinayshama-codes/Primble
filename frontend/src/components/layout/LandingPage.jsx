import PricingPage from "../pages/PricingPage";

export default function LandingPage({ user, onGetStarted, token, onError, openBillingPortal }) {
  return (
    <div style={{ fontFamily: "'Montserrat', sans-serif" }}>
      <div className="hero-wrapper">
        <section className="hero">
          <p className="hero-eyebrow-label">INTELLIGENT SUBMISSIONS</p>
          <h1 className="hero-h1-main">Submission Quality Control for Commercial Insurance</h1>
          {!user && (
            <p className="hero-free-copy">Build and validate your first few packages on us. No credit card required.</p>
          )}
          <div className="hero-actions">
            <button className="btn-primary" onClick={() => onGetStarted(null, null, "signup")}>
              {user ? "Upload Documents" : "Get Started for Free"}
            </button>
          </div>
        </section>
      </div>

      <PricingPage onGetStarted={onGetStarted} token={token} user={user} onError={onError} openBillingPortal={openBillingPortal} />
    </div>
  );
}