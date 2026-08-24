"""client_answer_review.py - the producer's post-generation decision list.

V1 plan C1, entry C1-D. Client rule 1.5: *"Client Answer Conflicts With Source:
do not automatically overwrite the source value. Create a conflict and route it
to the producer."*

WHY THIS IS NOT THE DATA CONSISTENCY PICKER (read before "simplifying" it there).
The picker resolves through ``confirm_underwriting_value`` -> ``_finalize_pipeline``,
and that function sets ``generated_forms: {}`` - it WIPES the generated forms.
``extraction_pipeline`` says so in its own comment: *"once forms have been
generated the producer can no longer return to this screen."* The client answers
AFTER generation, so routing a held answer into the picker would either be
invisible or destroy the producer's forms. C1-C shipped that routing and it was
wrong; this module is the correction.

The post-generation door that already works is
``arq_service.apply_producer_answer_to_session`` -> ``_restamp_canonical_into_forms``:
it writes a producer-provenance fact and patches the EXISTING forms in place.
That is what "Use the client's value" does here.

Two choices, both terminal, both audited:
  * **use_client**  - the client's value becomes a producer-provenance fact and
    is stamped into every generated form that carries it.
  * **keep_source** - the documents stand; the held answer is discarded.

Either way the hold is released, so the row retires and cannot re-fire.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

CHOICE_USE_CLIENT = "use_client"
CHOICE_KEEP_SOURCE = "keep_source"
VALID_CHOICES = frozenset({CHOICE_USE_CLIENT, CHOICE_KEEP_SOURCE})

# Where the held answers live. `facts` carries the copy the picker/pipeline read;
# the session column is the durable one the producer view reads.
SESSION_KEY = "client_answer_conflicts"
FACTS_KEY = "_client_answer_conflicts"


def _label_for(fact_key: str) -> str:
    """Human label for a fact key, from the tables that already name them."""
    try:
        from services.underwriting_consistency import RECONCILABLE_FIELDS
        cfg = RECONCILABLE_FIELDS.get(fact_key)
        if cfg and cfg.get("label"):
            return cfg["label"]
    except Exception:                                         # noqa: BLE001
        pass
    try:
        from services.fact_registry import FACT_REGISTRY
        entry = FACT_REGISTRY.get(fact_key) or {}
        for key in ("label", "display_name", "title"):
            if entry.get(key):
                return str(entry[key])
    except Exception:                                         # noqa: BLE001
        pass
    return fact_key.replace("_", " ").title()


def held_conflicts(session: Optional[dict]) -> Dict[str, dict]:
    """The raw held map for a session, from the durable column with a fallback
    to the copy carried on facts (older sessions, or a facts-only caller)."""
    if not isinstance(session, dict):
        return {}
    held = session.get(SESSION_KEY)
    if not isinstance(held, dict) or not held:
        facts = session.get("facts")
        held = (facts or {}).get(FACTS_KEY) if isinstance(facts, dict) else None
    return {k: v for k, v in (held or {}).items()
            if isinstance(v, dict) and str(v.get("client_value") or "").strip()}


def build_review_rows(session: Optional[dict]) -> List[dict]:
    """Display rows for the producer's "Needs your decision" section.

    One row per held answer. Pure; safe to call on any session shape. Returns
    [] when nothing is held, which is what keeps the section hidden.
    """
    rows: List[dict] = []
    for fact_key, held in sorted(held_conflicts(session).items()):
        rows.append({
            "fact_key":     fact_key,
            "label":        _label_for(fact_key),
            "client_value": str(held.get("client_value") or ""),
            "source_value": str(held.get("source_value") or ""),
            "field_name":   held.get("field_name") or fact_key,
            "held_at":      held.get("held_at"),
            "reason":       "The client's questionnaire answer does not match "
                            "the uploaded documents.",
        })
    return rows


def _strip_hold(container: Optional[dict], fact_key: str) -> Optional[dict]:
    """Remove one key from a held map, returning the remainder (or None)."""
    if not isinstance(container, dict):
        return None
    remaining = {k: v for k, v in container.items() if k != fact_key}
    return remaining or None


async def resolve_client_answer(
    session_id: str,
    fact_key: str,
    choice: str,
    user_id: Any = None,
) -> dict:
    """Apply the producer's decision on one held client answer.

    ``use_client``  - writes the client's value as a producer-provenance fact and
                      patches every generated form that carries it (no wipe, no
                      regeneration), then recomputes stops and SQS.
    ``keep_source`` - discards the held answer; the documents stand.

    Returns ``{"ok": bool, "message": str, ...}``. Never raises for an ordinary
    miss (unknown key, already resolved) - the row simply reports itself gone.
    """
    from repositories.session_repository import (
        get_processing_session, upd_processing_session,
    )

    if choice not in VALID_CHOICES:
        return {"ok": False, "message": "Choose the client's value or the document value."}

    session = await get_processing_session(session_id)
    held = held_conflicts(session)
    entry = held.get(fact_key)
    if not entry:
        return {"ok": False, "resolved_already": True,
                "message": "This item has already been resolved."}

    client_value = str(entry.get("client_value") or "").strip()
    source_value = str(entry.get("source_value") or "").strip()
    applied_forms: List[str] = []

    if choice == CHOICE_USE_CLIENT:
        from services.arq_service import apply_producer_answer_to_session
        ok, updated = await apply_producer_answer_to_session(
            session_id, fact_key, client_value)
        if not ok:
            return {"ok": False,
                    "message": "That value can't be applied to the forms directly. "
                               "Edit the field on the form instead."}
        applied_forms = list(updated or [])

    # Release the hold on BOTH copies, whichever choice was made. Re-read the
    # session: apply_producer_answer_to_session rewrote facts and generated_forms.
    session = await get_processing_session(session_id)
    facts = dict(session.get("facts") or {})
    remaining_facts = _strip_hold(facts.get(FACTS_KEY), fact_key)
    if remaining_facts:
        facts[FACTS_KEY] = remaining_facts
    else:
        facts.pop(FACTS_KEY, None)
    remaining_session = _strip_hold(session.get(SESSION_KEY), fact_key) or {}
    # `delete_facts`, not a bare pop: the facts merge in upd_processing_session
    # is ADDITIVE - a key simply absent from updates["facts"] is PRESERVED, so
    # popping it here cleared nothing in the database and the hold would have
    # come back on the next read (bug B13, found 2026-08-21).
    await upd_processing_session(
        session_id,
        {"facts": facts, SESSION_KEY: remaining_session},
        delete_facts=([FACTS_KEY] if not remaining_facts else None),
    )

    # Audit: the producer saw both values and chose. Reuses the confirmation
    # table so the E&O record has one home for "a human picked between two
    # values" (V1 F10 - candidates + reason are persisted with it).
    try:
        from services.audit_service import log_underwriting_confirmation
        await log_underwriting_confirmation(
            session_id, str(user_id) if user_id is not None else None,
            fact_key=fact_key, label=_label_for(fact_key),
            confirmed_value=(client_value if choice == CHOICE_USE_CLIENT else source_value),
            previous_value=source_value,
            candidates=[
                {"value": source_value, "sources": [{"filename": "uploaded documents"}]},
                {"value": client_value, "sources": [{"filename": "Client questionnaire"}]},
            ],
            reason="client questionnaire answer disagreed with the documents",
        )
    except Exception as exc:                                  # noqa: BLE001
        logger.error("client_answer_review: audit write failed for %s - %s", fact_key, exc)

    # Recompute stops / SQS so the panel and the score reflect the decision.
    score_update: dict = {}
    try:
        from services.arq_service import recalculate_session_scores
        score_update = await recalculate_session_scores(session_id) or {}
    except Exception as exc:                                  # noqa: BLE001
        logger.error("client_answer_review: recalc failed for %s - %s", fact_key, exc)

    logger.info(
        "client_answer_review: session=%s fact=%s choice=%s forms=%s (user=%s)",
        session_id, fact_key, choice, applied_forms, user_id,
    )
    session = await get_processing_session(session_id)
    return {
        "ok": True,
        "fact_key": fact_key,
        "choice": choice,
        "applied_value": client_value if choice == CHOICE_USE_CLIENT else source_value,
        "forms_updated": applied_forms,
        "client_answer_review": build_review_rows(session),
        "package_sqs": session.get("package_sqs"),
        "score_recalculated": bool(score_update.get("ok")),
        "message": ("The client's answer has been applied to the forms."
                    if choice == CHOICE_USE_CLIENT
                    else "Kept the value from the documents."),
    }
