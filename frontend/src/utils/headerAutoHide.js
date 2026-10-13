// The app header's auto-hide (layout/Header.jsx) as a pure step - owner, 13 Oct
// 2026: "i refreshed and opened the same session ... scrolling up and down but
// i cant see the navbar" (a blank band where the header was).
//
// Two defects, both in how a scroll was measured:
//   * an element's FIRST scroll was measured from 0. A refreshed page restores
//     its scroll position, so the first move - even upward - read as a huge
//     downward scroll and hid the header;
//   * the header came back only on ONE upward step of more than 40px. A
//     trackpad scrolls in many small steps, each measured from the last, so no
//     step ever reached 40 and the header stayed away - at the top of the page
//     too, where its empty box is the blank band.
// Now an element's first event is its starting point, an upward scroll is
// measured from where the last downward run ended (small steps add up), and
// the top of the page always shows the header.
// Pure, no React: the backend suite runs it under node.

export const HIDE_AFTER = 80;   // px from the top before a downward scroll may hide it
export const HIDE_STEP = 6;     // a downward step larger than this hides it
export const SHOW_RUN = 40;     // an upward run larger than this brings it back
export const MIN_STEP = 4;      // smaller moves are jitter

export function createHeaderAutoHide() {
  const positions = new WeakMap();
  const turns = new WeakMap();      // where each element's last downward run ended
  return {
    // The header's next hidden state for `el` scrolled to `y`, or null when
    // it stays as it is.
    step(el, y, hidden) {
      if (!el || typeof y !== "number") return null;
      if (!positions.has(el)) {
        positions.set(el, y);
        turns.set(el, y);
        return hidden && y <= HIDE_AFTER ? false : null;
      }
      const delta = y - positions.get(el);
      if (Math.abs(delta) < MIN_STEP) return null;
      positions.set(el, y);
      if (delta > 0) turns.set(el, y);
      const upRun = (turns.has(el) ? turns.get(el) : y) - y;
      if (!hidden && delta > HIDE_STEP && y > HIDE_AFTER) return true;
      if (hidden && (upRun > SHOW_RUN || y <= HIDE_AFTER)) return false;
      return null;
    },
    // A screen swapped its scroll container out: start this element afresh.
    reset(el, y) {
      if (!el || typeof y !== "number") return;
      positions.set(el, y);
      turns.set(el, y);
    },
  };
}
