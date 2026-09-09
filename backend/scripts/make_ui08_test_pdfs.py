"""make_ui08_test_pdfs.py - TWO PDFs that put the Data Consistency panel into the
exact state UI-08 was reported in: a confirmed Umbrella / Excess Limit whose row
names the ACORD forms it reaches.

    py backend/scripts/make_ui08_test_pdfs.py

Writes ui08_test_data/ at the repo root: two PDFs plus README-HOW-TO-TEST.md.

WHAT UI-08 WAS
--------------
The confirmed row read:

    Umbrella / Excess Limit   Confirmed: $3,000,000 - applied to ACORD 131, ACORD 25

That form list is DERIVED from the stamping paths (`_forms_for_field` ->
`pdf_service.forms_consuming_fact`) - it is where a confirmed value CAN land,
not proof it has been written. On the pre-form screen no form exists yet, so
"applied to" claimed a write that had not happened. It now reads
"available for". "Applied to" is reserved for a real write event.

WHY TWO DOCUMENTS
-----------------
`assess_underwriting_consistency` compares PER-DOCUMENT facts. One document
cannot disagree with itself, so a single PDF produces no conflict, no Confirm
button, and nothing to look at. These are the client's literal Orbin values -
dec page $3,000,000, later COI $1,000,000 - because that is the case the row
was screenshotted in (the replay-client-report-verbatim rule).

FIXTURE RULES (each one is a way this kit could silently stop working)
---------------------------------------------------------------------
1. $3,000,000 is printed ONLY on the umbrella declarations page (twice, as its
   own occurrence and aggregate limits - what a real umbrella dec looks like)
   and NEVER inside the GL block. C23 is the reason: an umbrella figure loose
   near the GL limits is exactly what used to be merged onto
   `gl_each_occurrence`. The GL block enumerates SIX distinct limits, so it wins
   its own composite outright, and $1,000,000 outnumbers $3,000,000 nine to two
   across the kit.
2. The carrier deliberately DISAGREES across the two documents as well
   (Employers Mutual Casualty Company vs EMC Property & Casualty Company - the
   client's own pair). That row is the CONTROL: `carrier_name` has an empty
   forms list, so it must render "Confirmed: <value>" with NO form clause at
   all. It proves the clause is conditional and that the fix did not staple a
   sentence onto every row.
3. The applicant name, FEIN and policy term are BYTE-IDENTICAL across both
   documents. Those are the hard-stop reconcilable keys; letting any of them
   differ would put a blocking conflict on the same screen and bury the two
   rows this kit is about.
4. The umbrella carries its underlying schedule, a stated GL/Auto/EL tower and
   a follow-form statement. Without them `_calculate_umbrella_adequacy` walks to
   0 and the form caps at 60 with a HARD STOPS block - noise that has nothing to
   do with UI-08.
5. Dates run from TODAY, so nothing drifts into the expired-term or renewal
   paths.
6. No vehicles, no WC payroll, no property values. Every one of those opens its
   own capture table or validation row on the same screen.
"""
from __future__ import annotations

import io
import os
import sys
from datetime import datetime, timedelta

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT_DIR = os.path.join(REPO, "ui08_test_data")

TODAY = datetime.now()
EFF = (TODAY + timedelta(days=14)).strftime("%m/%d/%Y")
EXP = (TODAY + timedelta(days=14 + 365)).strftime("%m/%d/%Y")

INSURED = "ORBIN CONTRACTING LLC"
ADDRESS = "2411 East 9 Mile Road, Suite 120, Warren, MI 48091"
FEIN = "84-2210987"
AGENCY = "CRS Insurance Brokerage LLC"

# The disagreeing pair. Both are real EMC entities, which is the point: this is
# a genuine cross-document disagreement, not a formatting variant the
# normalizer would collapse.
CARRIER_POLICY = "Employers Mutual Casualty Company"
CARRIER_COI = "EMC Property & Casualty Company"

UMBRELLA_POLICY = "$3,000,000"      # dec page
UMBRELLA_COI = "$1,000,000"         # certificate

OPS = (
    "Orbin Contracting LLC performs commercial interior finishing and light "
    "renovation work at commercial premises. The applicant self performs "
    "carpentry and finish work and retains licensed subcontractors for "
    "mechanical and electrical scopes."
)


# -- Layout helpers ----------------------------------------------------------

