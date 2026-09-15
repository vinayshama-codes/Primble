"""Confirm-or-correct: show the client what we already hold, and say where from.

Chat 5 (14 Sep 2026), client Orbin audit, verbatim: "Do not ask the client for
information we already have. We already had the Subaru year/make/model/VIN in
the policy, yet the client was asked for it again ... Primble should prepopulate
source-verified information and ask the client to confirm or correct it, then
only ask for what is actually missing."

Before this module the questionnaire had exactly two moves for a fact: ASK it
(blank) or HIDE it (known). A known value never reached the client at all -
`send_arq` and `client_view` both hard-blank `current_value` - and a known
schedule reached them pre-filled under "Please list the vehicles to be insured",
which reads as a request for data we already hold. There was no third move.

This is the third move, built only from pieces that already exist:

  * the fact envelope's `evidence_state` (`fact_state`) says whether a value is
    SOURCE VERIFIED, and `user_confirmed` is already an evidence state that
    `derive_evidence_state` honours and `human_provenance_facts` carries across
    a pipeline re-run - so a confirmation needs no new column and survives
    re-merges;
  * per-document facts say WHICH uploaded document carries a value, which gives
    the client a plain "from your policy declarations" label for free;
  * the questionnaire's "I'm not sure" sentinel is the template for a
    "this is correct" answer that is recorded but never written into a box;
  * a CORRECTION is simply an answer, and a client answer that contradicts the
    documents is already held for the producer (arq_service F7).

Pure functions only - no I/O, no LLM.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any, Iterable, List, Optional

logger = logging.getLogger(__name__)

# The client's "this is correct" answer. Recorded like any other answer while
# drafting and at submit, but never stamped into a form and never read as a
# value. MUST stay identical to CONFIRMED in
# frontend/src/components/arq/ClientQuestionnaire.jsx.
CONFIRMED_SENTINEL = "__CONFIRMED__"

# facts[CONFIRMATIONS_KEY] = {"fact:<key>" | "schedule::<list_key>": {...}}.
# Private (underscore) key: skipped by every fact sweep, merged additively by
# `upd_processing_session`, so it survives a pipeline re-run untouched.
CONFIRMATIONS_KEY = "_client_confirmations"

MAX_SOURCE_LABELS = 3
_MAX_DISPLAY_CHARS = 300

# Client-safe names for the documents a value came from. The uploaded FILE name
# is never shown to the insured - it can carry internal notes ("CRS COI FIO -
# Orbin CERT ONLY.pdf") - only what KIND of document it is.
_DOC_TYPE_LABELS = {
    "dec_page":          "your policy declarations",
    "declarations":      "your policy declarations",
    "policy":            "your policy",
    "certificate":       "your certificate of insurance",
    "application":       "your insurance application",
    "acord_application": "your insurance application",
    "narrative":         "your submission narrative",
    "loss_run":          "your loss runs",
    "questionnaire":     "your completed questionnaire",
    "supplemental":      "your supplemental application",
}
_FALLBACK_DOC_LABEL = "your documents"

# Values that must never be echoed back through an emailed link. A federal tax
# ID, a date of birth or a licence number is the insured's own data, but a
# questionnaire link can be forwarded, and printing it back in full is not what
# "confirm" needs. These stay ask-only.
_SENSITIVE_KEY_RE = re.compile(
    r"(fein|ssn|social_security|tax_id|taxid|\bdob\b|birth|license_number|"
    r"licence_number|bank|routing|account_number)", re.I)


# ── the answer sentinel ─────────────────────────────────────────────────────

def is_confirmed_value(raw: Any) -> bool:
    return isinstance(raw, str) and raw.strip() == CONFIRMED_SENTINEL


# ── which facts are confirmable ─────────────────────────────────────────────

def is_sensitive(key: str) -> bool:
    return bool(key) and bool(_SENSITIVE_KEY_RE.search(str(key)))


def core_confirm_candidates() -> List[str]:
    """The facts SQS itself calls core - Tier 1, the Tier 1 contact trio and
    Tier 2 - in the scorer's own order. Derived, not a second list: a fact
    added to a tier becomes confirmable the same day. Every other gate
    (client audience, not insurance judgment, source verified) still applies at
    the call site."""
    try:
        from services.sqs_service import TIER1_CONTACT, TIER1_FIELDS, TIER2_FIELDS
    except Exception:                                         # noqa: BLE001
        return []
    out: List[str] = []
    for key in list(TIER1_FIELDS) + list(TIER1_CONTACT) + list(TIER2_FIELDS):
        if key not in out:
            out.append(key)
    return out


def _unwrap(raw: Any) -> Any:
    return raw.get("value") if isinstance(raw, dict) and "value" in raw else raw


def display_value(raw: Any) -> Optional[str]:
    """A scalar we can show and the client can check, or None."""
    val = _unwrap(raw)
    if val is None or isinstance(val, (bool, list, dict)):
        return None
    text = re.sub(r"\s+", " ", str(val)).strip()
    if not text or len(text) > _MAX_DISPLAY_CHARS:
        return None
    return text


def _conflicted(facts: dict, key: str) -> bool:
    for k in ("_uw_conflict_keys", "_uw_conflicted_keys"):
        if key in set((facts or {}).get(k) or ()):
            return True
    return False


def confirmable_display_value(facts: Optional[dict], key: str) -> Optional[str]:
    """The value to show for confirmation, or None when it must not be shown.

    Only a SOURCE VERIFIED, PRESENT, uncontested scalar qualifies. A value the
    model merely suggested is not "source-verified information" - showing it
    as ours would be exactly the silent promotion the client's rule forbids -
    and a bare scalar carries no provenance at all, so it is never shown.
    """
    if not isinstance(facts, dict) or not key or is_sensitive(key):
        return None
    raw = facts.get(key)
    if not (isinstance(raw, dict) and "value" in raw):
        return None
    if _conflicted(facts, key):
        return None
    try:
        from services.fact_state import (
            PRESENT, SOURCE_VERIFIED, derive_evidence_state, derive_value_state,
        )
        if derive_evidence_state(raw)[0] != SOURCE_VERIFIED:
            return None
        if derive_value_state(key, raw, facts) != PRESENT:
            return None
    except Exception:                                         # noqa: BLE001
        return None
    return display_value(raw)


# ── where a value came from ─────────────────────────────────────────────────

def doc_label(doc_type: Any) -> str:
    return _DOC_TYPE_LABELS.get(str(doc_type or "").strip().lower(), _FALLBACK_DOC_LABEL)


def _active_docs(session_docs: Optional[Iterable[dict]]) -> List[dict]:
    return [d for d in (session_docs or [])
            if isinstance(d, dict) and not d.get("excluded")]


def _add_label(out: List[str], label: str) -> None:
    if label and label not in out and len(out) < MAX_SOURCE_LABELS:
        out.append(label)


def source_labels_for_list(list_key: str, session_docs: Optional[Iterable[dict]]) -> List[str]:
    """Documents whose own facts carry this schedule."""
    out: List[str] = []
    for d in _active_docs(session_docs):
        rows = _unwrap((d.get("facts") or {}).get(list_key))
        if isinstance(rows, list) and any(
                isinstance(r, (dict, str)) and r for r in rows):
            _add_label(out, doc_label(d.get("doc_type")))
    return out


def source_labels_for_fact(fact_key: str, value: Any,
                           session_docs: Optional[Iterable[dict]]) -> List[str]:
    """Documents whose own copy of this fact says the SAME thing.

    Sameness goes through the one comparison door (`fact_comparison`), so two
    printings of one address both count and a different value never lends its
    document's name to ours.
    """
    out: List[str] = []
    try:
        from services.fact_comparison import values_agree
    except Exception:                                         # noqa: BLE001
        return out
    for d in _active_docs(session_docs):
        dv = display_value((d.get("facts") or {}).get(fact_key))
        if dv is None:
            continue
        try:
            same = dv == str(value).strip() or values_agree(fact_key, dv, value)
        except Exception:                                     # noqa: BLE001
            same = False
        if same:
            _add_label(out, doc_label(d.get("doc_type")))
    return out


def sanitize_source_labels(raw: Any) -> List[str]:
    """Labels arriving on the wire (a producer request, a stored ARQ)."""
    if not isinstance(raw, list):
        return []
    out: List[str] = []
    for item in raw:
        text = re.sub(r"<[^>]*>", "", str(item or "")).strip()[:80]
        _add_label(out, text)
    return out


def sources_phrase(labels: Optional[List[str]]) -> str:
    """ "your policy declarations and your certificate of insurance" """
    labels = [l for l in (labels or []) if l]
    if not labels:
        return ""
    if len(labels) == 1:
        return labels[0]
    return ", ".join(labels[:-1]) + " and " + labels[-1]


# ── schedules ───────────────────────────────────────────────────────────────

def rows_signature(rows: Any) -> str:
    """Stable fingerprint of a table as it was shown."""
    try:
        blob = json.dumps(rows or [], sort_keys=True, separators=(",", ":"), default=str)
    except Exception:                                         # noqa: BLE001
        blob = str(rows)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def _confirmations(facts: Optional[dict]) -> dict:
    rec = (facts or {}).get(CONFIRMATIONS_KEY)
    return rec if isinstance(rec, dict) else {}


def schedule_is_confirmed(facts: Optional[dict], list_key: str, rows: Any) -> bool:
    """The client confirmed THIS table and it has not changed since."""
    rec = _confirmations(facts).get(f"schedule::{list_key}")
    return isinstance(rec, dict) and bool(rows) and rec.get("signature") == rows_signature(rows)


def record_schedule_confirmation(facts: dict, list_key: str, shown_rows: Any,
                                 arq_id: Optional[str], at_iso: str) -> None:
    conf = dict(_confirmations(facts))
    conf[f"schedule::{list_key}"] = {
        "at": at_iso, "arq_id": arq_id, "by": "client_arq",
        "rows": len(shown_rows or []), "signature": rows_signature(shown_rows),
    }
    facts[CONFIRMATIONS_KEY] = conf


def schedule_row_changes(list_key: str, seed_rows: Any, submitted_rows: Any) -> int:
    """How many rows WE supplied the client removed or altered.

    Judged by each table's own duplicate-detection identity (VIN for a
    vehicle, name + date of birth for a driver, address for a location), so a
    row that merely moved position is not a change. A row with no identity at
    all is compared whole.
    """
    try:
        from services import schedule_capture as sc
        defn = sc.get_def(list_key)
        if defn is None:
            return 0

        def _key(row: dict) -> str:
            sig = sc._dedup_signature(defn, row)             # noqa: SLF001
            return sig if sig is not None else json.dumps(row, sort_keys=True, default=str)

        submitted = {}
        for row in submitted_rows or []:
            if isinstance(row, dict):
                submitted.setdefault(_key(row), []).append(row)
        changed = 0
        for row in seed_rows or []:
            if not isinstance(row, dict):
                continue
            matches = submitted.get(_key(row)) or []
            if not any(m == row for m in matches):
                changed += 1
        return changed
    except Exception:                                         # noqa: BLE001
        return 0


# ── scalar facts ────────────────────────────────────────────────────────────

def record_fact_confirmation(facts: dict, fact_key: str, shown_value: Any,
                             arq_id: Optional[str], at_iso: str) -> bool:
    """Mark the client's confirmation on the fact envelope, value untouched.

    Only when the fact still says what the client was shown - a producer edit
    after the questionnaire went out must not inherit a confirmation of the
    old value. Returns True when recorded.
    """
    if not isinstance(facts, dict) or not fact_key:
        return False
    raw = facts.get(fact_key)
    if not (isinstance(raw, dict) and "value" in raw):
        return False
    current = display_value(raw)
    shown = display_value(shown_value)
    if current is None or shown is None:
        return False
    same = current == shown
    if not same:
        try:
            from services.fact_comparison import values_agree
            same = values_agree(fact_key, current, shown)
        except Exception:                                     # noqa: BLE001
            same = False
    if not same:
        logger.info("confirmation for %s not recorded: the value changed after "
                    "the questionnaire was sent", fact_key)
        return False
    try:
        from services.fact_state import USER_CONFIRMED
    except Exception:                                         # noqa: BLE001
        USER_CONFIRMED = "user_confirmed"
    env = dict(raw)
    env["evidence_state"] = USER_CONFIRMED
    env["evidence_actor"] = "client"
    env["confirmed_by"] = "client_arq"
    env["confirmed_at"] = at_iso
    if arq_id:
        env["confirmed_arq_id"] = arq_id
    facts[fact_key] = env
    conf = dict(_confirmations(facts))
    conf[f"fact:{fact_key}"] = {"at": at_iso, "arq_id": arq_id, "by": "client_arq",
                                "value": current}
    facts[CONFIRMATIONS_KEY] = conf
    return True
