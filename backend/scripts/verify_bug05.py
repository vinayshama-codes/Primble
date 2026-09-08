"""verify_bug05.py - prove BUG-05 is closed, with no server and no upload.

    py backend/scripts/verify_bug05.py

BUG-05 as reported: the review / recommendation flow returns red errors during
normal remediation. One card answers "Network error. Please try again."; another
offers a direct-answer box and a Submit button, then rejects the action with
"This item can't be answered directly. Attach a supporting document or dismiss
it with a note."

Two independent defects, plus a third nobody reported that is worse than either.

  A  The producer-answer door raised UnboundLocalError on every fact except
     New Venture, and the 500 carried no CORS header, so `fetch` REJECTED and
     the catch block printed "Network error". Covered by verify_bug06.py.

  B  The card decided answerability with `!!rec.field` while the server decided
     it with `_canonical_key`. `rec_narrative_components` declared
     `acord101_remarks` - a legacy READ-only alias - so the box was drawn and
     the answer refused, on every package with a narrative gap.

  C  `rec_auto_vin_schedule` / `rec_wc_class_codes` name LIVE CAPTURE
     SCHEDULES. The card drew a one-line box; typing into it replaced the whole
     extracted table with that string and printed "Resolved". Silent data loss
     that looks like a success.

WHAT THIS SCRIPT DRIVES
-----------------------
The real per-form scorer across all 17 real ACORD schemas, the real routing door
(`services/answer_routing`) and the real write door
(`arq_service.apply_producer_answer_to_session`) against an in-memory session
repository. No Postgres, no LLM, no document, no browser.

Exit code 1 while any defect is present, 0 once every card is coherent - so this
is also the before/after check.
"""
from __future__ import annotations

import asyncio
import glob
import os
import sys

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

# A session repository that lives in memory. Patched BEFORE arq_service is
# imported, because the write door imports these two names locally at call time
# and would otherwise reach for Postgres.
import repositories.session_repository as _sr  # noqa: E402

_STORE: dict = {"facts": {}, "flags": {}, "generated_forms": {}}


async def _fake_get(_sid):
    return {k: (dict(v) if isinstance(v, dict) else v) for k, v in _STORE.items()}


async def _fake_upd(_sid, payload, delete_facts=None):
    for k, v in (payload or {}).items():
        _STORE[k] = v
    for k in (delete_facts or []):
        _STORE.get("facts", {}).pop(k, None)
    return True


_sr.get_processing_session = _fake_get
_sr.upd_processing_session = _fake_upd

from services import answer_routing as AR          # noqa: E402
from services import arq_service as A              # noqa: E402
from services import schedule_capture as SC        # noqa: E402
from services.arq_service import _canonical_key    # noqa: E402
from services.sqs_service import calculate_sqs     # noqa: E402

_FLAGS = {
    "has_auto_coverage": True, "has_workers_comp": True,
    "has_property_coverage": True, "has_umbrella": True,
    "has_gl_coverage": True, "has_inland_marine": True,
}


def _form_ids():
    return sorted(os.path.basename(p).replace("_schema.json", "")
                  for p in glob.glob(os.path.join(_BACKEND, "forms_schemas", "*_schema.json")))


def _harvest():
    """Every recommendation card the scorer can draw, on any client's data.

    Empty facts + every coverage flag on, so no checklist is skipped for want of
    an exposure and every gap is open.
    """
    ids = _form_ids()
    out = []
    for fid in ids:
        res = calculate_sqs({}, dict(_FLAGS), {}, {}, ids, [], [], 0, form_id=fid)
        for rec in res.get("recommendations") or []:
            if isinstance(rec, dict):
                out.append((fid, rec))
    return out


def _check_cards() -> int:
    print("=" * 78)
    print("EVERY RECOMMENDATION CARD, ALL 17 SCHEMAS")
    print("=" * 78)
    recs = _harvest()
    if len(recs) < 30:
        print(f"  harvest looks empty ({len(recs)}) - the probe proves nothing")
        return 1

    sched = set(getattr(SC, "SCHEDULE_DEFS", {}) or {})
    narr = AR._narrative_keys()
    seen: dict = {}
    broken: list = []

    for _fid, rec in recs:
        rid = rec.get("rec_id")
        if rid in seen:
            continue
        mode = rec.get("answer_mode")
        field = rec.get("field")
        seen[rid] = mode

        if mode not in AR.VALID_MODES:
            broken.append((rid, field, f"invalid mode {mode!r}"))
        elif mode == "field":
            if not _canonical_key(field):
                broken.append((rid, field, "typed box the server will REFUSE"))
            elif field in sched:
                broken.append((rid, field, "typed box over a LIVE SCHEDULE"))
        elif mode == "schedule":
            if rec.get("schedule_key") not in sched:
                broken.append((rid, field, "schedule mode with no live table"))
        elif mode == "narrative":
            if field not in narr:
                broken.append((rid, field, "narrative mode on a non-prose fact"))
        elif mode == "none":
            if not (rec.get("answer_note") or "").strip():
                broken.append((rid, field, "no input and no explanation"))

    tally: dict = {}
    for m in seen.values():
        tally[m] = tally.get(m, 0) + 1
    print(f"  distinct cards: {len(seen)}")
    for m in sorted(tally, key=str):
        print(f"    {str(m):10s} {tally[m]}")

    if broken:
        print()
        print("  BROKEN:")
        for rid, field, why in broken:
            print(f"    {str(rid):42s} {str(field):28s} {why}")
    return 1 if broken else 0


