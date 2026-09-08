"""fuzz_sys04_safety.py - adversarial sweep over MESSY, realistic fact shapes.

    py backend/scripts/fuzz_sys04_safety.py [iterations]      # default 20000

WHY THIS EXISTS. Every SYS-04 test to date used PDFs I wrote myself: clean text
layer, layout I chose, extraction I could predict. Real submissions are scanned,
noisy, differently laid out, and 271 pages. This harness cannot run the
extraction model - but it CAN drive everything downstream of it against the
shapes a messy extraction actually produces: OCR-mangled line names, envelopes
instead of scalars, nulls where strings are expected, values in the wrong type,
missing keys, duplicated rows, whitespace, unicode.

THE TWO PROPERTIES THAT MUST HOLD. These are safety, not effectiveness - a
violation means we made something WRONG, not merely that we failed to improve
it.

  P1  NO FALSE SUPPRESSION. If a package carries ANY real Workers Comp
      evidence, the gate must never answer ABSENT and must never drop the WC
      narrative components. Dropping WC asks on a WC account is worse than the
      defect being fixed.
  P2  NO FALSE CONFLICT. A no-loss attestation must never be contradicted
      unless real, corroborated claim evidence exists.
  P3  NO FALSE ATTESTATION. The "Check if none" box must never print ticked
      unless a genuine attestation or a human's answer is on file.
  P4  TOTALITY. Nothing raises. The component map never grows. The verdict is
      always one of the three words.

AND ONE EFFECTIVENESS MEASURE, reported separately and NEVER asserted: on
packages with no WC evidence at all, how often does the gate actually fire?
A miss there leaves today's behaviour, which is safe but unfixed - the honest
number to quote, not a pass/fail.
"""
from __future__ import annotations

import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

from services.line_presence import line_in_submission, reconcile_line_flags  # noqa: E402
from services.sqs_service import (  # noqa: E402
    applicable_narrative_components, NARRATIVE_COMPONENT_LABELS,
    _calculate_narrative_quality, _loss_history_conflict,
)
from services.pdf_service import no_loss_attestation_verdict  # noqa: E402

# ── Messiness the real world produces ───────────────────────────────────────
# OCR mangles, punctuation, casing, abbreviation, spacing. Every one of these
# is a Workers Comp line name a real document might yield.
WC_NAMES = [
    "Workers Compensation", "Workers' Compensation", "WORKERS COMPENSATION",
    "Workers Comp", "Workers' Comp.", "WC", "Workmans Compensation",
    "Employers Liability", "EMPLOYERS' LIABILITY",
    "Workers Compensation and Employers Liability",
    "  Workers   Compensation  ", "Workers Compensat1on", "W0rkers Compensation",
    "WORKERS COMPENSATION AND EMPLOYERS' LIABILITY",
]
OTHER_NAMES = [
    "General Liability", "Commercial General Liability", "CGL",
    "Commercial Property", "Property", "Business Auto", "Automobile Liability",
    "Commercial Umbrella", "Umbrella Liab", "Excess Liability",
    "Inland Marine", "Crime", "Cyber Liability", "Professional Liability",
]
MONEY = [None, "", "0", "4200", "$4,200", "4,200.00", " 12000 ", "1,000,000",
         "No Coverage", "NO COVERAGE", "Not Covered", "Included", "Statutory",
         "N/A", "TBD", 4200, 0, 0.0]
POLICY = [None, "", "BX441201", "3K21-44-19", "CG 00 01 04 13", "  W99  ",
          "WC-9931", 12345, "N/A"]
SOURCES = [None, "ai", "producer", "client_arq", "user", "derived", "dec_entry", ""]
CONF = [None, "ai_high", "ai_low", "filled"]
WC_FACT_KEYS = ["wc_payroll", "wc_xmod", "wc_class_codes", "wc_officer_exclusions",
                "employers_liability_limits", "wc_payroll_period"]
FACT_VALUES = [None, "", "  ", "N/A", "n/a", "None", "none", "not applicable",
               "unknown", "TBD", "0", "0.94", "250000", "$250,000", 0, 1, True,
               False, [], {}, ["8810"], "no workers comp coverage"]


def envelope(rnd, value):
    """Sometimes a bare scalar, sometimes the envelope the pipeline writes."""
    shape = rnd.random()
    if shape < 0.35:
        return value
    env = {"value": value}
    if rnd.random() < 0.8:
        env["source"] = rnd.choice(SOURCES)
    if rnd.random() < 0.7:
        env["confidence"] = rnd.choice(CONF)
    return env


def coverage_row(rnd, wc: bool):
    row = {"line": rnd.choice(WC_NAMES if wc else OTHER_NAMES)}
    for key, pool in (("premium", MONEY), ("limit", MONEY),
                      ("policy_number", POLICY)):
        if rnd.random() < 0.72:
            row[key] = rnd.choice(pool)
    if rnd.random() < 0.15:
        row["carrier"] = rnd.choice(["Acme Mutual", None, ""])
    if rnd.random() < 0.05:
        return rnd.choice([None, "not a dict", 7, []])       # malformed row
    return row


