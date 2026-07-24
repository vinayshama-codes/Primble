// formatters.js
//
// Decision_Tree.txt §522-527 tier mapping (client-confirmed):
//   A: 90-100 "Submission Ready" (Green)
//   B: 80-89  "Almost There"     (Yellow)
//   C: 70-79  "Needs Work"       (Orange)
//   D: 60-69  "Major Gaps"       (Red)
//   F: <60    "Not Ready"        (Red)

export const gradeColor = (g) =>
  ({ A: "#10b981", B: "#eab308", C: "#f59e0b", D: "#ef4444", F: "#ef4444" }[g] || "#6b7280");

export const barColor = (v) =>
  v >= 80 ? "#10b981" : v >= 70 ? "#f59e0b" : "#ef4444";

export const sqsGradeFromScore = (v) => {
  if (v == null) return null;
  if (v >= 90) return "A";
  if (v >= 80) return "B";
  if (v >= 70) return "C";
  if (v >= 60) return "D";
  return "F";
};

// Short label for a form where space is tight (e.g. the pinned score header in a
// 300px sidebar). form_name is the full title - "ACORD 137 CA (2023/01) -
// California Commercial Auto Coverages / Limits Section" - which wraps badly
// there, so prefer the form id: "ACORD_137_CA" -> "ACORD 137 CA". Falls back to
// the part of form_name before the first " - " when no id is available.
export const shortFormLabel = (formId, formName) => {
  if (formId) return String(formId).replace(/_/g, " ").trim();
  if (formName) return String(formName).split(" - ")[0].trim();
  return "This form";
};

