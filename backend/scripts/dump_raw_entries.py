"""dump_raw_entries.py - the RAW per-document dec entries, exactly as the model
returned them, before `_verify_dec_entries` rebuilds them.

    py backend/scripts/dump_raw_entries.py <session_id>

Writes raw_entries_<session>.json and prints a summary.

WHY THIS EXISTS RATHER THAN A ONE-LINER. The merged index
(`scripts/dump_dec_index.py`) is the VERIFIED view: it keeps six named keys and
drops label-less entries, so it cannot tell you what the index prompt actually
produced. Judging the prompt needs the raw copy, and the obvious way to get it -
`dump_session_facts.py --json > run.json` piped into python - breaks on Windows
PowerShell, which writes `>` redirects as UTF-16 and hands python a 0xff BOM.
One script, no pipe, no encoding trap.

READING THE OUTPUT
    0 entries              the index pass produced nothing - check the backend
                           console for `dec_index_pass` warnings
    N entries, 6 keys      the main extraction recorded these, not the dedicated
                           pass (only possible if dec_page_entries was restored
                           to _EXTRACT_SCHEMA)
    N entries, 13 keys     the dedicated pass ran - this is the healthy shape

The file contains the applicant's real declarations data. Treat it like the
uploaded policy: do not commit it.
"""
import asyncio
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")


def _unwrap(v):
    return v.get("value") if isinstance(v, dict) and "value" in v else v


async def _main() -> int:
    from config.database import create_pool, close_pool
    from repositories.session_repository import get_processing_session

    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    sid = sys.argv[1]
    await create_pool()
    try:
        session = await get_processing_session(sid)
        if not session:
            print(f"No session {sid}")
            return 1

        docs = session.get("docs") or []
        all_entries = []
        print(f"\nSESSION {sid}   documents={len(docs)}\n" + "=" * 78)
        for i, doc in enumerate(docs):
            raw = _unwrap((doc.get("facts") or {}).get("dec_page_entries"))
            raw = raw if isinstance(raw, list) else []
            keysets = Counter(tuple(sorted(e.keys())) for e in raw if isinstance(e, dict))
            print(f"\nDOC {i}: {doc.get('filename')!r}  [{doc.get('doc_type')}]"
                  f"  text={len(doc.get('text') or ''):,} chars")
            if not raw:
                print("   0 raw entries - the index pass produced nothing for this "
                      "document.\n   Check the backend console for 'dec_index_pass'.")
            for ks, n in keysets.most_common():
                tag = ("dedicated pass (13-key)" if "kind" in ks
                       else "main extraction (6-key)" if len(ks) == 6 else "unknown shape")
                print(f"   {n:5} entries x {len(ks):2} keys  [{tag}]")
                print(f"         {list(ks)}")
            all_entries.extend(raw)

        merged = _unwrap((session.get("facts") or {}).get("dec_page_entries")) or []
        print(f"\nMERGED (verified, what LLM call 2 reads): {len(merged)} entries")
        if all_entries and not merged:
            print("   ^ raw entries exist but NONE survived verification - that is a"
                  "\n     bug worth reporting, not a quiet nothing.")

        out = os.path.abspath(f"raw_entries_{sid}.json")
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(all_entries, fh, indent=2, ensure_ascii=False)
        print(f"\nWrote {len(all_entries)} raw entries -> {out}")
        if all_entries:
            print("\nFirst entry:")
            print(json.dumps(all_entries[0], indent=2, ensure_ascii=False))
        return 0
    finally:
        try:
            await close_pool()
        except Exception:                                  # noqa: BLE001
            pass


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