def _check_reported_cards() -> int:
    """The two cards from the screenshot, by name."""
    print()
    print("=" * 78)
    print("THE REPORTED CARDS")
    print("=" * 78)
    by_id = {r.get("rec_id"): r for _f, r in _harvest()}
    rc = 0

    narrative = by_id.get("rec_narrative_components")
    if not narrative:
        print("  rec_narrative_components not emitted - cannot verify"); rc = 1
    else:
        ok = (narrative.get("answer_mode") == "narrative"
              and narrative.get("field") == "additional_remarks_text"
              and bool(_canonical_key(narrative.get("field"))))
        print(f"  Narrative Quality  mode={narrative.get('answer_mode'):10s} "
              f"field={narrative.get('field')}  -> {'OK' if ok else 'STILL BROKEN'}")
        rc |= 0 if ok else 1

    for rid, key in (("rec_auto_vin_schedule", "auto_vin_schedule"),
                     ("rec_wc_class_codes", "wc_class_codes")):
        rec = by_id.get(rid)
        if not rec:
            print(f"  {rid} not emitted - cannot verify"); rc = 1
            continue
        ok = rec.get("answer_mode") == "schedule" and rec.get("schedule_key") == key
        print(f"  {rid:24s} mode={str(rec.get('answer_mode')):10s} "
              f"schedule={rec.get('schedule_key')}  -> {'OK' if ok else 'STILL TYPEABLE'}")
        rc |= 0 if ok else 1
    return rc


def _check_write_door() -> int:
    """The write door refuses a scalar over a table - and still writes ordinary
    facts. A guard that refuses everything would pass the first half and break
    the product."""
    print()
    print("=" * 78)
    print("THE WRITE DOOR")
    print("=" * 78)
    rc = 0

    async def _drive():
        nonlocal rc
        fleet = [{"vin": "4S4BRCGC9C3217772", "year": "2012", "make": "Subaru"}]

        _STORE["facts"] = {"auto_vin_schedule": list(fleet)}
        ok, _ = await A.apply_producer_answer_to_session("s", "auto_vin_schedule",
                                                        "2019 Ford Transit")
        kept = _STORE["facts"].get("auto_vin_schedule") == fleet
        print(f"  scalar over a populated fleet   applied={ok!s:5s} "
              f"rows kept={kept!s:5s} -> {'OK' if (not ok and kept) else 'DATA LOSS'}")
        rc |= 0 if (not ok and kept) else 1

        # An EMPTY row-shaped fact still takes a typed answer - that is how
        # those gaps have always been closed, and it must not regress.
        _STORE["facts"] = {}
        ok, _ = await A.apply_producer_answer_to_session(
            "s", "gl_class_codes_by_location", "91580 at 12 Alder St")
        print(f"  scalar into an EMPTY row fact   applied={ok!s:5s} "
              f"-> {'OK' if ok else 'REGRESSION'}")
        rc |= 0 if ok else 1

        # A list of plain STRINGS is not a table - the tier-1 lines-of-business
        # fix writes one and must keep working.
        _STORE["facts"] = {"lines_of_business": ["GL", "Auto"]}
        ok, _ = await A.apply_producer_answer_to_session(
            "s", "lines_of_business", "General Liability, Commercial Auto")
        print(f"  scalar over a STRING list       applied={ok!s:5s} "
              f"-> {'OK' if ok else 'REGRESSION'}")
        rc |= 0 if ok else 1

        # `auto_covered_symbols` is row-shaped but declares a reader for typed
        # text. Four cross-form resolutions depend on that.
        _STORE["facts"] = {"auto_covered_symbols": [{"coverage": "Liability", "symbols": [1]}]}
        ok, _ = await A.apply_producer_answer_to_session(
            "s", "auto_covered_symbols", "Liability 1, Comprehensive 7")
        print(f"  symbols (declared free text)    applied={ok!s:5s} "
              f"-> {'OK' if ok else 'REGRESSION'}")
        rc |= 0 if ok else 1

        # And the narrative door APPENDS rather than replacing.
        _STORE["facts"] = {}
        await A.append_producer_narrative("s", "Account overview: metal fabrication.")
        await A.append_producer_narrative("s", "WC payroll context: $2.1M across 3 states.")
        from services.fact_lineage import envelope_value
        text = str(envelope_value(_STORE["facts"].get("additional_remarks_text")) or "")
        both = ("Account overview" in text) and ("WC payroll context" in text)
        print(f"  narrative append keeps both     -> {'OK' if both else 'OVERWRITTEN'}")
        rc |= 0 if both else 1

    asyncio.run(_drive())
    return rc


def main() -> None:
    rc = _check_cards() | _check_reported_cards() | _check_write_door()
    print()
    print("=" * 78)
    print("VERDICT: BUG-05 CLOSED" if not rc else "VERDICT: BUG-05 STILL PRESENT")
    print("=" * 78)
    raise SystemExit(rc)


if __name__ == "__main__":
    main()
