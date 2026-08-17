"""
Dump everything the conflict layer reads for one session, so a real run can be
inspected offline instead of reasoned about.

WHY THIS EXISTS: on 2026-08-17 three of four predictions about conflict
behaviour were wrong, and every one of them was wrong because the reasoning was
done against the CODE instead of against a real session's facts. Extraction
produces fact keys nobody anticipated (contractor_type, a composite gl_limits
string, an umbrella date lifted out of a remarks sentence, a page header stored
as additional_remarks_text) and those keys are half of what the conflict layer
argues about. There was no way to see them. Now there is.

Usage (from backend/):
    py scripts/dump_session_facts.py <session_id>
    py scripts/dump_session_facts.py <session_id> --json > session.json

Find the session id in the browser URL of the review screen, or run with
    py scripts/dump_session_facts.py --list
to print the most recent sessions.

Output sections:
  1. MERGED FACTS   - the single fact dict every downstream layer reads
  2. FLAGS          - the boolean coverage indicators
  3. PER-DOCUMENT   - each document's own facts (this is what the Data
                      Consistency picker actually compares)
  4. WITHHELD       - facts flagged unresolved (_uw_conflicted_keys)
  5. DEC ENTRIES    - the label/value/policy/line index. THE CONTEXT THAT
                      EXISTS AND THE CONFLICT LAYER NEVER READS.
  6. CONFLICT REPLAY- re-runs assess_underwriting_consistency on the stored
                      docs and prints every row it would produce, so a
                      Data Consistency row can be traced to its inputs.
"""
import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")


def _short(v, n=110):
    s = json.dumps(v, default=str) if isinstance(v, (dict, list)) else str(v)
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _unwrap(v):
    return v["value"] if isinstance(v, dict) and "value" in v else v


async def _list_recent(limit=15):
    from config.database import create_pool, get_pool
    await create_pool()
    pool = get_pool()
    async with pool.acquire() as con:
        rows = await con.fetch(
            "SELECT id, created_at, user_id FROM processing_sessions "
            "ORDER BY created_at DESC LIMIT $1", limit)
    print(f"{'session_id':40} {'created':26} user")
    print("-" * 80)
    for r in rows:
        print(f"{str(r['id']):40} {str(r['created_at']):26} {r['user_id']}")


