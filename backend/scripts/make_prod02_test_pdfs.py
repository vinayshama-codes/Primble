"""make_prod02_test_pdfs.py - live kit for PROD-02 (2026-09-09).

    py backend/scripts/make_prod02_test_pdfs.py

Writes to prod02_test_data/ at the repo root, plus README-HOW-TO-TEST.md.

WHY TWO FILES AND NOT ONE. The defect is a CROSS-DOCUMENT conflict.
``detect_source_conflicts`` returns ``[]`` on ``len(docs) < 2`` and
``extraction_pipeline`` only calls it when ``len(active_docs) > 1``. One
uploaded file is one document, so a single PDF cannot raise the card even
BEFORE the fix - a one-file run would prove nothing. Two files, uploaded
together as ONE session, is the floor.

THE CONTROLS MUST SIT ON THE PATH UNDER TEST, and the first draft of this kit
got that wrong. On a LIVE run `extraction_pipeline` passes
``skip_fields = RECONCILABLE_FIELD_KEYS | assessed_keys``, and
`ENABLE_FULL_FIELD_RECONCILIATION` auto-discovers **every scalar fact**, so
`num_employees` / `carrier_name` / `total_revenue` / `policy_number` are ALL
owned by the Data Consistency picker and never reach `detect_source_conflicts`
at all. `_auto_scalar_keys` explicitly skips dicts, which is exactly why the
client's card came from `risk_transfer` - a structured dict - and why every
control below is a `risk_transfer` SUB-KEY.

  1. THE FIX. Both files print a long boilerplate clause into
     `risk_transfer.specific_wording_requirements` - the dec page's
     service-of-process CONDITION and the ACORD 25's own PREPRINTED FOOTER,
     both verbatim from the client's screenshot. No card may appear.

  2. NOTHING GENUINE WAS LOST. `risk_transfer.mortgagee_name` is "First
     National Bank of Toledo" against "Wells Fargo Bank NA", and
     `certificate_holder_name` is two different parties. Both cards MUST still
     appear, from the same function, printing both raw values.

  3. TWO PRINTINGS OF ONE NAME ARE STILL NOT A CONFLICT.
     `risk_transfer.loss_payee_name` is "Midwest Equipment Leasing Company"
     against "Midwest Equipment Leasing Co." - silent.

  4. THE PICKER IS UNTOUCHED. The four scalars above are still seeded with a
     genuine conflict (employees 47 vs 62), a carrier ALIAS pair (the
     regression the first version of this fix nearly shipped) and two
     formatting-only pairs. They render in **Data Consistency**, not in
     Warnings (UI-13), and prove this change did not disturb that half.

HONEST LIMIT, stated rather than hidden. Extraction is a MODEL. This kit puts
the two clauses on the page under headings that invite the wording fact, but it
cannot guarantee the model files them under
`risk_transfer.specific_wording_requirements` rather than somewhere else. If
check 1 passes because the fact was never populated, that is a PASS BY ACCIDENT
and the README says how to tell the difference in one command.
"""
import os
import sys
import textwrap

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reportlab.lib.pagesizes import LETTER            # noqa: E402
from reportlab.lib.units import inch                  # noqa: E402
from reportlab.pdfgen import canvas                   # noqa: E402

from scripts.make_sys07_test_pdfs import (            # noqa: E402
    _page, _new_page, _row, _head, _table, _coverage,
    EFF, EXP, AGENCY, GL_LIMITS, AUTO_LIMITS,
)

OUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "prod02_test_data",
)

INSURED = "Harrow Ridge Fabrication LLC"
ADDR = "1420 Ironworks Parkway, Suite 300, Toledo, OH 43604"
FEIN = "34-7712085"
OPS = ("Structural steel fabrication and installation for commercial "
       "construction projects")

