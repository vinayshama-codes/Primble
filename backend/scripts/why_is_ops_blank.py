"""why_is_ops_blank.py - one command, one answer.

    py backend/scripts/why_is_ops_blank.py

Prints ONLY what is needed to explain why ACORD 125's "Description of
Operations" boxes ship blank on the NEWEST session. No arguments, no session id
to hunt for.

WHY THIS EXISTS. Five predictions about that blank were made from the CODE and
all five were wrong: the withhold list (empty), the value's length (both
lengths stamp), a three-field Guard 4 repro (cluster too small), the fact
envelope shape, and finally Guard 4's exact-match ownership - which WAS a real
defect and is fixed, but was still not the live cause.

That is `dump_session_facts.py`'s own lesson, earned twice: reason against a
real session's facts, never against the code.

Reads only. Touches nothing. Facts are encrypted at rest, so it loads through
`get_processing_session` - the same door `dump_session_facts.py` uses.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

OPS_KEYS = (
    "operations_description",
    "certificate_description_of_operations",
    "wc_description_of_operations",
    "account_description",
    "premises_description",
)

STAMP_FIELDS = (
    "CommercialPolicy_OperationsDescription_A",
    "BuildingOccupancy_OperationsDescription_A",
    "NamedInsured_BusinessDescription_A",
)


def _show(val):
    """The RAW envelope - `value_state` and `source` are half the answer."""
    if isinstance(val, dict):
        keep = {k: v for k, v in val.items()
                if k in ("value", "value_state", "evidence_state", "source",
                         "confidence")}
        return json.dumps(keep, ensure_ascii=False)[:300]
    return repr(val)[:300]


async def main() -> None:
    from config.database import create_pool, get_pool
    from repositories.session_repository import get_processing_session

    await create_pool()
    pool = get_pool()
    async with pool.acquire() as con:
        row = await con.fetchrow(
            "SELECT id, created_at FROM processing_sessions "
            "ORDER BY created_at DESC LIMIT 1")
    if not row:
        print("no sessions found")
        return

    sess = await get_processing_session(str(row["id"]))
    facts = sess.get("facts") or {}
    flags = sess.get("flags") or {}
    docs = sess.get("docs") or []

    print(f"SESSION {row['id']}   created {row['created_at']}   documents={len(docs)}")
    print("=" * 78)

    print()
    print("1. MERGED FACTS - the dict the stamper reads")
    for k in OPS_KEYS:
        mark = "  " if k in facts else "??"
        print(f"  {mark} {k:42} = {_show(facts.get(k))}")

    print()
    print("2. PER-DOCUMENT - what each file contributed")
    for d in docs:
        if not isinstance(d, dict):
            continue
        df = d.get("facts") or {}
        print(f"  {d.get('filename')}  [doc_type={d.get('doc_type')}]")
        hit = False
        for k in OPS_KEYS:
            if k in df:
                hit = True
                print(f"      {k:38} = {_show(df.get(k))}")
        if not hit:
            print("      (states none of the operations facts)")

    print()
    print("3. PREMISES SCHEDULE - the other place operations can live")
    locs = facts.get("property_locations")
    if isinstance(locs, list) and locs:
        for i, loc in enumerate(locs):
            if isinstance(loc, dict):
                print(f"  row {i}: address={str(loc.get('address_line1'))[:38]!r} "
                      f"ops={_show(loc.get('operations_description'))}")
    else:
        print(f"  property_locations = {type(locs).__name__}: {str(locs)[:80]!r}")

    print()
    print("4. PACKAGE FLAGS that gate the Tier 1 checklist")
    for k in ("_only_dec_page", "_only_certificate", "is_certificate_doc",
              "has_certificate_request", "_doc_type"):
        print(f"  {k:26} = {flags.get(k)!r}")

    print()
    print("5. WITHHELD (_uw_conflicted_keys)")
    print(f"  {facts.get('_uw_conflicted_keys')!r}")

    print()
    print("6. WHAT THE STAMPER PRODUCES FROM THESE FACTS, RIGHT NOW")
    try:
        from services.pdf_service import _deterministic_map
        for f in STAMP_FIELDS:
            print(f"  {f:44} -> {str(_deterministic_map(f, facts))[:70]!r}")
    except Exception as exc:                                  # noqa: BLE001
        print(f"  could not run the stamper: {exc}")

    print()
    print("READ IT LIKE THIS")
    print("  section 1 empty  -> extraction/merge never produced the fact")
    print("  section 1 filled but section 6 None -> the stamping rule is the problem")
    print("  section 1 and 6 both filled -> a POST-FILL GUARD is blanking it")


if __name__ == "__main__":
    asyncio.run(main())
