"""why_is_loss_conflicting.py - why does this session say "Conflicting"?

    py backend/scripts/why_is_loss_conflicting.py          # the last N sessions
    py backend/scripts/why_is_loss_conflicting.py 8        # the last 8

Prints, per session, EVERY input `_loss_history_conflict` reads and the door's
verdict at each step - so a "Conflicting - attested no losses but loss runs show
claims" on a package with no loss run can be traced to the exact fact that
produced it instead of guessed at.

WHY THIS EXISTS. The live run of 2026-09-05 showed that state on nine sessions
of nine, on documents containing no loss run. `claims_are_corroborated` was
added to gate it, and on the re-run W2 cleared while W1 / W3 / W4 did not - so
either the claim figure is not arriving as `source: "ai"`, or something else in
the corroboration set is answering True. Only the stored session row can say
which, and no screenshot shows it.

Read-only. Touches nothing.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

# Every fact the conflict path can read, in the order the door reads them.
CLAIM_FACTS = ("num_claims", "total_incurred", "loss_history",
               "loss_run_age_days", "loss_run_status", "loss_history_years",
               "open_claims_count", "total_paid")
ATTEST_FACTS = ("no_prior_losses", "loss_history_no_prior_losses_indicator")
ATTEST_FLAGS = ("no_prior_losses", "narrative_states_no_losses",
                "asserts_no_known_losses")


def _envelope(raw):
    """(value, source, confidence) whatever shape the fact is stored in."""
    if isinstance(raw, dict) and "value" in raw:
        return raw.get("value"), raw.get("source"), raw.get("confidence")
    return raw, None, None


def _short(value, limit=110):
    text = json.dumps(value, default=str) if isinstance(value, (list, dict)) else str(value)
    return text if len(text) <= limit else text[:limit] + " ..."


async def main() -> None:
    from config.database import create_pool, get_pool
    from repositories.session_repository import get_processing_session

    limit = 6
    if len(sys.argv) > 1:
        try:
            limit = max(1, int(sys.argv[1]))
        except ValueError:
            pass

    await create_pool()
    pool = get_pool()
    async with pool.acquire() as con:
        rows = await con.fetch(
            "SELECT id, created_at FROM processing_sessions "
            "ORDER BY created_at DESC LIMIT $1", limit)
    if not rows:
        print("no sessions found")
        return

    from services.sqs_service import _loss_history_conflict
    from services.loss_history_state import asserted_claims, claims_are_corroborated

    for row in rows:
        sess = await get_processing_session(str(row["id"]))
        facts = sess.get("facts") or {}
        flags = sess.get("flags") or {}
        docs = sess.get("docs") or []
        names = ", ".join(str(d.get("filename") or "?") for d in docs if isinstance(d, dict))
        doc_types = [str(d.get("doc_type") or "?") for d in docs if isinstance(d, dict)]
        has_loss_run = any(
            isinstance(d, dict) and d.get("doc_type") == "loss_run" and not d.get("excluded")
            for d in docs)

        print("=" * 78)
        print(f"SESSION {row['id']}  {row['created_at']}")
        print(f"  documents : {names or '(none)'}")
        print(f"  doc_types : {doc_types}   loss_run doc present = {has_loss_run}")

        print("  -- attestation (any True enters the conflict branch) --")
        for key in ATTEST_FLAGS:
            if key in flags:
                print(f"     flag  {key:38} = {_short(flags.get(key))}")
        for key in ATTEST_FACTS:
            if key in facts:
                value, source, conf = _envelope(facts.get(key))
                print(f"     fact  {key:38} = {_short(value)}   source={source} conf={conf}")

        print("  -- claim evidence (THE SUSPECT) --")
        for key in CLAIM_FACTS:
            if key not in facts:
                continue
            value, source, conf = _envelope(facts.get(key))
            flag = ""
            if key in ("num_claims", "total_incurred"):
                flag = ("   <-- MODEL-AUTHORED, gateable"
                        if str(source or "").strip().lower() == "ai"
                        else "   <-- NOT provably model-authored, gate leaves it alone")
            print(f"     {key:40} = {_short(value)}")
            print(f"     {'':40}   source={source} confidence={conf}{flag}")

        claims, incurred = asserted_claims(facts)
        corroborated = claims_are_corroborated(facts, has_loss_run)
        verdict = _loss_history_conflict(facts, flags, has_loss_run)
        print("  -- verdict --")
        print(f"     asserted_claims          = claims={claims} incurred={incurred}")
        print(f"     claims_are_corroborated  = {corroborated}")
        print(f"     _loss_history_conflict   = {verdict}")
        if verdict:
            print("     >>> THIS SESSION SHOWS 'Conflicting'. The line above says why:")
            print("         corroborated=True means one of - a loss_run document, a stated")
            print("         loss_run_age_days, a typed loss_history row, or a claim figure")
            print("         whose source is not 'ai'. The printout above names which.")
        print()


if __name__ == "__main__":
    asyncio.run(main())