# ── 1. THE FACT UNDER TEST - both sides are boilerplate ────────────────────
# Verbatim from the client's PROD-02 screenshot. Neither is a requirement
# anybody imposed on this insured: the first is a service-of-process policy
# CONDITION, the second is the text ACORD prints on every certificate before
# anyone types into it.
DEC_WORDING = (
    "If the insured's whereabouts for service of process cannot be determined "
    "through reasonable effort, the insured agrees to designate and irrevocably "
    "appoint us as the agent of the insured for service of process, pleadings "
    "or other filings in a civil action brought against the insured."
)
COI_WORDING = (
    "If the certificate holder is an ADDITIONAL INSURED, the policy(ies) must "
    "have ADDITIONAL INSURED provisions or be endorsed. If SUBROGATION IS "
    "WAIVED, subject to the terms and conditions of the policy, certain "
    "policies may require an endorsement. A statement on this certificate does "
    "not confer rights to the certificate holder in lieu of such endorsement(s)."
)

# ── 2. POSITIVE CONTROLS on the SAME path - must SURVIVE ───────────────────
# risk_transfer sub-keys, because that is the only family that still reaches
# detect_source_conflicts on a live run (see the module docstring).
MORTGAGEE_DEC = "First National Bank of Toledo"
MORTGAGEE_COI = "Wells Fargo Bank NA"
HOLDER_DEC = "Kestrel Terminal Authority"
HOLDER_COI = "Brandt Logistics Group Inc"

# ── 3. SILENT CONTROL on the same path - one name, two printings ───────────
PAYEE_DEC = "Midwest Equipment Leasing Company"
PAYEE_COI = "Midwest Equipment Leasing Co."

# ── 4. PICKER CONTROLS - these render in Data Consistency, not Warnings ────
EMPLOYEES_DEC = "47"
EMPLOYEES_COI = "62"

# ── 3. THE REGRESSION CONTROL - one carrier, two printings ─────────────────
CARRIER_DEC = "Employers Mutual Casualty Company"
CARRIER_COI = "EMC Property & Casualty Company"
NAIC = "21415"

# ── 4. FORMATTING CONTROLS - must stay silent ──────────────────────────────
REVENUE_DEC = "$5,000,000"
REVENUE_COI = "5000000"
POLICY_DEC = "BBC7263 - 26"
POLICY_COI = "BBC7263"


def _wrap(c, y, text, width=104, indent=1.0):
    """Draw a long clause as wrapped body text. _para draws one line and these
    clauses are 40+ words - the whole point of the test."""
    c.setFont("Helvetica", 8.5)
    for line in textwrap.wrap(text, width):
        c.drawString(indent * inch, y, line)
        y -= 0.155 * inch
    return y - 0.06 * inch


def build_dec(path):
    """Declarations page. Carries the service-of-process CONDITION."""
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "COMMERCIAL PACKAGE POLICY - DECLARATIONS",
              "Common Policy Declarations")
    y = _row(c, y, "Named Insured", INSURED)
    y = _row(c, y, "Mailing Address", ADDR)
    y = _row(c, y, "FEIN", FEIN)
    y = _row(c, y, "Entity Type", "Limited Liability Company")
    y = _row(c, y, "Contact", "Dana Whitcomb, (419) 555-0182, "
                              "dwhitcomb@harrowridge.com")
    y = _row(c, y, "Producer / Agency", AGENCY)
    y = _row(c, y, "Policy Period", "%s to %s" % (EFF, EXP))
    y = _row(c, y, "Description of Operations", OPS)
    y = _row(c, y, "Annual Gross Sales", REVENUE_DEC)
    y = _row(c, y, "Number of Employees", EMPLOYEES_DEC)
    y = _row(c, y, "Years in Business", "16")
    y = _row(c, y, "NAICS Code", "238120")

    y = _head(c, y, "SCHEDULE OF COVERAGES")
    y = _table(c, y, ["COVERAGE LINE", "COMPANY", "NAIC", "POLICY NUMBER", "PREMIUM"],
               [["General Liability", CARRIER_DEC, NAIC, POLICY_DEC, "$8,240"],
                ["Commercial Auto", CARRIER_DEC, NAIC, "6E7-40-02---26", "$3,110"]],
               [1.0, 2.25, 4.45, 5.05, 6.65])
    y = _row(c, y, "Total Advance Premium", "$11,350")

    y = _new_page(c, "COMMERCIAL GENERAL LIABILITY DECLARATIONS",
                  "Coverage Part - General Liability")
    y = _coverage(c, y, "GENERAL LIABILITY COVERAGE PART", CARRIER_DEC, NAIC,
                  POLICY_DEC, "$8,240", GL_LIMITS)
    y = _coverage(c, y, "BUSINESS AUTO COVERAGE PART", CARRIER_DEC, NAIC,
                  "6E7-40-02---26", "$3,110", AUTO_LIMITS)

    # THE FACT UNDER TEST. A policy CONDITION, printed the way a carrier prints
    # one - under a conditions heading, in the endorsement-wording register that
    # invites `specific_wording_requirements`.
    y = _new_page(c, "COMMON POLICY CONDITIONS",
                  "Applicable to all coverage parts")
    y = _head(c, y, "SERVICE OF PROCESS AND LEGAL NOTICES - REQUIRED WORDING")
    y = _wrap(c, y, DEC_WORDING)
    y -= 0.10 * inch
    y = _head(c, y, "ADDITIONAL INSURED STATUS")
    y = _wrap(c, y, "Additional insured status is provided where required by "
                    "written contract executed prior to loss.")
    y -= 0.10 * inch
    # The controls that sit on the SAME code path as the fact under test.
    y = _head(c, y, "INTERESTED PARTIES")
    y = _row(c, y, "Mortgagee", MORTGAGEE_DEC)
    y = _row(c, y, "Loss Payee", PAYEE_DEC)
    y = _row(c, y, "Certificate Holder", HOLDER_DEC)
    c.showPage()
    c.save()


