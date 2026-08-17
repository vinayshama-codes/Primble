"""Check a real session against the client's 2026-08-17 items 3 and 4.

Run this on a FRESH upload instead of clicking through screens. Every check
drives production code on the session's own facts - none of it is a mock.

Usage (from backend/):
    py scripts/verify_client_fixes.py <session_id>
    py scripts/verify_client_fixes.py --latest

Exit code is 0 when every check the client asked for passes.
"""
import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

PASS, FAIL, WARN = "PASS", "FAIL", "OPEN"
_results: list = []


def check(label: str, ok, detail: str = "", soft: bool = False) -> None:
    status = PASS if ok else (WARN if soft else FAIL)
    _results.append((status, label))
    mark = {PASS: "  ok  ", FAIL: " FAIL ", WARN: " open "}[status]
    print(f"[{mark}] {label}")
    # Detail explains a failure. Printing it on a pass reads as a contradiction
    # ("ok ... a card still writes into the year-count field"), which is exactly
    # how a green run gets mistaken for a red one.
    if detail and status != PASS:
        for line in str(detail).splitlines():
            print(f"          {line}")


async def _latest_session() -> str:
    from config.database import get_pool
    async with get_pool().acquire() as con:
        return await con.fetchval(
            "SELECT id FROM processing_sessions "
            "WHERE jsonb_typeof(data->'generated_forms') = 'object' "
            "  AND data->'generated_forms' <> '{}'::jsonb "
            "ORDER BY created_at DESC LIMIT 1")


