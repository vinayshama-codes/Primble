"""verify_bug04_matrix.py - the whole BUG-04 edge-case matrix, offline.

    py backend/scripts/verify_bug04_matrix.py
    py backend/scripts/verify_bug04_matrix.py --sweep 20000

No upload, no session, no API cost, no LLM. It drives the REAL production
functions against the REAL ACORD 125 schema:

    pdf_service.apply_acord125_missing_field_highlights   which cells go yellow
    pdf_service.no_loss_attestation_verdict               how the box prints
    sqs_service.calculate_p4_loss_history                 the pillar score

WHY THIS EXISTS
---------------
The live test file (`make_bug04_test_pdf.py`) proves ONE thing: that the fix is
in the layer the screen reads. It cannot practically walk every loss-history
state - each one would be another upload, another session, another extraction.

This walks all of them in a second, so "test every edge case" and "one PDF" are
not a trade. Live run for the seam; this for the matrix.

WHAT IT CHECKS
--------------
Part 1  the exact states a real submission lands in, with the expected yellow
        count, box printing and pillar score written next to each.
Part 2  the three invariants, over randomly generated field states:
          I1  a ticked "Check if none" never requires a loss-row cell
          I2  a required loss row is always backed by a real claim CELL
          I3  the function never raises and never invents a field
Part 3  the derivation itself - which LossHistory fields the schema classes as
        table cells and which as section summaries. This is the fix.
Part 4  the classifier: a document DENYING it has loss runs is not a loss run,
        and ACORD 25 - which denies itself in boilerplate on every certificate
        ever issued - is still a certificate.

Exit code 0 = everything held. Non-zero = something to look at.
"""

from __future__ import annotations

import argparse
import os
import random
import string
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.pdf_service import (  # noqa: E402
    _ACORD125_LOSS_ROW_FIELDS,
    _all_form_schemas,
    _row_scoped_bases,
    apply_acord125_missing_field_highlights,
    no_loss_attestation_verdict,
)
from services.sqs_service import calculate_p4_loss_history  # noqa: E402

FORM = "ACORD_125"
TICK = "LossHistory_NoPriorLossesIndicator_A"
YEARS = "LossHistory_InformationYearCount_A"
TOTAL = "LossHistory_TotalAmount_A"
ROWS = ("A", "B", "C")
ROW_FIELDS = {t.format(row=r) for t in _ACORD125_LOSS_ROW_FIELDS for r in ROWS}

_GREEN, _RED, _DIM, _OFF = "\033[32m", "\033[31m", "\033[2m", "\033[0m"
if os.name == "nt" and not os.environ.get("WT_SESSION"):
    _GREEN = _RED = _DIM = _OFF = ""

_failures: list = []


def _ok(cond, label, detail=""):
    print(f"  {_GREEN + 'PASS' + _OFF if cond else _RED + 'FAIL' + _OFF}  {label}"
          + (f"   {_DIM}{detail}{_OFF}" if detail else ""))
    if not cond:
        _failures.append(label)
    return cond


def _blank_state():
    st = {f: "" for f in ROW_FIELDS}
    st.update({TICK: "", YEARS: "", TOTAL: ""})
    return st


def _yellow(state):
    conf = {k: "low_confidence" for k in state}
    out = apply_acord125_missing_field_highlights(FORM, {}, dict(state), conf)
    return {k for k, v in out.items() if v == "missing_required"}


def _real_loss_cells():
    """Every ROW-SCOPED LossHistory cell the real form prints - derived, so it
    also covers columns the highlighter does not manage."""
    bases = _row_scoped_bases(FORM)
    return {n for n in (_all_form_schemas().get(FORM) or {})
            if n.startswith("LossHistory_") and n.rsplit("_", 1)[0] in bases}


# ── Part 1 - the real-world states ───────────────────────────────────────────