def _page(c, title, subtitle=""):
    c.setFont("Helvetica-Bold", 15)
    c.drawString(1 * inch, 10.2 * inch, title)
    if subtitle:
        c.setFont("Helvetica", 9.5)
        c.drawString(1 * inch, 9.95 * inch, subtitle)
    c.setLineWidth(0.7)
    c.line(1 * inch, 9.82 * inch, 7.5 * inch, 9.82 * inch)
    return 9.5 * inch


def _row(c, y, label, value, lw=3.1):
    c.setFont("Helvetica-Bold", 9)
    c.drawString(1 * inch, y, "%s:" % label)
    c.setFont("Helvetica", 9)
    c.drawString((1 + lw) * inch, y, str(value))
    return y - 0.21 * inch


def _head(c, y, text):
    y -= 0.10 * inch
    c.setFont("Helvetica-Bold", 10.5)
    c.drawString(1 * inch, y, text)
    return y - 0.22 * inch


def _wrap(c, y, text, width=98):
    c.setFont("Helvetica", 9)
    words, line = text.split(), ""
    for w in words:
        if len(line) + len(w) + 1 > width:
            c.drawString(1 * inch, y, line)
            y -= 0.19 * inch
            line = w
        else:
            line = ("%s %s" % (line, w)).strip()
    if line:
        c.drawString(1 * inch, y, line)
        y -= 0.19 * inch
    return y - 0.06 * inch


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
    return y - 0.09 * inch


# -- Document 1: the package policy declarations -----------------------------

def build_policy(path):
    c = canvas.Canvas(path, pagesize=LETTER)

    y = _page(c, "COMMERCIAL PACKAGE POLICY - DECLARATIONS",
              "%s  |  NAIC 21415  |  Policy No. 5D3-40-02---26" % CARRIER_POLICY)
    y = _row(c, y, "Named Insured", INSURED)
    y = _row(c, y, "Mailing Address", ADDRESS)
    y = _row(c, y, "FEIN", FEIN)
    y = _row(c, y, "Entity Type", "Limited Liability Company")
    y = _row(c, y, "Producer / Agency", AGENCY)
    y = _row(c, y, "Policy Period", "%s to %s" % (EFF, EXP))
    y = _row(c, y, "Annual Gross Sales", "$4,120,000")
    y = _row(c, y, "Number of Employees", "22")

    y = _head(c, y, "DESCRIPTION OF OPERATIONS")
    y = _wrap(c, y, OPS)

    # Fixture rule 1: six distinct limits, so this block wins its own composite
    # and no umbrella figure can be dragged onto a GL scalar (C23).
    y = _head(c, y, "COMMERCIAL GENERAL LIABILITY - COVERAGE PART")
    y = _row(c, y, "Each Occurrence Limit", "$1,000,000")
    y = _row(c, y, "General Aggregate Limit", "$2,000,000")
    y = _row(c, y, "Products/Completed Operations Aggregate", "$2,000,000")
    y = _row(c, y, "Personal & Advertising Injury Limit", "$1,000,000")
    y = _row(c, y, "Damage to Premises Rented to You", "$300,000")
    y = _row(c, y, "Medical Expense Limit (any one person)", "$10,000")
    y = _row(c, y, "General Liability Premium", "$34,180")

    y = _head(c, y, "BUSINESS AUTO - COVERAGE PART")
    y = _row(c, y, "Liability Combined Single Limit", "$1,000,000")
    y = _row(c, y, "Covered Autos - Liability", "Symbol 01 - Any Auto")
    y = _row(c, y, "Business Auto Premium", "$8,940")

    y = _head(c, y, "WORKERS COMPENSATION - EMPLOYERS LIABILITY")
    y = _row(c, y, "Bodily Injury by Accident - Each Accident", "$1,000,000")
    y = _row(c, y, "Bodily Injury by Disease - Policy Limit", "$1,000,000")
    y = _row(c, y, "Bodily Injury by Disease - Each Employee", "$500,000")

    c.showPage()

    # Page 2 - the umbrella. THE figure this kit exists for.
    y = _page(c, "COMMERCIAL LIABILITY UMBRELLA - DECLARATIONS",
              "%s  |  Policy No. 5U7-40-02---26" % CARRIER_POLICY)
    y = _row(c, y, "Named Insured", INSURED)
    y = _row(c, y, "Policy Period", "%s to %s" % (EFF, EXP))
    y = _row(c, y, "Each Occurrence Limit", UMBRELLA_POLICY)
    y = _row(c, y, "Aggregate Limit", UMBRELLA_POLICY)
    y = _row(c, y, "Self-Insured Retention", "$10,000")
    y = _row(c, y, "Umbrella Premium", "$11,650")

    # Fixture rule 4: a stated tower and a follow-form sentence, so the
    # umbrella pillar does not walk to 0 and cap the form at 60.
    y = _head(c, y, "SCHEDULE OF UNDERLYING INSURANCE")
    y = _table(
        c, y,
        ["COVERAGE", "CARRIER", "POLICY NUMBER", "LIMITS"],
        [["Commercial General Liability", CARRIER_POLICY, "5D3-40-02---26",
          "$1,000,000 occurrence / $2,000,000 aggregate"],
         ["Business Auto Liability", CARRIER_POLICY, "5D3-40-02---26",
          "$1,000,000 combined single limit"],
         ["Employers Liability", CARRIER_POLICY, "5W1-40-02---26",
          "$1,000,000 / $1,000,000 / $500,000"]],
        [1.0, 2.6, 4.5, 5.9],
    )
    y = _wrap(c, y, "This umbrella policy follows the form of the underlying "
                    "insurance scheduled above except as otherwise stated in "
                    "the policy provisions.")

    c.showPage()
    c.save()


