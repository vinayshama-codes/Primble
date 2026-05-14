import { useEffect } from "react";
import { API_BASE } from "../config/constants";

export function useUpgradePolling(shouldPoll, setUser, setUpgradeChecking, setUpgradeFailed, expectedPlan, stripeSessionId) {
  useEffect(() => {
    if (!shouldPoll) return;

    setUpgradeChecking(true);
    setUpgradeFailed(false);

    const MAX_POLL    = 12;
    const BASE_DELAY  = 2000;
    let   attempts    = 0;

    const isPlanReady = (tier) => {
      if (!tier || tier === "free") return false;
      if (expectedPlan) return tier === expectedPlan;
      return true;
    };

    const backoffDelay = (attempt) => Math.min(BASE_DELAY * Math.pow(1.5, attempt), 15000);

    const pollMe = () => {
      attempts++;
      fetch(`${API_BASE}/api/auth/me`, { credentials: "include" })
        .then((r) => (r.ok ? r.json() : null))
        .then((data) => {
          if (!data) { tryVerifyFallback(); return; }
          setUser(data);
          if (isPlanReady(data.subscription_tier)) {
            setUpgradeChecking(false);
          } else if (attempts < MAX_POLL) {
            setTimeout(pollMe, backoffDelay(attempts));
          } else {
            tryVerifyFallback();
          }
        })
        .catch(() => {
          if (attempts < MAX_POLL) setTimeout(pollMe, backoffDelay(attempts));
          else tryVerifyFallback();
        });
    };

    // Only call verify-upgrade when Stripe provided a session_id in the redirect URL,
    // confirming this is a genuine checkout completion and not an arbitrary URL visit.
    const tryVerifyFallback = () => {
      if (!stripeSessionId) {
        setUpgradeChecking(false);
        setUpgradeFailed(true);
        return;
      }
      fetch(`${API_BASE}/api/stripe/verify-upgrade`, { method: "POST", credentials: "include" })
        .then((r) => (r.ok ? r.json() : null))
        .then((data) => {
          if (data && isPlanReady(data.subscription_tier)) {
            fetch(`${API_BASE}/api/auth/me`, { credentials: "include" })
              .then((r) => (r.ok ? r.json() : null))
              .then((me) => { if (me) setUser(me); });
            setUpgradeChecking(false);
          } else {
            setUpgradeChecking(false);
            setUpgradeFailed(true);
          }
        })
        .catch(() => { setUpgradeChecking(false); setUpgradeFailed(true); });
    };

    pollMe();
  }, [shouldPoll]); // eslint-disable-line
}

export function useBillingReturnPolling(token, setUser, setUpgradeChecking) {
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("billing_updated") !== "true") return;
    window.history.replaceState({}, "", "/");
    setUpgradeChecking(true);
    let attempts = 0;
    const poll = () => {
      attempts++;
      fetch(`${API_BASE}/api/auth/me`, { credentials: "include" })
        .then((r) => (r.ok ? r.json() : null))
        .then((data) => { if (data) setUser(data); setUpgradeChecking(false); })
        .catch(() => { if (attempts < 6) setTimeout(poll, 2000); else setUpgradeChecking(false); });
    };
    setTimeout(poll, 1000);
  }, []); // eslint-disable-line
}
