# H7 - Audit / Edit History Completion: HOW TO TEST

Client section 12. Regenerate any time with:

    py backend/scripts/make_h7_test_pdfs.py

Dates are computed from the generation date. **Restart the backend before the
first run** - H7 adds columns (`audit_events.package_label`,
`audit_events.visibility`, `field_source_audit.previous_source`,
`field_source_audit.reason`) and `init_db()` only applies them at startup.

The record is REGENERATED on every click, so if you re-check after a fix you
only need a backend restart and a browser refresh - no re-upload.

---

## What is actually being tested

Section 12 is about HISTORY, so the PDFs barely matter - the CLICK SEQUENCE is
the test. Each numbered step below produces one of the client's eight material
events. The checks are all in one place: **the Audit Record**, downloaded from
the button in the SQS panel on the generated-forms screen.

Two things to know before you start, so you do not report them as failures:

* **"24" gets no page citation.** Values under 4 normalised
  characters are never cited (C5 caveat 1, blank-over-wrong applied to
  lineage). The employee count still appears in the history with its before and
  after - that is what H7 is testing.
* **One click can make two history rows.** Answering a recommendation records
  both "Recommendation answered" and "Field changed" at the same timestamp.
  Those are two true statements about one act, in one store, adjacent in time -
  not a duplicate.

---

# SCENARIO 1 - the full history of one submission

**Upload together:** `H7A_package_policy.pdf` + `H7B_certificate.pdf`

### Pre-form screen

**Step 1 - reclassify a document** (produces `producer_override`)
Find the document list. Change `H7B_certificate.pdf`'s type to something else
(e.g. "Policy / Declarations") using the type control, then change it back if
you like - both moves are recorded.
> CHECK 1: the screen accepts it and the package re-scores.

**Step 2 - resolve the umbrella conflict** (produces `conflict_resolved`)
A Data Consistency card should show **$3,000,000** (from H7A) against
**$1,000,000** (from H7B).
> CHECK 2: BOTH values are shown, each tagged with the file it came from.
Choose **$3,000,000** and confirm. If the picker offers a note box, type
`Dec page governs` - it is optional and there may not be one yet.

### Generate

**Step 3 -** generate **ACORD 125** and **ACORD 131**.
(131 because the package carries an umbrella; 125 is the field-edit target.)

### On the generated forms

**Step 4a - override an AI-generated value** (produces `field_changed`, kind =
generated-value override)
On ACORD 125 find **Description of Operations**. It reads
`Commercial HVAC installation, service and duct cleaning`.
Change it to `Commercial HVAC installation, service, duct cleaning and 24-hour emergency repair` and save.
> CHECK 3: the field saves and the score refreshes.

**Step 4b - the CONTRAST edit** (produces `field_changed`, kind = correction)
Also on ACORD 125, find **Full Time Employees** = `24` and change it
to `30`.
> This one is EXPECTED to record `corrected an existing entry`, NOT an override.
> That box maps to a canonical key nothing writes, so the prior AI envelope
> cannot be found, and the classifier says the milder thing rather than
> inventing an override that may not have happened. Both rows must appear; only
> 4a should be labelled an override. See CHECK 7.

**Step 5 - answer a recommendation** (produces `recommendation_answered`)
In the SQS panel, find any card with an answer box. Type a real value and
submit.

**Step 6 - reopen it and answer DIFFERENTLY** (the destructive-history case)
Reopen the card you just answered (Reviewed section -> Reopen), then answer it
again with a *different* value.
> This is the case the old code could not record: the answer column is a
> latest-wins UPSERT, so the first answer used to be overwritten and lost.

**Step 7 - dismiss a recommendation WITH a typed reason** (produces
`recommendation_dismissed`)
Pick a different card, click Dismiss, and type a real reason such as
`Carrier confirmed no prior losses`.

**Step 8 - resolve an issue with NO reason** (produces `issue_status_changed`)
In the Hard Stops / Warnings list, mark any issue **Resolved** without typing a
note.
> This is the second case the old record could not show: the export only
> printed issue rows that happened to carry a reason, so a plain resolve was
> invisible.

**Step 9 - send the client questionnaire and answer it** (produces
`client_answers_applied` + `field_changed` rows with role = Client)
Send to client, open the client link, answer at least two questions, submit.
*(Skip if email/link is not wired in your environment - note it as untested.)*

**Step 10 - download with open items** (produces `package_downloaded`)
Download the package while items are still open. When prompted for an override
note, type `Client needs it today`.

### Step 11 - THE CHECKS. Download the **Audit Record**.

Open the downloaded `.txt`. Work through these:

> **CHECK 4 - the section exists.** There is a section headed
> `COMPLETE HISTORY (chronological)`. There is NO section headed `EVENT LOG`
> (it was removed - it showed the same rows with less on each).

> **CHECK 5 - every row names a person.** Every line under COMPLETE HISTORY has
> a `By: <name> <email> (Role)` line. **Not one** should say `By: unknown`, and
> none should print a bare UUID. Before H7 the record named no human anywhere.

