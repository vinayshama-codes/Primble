import { useState, useEffect } from "react";

export default function UpgradeStageOverlay() {
  const stages = ["Updating Billing", "Activating Plan", "Finalizing Account"];
  const [activeIdx, setActiveIdx] = useState(0);

  useEffect(() => {
    const timers = [
      setTimeout(() => setActiveIdx(1), 2000),
      setTimeout(() => setActiveIdx(2), 4500),
    ];
    return () => timers.forEach(clearTimeout);
  }, []);

  return (
    <div className="upgrade-stage-overlay">
      <div className="upgrade-stage-spinner" />
      <div className="upgrade-stage-steps">
        {stages.map((stage, i) => (
          <div
            key={stage}
            className={`upgrade-stage-step ${i === activeIdx ? "active" : i < activeIdx ? "done" : ""}`}
          >
            <div className="upgrade-stage-dot" />
            {i < activeIdx ? `✓ ${stage}` : stage}
          </div>
        ))}
      </div>
    </div>
  );
}