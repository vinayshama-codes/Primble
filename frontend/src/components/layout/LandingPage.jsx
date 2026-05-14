import PricingPage from "../pages/PricingPage";

export default function LandingPage({ user, onGetStarted, token, onError, openBillingPortal }) {
  return (
    <>
      <section className="hero">
        <div className="hero-badge">ACORD® Automation Platform</div>
        <h1 className="hero-h1">
          Intelligent submissions<br />start <span style={{ color: "var(--primary)" }}>here</span>
        </h1>

        <div className="hero-actions">
          <button className="btn-primary" onClick={() => onGetStarted()}>
            {user ? "Upload Documents" : "Get Started for Free"}
          </button>
        </div>
      </section>

      <PricingPage onGetStarted={onGetStarted} token={token} user={user} onError={onError} openBillingPortal={openBillingPortal} />
    </>
  );
}