def build_cert(path):
    """ACORD 25-style certificate. Carries ACORD's OWN preprinted footer."""
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "CERTIFICATE OF LIABILITY INSURANCE",
              "ACORD 25 - This certificate is issued as a matter of "
              "information only")
    y = _row(c, y, "Insured", INSURED)
    y = _row(c, y, "Insured Address", ADDR)
    y = _row(c, y, "Producer", AGENCY)
    y = _row(c, y, "Certificate Holder", HOLDER_COI)
    y = _row(c, y, "Mortgagee", MORTGAGEE_COI)
    y = _row(c, y, "Loss Payee", PAYEE_COI)
    y = _row(c, y, "Annual Gross Sales", REVENUE_COI)
    # THE POSITIVE CONTROL. A genuinely different number - this card must live.
    y = _row(c, y, "Number of Employees", EMPLOYEES_COI)

    y = _head(c, y, "COVERAGES")
    y = _table(c, y, ["TYPE OF INSURANCE", "INSURER", "NAIC", "POLICY NUMBER",
                      "EFF DATE"],
               [["General Liability", CARRIER_COI, NAIC, POLICY_COI, EFF],
                ["Automobile Liability", CARRIER_COI, NAIC, "6E74002", EFF]],
               [1.0, 2.35, 4.45, 5.05, 6.65])
    y = _row(c, y, "Each Occurrence", "$1,000,000")
    y = _row(c, y, "General Aggregate", "$2,000,000")
    y = _row(c, y, "Combined Single Limit", "$1,000,000")

    # THE FACT UNDER TEST, other side. This paragraph is printed on EVERY
    # ACORD 25 ever issued, before anyone types a character into the form.
    y = _new_page(c, "CERTIFICATE OF LIABILITY INSURANCE",
                  "ACORD 25 - continued")
    y = _head(c, y, "IMPORTANT - SPECIFIC WORDING REQUIREMENTS")
    y = _wrap(c, y, COI_WORDING)
    y -= 0.10 * inch
    y = _head(c, y, "DESCRIPTION OF OPERATIONS / LOCATIONS / VEHICLES")
    y = _wrap(c, y, "%s is named as additional insured with respect to work "
                    "performed by the named insured, where required by written "
                    "contract." % HOLDER_COI)
    c.showPage()
    c.save()


# ── The kit refuses to claim it is correct ─────────────────────────────────

def _text(path):
    import pdfplumber
    out = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            out.append(page.extract_text() or "")
    return "\n".join(out)


def _norm(s):
    return " ".join(s.split()).lower()


