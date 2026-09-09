"""services/form_addition.py - add ONE ACORD form to an already-generated package.

WHY THIS EXISTS
---------------
Client handoff UX-05: a validation can correctly say "ACORD 186 is missing" and
then offer only Dismiss / Mark resolved. Neither adds the form, and after
generation there is no route back to the form list at all.

The client's own spec asked for this and we only built half of it:

    Decision_Tree.txt L501 - "Missing certificate when requested = user-facing
    failure ... PROMPT USER TO GENERATE ACORD 25/28 post-bind."

We shipped the warning and never shipped the prompt-to-generate.

WHAT THIS IS NOT
----------------
NOT a general "add any form later" affordance. Owner ruling 2026-09-08:

    "no form can only be added after the generation of forms if our system finds
     that a form is missing, user can't add it later on"

So the 2026-08-13 product rule ("once any form is generated, user cannot go back
in that same package to generate another form") is NARROWED, not reversed: the
only way back in is a validation finding OUR OWN rules raised, and the route
enforces that by refusing any form no live issue is asking for.

WHY NOT REUSE `select_forms_bulk`
---------------------------------
It is destructive for this purpose, in four ways measured against the code:

  * `generated_forms` MERGES per form id (session_repository), so the six
    already-generated forms would survive - but
  * `selected_form_ids`, `active_form_id`, `cross_issues_last` and `package_sqs`
    are replace-wholesale, so posting one id collapses the session into a
    one-form package: the trigger set shrinks, cross-form rules that depend on
    the other forms stop firing, and the package score is recomputed from one
    form.
  * its JSON reply carries only the forms it generated, and the modal does
    `setGeneratedForms(data.generated)` - the on-screen list would drop to one.
  * re-running it over ALL ids instead rebuilds every form's `field_state`,
    destroying every producer edit that has no fact write-back.

So this module generates exactly the one new form and merges it in. Nothing
that already exists is regenerated, re-stamped or re-scored here - re-scoring is
`arq_service.recalculate_session_scores`, called by the route afterwards, which
is the same door the inline-resolution and ARQ paths already use.

THE DEC INDEX IS ALREADY GONE, AND THAT IS FINE
-----------------------------------------------
`PURGE_DEC_INDEX_AFTER_GENERATION` defaults to 1, so `dec_page_entries` was
deleted when the package generated. A form added afterwards therefore runs
without the Stage A index - the pre-2026-08-13 pipeline. Measured blast radius
of a missing index across all 17 schemas: 9 of 5,852 fields degrade to a blank
or a shorter printing of the same policy number. NO FIELD EVER GETS A WRONG
VALUE. Degrading is the documented, intended behaviour, not a new risk.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import os
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# Outcome codes, so the route never has to string-match a message.
OK = "ok"
ALREADY_PRESENT = "already_present"
UNKNOWN_FORM = "unknown_form"
NOT_REQUESTED = "not_requested"
NOT_GENERATED_YET = "not_generated_yet"
FAILED = "failed"

_MESSAGES = {
    ALREADY_PRESENT: "That form is already in this package.",
    UNKNOWN_FORM: "That form is not available for this submission.",
    NOT_REQUESTED: (
        "No open validation is asking for that form, so it can't be added here. "
        "Start a new package if you need it."
    ),
    NOT_GENERATED_YET: (
        "Forms have not been generated yet - tick the form on the Select Forms "
        "screen instead."
    ),
    FAILED: "The form could not be generated. Please try again.",
}


def message_for(outcome: str) -> str:
    return _MESSAGES.get(outcome, _MESSAGES[FAILED])


# ── What a live issue is ASKING for ──────────────────────────────────────────

def requested_form_ids(session: dict) -> set:
    """Every form id an OPEN validation on this session is asking to be added.

    Read off `resolution["add_forms"]`, which `cross_form_validator` stamps at
    the emit site - the same declaration the card renders. This is the owner's
    ruling made executable: a form nobody is asking for cannot be added.

    Deliberately reads the STORED issue list rather than re-running the rules.
    Re-running would need facts, flags and the trigger set and would disagree
    with what the producer is looking at; the stored list IS what they clicked.
    """
    out: set = set()
    for issue in (session.get("cross_issues_last") or []):
        if not isinstance(issue, dict):
            continue
        res = issue.get("resolution")
        if not isinstance(res, dict):
            continue
        for fid in (res.get("add_forms") or []):
            if isinstance(fid, str) and fid.strip():
                out.add(fid.strip())
    return out


def _form_meta(session: dict, form_id: str) -> Optional[dict]:
    """The form's own metadata row, or None when this session cannot build it.

    `all_forms` is written at extraction (`extraction_pipeline`) and has already
    been through `filter_available_forms`, so membership here means the template
    file existed at upload time. The path is re-checked below anyway - a
    template that has since moved must fail loudly, not stamp a blank PDF.
    """
    for f in (session.get("all_forms") or []):
        if isinstance(f, dict) and f.get("form_id") == form_id:
            return f
    return None


def _package_form_ids(session: dict) -> set:
    """Forms already in this package - selected OR generated.

    The union, not either alone: `selected_form_ids` is what the cross-form
    trigger set is built from, `generated_forms` is what the producer can see.
    A form in either one is present as far as "is it missing?" is concerned.
    """
    return set(session.get("selected_form_ids") or []) | set(
        (session.get("generated_forms") or {}).keys()
    )


# ── The door ─────────────────────────────────────────────────────────────────

async def add_form_to_session(
    session_id: str,
    form_id: str,
    *,
    enforce_requested: bool = True,
) -> Tuple[str, Dict[str, Any]]:
    """Generate `form_id` and merge it into an existing package.

    Returns `(outcome, payload)`. `payload` carries `form` (the same summary
    shape `select_forms_bulk` returns per form) on success, so the panel can add
    the row without a reload.

    Idempotent: a form already in the package returns ALREADY_PRESENT and writes
    nothing, so a double-click or a stale tab cannot regenerate a form the
    producer has already edited.
    """
    # Imported here, not at module import: `form_service` pulls in the PDF and
    # scoring stack, and this module is imported by the route layer at startup.
    from repositories.session_repository import (
        get_processing_session, upd_processing_session,
    )
    from services.form_service import active_document_text, process_single_form
    from services.pdf_service import (
        combined_gap_fill, compute_form_gaps, extract_form_schema,
    )
    from utils.helpers import safe_join
    from config.settings import TEMPLATE_DIR

    form_id = (form_id or "").strip()
    if not form_id:
        return UNKNOWN_FORM, {}

    session = await get_processing_session(session_id)

    # Pre-generation this endpoint is the WRONG door - the Select Forms list is
    # right there and costs nothing. Refusing keeps one invariant: everything
    # here is an addition to a package that already exists.
    if not (session.get("generated_forms") or {}):
        return NOT_GENERATED_YET, {}

    present = _package_form_ids(session)
    if form_id in present:
        return ALREADY_PRESENT, {}

    if enforce_requested and form_id not in requested_form_ids(session):
        return NOT_REQUESTED, {}

    form_meta = _form_meta(session, form_id)
    if not form_meta or not form_meta.get("template_file"):
        return UNKNOWN_FORM, {}
    try:
        tpl = safe_join(TEMPLATE_DIR, form_meta["template_file"])
    except ValueError:
        logger.warning("form_addition: unsafe template path blocked for %s", form_id)
        return UNKNOWN_FORM, {}
    if not os.path.exists(tpl):
        logger.warning("form_addition: template missing on disk for %s", form_id)
        return UNKNOWN_FORM, {}

    loop = asyncio.get_event_loop()
    # Reuse the generation thread pool rather than starting a second one, so a
    # form added here contends for the same bounded capacity as a normal
    # generation instead of running beside it.
    from routes.form_routes import _FORM_EXECUTOR

    try:
        facts_with_flags = {**(session.get("facts") or {}),
                            **(session.get("flags") or {})}

        schema = await loop.run_in_executor(
            _FORM_EXECUTOR, extract_form_schema, tpl, form_id,
        )
        mapped, unmatched, _det = await loop.run_in_executor(
            _FORM_EXECUTOR, compute_form_gaps, form_id, schema, facts_with_flags,
        )

        # ONE form's slice of the shared pass. `combined_gap_fill` is the same
        # function generation uses; calling it with a single-entry dict is the
        # documented degenerate case, not a special path - so batching, the
        # evidence gate and every post-fill guard behave identically.
        pre_filled = None
        if unmatched:
            raw_text = active_document_text(session)
            pre_filled_all = await loop.run_in_executor(
                _FORM_EXECUTOR,
                functools.partial(
                    combined_gap_fill,
                    {form_id: unmatched}, facts_with_flags, raw_text,
                    forms_to_mapped={form_id: mapped} if mapped else None,
                ),
            )
            pre_filled = (pre_filled_all or {}).get(form_id)

        result = await loop.run_in_executor(
            _FORM_EXECUTOR, process_single_form, form_meta, session, pre_filled,
        )
    except Exception as ex:                                       # noqa: BLE001
        logger.error("form_addition: generation failed session=%s form=%s: %s",
                     session_id, form_id, ex, exc_info=True)
        return FAILED, {}

    if not result:
        logger.error("form_addition: empty result session=%s form=%s",
                     session_id, form_id)
        return FAILED, {}

    # `generated_forms` merges per form id in session_repository, so this adds
    # the row without touching the six already there. `selected_form_ids` is
    # replace-wholesale, so it MUST be sent complete - sending only the new id
    # is precisely how reusing select_forms_bulk would have collapsed the
    # package.
    selected = list(session.get("selected_form_ids") or [])
    if form_id not in selected:
        selected.append(form_id)
    await upd_processing_session(session_id, {
        "generated_forms":   {form_id: result},
        "selected_form_ids": selected,
    })

    logger.info("form_addition: added %s to session=%s (package now %d forms)",
                form_id, session_id, len(selected))

    return OK, {
        "form": {
            "form_id":       result.get("form_id", form_id),
            "form_name":     result.get("form_name", form_id),
            "form":          result.get("form"),
            "sqs":           result.get("sqs"),
            "fields_mapped": sum(1 for v in (result.get("mapped") or {}).values()
                                 if v is not None),
            "schema_size":   len(result.get("schema") or {}),
        },
        "selected_form_ids": selected,
    }
