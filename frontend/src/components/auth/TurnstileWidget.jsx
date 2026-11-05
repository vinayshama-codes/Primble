// TurnstileWidget.jsx - the Cloudflare Turnstile captcha on the sign-in screens (3 Nov 2026; backend
// services/captcha.py). Drawn only when the server hands out a site key (`GET /api/auth/captcha-config`); with no
// key nothing renders and nothing changes. Each answer is single-use: the parent bumps `resetSignal` after it sends
// one, and a fresh answer arrives through `onToken`. `onToken("")` whenever there is no usable answer.
import { useEffect, useRef, useState } from "react";

const SCRIPT_SRC = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
let scriptPromise = null;

function loadTurnstile() {
  if (window.turnstile) return Promise.resolve(window.turnstile);
  if (!scriptPromise) {
    scriptPromise = new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = SCRIPT_SRC;
      s.async = true;
      s.defer = true;
      // A content blocker can load an empty stand-in: forget this attempt too, so reopening the window tries again
      // (review pass 3).
      s.onload = () => {
        if (window.turnstile) { resolve(window.turnstile); return; }
        scriptPromise = null; s.remove(); reject(new Error("turnstile missing"));
      };
      s.onerror = () => { scriptPromise = null; s.remove(); reject(new Error("turnstile script")); };
      document.head.appendChild(s);
    });
  }
  return scriptPromise;
}

export default function TurnstileWidget({ siteKey, onToken, resetSignal = 0, action = "" }) {
  const box = useRef(null);
  const widget = useRef(null);
  const tokenCb = useRef(onToken);
  tokenCb.current = onToken;
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!siteKey) return undefined;
    let gone = false;
    setFailed(false);
    tokenCb.current("");
    loadTurnstile()
      .then((ts) => {
        if (gone || !box.current) return;
        widget.current = ts.render(box.current, {
          sitekey: siteKey,
          action,
          theme: "light",
          callback: (t) => tokenCb.current(t || ""),
          "expired-callback": () => tokenCb.current(""),
          "error-callback": () => tokenCb.current(""),
        });
      })
      .catch(() => { if (!gone) { setFailed(true); tokenCb.current(""); } });
    return () => {
      gone = true;
      try { if (widget.current != null && window.turnstile) window.turnstile.remove(widget.current); } catch { /* gone */ }
      widget.current = null;
    };
  }, [siteKey, action]);

  useEffect(() => {
    if (!resetSignal || widget.current == null || !window.turnstile) return;
    tokenCb.current("");
    try { window.turnstile.reset(widget.current); } catch { /* a new widget will be drawn */ }
  }, [resetSignal]);

  if (!siteKey) return null;
  return (
    <div className="auth-captcha">
      <div ref={box} />
      {failed && (
        <div className="auth-captcha-note">
          The security check could not load. Check your connection or turn off a content blocker, then reopen this window.
        </div>
      )}
    </div>
  );
}