# -- Document 2: the certificate of insurance --------------------------------

def build_coi(path):
    c = canvas.Canvas(path, pagesize=LETTER)

    y = _page(c, "CERTIFICATE OF LIABILITY INSURANCE",
              "Issued by %s  |  Date: %s" % (AGENCY, TODAY.strftime("%m/%d/%Y")))
    y = _wrap(c, y, "THIS CERTIFICATE IS ISSUED AS A MATTER OF INFORMATION ONLY "
                    "AND CONFERS NO RIGHTS UPON THE CERTIFICATE HOLDER. THIS "
                    "CERTIFICATE DOES NOT AFFIRMATIVELY OR NEGATIVELY AMEND, "
                    "EXTEND OR ALTER THE COVERAGE AFFORDED BY THE POLICIES BELOW.")

    # Fixture rule 3: identity fields are byte-identical to the policy.
    y = _row(c, y, "Insured", INSURED)
    y = _row(c, y, "Insured Address", ADDRESS)
    y = _row(c, y, "FEIN", FEIN)
    y = _row(c, y, "Producer", AGENCY)

    # Fixture rule 2: the CONTROL conflict. Same tower, different EMC entity.
    y = _head(c, y, "INSURER(S) AFFORDING COVERAGE")
    y = _row(c, y, "Insurer A", "%s   NAIC 25186" % CARRIER_COI)

    y = _head(c, y, "COVERAGES")
    y = _table(
        c, y,
        ["TYPE OF INSURANCE", "POLICY NUMBER", "EFF", "EXP", "LIMITS"],
        [["Commercial General Liability", "5D3-40-02---26", EFF, EXP,
          "Each occurrence $1,000,000"],
         ["General Aggregate", "5D3-40-02---26", EFF, EXP,
          "$2,000,000"],
         ["Business Auto Liability", "5D3-40-02---26", EFF, EXP,
          "Combined single limit $1,000,000"],
         ["Umbrella Liability - Occurrence", "5U7-40-02---26", EFF, EXP,
          "Each occurrence %s" % UMBRELLA_COI],
         ["Umbrella Liability - Aggregate", "5U7-40-02---26", EFF, EXP,
          UMBRELLA_COI]],
        [1.0, 3.0, 4.3, 5.1, 5.9],
    )

    y = _head(c, y, "CERTIFICATE HOLDER")
    y = _row(c, y, "Certificate Holder", "Fenwick Industrial Owners LP")
    y = _row(c, y, "Holder Address", "700 Tower Drive, Suite 900, Troy, MI 48098")

    c.showPage()
    c.save()


# -- Self-verification -------------------------------------------------------
#
# An offline probe proves the FUNCTION, never the SEAM around it. So this is
# honest about what it checks: it drives the REAL reconciler over the facts
# these documents are written to produce, and it reads the REAL frontend source
# for the string that was fixed. It cannot prove extraction reads the amounts
# off the PDFs - only the live run does that, which is why the kit exists.

