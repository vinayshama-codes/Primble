"""Reading a person's narrative for what it covers (owner, 13 Oct 2026).

The narrative score checks 12 topics and 8 kinds of depth by KEYWORD. A person's
own wording ("most of our jobs are commercial remodels") says what "scope of
work: primarily commercial" says and fails the keyword list - the card stays and
nobody can tell why. Owner's decision, three layers:

  1. The fix window offers every missing item as an option; ticking one adds a
     labelled starter. The LABEL is the classification and the person's words
     are the content - so a starter with nothing real after it (or "TBD") is
     not content: `strip_unfinished_starters` removes such lines before anything
     is stored or scored.
  2. When a narrative is saved, ONE small model call reads it for meaning
     (`read_narrative`) and may credit an item only by QUOTING the narrative
     word for word - a quote not found in the text credits nothing, so it can
     never invent credit. Stored with a hash of the text it read; a different
     text (an edit, an undo, a document re-read) is a different reading.
  3. The keyword check stays the free first pass; the reading only ADDS.

Fail-open to (3): no key, no network, a malformed reply - nothing changes.
LLM call registry: improving-ll.md ("Narrative reader").
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from typing import Any, Dict, Optional, Set, Tuple

logger = logging.getLogger(__name__)

READING_KEY = "_narrative_reading"      # bookkeeping fact (facts merge per key)
# 2 (24 Oct 2026): the reading also carries the narrative's LOSS STANCE
# (`loss:claims` / `loss:no_claims`, with its quote). A reading stored before
# carries none, and only a version-2 reading is asked for one (`loss_stance`).
READER_VERSION = 2
LOSS_STANCES = ("claims", "no_claims")
_MIN_QUOTE_CHARS = 8
_MAX_TEXT_CHARS = 12000


def _norm(text: Any) -> str:
    return " ".join(str(text or "").split()).lower()


def text_hash(text: Any) -> str:
    return hashlib.sha256(_norm(text).encode("utf-8")).hexdigest()[:16]


# ── 1. An unfinished starter is not content ──────────────────────────────────
def _starters() -> list:
    from services.sqs_service import NARRATIVE_COMPONENT_LABELS, NARRATIVE_SUBSTANCE_STARTERS
    found = {_norm(s) for s in NARRATIVE_SUBSTANCE_STARTERS.values() if _norm(s)}
    found |= {_norm(f"{label}:") for label in NARRATIVE_COMPONENT_LABELS.values()}
    return sorted(found, key=len, reverse=True)


def _has_content(rest: str) -> bool:
    rest = rest.strip(" :-.,;")
    if not re.search(r"[a-z0-9]", rest):
        return False
    try:
        from services.answer_semantics import VALUE, interpret_answer
        return interpret_answer("additional_remarks_text", rest).intent == VALUE
    except Exception:                                          # noqa: BLE001
        return True


def strip_unfinished_starters(text: Any) -> str:
    """The text without lines that are only a starter or topic label with no
    real words after it ("Scope of work: primarily", "Loss History: TBD")."""
    raw = str(text or "")
    if not raw.strip():
        return raw
    try:
        starters = _starters()
    except Exception:                                          # noqa: BLE001
        return raw
    kept = []
    for line in raw.splitlines():
        low = _norm(line)
        hit = next((s for s in starters if low.startswith(s)), None)
        if hit is not None and not _has_content(low[len(hit):]):
            continue
        kept.append(line)
    return "\n".join(kept).strip() if len(kept) != len(raw.splitlines()) else raw


# ── 2. One meaning-based reading, evidence-gated ─────────────────────────────
_SYSTEM = (
    "You check an insurance submission narrative written by an insurance broker. For each "
    "item listed, decide whether the narrative clearly covers it, in any wording. When it "
    "does, copy the exact words from the narrative that show it - word for word, a short "
    "phrase or sentence, never paraphrased. When it does not clearly cover the item, answer "
    "false with an empty quote. Never guess and never quote words that are not in the "
    "narrative. Use each item id exactly as given, prefix included. ALSO say what the narrative "
    "states about the insured's OWN claims or losses in the last five years: \"claims\" (it says "
    "there were some), \"no_claims\" (it says there were none), \"mixed\" (it says both, or only "
    "for some lines, years or another company), or \"not_stated\" - with the exact words it relies "
    "on, copied word for word (empty when not_stated). Reply with JSON only: {\"items\": {\"<id>\": "
    "{\"covered\": true|false, \"quote\": \"...\"}}, \"loss\": {\"stance\": "
    "\"claims|no_claims|mixed|not_stated\", \"quote\": \"...\"}}"
)

_COMPONENT_HINTS = {
    "account_overview": "who the business is - an overview of the account",
    "operations": "what the business does - its operations",
    "years_in_business": "how long the business has operated",
    "management": "the owners' or managers' experience",
    "risk_controls": "safety, loss-control or risk-management practices",
    "loss_history": "the loss or claims history",
    "coverage_discussion": "the coverage, limits or program being sought",
    "carrier_market": "the current or prior carrier, or why the account is being marketed",
    "location_exposure": "the premises or locations",
    "employee_practices": "employees, headcount or payroll",
    "growth_trends": "workers compensation payroll or class codes",
    "target_markets": "the experience modification factor (EMOD / XMOD)",
}


def _items() -> Dict[str, str]:
    from services.sqs_service import NARRATIVE_COMPONENT_LABELS, NARRATIVE_SUBSTANCE_ASKS
    items = {f"topic:{k}": _COMPONENT_HINTS.get(k, label)
             for k, label in NARRATIVE_COMPONENT_LABELS.items()}
    items.update({f"depth:{k}": ask for k, ask in NARRATIVE_SUBSTANCE_ASKS.items()})
    return items


def gate_reply(reply: Any, text: str) -> Dict[str, str]:
    """{item id: quote} for each item the reply credits WITH a quote that is in
    the text (whitespace and case aside, at least a few characters)."""
    items = _items()
    body = _norm(text)
    out: Dict[str, str] = {}
    # The loss stance (24 Oct 2026): "claims" / "no_claims" with a quote that is
    # in the text, never "mixed" or "not_stated" - same gate as an item.
    loss = reply.get("loss") if isinstance(reply, dict) else None
    if isinstance(loss, dict) and loss.get("stance") in LOSS_STANCES:
        lq = _norm(loss.get("quote"))
        if len(lq) >= _MIN_QUOTE_CHARS and lq in body:
            out[f"loss:{loss['stance']}"] = str(loss.get("quote"))[:300]
    data = reply.get("items") if isinstance(reply, dict) else None
    if not isinstance(data, dict):
        return out
    for key, verdict in data.items():
        if not isinstance(verdict, dict) or verdict.get("covered") is not True:
            continue
        quote = _norm(verdict.get("quote"))
        if len(quote) < _MIN_QUOTE_CHARS or quote not in body:
            continue
        # The model sometimes drops the "topic:" / "depth:" prefix (measured on
        # gpt-5.4-mini, 13 Oct 2026). A bare id credits every item it names -
        # "risk_controls" is both a topic and a depth category, same meaning.
        ids = [key] if key in items else [i for i in items if i.split(":", 1)[1] == key]
        for i in ids:
            out[i] = str(verdict.get("quote"))[:300]
    return out


async def read_narrative(text: str) -> Optional[Dict[str, str]]:
    """The evidence-gated reading of `text`, or None when no reading was made."""
    text = str(text or "").strip()
    if not text:
        return {}
    if os.getenv("NARRATIVE_READER", "1") == "0":
        return None                     # switched off (the test suite runs offline)
    try:
        from config.settings import LLM_MODEL, groq_chat
        listing = "\n".join(f"- {k}: {v}" for k, v in _items().items())
        raw = await groq_chat(
            LLM_MODEL,
            [{"role": "system", "content": _SYSTEM},
             {"role": "user", "content": f"ITEMS:\n{listing}\n\nNARRATIVE:\n{text[:_MAX_TEXT_CHARS]}"}],
            temperature=0, max_tokens=2000, _retries=1,
        )
        m = re.search(r"\{.*\}", raw or "", re.S)
        reply = json.loads(m.group(0)) if m else None
    except Exception as exc:                                   # noqa: BLE001
        logger.info("narrative_reader: no reading (%s) - keywords only", exc)
        return None
    return gate_reply(reply, text)


def loss_stance(facts: Any, text: Any) -> Optional[str]:
    """"claims" / "no_claims" the stored reading of exactly `text` gives (a
    version-2 reading, one gated stance), else None."""
    reading = (facts or {}).get(READING_KEY) if isinstance(facts, dict) else None
    if not isinstance(reading, dict) or reading.get("text_hash") != text_hash(text) \
            or int(reading.get("version") or 1) < READER_VERSION:
        return None
    found = [k.split(":", 1)[1] for k in (reading.get("items") or {}) if k.startswith("loss:")]
    return found[0] if len(found) == 1 and found[0] in LOSS_STANCES else None


def credited(facts: Any, text: Any) -> Tuple[Set[str], Set[str]]:
    """(topic keys, depth keys) the stored reading credits for exactly `text`."""
    reading = (facts or {}).get(READING_KEY) if isinstance(facts, dict) else None
    if not isinstance(reading, dict) or reading.get("text_hash") != text_hash(text):
        return set(), set()
    items = reading.get("items") or {}
    topics = {k.split(":", 1)[1] for k in items if k.startswith("topic:")}
    depth = {k.split(":", 1)[1] for k in items if k.startswith("depth:")}
    return topics, depth
