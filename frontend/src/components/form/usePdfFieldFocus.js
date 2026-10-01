import { useEffect } from "react";

// "Jump to this box" for the PDF viewer (Orbin 22 Sep item 19, 30 Sep 2026).
// Self-contained on purpose: the viewer passes its own refs and page setter,
// and marks each overlay box with `data-field-name`. A request is
// `{ field, nonce }`; each nonce is handled ONCE, even across a viewer
// remount (the viewer is re-keyed on every re-stamp), so paging away after a
// jump never pulls the reader back.

export const FOCUS_FLASH_MS = 2400;
// How long a jump waits for its box to be drawn before it is dropped.
export const FOCUS_WAIT_MS = 12000;
const _handled = new Set();

const _selector = (name) => {
  const esc = typeof window !== "undefined" && window.CSS && typeof window.CSS.escape === "function"
    ? window.CSS.escape(name)
    : String(name).replace(/["\\]/g, "\\$&");
  return `[data-field-name="${esc}"]`;
};

export default function usePdfFieldFocus({ focusField, fieldsLoaded, fieldsRef, overlayRef, pageNum, setPageNum }) {
  const nonce = focusField?.nonce;
  const name = focusField?.field;
  useEffect(() => {
    if (!name || nonce == null || !fieldsLoaded || _handled.has(nonce)) return undefined;
    const target = (fieldsRef.current || []).find(f => f.name === name);
    if (!target) { _handled.add(nonce); return undefined; }
    const wantPage = (Number(target.page) || 0) + 1;
    if (wantPage !== pageNum) { setPageNum(wantPage); return undefined; }  // re-runs on the new page

    let cancelled = false;
    let timer = null;
    let observer = null;
    const started0 = Date.now();
    const stopWatching = () => {
      if (timer) { clearTimeout(timer); timer = null; }
      if (observer) { observer.disconnect(); observer = null; }
    };
    const find = () => {
      if (cancelled) return;
      const el = overlayRef.current ? overlayRef.current.querySelector(_selector(name)) : null;
      if (!el) {
        // The page (or the whole PDF, after a re-stamp remount) is still
        // drawing. Watch the overlay for the box instead of guessing a delay;
        // give up after FOCUS_WAIT_MS and mark the request handled, so a late
        // page turn can never pull the reader back to an old target (review).
        if (Date.now() - started0 > FOCUS_WAIT_MS) { _handled.add(nonce); stopWatching(); return; }
        if (!observer && overlayRef.current && typeof MutationObserver !== "undefined") {
          observer = new MutationObserver(() => find());
          observer.observe(overlayRef.current, { childList: true, subtree: true });
        }
        if (!timer) timer = setTimeout(() => { timer = null; find(); }, 250);
        return;
      }
      stopWatching();
      _handled.add(nonce);
      try { el.scrollIntoView({ block: "center", inline: "nearest", behavior: "smooth" }); } catch { /* old browsers */ }
      const input = el.querySelector("input");
      if (input) { try { input.focus({ preventScroll: true }); } catch { /* not focusable */ } }
      // The overlay can be rebuilt once more while the page settles; keep the
      // flash on whichever element currently draws the box.
      // Flash with the OUTLINE only: the box's own box-shadow carries the
      // viewer's Yes/No marking (item 18) and must survive the flash (review).
      const started = Date.now();
      const flash = () => {
        const cur = overlayRef.current ? overlayRef.current.querySelector(_selector(name)) : null;
        const on = Date.now() - started < FOCUS_FLASH_MS;
        if (cur) {
          if (on && cur.dataset.flashPrevZ === undefined) cur.dataset.flashPrevZ = cur.style.zIndex || "";
          cur.style.outline = on ? "3px solid #E61B84" : "";
          cur.style.outlineOffset = on ? "2px" : "";
          if (on) cur.style.zIndex = "5";
          else if (cur.dataset.flashPrevZ !== undefined) {
            cur.style.zIndex = cur.dataset.flashPrevZ;
            delete cur.dataset.flashPrevZ;
          }
        }
        if (on) setTimeout(flash, 200);
      };
      flash();
    };
    find();
    return () => { cancelled = true; stopWatching(); };
  }, [nonce, name, fieldsLoaded, pageNum]); // eslint-disable-line react-hooks/exhaustive-deps
}