POLICY_FACTS = {
    "applicant_name": INSURED,
    "fein": FEIN,
    "mailing_address": ADDRESS,
    "carrier_name": CARRIER_POLICY,
    "effective_date": EFF,
    "expiration_date": EXP,
    "umbrella_limit": UMBRELLA_POLICY,
    "gl_each_occurrence": "$1,000,000",
    "gl_aggregate": "$2,000,000",
}
COI_FACTS = {
    "applicant_name": INSURED,
    "fein": FEIN,
    "mailing_address": ADDRESS,
    "carrier_name": CARRIER_COI,
    "effective_date": EFF,
    "expiration_date": EXP,
    "umbrella_limit": UMBRELLA_COI,
    "gl_each_occurrence": "$1,000,000",
    "gl_aggregate": "$2,000,000",
}

ACORD_MODAL = os.path.join(
    REPO, "frontend", "src", "components", "form", "AcordModal.jsx")


def _docs(pdf_names):
    return [
        {"doc_id": "1", "filename": pdf_names[0], "doc_type": "policy",
         "facts": dict(POLICY_FACTS), "text": ""},
        {"doc_id": "2", "filename": pdf_names[1], "doc_type": "certificate",
         "facts": dict(COI_FACTS), "text": ""},
    ]


def verify(pdf_names):
    from services.underwriting_consistency import assess_underwriting_consistency

    problems = []
    docs = _docs(pdf_names)
    merged = dict(POLICY_FACTS)

    # 1. Unconfirmed: the umbrella row must be a real conflict with both amounts.
    before = assess_underwriting_consistency(docs, merged, {})
    rows = dict((f["fact_key"], f) for f in before["fields"])
    umb = rows.get("umbrella_limit")
    if not umb:
        problems.append("MISSING: no umbrella_limit row at all")
    else:
        if umb["status"] != "conflict":
            problems.append("WRONG:   umbrella_limit status is %r, expected 'conflict'"
                            % umb["status"])
        seen = set(v["display"] for v in umb["values"])
        if seen != set([UMBRELLA_POLICY, UMBRELLA_COI]):
            problems.append("WRONG:   umbrella values %s, expected both amounts"
                            % sorted(seen))
        if umb["forms"] != ["ACORD_131", "ACORD_25"]:
            problems.append("WRONG:   umbrella forms %s, expected ['ACORD_131', 'ACORD_25']"
                            % umb["forms"])

    # 2. The control row: carrier disagrees too, and carries NO forms list, so
    #    the confirmed line has no form clause to get the wording wrong in.
    car = rows.get("carrier_name")
    if not car or car["status"] != "conflict":
        problems.append("MISSING: carrier_name is not a conflict - the control row is dead")
    elif car["forms"]:
        problems.append("WRONG:   carrier_name forms %s, expected [] (control row)"
                        % car["forms"])

    # 3. The hard-stop identity keys must NOT conflict (fixture rule 3).
    for key in ("applicant_name", "fein", "effective_date", "expiration_date"):
        r = rows.get(key)
        if r and r["status"] == "conflict":
            problems.append("BAD:     %s conflicts - a blocking row would bury the kit" % key)

    # 4. Confirmed: this is the exact state the screenshot was taken in.
    after = assess_underwriting_consistency(
        docs, merged, {"umbrella_limit": UMBRELLA_POLICY})
    umb2 = dict((f["fact_key"], f) for f in after["fields"]).get("umbrella_limit") or {}
    if umb2.get("status") != "confirmed":
        problems.append("WRONG:   after confirming, status is %r" % umb2.get("status"))
    if umb2.get("confirmed_value") != UMBRELLA_POLICY:
        problems.append("WRONG:   confirmed_value %r" % umb2.get("confirmed_value"))
    if umb2.get("forms") != ["ACORD_131", "ACORD_25"]:
        problems.append("WRONG:   confirmed forms %s" % umb2.get("forms"))

    # 5. The fix itself. This is the only check that actually looks at UI-08.
    try:
        src = io.open(ACORD_MODAL, encoding="utf-8").read()
    except Exception as exc:
        problems.append("BAD:     cannot read AcordModal.jsx - %s" % exc)
        return problems, None
    if "applied to ${formsLabel}" in src:
        problems.append("REGRESSED: AcordModal still renders 'applied to ${formsLabel}'")
    if "available for ${formsLabel}" not in src:
        problems.append("MISSING:   AcordModal does not render 'available for ${formsLabel}'")

    label = ", ".join(f.replace("ACORD_", "ACORD ") for f in (umb2.get("forms") or []))
    expected_line = "Confirmed: %s - available for %s" % (UMBRELLA_POLICY, label)
    return problems, expected_line


