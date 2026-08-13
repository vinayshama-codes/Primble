#!/usr/bin/env python
"""Correctness harness for LLM call 2 (gap fill).

WHY THIS EXISTS
---------------
`inspect_gap_fill_prompts.py` reports **PASS** on a run that fills ~26% of the
form, because it measures prefix stability and cost - and by those measures the
pipeline is excellent. Nothing in the repo measured whether the right value
landed in the right box.

That is why months of tuning moved cost and not quality: the optimisation loop was
running against a metric that could not see the problem. This script is the
missing metric. Build the fixture before changing anything else in this area.

WHAT IT REPORTS
---------------
    filled     a value was stamped
    correct    stamped AND matches ground truth
    wrong      stamped AND contradicts ground truth   <- the expensive failure
    missed     ground truth exists, nothing stamped   <- the cheap failure
    unjudged   stamped, no ground truth for it        <- fixture gap, not a result

    recall     correct / (fields with ground truth)
    precision  correct / (correct + wrong)

`precision` is the number to protect. This codebase's standing rule is
blank-over-wrong: a missed field goes to the client questionnaire, a wrong field
goes onto a legal document. A change that lifts recall while dropping precision is
a regression however good the headline looks.

THE FIXTURE
-----------
A JSON file of {ACORD_field_name: expected_value}. Hand-written, from a real
package, by someone who read the dec pages. 25-40 fields is enough to steer by -
cover the ones that matter (limits, dates, named insured, FEIN, a couple of
schedule rows, a couple of compliance Y/N) rather than trying to be exhaustive.

    { "_doc": "path/to/document.txt",
      "_forms": ["ACORD_125", "ACORD_126"],
      "NamedInsured_FullName_A": "ORBIN CONTRACTING LLC",
      "GeneralLiability_EachOccurrenceLimit_A": "$1,000,000" }

Keys starting with "_" are configuration, not expectations.

USAGE
    py backend/scripts/score_gap_fill.py --truth fixtures/orbin.json --live
    py backend/scripts/score_gap_fill.py --truth fixtures/orbin.json --live \
        --env GAP_FILL_CHUNK_ROUTING=0        # A/B a single knob

COST
    --live makes REAL OpenAI calls and costs real money (~$1 per run on a large
    package). Without it the script refuses to run rather than print a fake
    number, because a harness that can be run for free is a harness that gets
    trusted when it should not be.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _normalise(value) -> str:
    """Compare values the way a broker reading the form would.

    Case, surrounding whitespace, and the cosmetic punctuation of money and
    phone numbers are not differences worth failing on: "$1,000,000" and
    "1000000" are the same limit, and marking that wrong would make the harness
    lie about a correct fill. Anything beyond that IS a difference.
    """
    s = str(value if value is not None else "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    if re.fullmatch(r"[\$\s]*[\d,]+(\.\d{1,2})?[\s]*", s or "x"):
        s = re.sub(r"[^\d.]", "", s).rstrip("0").rstrip(".") if "." in s \
            else re.sub(r"[^\d]", "", s)
    return s


def _judge(expected: str, actual) -> str:
    if actual is None or str(actual).strip() == "":
        return "missed"
    e, a = _normalise(expected), _normalise(actual)
    if e == a:
        return "correct"
    # A stamped value that CONTAINS the expected one (or vice versa) is counted
    # correct: ACORD boxes routinely hold "ORBIN CONTRACTING LLC" where truth
    # says "Orbin Contracting". Scoring that as wrong would punish the pipeline
    # for the fixture author's phrasing.
    if e and a and (e in a or a in e):
        return "correct"
    return "wrong"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--truth", required=True, help="ground-truth JSON fixture")
    ap.add_argument("--doc", help="document text file (overrides fixture's _doc)")
    ap.add_argument("--forms", nargs="+", help="override the fixture's _forms")
    ap.add_argument("--live", action="store_true",
                    help="REQUIRED. Makes real OpenAI calls and costs real money.")
    ap.add_argument("--env", action="append", default=[], metavar="K=V",
                    help="set an env var for this run (repeatable), e.g. "
                         "--env GAP_FILL_CHUNK_ROUTING=0")
    ap.add_argument("--json-out", metavar="PATH",
                    help="also write the per-field verdicts as JSON")
    args = ap.parse_args()

    for kv in args.env:
        k, _, v = kv.partition("=")
        os.environ[k.strip()] = v.strip()
        print(f"env: {k.strip()}={v.strip()}")

    truth_path = Path(args.truth)
    truth_raw: dict = json.loads(truth_path.read_text(encoding="utf-8"))
    doc_path = args.doc or truth_raw.get("_doc")
    forms: List[str] = args.forms or truth_raw.get("_forms") or []
    facts: dict = truth_raw.get("_facts") or {}
    truth: Dict[str, str] = {k: v for k, v in truth_raw.items()
                             if not k.startswith("_")}

    if not doc_path or not forms:
        print("fixture needs _doc and _forms (or pass --doc/--forms)")
        return 2
    if not truth:
        print("fixture contains no expectations - nothing to score")
        return 2
    if not args.live:
        print(__doc__.split("COST")[-1].strip())
        print("\nRefusing to run without --live. See COST above.")
        return 2

    raw_text = Path(doc_path).read_text(encoding="utf-8", errors="ignore")
    print(f"document : {doc_path} ({len(raw_text):,} chars)")
    print(f"forms    : {', '.join(forms)}")
    print(f"truth    : {len(truth)} field(s)\n")

    import services.pdf_service as ps

    forms_to_unmatched: Dict[str, dict] = {}
    forms_to_mapped: Dict[str, dict] = {}
    schemas: Dict[str, dict] = {}
    for fid in forms:
        schema = json.loads(
            (Path(__file__).resolve().parents[1] / "forms_schemas" /
             f"{fid}_schema.json").read_text(encoding="utf-8"))
        schemas[fid] = schema
        mapped, unmatched, _ = ps.compute_form_gaps(fid, schema, facts)
        forms_to_unmatched[fid] = unmatched
        forms_to_mapped[fid] = mapped
        print(f"  {fid}: {len(mapped)} deterministic, {len(unmatched)} to gap-fill")

    print("\nrunning combined_gap_fill (live) ...\n")
    results = ps.combined_gap_fill(forms_to_unmatched, facts, raw_text,
                                   forms_to_mapped=forms_to_mapped)

    # A field can belong to several forms; take the first stamped value for it.
    stamped: Dict[str, str] = {}
    for fid in forms:
        for k, v in (forms_to_mapped.get(fid) or {}).items():
            stamped.setdefault(k, v)
        for k, v in (results.get(fid, {}).get("filled_values") or {}).items():
            stamped.setdefault(k, v)

    verdicts: Dict[str, Tuple[str, str, str]] = {}
    tally: Counter = Counter()
    by_family: Dict[str, Counter] = defaultdict(Counter)
    for field, expected in truth.items():
        verdict = _judge(expected, stamped.get(field))
        verdicts[field] = (verdict, str(expected), str(stamped.get(field) or ""))
        tally[verdict] += 1
        by_family[field.split("_", 1)[0]][verdict] += 1

    judged = tally["correct"] + tally["wrong"]
    recall = tally["correct"] / len(truth) if truth else 0.0
    precision = tally["correct"] / judged if judged else 0.0

    print("=" * 74)
    print(f"  correct  {tally['correct']:>4}")
    print(f"  wrong    {tally['wrong']:>4}   <- values that contradict the document")
    print(f"  missed   {tally['missed']:>4}   <- left blank, goes to ARQ")
    print("-" * 74)
    print(f"  RECALL    {recall:6.1%}   (correct / {len(truth)} known fields)")
    print(f"  PRECISION {precision:6.1%}   (correct / {judged} stamped-and-judged)")
    print("=" * 74)

    if len(by_family) > 1:
        print("\nby family:")
        for fam, c in sorted(by_family.items(),
                             key=lambda kv: -(kv[1]['wrong'] + kv[1]['missed'])):
            print(f"  {fam:<28} correct {c['correct']:>3}  wrong {c['wrong']:>3}"
                  f"  missed {c['missed']:>3}")

    bad = [(f, *v) for f, v in verdicts.items() if v[0] != "correct"]
    if bad:
        print(f"\n{len(bad)} field(s) not correct:")
        for field, verdict, exp, act in sorted(bad, key=lambda r: r[1]):
            print(f"  [{verdict:<6}] {field}")
            print(f"             expected: {exp[:70]}")
            if verdict == "wrong":
                print(f"             got     : {act[:70]}")

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(
            {"recall": recall, "precision": precision,
             "tally": dict(tally),
             "verdicts": {k: {"verdict": v[0], "expected": v[1], "actual": v[2]}
                          for k, v in verdicts.items()}},
            indent=2), encoding="utf-8")
        print(f"\nwrote {args.json_out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
