# STAMPING-BRIEF.md

> **Purpose.** Brief an independent engineer to diagnose, from the code, why ACORD form
> fields are stamped with wrong values.
>
> **Conclusions are deliberately omitted from this document.** It contains symptoms,
> constraints, and how to run things. It does not contain any prior analysis of cause.
> Form your own view from the code.

---

## 1. Read this before you read anything else

Several documents in this repo contain a previous engineer's root-cause claims, written as
settled fact. They have NOT been independently verified. Some are known to be stale, and at
least two contain claims that were later measured false.

| file | what it is |
|---|---|
| `CLAUDE.md` | project instructions - **auto-loaded into your context**. Roughly the last two-thirds is a running "Known Issues" narrative of prior fixes and their claimed causes |
| `fix-form-stamping.md` | 1,700 lines of prior diagnosis of this exact problem |
| `HANDOFF.md`, `improving-ll.md` | LLM cost/quality work, prior conclusions |
| `docs/KNOWN_LIMITATIONS.md`, `docs/DECISION_TREE_MAPPING.md` | assorted |

**Treat every causal claim in those files as an unverified hypothesis.** The parts worth
trusting are the factual ones: stack, env vars, schema conventions, the rule that
`backend/forms_schemas/*.json` is never modified, and the DB schema convention.

The reason this brief exists is that repeated fixes have been made against those documents'
conclusions and the output has not improved. A fresh derivation is wanted.

---

## 2. What the system does

Insurance brokers upload policy documents (declarations pages, endorsements, loss runs).
The system OCRs them, extracts data, the user selects which ACORD forms they need, and the
system fills those forms' PDF fields and returns the completed PDFs.

* 17 supported ACORD forms. Field schemas: `backend/forms_schemas/*.json` (read-only,
  129-1135 fields each). Each entry carries the PDF field type (`ft`) and ACORD's own
  tooltip text (`tu`).
* Backend: FastAPI + PostgreSQL. LLM: OpenAI. OCR: Google Cloud Vision.
* Entry points worth knowing: `backend/routes/form_routes.py`.

**The pipeline as the product owner describes it** (their words, unverified by you):

> we make a first LLM call to find facts and flags, and we use those to recommend forms and
> in SQS scoring and also we use some of the facts in form mapping. then we make a 2nd LLM
> call after the user selects the forms, and in that we find the form values.

---

## 3. The problem statement you are being asked to solve

Values are stamped into the wrong fields, or values that are not in the document are
invented, or fields that should be filled are left blank. This has been reported by the
client across six test runs of the **same source document**.

Each round, individual reported values were fixed. The number of functions grew
substantially. The client's reports did not stop, and new wrong values appeared in
categories that had previously been fine.

**The question:** is there a fundamental reason this keeps happening, and is the current
architecture more complicated than the problem requires?

The product owner's framing, worth engaging with directly:

> we need to find values in the dec page uploaded by the user, and we know which values to
> find because we have all the schemas of forms that user selects. how difficult is that
> getting? why do we need to write a lot of functions for this?

---

## 4. Observed issues :
Values stamping on the form are wrong and very wrong and sometimes ai is making values up that are not even in the dec page. You need to run an independent analysis to find the issues and do not depend on claude.md or and other md files, comments written near functions and i need you to look into the code directly to find out the issue 

## 5. Constraints - these are not negotiable

1. **No loss of form coverage.** A correctness fix that leaves more boxes blank than before
   is not acceptable. This has happened repeatedly and is the product owner's primary
   concern. Measure before and after, per field, by name.
2. **Do not weaken the Yes/No evidence rules.** The stated rule: if the document indicates
   a Y or N, stamp it; if `Y`, an explanation is mandatory; if there is no conclusive
   evidence either way, leave it blank.
3. **Prefer blank over wrong** for values that would be a misstatement on a legal document -
   but do not blank a legitimate, document-grounded answer to achieve it.
4. **Nothing may be hardcoded** to this document, this client, or ACORD 125. Every rule must
   be derived (ACORD's own tooltips and field types are a legitimate derivation source) and
   must hold across all 17 forms.
5. **Never modify `backend/forms_schemas/*.json`.**
6. Any change to an LLM call, prompt, batching or chunking must be recorded in
   `improving-ll.md` in the same commit.

---

## 6. How to run and measure

```bash
# tests - from backend/
py -m pytest -q
```

Current baseline: **1758 passed / 2 failed / 2 skipped.** The two failures
(`test_arq_acord125_missing_only`, `test_normalization`) are pre-existing and unrelated to
form stamping. Anything else is new.

```bash
# prompt shape / prefix-cache inspection - offline, zero API cost
py backend/scripts/inspect_gap_fill_prompts.py
```

Do **not** verify prompt changes by diffing two live runs; the pipeline is
non-deterministic and jitter hides regressions.

**The working tree is not clean.** There is a large uncommitted change set from the
previous engineer:

```bash
git diff --stat HEAD -- backend/services/
git status --short
```

To compare current behaviour against the last commit, a detached worktree is useful:

```bash
git worktree add /tmp/head HEAD --detach
```

Running the same probe against both trees with identical inputs is the only reliable way to
tell whether a change added or removed coverage.

**You can exercise the fill pipeline offline with no API key.** The deterministic passes and
every guard are plain Python over a facts dict and a schema dict. You do not need live
documents to measure what gets filled, what gets withheld from the model, and what gets
asked of the model.

---

## 7. What is not wanted

* Another guard that inspects a value after it has already been stamped wrongly. That is the
  pattern that produced the current state.
* An architecture proposal that does not state, per change, whether it increases or
  decreases the number of correctly filled fields, and how that was measured.
* Deference to the prior conclusions in section 1.

## 8. Deliverable

A problem statement and root-cause analysis derived from the code, with evidence:
`file:line` references and measured numbers, not reasoning from comments or docstrings.
Where you find the architecture more complicated than the problem requires, say so plainly
and say what the simpler shape is.

If your conclusion contradicts something in `CLAUDE.md` or `fix-form-stamping.md`, that is
expected and useful. Say which claim and what the measurement was.