> **CHECK 6 - all eight events are present.** Look for these labels:
>   - `Field changed`            (steps 4 and 9)
>   - `Recommendation answered`  (steps 5 and 6 - **TWO rows, different values**)
>   - `Recommendation dismissed` (step 7)
>   - `Issue status changed`     (step 8)
>   - `Data consistency conflict resolved` (step 2)
>   - `Producer override`        (step 1)
>   - `Package downloaded with open items` (step 10)
>   - `Client questionnaire answers applied` (step 9, if run)

> **CHECK 7 - the generated-value override is LABELLED, and only where it
> should be.** Two rows from step 4:
>   - the Description of Operations row shows the old text -> the new text AND
>     `Change: overrode an AI-generated value`;
>   - the employee-count row shows `"24" -> "30"` and
>     `Change: corrected an existing entry` - **this is correct, not a bug**
>     (see step 4b).
> A row where the producer filled a BLANK must say `filled a blank field`.
> **If a field that was EMPTY is ever called an override, that IS a bug** -
> report it, because that direction puts a false statement about a human into
> an E&O record.

> **CHECK 8 - the client is not filed as the producer.** The rows from step 9
> must read `(Client)`, not `(Producer)` - even though the questionnaire is
> applied under YOUR user id. This is the subtle one.

> **CHECK 9 - reasons appear where they were given.** The dismissal (step 7)
> shows `Reason: Carrier confirmed no prior losses`; the download (step 10)
> shows `Reason: Client needs it today`. The issue resolved with no reason
> (step 8) still appears, with no Reason line - present, not hidden.

> **CHECK 10 - both answers survived.** Step 5's answer AND step 6's different
> answer are BOTH in the history, in order. If only the last one is there, the
> spine is not being written.

> **CHECK 11 - the older sections now name their actor too.** DISMISSED ITEMS,
> QUESTIONS ANSWERED BY PRODUCER, DATA CONSISTENCY RESOLUTIONS, ISSUE STATUS
> OVERRIDES, DOWNLOADED WITH OPEN ITEMS and MODIFICATION HISTORY each carry a
> `By:` line now.

> **CHECK 12 - MODIFICATION HISTORY says how, not just who.** Each row has a
> `How:` line naming the source, and where a previous value existed it names
> what produced it.

> **CHECK 13 - PRODUCER OVERRIDES section.** Step 1's reclassification appears
> with its before -> after document type, a timestamp and an actor. This table
> had three writers and NO reader before H7.

### Step 12 - the Activity Log (one model, D50)

Open the navbar **Activity Log**.
> **CHECK 14 - it still works and is still clean.** It shows package
> milestones - forms generated, submission scored, downloads, questionnaire
> events - with their normal titles and coloured dots.
> **CHECK 15 - it does NOT show E&O noise.** Your field edit, your dismissal
> and your score snapshots must NOT appear here. If you see raw event names
> like `field_changed` in the feed, the visibility filter is broken.
> **CHECK 16 - older activity is still there.** Packages from before today are
> still listed. Nothing existing was dropped by the move.

---

# SCENARIO 2 - producer override of a system determination

**New submission. Upload together:** `H7A_package_policy.pdf` +
`H7C_foreign_loss_run.pdf`

H7C belongs to **Halevy Brothers Electric Inc** - a different insured with a different FEIN - so
the package should be flagged.

**Step 1 -** on the pre-form screen the Submission Integrity review appears.
> **CHECK 17:** it names BOTH insureds and offers a choice.

**Step 2 -** choose **Continue anyway** (do NOT remove the document - removing
it is housekeeping, keeping it is the override).

**Step 3 -** generate **ACORD 125** (any one form, so the Audit Record button
is reachable).

**Step 4 -** download the **Audit Record**.
> **CHECK 18 - PRODUCER OVERRIDES** carries a
> `Submission integrity review: continue_anyway` entry, with the line
> **"The producer kept a package the system had flagged for review."**, the
> verdict at the time, both detected insured names, a timestamp and an actor.
> **CHECK 19 - COMPLETE HISTORY** carries a matching `Producer override` row.

---

## If something looks wrong

* Grep the backend log for `record_material_change`, `not recorded` or
  `Failed to log audit event` - every history write logs its failure with a
  traceback, and a lost history row NEVER fails the action it records (so the
  UI will look fine while the record is short).
* A history row with `By: unknown` means the act had no acting user - report
  which step produced it.
* If COMPLETE HISTORY is empty, the backend was not restarted after the schema
  change.

## Files

| File | Insured | Purpose |
|---|---|---|
| `H7A_package_policy.pdf` | Marrow Ridge Mechanical LLC | 4 pages. The subject of every action. Umbrella $3,000,000, employees 24, an AI-written operations description to override, deliberate gaps. |
| `H7B_certificate.pdf` | Marrow Ridge Mechanical LLC | Umbrella $1,000,000 - the disagreement that creates the conflict to resolve. |
| `H7C_foreign_loss_run.pdf` | Halevy Brothers Electric Inc | A different insured, so the multi-insured review can be overridden. S2 only. |
