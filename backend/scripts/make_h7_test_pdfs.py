"""
make_h7_test_pdfs.py - live test kit for V1 H7 (client section 12,
"Audit / Edit History Completion").

    py backend/scripts/make_h7_test_pdfs.py

Writes THREE PDFs into `h7_test_data/` plus README-HOW-TO-TEST.md.

WHY ONLY THREE, AND WHY THESE THREE
-----------------------------------
Section 12 is about HISTORY, and history is made by ACTIONS, not by document
content. The documents only have to make each of the client's eight material
events *reachable* in the UI; everything else is the click sequence in the
README. So the kit is deliberately small:

  H7A  the package policy      - the thing everything else acts on. Carries an
                                 AI-extractable employee count (the value the
                                 producer will override), an umbrella limit that
                                 H7B will disagree with, and deliberate GAPS so
                                 there are real recommendations to answer,
                                 dismiss and send to the client.
  H7B  a certificate           - states a DIFFERENT umbrella limit, which is the
                                 only way to make the Data Consistency picker
                                 appear, which is the only way to produce a
                                 `conflict_resolved` event.
  H7C  a foreign loss run      - a DIFFERENT insured, which is the only way to
                                 raise the multi-insured integrity review, which
                                 is the only way to produce the `overridden`
                                 half of `producer_override`. Used in its own
                                 scenario so it never contaminates S1's facts.

Two events need no document at all: `document_reclassified` (the reclassify
control is on every session, not just flagged ones - verified in
form_routes.document_reclassify) and `package_downloaded` (any download with an
open item).

DESIGN RULE (inherited from the C5 kit, C5-C)
---------------------------------------------
A fixture must PRINT the value its check cites. `_verify()` at the bottom
re-reads every generated PDF with pdfplumber and FAILS THE BUILD if a cited
value is missing, if H7A stops being multi-page, or if the two umbrella limits
ever stop disagreeing - because a conflict fixture that agrees proves nothing
and would look like a passing test.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

OUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "h7_test_data",
)

TODAY = datetime.now()


def _d(days: int) -> str:
    return (TODAY + timedelta(days=days)).strftime("%m/%d/%Y")


# An ordinary future annual term - H7 is not testing date routing, and an
# expired term would add an unrelated hard stop to every screenshot.
EFF, EXP = _d(21), _d(21 + 365)

# ── S1 identity ──────────────────────────────────────────────────────────────
A_NAME   = "Marrow Ridge Mechanical LLC"
A_ADDR   = "4820 Fenwick Industrial Parkway"
A_CSZ    = "Akron, OH 44312"
A_FEIN   = "82-4419077"
A_POLICY = "CPP-70255-26"
A_CARRIER = "Continental Basin Insurance Company"
A_NAIC   = "24112"

# THE conflict. H7A prints $3,000,000; H7B prints $1,000,000. The Data
# Consistency picker exists to make the producer choose, and that choice is the
# `conflict_resolved` event.
A_UMBRELLA = "$3,000,000"
B_UMBRELLA = "$1,000,000"

# THE generated-value override target. Chosen by MEASUREMENT, not by guess: the
# override classification needs the edited PDF box to resolve (via
# `_ACORD_FIELD_RULES`) to a canonical fact that actually exists in the store,
# because that envelope is what states "the model produced this". Driving the
# real stamper over ACORD 125 with these facts, 8 of 13 populated boxes qualify;
# Description of Operations is the safest of them - long, obviously AI-written,
# natural for a producer to refine, and it fires no identity hard stop the way
# editing the insured name or a policy date would.
A_OPS = "Commercial HVAC installation, service and duct cleaning"
OPS_OVERRIDE_TO = ("Commercial HVAC installation, service, duct cleaning and "
                   "24-hour emergency repair")

# THE CONTRAST CASE, deliberately included. `BusinessInformation_FullTimeEmployeeCount_A`
# is alias-stamped from `num_employees`, but the field rules map that BOX to
# `num_employees_full_time` - a key nothing writes - so the prior envelope
# cannot be found and the edit is classified `corrected an existing entry`
# instead of an override. That is the SAFE direction (it never invents an
# override that did not happen) and the README asks for both edits so the limit
# is visible to the owner rather than buried in a comment.
A_EMPLOYEES = "24"
OVERRIDE_TO = "30"

# ── S2 identity - deliberately a DIFFERENT insured ───────────────────────────
C_NAME   = "Halevy Brothers Electric Inc"
C_FEIN   = "45-2208814"


# ── Layout helpers (same conventions as make_c5_test_pdfs.py) ───────────────

def _page(c, title, subtitle=""):
    c.setFont("Helvetica-Bold", 15)
    c.drawString(1 * inch, 10.2 * inch, title)
    if subtitle:
        c.setFont("Helvetica", 9.5)
        c.drawString(1 * inch, 9.95 * inch, subtitle)
    c.setLineWidth(0.7)
    c.line(1 * inch, 9.82 * inch, 7.5 * inch, 9.82 * inch)
    return 9.5 * inch


def _row(c, y, label, value, lw=2.9):
    c.setFont("Helvetica-Bold", 9)
    c.drawString(1 * inch, y, f"{label}:")
    c.setFont("Helvetica", 9)
    c.drawString((1 + lw) * inch, y, str(value))
    return y - 0.21 * inch


def _head(c, y, text):
    y -= 0.10 * inch
    c.setFont("Helvetica-Bold", 10.5)
    c.drawString(1 * inch, y, text)
    return y - 0.22 * inch


def _para(c, y, text):
    c.setFont("Helvetica", 9)
    c.drawString(1 * inch, y, text)
    return y - 0.19 * inch


def _table(c, y, headers, rows, cols):
    c.setFont("Helvetica-Bold", 8.5)
    for x, h in zip(cols, headers):
        c.drawString(x * inch, y, h)
    y -= 0.20 * inch
    c.setFont("Helvetica", 8)
    for r in rows:
        for x, v in zip(cols, r):
            c.drawString(x * inch, y, str(v))
        y -= 0.19 * inch
    return y - 0.06 * inch


# ── H7A: the package policy (MULTI-PAGE on purpose) ─────────────────────────

def h7a(path):
    """Four pages. Multi-page matters: `ocr_service` emits a page marker only
    for a multi-page document, and the record's Document + Page evidence (which
    the history sits alongside) depends on those markers.

    GAPS ARE DELIBERATE - no loss history, no NAICS, no subcontractor answers,
    no payroll. They are what produce the open recommendations the README then
    answers, dismisses, resolves and sends to the client. A complete fixture
    would leave nothing to act on and the whole kit would prove nothing.
    """
    c = canvas.Canvas(path, pagesize=LETTER)

    # p1 - identity + the employee count that will be overridden
    y = _page(c, "COMMERCIAL PACKAGE POLICY", "Declarations - Page 1 of 4")
    y = _row(c, y, "Named Insured", A_NAME)
    y = _row(c, y, "Mailing Address", A_ADDR)
    y = _row(c, y, "City / State / Zip", A_CSZ)
    y = _row(c, y, "Federal Employer ID", A_FEIN)
    y = _row(c, y, "Policy Number", A_POLICY)
    y = _row(c, y, "Carrier", A_CARRIER)
    y = _row(c, y, "NAIC Code", A_NAIC)
    y = _row(c, y, "Policy Effective Date", EFF)
    y = _row(c, y, "Policy Expiration Date", EXP)
    y = _head(c, y, "APPLICANT INFORMATION")
    y = _row(c, y, "Business Type", "Limited Liability Company")
    y = _row(c, y, "Number of Employees", A_EMPLOYEES)
    y = _row(c, y, "Annual Gross Sales", "$4,180,000")
    y = _row(c, y, "Description of Operations", A_OPS)
    c.showPage()

    # p2 - GL
    y = _page(c, "GENERAL LIABILITY COVERAGE PART", "Page 2 of 4")
    y = _row(c, y, "Each Occurrence Limit", "$1,000,000")
    y = _row(c, y, "General Aggregate Limit", "$2,000,000")
    y = _row(c, y, "Products/Completed Operations Aggregate", "$2,000,000")
    y = _row(c, y, "Personal & Advertising Injury Limit", "$1,000,000")
    y = _row(c, y, "Damage To Premises Rented", "$100,000")
    y = _row(c, y, "Medical Expense Limit", "$10,000")
    y = _row(c, y, "General Liability Deductible", "$1,000")
    y = _row(c, y, "Coverage Form", "Occurrence")
    y = _row(c, y, "General Liability Premium", "$18,430")
    c.showPage()

    # p3 - THE umbrella limit that H7B will contradict
    y = _page(c, "COMMERCIAL UMBRELLA COVERAGE PART", "Page 3 of 4")
    y = _row(c, y, "Each Occurrence Limit", A_UMBRELLA)
    y = _row(c, y, "Aggregate Limit", A_UMBRELLA)
    y = _row(c, y, "Self-Insured Retention", "$10,000")
    y = _row(c, y, "Umbrella Premium", "$6,900")
    y = _head(c, y, "SCHEDULE OF UNDERLYING INSURANCE")
    y = _table(
        c, y,
        ["Coverage", "Carrier", "Policy Number", "Limit"],
        [["General Liability", A_CARRIER, A_POLICY, "$1,000,000"],
         ["Business Auto", A_CARRIER, A_POLICY, "$1,000,000"]],
        [1.0, 2.4, 4.5, 6.2],
    )
    c.showPage()

    # p4 - premium summary
    y = _page(c, "PREMIUM SUMMARY", "Page 4 of 4")
    y = _table(
        c, y,
        ["Coverage Part", "Premium"],
        [["General Liability", "$18,430"],
         ["Commercial Umbrella", "$6,900"],
         ["Commercial Property", "$9,145"]],
        [1.0, 4.5],
    )
    y = _row(c, y, "Total Policy Premium", "$34,475")
    y -= 0.15 * inch
    y = _para(c, y, "This declarations page is issued in connection with the")
    y = _para(c, y, "policy identified above and supersedes any prior issue.")
    c.showPage()
    c.save()


# ── H7B: the certificate that DISAGREES ─────────────────────────────────────

def h7b(path):
    """Single page. Same insured, and an umbrella limit that contradicts H7A's.

    That contradiction is the ENTIRE job of this file. Without it there is no
    Data Consistency card, so no `conflict_resolved` event, so clause "conflict
    resolution" cannot be tested at all.
    """
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "CERTIFICATE OF LIABILITY INSURANCE",
              "This certificate is issued as a matter of information only.")
    y = _row(c, y, "Insured", A_NAME)
    y = _row(c, y, "Address", A_ADDR)
    y = _row(c, y, "City / State / Zip", A_CSZ)
    y = _row(c, y, "Insurer A", A_CARRIER)
    y = _row(c, y, "NAIC #", A_NAIC)
    y = _head(c, y, "COVERAGES")
    y = _table(
        c, y,
        ["Type of Insurance", "Policy Number", "Eff", "Exp", "Limits"],
        [["Commercial General Liability", A_POLICY, EFF, EXP, "$1,000,000"],
         ["Umbrella Liability", A_POLICY, EFF, EXP, B_UMBRELLA],
         ["Excess Liability - Aggregate", A_POLICY, EFF, EXP, B_UMBRELLA]],
        [1.0, 2.9, 4.1, 5.0, 6.0],
    )
    y = _head(c, y, "DESCRIPTION OF OPERATIONS")
    y = _para(c, y, "Commercial HVAC installation and service. Certificate")
    y = _para(c, y, "holder is included as additional insured where required")
    y = _para(c, y, "by written contract.")
    c.showPage()
    c.save()


# ── H7C: a DIFFERENT insured, to raise the integrity review ─────────────────

def h7c(path):
    """A loss run belonging to somebody else.

    `submission_integrity.assess_submission_integrity` returns LOW (and
    review_required) only when 2+ documents carry DISTINCT insured identities.
    A different name AND a different FEIN is the unambiguous way to get there,
    so the producer is offered "Continue anyway" - and that click is the
    `overridden=True` half of `producer_override`, the one that sat in a table
    with no reader until H7.

    Kept in its OWN scenario: uploaded alongside H7A it would otherwise drag a
    foreign entity's facts into the package S1 spends ten steps auditing.
    """
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "CARRIER LOSS RUN REPORT",
              "Valued as of " + _d(-7))
    y = _row(c, y, "Named Insured", C_NAME)
    y = _row(c, y, "Federal Employer ID", C_FEIN)
    y = _row(c, y, "Mailing Address", "77 Trestle Court, Youngstown, OH 44503")
    y = _row(c, y, "Policy Number", "WC-33917-24")
    y = _row(c, y, "Carrier", "Lakeshore Mutual Casualty")
    y = _head(c, y, "CLAIM DETAIL")
    y = _table(
        c, y,
        ["Claim Number", "Date of Loss", "Description", "Paid", "Status"],
        [["LM-88201", _d(-420), "Laceration - hand", "$4,180", "Closed"],
         ["LM-88644", _d(-190), "Vehicle backing", "$11,905", "Open"]],
        [1.0, 2.3, 3.5, 5.5, 6.5],
    )
    y = _head(c, y, "SUMMARY")
    y = _row(c, y, "Total Incurred", "$16,085")
    y = _row(c, y, "Number of Claims", "2")
    c.showPage()
    c.save()


# ── Self-verification: the fixture must print what the checks cite ──────────

def _verify():
    import pdfplumber

    def text_of(name):
        with pdfplumber.open(os.path.join(OUT_DIR, name)) as pdf:
            return [(p.extract_text() or "") for p in pdf.pages]

    problems = []

    a_pages = text_of("H7A_package_policy.pdf")
    a_all = "\n".join(a_pages)
    # Page markers only exist for a multi-page document.
    if len(a_pages) < 2:
        problems.append("H7A must be multi-page (page markers depend on it)")
    for value in (A_NAME, A_FEIN, A_POLICY, A_UMBRELLA, A_EMPLOYEES, A_OPS,
                  "$1,000,000"):
        if value not in a_all:
            problems.append(f"H7A does not print {value!r}")

    b_all = "\n".join(text_of("H7B_certificate.pdf"))
    for value in (A_NAME, B_UMBRELLA):
        if value not in b_all:
            problems.append(f"H7B does not print {value!r}")

    c_all = "\n".join(text_of("H7C_foreign_loss_run.pdf"))
    for value in (C_NAME, C_FEIN):
        if value not in c_all:
            problems.append(f"H7C does not print {value!r}")

    # THE fixture invariant. A conflict kit whose two documents agree raises no
    # picker, produces no `conflict_resolved` event, and every check below it
    # would "pass" by never running.
    if A_UMBRELLA == B_UMBRELLA:
        problems.append("H7A and H7B state the SAME umbrella limit - there is "
                        "no conflict left to resolve")
    # The direction that actually matters: if the CERTIFICATE also printed the
    # policy's limit it could be read as agreeing and the picker would never
    # appear. The reverse is NOT a problem and must not be checked - H7A's
    # umbrella page legitimately lists $1,000,000 as the UNDERLYING GL limit,
    # which is what a real umbrella declarations page looks like. Sanitising
    # that away would be building the convenient fixture D22 warns about, and
    # if the extractor cannot tell an umbrella limit from its own underlying
    # schedule that is a real finding worth surfacing, not one to hide.
    if A_UMBRELLA in b_all:
        problems.append("H7B prints H7A's umbrella limit too - the two "
                        "documents would agree and no conflict would be raised")

    # The integrity review needs DISTINCT identities, not a name variant.
    if C_NAME == A_NAME or C_FEIN == A_FEIN:
        problems.append("H7C shares S1's identity - no multi-insured review "
                        "would be raised")

    # The override target must actually change.
    if A_EMPLOYEES == OVERRIDE_TO:
        problems.append("the employee-count contrast edit does not change the value")
    if A_OPS == OPS_OVERRIDE_TO:
        problems.append("the operations-description override does not change the value")

    if problems:
        raise SystemExit("FIXTURE VERIFY FAILED:\n  - " + "\n  - ".join(problems))
    print("fixture verify: OK (3 PDFs, conflict intact, identities distinct)")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    h7a(os.path.join(OUT_DIR, "H7A_package_policy.pdf"))
    h7b(os.path.join(OUT_DIR, "H7B_certificate.pdf"))
    h7c(os.path.join(OUT_DIR, "H7C_foreign_loss_run.pdf"))
    _write_readme()
    _verify()
    print(f"wrote 3 PDFs + README-HOW-TO-TEST.md to {OUT_DIR}")


def _write_readme():
    readme = f"""# H7 - Audit / Edit History Completion: HOW TO TEST

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

