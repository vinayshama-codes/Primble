"""why_capped.py - name the thing holding a session's score down.

    py backend/scripts/why_capped.py <session_id>
    py backend/scripts/why_capped.py --list

WHY THIS EXISTS (2026-09-22). The client's report was "we cannot get the Orbin
package score over 85", and answering it took a day of reading code because the
product does not say. An SQS ceiling is 60 (any hard stop) or 85 (any warning),
and `_resolve_cap` records the exact sentence that bound it - but a 60 only
names itself on screen through `cap_hard_stops` and an 85 names itself nowhere
at all. Worse, a warning can be in `soft_stops` (so it CAPS) and draw no card:
Data Consistency rows are removed from the grouped view by UI-13 and excluded
from `counts.warnings`, so a package can honestly print "0 warnings" at 85.

This prints the ground truth for one session, re-derived from the stored facts
rather than read off whatever the last write happened to leave behind:

  1. STORED       - the score, the ceiling and the sentence that bound it
  2. LIVE STOPS   - what the engines emit from these facts RIGHT NOW
  3. CAN IT BE FIXED - each warning's resolution mode, and whether the fix
                    actually writes the fact the rule reads. `NO FIX` here is
                    the defect class that stranded legacy_gl_no_class_codes:
                    the card refuses, "Mark resolved" is work-tracking that
                    never touches a score, and a Dismiss credit is added to the
                    RAW score and clamped straight back under the same ceiling.
  4. HIDDEN       - in `soft_stops` (so it caps) but drawing no warning card
  5. VERDICT      - the ceiling, the sentence, and what would clear it

Read-only. No LLM, no writes, no document.
"""
import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")


def _h(t):
    print("\n" + "=" * 78 + f"\n{t}\n" + "=" * 78)


async def _list_recent(limit=15):
    from config.database import create_pool, get_pool
    await create_pool()
    async with get_pool().acquire() as con:
        rows = await con.fetch(
            "SELECT id, created_at, user_id FROM processing_sessions "
            "ORDER BY created_at DESC LIMIT $1", limit)
    print(f"{'session_id':40} {'created':26} user")
    print("-" * 80)
    for r in rows:
        print(f"{str(r['id']):40} {str(r['created_at']):26} {r['user_id']}")


async def _run(session_id: str):
    from config.database import create_pool
    from repositories.session_repository import get_processing_session
    from services.sqs_service import (
        evaluate_stops, HARD_STOP_CAP, SOFT_STOP_CAP, _resolve_cap,
    )
    from services.cross_form_validator import (
        run_cross_form_validation, split_cross_form_issues,
    )
    from services.issue_registry import (
        RESOLUTION_MAP, build_grouped_view, classify_legacy,
        _legacy_message_resolution,
    )

    await create_pool()
    s = await get_processing_session(session_id)
    facts = s.get("facts") or {}
    flags = s.get("flags") or {}
    pkg = s.get("package_sqs") or {}

    _h("1. STORED")
    print(f"  displayed score : {pkg.get('package_sqs_score')}")
    print(f"  raw (uncapped)  : {pkg.get('raw_sqs_score')}")
    print(f"  tier            : {pkg.get('tier')}")
    print(f"  cap_reason      : {pkg.get('cap_reason')}")
    print(f"  credits applied : {pkg.get('credits_applied')}")
    print(f"  stored hard/soft: {len(s.get('hard_stops') or [])} / "
          f"{len(s.get('soft_stops') or [])}")

    _h("2. LIVE STOPS (re-derived from the stored facts)")
    fh, fs = evaluate_stops(facts, flags)
    ids = set(s.get("selected_form_ids") or []) | set(
        (s.get("generated_forms") or {}).keys())
    cf = run_cross_form_validation(facts, flags, ids)
    ch, cs, adv = split_cross_form_issues(cf)
    hard = list(fh) + list(ch)
    soft = list(fs) + list(cs)
    print(f"  forms in scope  : {sorted(ids)}")
    print(f"  HARD ({len(hard)}):")
    for m in hard:
        print(f"    - {m}")
    print(f"  SOFT ({len(soft)}):")
    for m in soft:
        print(f"    - {m}")
    print(f"  advisory ({len(adv)}) - these do NOT cap:")
    for a in adv:
        print(f"    - {(a.get('message') if isinstance(a, dict) else a)}")

    _h("3. CAN IT BE FIXED?")
    dead = []
    for m in soft + hard:
        res, code = None, None
        for i in cf:
            if isinstance(i, dict) and i.get("message") and m.startswith(i["message"][:40]):
                code = i.get("code")
                res = i.get("resolution") or RESOLUTION_MAP.get(code) or {}
                break
        if res is None:
            code = classify_legacy(m, "soft_warning")[0]
            res = _legacy_message_resolution(m) or {}
        mode = res.get("mode") or "none"
        if res.get("add_forms"):
            label = "ADD FORM"
        elif mode == "none":
            dead.append((code, m))
            label = "NO FIX"
        else:
            label = mode.upper()
        detail = (res.get("facts") or res.get("schedule_key")
                  or res.get("add_forms") or res.get("note") or "")
        print(f"  [{label:9}] {code}")
        print(f"              {m[:88]}")
        if detail:
            print(f"              -> {json.dumps(detail)[:120]}")

    _h("4. HIDDEN - caps the score, draws no warning card")
    grouped = build_grouped_view(
        s.get("structured_issues") or [], hard, soft, cross_issues=cf)
    rendered = {
        (i.get("message") or "").strip()
        for sec in (list(grouped["hard_stops"])
                    + [c for t in grouped["warnings"].values() for c in t])
        for i in sec.get("items", [])
    }
    hidden = [m for m in soft
              if not any(m.strip() == r or m.strip().startswith(r)
                         or r.startswith(m.strip()) for r in rendered if r)]
    print(f"  warnings the screen counts : {grouped['counts']['warnings']}")
    print(f"  warnings actually capping  : {len(soft)}")
    if hidden:
        for m in hidden:
            print(f"    HIDDEN -> {m[:90]}")
        print("\n  These are in soft_stops (so they hold the 85) but render no")
        print("  warning card. Data Consistency rows are the usual cause - they")
        print("  are fixed in the picker, not from the Warnings list.")
    else:
        print("  none - every capping warning draws a card")

    _h("5. VERDICT")
    cap, reason = _resolve_cap(hard, soft)
    if cap is None:
        print("  No ceiling. The score is whatever the pillars earned.")
    else:
        which = "hard stop" if cap == HARD_STOP_CAP else "warning"
        print(f"  Ceiling {cap} - held by this {which}:")
        print(f"    \"{reason}\"")
        print(f"\n  {len(soft)} warning(s) and {len(hard)} hard stop(s) are open.")
        print(f"  EVERY one of them must stop firing before the score can pass {cap}.")
        print("  Dismissing does not count: a dismiss credit is added to the RAW")
        print("  score and then clamped back under this same ceiling.")
    if dead:
        print(f"\n  *** {len(dead)} of these offer the producer NO fix: ***")
        for code, m in dead:
            print(f"      {code}: {m[:70]}")
        print("      A rule that fires on an empty fact and offers no way to fill")
        print("      it is unsatisfiable - the ceiling is permanent. Check it")
        print("      against services/answer_routing.answer_mode(<fact>).")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("session_id", nargs="?")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.list or not a.session_id:
        asyncio.run(_list_recent())
    else:
        asyncio.run(_run(a.session_id))


if __name__ == "__main__":
    main()