def part1() -> None:
    print("\nPART 1  the states a real submission lands in")
    print("        (yellow = Required cells INSIDE the claim grid)\n")

    cases = [
        # label,                          field overrides,                    facts, flags,  yellow, box,   pillar
        ("silent on losses",              {},                                 {}, {},                 0, None, 25),
        ("narrative says no losses",      {},                                 {}, {"narrative_states_no_losses": True}, 0, None, 40),
        ("THE SCREENSHOT: narrative + 5y",{YEARS: "5"},                       {}, {"narrative_states_no_losses": True}, 0, None, 40),
        ("...and TOTAL LOSSES $0",        {YEARS: "5", TOTAL: "0"},           {}, {"narrative_states_no_losses": True}, 0, None, 40),
        ("producer TICKS the box",        {TICK: "Yes", YEARS: "5"},
         {"loss_history_no_prior_losses_indicator": {"value": "Yes", "source": "producer"}}, {},        0, "Yes", 60),
        ("producer UNTICKS it",           {TICK: "No", YEARS: "5"},
         {"loss_history_no_prior_losses_indicator": {"value": "No", "source": "producer"}}, {},         0, "No", 25),
        ("client ARQ: no claims in 5 yrs", {TICK: "Yes"},
         {"loss_history_no_prior_losses_indicator":
          {"value": "No - no claims or losses in the past 5 years", "source": "client_arq"}},
         {"no_prior_losses": True},                                                                     0, "Yes", 60),
        ("client ARQ: we have had claims", {TICK: "No"},
         {"loss_history_no_prior_losses_indicator":
          {"value": "Yes - we have had claims or losses", "source": "client_arq"}}, {},                 0, "No", 25),
        ("attestation from an uploaded ACORD", {TICK: "Yes"},
         {"loss_history_no_prior_losses_indicator": "Yes"}, {},                                         0, "Yes", 60),
        ("TOTAL LOSSES stated, no rows",  {TOTAL: "48500"},                   {}, {},                   0, None, 25),
        ("one real claim in row A",       {"LossHistory_OccurrenceDate_A": "03/14/2024"},
         {"num_claims": 1, "total_incurred": 12000}, {},                                                6, "No", None),
        ("real claim + producer ticks",   {"LossHistory_OccurrenceDate_A": "03/14/2024", TICK: "Yes"},
         {"loss_history_no_prior_losses_indicator": {"value": "Yes", "source": "producer"}}, {},        0, "Yes", 60),
        ("claims in rows A and B",        {"LossHistory_OccurrenceDate_A": "03/14/2024",
                                          "LossHistory_PaidAmount_B": "5000"},
         {"num_claims": 2, "total_incurred": 41900}, {},                                               12, "No", None),
    ]

    for label, over, facts, flags, want_yellow, want_box, want_pillar in cases:
        st = _blank_state()
        st.update(over)
        got_yellow = len(_yellow(st) & ROW_FIELDS)
        got_box = no_loss_attestation_verdict({**facts, **flags})
        got_pillar = None
        if want_pillar is not None:
            got_pillar, _ = calculate_p4_loss_history(dict(facts), dict(flags))
        good = got_yellow == want_yellow and got_box == want_box and (
            want_pillar is None or got_pillar == want_pillar)
        detail = (f"yellow={got_yellow} (want {want_yellow})  "
                  f"box={got_box or 'blank'} (want {want_box or 'blank'})")
        if want_pillar is not None:
            detail += f"  pillar={got_pillar} (want {want_pillar})"
        _ok(good, f"{label:<38}", detail)


# ── Part 2 - the invariants, over random shapes ──────────────────────────────

_JUNK = ["", "   ", None, "null", "None", "Off", "No", "N/A", "0", "0.00", "$0",
         "Yes", "yes", "TRUE", "see attached", "-", "unknown", "TBD", "03/14/2024",
         "5", "12500", "$1,200.00", 0, 1, True, False, 12.5, "éàü",
         "a" * 400, "\n\t", "<script>", "'; DROP TABLE"]


def part2(n: int) -> None:
    print(f"\nPART 2  the three invariants over {n:,} random field states\n")
    rng = random.Random(20260908)
    names = sorted(_all_form_schemas().get(FORM) or {})
    real_cells = _real_loss_cells()
    i1 = i2 = i3 = 0

    def _has_real_cell(st):
        return any(f in st and st[f] is not None and str(st[f]).strip() not in
                   ("", "null", "None", "Off", "No", "false", "0") for f in real_cells)

    for i in range(n):
        st = {}
        for nm in rng.sample(names, rng.randint(0, min(60, len(names)))):
            st[nm] = rng.choice(_JUNK)
        for _ in range(rng.randint(0, 5)):
            st["".join(rng.choice(string.ascii_letters + "_")
                       for _ in range(rng.randint(1, 20)))] = rng.choice(_JUNK)
        conf = {k: rng.choice(["filled", "low_confidence", "ai_high"])
                for k in st if rng.random() < 0.8}
        known = set(st) | set(conf)

        # I1 - a tick never requires a loss-row cell.
        ticked = dict(st)
        ticked[TICK] = rng.choice(["Yes", "yes", "Y", "true", "1", "on", "On"])
        try:
            if _yellow(ticked) & ROW_FIELDS:
                i1 += 1
        except Exception:                                          # noqa: BLE001
            i3 += 1

        # I2 - a required loss row is always backed by a real claim cell.
        plain = dict(st)
        plain.pop(TICK, None)
        try:
            if (_yellow(plain) & ROW_FIELDS) and not _has_real_cell(plain):
                i2 += 1
        except Exception:                                          # noqa: BLE001
            i3 += 1

        # I3 - total function, invents nothing.
        try:
            out = apply_acord125_missing_field_highlights(FORM, {}, dict(st), dict(conf))
            if not isinstance(out, dict) or not set(out) <= known:
                i3 += 1
        except Exception:                                          # noqa: BLE001
            i3 += 1

    _ok(i1 == 0, "I1  a ticked box never requires a loss-row cell", f"violations: {i1}")
    _ok(i2 == 0, "I2  a required loss row always has a real claim cell", f"violations: {i2}")
    _ok(i3 == 0, "I3  never raises, never invents a field", f"violations: {i3}")


