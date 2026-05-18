// formatters.js

export const gradeColor = (g) =>
  ({ A: "#10b981", B: "#14b8a6", C: "#f59e0b", D: "#ef4444", F: "#dc2626" }[g] || "#6b7280");

export const barColor = (v) =>
  v >= 80 ? "#10b981" : v >= 60 ? "#f59e0b" : "#ef4444";

