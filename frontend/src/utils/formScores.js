// A save that moved the package's warnings re-scores EVERY form on the server
// (15 Oct 2026, live 0353c36b: confirming one value took the package to 99
// while nine forms stayed at 85 under a warning that no longer fired). The
// save's response then carries `forms_sqs` - { formId: sqs } - and each listed
// form takes its new score; a form not listed keeps its own.
export function withFormScores(forms, formsSqs) {
  if (!forms || typeof forms !== "object" || !formsSqs || typeof formsSqs !== "object") return forms;
  let changed = false;
  const next = { ...forms };
  for (const [fid, sqs] of Object.entries(formsSqs)) {
    if (next[fid] && sqs && typeof sqs === "object") {
      next[fid] = { ...next[fid], sqs };
      changed = true;
    }
  }
  return changed ? next : forms;
}