def _verify(dec_path, cert_path):
    problems = []
    dec, cert = _norm(_text(dec_path)), _norm(_text(cert_path))

    # 1. Both clauses actually reached the page, in full.
    for label, clause, blob in (("dec", DEC_WORDING, dec),
                                ("certificate", COI_WORDING, cert)):
        if _norm(clause) not in blob:
            problems.append(
                "the %s file does not print its clause verbatim - the whole "
                "test is that two long paragraphs disagree" % label)
    if len(DEC_WORDING.split()) < 25 or len(COI_WORDING.split()) < 25:
        problems.append("a clause is under the 25-word prose floor, so it "
                        "would be compared as an ordinary value")

    # 2. Every control value actually reached its page.
    pairs = [(MORTGAGEE_DEC, MORTGAGEE_COI), (HOLDER_DEC, HOLDER_COI),
             (PAYEE_DEC, PAYEE_COI), (EMPLOYEES_DEC, EMPLOYEES_COI),
             (CARRIER_DEC, CARRIER_COI), (REVENUE_DEC, REVENUE_COI),
             (POLICY_DEC, POLICY_COI)]
    for a, b in pairs:
        if _norm(a) not in dec:
            problems.append("%r missing from the dec file" % a)
        if _norm(b) not in cert:
            problems.append("%r missing from the certificate file" % b)
        if a == b:
            problems.append("%r is printed identically on both files - that "
                            "control is inert" % a)

    # 3. The clauses must not be accidentally equal.
    if _norm(DEC_WORDING) == _norm(COI_WORDING):
        problems.append("both files print the SAME clause - nothing to compare")

    # 4. THE KIT MUST BITE. Drive the real function over the fact shapes these
    #    pages are built to produce, with the door forced ON (today) and forced
    #    to always agree (the old single-gate behaviour). A kit that cannot show
    #    a before/after difference proves nothing, so it is not shipped.
    problems += _bites()
    return problems


def _bites():
    """Run the REAL detect_source_conflicts over this kit's fact shapes."""
    from services import fact_comparison
    from services.extraction_service import detect_source_conflicts

    def _docs():
        return [
            {"doc_type": "dec_page", "facts": {"risk_transfer": {
                "specific_wording_requirements": DEC_WORDING,
                "mortgagee_name": MORTGAGEE_DEC,
                "certificate_holder_name": HOLDER_DEC,
                "loss_payee_name": PAYEE_DEC}}},
            {"doc_type": "certificate", "facts": {"risk_transfer": {
                "specific_wording_requirements": COI_WORDING,
                "mortgagee_name": MORTGAGEE_COI,
                "certificate_holder_name": HOLDER_COI,
                "loss_payee_name": PAYEE_COI}}},
        ]

    real = fact_comparison.conflict
    fact_comparison.conflict = lambda *a, **k: True      # the OLD single gate
    try:
        before = detect_source_conflicts(_docs())
    finally:
        fact_comparison.conflict = real
    after = detect_source_conflicts(_docs())

    def has(msgs, phrase):
        return any(phrase.lower() in m.lower() for m in msgs)

    bad = []
    if not has(before, "Specific Wording"):
        bad.append("the OLD behaviour does not raise the wording card - this "
                   "kit cannot show the fix doing anything")
    if has(after, "Specific Wording"):
        bad.append("the wording card STILL fires - the fix is not in effect")
    for phrase in ("Mortgagee Name", "Certificate Holder Name"):
        if not has(after, phrase):
            bad.append("%s stopped being reported - a genuine conflict was "
                       "lost" % phrase)
    if has(after, "Loss Payee"):
        bad.append("Loss Payee fired - two printings of one name are not a "
                   "conflict")
    return bad


