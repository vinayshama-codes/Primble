// The score with and without forms (13 Oct 2026, owner + Brent: "the SQS can
// exist without the forms", and once forms are generated it is recalculated
// with them). A post-generation package score carries `without_forms` - the
// same package scored by the pre-form recipe, no forms - so the screen can say
// why the number moved at generation instead of leaving a 100 that became a 97
// unexplained.
//
// Pure functions, no React: the backend suite runs them under node.

const num = (x) => (typeof x === "number" && Number.isFinite(x) ? x : null);

// { text, detail } for a post-generation package score, or null when there is
// nothing to compare (before forms, an old payload, a failed side score).
export function formsEffect(packageSqs) {
  const without = num(packageSqs?.without_forms?.score);
  const withForms = num(packageSqs?.package_sqs_score);
  if (without === null || withForms === null) return null;
  const text = `Without forms ${without} · With forms ${withForms}`;
  let detail = "";
  if (withForms < without) {
    detail = "The forms add their boxes and the checks across forms. Confirm the Please verify values on each form and clear the form warnings to close the gap.";
  } else if (withForms > without) {
    detail = "The forms answered gaps the documents left open.";
  }
  return { text, detail, without, withForms };
}