* **"{A_EMPLOYEES}" gets no page citation.** Values under 4 normalised
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
A Data Consistency card should show **{A_UMBRELLA}** (from H7A) against
**{B_UMBRELLA}** (from H7B).
> CHECK 2: BOTH values are shown, each tagged with the file it came from.
Choose **{A_UMBRELLA}** and confirm. If the picker offers a note box, type
`Dec page governs` - it is optional and there may not be one yet.

### Generate

**Step 3 -** generate **ACORD 125** and **ACORD 131**.
(131 because the package carries an umbrella; 125 is the field-edit target.)

### On the generated forms

**Step 4a - override an AI-generated value** (produces `field_changed`, kind =
generated-value override)
On ACORD 125 find **Description of Operations**. It reads
`{A_OPS}`.
Change it to `{OPS_OVERRIDE_TO}` and save.
> CHECK 3: the field saves and the score refreshes.

**Step 4b - the CONTRAST edit** (produces `field_changed`, kind = correction)
Also on ACORD 125, find **Full Time Employees** = `{A_EMPLOYEES}` and change it
to `{OVERRIDE_TO}`.
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
>   - the employee-count row shows `"{A_EMPLOYEES}" -> "{OVERRIDE_TO}"` and
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

H7C belongs to **{C_NAME}** - a different insured with a different FEIN - so
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
| `H7A_package_policy.pdf` | {A_NAME} | 4 pages. The subject of every action. Umbrella {A_UMBRELLA}, employees {A_EMPLOYEES}, an AI-written operations description to override, deliberate gaps. |
| `H7B_certificate.pdf` | {A_NAME} | Umbrella {B_UMBRELLA} - the disagreement that creates the conflict to resolve. |
| `H7C_foreign_loss_run.pdf` | {C_NAME} | A different insured, so the multi-insured review can be overridden. S2 only. |
"""
    with open(os.path.join(OUT_DIR, "README-HOW-TO-TEST.md"), "w",
              encoding="utf-8") as fh:
        fh.write(readme)


if __name__ == "__main__":
    main()