async def _dump(session_id: str, as_json: bool):
    from config.database import create_pool
    from repositories.session_repository import get_processing_session
    from services.underwriting_consistency import assess_underwriting_consistency

    await create_pool()
    s = await get_processing_session(session_id)
    facts = s.get("facts") or {}
    flags = s.get("flags") or {}
    docs = s.get("docs") or []

    if as_json:
        print(json.dumps({
            "session_id": session_id,
            "merged_facts": facts,
            "flags": flags,
            "documents": [
                {"doc_id": d.get("doc_id"), "filename": d.get("filename"),
                 "doc_type": d.get("doc_type"), "facts": d.get("facts") or {}}
                for d in docs
            ],
        }, indent=2, default=str))
        return

    print("=" * 78)
    print(f"SESSION {session_id}   documents={len(docs)}")
    print("=" * 78)

    # ── 1. merged facts ──────────────────────────────────────────────────
    scalars, lists, private = {}, {}, {}
    for k, v in sorted(facts.items()):
        val = _unwrap(v)
        if k.startswith("_"):
            private[k] = val
        elif isinstance(val, (list, dict)):
            lists[k] = val
        else:
            scalars[k] = val
    print(f"\n1. MERGED SCALAR FACTS ({len(scalars)}) - what the conflict layer compares")
    print("-" * 78)
    for k, v in scalars.items():
        print(f"  {k:36} {_short(v)}")
    print(f"\n   LIST / STRUCTURED FACTS ({len(lists)}) - excluded from the picker")
    for k, v in lists.items():
        n = len(v) if isinstance(v, (list, dict)) else "?"
        print(f"  {k:36} [{n} entries] {_short(v, 70)}")

    # ── 2. flags ─────────────────────────────────────────────────────────
    print(f"\n2. FLAGS ({len(flags)})")
    print("-" * 78)
    on = [k for k, v in sorted(flags.items()) if v is True]
    off = [k for k, v in sorted(flags.items()) if v is False]
    null = [k for k, v in sorted(flags.items()) if v is None]
    print(f"  TRUE  ({len(on)}): {', '.join(on) or '-'}")
    print(f"  FALSE ({len(off)}): {', '.join(off) or '-'}")
    print(f"  NULL  ({len(null)}): {', '.join(null) or '-'}   <- 'not stated'; "
          f"an empty list here means the schema never allows 'unknown'")

    # ── 3. per-document facts ────────────────────────────────────────────
    print(f"\n3. PER-DOCUMENT FACTS - the ACTUAL input to the Data Consistency picker")
    print("-" * 78)
    for i, d in enumerate(docs, 1):
        df = d.get("facts") or {}
        ds = {k: _unwrap(v) for k, v in df.items()
              if not k.startswith("_") and not isinstance(_unwrap(v), (list, dict))}
        print(f"\n  DOC {i}: {d.get('filename')}  [{d.get('doc_type')}]  "
              f"{len(ds)} scalar facts, raw text {len(str(d.get('text') or ''))} chars")
        for k, v in sorted(ds.items()):
            print(f"     {k:34} {_short(v, 90)}")

    # ── 4. withheld ──────────────────────────────────────────────────────
    print(f"\n4. WITHHELD (unresolved, stamped blank)")
    print("-" * 78)
    print("  " + (", ".join(facts.get("_uw_conflicted_keys") or []) or "(none)"))
    if private:
        print("  other private keys: " + ", ".join(sorted(private)))

    # ── 5. dec entries ───────────────────────────────────────────────────
    entries = facts.get("dec_page_entries") or []
    lines = facts.get("coverage_lines") or []
    print(f"\n5. DEC INDEX - {len(entries)} entries, {len(lines)} coverage lines")
    print("-" * 78)
    print("  THIS is where policy/line context lives. The conflict layer reads")
    print("  none of it - it only reads the flat scalars in section 1.")
    for e in lines:
        if isinstance(e, dict):
            print(f"   line={_short(e.get('line'), 28):30} "
                  f"policy={_short(e.get('policy_number'), 20):22} "
                  f"carrier={_short(e.get('carrier'), 30)}")
    shown = 0
    for e in entries:
        if not isinstance(e, dict):
            continue
        if e.get("policy_number") or e.get("line_of_business"):
            print(f"   {_short(e.get('label'), 32):34} = {_short(e.get('value'), 26):28} "
                  f"| {_short(e.get('line_of_business'), 20):22} | {_short(e.get('policy_number'), 18)}")
            shown += 1
            if shown >= 40:
                print(f"   … {len(entries) - shown} more")
                break

    # ── 6. conflict replay ───────────────────────────────────────────────
    print(f"\n6. CONFLICT REPLAY - every row the picker builds, with its inputs")
    print("-" * 78)
    active = [d for d in docs if not d.get("excluded")] or docs
    res = assess_underwriting_consistency(active, facts, s.get("uw_confirmations") or {})
    rows = [f for f in res.get("fields") or [] if f.get("status") == "conflict"]
    print(f"  {len(rows)} conflict row(s), {len(active)} active document(s)\n")
    for f in rows:
        print(f"  * {f['label']}  [{f['fact_key']}]  kind={f['kind']} "
              f"confidence={f.get('confidence')}")
        for v in f.get("values") or []:
            srcs = ", ".join(
                f"{s_.get('filename')}({s_.get('source_method')})"
                for s_ in v.get("sources") or [])
            mark = "  <-- SUGGESTED" if v.get("display") == f.get("suggested_value") else ""
            print(f"      {_short(v.get('display'), 70):72}{mark}")
            print(f"        from {srcs}")
        print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("session_id", nargs="?")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.list or not a.session_id:
        asyncio.run(_list_recent())
        return
    asyncio.run(_dump(a.session_id, a.json))


if __name__ == "__main__":
    main()
