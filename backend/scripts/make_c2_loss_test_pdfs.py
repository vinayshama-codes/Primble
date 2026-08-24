"""make_c2_loss_test_pdfs.py - the live test packages for V1 item C2 (Loss History).

Generates FIVE separate scenario packages (upload each scenario's files as its
OWN session - they are different companies on purpose, so extraction caches and
identity matching can never bleed between scenarios):

    py backend/scripts/make_c2_loss_test_pdfs.py

Writes to test_data_c2_loss/ at the repo root, plus README-HOW-TO-TEST.md with
the numbered checks. REGENERATE BEFORE EVERY RUN - valuation/period dates are
computed from today so the recency bands stay in-band whenever you test.

Scenario -> the one C2 behaviour it proves live
    S1  Path B strong pin: matched runs, NO readable dates  -> pillar 60 (was 45)
    S2  Path A 3-4yr = 85 + freq/ratio ADVISORY only         -> pillar 85 (was 50)
    S3  2.6 contradiction: "no known losses" vs real claims  -> capped 45 + DC row
    S4  Path C nothing = 25 + New Venture flow               -> 25 -> N/A (rescale)
    S5  Pending = 50 (was 70)                                -> pillar 50

Design notes (same rules as make_v1_c1_test_pdfs.py)
----------------------------------------------------
* Real text via reportlab - extractable by pdfplumber, no OCR dependency.
* Column x-positions far enough apart that characters never interleave (the
  2026-08-22 fixture-defect lesson).
* S1 prints NO date anywhere and no year-like token - Path B exists only while
  claim years are unextractable. Self-verified below with a date-regex scan.
* No scenario except S3 contains any _NO_LOSS_PHRASES wording - also
  self-verified, because one stray "no claims" would silently change the path.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

OUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "test_data_c2_loss",
)

TODAY = datetime.now()


def _d(days_ago: int) -> str:
    return (TODAY - timedelta(days=days_ago)).strftime("%m/%d/%Y")


def _future(days: int) -> str:
    return (TODAY + timedelta(days=days)).strftime("%m/%d/%Y")


# Proposed policy term shared by every scenario (starts just ahead of today so
# no expired-term / renewal-routing logic is tickled).
EFF = _future(8)
EXP = (TODAY + timedelta(days=8 + 365)).strftime("%m/%d/%Y")

# ── Layout helpers (proven in make_v1_c1_test_pdfs.py) ───────────────────────

def _page(c, title, subtitle=""):
    c.setFont("Helvetica-Bold", 15)
    c.drawString(1 * inch, 10.2 * inch, title)
    if subtitle:
        c.setFont("Helvetica", 9.5)
        c.drawString(1 * inch, 9.95 * inch, subtitle)
    c.setLineWidth(0.7)
    c.line(1 * inch, 9.82 * inch, 7.5 * inch, 9.82 * inch)
    return 9.5 * inch


def _row(c, y, label, value, lw=2.6):
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


def _dec_common(c, y, name, addr, fein, ops, revenue, payroll, employees,
                carrier, policy):
    y = _row(c, y, "Named Insured", name)
    y = _row(c, y, "Mailing Address", addr)
    y = _row(c, y, "FEIN", fein)
    y = _row(c, y, "Entity Type", "Limited Liability Company")
    y = _row(c, y, "Description of Operations", ops)
    y = _row(c, y, "Annual Gross Sales", revenue)
    y = _row(c, y, "Total Annual Payroll", payroll)
    y = _row(c, y, "Number of Employees", employees)
    y = _head(c, y, "COVERAGE - COMMERCIAL GENERAL LIABILITY")
    y = _row(c, y, "Carrier", carrier)
    y = _row(c, y, "Policy Number", policy)
    y = _row(c, y, "Policy Period", f"{EFF} to {EXP}")
    y = _row(c, y, "Each Occurrence Limit", "$1,000,000")
    y = _row(c, y, "General Aggregate Limit", "$2,000,000")
    return y


# ═════════════════════════════════════════════════════════════════════════════
# SCENARIO 1 - Cascade Plumbing: strong match, claim years NOT readable -> 60
# ═════════════════════════════════════════════════════════════════════════════
S1_NAME = "CASCADE PLUMBING SERVICES LLC"
S1_FEIN_DASHED = "45-3310886"
S1_FEIN_PLAIN = "453310886"          # loss run prints it unpunctuated (C1-proven)
S1_POL = "CPP-GLX-8842"              # letter-heavy: no year-like token anywhere
S1_CARRIER = "Granite State Mutual Insurance Company"


def s1_dec(path):
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "COMMERCIAL GENERAL LIABILITY DECLARATIONS",
              "Policy Declarations - New Business")
    _dec_common(c, y, S1_NAME, "2210 Alder Crossing, Tacoma, WA 98402",
                S1_FEIN_DASHED, "Residential and light commercial plumbing services",
                "$2,400,000", "$980,000", "11", S1_CARRIER, S1_POL)
    c.showPage()
    c.save()


def s1_loss_run(path):
    """The client's literal case: runs provably OURS (name + FEIN + policy),
    but every date is illegible - no valuation date, no period, no loss dates.
    Expected pillar: 60 PINNED (old system: 45 via the unknown-date -15)."""
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "LOSS RUN REPORT",
              f"Prepared by {S1_CARRIER}")
    y = _row(c, y, "Insured", S1_NAME)
    y = _row(c, y, "FEIN", S1_FEIN_PLAIN)
    y = _row(c, y, "Policy Number", S1_POL)
    y = _para(c, y - 0.05 * inch,
              "Loss dates in the source report are illegible; amounts and "
              "statuses transcribed only.")
    y = _head(c, y, "CLAIM DETAIL")
    c.setFont("Helvetica-Bold", 8.5)
    cols = [1.0, 2.4, 5.0, 5.9, 6.8]
    for x, h in zip(cols, ["CLAIM NUMBER", "DESCRIPTION", "PAID",
                           "RESERVED", "STATUS"]):
        c.drawString(x * inch, y, h)
    y -= 0.20 * inch
    c.setFont("Helvetica", 8)
    rows = [
        ("CLM-88412", "Water line failure at customer residence",
         "$6,240", "$0", "Closed"),
        ("CLM-90177", "Slip incident at supply warehouse",
         "$11,900", "$0", "Closed"),
    ]
    for r in rows:
        for x, v in zip(cols, r):
            c.drawString(x * inch, y, v)
        y -= 0.185 * inch
    y = _row(c, y - 0.1 * inch, "Total Incurred", "$18,140")
    y = _row(c, y, "Number of Claims", "2")
    c.showPage()
    c.save()


# ═════════════════════════════════════════════════════════════════════════════
# SCENARIO 2 - Bluewater Catering: 4 readable years -> 85; freq/ratio advisory
# ═════════════════════════════════════════════════════════════════════════════
S2_NAME = "BLUEWATER CATERING GROUP LLC"
S2_FEIN = "82-1147765"
S2_POL = "BWC-GLP-5521"
S2_CARRIER = "Lakeshore Standard Insurance Company"
S2_PRIOR = "Meridian Insurance Group"
S2_VAL = _d(10)                       # currently valued (<= 90 days)
S2_START = (TODAY - timedelta(days=10 + round(4 * 365.25))).strftime("%m/%d/%Y")


def s2_dec(path):
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "COMMERCIAL GENERAL LIABILITY DECLARATIONS",
              "Policy Declarations")
    y = _dec_common(c, y, S2_NAME, "515 Bayfront Avenue, Suite 3, Mobile, AL 36602",
                    S2_FEIN, "Off-premises catering and event food service",
                    "$1,000,000", "$620,000", "14", S2_CARRIER, S2_POL)
    y = _row(c, y, "Prior Carrier", S2_PRIOR)
    c.showPage()
    c.save()


def s2_loss_run(path):
    """4 readable years, currently valued, strong match, prior carrier named,
    HEAVY frequency (5 claims on $1M sales) and 15% loss ratio.
    Expected pillar: 85 EXACTLY - old system: 80 +10 carrier -25 freq -15 ratio = 50."""
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "LOSS RUN REPORT",
              f"Prepared by {S2_PRIOR} - Valuation Date {S2_VAL}")
    y = _row(c, y, "Insured", S2_NAME)
    y = _row(c, y, "FEIN", S2_FEIN)
    y = _row(c, y, "Policy Number", S2_POL)
    y = _row(c, y, "Prior Carrier", S2_PRIOR)
    y = _row(c, y, "Period Covered", f"{S2_START} to {S2_VAL}  (4 years)")
    y = _head(c, y, "CLAIM DETAIL")
    c.setFont("Helvetica-Bold", 8.5)
    cols = [1.0, 2.15, 3.35, 5.15, 6.05, 6.85]
    for x, h in zip(cols, ["DATE OF LOSS", "CLAIM NUMBER", "DESCRIPTION",
                           "PAID", "RESERVED", "STATUS"]):
        c.drawString(x * inch, y, h)
    y -= 0.20 * inch
    c.setFont("Helvetica", 8)
    rows = [
        (_d(160), "BW-2201", "Guest illness alleged at event", "$18,000", "$0", "Closed"),
        (_d(420), "BW-2140", "Serving table collapse injury", "$42,500", "$12,000", "Open"),
        (_d(700), "BW-2071", "Delivery van struck fixed object", "$9,800", "$0", "Closed"),
        (_d(980), "BW-1988", "Burn injury to staff member", "$31,200", "$0", "Closed"),
        (_d(1300), "BW-1902", "Slip and fall at venue entrance", "$36,500", "$0", "Closed"),
    ]
    for r in rows:
        for x, v in zip(cols, r):
            c.drawString(x * inch, y, v)
        y -= 0.185 * inch
    y = _row(c, y - 0.1 * inch, "Total Incurred", "$150,000")
    y = _row(c, y, "Number of Claims", "5")
    c.showPage()
    c.save()


# ═════════════════════════════════════════════════════════════════════════════
# SCENARIO 3 - Ironpeak Roofing: attestation vs real claims -> capped 45 + DC row
# ═════════════════════════════════════════════════════════════════════════════
S3_NAME = "IRONPEAK ROOFING LLC"
S3_FEIN = "47-9902213"
S3_POL = "IRP-GLR-3308"
S3_CARRIER = "Summit Ridge Insurance Company"
S3_VAL = _d(12)
S3_START = (TODAY - timedelta(days=12 + round(5 * 365.25))).strftime("%m/%d/%Y")


def s3_application(path):
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "COMMERCIAL INSURANCE APPLICATION",
              "Applicant Information Section")
    y = _dec_common(c, y, S3_NAME, "77 Quarry Bend Road, Boise, ID 83702",
                    S3_FEIN, "Commercial roofing installation and repair",
                    "$3,600,000", "$1,450,000", "16", S3_CARRIER, S3_POL)
    y = _row(c, y, "Prior Carrier", "Summit Ridge Insurance Company")
    y = _head(c, y, "APPLICANT STATEMENT")
    y = _para(c, y, "The applicant reports no known losses.")
    c.showPage()
    c.save()


def s3_loss_run(path):
    """The runs contradict the statement above: 5 clean years would score 100,
    the contradiction must CAP at 45 and raise a Data Consistency card."""
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "LOSS RUN REPORT",
              f"Prepared by {S3_CARRIER} - Valuation Date {S3_VAL}")
    y = _row(c, y, "Insured", S3_NAME)
    y = _row(c, y, "FEIN", S3_FEIN)
    y = _row(c, y, "Policy Number", S3_POL)
    y = _row(c, y, "Period Covered", f"{S3_START} to {S3_VAL}  (5 years)")
    y = _head(c, y, "CLAIM DETAIL")
    c.setFont("Helvetica-Bold", 8.5)
    cols = [1.0, 2.15, 3.35, 5.15, 6.05, 6.85]
    for x, h in zip(cols, ["DATE OF LOSS", "CLAIM NUMBER", "DESCRIPTION",
                           "PAID", "RESERVED", "STATUS"]):
        c.drawString(x * inch, y, h)
    y -= 0.20 * inch
    c.setFont("Helvetica", 8)
    rows = [
        (_d(430), "IR-7714", "Dropped material damaged parked vehicle",
         "$8,400", "$0", "Closed"),
        (_d(900), "IR-7583", "Water intrusion after re-roof",
         "$22,700", "$0", "Closed"),
    ]
    for r in rows:
        for x, v in zip(cols, r):
            c.drawString(x * inch, y, v)
        y -= 0.185 * inch
    y = _row(c, y - 0.1 * inch, "Total Incurred", "$31,100")
    y = _row(c, y, "Number of Claims", "2")
    c.showPage()
    c.save()


# ═════════════════════════════════════════════════════════════════════════════
# SCENARIO 4 - Nova Kitchen Studio: nothing provided -> 25 -> New Venture flow
# ═════════════════════════════════════════════════════════════════════════════
S4_NAME = "NOVA KITCHEN STUDIO LLC"
S4_FEIN = "88-4406119"
S4_POL = "NKS-GLN-1102"
S4_CARRIER = "Beacon Harbor Insurance Company"


def s4_application(path):
    """ZERO loss-history information, no prior carrier, explicitly new business.
    The words 'loss' and 'claim' must not appear anywhere in this document -
    self-verified below."""
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "COMMERCIAL INSURANCE APPLICATION",
              "Applicant Information Section - New Business Submission")
    y = _dec_common(c, y, S4_NAME, "940 Larkspur Lane, Unit B, Madison, WI 53703",
                    S4_FEIN, "Custom kitchen design studio and showroom",
                    "$450,000", "$210,000", "4", S4_CARRIER, S4_POL)
    y = _row(c, y, "Transaction Type", "New Business")
    y = _row(c, y, "Business Start Date", _d(60))
    c.showPage()
    c.save()


# ═════════════════════════════════════════════════════════════════════════════
# SCENARIO 5 - Harborline Electric: runs requested / pending -> 50 (was 70)
# ═════════════════════════════════════════════════════════════════════════════
S5_NAME = "HARBORLINE ELECTRIC LLC"
S5_FEIN = "61-2208843"
S5_POL = "HLE-GLE-7714"
S5_CARRIER = "Puget Crown Insurance Company"


def s5_dec(path):
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "COMMERCIAL GENERAL LIABILITY DECLARATIONS",
              "Policy Declarations")
    _dec_common(c, y, S5_NAME, "18 Ferry Slip Road, Bremerton, WA 98337",
                S5_FEIN, "Commercial electrical contracting",
                "$2,900,000", "$1,240,000", "13", S5_CARRIER, S5_POL)
    c.showPage()
    c.save()


def s5_cover_letter(path):
    c = canvas.Canvas(path, pagesize=LETTER)
    y = _page(c, "SUBMISSION COVER LETTER",
              "Broker transmittal - supporting documentation status")
    y = _row(c, y, "Applicant", S5_NAME)
    y = _row(c, y, "FEIN", S5_FEIN)
    y = _para(c, y - 0.05 * inch,
              "Loss runs have been requested from the prior carrier, Atlantic "
              "Casualty Company, and are pending receipt.")
    y = _para(c, y,
              "They will be forwarded to the underwriter as soon as they arrive.")
    c.showPage()
    c.save()


# ═════════════════════════════════════════════════════════════════════════════
# Self-verification - a fixture defect must fail HERE, not mid-live-run.
# ═════════════════════════════════════════════════════════════════════════════

_NO_LOSS_PHRASES = (
    "no prior losses", "no losses", "no prior claims", "no claims",
    "no known losses", "no known claims", "no reported losses",
    "no reported claims", "loss-free", "loss free", "claims-free",
    "claims free", "clean loss history", "favorable loss history",
    "clean loss record",
)
_DATE_RE = re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b")


def _pdf_text(path: str) -> str:
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages)


def _verify(files: dict) -> None:
    errs = []
    t1 = _pdf_text(files["1B_loss_run_no_dates.pdf"]).lower()
    if _DATE_RE.search(t1):
        errs.append(f"S1 loss run contains a date: {_DATE_RE.search(t1).group(0)!r} "
                    "- Path B needs claim years unreadable")
    for fname in files:
        txt = _pdf_text(files[fname]).lower()
        hits = [p for p in _NO_LOSS_PHRASES if p in txt]
        if fname.startswith("3A"):
            if not hits:
                errs.append("S3 application lost its no-loss assertion")
        elif hits:
            errs.append(f"{fname} accidentally contains a no-loss phrase {hits} "
                        "- this silently changes the scoring path")
    t4 = _pdf_text(files["4A_application_only.pdf"]).lower()
    for word in ("loss", "claim"):
        if word in t4:
            errs.append(f"S4 application mentions {word!r} - it must carry zero "
                        "loss-history signal")
    t1_full = _pdf_text(files["1B_loss_run_no_dates.pdf"])
    for token in ("CLAIM NUMBER", "Total Incurred"):
        if token.lower() not in t1_full.lower():
            errs.append(f"S1 loss run missing {token!r} - may not classify as loss_run")
    if "pending" not in _pdf_text(files["5B_cover_letter.pdf"]).lower():
        errs.append("S5 letter lost its pending wording")
    if errs:
        raise SystemExit("FIXTURE SELF-CHECK FAILED:\n  - " + "\n  - ".join(errs))
    print("Self-check PASSED (dates/phrases/classification signals verified).")


README = """# C2 Loss History - live test packages (regenerated {today})