def _grants(row) -> bool:
    """Does this row EVIDENCE a real policy? Mirrors the product's own door so
    the oracle is independent of the code being tested only in shape, not in
    definition - the harness asks pdf_service directly."""
    try:
        from services.pdf_service import _line_entry_evidences_policy
        return bool(isinstance(row, dict) and _line_entry_evidences_policy(row))
    except Exception:
        return False


def build(rnd):
    """One messy package, plus an INDEPENDENT record of whether it truly
    carries Workers Comp evidence."""
    facts, flags, form_ids = {}, {}, []
    lines = []
    n_other = rnd.randint(0, 6)
    for _ in range(n_other):
        lines.append(coverage_row(rnd, wc=False))

    wc_row_granted = False
    if rnd.random() < 0.45:
        row = coverage_row(rnd, wc=True)
        lines.append(row)
        wc_row_granted = _grants(row)

    if rnd.random() < 0.85:
        facts["coverage_lines"] = lines
    elif rnd.random() < 0.5:
        facts["coverage_lines"] = rnd.choice([None, "junk", 7, {}])

    for key in WC_FACT_KEYS:
        if rnd.random() < 0.22:
            facts[key] = envelope(rnd, rnd.choice(FACT_VALUES))

    if rnd.random() < 0.85:
        flags["has_workers_comp"] = rnd.choice(
            [True, False, None, 0, 1, "true", "false", "", "maybe"])
    if rnd.random() < 0.3:
        flags["narrative_states_no_losses"] = rnd.choice([True, False])
    if rnd.random() < 0.2:
        flags["no_prior_losses"] = rnd.choice([True, False])

    if rnd.random() < 0.18:
        form_ids = rnd.choice([["ACORD_130"], ["ACORD_125", "ACORD_130"],
                               ["acord_130"]])
    elif rnd.random() < 0.4:
        form_ids = rnd.choice([["ACORD_125"], ["ACORD_133"], [], None,
                               ["ACORD_125", "ACORD_140"]])

    if rnd.random() < 0.35:
        facts["num_claims"] = envelope(rnd, rnd.choice(
            [None, "0", "1", "3", 0, 3, "N/A", "", "10"]))
    if rnd.random() < 0.25:
        facts["total_incurred"] = envelope(rnd, rnd.choice(MONEY))
    if rnd.random() < 0.25:
        facts["loss_history"] = rnd.choice([
            [], None, "junk",
            [{"description": "no prior losses or claims in the last five years"}],
            [{"date": "03/12/2024", "description": "slip and fall", "paid": "8200"}],
            [{}, {"date": ""}],
        ])
    if rnd.random() < 0.2:
        facts["loss_history_no_prior_losses_indicator"] = envelope(
            rnd, rnd.choice(["Yes", "No", "", None, "Off", "N/A"]))
    if rnd.random() < 0.4:
        facts["account_description"] = rnd.choice([
            "ABC LLC operates as a retailer. General liability requested.",
            "Family owned since 1998. No prior losses. Safety program in place.",
            "", None, "   ",
        ])

    return facts, flags, form_ids, wc_evidence_present(facts, form_ids)


