"""
score_form_fill.py - grade generated ACORD PDFs against a T1-style answer key.

    py backend/scripts/score_form_fill.py --key t1_test_data/T1_answer_key.json \
        --pdf-dir <folder holding the generated ACORD PDFs>

    # exact owned-blank census (recommended): dump the session facts first
    py backend/scripts/dump_session_facts.py <session_id> > facts.json
    py backend/scripts/score_form_fill.py --key ... --pdf-dir ... --facts facts.json

WHY NOT `score_gap_fill.py`
--------------------------
That harness drives `combined_gap_fill` in-process and reports
correct/wrong/missed. It is the right tool for A/B-ing a prompt knob. It cannot
see three things this one has to:

  * a value stamped where the document said nothing (it has no must-be-blank
    concept, so a fabricated grid scores as "unjudged");
  * whether a table row is INTERNALLY consistent - whose truck the cells in
    row B actually describe;
  * whether a blank is a defect or a deliberate owned blank.

And it measures the gap-fill stage, not the artefact. This one reads the PDF a
broker would receive, so Pass 1, Pass 1.5, the evidence gate, every post-fill
guard and the stamper are all inside the measurement.

THE FIVE NUMBERS
----------------
    correct / wrong / missing / must-be-blank hit      the four buckets
    ROW-CELL                                           the one to steer by

ROW-CELL is the share of cells in a multi-row group that carry the right value
FOR THE ROW THEY ARE IN. A run that fills every cell of a four-row table with
values borrowed from four different entities scores 100% on fields and near
zero here. `cross-row` counts the cells that match a DIFFERENT row - that is
the defect, named and counted.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))

TRUEISH = {"y", "yes", "on", "x", "true", "1", "checked"}
FALSEISH = {"n", "no", "off", "false", "0"}


# ═════════════════════════════════════════════════════════════════════════════
# Normalisation - the contract, fixed before anything is scored
# ═════════════════════════════════════════════════════════════════════════════
# A unit the FORM's own printed label already states, so repeating it in the box
# is cosmetic, not a different value. ACORD labels the box "OCCUPIED AREA ... SQ FT"
# and the pipeline stamps "6,500 sq ft"; a broker reads those as the same number.
# Scoring them as WRONG buries real defects under formatting noise - on the first
# baseline this alone accounted for 8 of 18 "wrong".
_REDUNDANT_UNIT_RE = re.compile(
    r"\s*(?:sq\.?\s*ft\.?|square\s+feet|sqft|years?|yrs?|months?|mos?|days?|"
    r"per\s+claim|per\s+occurrence|each\s+occurrence)\s*$", re.I)


# Only these can make the EXPECTED side a yes/no question. "1", "x" and "on" are
# how a TICKED CHECKBOX reads out of the PDF - they are never how a key states an
# expectation. Keeping them out of this set is what stops a LOC # of "1" being
# compared as a boolean: `norm("1")` used to return "yes", so location 1 scored
# WRONG against an expected "001" while locations 2-4 scored correct.
_EXPECTED_BOOL = {"y", "yes", "n", "no", "true", "false"}


def _as_bool(s: str):
    """'yes' / 'no' / None - None meaning "this is not a boolean at all"."""
    if s in TRUEISH:
        return "yes"
    if s in FALSEISH:
        return "no"
    return None


def norm(value) -> str:
    s = str(value if value is not None else "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    if not s:
        return ""
    s = _REDUNDANT_UNIT_RE.sub("", s).strip() or s
    # a bare money / percent / count figure compares on its digits
    if re.fullmatch(r"[\$\s]*-?[\d,]+(\.\d+)?\s*%?", s):
        digits = re.sub(r"[^\d.]", "", s)
        if "." in digits:
            digits = digits.rstrip("0").rstrip(".")
        else:
            # Leading zeros are a PRINTING convention, not a value. ACORD's LOC #
            # box holds the same location whether the document typed "001" and the
            # pipeline derived "1". Applied only to whole numbers, so a decimal
            # rate ("0.902") keeps its leading zero and stays comparable.
            digits = digits.lstrip("0") or "0"
        return digits
    return s


def same(expected, actual) -> bool:
    # THE KEY DECIDES THE TYPE. When the expectation is a yes/no answer, compare
    # booleans - a ticked box reads as "1"/"x"/"on" and must still match "Yes".
    # When it is anything else, compare values, so a count or a location number
    # of "1" is a number and not a tick.
    e_raw = str(expected if expected is not None else "").strip().lower()
    if e_raw in _EXPECTED_BOOL:
        return _as_bool(str(actual if actual is not None else "").strip().lower()) \
            == _as_bool(e_raw)
    e, a = norm(expected), norm(actual)
    if not e or not a:
        return False
    if e == a:
        return True
    # ACORD boxes routinely carry a longer legal name than the key states.
    return len(e) >= 4 and len(a) >= 4 and (e in a or a in e)


def blank(value) -> bool:
    """An UNCHECKED checkbox is a blank, not an answer of "No".

    `/Off` is what pikepdf reads out of every checkbox nobody ticked, and it is
    indistinguishable from the field never having been touched. Reading it as a
    negative answer turns every untouched box on the form into a stamped "No" -
    which would score a missing Yes as WRONG and an untouched must-be-blank box
    as a VIOLATION. So this is tested on the RAW value, before `norm` folds
    "off" into the false-ish set for genuine Y/N text fields.
    """
    return str(value if value is not None else "").strip().lower() in ("", "off", "/off")


# ═════════════════════════════════════════════════════════════════════════════
# Reading a filled ACORD PDF
# ═════════════════════════════════════════════════════════════════════════════
def read_acroform(path: Path) -> Dict[str, str]:
    import pikepdf

    values: Dict[str, str] = {}

    def walk(node, inherited_name: str = ""):
        try:
            kids = node.get("/Kids")
        except Exception:                                     # noqa: BLE001
            kids = None
        name = str(node.get("/T")) if node.get("/T") is not None else ""
        full = f"{inherited_name}.{name}" if inherited_name and name else (name or inherited_name)
        if kids is not None:
            for k in kids:
                walk(k, full)
            return
        if not full:
            return
        v = node.get("/V")
        if v is None:
            values.setdefault(full.split(".")[-1], "")
            return
        s = str(v)
        if s.startswith("/"):
            s = s[1:]
        values[full.split(".")[-1]] = s

    with pikepdf.open(str(path)) as pdf:
        acro = pdf.Root.get("/AcroForm")
        if acro is None:
            return values
        for f in acro.get("/Fields", []):
            walk(f)
    return values


def locate_pdfs(pdf_dir: Path, forms: List[str]) -> Dict[str, Path]:
    found: Dict[str, Path] = {}
    files = list(pdf_dir.rglob("*.pdf"))
    for form in forms:
        digits = form.split("_")[-1]
        cands = [p for p in files
                 if re.search(rf"(^|[^0-9]){re.escape(digits)}([^0-9]|$)", p.name)]
        if cands:
            found[form] = sorted(cands, key=lambda p: -p.stat().st_mtime)[0]
    return found


# ═════════════════════════════════════════════════════════════════════════════
# Owned-blank census
# ═════════════════════════════════════════════════════════════════════════════
def owned_blank_probe(facts: dict):
    """Return fn(field) -> reason|None for boxes the pipeline OWNS as blanks.

    With no facts this is a STRUCTURAL census only: it sees the schedule
    registry and the resolvers that do not need facts to claim a field. Pass
    `--facts` for the exact answer - several resolvers (vehicle rating cells,
    declared-absent lines) can only decide with the session's own facts.
    """
    try:
        import services.pdf_service as ps
    except Exception as ex:                                   # noqa: BLE001
        print(f"  (owned-blank census unavailable: {ex})")
        return lambda _f: None

    def probe(field: str) -> Optional[str]:
        try:
            if ps._resolve_schedule_row(field, facts) is not ps._SCHED_SKIP:
                return "schedule-bound (gap fill is excluded by construction)"
        except Exception:                                     # noqa: BLE001
            pass
        for name in getattr(ps, "_AUTHORITATIVE_BLANK_RESOLVERS", ()):
            try:
                if ps.__dict__[name](field, facts) is not ps._SCHED_SKIP:
                    return f"owned by {name}"
            except Exception:                                 # noqa: BLE001
                continue
        return None

    return probe


# ═════════════════════════════════════════════════════════════════════════════
# Scoring
# ═════════════════════════════════════════════════════════════════════════════
def scope_matches(field: str, scope: str) -> bool:
    return fnmatch.fnmatch(field, scope)


def score_form(form: str, key: dict, stamped: Dict[str, str], probe) -> dict:
    exp = key["expect"].get(form, {})
    blanks = key["must_be_blank"].get(form, [])
    tally = Counter()
    details: Dict[str, List[tuple]] = defaultdict(list)

    for field, want in exp.items():
        got = stamped.get(field, "")
        if blank(got):
            reason = probe(field)
            if reason:
                tally["missing_owned"] += 1
                details["missing_owned"].append((field, want, reason))
            else:
                tally["missing"] += 1
                details["missing"].append((field, want, ""))
        elif same(want, got):
            tally["correct"] += 1
        else:
            tally["wrong"] += 1
            details["wrong"].append((field, want, got))

    for field in blanks:
        got = stamped.get(field, "")
        if not blank(got):
            tally["blank_violation"] += 1
            details["blank_violation"].append((field, "(must be blank)", got))

    # forbidden values, scoped to the fields they are forbidden in
    for scope, bad_values in (key.get("forbidden", {}).get(form, {})).items():
        for field, got in stamped.items():
            if blank(got) or not scope_matches(field, scope):
                continue
            for bad in bad_values:
                if same(bad, got):
                    tally["forbidden"] += 1
                    details["forbidden"].append((field, f"must not be {bad!r}", got))
                    break

    # shape rules - a code must match the shape of its own box
    for scope, rule in (key.get("shapes", {}).get(form, {})).items():
        rx = re.compile(rule["regex"])
        for field, got in stamped.items():
            if blank(got) or not scope_matches(field, scope):
                continue
            if not rx.match(str(got).strip()):
                tally["shape"] += 1
                details["shape"].append((field, rule["why"], got))

    # documented rows with no slot: they must appear nowhere in scope
    ea = key.get("expected_absent", {}).get(form)
    if ea:
        for field, got in stamped.items():
            if blank(got) or not any(scope_matches(field, s) for s in ea["scope"]):
                continue
            for v in ea["values"]:
                if same(v, got):
                    tally["overflow_leak"] += 1
                    details["overflow_leak"].append((field, "overflow row displaced a real one", got))
                    break

    return {"tally": tally, "details": details}


def score_rows(form: str, key: dict, stamped: Dict[str, str]) -> List[dict]:
    """The row-cell metric, per multi-row group."""
    out = []
    for group, spec in (key.get("row_sets", {}).get(form, {})).items():
        cols = spec["columns"]
        rows = spec["rows"]
        used, assigned = [], {}
        for slot in spec["slots"]:
            cells = {c: stamped.get(t.format(row=slot), "") for c, t in cols.items()}
            if all(blank(v) for v in cells.values()):
                continue
            used.append((slot, cells))

        # greedy identity assignment: the key row this slot agrees with most
        taken = set()
        for slot, cells in used:
            best, best_hits = None, 0
            for ri, kr in enumerate(rows):
                if ri in taken:
                    continue
                hits = sum(1 for c, v in cells.items()
                           if not blank(v) and c in kr and same(kr[c], v))
                if hits > best_hits:
                    best, best_hits = ri, hits
            if best is not None:
                taken.add(best)
            assigned[slot] = best

        cells_expected = cells_correct = cross_row = orphan = 0
        for slot, cells in used:
            ri = assigned.get(slot)
            kr = rows[ri] if ri is not None else None
            for c, v in cells.items():
                if kr is not None and c in kr and str(kr[c]).strip():
                    cells_expected += 1
                if blank(v):
                    continue
                if kr is not None and c in kr and same(kr[c], v):
                    cells_correct += 1
                elif any(same(other.get(c, ""), v) for j, other in enumerate(rows)
                         if j != ri and c in other):
                    cross_row += 1
                else:
                    orphan += 1

        out.append({
            "group": group, "slots": len(spec["slots"]), "rows_in_document": len(rows),
            "slots_used": len(used), "cells_expected": cells_expected,
            "cells_correct": cells_correct, "cross_row": cross_row, "orphan": orphan,
            "identified": sum(1 for s in assigned.values() if s is not None),
        })
    return out


# ═════════════════════════════════════════════════════════════════════════════
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", required=True)
    ap.add_argument("--pdf-dir", required=True,
                    help="folder containing the generated ACORD PDFs")
    ap.add_argument("--facts", help="session facts JSON, for an exact owned-blank census")
    ap.add_argument("--json-out")
    ap.add_argument("--max-detail", type=int, default=25)
    args = ap.parse_args()

    key = json.loads(Path(args.key).read_text(encoding="utf-8"))
    forms = key["_forms"]
    pdfs = locate_pdfs(Path(args.pdf_dir), forms)
    missing_pdfs = [f for f in forms if f not in pdfs]
    if missing_pdfs:
        print(f"no PDF found for: {', '.join(missing_pdfs)}")
        if not pdfs:
            return 2

    facts = json.loads(Path(args.facts).read_text(encoding="utf-8")) if args.facts else {}
    if isinstance(facts, dict) and "facts" in facts:
        facts = facts["facts"]
    probe = owned_blank_probe(facts)
    if not args.facts:
        print("  NOTE: no --facts given; the owned-blank census is structural only.\n")

    grand = Counter()
    report: dict = {"forms": {}, "rows": {}}
    for form in forms:
        if form not in pdfs:
            continue
        stamped = read_acroform(pdfs[form])
        res = score_form(form, key, stamped, probe)
        rows = score_rows(form, key, stamped)
        grand.update(res["tally"])
        report["forms"][form] = {k: v for k, v in res["tally"].items()}
        report["rows"][form] = rows

        t = res["tally"]
        judged = t["correct"] + t["wrong"]
        n_exp = len(key["expect"].get(form, {}))
        print("=" * 78)
        print(f"  {form}    ({pdfs[form].name})")
        print("-" * 78)
        print(f"  correct              {t['correct']:>4} / {n_exp}")
        print(f"  wrong                {t['wrong']:>4}   contradicts the document")
        print(f"  missing              {t['missing']:>4}   stated in the document, box blank")
        print(f"  missing (owned)      {t['missing_owned']:>4}   the pipeline refuses this box by design")
        print(f"  must-be-blank hit    {t['blank_violation']:>4} / {len(key['must_be_blank'].get(form, []))}"
              f"   asserts what the document never said")
        if t["forbidden"]:
            print(f"  forbidden value      {t['forbidden']:>4}   a value from the wrong role")
        if t["shape"]:
            print(f"  wrong shape          {t['shape']:>4}   e.g. a 6-digit code in the 4-digit box")
        if t["overflow_leak"]:
            print(f"  overflow leak        {t['overflow_leak']:>4}   an unslotted row displaced a real one")
        if judged:
            print(f"  PRECISION            {t['correct'] / judged:6.1%}   (correct / stamped-and-judged)")
        if n_exp:
            print(f"  RECALL               {t['correct'] / n_exp:6.1%}")

        if rows:
            print("-" * 78)
            print("  ROW-CELL (does the cell describe the row it sits in?)")
            for r in rows:
                pct = (r["cells_correct"] / r["cells_expected"]) if r["cells_expected"] else 0.0
                print(f"    {r['group']:<14} slots {r['slots_used']}/{r['slots']} used, "
                      f"{r['rows_in_document']} rows in the document")
                print(f"    {'':<14} cells {r['cells_correct']}/{r['cells_expected']} correct "
                      f"({pct:.0%})   cross-row {r['cross_row']}   ungrounded {r['orphan']}")

        for bucket, label in [("wrong", "WRONG"), ("blank_violation", "MUST BE BLANK"),
                              ("forbidden", "FORBIDDEN"), ("shape", "WRONG SHAPE"),
                              ("overflow_leak", "OVERFLOW LEAK"), ("missing", "MISSING")]:
            items = res["details"].get(bucket) or []
            if not items:
                continue
            print(f"\n  {label} ({len(items)})")
            for field, want, got in items[:args.max_detail]:
                print(f"    {field}")
                print(f"      expected {want!r}")
                if got:
                    print(f"      stamped  {got!r}")
            if len(items) > args.max_detail:
                print(f"    ... and {len(items) - args.max_detail} more")
        print()

    print("=" * 78)
    print("  PACKAGE TOTAL")
    tc, tw = grand["correct"], grand["wrong"]
    tm, tmo = grand["missing"], grand["missing_owned"]
    tb = grand["blank_violation"]
    total_exp = sum(len(key["expect"][f]) for f in forms if f in pdfs)
    print(f"    correct {tc}   wrong {tw}   missing {tm}   missing-owned {tmo}   "
          f"must-be-blank hit {tb}")
    if tc + tw:
        print(f"    PRECISION {tc / (tc + tw):.1%}    RECALL {tc / total_exp:.1%}"
              f"    (recall excludes owned blanks: {(tc) / max(1, total_exp - tmo):.1%})")
    ce = sum(r["cells_expected"] for f in report["rows"] for r in report["rows"][f])
    cc = sum(r["cells_correct"] for f in report["rows"] for r in report["rows"][f])
    cx = sum(r["cross_row"] for f in report["rows"] for r in report["rows"][f])
    if ce:
        print(f"    ROW-CELL  {cc}/{ce} ({cc / ce:.1%})   cross-row contamination {cx}")
    print("=" * 78)

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"  wrote {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