README = """# UI-08 live test - "available for" vs "applied to"

TWO uploads, ONE sentence to read.

## What was wrong

The Data Consistency row for a confirmed Umbrella limit read:

    Umbrella / Excess Limit   Confirmed: $3,000,000 - applied to ACORD 131, ACORD 25

That form list is derived from where the value CAN be stamped, not from a write
that happened. On the pre-form screen no form exists yet, so "applied to" was
claiming something untrue. It now reads **available for**.

## 1. Upload

Upload BOTH files together as ONE new package (not two sessions, and not into an
existing session - extraction caches per document):

  * `ui08-orbin-package-policy.pdf`   - the dec page. Umbrella limit $3,000,000.
  * `ui08-orbin-coi.pdf`              - the certificate. Umbrella limit $1,000,000.

They disagree on purpose. One document cannot disagree with itself, so a single
upload produces no conflict, no Confirm button and nothing to look at.

## 2. Go to the pre-form Review screen

Do NOT generate forms yet. The whole point of UI-08 is the state BEFORE
generation. Open the **DATA CONSISTENCY** panel.

You should see two rows marked VALUES DIFFER - CONFIRM:

  * **Umbrella / Excess Limit** - $3,000,000 (package policy) vs $1,000,000 (COI)
  * **Carrier** - Employers Mutual Casualty Company vs EMC Property & Casualty Company

## 3. The check

Select **$3,000,000** on the Umbrella row and click **Confirm**.

The row must now read:

    Umbrella / Excess Limit   Confirmed: $3,000,000 - available for ACORD 131, ACORD 25

**PASS** - it says "available for".
**FAIL** - it says "applied to", anywhere on that line.

## 4. The control - do this one too

Confirm the **Carrier** row the same way (pick either value).

It must read simply:

    Carrier   Confirmed: Employers Mutual Casualty Company

with **no form clause at all**. `carrier_name` has no derived form list, so
there is nothing to name. If a form clause appeared there, the fix was applied
too widely.

## 5. Nothing else should have moved

This was a text change to one line. Everything below is unchanged and must stay
that way:

  * Both radio lists still show which document each value came from.
  * The button now reads **Confirm** (UI-07, same session). It still does
    exactly what it did: confirming re-runs the pipeline, so the value
    propagates to every applicable form, warning and score by itself.
  * The free-text override box beside it still accepts a typed value.
  * Scores, hard stops and warnings are identical to before the fix.
  * After you generate forms, ACORD 131 and ACORD 25 must carry $3,000,000.

## 6. What to send back

* A screenshot of the confirmed Umbrella row.
* A screenshot of the confirmed Carrier row (the control).
* Anything that read wrong in plain English.

## Known and expected

* Until you confirm it, the umbrella limit is WITHHELD from stamping
  (`CONFLICT_WITHHOLD_KEYS`) - the forms would ship that box blank rather than
  guess between $3M and $1M. That is the designed behaviour, and it is also why
  "applied to" was wrong: at that moment nothing had been applied anywhere.
* Confirming re-runs the pipeline, so the screen takes a few seconds and the
  package score can move.
* An "Umbrella" hard stop should NOT appear - the dec page carries a full
  schedule of underlying insurance and a follow-form statement on purpose.
"""


def main():
    if not os.path.isdir(OUT_DIR):
        os.makedirs(OUT_DIR)
    policy_name = "ui08-orbin-package-policy.pdf"
    coi_name = "ui08-orbin-coi.pdf"

    problems, expected = verify((policy_name, coi_name))

    build_policy(os.path.join(OUT_DIR, policy_name))
    build_coi(os.path.join(OUT_DIR, coi_name))
    with io.open(os.path.join(OUT_DIR, "README-HOW-TO-TEST.md"), "w",
                 encoding="utf-8") as f:
        f.write(README)

    print("wrote %s" % os.path.join(OUT_DIR, policy_name))
    print("wrote %s" % os.path.join(OUT_DIR, coi_name))
    print("wrote %s" % os.path.join(OUT_DIR, "README-HOW-TO-TEST.md"))
    if expected:
        print("\nThe row the tester must read, per the real reconciler:")
        print("    Umbrella / Excess Limit   %s" % expected)
    if problems:
        print("\nFIXTURE PROBLEMS:")
        for p in problems:
            print("  " + p)
        return 1
    print("\nOK - conflict + control + confirmed state all verified, and the "
          "frontend renders 'available for'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
