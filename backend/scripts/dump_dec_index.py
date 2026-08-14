"""Dump a session's declarations index (`dec_page_entries`) to a JSON file.

WHY THIS EXISTS: the index is NOT a file. It is a fact on the session row in
Postgres (`processing_sessions.data -> facts -> dec_page_entries`), built fresh
by LLM call 1 on every upload, read by Stage A of LLM call 2, and PURGED once
forms are generated (`_PURGE_DEC_INDEX_AFTER_GENERATION`, improving-ll.md C57)
because it is a verbatim copy of the client's declarations pages and there is
no reason to retain PII past the job that needs it.

So there is nothing to open unless you look while a session is mid-flight -
after upload, BEFORE generating forms. This script is that look.

FALLBACK (2026-08-14): the purge deletes only the SESSION-level copy. Each
uploaded document keeps its own raw `facts.dec_page_entries` (that is what
merge_facts reads), so when the session copy is gone this script rebuilds the
index from the per-doc copies and re-runs the SAME verification gate
(`_verify_dec_entries`) against each document's own text - the output is the
index as it was, not a guess. The dump says RECONSTRUCTED when this path ran.

    py backend/scripts/dump_dec_index.py                 # list live sessions
    py backend/scripts/dump_dec_index.py <session-id>    # dump one

Writes `dec_index_<session>.json` in the current directory and prints a
by-section summary. Read-only: it never writes to the database.

The output contains the applicant's real declarations data. Treat the file as
you would the uploaded policy - do not commit it.
"""
import asyncio
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def _main() -> int:
    from config.database import create_pool, get_pool, close_pool
    from repositories.session_repository import get_processing_session

    await create_pool()
    try:
        if len(sys.argv) < 2:
            # TWO traps found 2026-08-14, both about what a LISTING can afford:
            # 1. Counting the SESSION copy via raw SQL is impossible - session
            #    facts are ENCRYPTED at rest, so data->'facts'->... is NULL and
            #    every session printed "0 (purged)" whether purged or not,
            #    which sent a whole debugging session chasing a purge that had
            #    never fired.
            # 2. Counting it via get_processing_session (decrypts) is honest
            #    but loads megabytes per session - 15 of them blew a 120s
            #    timeout. A listing must stay cheap.
            # So the listing counts the PER-DOCUMENT raw copies, which are
            # plaintext jsonb and one aggregate away. That is the RECORDED
            # count, not the verified one - dump an id for the exact index.
            async with get_pool().acquire() as conn:
                rows = await conn.fetch(
                    "SELECT id, created_at, "
                    "  (SELECT COALESCE(SUM(jsonb_array_length("
                    "     CASE jsonb_typeof(doc->'facts'->'dec_page_entries') "
                    "       WHEN 'array' THEN doc->'facts'->'dec_page_entries' "
                    "       ELSE '[]'::jsonb END)), 0) "
                    "   FROM jsonb_array_elements("
                    "     CASE jsonb_typeof(data->'docs') WHEN 'array' "
                    "       THEN data->'docs' ELSE '[]'::jsonb END) AS doc"
                    "  ) AS doc_entries "
                    "FROM processing_sessions ORDER BY created_at DESC LIMIT 15"
                )
            if not rows:
                print("No processing sessions found.")
                return 0
            print(f"{'SESSION ID':38} {'CREATED':22} RAW ENTRIES (per-doc copies)")
            for r in rows:
                n = r["doc_entries"]
                note = "" if n else "   (none recorded - old session shape, or no dec content)"
                print(f"{str(r['id']):38} {str(r['created_at'])[:19]:22} {n}{note}")
            print("\nRe-run with a session id to dump its verified index "
                  "(the session copy, or a reconstruction if it was purged).")
            return 0

        sid = sys.argv[1]
        session = await get_processing_session(sid)
        entries = (session.get("facts") or {}).get("dec_page_entries") or []
        reconstructed = False
        if not entries:
            # Purged (or never merged). Rebuild from the per-document raw
            # copies, through the SAME gate the pipeline used.
            from services.extraction_service import _verify_dec_entries
            for doc in session.get("docs") or []:
                if not isinstance(doc, dict):
                    continue
                raw = (doc.get("facts") or {}).get("dec_page_entries")
                text = doc.get("text") or ""
                if isinstance(raw, list) and raw and text:
                    entries.extend(_verify_dec_entries(raw, text))
            reconstructed = bool(entries)
        if not entries:
            print(f"Session {sid} has no dec_page_entries.\n"
                  "The session copy is purged after generation when\n"
                  "PURGE_DEC_INDEX_AFTER_GENERATION is on (improving-ll.md C57)\n"
                  "and no per-document copy was recoverable either - so either\n"
                  "extraction recorded no declarations content, or this is an\n"
                  "old session shape. Dump a session that has finished\n"
                  "uploading but has NOT generated forms yet.")
            return 1

        out = os.path.abspath(f"dec_index_{sid}.json")
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(entries, fh, indent=2, ensure_ascii=False)

        by_section = Counter(e.get("section") or "(no section)" for e in entries)
        by_owner = Counter(e.get("owner") or "(none)" for e in entries)
        note = (" (RECONSTRUCTED from the per-document copies - the session "
                "copy was purged)" if reconstructed else "")
        print(f"Wrote {len(entries)} entries -> {out}{note}\n")
        print("BY SECTION (the C23 discriminator - which coverage part a figure "
              "belongs to):")
        for section, n in by_section.most_common():
            print(f"  {n:5}  {section}")
        print("\nBY OWNER:")
        for owner, n in by_owner.most_common():
            print(f"  {n:5}  {owner}")
        print("\nFIRST 5 ENTRIES:")
        for e in entries[:5]:
            print(f"  {e.get('label')!r} = {e.get('value')!r}"
                  f"   [{e.get('section') or '-'}]")
        return 0
    finally:
        await close_pool()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
