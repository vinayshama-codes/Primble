// A questionnaire question shown only while its parent's answer is one of a set
// of values (Orbin G2, 1 Oct 2026: the landlord, asked the moment the client
// answers that the business rents its space). The twin of the backend's
// services/follow_ups.py - the page, the receipt and the server agree on what
// was shown. A question with no condition is always shown.

export const followUpShown = (question, answers) => {
  const cond = question && question.show_if;
  if (!cond) return true;
  const raw = (answers || {})[cond.field];
  const val = String(raw == null ? "" : raw).trim();
  return (cond.any_of || []).some((v) => String(v).trim() === val);
};

export const shownQuestions = (questions, answers) =>
  (questions || []).filter((q) => followUpShown(q, answers));

// The answers for questions that are not on screen are dropped before submit:
// a landlord typed and then hidden by answering "we own it" is not an answer.
export const answersForShown = (questions, answers) => {
  const hidden = new Set((questions || [])
    .filter((q) => !followUpShown(q, answers)).map((q) => q.field_name));
  return Object.fromEntries(Object.entries(answers || {}).filter(([k]) => !hidden.has(k)));
};
