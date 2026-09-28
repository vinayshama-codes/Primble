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


// A coverage line's name for the screen. The backend scopes values to a line
// FAMILY key ("general_liab", "inland_marine" - services/lob_canon.py); the key
// is an identifier, not a label, and printed raw it read "general liab". Prefer
// the name the policy itself prints for that line (`line_printed` on the line
// records - the same text the "Policies in this submission" table shows), then
// a readable family name, then the key made readable.
const LINE_FAMILY_LABELS = {
  general_liab: "General Liability",
  auto: "Automobile",
  umbrella: "Umbrella",
  workers_comp: "Workers Compensation",
  property: "Property",
  inland_marine: "Inland Marine",
  crime: "Crime",
  cyber: "Cyber",
  professional: "Professional Liability",
  epli: "Employment Practices Liability",
  pollution: "Pollution",
  directors_officers: "Directors and Officers",
  employee_benefits: "Employee Benefits",
  liquor: "Liquor Liability",
};

export const lineLabel = (key, lineRecords) => {
  const k = String(key || "").trim();
  if (!k) return "";
  const rec = (lineRecords || []).find((r) => r && r.line === k && String(r.line_printed || "").trim());
  if (rec) return String(rec.line_printed).trim();
  if (LINE_FAMILY_LABELS[k]) return LINE_FAMILY_LABELS[k];
  const s = k.replace(/_/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
};
