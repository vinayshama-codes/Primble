import { useEffect, useRef } from "react";

/**
 * Run `onRestore` when the browser brings this page back from its
 * back/forward cache (bfcache).
 *
 * Why this exists: every Stripe redirect (plan checkout, billing portal) sets a
 * loading flag - "Opening cart…", "Redirecting to Stripe…" - and then assigns
 * window.location. If the user presses Back on the Stripe page, the browser can
 * restore the frozen page instead of reloading it. No component remounts and no
 * state resets, so the flag set just before leaving is still true: the spinner
 * runs forever and the buttons stay disabled.
 *
 * `pageshow` with `event.persisted === true` fires only for a bfcache restore.
 * A normal load or a reload (where state is fresh anyway) never triggers it.
 */
export function usePageRestore(onRestore) {
  const onRestoreRef = useRef(onRestore);

  useEffect(() => {
    onRestoreRef.current = onRestore;
  });

  useEffect(() => {
    const handlePageShow = (event) => {
      if (event.persisted) onRestoreRef.current();
    };
    window.addEventListener("pageshow", handlePageShow);
    return () => window.removeEventListener("pageshow", handlePageShow);
  }, []);
}
