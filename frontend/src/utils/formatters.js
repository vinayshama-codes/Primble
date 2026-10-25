// formatters.js
//
import { formLabel } from "./formInstances.js";
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

// An Exposure deduction row (Choice Electric #26): the points that bucket took
// from its pillar, so the rows add up to it (Exposure = 100 minus every row).
// "-20 pts"; nothing taken is "0 pts". Never a negative zero, never a fraction.
export const deductionText = (n) => {
  const pts = Math.round(Number(n) || 0);
  return pts > 0 ? `-${pts} pts` : "0 pts";
};

// Nothing taken is green; a small deduction amber; ten points or more red.
export const deductionColor = (n) => {
  const pts = Math.round(Number(n) || 0);
  return pts <= 0 ? "#10b981" : pts < 10 ? "#f59e0b" : "#ef4444";
};

export const sqsGradeFromScore = (v) => {
  if (v == null) return null;
  if (v >= 90) return "A";
  if (v >= 80) return "B";
  if (v >= 70) return "C";
  if (v >= 60) return "D";
  return "F";
};

// The pre-form Review screen's score (Orbin 22 Sep item 2, 29 Sep 2026): the
// package SQS the backend's one door computed from the facts as they stand,
// printed as "<n> / 100 - <tier>". No forms needed (Brent: SQS must not read
// as forms-dependent - the "so far" wording went 14 Oct). Null when there is no finite score, so a
// missing score reads "Not scored yet" and never "0 / 100" (Number(null) and
// Number("") are both 0).
export const scoreSoFar = (pkg) => {
  const raw = pkg?.package_sqs_score;
  if (typeof raw !== "number" && typeof raw !== "string") return null;
  if (typeof raw === "string" && raw.trim() === "") return null;
  const score = Number(raw);
  if (!Number.isFinite(score)) return null;
  const tier = typeof pkg?.tier === "string" ? pkg.tier.trim() : "";
  return { score, text: tier ? `${score} / 100 - ${tier}` : `${score} / 100` };
};

// Short label for a form where space is tight (e.g. the pinned score header in a
// 300px sidebar). form_name is the full title - "ACORD 137 CA (2023/01) -
// California Commercial Auto Coverages / Limits Section" - which wraps badly
// there, so prefer the form id: "ACORD_137_CA" -> "ACORD 137 CA". Falls back to
// the part of form_name before the first " - " when no id is available.
export const shortFormLabel = (formId, formName) => {
  // "ACORD 137 CA"; a form's second copy "ACORD 131 (Excess)" (7 Oct 2026).
  if (formId) return formLabel(formId);
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

// A document source with the page that prints its value (Brent, 19 Oct 2026:
// "keep the source and page reference"): "Package Policy.pdf p.1". The server
// names a page only when the document prints the value there.
export const sourceLabel = (src) => {
  const name = String(src?.filename || src?.file || "").trim();
  if (!name) return "";
  return src?.page ? `${name} p.${src.page}` : name;
};

// "Submission Ready" (Brent, 19 Oct 2026): 90+ AND no open hard stop. Read from
// the score as shown and the score's own open hard stops, so a credit patched
// onto the number moves it too; else the server's flag; else 90+, which the 60
// cap a hard stop holds makes the same rule.
export const submissionReady = (pkg) => {
  if (!pkg) return false;
  const score = Number(pkg.package_sqs_score ?? pkg.sqs_score ?? 0);
  if (pkg.open_hard_stops != null) return score >= 90 && !Number(pkg.open_hard_stops);
  if (typeof pkg.submission_ready === "boolean") return pkg.submission_ready;
  return score >= 90;
};