# ── Part 3 - the derivation that IS the fix ──────────────────────────────────

def part3() -> None:
    print("\nPART 3  the derivation - what the schema says is a table cell\n")
    schema = _all_form_schemas().get(FORM) or {}
    bases = _row_scoped_bases(FORM)
    summaries, cells = [], []
    for n in sorted(schema):
        if not n.startswith("LossHistory_"):
            continue
        (cells if n.rsplit("_", 1)[0] in bases else summaries).append(n)

    print(f"  {_DIM}section summaries (a row letter, but no table){_OFF}")
    for n in summaries:
        print(f"    {n}")
    print(f"  {_DIM}table cells ({len(cells)}){_OFF}")
    print(f"    {', '.join(sorted({c.rsplit('_', 1)[0] for c in cells}))}")

    _ok(set(summaries) == {TICK, YEARS, TOTAL},
        "the three section boxes are classed as summaries",
        f"{len(summaries)} found")
    _ok(all(t.format(row='A').rsplit('_', 1)[0] in bases for t in _ACORD125_LOSS_ROW_FIELDS),
        "every managed claim column is classed as a table cell")
    _ok(len(bases) > 50, "the rule is derived from the whole form, not the loss section",
        f"{len(bases)} row-scoped bases across {len(schema)} fields")


# ── Part 4 - a denial is not evidence (the classifier) ───────────────────────

def part4() -> None:
    print("\nPART 4  a document denying it has something is not evidence that it does\n")
    from services.extraction_service import classify_document

    APP = ("ACORD 125 - COMMERCIAL INSURANCE APPLICATION. Application for Insurance. "
           "Named Insured: Test Company. FEIN 27-4244106. ")
    cases = [
        ("THE REPORTED CASE - app denying loss runs",
         APP + "LOSS HISTORY. Loss runs have not been attached to this submission.",
         "application"),
        ("ADVERSARIAL - ACORD 25 denies itself in print",
         "CERTIFICATE OF LIABILITY INSURANCE. THIS CERTIFICATE OF INSURANCE DOES NOT "
         "CONSTITUTE A CONTRACT BETWEEN THE ISSUING INSURER AND THE CERTIFICATE HOLDER. "
         "THIS IS TO CERTIFY that the policies listed below have been issued.",
         "certificate"),
        ("a genuine loss run WITH claims",
         "LOSS RUN. Claim number 88213. Date of loss 03/14/2024. Paid losses $12,000. "
         "Claimant: J Doe. No injuries reported on this claim.", "loss_run"),
        ("a genuine loss run for a CLEAN account",
         "LOSS RUN REPORT. Insured: Test Company. Date of loss: none. Paid losses: $0. "
         "No claims were reported during this period.", "loss_run"),
        ("'no loss runs on file' (determiner form)",
         APP + "There are no loss runs on file for this account.", "application"),
        ("an application ASKING for loss runs",
         APP + "Please provide loss runs for the past five years.", "application"),
        ("'Policy No. 12345' is a NUMBER, not a negation",
         "LOSS RUN. Policy No. 12345. Date of loss 01/02/2025. Claim number 77.",
         "loss_run"),
        ("dec page untouched",
         "POLICY DECLARATIONS. Declarations page. Policy period 01/01/2026 to "
         "01/01/2027. Named insured: X. Policy number BBC7263.", "dec_page"),
    ]
    for label, text, want in cases:
        got = classify_document(text)
        _ok(got.get("doc_type") == want, f"{label:<44}",
            f"{got.get('doc_type')} (want {want})")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sweep", type=int, default=6000,
                    help="random field states per invariant (default 6000)")
    args = ap.parse_args()

    print("=" * 78)
    print("BUG-04 matrix - real production code, real ACORD 125 schema, no upload")
    print("=" * 78)
    part1()
    part2(args.sweep)
    part3()
    part4()

    print("\n" + "=" * 78)
    if _failures:
        print(f"{_RED}{len(_failures)} FAILED{_OFF}")
        for f in _failures:
            print(f"  - {f.strip()}")
        return 1
    print(f"{_GREEN}ALL HELD{_OFF}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
