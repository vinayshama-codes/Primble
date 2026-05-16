import PricingPage from "../pages/PricingPage";

export default function LandingPage({ user, onGetStarted, token, onError, openBillingPortal }) {
  return (
    <>
      <div className="hero-wrapper">
        <section className="hero">
          <h1 className="hero-h1">INTELLIGENT SUBMISSIONS</h1>
          <p className="hero-tagline">Submission Quality Control for Commercial Insurance</p>
          {!user && (
            <p className="hero-free-copy">Build and validate your first three packages on us. No credit card required.</p>
          )}
          <div className="hero-actions">
            <button className="btn-primary" onClick={() => onGetStarted()}>
              {user ? "Upload Documents" : "Get Started for Free"}
            </button>
          </div>
        </section>
      </div>

      <PricingPage onGetStarted={onGetStarted} token={token} user={user} onError={onError} openBillingPortal={openBillingPortal} />
    </>
  );
}