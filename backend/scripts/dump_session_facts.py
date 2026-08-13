"""Dump the extracted FACTS for a session, so a wrong or missing value on a
generated form can be traced to the layer that actually produced it.

WHY THIS EXISTS
---------------
Every "the form went blank" investigation so far has stalled at the same point.
A generated PDF shows only the OUTCOME; it cannot tell you whether a box is
empty because

    (a) extraction never produced the fact,          -> extraction problem
    (b) a resolver deliberately owns the box,        -> working as designed
    (c) a guard removed a value that WAS there.      -> stamping problem

Those three need completely different fixes, and guessing between them from a
PDF has cost several rounds. Verified on 2026-08-12: the producer contact name,
fax, program name and transaction status all stamp CORRECTLY when their facts
exist - so those blanks are (a), and no amount of work on the stamping layer
will move them.

USAGE
-----
    py backend/scripts/dump_session_facts.py                  # newest session
    py backend/scripts/dump_session_facts.py <session_id>
    py backend/scripts/dump_session_facts.py --keys producer,premium,naic

Reads through the repository layer, so field-level encryption is handled.
Output is TRUNCATED and FEIN/SSN/DOB are masked - it is safe to paste into a
chat. Nothing is written or modified.
"""
import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

# Facts most often implicated in a blank/wrong box on ACORD 125.
_INTERESTING = (
    "producer_name", "producer_contact_name", "producer_contact_phone",
    "producer_contact_email", "producer_fax", "producer_address",
    "carrier_name", "naic_code", "policy_number", "program_name", "program_code",
    "total_policy_premium", "coverage_lines", "lines_of_business",
    "auto_drivers", "auto_vin_schedule", "property_locations",
    "operations_description", "contractor_type", "is_contractor",
    "applicant_name", "fein", "entity_type", "num_employees",
)

_MASK = ("fein", "ssn", "dob", "tax", "social")
_MAX = 220


def _mask(key: str, value):
    if any(m in key.lower() for m in _MASK):
        s = str(value or "")
        return ("*" * max(0, len(s) - 4) + s[-4:]) if s else value
    return value


def _fmt(value) -> str:
    if isinstance(value, (dict, list)):
        try:
            out = json.dumps(value, ensure_ascii=False, default=str)
        except Exception:                                     # noqa: BLE001
            out = str(value)
    else:
        out = str(value)
    return out if len(out) <= _MAX else out[:_MAX] + f"... [{len(out)} chars]"


async def _newest_session_id():
    from config.database import get_pool
    pool = get_pool()
    async with pool.acquire() as con:
        row = await con.fetchrow(
            "SELECT id FROM processing_sessions ORDER BY created_at DESC LIMIT 1")
    return row["id"] if row else None


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("session_id", nargs="?")
    ap.add_argument("--keys", help="comma-separated substrings to filter on")
    ap.add_argument("--all", action="store_true", help="every fact, not just the usual suspects")
    args = ap.parse_args()

    # Stand up the same pool the app uses, so encryption and pooling behave
    # identically to a real run.
    from config.database import create_pool
    await create_pool()

    sid = args.session_id or await _newest_session_id()
    if not sid:
        print("no sessions found")
        return

    from repositories.session_repository import get_processing_session
    session = await get_processing_session(sid)
    if not session:
        print(f"session {sid} not found")
        return

    facts = session.get("facts") or {}
    flags = session.get("flags") or {}
    docs = session.get("docs") or []

    print(f"session   : {sid}")
    print(f"documents : {len(docs)}  "
          f"(excluded: {sum(1 for d in docs if isinstance(d, dict) and d.get('excluded'))})")
    print(f"facts     : {len(facts)}      flags: {len(flags)}")
    print("=" * 78)

    if args.keys:
        wanted = [k.strip().lower() for k in args.keys.split(",") if k.strip()]
        keys = [k for k in facts if any(w in k.lower() for w in wanted)]
    elif args.all:
        keys = sorted(facts)
    else:
        keys = [k for k in _INTERESTING if k in facts]
        missing = [k for k in _INTERESTING if k not in facts]
        if missing:
            print("NOT EXTRACTED AT ALL (this is why the box is blank):")
            for k in missing:
                print(f"   - {k}")
            print("-" * 78)

    for k in keys:
        v = facts.get(k)
        empty = v is None or (isinstance(v, (str, list, dict)) and not v)
        tag = "  <-- EMPTY" if empty else ""
        print(f"{k:28} = {_fmt(_mask(k, v))}{tag}")

    print("-" * 78)
    print("FLAGS that drive checkboxes:")
    for k in ("is_contractor", "has_general_liability", "has_commercial_auto",
              "has_umbrella", "has_inland_marine", "has_open_cargo",
              "has_crime", "has_cyber", "has_property_coverage"):
        if k in flags or k in facts:
            print(f"   {k:28} = {flags.get(k, facts.get(k))!r}")


if __name__ == "__main__":
    asyncio.run(main())
