"""
dump_a125_run.py - capture one ACORD 125 run in a single file, for grading
against `271page_test_data/A125_answer_key.json`.

    py backend/scripts/dump_a125_run.py --list
    py backend/scripts/dump_a125_run.py <session_id> > a125_run.json

WHY THIS AND NOT THE DOWNLOADED PDF
-----------------------------------
The stamped values live on the session row as
`generated_forms["ACORD_125"]["mapped"]`; the PDF bytes live in a separate
table and are rendered on download. On a venv where `pikepdf` renders blank
templates, the downloaded PDF is empty while the stored values are perfectly
intact - so grade the stored values, never the download.

WHAT IT CAPTURES
----------------
  merged_facts / flags   what LLM call 1 produced, after the merge
  documents[].facts      each document's own extraction, before the merge
  dec_page_entries       the declarations index, IF it survived generation
                         (PURGE_DEC_INDEX_AFTER_GENERATION=1 deletes it -
                         set it to 0 for the test run to keep it)
  stamped                generated_forms["ACORD_125"]["mapped"]
  confidence             per-field confidence labels for the same form
  fates                  every one of the 548 boxes re-classified by replaying
                         compute_form_gaps on the STORED facts: which boxes
                         Pass 1/1.5 owned, which went to LLM call 2, which were
                         owned blanks. This is what separates "call 1 never
                         extracted it" from "call 2 was asked and got it wrong".
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

FORM = "ACORD_125"


async def _list(limit: int = 15) -> None:
    from config.database import create_pool, get_pool
    await create_pool()
    async with get_pool().acquire() as con:
        rows = await con.fetch(
            "SELECT id, created_at, user_id FROM processing_sessions "
            "ORDER BY created_at DESC LIMIT $1", limit)
    print(f"{'session_id':40} {'created':28} user", file=sys.stderr)
    for r in rows:
        print(f"{str(r['id']):40} {str(r['created_at']):28} {r['user_id']}",
              file=sys.stderr)


def _fates(facts: dict) -> dict:
    """Replay the pre-LLM passes on the stored facts: who owned each box."""
    from pathlib import Path
    import services.pdf_service as ps
    here = Path(__file__).resolve().parents[1]
    schema = json.loads((here / "forms_schemas" / f"{FORM}_schema.json")
                        .read_text(encoding="utf-8"))
    mapped, unmatched, _det = ps.compute_form_gaps(FORM, schema, dict(facts))
    out = {}
    for f in schema:
        if f in mapped and mapped[f] not in (None, "", []):
            out[f] = "pass1"
        elif f in unmatched:
            out[f] = "call2"
        else:
            out[f] = "owned_blank"
    return out


async def _dump(session_id: str) -> None:
    from config.database import create_pool
    from repositories.session_repository import get_processing_session

    await create_pool()
    s = await get_processing_session(session_id)
    if not s:
        raise SystemExit(f"no session {session_id}")

    facts = s.get("facts") or {}
    flags = s.get("flags") or {}
    docs = s.get("docs") or []
    gen = (s.get("generated_forms") or {}).get(FORM) or {}

    try:
        fates = _fates({**facts, **flags})
    except Exception as exc:                                   # noqa: BLE001
        fates = {"_error": f"{type(exc).__name__}: {exc}"}

    payload = {
        "session_id": session_id,
        "form": FORM,
        "form_generated": bool(gen),
        "merged_facts": facts,
        "flags": flags,
        "dec_page_entries": facts.get("dec_page_entries") or
                            "(purged - set PURGE_DEC_INDEX_AFTER_GENERATION=0 "
                            "before the run to keep it)",
        "documents": [
            {"doc_id": d.get("doc_id"), "filename": d.get("filename"),
             "doc_type": d.get("doc_type"),
             "doc_type_confidence": d.get("doc_type_confidence"),
             "facts": d.get("facts") or {}, "flags": d.get("flags") or {}}
            for d in docs
        ],
        "stamped": gen.get("mapped") or {},
        "confidence": gen.get("confidence") or {},
        "fates": fates,
        "package_sqs": s.get("package_sqs"),
    }

    # RELATIONSHIP FINDINGS. No answer key involved - these check the facts
    # against EACH OTHER, so they are the half of the diagnosis that works on a
    # real client package. A high fill rate with findings here means extraction
    # is finding the values and attaching them to the wrong parties, which is
    # invisible on the finished form.
    # The uploaded text, so `score_a125_extraction.py` can run the grounding
    # half of the relationship checks on this dump alone. Capped: a 271-page
    # package is ~700k chars and the point is a debuggable file, not an archive.
    payload["raw_text"] = "\n".join(
        str(d.get("text") or "") for d in docs)[:2_000_000]

    try:
        from services.fact_relationships import check_fact_relationships, summarise
        _raw = payload["raw_text"]
        _rel = check_fact_relationships({**facts, **flags}, _raw)
        payload["relationship_findings"] = _rel
        payload["relationship_summary"] = summarise(_rel)
        for _f in _rel:
            print(f"  relationship [{_f['severity']}] {_f['code']}: {_f['message'][:110]}",
                  file=sys.stderr)
        if not _rel:
            print("  relationships: clean", file=sys.stderr)
    except Exception as exc:                                   # noqa: BLE001
        payload["relationship_findings"] = [{"code": "CHECK_FAILED",
                                             "message": f"{type(exc).__name__}: {exc}"}]
    print(json.dumps(payload, indent=1, default=str))
    n = len(payload["stamped"])
    filled = sum(1 for v in payload["stamped"].values()
                 if v not in (None, "", []))
    print(f"  session {session_id}: {len(docs)} document(s), "
          f"{len(facts)} merged facts, {filled} of {n} ACORD 125 boxes carry a "
          f"value", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("session_id", nargs="?")
    ap.add_argument("--list", action="store_true",
                    help="print the most recent sessions and exit")
    a = ap.parse_args()
    if a.list or not a.session_id:
        asyncio.run(_list())
        return 0
    asyncio.run(_dump(a.session_id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
