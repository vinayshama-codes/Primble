"""Dump a session's declarations index (`dec_page_entries`) to a JSON file.

WHY THIS EXISTS: the index is NOT a file. It is a fact on the session row in
Postgres (`processing_sessions.data -> facts -> dec_page_entries`), built fresh
by LLM call 1 on every upload, read by Stage A of LLM call 2, and PURGED once
forms are generated (`_PURGE_DEC_INDEX_AFTER_GENERATION`, improving-ll.md C57)
because it is a verbatim copy of the client's declarations pages and there is
no reason to retain PII past the job that needs it.

So there is nothing to open unless you look while a session is mid-flight -
after upload, BEFORE generating forms. This script is that look.

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
            async with get_pool().acquire() as conn:
                rows = await conn.fetch(
                    "SELECT id, created_at, "
                    "       jsonb_array_length("
                    "         COALESCE(data->'facts'->'dec_page_entries', '[]'::jsonb)"
                    "       ) AS entries "
                    "FROM processing_sessions ORDER BY created_at DESC LIMIT 15"
                )
            if not rows:
                print("No processing sessions found.")
                return 0
            print(f"{'SESSION ID':38} {'CREATED':22} ENTRIES")
            for r in rows:
                note = "" if r["entries"] else "   (empty - purged, or forms generated)"
                print(f"{str(r['id']):38} {str(r['created_at'])[:19]:22} "
                      f"{r['entries']}{note}")
            print("\nRe-run with a session id to dump its index.")
            return 0

        sid = sys.argv[1]
        session = await get_processing_session(sid)
        entries = (session.get("facts") or {}).get("dec_page_entries") or []
        if not entries:
            print(f"Session {sid} has no dec_page_entries.\n"
                  "Either forms were already generated (the index is purged at\n"
                  "that point by design - improving-ll.md C57), or extraction\n"
                  "recorded no declarations content. Dump a session that has\n"
                  "finished uploading but has NOT generated forms yet.")
            return 1

        out = os.path.abspath(f"dec_index_{sid}.json")
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(entries, fh, indent=2, ensure_ascii=False)

        by_section = Counter(e.get("section") or "(no section)" for e in entries)
        by_owner = Counter(e.get("owner") or "(none)" for e in entries)
        print(f"Wrote {len(entries)} entries -> {out}\n")
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
