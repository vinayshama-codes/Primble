"""Rebuild a session's merged `facts` from the per-document copies it still holds.

WHY THIS EXISTS: on 2026-08-17 a live session lost its merged facts. An
undecryptable blob made `_decrypt_facts` substitute None, None is not a dict so
`upd_processing_session`'s additive merge was skipped, and a single ARQ answer
became the entire fact set - 71 facts down to 1, package SQS 81 -> 37. That write
path is fixed (see `resolve_facts_write`), but the sessions it already damaged
still need putting back.

Nothing is lost in that failure mode: every document keeps its OWN extracted
facts under `docs[i]["facts"]`, and only the merged copy is destroyed. This
script re-runs the SAME deterministic merge the extraction pipeline runs
(`select_primary_truth` + `merge_facts`) over those stored per-document facts.

DETERMINISTIC AND FREE. No OCR, no LLM call, no network beyond the database. It
deliberately does NOT re-run `_finalize_pipeline`: that stage can fire an
umbrella-period LLM probe and rewrites flags, and a restore must put back what
was there, not re-derive a new answer.

Usage (from backend/):
    py scripts/restore_session_facts.py <session_id>            # dry run
    py scripts/restore_session_facts.py <session_id> --apply    # write it
    py scripts/restore_session_facts.py --scan                  # find damaged sessions

The dry run prints exactly what would be written and changes nothing.
"""
import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

# A merged fact set this small on a session that has generated forms is the
# signature of the 2026-08-17 wipe, not of a genuinely sparse submission.
_WIPE_SUSPECT_FACT_KEYS = 5


def _unwrap(v):
    return v["value"] if isinstance(v, dict) and "value" in v else v


def _short(v, n=70):
    s = json.dumps(v, default=str) if isinstance(v, (dict, list)) else str(v)
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"


def rebuild_facts(docs: list) -> tuple:
    """(merged_facts, merged_flags, primary_filename) from stored per-doc facts."""
    from services.extraction_service import merge_facts, select_primary_truth

    active = [d for d in docs if isinstance(d, dict) and not d.get("excluded")]
    if not active:
        return {}, {}, None
    candidates = [d for d in active if not d.get("supporting_only")] or active
    primary = select_primary_truth(candidates)
    merged, mflags = merge_facts(active, primary)
    return merged, mflags, primary.get("filename")


async def _scan(limit: int = 500) -> None:
    """List sessions whose merged facts look wiped but whose documents survive."""
    from config.database import create_pool, get_pool

    await create_pool()
    async with get_pool().acquire() as con:
        rows = await con.fetch(
            """
            SELECT id, created_at, updated_at,
                   length(data->>'facts')                       AS facts_bytes,
                   length(data->'docs'->0->>'facts')            AS doc_facts_bytes,
                   jsonb_array_length(COALESCE(data->'docs','[]'::jsonb)) AS ndocs,
                   (SELECT count(*) FROM jsonb_object_keys(
                        COALESCE(data->'generated_forms','{}'::jsonb)))   AS nforms
            FROM processing_sessions
            ORDER BY created_at DESC
            LIMIT $1
            """,
            limit,
        )

    hits = [
        r for r in rows
        if (r["facts_bytes"] or 0) < 2000
        and (r["nforms"] or 0) > 0
        and (r["doc_facts_bytes"] or 0) > 2000
    ]
    print(f"scanned {len(rows)} session(s); {len(hits)} look damaged AND recoverable\n")
    for r in hits:
        print(f"  {r['id']}  created={str(r['created_at'])[:19]} "
              f"facts={r['facts_bytes']}B docs={r['ndocs']} "
              f"doc_facts={r['doc_facts_bytes']}B forms={r['nforms']}")
    if not hits:
        print("  nothing to restore.")


