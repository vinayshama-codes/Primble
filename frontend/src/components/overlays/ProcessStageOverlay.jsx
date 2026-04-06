import { useState, useEffect } from "react";

export default function ProcessStageOverlay({ stages, advanceAfter = 3000 }) {
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