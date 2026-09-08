"""
snapshot_deterministic_fill.py - a before/after safety net for the pre-LLM passes.

    py backend/scripts/snapshot_deterministic_fill.py --facts facts.json --out before.json
    ...make a change...
    py backend/scripts/snapshot_deterministic_fill.py --facts facts.json --out after.json
    py backend/scripts/snapshot_deterministic_fill.py --diff before.json after.json

WHY THIS EXISTS
---------------
Every fix in this area touches a predicate or a resolver that ALL 17 forms consult.
A change that fixes ACORD 131 can silently blank a box on ACORD 140, and no live
run of three forms would ever show it.

This drives the REAL `compute_form_gaps` over every schema with a real session's
facts and records, per field: the stamped value, and which of the three fates the
field met (filled / owned-blank / sent-to-gap-fill). No LLM is involved, so the
result is deterministic and any diff is attributable to the change under test.

Deliberately NOT a pass/fail test. It is a diff you READ: some movement is the
point of the change, and the tool's job is to make sure none of it is a surprise.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline-snapshot")

FILLED, OWNED_BLANK, TO_GPT = "filled", "owned_blank", "to_gpt"


def _schemas() -> Dict[str, dict]:
    out = {}
    for p in sorted((BACKEND / "forms_schemas").glob("ACORD_*_schema.json")):
        form_id = p.name.replace("_schema.json", "")
        raw = json.loads(p.read_text(encoding="utf-8"))
        out[form_id] = raw["fields"] if isinstance(raw, dict) and "fields" in raw else raw
    return out


def snapshot(facts: dict) -> dict:
    import services.pdf_service as ps

    result: Dict[str, dict] = {}
    for form_id, schema in _schemas().items():
        mapped, unmatched, _ = ps.compute_form_gaps(form_id, schema, dict(facts))
        rows = {}
        for field in schema:
            if field in unmatched:
                rows[field] = [TO_GPT, None]
            else:
                val = mapped.get(field)
                sval = None if val is None else str(val)
                rows[field] = ([FILLED, sval] if sval not in (None, "", "UNMATCHED")
                               else [OWNED_BLANK, None])
        result[form_id] = rows
    return result


def _counts(snap: dict) -> Dict[str, Dict[str, int]]:
    out = {}
    for form_id, rows in snap.items():
        c = {FILLED: 0, OWNED_BLANK: 0, TO_GPT: 0}
        for fate, _v in rows.values():
            c[fate] += 1
        out[form_id] = c
    return out


def diff(before: dict, after: dict, limit: int) -> int:
    moved_total = 0
    print(f"{'form':<14}{'filled':>18}{'owned blank':>18}{'to gap fill':>16}")
    print("-" * 68)
    cb, ca = _counts(before), _counts(after)
    for form_id in sorted(set(before) | set(after)):
        b, a = cb.get(form_id, {}), ca.get(form_id, {})
        def d(k):
            delta = a.get(k, 0) - b.get(k, 0)
            return f"{b.get(k,0)}->{a.get(k,0)} ({delta:+d})" if delta else f"{b.get(k,0)}"
        print(f"{form_id:<14}{d(FILLED):>18}{d(OWNED_BLANK):>18}{d(TO_GPT):>16}")

    print("\nPER-FIELD MOVEMENT")
    print("-" * 68)
    for form_id in sorted(set(before) | set(after)):
        rb, ra = before.get(form_id, {}), after.get(form_id, {})
        moved = []
        for field in sorted(set(rb) | set(ra)):
            fb, fa = rb.get(field), ra.get(field)
            if fb != fa:
                moved.append((field, fb, fa))
        if not moved:
            continue
        moved_total += len(moved)
        # A newly filled box is the point; a newly BLANK box is a regression
        # until proven otherwise, so it is listed first and flagged.
        lost = [m for m in moved if m[1] and m[1][0] == FILLED and (not m[2] or m[2][0] != FILLED)]
        gained = [m for m in moved if (not m[1] or m[1][0] != FILLED) and m[2] and m[2][0] == FILLED]
        other = [m for m in moved if m not in lost and m not in gained]
        print(f"\n  {form_id}: {len(moved)} field(s) moved "
              f"({len(gained)} newly filled, {len(lost)} LOST A VALUE, {len(other)} re-routed)")
        for tag, group in (("LOST", lost), ("GAINED", gained), ("ROUTE", other)):
            for field, fb, fa in group[:limit]:
                sb = f"{fb[0]}={fb[1]!r}" if fb else "absent"
                sa = f"{fa[0]}={fa[1]!r}" if fa else "absent"
                print(f"    [{tag}] {field}\n            {sb}  ->  {sa}")
            if len(group) > limit:
                print(f"    ... and {len(group)-limit} more {tag}")
    if not moved_total:
        print("  (no field changed fate or value)")
    return moved_total


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--facts", help="session facts JSON (from dump_session_facts.py)")
    ap.add_argument("--out")
    ap.add_argument("--diff", nargs=2, metavar=("BEFORE", "AFTER"))
    ap.add_argument("--limit", type=int, default=30)
    args = ap.parse_args()

    if args.diff:
        b = json.loads(Path(args.diff[0]).read_text(encoding="utf-8"))
        a = json.loads(Path(args.diff[1]).read_text(encoding="utf-8"))
        diff(b, a, args.limit)
        return 0

    if not (args.facts and args.out):
        print("need --facts and --out (or --diff BEFORE AFTER)")
        return 2
    raw = json.loads(Path(args.facts).read_text(encoding="utf-8"))
    facts = raw.get("merged_facts") or raw.get("facts") or raw
    snap = snapshot(facts)
    Path(args.out).write_text(json.dumps(snap, indent=0, sort_keys=True), encoding="utf-8")
    c = _counts(snap)
    tot = {k: sum(v[k] for v in c.values()) for k in (FILLED, OWNED_BLANK, TO_GPT)}
    print(f"  wrote {args.out}: {len(snap)} forms, "
          f"{sum(len(r) for r in snap.values())} fields "
          f"({tot[FILLED]} filled, {tot[OWNED_BLANK]} owned-blank, {tot[TO_GPT]} to gap fill)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
