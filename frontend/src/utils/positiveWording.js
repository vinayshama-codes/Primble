// Positive score wording on screen (Brent's Choice Electric #16; owner, 9 Oct
// 2026). Brent: "Remove this highlighted part about the SQS. Or change to
// '- fulfill to increase your Submission Quality Score (SQS)™.' Aim to
// encourage positive messaging of the good outcome rather than a negative."
// The owner: exactly that, on the screen only, on every similar message.
//
// SCREEN ONLY. A hard stop / warning keeps its stored message word for word:
// its issue id, its Dismissed / Resolved status, the legacy rule table and
// the score's own trace are all keyed on that text. This rewrites the copy a
// person reads, at the moment it is drawn, and nothing else.
//
// Every message the backend can send with a "your score is capped / held /
// pinned" clause is listed below by its own shape (the backend suite harvests
// those strings from the Python source and fails when a new one appears that
// this file does not rewrite). Anything else passes through unchanged.
// Pure: no React.

export const SQS_POSITIVE = "fulfill to increase your Submission Quality Score (SQS)™";

// The score's name in the current wording, and in older sessions' stored messages
// ("SQS capped at 85", "Score is capped at 60 until ...").
const SQS_NAME = "(?:Submission Quality Score \\(SQS\\)|SQS|Score)";

const RULES = [
  // "Carrier-Grade COPE incomplete - Submission Quality Score (SQS) capped at 85.
  // Missing: ..." - the clause Brent highlighted, replaced by his own words. An
  // older session stored it with a dash of another kind ("... \u2014 SQS capped at 85", an em dash).
  [new RegExp(`\\s+[-\u2013\u2014]\\s+${SQS_NAME}\\s+(?:is\\s+)?capped at \\d+`, "g"), ` - ${SQS_POSITIVE}`],
  // "FEIN differs across uploaded documents. Submission Quality Score (SQS) is
  // capped at 60 until this is confirmed." / "... unless the difference is
  // explained." - the condition only restates the Fix that follows.
  [new RegExp(`\\.\\s+${SQS_NAME}\\s+is\\s+capped at \\d+(?:\\s+(?:until|unless)\\b[^.]*)?\\.`, "g"), ` - ${SQS_POSITIVE}.`],
  // "... Submission can proceed but your Submission Quality Score (SQS) will be
  // capped." - the reassurance stays, the cap goes.
  // (An older session stored it without "your": "... but SQS will be capped.")
  [new RegExp(`\\.\\s+Submission can proceed but (?:your )?${SQS_NAME} will be capped\\.`, "g"), `. Submission can proceed - ${SQS_POSITIVE}.`],
  // "... uploaded loss runs. Loss History is held at 45 until the discrepancy is
  // resolved - confirm with the insured which is correct."
  [/\.\s+Loss History is held at \d+ until the discrepancy is resolved\s+-\s+(\w)/g,
    (_m, first) => ` - ${SQS_POSITIVE}. ${first.toUpperCase()}`],
  // "... claim years are not readable - pinned at 60. Confirm claim years ..."
  [/\s+-\s+pinned at \d+\./g, ` - ${SQS_POSITIVE}.`],
];

// The text a person sees for a message. Non-strings pass through untouched.
export function positiveScoreWording(text) {
  if (typeof text !== "string" || !text) return text;
  let out = text;
  for (const [pattern, replacement] of RULES) {
    pattern.lastIndex = 0;
    out = out.replace(pattern, replacement);
  }
  return out;
}
