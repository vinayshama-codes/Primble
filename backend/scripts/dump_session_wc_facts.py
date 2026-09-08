"""Dump the WC facts and the coverage flags for a session.

Answers one question: when ACORD 25's Workers Compensation block fills on a
package that carries no workers comp, is it because

  (a) extraction produced a `wc_*` fact - in which case the suppression rule is
      working as designed and the defect is upstream, in extraction; or
  (b) the flags dict reached form fill too thin for `_flags_were_computed` - in
      which case the suppression never fires and the rule is inert.

Usage, from backend/ with the same environment the app runs in:

    py scripts/dump_session_wc_facts.py                 # the most recent session
    py scripts/dump_session_wc_facts.py <session_id>    # a specific one
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


async def main() -> None:
    import config.database as db                                   # noqa: E402
    from repositories.session_repository import get_processing_session  # noqa: E402

    sid = sys.argv[1] if len(sys.argv) > 1 else None
    if db._pool is None:
        await db.create_pool()

    if sid in ("--list", "-l", "list"):
        async with db._pool.acquire() as con:
            rows = await con.fetch(
                "SELECT id, created_at, data FROM processing_sessions "
                "ORDER BY created_at DESC LIMIT 15")
        print(f"{'SESSION ID':38s} {'CREATED':20s} FORMS GENERATED")
        for r in rows:
            d = r["data"]
            if isinstance(d, (str, bytes)):
                try:
                    d = json.loads(d)
                except Exception:                                  # noqa: BLE001
                    d = {}
            forms = sorted((d.get("generated_forms") or {}).keys())
            print(f"{str(r['id']):38s} {str(r['created_at'])[:19]:20s} "
                  f"{', '.join(forms) or '(none)'}")
        print()
        print("Re-run with the id of the session that produced ACORD_25.")
        return

    if not sid:
        async with db._pool.acquire() as con:
            r = await con.fetchrow("SELECT id FROM processing_sessions "
                                   "ORDER BY created_at DESC LIMIT 1")
        if not r:
            print("no session found")
            return
        sid = str(r["id"])
    # Through the repository, NOT raw SQL: `facts` is stored ENCRYPTED
    # (utils/crypto.py) and only `get_processing_session` decrypts it.
    data = await get_processing_session(sid)
    facts = data.get("facts") or {}
    flags = data.get("flags") or {}
    if isinstance(facts, str):
        try:
            facts = json.loads(facts)
        except Exception:                                          # noqa: BLE001
            print("facts did not decrypt - is FIELD_ENCRYPTION_KEY set in this shell?")
            print(f"raw facts starts: {facts[:80]!r}")
            return
    if isinstance(flags, str):
        try:
            flags = json.loads(flags)
        except Exception:                                          # noqa: BLE001
            flags = {}
    row = {"id": sid}

    print(f"session : {row['id']}")
    print(f"forms   : {sorted((data.get('generated_forms') or {}).keys())}")
    print()

    wc = {k: v for k, v in facts.items()
          if isinstance(k, str)
          and k.startswith(("wc_", "workers_", "employers_", "el_",
                            "total_payroll", "class_code", "officer_"))}
    print(f"--- WC facts in facts{{}}: {len(wc)}")
    for k, v in sorted(wc.items()):
        print(f"      {k} = {json.dumps(v)[:120]}")
    if not wc:
        print("      (none)")
    print()

    has_facts = sorted(k for k in facts if isinstance(k, str) and k.startswith("has_"))
    has_flags = sorted(k for k in flags if isinstance(k, str) and k.startswith("has_"))
    print(f"--- has_* keys in flags{{}} : {len(has_flags)}")
    print(f"      {has_flags}")
    print(f"--- has_* keys in facts{{}} : {len(has_facts)}")
    print(f"      {has_facts}")
    print(f"--- has_workers_comp        : "
          f"facts={facts.get('has_workers_comp')!r}  flags={flags.get('has_workers_comp')!r}")
    print()

    merged = {**facts, **flags}
    try:
        os.environ.setdefault("OPENAI_API_KEY", "sk-offline-test")
        import services.pdf_service as ps                          # noqa: E402
        print("--- THE VERDICT, computed by the real code on this session")
        print(f"      _flags_were_computed(facts+flags) = "
              f"{ps._flags_were_computed(merged)}")
        print(f"      _family_has_no_evidence(...)      = "
              f"{ps._family_has_no_evidence(merged, ('workers compensation', 'employers liability'))}")
        wc_field = ("WorkersCompensationEmployersLiability_EmployersLiability_"
                    "EachAccidentLimitAmount_A")
        asked = ps._resolve_declared_absent_line_row(wc_field, merged) is ps._SCHED_SKIP
        print(f"      WC band is {'ASKED OF THE MODEL' if asked else 'an OWNED BLANK'}")
    except Exception as exc:                                       # noqa: BLE001
        print(f"      (could not evaluate: {exc})")


if __name__ == "__main__":
    asyncio.run(main())
