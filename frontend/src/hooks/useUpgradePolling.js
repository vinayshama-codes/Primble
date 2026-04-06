import { useEffect } from "react";
import { API_BASE } from "../config/constants";

export function useUpgradePolling(token, setUser, setUpgradeChecking, setUpgradeFailed) {
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("upgraded") !== "true") return;
    window.history.replaceState({}, "", "/");
    if (!token) return;

    setUpgradeChecking(true);
    setUpgradeFailed(false);

    const MAX_POLL   = 8;
    const POLL_DELAY = 2000;
    let   attempts   = 0;
    const isPaid     = (tier) => tier && tier !== "free";

    const pollMe = () => {
      attempts++;
      fetch(`${API_BASE}/api/auth/me`, { headers: { Authorization: `Bearer ${token}` } })
        .then((r) => (r.ok ? r.json() : null))
        .then((data) => {
          if (!data) { tryVerifyFallback(); return; }
          setUser(data);
          if (isPaid(data.subscription_tier)) {
            setUpgradeChecking(false);
          } else if (attempts < MAX_POLL) {
            setTimeout(pollMe, POLL_DELAY);
          } else {
            tryVerifyFallback();
          }
        })
        .catch(() => {
          if (attempts < MAX_POLL) setTimeout(pollMe, POLL_DELAY);
          else tryVerifyFallback();
        });
    };

    const tryVerifyFallback = () => {
      fetch(`${API_BASE}/api/stripe/verify-upgrade`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      })
        .then((r) => (r.ok ? r.json() : null))
        .then((data) => {
          if (data && isPaid(data.subscription_tier)) {
            fetch(`${API_BASE}/api/auth/me`, { headers: { Authorization: `Bearer ${token}` } })
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
  }, []); // eslint-disable-line
}

export function useBillingReturnPolling(token, setUser, setUpgradeChecking) {
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("billing_updated") !== "true") return;
    if (!token) return;
    window.history.replaceState({}, "", "/");
    setUpgradeChecking(true);
    let attempts = 0;
    const poll = () => {
      attempts++;
      fetch(`${API_BASE}/api/auth/me`, { headers: { Authorization: `Bearer ${token}` } })
        .then((r) => (r.ok ? r.json() : null))
        .then((data) => { if (data) setUser(data); setUpgradeChecking(false); })
        .catch(() => { if (attempts < 6) setTimeout(poll, 2000); else setUpgradeChecking(false); });
    };
    setTimeout(poll, 1000);
  }, [token]); // eslint-disable-line
}