async def _restore(sid: str, apply: bool) -> int:
    from config.database import create_pool

    await create_pool()
    from repositories.session_repository import (
        get_processing_session, upd_processing_session,
    )

    session = await get_processing_session(sid)
    docs    = session.get("docs") or []
    current = session.get("facts")
    if isinstance(current, str):
        try:
            current = json.loads(current)
        except Exception:
            current = None

    if current is None:
        print("REFUSING: this session's facts blob could not be decrypted.\n"
              "  The ciphertext is preserved and still recoverable - restoring on\n"
              "  top of it would be guesswork. Fix FIELD_ENCRYPTION_KEY first.")
        return 2
    if not isinstance(current, dict):
        print(f"REFUSING: stored facts is {type(current).__name__}, not a dict.")
        return 2
    if not docs:
        print("REFUSING: this session has no documents to rebuild from.")
        return 2

    rebuilt, rflags, primary_name = rebuild_facts(docs)
    if not rebuilt:
        print("REFUSING: the documents carry no usable facts.")
        return 2

    print(f"session      : {sid}")
    print(f"documents    : {len(docs)} (primary: {primary_name})")
    print(f"facts now    : {len(current)} key(s)")
    print(f"facts rebuilt: {len(rebuilt)} key(s)")

    if len(rebuilt) <= len(current):
        print("\nNothing to restore - the rebuild is not larger than what is stored.")
        return 0

    restored = {k: v for k, v in rebuilt.items() if k not in current}
    kept     = {k: v for k, v in current.items() if k not in rebuilt}
    conflict = {
        k: (current[k], rebuilt[k])
        for k in current if k in rebuilt and current[k] != rebuilt[k]
    }

    print(f"\n  + {len(restored)} key(s) restored")
    for k in sorted(restored)[:25]:
        print(f"      {k:38s} = {_short(_unwrap(restored[k]))}")
    if len(restored) > 25:
        print(f"      … and {len(restored) - 25} more")

    if conflict:
        # The stored value WINS. A producer answer typed after the wipe is newer
        # than the extraction it is being merged back on top of, and silently
        # reverting someone's typed answer is the same class of surprise this
        # script exists to undo.
        print(f"\n  ! {len(conflict)} key(s) exist in BOTH - keeping the stored value:")
        for k, (cur, new) in list(conflict.items())[:10]:
            print(f"      {k:38s} stored={_short(_unwrap(cur), 34)} "
                  f"| rebuilt={_short(_unwrap(new), 34)}")
    if kept:
        print(f"\n  = {len(kept)} stored-only key(s) left untouched: {sorted(kept)[:8]}")

    # `dec_page_entries` is purged from the merged facts after generation when
    # PURGE_DEC_INDEX_AFTER_GENERATION is on (the default). Restoring it would
    # quietly undo that privacy decision, so honour the same flag here.
    purge_dec = os.getenv(
        "PURGE_DEC_INDEX_AFTER_GENERATION", "1").strip().lower() not in ("0", "false", "no")
    if purge_dec and "dec_page_entries" in restored:
        restored.pop("dec_page_entries")
        print("\n  - dec_page_entries NOT restored "
              "(PURGE_DEC_INDEX_AFTER_GENERATION is on)")
    elif "dec_page_entries" in restored:
        print("\n  * dec_page_entries IS restored "
              "(PURGE_DEC_INDEX_AFTER_GENERATION=0)")

    if not apply:
        print(f"\nDRY RUN - nothing written. Re-run with --apply to write "
              f"{len(restored)} key(s).")
        return 0

    # The additive merge in upd_processing_session keeps every stored key, so a
    # value typed after the wipe survives this write.
    await upd_processing_session(sid, {"facts": restored})

    verify = await get_processing_session(sid)
    after  = verify.get("facts") or {}
    print(f"\nAPPLIED. facts now: {len(after)} key(s) "
          f"(was {len(current)}, restored {len(restored)}).")
    if len(after) < len(current) + len(restored):
        print("  WARNING: fewer keys than expected - check the write path.")
        return 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("session_id", nargs="?", help="session to restore")
    ap.add_argument("--apply", action="store_true", help="write (default: dry run)")
    ap.add_argument("--scan", action="store_true", help="list damaged sessions")
    args = ap.parse_args()

    if args.scan:
        return asyncio.run(_scan()) or 0
    if not args.session_id:
        ap.error("give a session id, or --scan")
    return asyncio.run(_restore(args.session_id, args.apply))


if __name__ == "__main__":
    sys.exit(main())