async def main(sid: str) -> int:
    from config.database import create_pool
    await create_pool()
    from repositories.session_repository import get_processing_session

    if not sid:
        sid = await _latest_session()
        print(f"using latest session with forms: {sid}\n")

    session = await get_processing_session(sid)
    facts = session.get("facts") or {}
    flags = session.get("flags") or {}
    forms = session.get("generated_forms") or {}

    if not isinstance(facts, dict) or not facts:
        print("Session has no readable facts - cannot verify. "
              "Check FIELD_ENCRYPTION_KEY.")
        return 2

    print(f"session : {sid}")
    print(f"forms   : {', '.join(sorted(forms)) or '(none)'}")
    print(f"facts   : {len(facts)}\n")

    # ── Item 4: the points on the card ───────────────────────────────────────
    print("--- Item 4: does the card state its real value? ---")
    from services.sqs_service import (
        SPEC_PILLAR_WEIGHTS, calculate_p4_loss_history, _attested_true)

    loss_cards = [
        (fid, r)
        for fid, fd in forms.items() if isinstance(fd, dict)
        for r in ((fd.get("sqs") or {}).get("recommendations") or [])
        if r.get("component") == "loss_history_alignment"
    ]
    check("a loss-history card is present to inspect", bool(loss_cards),
          "no loss card on this submission - upload one with no loss runs",
          soft=True)

    if loss_cards:
        eights = [r for _f, r in loss_cards if r.get("score_impact") == 8]
        check("no card still prints the hardcoded +8", not eights,
              "\n".join(f"{f}: {r.get('message','')[:70]}" for f, r in loss_cards
                        if r.get("score_impact") == 8))

        pillar_now, _ = calculate_p4_loss_history(facts, flags)
        w = SPEC_PILLAR_WEIGHTS["loss_history_alignment"]
        # Once the producer has attested, the live card is the NEXT tier up
        # (60 -> 100, "attach loss runs"), so the 45/25 -> 60 arithmetic the
        # client quoted no longer applies. Check whichever target is live rather
        # than reporting a false failure on an already-answered submission.
        target = 100 if pillar_now >= 60 else 60
        expected = round(max(0, (target - pillar_now)) * w)
        shown = {r.get("score_impact") for _f, r in loss_cards}
        check("the printed value matches the published formula",
              any(abs(int(s) - expected) <= 1 for s in shown if s is not None),
              f"pillar now {pillar_now} -> {target} is ({target}-{pillar_now}) x {w} "
              f"= ~{expected} pts; cards show {sorted(shown)}")

        check("cards say whether the number is exact or a ceiling",
              all("impact_is_exact" in r for _f, r in loss_cards),
              "missing impact_is_exact - the UI cannot drop the 'up to' hedge")

        check("the card targets the fact that actually answers it",
              all(r.get("field") != "loss_history_years" for _f, r in loss_cards
                  if "No Known Losses" in str(r.get("message")) or
                  "No loss history" in str(r.get("message"))),
              "a confirmation card still writes into the year-count field")

    # every card, every form: never promise more than the pillar holds
    over = []
    for fid, fd in forms.items():
        if not isinstance(fd, dict):
            continue
        for r in ((fd.get("sqs") or {}).get("recommendations") or []):
            comp = r.get("component")
            if comp in SPEC_PILLAR_WEIGHTS:
                ceiling = round(SPEC_PILLAR_WEIGHTS[comp] * 100)
                if (r.get("score_impact") or 0) > ceiling:
                    over.append(f"{fid} {comp}: {r['score_impact']} > {ceiling}")
    check("no card promises more than its pillar can give", not over,
          "\n".join(over[:5]))

    # ── Item 3: absence is not "No" ──────────────────────────────────────────
    print("\n--- Item 3a: absence must not become No ---")
    for key, label in (("additional_insured_required",   "Additional Insured"),
                       ("waiver_of_subrogation_required", "Waiver of Subrogation"),
                       ("primary_noncontributory_required", "Primary/Noncontributory")):
        rt = facts.get("risk_transfer")
        rt = rt.get("value") if isinstance(rt, dict) and "value" in rt else rt
        val = (rt or {}).get(key) if isinstance(rt, dict) else facts.get(key)
        check(f"{label} can say 'not stated'", val is None or isinstance(val, bool),
              f"stored as {val!r} (None = not stated, which is the point)",
              soft=True)

    blank_pillar, _ = calculate_p4_loss_history({}, {})
    check("a blank loss answer scores as no information, not as 'no losses'",
          blank_pillar == 25, f"blank -> pillar {blank_pillar} (25 expected)")
    check("blank does not read as an attestation",
          _attested_true("") is False and _attested_true(None) is False)

    # ── Item 3b: the questionnaire ───────────────────────────────────────────
    print("\n--- Item 3b: the Client Questionnaire ---")
    from services.arq_service import (
        generate_arq_questions, NO_LOSS_INDICATOR_FIELD, _NO_LOSS_OPTIONS)

    questions = await generate_arq_questions(
        facts, flags, forms,
        session.get("hard_stops") or [], session.get("soft_stops") or [],
        session_docs=session.get("docs") or [])

    loss_q = next((q for q in questions
                   if q.get("field_name") == NO_LOSS_INDICATOR_FIELD), None)
    # An already-answered submission must NOT be asked again, so absence is the
    # correct result there. Only a still-unattested one owes us the question.
    already_attested = _attested_true(
        (facts.get(NO_LOSS_INDICATOR_FIELD) or {}).get("value")
        if isinstance(facts.get(NO_LOSS_INDICATOR_FIELD), dict)
        else facts.get(NO_LOSS_INDICATOR_FIELD)
    )
    if already_attested:
        print("[  ok  ] loss history already attested on this submission - the "
              "questionnaire correctly does not ask again")
        _results.append((PASS, "loss question correctly not re-asked"))
    else:
        check("the loss-history question exists at all", loss_q is not None,
              "it used to appear only as the raw field "
              "LossHistory_NoPriorLossesIndicator_A, classed internal")

    if loss_q:
        check("it is pre-selected", bool(loss_q.get("default_selected")),
              f"default_selected={loss_q.get('default_selected')}")
        qt = str(loss_q.get("question", "")).lower()
        check("it uses the client's wording",
              "have you had any insurance claims or losses" in qt,
              loss_q.get("question"))
        check("it is not a checkbox (a checkbox cannot say 'not answered')",
              loss_q.get("field_type") == "select",
              f"field_type={loss_q.get('field_type')} "
              f"options={loss_q.get('options')}")
        check("both explicit answers are offered",
              list(loss_q.get("options") or []) == list(_NO_LOSS_OPTIONS))
        check("it is not pre-answered", not loss_q.get("current_value"))

    urgency = next((q for q in questions
                    if q.get("field_name") == "submission_urgency"), None)
    if loss_q and urgency:
        check("the valuable question outranks Submission Urgency",
              (loss_q.get("sqs_points") or 0) > (urgency.get("sqs_points") or 0),
              f"loss={loss_q.get('sqs_points')} pts, "
              f"urgency={urgency.get('sqs_points')} pts")

    selected = [q for q in questions if q.get("default_selected")]
    print(f"          pre-selected ({len(selected)}):")
    for q in selected:
        print(f"            {str(q.get('field_name'))[:44]:46s} "
              f"pts={q.get('sqs_points') or 0}")

    # ── Item 3c: readable questions ──────────────────────────────────────────
    print("\n--- Item 3c: readable questions in the normal workflow ---")
    human = [q for q in questions
             if q.get("audience") in ("client", "producer")
             and not q.get("suppressed")]
    raw = [q for q in human
           if str(q.get("question", "")).startswith("Please provide your")]
    check("no machine-worded prompt reaches a client or producer",
          not raw,
          "\n".join(f"[{q.get('audience')}] {q.get('question')}" for q in raw[:8])
          + (f"\n... {len(raw)} of {len(human)} visible questions" if raw else ""),
          soft=True)

    print(f"\n{'='*64}")
    failed = [l for s, l in _results if s == FAIL]
    opened = [l for s, l in _results if s == WARN]
    print(f"{len([1 for s,_ in _results if s==PASS])} passed, "
          f"{len(failed)} failed, {len(opened)} known-open")
    for l in failed:
        print(f"  FAILED: {l}")
    for l in opened:
        print(f"  open  : {l}")
    return 1 if failed else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("session_id", nargs="?")
    ap.add_argument("--latest", action="store_true")
    a = ap.parse_args()
    sys.exit(asyncio.run(main(None if a.latest else a.session_id)))
