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
        <p style={{ margin: "0 0 16px", fontSize: 20, fontWeight: 700, color: "#0f172a", letterSpacing: "-0.2px", textAlign: "center", lineHeight: 1.4, padding: "0 20px", maxWidth: 420 }}>
          {tagline}
        </p>
      )}
      {note && (
        <div style={{ margin: "0 0 24px", padding: "12px 20px", background: "rgba(253,242,248,0.96)", border: "1px solid rgba(230,27,132,0.18)", borderRadius: 12, maxWidth: 380, width: "calc(100% - 48px)", textAlign: "center" }}>
          <p style={{ margin: 0, fontSize: 13, color: "#9d174d", lineHeight: 1.65, fontWeight: 450 }}>
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