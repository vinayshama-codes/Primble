export default function SaveStageOverlay({ stage }) {
  const stages   = ["Saving edits", "Generating form"];
  const activeIdx = stage === "saving" ? 0 : 1;

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