#!/usr/bin/env python
"""Grade LLM CALL 1 against the A125 kit - the missing metric.

    python3 backend/scripts/dump_a125_run.py <session_id> > a125_run.json
    python3 backend/scripts/score_a125_extraction.py a125_run.json

WHY THIS EXISTS
---------------
`score_gap_fill.py` grades call 2. `score_form_fill.py` grades the finished
PDF. NOTHING graded call 1, so every measurement of this pipeline has assumed
extraction works - including the 231/1/0 the deterministic harness reports,
which supplies the facts by hand.

That assumption is exactly where the 21 Sep defects lived. The SECOND named
insured's website was extracted correctly, stored correctly, and attached to
the WRONG COMPANY. On the form it looked like a clean fill.

WHAT IT REPORTS
---------------
  SCALARS        correct / wrong / missing, per fact
  ROWS           did each list fact find the right number of entities
  ENTITY-CELL    the number to steer by: of the cells that should carry a
                 value, how many carry the right value FOR THE ENTITY THEY ARE
                 ATTACHED TO. Rows are matched by NAME, never by position, so a
                 correct table in a different order scores 100% and a table
                 whose columns were mixed does not.
  CROSS-ENTITY   cells holding a DIFFERENT entity's value. THE defect this kit
                 was built to catch, counted rather than described.

It also runs `services.fact_relationships`, which needs no key at all, so you
can see what that WOULD have caught on this package.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "scripts"))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

import _a125_data as D                                      # noqa: E402
from services.fact_relationships import (                   # noqa: E402
    check_fact_relationships, _org_tokens,
)


def _norm(v) -> str:
    if v is None:
        return ""
    s = str(v).strip().lower()
    s = s.replace("$", "").replace(",", "").replace("%", "")
    s = re.sub(r"\s+", " ", s)
    if re.fullmatch(r"[\d\-() .]+", s) and any(c.isdigit() for c in s):
        d = re.sub(r"\D", "", s)
        return d.lstrip("0") or "0"
    return re.sub(r"[^a-z0-9@./ ]+", "", s).strip()


def _unwrap(v):
    return v.get("value") if isinstance(v, dict) and "value" in v else v


# ── What the kit's document states, as FACTS ────────────────────────────────
def expected_facts() -> dict:
    I, L, C, IT = D.INSUREDS, D.LOCATIONS, D.CONTACTS, D.INTERESTS
    topic = {"AAI": "subsidiary_of_another", "AAJ": "has_subsidiaries",
             "KAA": "formal_safety_program", "ABC": "flammables_explosives_chemicals",
             "AAH": "other_insurance_with_carrier",
             "AAC": "coverage_declined_cancelled_nonrenewed",
             "AAD": "abuse_molestation_discrimination_claims",
             "KAB": "fraud_arson_conviction",
             "AAF": "uncorrected_fire_safety_violations",
             "KAK": "foreclosure_repossession_bankruptcy", "KAL": "judgement_or_lien",
             "ABB": "business_in_trust", "KAC": "foreign_operations",
             "KAM": "other_business_ventures", "KAN": "owns_leases_operates_drones",
             "KAO": "hires_drone_operators"}
    return {
        "_scalars": {
            "applicant_name": I[0]["name"], "fein": I[0]["fein"],
            "sic_code": I[0]["sic"], "naics_code": I[0]["naics"],
            "entity_type": I[0]["entity"], "business_start_date": I[0]["start"],
            "effective_date": D.PROPOSED_EFF, "expiration_date": D.PROPOSED_EXP,
            "operations_description": D.PRIMARY_OPERATIONS,
            "other_named_insured_operations": D.OTHER_INSURED_OPERATIONS,
            "audit_period": D.AUDIT_PERIOD,
        },
        "_lists": {
            "additional_named_insureds": {
                "expected": [{"name": i["name"]} for i in I[1:3]],
                "key": "name", "columns": ("name",)},
            "named_insured_details": {
                "expected": [{"name": i["name"], "fein": i["fein"], "sic": i["sic"],
                              "naics": i["naics"], "phone": i["phone"],
                              "website": i.get("web") or "", "city": i["city"],
                              "state": i["state"], "postal_code": i["zip"],
                              "entity_type": i.get("entity") or ""} for i in I[1:3]],
                "key": "name",
                "columns": ("fein", "sic", "naics", "phone", "website", "city",
                            "state", "postal_code", "entity_type")},
            "applicant_contacts": {
                "expected": [{"name": c["name"], "contact_type": c["type"],
                              "phone": c["phone"], "email": c["email"] or ""}
                             for c in C],
                "key": "name", "columns": ("contact_type", "phone", "email")},
            "additional_interests": {
                "expected": [{"name": it["name"], "interest_type": it["interest"],
                              "lien_amount": it.get("loan") or "",
                              "reference_number": it.get("account") or "",
                              "phone": it.get("phone") or "",
                              "email": it.get("email") or "",
                              "item_description": it.get("item") or "",
                              "interest_reason": it.get("reason") or ""}
                             for it in IT],
                "key": "name",
                "columns": ("interest_type", "lien_amount", "reference_number",
                            "phone", "email", "item_description", "interest_reason")},
            # NOTE: city / state / zip are deliberately NOT graded. They are
            # not declared columns of `property_locations` - the `address`
            # string carries the whole address and the stamper parses it out.
            # Grading them counted 10 blanks that are correct by design and
            # made the premises table look half-extracted when it is not. A
            # grader's expectations are a fixture and get the same scrutiny as
            # the code.
            "property_locations": {
                "expected": [{"address": l["l1"], "county": l["county"] or "",
                              "full_time_employees": l["ft"],
                              "part_time_employees": l["pt"],
                              "annual_revenue": l["revenue"],
                              "occupied_area": l["occupied"],
                              "open_to_public_area": l["public"],
                              "total_building_area": l["total_area"]} for l in L],
                "key": "address",
                "columns": ("county", "full_time_employees", "part_time_employees",
                            "annual_revenue", "occupied_area",
                            "open_to_public_area", "total_building_area")},
            "organization_relationships": {
                "expected": [{"name": D.PARENT_ORG, "role": "parent",
                              "percent_owned": D.PARENT_PCT},
                             {"name": D.SUBSIDIARY_ORG, "role": "subsidiary",
                              "percent_owned": D.SUBSIDIARY_PCT}],
                "key": "name", "columns": ("role", "percent_owned")},
            "disclosure_answers": {
                "expected": [{"topic": topic[c], "answer": q["answer"]}
                             for c, q in D.QUESTIONS.items()
                             if c in topic and q.get("answer")],
                "key": "topic", "columns": ("answer",)},
        },
    }


def _match(exp_rows, got_rows, key):
    """Pair expected rows to extracted rows BY IDENTITY, never by position."""
    pairs, used = [], set()
    for e in exp_rows:
        want = _org_tokens(e.get(key)) or {_norm(e.get(key))}
        best, best_score = None, 0
        for j, g in enumerate(got_rows):
            if j in used:
                continue
            have = _org_tokens(g.get(key)) or {_norm(g.get(key))}
            score = len(want & have)
            if _norm(g.get(key)) == _norm(e.get(key)):
                score = 99
            if score > best_score:
                best, best_score = j, score
        if best is not None and best_score > 0:
            used.add(best)
            pairs.append((e, got_rows[best]))
        else:
            pairs.append((e, None))
    extra = [g for j, g in enumerate(got_rows) if j not in used]
    return pairs, extra


def _selftest_blobs():
    """Two fixtures, so the harness can be trusted before it is believed.

    PERFECT is the kit's own facts. BROKEN holds THE SAME VALUES with row B's
    website on row A, two FEINs swapped and two contact phones swapped - the
    21 Sep defects, reproduced. A scalar metric cannot tell them apart; that is
    the demonstration."""
    e = expected_facts()
    perfect = dict(e["_scalars"])
    for k, spec in e["_lists"].items():
        perfect[k] = [dict(r) for r in spec["expected"]]
    perfect["additional_named_insureds"] = [r["name"] for r in
                                            perfect["additional_named_insureds"]]
    broken = json.loads(json.dumps(perfect))
    broken["applicant_website"] = D.INSUREDS[1].get("web") or ""
    if broken.get("named_insured_details"):
        broken["named_insured_details"][0]["website"] = ""
        b = broken["named_insured_details"]
        if len(b) > 1:
            b[0]["fein"], b[1]["fein"] = b[1]["fein"], b[0]["fein"]
    c = broken.get("applicant_contacts") or []
    if len(c) > 1:
        c[0]["phone"], c[1]["phone"] = c[1]["phone"], c[0]["phone"]
    return perfect, broken


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dump", nargs="?",
                    help="a125_run.json from dump_a125_run.py (or a bare facts json)")
    ap.add_argument("--selftest", action="store_true",
                    help="grade two built-in fixtures instead - proves the harness "
                         "separates a correct extraction from a mis-attributed one")
    a = ap.parse_args()
    if a.selftest:
        perfect, broken = _selftest_blobs()
        for label, f in (("PERFECT EXTRACTION", perfect),
                         ("SAME VALUES, WRONG ENTITIES", broken)):
            print("\n" + "#" * 74)
            print("#  " + label)
            print("#" * 74)
            _report(f, "")
        print("\nThe SCALAR line is identical in both runs. Only ENTITY-CELL and the")
        print("relationship checks can tell them apart.")
        return 0
    if not a.dump:
        ap.error("give a dump file, or --selftest")
    blob = json.loads(Path(a.dump).read_text())
    facts = blob.get("merged_facts", blob) or {}
    raw = blob.get("raw_text", "") or ""
    return _report(facts, raw)


def _report(facts: dict, raw: str) -> int:
    exp = expected_facts()

    print("=" * 74)
    print("LLM CALL 1 vs the A125 kit")
    print("=" * 74)

    ok = wrong = missing = 0
    print("\nSCALARS")
    for k, want in exp["_scalars"].items():
        got = _unwrap(facts.get(k))
        if not _norm(got):
            missing += 1
            print(f"  MISSING  {k:34} want={str(want)[:40]!r}")
        elif _norm(got) == _norm(want) or (
                len(_norm(want)) > 40 and _norm(want)[:40] in _norm(got)):
            ok += 1
        else:
            wrong += 1
            print(f"  WRONG    {k:34} want={str(want)[:34]!r} got={str(got)[:34]!r}")
    print(f"  -> {ok} correct / {wrong} wrong / {missing} missing")

    tot_cells = tot_ok = tot_cross = tot_blank = 0
    print("\nLISTS")
    print(f"  {'fact':30} {'rows':>9} {'cells':>7} {'right':>6} {'cross':>6} {'blank':>6}")
    for name, spec in exp["_lists"].items():
        got_rows = [r for r in (_unwrap(facts.get(name)) or [])
                    if isinstance(r, dict)] if isinstance(_unwrap(facts.get(name)), list) else []
        if isinstance(_unwrap(facts.get(name)), list) and not got_rows:
            got_rows = [{spec["key"]: v} for v in _unwrap(facts.get(name))
                        if not isinstance(v, dict)]
        pairs, extra = _match(spec["expected"], got_rows, spec["key"])
        found = sum(1 for _e, g in pairs if g is not None)
        cells = right = cross = blank = 0
        for e, g in pairs:
            for col in spec["columns"]:
                want = e.get(col)
                if not _norm(want):
                    continue
                cells += 1
                got = _norm((g or {}).get(col))
                if not got:
                    blank += 1
                elif got == _norm(want):
                    right += 1
                elif any(_norm(o.get(col)) == got for o in spec["expected"] if o is not e):
                    cross += 1
                    print(f"     CROSS-ENTITY  {name}[{_norm(e.get(spec['key']))[:22]}]"
                          f".{col} holds another entity's value: {got[:28]!r}")
        tot_cells += cells; tot_ok += right; tot_cross += cross; tot_blank += blank
        extra_note = f"  (+{len(extra)} unexpected)" if extra else ""
        print(f"  {name:30} {found}/{len(spec['expected']):<7} {cells:>7} {right:>6} "
              f"{cross:>6} {blank:>6}{extra_note}")

    pct = (100.0 * tot_ok / tot_cells) if tot_cells else 0.0
    print(f"\n  ENTITY-CELL  {tot_ok}/{tot_cells} = {pct:.1f}%"
          f"   cross-entity {tot_cross}   blank {tot_blank}")

    print("\nRELATIONSHIP CHECKS (no answer key - these run on any package)")
    findings = check_fact_relationships(facts, raw)
    if not findings:
        print("  clean")
    for f in findings:
        print(f"  [{f['severity']:5}] {f['code']:38} {f['message'][:88]}")

    print("\nHOW TO READ THIS")
    print("  ENTITY-CELL is the number to steer by. A high scalar score with a low")
    print("  entity-cell score means extraction is FINDING the values and attaching")
    print("  them to the wrong parties - which no form-level metric can see.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