Five SEPARATE packages. Upload each scenario's file(s) as its OWN new session,
select **ACORD 125 only**, generate, then read the results in the review screen:

* **Loss History pillar + state**: right sidebar -> "Total Package Score" ->
  expand -> the **Loss History** row (number) and the state label under it.
  Click the label for the provenance card. "Matched on: ..." renders there too.
* **Cards**: the recommendations list (loss cards name their action).
* **Data Consistency / issues**: the validation & issues area (S3 only).
* **Client questionnaire**: the "Send to Client" question list (S1, S4).

| # | Upload | Expect | Old system said |
|---|--------|--------|-----------------|
| S1 | 1A + 1B | Loss History **60**, state "Loss runs match insured", Matched on: name, fein, policy number. Card says pinned at 60 / confirm claim years. **NO prior-carrier card, NO valuation-date deduction.** ARQ does NOT ask "how many years of claims history can you provide" | 45 (unknown-date -15) |
| S2 | 2A + 2B | Loss History **85** exactly. TWO cards prefixed "Underwriting advisory (no score effect)" (frequency + loss ratio). State "Loss data reconciled" | 50 (80 +10 carrier -25 freq -15 ratio) |
| S3 | 3A + 3B | Loss History **45** (capped), state "Conflicting". A conflict card ("reconcile before submission") AND a Data Consistency advisory ("held at 45"). ARQ offers the explain-the-discrepancy question | 45 cap existed; the DC card is NEW |
| S4 | 4A only | Loss History **25**, state "No loss information provided". TWO cards: the attestation card AND "confirm New Venture status". **Then**: answer the New Venture card with `Yes` -> pillar shows **N/A**, package score recomputes (loss AND umbrella both N/A -> the remaining four pillars rescale), ARQ list drops prior-carrier / claim-count / years questions | No New Venture concept at all |
| S5 | 5A + 5B | Loss History **50**, state "Loss runs requested / pending" | 70 |