README = """# PROD-02 live test - "Specific Wording Requirements" boilerplate card

**One session. Upload BOTH files together.**

    P1_dec_page.pdf
    P2_certificate.pdf

## Why two files and not one

This is a **cross-document** conflict. The code that raises the card returns
nothing unless the session has 2+ documents, and one uploaded file is one
document. A single PDF cannot produce the card even on the OLD code, so a
one-file run would prove nothing either way.

## What was reported

The pre-form review screen's **IMPORTANT** band - the 5-second "fix these
first" shortlist - led with:

> Conflicting values for Specific Wording Requirements across documents -
> Dec Page: *If the insured's whereabouts for service of process cannot be
> determined...*, Certificate of Insurance: *If the certificate holder is an
> ADDITIONAL INSURED, the policy(ies) must have ADDITIONAL INSURED provisions
> or be endorsed...*
> **Fix:** Review and confirm the correct value.

Neither side is a requirement anyone imposed on this insured. The first is a
service-of-process policy **condition**; the second is the text **ACORD prints
on every certificate** before anyone fills it in. There was no correct value to
confirm, the card had no control to confirm it with, and it capped the SQS
at 85.

Both files below print those clauses **verbatim**.

## A - In the WARNINGS section (this is the code path that changed)

| # | Check | Expected | What it proves |
|---|---|---|---|
| A1 | Anything mentioning **Specific Wording Requirements** | **NOTHING** - not in IMPORTANT, not in Warnings | the fix |
| A2 | **Mortgagee Name** - First National Bank of Toledo vs Wells Fargo Bank NA | a card, printing **both** names | a genuine conflict on the same path still fires |
| A3 | **Certificate Holder Name** - Kestrel Terminal Authority vs Brandt Logistics Group Inc | a card, printing **both** | same, second witness |
| A4 | Anything about the **Loss Payee** | **NOTHING** | "Midwest Equipment Leasing Company" vs "...Leasing Co." is one name twice |

**A2 and A3 matter as much as A1.** A run where everything went quiet is a
**failure**, not a pass - it would mean the fix silenced the whole family.

## B - In the DATA CONSISTENCY section (a different engine - must be undisturbed)

Every top-level scalar fact is owned by the Data Consistency picker, so these
never reach the function that changed. They are here to prove nothing else
moved, and since UI-13 they render **only** in Data Consistency, not as
warnings.

| # | Check | Expected |
|---|---|---|
| B1 | **Number of employees** 47 vs 62 | a picker row - a real disagreement |
| B2 | **Carrier** - "Employers Mutual Casualty Company" vs "EMC Property & Casualty Company" | **NOTHING** - one carrier, two printings |
| B3 | **Annual revenue** `$5,000,000` vs `5000000` | **NOTHING** - formatting |
| B4 | **Policy number** `BBC7263 - 26` vs `BBC7263` | **NOTHING** - one contract, two printings |

B2 is the one to look hardest at: the first version of this fix replaced the
alias-folding gate instead of adding to it, and that pair started drawing a
card.

## Read the fact, not just the screen (30 seconds)

Check 1 can pass for the wrong reason: extraction is a model, and it may simply
not have filed either clause under the wording fact. Confirm the fact was
actually populated:

    py backend/scripts/dump_session_facts.py <session_id>

Look for `risk_transfer` -> `specific_wording_requirements`.

* **Populated on both documents, and no card on screen** - the real pass.
* **Empty or on one document only** - inconclusive. The pipeline never had two
  values to compare, so the card was never in play. Say so in the report; it is
  not a failure, and it is not a pass either.

## Report back

1. Screenshot of the whole **Warnings** section, IMPORTANT band included.
2. The **Data Consistency** section, in full.
3. The `risk_transfer` block from the fact dump.
4. The package **SQS**. It should NOT be capped at 85 by a wording item; a cap
   from the mortgagee / certificate-holder conflicts is expected and correct.

## Known, and not what this kit tests

The IMPORTANT band still ranks by TIER, and every real underwriting warning
(umbrella attachment, property COPE, auto symbols, WC payroll) sits in the
LOWER tier than any cross-document conflict. Removing this card frees the top
slot; it does not reorder the list. That is a separate, owner-level decision -
see "Still open, deliberately" in `1stSep-liveTestFixes.md`.
"""


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    dec_path = os.path.join(OUT_DIR, "P1_dec_page.pdf")
    cert_path = os.path.join(OUT_DIR, "P2_certificate.pdf")
    build_dec(dec_path)
    build_cert(cert_path)
    problems = _verify(dec_path, cert_path)
    with open(os.path.join(OUT_DIR, "README-HOW-TO-TEST.md"), "w",
              encoding="utf-8") as fh:
        fh.write(README)
    if problems:
        print("REFUSING TO CLAIM THIS KIT IS CORRECT:")
        for p in problems:
            print("  -", p)
        raise SystemExit(1)
    print("wrote 2 PDFs + README to %s" % OUT_DIR)
    for p in (dec_path, cert_path):
        print("   ", os.path.basename(p))


if __name__ == "__main__":
    main()
