import { useState, useEffect } from "react";

export default function ProcessStageOverlay({ stages, advanceAfter = 3000, tagline, note }) {
  const [activeIdx, setActiveIdx] = useState(0);

  useEffect(() => {
    if (activeIdx >= stages.length - 1) return;
    const t = setTimeout(
      () => setActiveIdx((i) => Math.min(i + 1, stages.length - 1)),
      advanceAfter
    );
    return () => clearTimeout(t);
  }, [activeIdx, stages.length, advanceAfter]);

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
        {stages.map((s, i) => (
          <div
            key={s}
            className={`upgrade-stage-step ${i === activeIdx ? "active" : i < activeIdx ? "done" : ""}`}
          >
            <div className="upgrade-stage-dot" />
            {i < activeIdx ? `✓ ${s}` : s}
          </div>
        ))}
      </div>
    </div>
  );
}