def wc_evidence_present(facts, form_ids) -> bool:
    """Does this package REALLY carry Workers Comp evidence?

    THE ORACLE, and it is computed from the FINAL facts only. The first version
    tracked it incrementally while building, which produced two classes of
    phantom failure and cost a whole run to find:

      * a granted WC row was built, then `coverage_lines` was dropped from the
        facts by a later coin-flip - the row no longer existed anywhere, and the
        oracle still said the package carried WC;
      * a fact's value state was read on the PARTIAL dict mid-build rather than
        on the finished one.

    An oracle that watches the generator instead of the artefact is not an
    independent oracle. Read the finished package, exactly as the product does.
    """
    stated = False
    try:
        from services.fact_state import value_state_of, PRESENT
        for key in WC_FACT_KEYS:
            if key in facts and value_state_of(facts, key) == PRESENT:
                stated = True
                break
    except Exception:                                          # noqa: BLE001
        pass

    granted = False
    rows = facts.get("coverage_lines")
    if isinstance(rows, list):
        try:
            from services.pdf_service import _entry_matches_line_strict
            phrases = ("workers compensation", "employers liability")
            for row in rows:
                if (isinstance(row, dict)
                        and _entry_matches_line_strict(str(row.get("line") or ""), phrases)
                        and _grants(row)):
                    granted = True
                    break
        except Exception:                                      # noqa: BLE001
            pass

    applied = False
    try:
        applied = any(str(f).strip().upper() == "ACORD_130"
                      for f in (form_ids or []) if f)
    except TypeError:
        applied = False

    return bool(stated or granted or applied)


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 20000
    rnd = random.Random(20260905)
    all_keys = set(NARRATIVE_COMPONENT_LABELS)

    p1 = p2 = p3 = p4 = 0
    examples = {"P1": [], "P2": [], "P3": []}
    no_wc_total = no_wc_fixed = 0
    verdicts = {"present": 0, "absent": 0, "unknown": 0}

    for _ in range(n):
        facts, flags, form_ids, wc_real = build(rnd)
        try:
            verdict = line_in_submission("workers_comp", facts, flags, form_ids)
            comps = applicable_narrative_components(facts, flags, form_ids)
            score, breakdown, _sub = _calculate_narrative_quality(
                facts, has_narrative_doc=True, flags=flags, form_ids=form_ids)
            conflict = _loss_history_conflict(facts, flags)
            box = no_loss_attestation_verdict({**facts, **flags})
            snapshot = dict(flags)
            reconcile_line_flags(snapshot, facts, form_ids)
        except Exception as ex:                                # noqa: BLE001
            p4 += 1
            examples.setdefault("P4", []).append((repr(ex)[:120], facts, flags))
            continue

        verdicts[verdict] = verdicts.get(verdict, 0) + 1

        # P4 - totality
        if (verdict not in verdicts or not isinstance(score, int)
                or not 0 <= score <= 100
                or not set(comps) <= all_keys
                or set(breakdown) != set(comps)):
            p4 += 1

        # P1 - never suppress WC on a package that really has it.
        # ORACLE CORRECTION (2026-09-05): the first version also flagged a flag
        # that was ALREADY False before reconciliation, which the gate never
        # touched - 1,082 phantom failures, none of them the product's. Only a
        # DEMOTION we performed counts.
        demoted = (flags.get("has_workers_comp") is not False
                   and snapshot.get("has_workers_comp") is False)
        if wc_real and (verdict == "absent" or not all_keys <= set(comps)
                        or demoted):
            p1 += 1
            if len(examples["P1"]) < 5:
                examples["P1"].append((verdict, sorted(set(all_keys) - set(comps)),
                                       facts, flags, form_ids))

        # P2 - a conflict needs corroborated claims
        if conflict:
            try:
                from services.loss_history_state import (
                    asserted_claims, claims_are_corroborated)
                claims, incurred = asserted_claims(facts)
                if not ((claims > 0 or incurred > 0)
                        and claims_are_corroborated(facts, False)):
                    p2 += 1
                    if len(examples["P2"]) < 5:
                        examples["P2"].append((facts, flags))
            except Exception:                                  # noqa: BLE001
                p2 += 1

        # P3 - the box never attests without a real attestation or a human
        if box == "Yes":
            # ORACLE CORRECTION (2026-09-05): the first version passed the RAW
            # envelope to `_attests_no_loss` while the code unwraps it with
            # `_fv` - 237 phantom failures, every one of them a genuine
            # attestation extracted from an uploaded ACORD form.
            from services.pdf_service import _attests_no_loss
            from services.sqs_service import _fv as _unwrap
            merged = {**facts, **flags}
            raw = merged.get("loss_history_no_prior_losses_indicator")
            human = (isinstance(raw, dict)
                     and str(raw.get("source") or "").lower()
                     in {"producer", "client_arq", "user", "human", "client"})
            genuine = (_attests_no_loss(_unwrap(merged, "loss_history_no_prior_losses_indicator"))
                       or _attests_no_loss(_unwrap(merged, "no_prior_losses")))
            if not (human or genuine):
                p3 += 1
                if len(examples["P3"]) < 5:
                    examples["P3"].append((facts, flags))

        # Effectiveness, reported not asserted
        if not wc_real:
            no_wc_total += 1
            if verdict == "absent":
                no_wc_fixed += 1

    print(f"iterations: {n:,}")
    print(f"verdict spread: {verdicts}")
    print()
    print("SAFETY - every one of these must be 0")
    print(f"  P1 false suppression (WC dropped on a real WC package) : {p1}")
    print(f"  P2 false loss conflict                                 : {p2}")
    print(f"  P3 false attestation printed on the form               : {p3}")
    print(f"  P4 crash / shape violation                             : {p4}")
    print()
    pct = (no_wc_fixed / no_wc_total * 100) if no_wc_total else 0.0
    print("EFFECTIVENESS - reported, never asserted")
    print(f"  packages with NO WC evidence   : {no_wc_total:,}")
    print(f"  ...where the WC asks were cut  : {no_wc_fixed:,}  ({pct:.1f}%)")
    print(f"  ...left as today's behaviour   : {no_wc_total - no_wc_fixed:,}"
          f"  ({100 - pct:.1f}%)  <- unfixed, never wrong")

    for key in ("P1", "P2", "P3", "P4"):
        for ex in examples.get(key, [])[:3]:
            print(f"\n  {key} EXAMPLE: {str(ex)[:400]}")

    return 1 if (p1 or p2 or p3 or p4) else 0


if __name__ == "__main__":
    sys.exit(main())
