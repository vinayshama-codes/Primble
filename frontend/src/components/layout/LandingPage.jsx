import { useState } from "react";
import PricingPage from "../pages/PricingPage";
import { API_BASE } from "../../config/constants";

export default function LandingPage({ user, onGetStarted, token, onError, openBillingPortal }) {
  return (
    <>
      <section className="hero">
        <h1 className="hero-h1">ACORD® made easy</h1>
        <p className="hero-p">Commercial insurance, without the paperwork. Instantly convert any insurance documents into completed ACORD forms.</p>
        <button className="btn-primary" onClick={() => onGetStarted()}>
          {user ? "UPLOAD DOCUMENTS" : "GET STARTED FOR FREE"}
        </button>
        <a href="https://www.youtube.com/watch?v=dQw4w9WgXcQ" target="_blank" rel="noopener noreferrer" className="hero-link">See how it works →</a>
      </section>

      <PricingPage onGetStarted={onGetStarted} token={token} user={user} onError={onError} openBillingPortal={openBillingPortal} />
    </>
  );
}