import { useState, useEffect } from "react";

export default function ProcessStageOverlay({ stages, advanceAfter = 3000, tagline, note, etaSeconds = 0, windowSize = 0 }) {
  const [activeIdx, setActiveIdx] = useState(0);
  const [eta, setEta] = useState(etaSeconds);

  useEffect(() => {
    if (activeIdx >= stages.length - 1) return;
    const t = setTimeout(
      () => setActiveIdx((i) => Math.min(i + 1, stages.length - 1)),
      advanceAfter
    );
    return () => clearTimeout(t);
  }, [activeIdx, stages.length, advanceAfter]);

  // Workstream 6 9.3 - rough "estimated time remaining". LLM latency varies, so
  // this is a reassurance signal, not a precise clock: it counts down one second
  // at a time, then decelerates in the final stretch when generation runs long
  // (so it never bottoms out and looks stalled) and holds at "Wrapping up...".
  useEffect(() => {
    if (!etaSeconds) return;
    const id = setInterval(() => setEta((e) => {
      if (e <= 6) return e;          // hold near the floor -> label shows "Wrapping up..."
      if (e <= 15) return e - 0.5;   // decelerate: visible seconds tick down slower
      return e - 1;                  // normal 1s / tick
    }), 1000);
    return () => clearInterval(id);
  }, [etaSeconds]);

  const etaLabel = (s) => {
    if (s <= 6) return "Wrapping up…";
    if (s < 60) return `Approximately ${Math.ceil(s)} seconds remaining`;
    const total = Math.ceil(s);
    const mins = Math.floor(total / 60);
    const secs = total % 60;
    const minPart = `${mins} minute${mins === 1 ? "" : "s"}`;
    if (secs === 0) return `Approximately ${minPart} remaining`;
    return `Approximately ${minPart} ${secs} second${secs === 1 ? "" : "s"} remaining`;
  };

  // Workstream 6 9.3 - optional "window": show only N stages at once (the
  // generation overlay shows 2 at a time, advancing through the list in pages).
  const _start = windowSize > 0 ? Math.floor(activeIdx / windowSize) * windowSize : 0;
  const _visible = windowSize > 0 ? stages.slice(_start, _start + windowSize) : stages;

  return (
    <div className="upgrade-stage-overlay">
      {tagline && (
        <p style={{ margin: "0 0 0", fontSize: "clamp(12px, 3.7vw, 22px)", fontWeight: 700, color: "#0f172a", letterSpacing: "-0.2px", textAlign: "center", lineHeight: 1.4, whiteSpace: "nowrap", padding: "0 10px", maxWidth: 580 }}>
          {tagline}
        </p>
      )}
      {note && (
        <div style={{ margin: 0, padding: "0 8px", maxWidth: 600, width: "100%", textAlign: "center" }}>
          <p style={{ margin: 0, fontSize: "clamp(5px, 1.8vw, 11px)", color: "#6b7280", lineHeight: 1.6, fontWeight: 450, whiteSpace: "nowrap" }}>
            {note}
          </p>
        </div>
      )}
      <div className="upgrade-stage-spinner" />
      <div className="upgrade-stage-steps">
        {_visible.map((s, vi) => {
          const i = _start + vi;
          return (
            <div
              key={s}
              className={`upgrade-stage-step ${i === activeIdx ? "active" : i < activeIdx ? "done" : ""}`}
            >
              <div className="upgrade-stage-dot" />
              {s}
            </div>
          );
        })}
      </div>
      {etaSeconds > 0 && (
        <div style={{ marginTop: 14, textAlign: "center" }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: "#E61B84" }}>
            {etaLabel(eta)}
          </div>
        </div>
      )}
    </div>
  );
}