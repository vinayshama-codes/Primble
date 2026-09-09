import { useCallback, useEffect, useRef, useState } from "react";

/**
 * UI-10 - ONE door for transient toast notifications.
 *
 * The reported defect ("Forms Generated" / "Review Required" stay on screen and
 * obscure the working area) was never about those two messages. Toast LIFETIME
 * had simply never been modelled: every surface hand-rolled its own state and
 * then invented - or forgot - its own dismissal. Two faces of that one class:
 *
 *   - AcordModal's job toasts had NO timer at all. They sat there forever.
 *   - App's overage toast auto-dismissed at 8s but had NO close button, and its
 *     setTimeout was never cleared, so it fired into an unmounted component.
 *
 * Every toast now goes through this hook, so a new surface cannot ship a toast
 * with no lifetime and cannot invent a fourth duration. Rendering stays with the
 * caller - the two surfaces look deliberately different and unifying their
 * visuals is not what was asked for.
 *
 * DURATION POLICY (owner-approved 2026-09-09):
 *   success / info   -> 8s.  The message is an announcement; the state it
 *                            announces (generated forms, hard-stop and warning
 *                            counts) lives permanently in the primary interface,
 *                            so nothing is lost when the card goes away. Owner
 *                            set 8s over the proposed 5s - with pause-on-hover
 *                            deliberately absent (see below) the timer runs while
 *                            the card is being read, so it gets the longer dwell.
 *                            It also matches what App's overage pill already used.
 *   warning / error  -> 10s. These carry an instruction the user has to READ and
 *                            ACT on ("click the lock icon in your address bar,
 *                            then reload").
 *
 * Consistent BEHAVIOUR, not an identical stopwatch. Manual close stays on every
 * toast either way - the timer is a floor on convenience, never the only exit.
 *
 * NOT DONE, deliberately (owner's call): pause-on-hover / pause-on-focus. Hover,
 * focus and tooltip behaviour elsewhere in the app is unchanged.
 */

export const TOAST_MS_INFO = 8000;
export const TOAST_MS_ACTION = 10000;

/** Duration for a tone. Exported so a caller can reason about it without
 *  re-deriving the policy (which is how three different durations appeared in
 *  the first place). */
export function toastDurationMs(tone) {
  return tone === "error" || tone === "warning" ? TOAST_MS_ACTION : TOAST_MS_INFO;
}

export function useToasts() {
  const [toasts, setToasts] = useState([]);
  // Timer handles live in a ref, not in state: clearing one must never trigger a
  // render, and the unmount cleanup has to see the LIVE set, not a closed-over
  // snapshot from whichever render registered it.
  const timers = useRef(new Map());

  const _drop = useCallback((id) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const dismiss = useCallback((id) => {
    const handle = timers.current.get(id);
    if (handle) {
      clearTimeout(handle);
      timers.current.delete(id);
    }
    _drop(id);
  }, [_drop]);

  /**
   * push({ title, body, tone, durationMs }) -> id
   *
   * `durationMs` overrides the policy for a genuinely exceptional message;
   * 0 or null means "no auto-dismiss" and should essentially never be used -
   * it is the behaviour UI-10 exists to remove.
   */
  const push = useCallback((toast) => {
    const t = toast || {};
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
    const tone = t.tone || "info";
    const ms = t.durationMs === undefined || t.durationMs === null
      ? toastDurationMs(tone)
      : t.durationMs;

    setToasts((prev) => [...prev, { ...t, id, tone }]);

    if (ms > 0) {
      const handle = setTimeout(() => {
        timers.current.delete(id);
        _drop(id);
      }, ms);
      timers.current.set(id, handle);
    }
    return id;
  }, [_drop]);

  const clearAll = useCallback(() => {
    timers.current.forEach((handle) => clearTimeout(handle));
    timers.current.clear();
    setToasts([]);
  }, []);

  // Unmount cleanup. App's overage toast used to leak two bare setTimeouts that
  // fired setState into a dead component on a fast navigate-away.
  useEffect(() => {
    const live = timers.current;
    return () => {
      live.forEach((handle) => clearTimeout(handle));
      live.clear();
    };
  }, []);

  return { toasts, push, dismiss, clearAll };
}

export default useToasts;
