// formatters.js

export const gradeColor = (g) =>
  ({ A: "#10b981", B: "#14b8a6", C: "#f59e0b", D: "#ef4444", F: "#dc2626" }[g] || "#6b7280");

export const barColor = (v) =>
  v >= 80 ? "#10b981" : v >= 60 ? "#f59e0b" : "#ef4444";

const PERSONAL_DOMAINS = [
  "gmail.com","yahoo.com","hotmail.com","outlook.com","icloud.com",
  "live.com","aol.com","msn.com","ymail.com","mail.com",
  "protonmail.com","proton.me","tutanota.com","zoho.com",
];

export const isPersonalEmail = (email) => {
  const d = email.toLowerCase().split("@")[1] || "";
  return PERSONAL_DOMAINS.includes(d);
};