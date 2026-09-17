// Which layout the pre-form "Review Your Submission" step renders.
//
//   rail    - the sectioned layout with a left navigation rail (the default).
//   classic - the original single-column screen.
//
// Resolution order, first match wins:
//   1. `?layout=rail` / `?layout=classic` in the URL. Remembered for the rest of
//      the browser tab (sessionStorage) so a demo link keeps working as the app
//      navigates, but never across tabs: after a rollback nobody stays stuck on
//      a layout because of a link they opened last week.
//   2. The value remembered from (1) in this tab.
//   3. The build-time setting VITE_REVIEW_LAYOUT (set it to "classic" to bring the
//      original screen back for everyone).
//   4. "rail" - anything unset or misspelled uses the sectioned layout.

const LAYOUTS = ["classic", "rail"];
const STORAGE_KEY = "primble.reviewLayout";

function valid(value) {
  return LAYOUTS.includes(value) ? value : null;
}

function layoutFromUrl() {
  if (typeof window === "undefined") return null;
  try {
    const fromUrl = valid(new URLSearchParams(window.location.search).get("layout"));
    if (fromUrl) window.sessionStorage.setItem(STORAGE_KEY, fromUrl);
    return fromUrl;
  } catch {
    return null;
  }
}

// Captured when the module first loads: App rewrites the URL to "/" on resume
// and billing-return links before AcordModal mounts, which would otherwise drop
// a ?layout= that arrived with them.
layoutFromUrl();

export function getReviewLayout() {
  if (typeof window !== "undefined") {
    const fromUrl = layoutFromUrl();
    if (fromUrl) return fromUrl;
    try {
      const remembered = valid(window.sessionStorage.getItem(STORAGE_KEY));
      if (remembered) return remembered;
    } catch { /* storage unavailable */ }
  }
  return valid(import.meta.env.VITE_REVIEW_LAYOUT) || "rail";
}