S4 second path (fresh session, optional): instead of New Venture, answer the
attestation card / client question "No - no claims or losses in the past 5
years" -> pillar 60. Then (third path, optional) answer "Yes - we have had
claims or losses" -> pillar 25 and the ARQ gains the NEW loss-run availability
select ("Have loss runs been requested, or are any available to upload?").

What to send back per scenario: the Loss History pillar number, the state label,
the Matched-on line (S1/S2/S3), and which cards you saw. Screenshots beat prose.

Caveats
* Regenerate before every run (dates are relative to today) - the standing
  stale-fixture rule.
* S1 depends on the model NOT inventing claim years; if S1 shows a state of
  "Loss data reconciled" the model hallucinated dates - send the extracted
  facts and we adjust the fixture, not the code.
"""


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    plan = (
        ("1A_dec_page.pdf", s1_dec),
        ("1B_loss_run_no_dates.pdf", s1_loss_run),
        ("2A_dec_page.pdf", s2_dec),
        ("2B_loss_run_4yr.pdf", s2_loss_run),
        ("3A_application_no_loss_statement.pdf", s3_application),
        ("3B_loss_run_with_claims.pdf", s3_loss_run),
        ("4A_application_only.pdf", s4_application),
        ("5A_dec_page.pdf", s5_dec),
        ("5B_cover_letter.pdf", s5_cover_letter),
    )
    files = {}
    for name, fn in plan:
        path = os.path.join(OUT_DIR, name)
        fn(path)
        files[name] = path
    with open(os.path.join(OUT_DIR, "README-HOW-TO-TEST.md"), "w",
              encoding="utf-8") as fh:
        fh.write(README.format(today=TODAY.strftime("%Y-%m-%d")))
    _verify(files)
    print(f"Wrote {len(files)} PDFs + README to {OUT_DIR}")
    for n in files:
        print(f"   {n:36s} {os.path.getsize(files[n]) / 1024:6.1f} KB")


if __name__ == "__main__":
    main()
