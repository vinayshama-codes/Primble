"""arq_assistant_usage.py - how the client questionnaire's Form Assistant is used
(Brent's V2 list, "ARQ Bot usage tracking", 27 Oct 2026).

One row per use of `POST /api/arq/chat/{token}`: which questionnaire / package,
the question the client had open, when, the model's token counts, the latency,
and the outcome. NEVER the client's message or the assistant's reply - what a
client types into a help box is theirs, and the counts need none of it.

COST: no extra model call. The token counts are the ones OpenAI already returns
with the reply, handed back through `config.settings.LLM_USAGE_SINK`. One
INSERT per use, best-effort - a failed row never fails the chat.

OUTCOMES (Brent's three words):
  answered  the assistant replied
  refused   the request was turned away - the link had expired, the
            questionnaire was already submitted, or the assistant declined an
            out-of-scope ask (`detail` says which; the decline is read off the
            reply's first sentence by a deterministic pattern, so it is an
            approximate count)
  error     no answer: the model call failed or returned nothing usable
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

TABLE = "arq_assistant_usage"

OUTCOME_ANSWERED = "answered"
OUTCOME_REFUSED = "refused"
OUTCOME_ERROR = "error"
OUTCOMES = (OUTCOME_ANSWERED, OUTCOME_REFUSED, OUTCOME_ERROR)

DETAIL_OUT_OF_SCOPE = "out_of_scope"
DETAIL_LINK_EXPIRED = "link_expired"
DETAIL_ALREADY_SUBMITTED = "already_submitted"
DETAIL_EMPTY_REPLY = "empty_reply"
DETAIL_LLM_ERROR = "llm_error"

# The assistant declining, in its first sentence ("I can't recommend ...",
# "That's a question for your broker ..."). Counting only - never shown.
_DECLINE_RE = re.compile(
    r"\b(?:I\s+(?:can(?:no|')t|am\s+not\s+able\s+to|'m\s+not\s+able\s+to|"
    r"am\s+unable\s+to|'m\s+unable\s+to|won't)\s+(?:recommend|advise|tell\s+you\s+(?:whether|if|which))"
    r"|that(?:'s|\s+is)\s+(?:a\s+(?:question|decision)\s+for|your)\s+(?:your\s+)?broker)",
    re.IGNORECASE,
)
_FIRST_SENTENCE_RE = re.compile(r"^.*?(?:[.!?](?:\s|$)|$)", re.DOTALL)


def classify_reply(reply: Optional[str], fallback: str) -> tuple:
    """(outcome, detail) for what the chat route is about to send back."""
    text = (reply or "").strip()
    if not text or text == (fallback or "").strip():
        return OUTCOME_ERROR, DETAIL_EMPTY_REPLY
    first = (_FIRST_SENTENCE_RE.match(text) or None)
    head = first.group(0) if first else text[:200]
    if _DECLINE_RE.search(head[:300]):
        return OUTCOME_REFUSED, DETAIL_OUT_OF_SCOPE
    return OUTCOME_ANSWERED, None


def known_field(questions: Any, active_field: Optional[str]) -> Optional[str]:
    """The question id the client had open - only when it IS one of this
    questionnaire's questions, so nothing the browser invents is stored."""
    af = str(active_field or "").strip()
    if not af:
        return None
    for q in questions or []:
        if isinstance(q, dict) and str(q.get("field_name") or "") == af:
            return af[:200]
    return None


def sum_usage(entries: Optional[Iterable[dict]]) -> dict:
    out = {"prompt_tokens": 0, "completion_tokens": 0, "cached_tokens": 0}
    for e in entries or []:
        if not isinstance(e, dict):
            continue
        for k in out:
            try:
                out[k] += int(e.get(k) or 0)
            except (TypeError, ValueError):
                pass
    return out


async def record_use(*, arq: dict, field_name: Optional[str], outcome: str,
                     detail: Optional[str] = None, model: Optional[str] = None,
                     usage: Optional[dict] = None, latency_ms: int = 0) -> bool:
    """Append one use. Best-effort; never raises."""
    if outcome not in OUTCOMES or not isinstance(arq, dict) or not arq.get("id"):
        return False
    u = usage or {}
    try:
        from config.database import get_pool
        async with get_pool().acquire() as conn:
            await conn.execute(
                f"INSERT INTO {TABLE} (id, arq_id, session_id, user_id, field_name,"
                " outcome, detail, model, prompt_tokens, completion_tokens,"
                " cached_tokens, latency_ms, created_at)"
                " VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)",
                f"aau_{uuid.uuid4().hex}", str(arq["id"]),
                (str(arq.get("session_id")) if arq.get("session_id") else None),
                (str(arq.get("user_id")) if arq.get("user_id") else None),
                field_name, outcome, detail, (str(model)[:80] if model else None),
                int(u.get("prompt_tokens") or 0), int(u.get("completion_tokens") or 0),
                int(u.get("cached_tokens") or 0), max(0, int(latency_ms or 0)),
                datetime.now(timezone.utc).isoformat(),
            )
        return True
    except Exception as ex:                                    # noqa: BLE001
        logger.warning("assistant usage not recorded for arq %s: %s", arq.get("id"), ex)
        return False


def _empty_counts() -> dict:
    return {"uses": 0, OUTCOME_ANSWERED: 0, OUTCOME_REFUSED: 0, OUTCOME_ERROR: 0,
            "last_used_at": None}


async def counts_for_arqs(arq_ids: Iterable[str]) -> Dict[str, dict]:
    """{arq_id: {uses, answered, refused, error, last_used_at}} - the producer's
    per-questionnaire view. Missing ids get zeros. Never raises."""
    ids = sorted({str(a) for a in arq_ids or [] if a})
    out = {a: _empty_counts() for a in ids}
    if not ids:
        return out
    try:
        from config.database import get_pool
        async with get_pool().acquire() as conn:
            rows = await conn.fetch(
                f"SELECT arq_id, outcome, COUNT(*)::int AS n, MAX(created_at) AS last_at"
                f" FROM {TABLE} WHERE arq_id = ANY($1::text[]) GROUP BY arq_id, outcome",
                ids)
    except Exception as ex:                                    # noqa: BLE001
        logger.warning("assistant usage counts unavailable: %s", ex)
        return out
    for r in rows:
        c = out.setdefault(str(r["arq_id"]), _empty_counts())
        n = int(r["n"] or 0)
        c["uses"] += n
        if r["outcome"] in OUTCOMES:
            c[r["outcome"]] += n
        if r["last_at"] and (c["last_used_at"] is None or str(r["last_at"]) > str(c["last_used_at"])):
            c["last_used_at"] = str(r["last_at"])
    return out


async def package_usage(session_id: str) -> dict:
    """One package's totals (every questionnaire sent for it)."""
    total = _empty_counts()
    total.update({"prompt_tokens": 0, "completion_tokens": 0})
    try:
        from config.database import get_pool
        async with get_pool().acquire() as conn:
            rows = await conn.fetch(
                f"SELECT outcome, COUNT(*)::int AS n, COALESCE(SUM(prompt_tokens),0)::int AS pt,"
                f" COALESCE(SUM(completion_tokens),0)::int AS ct, MAX(created_at) AS last_at"
                f" FROM {TABLE} WHERE session_id = $1 GROUP BY outcome",
                str(session_id))
    except Exception as ex:                                    # noqa: BLE001
        logger.warning("assistant usage unavailable for %s: %s", session_id, ex)
        return total
    for r in rows:
        n = int(r["n"] or 0)
        total["uses"] += n
        if r["outcome"] in OUTCOMES:
            total[r["outcome"]] += n
        total["prompt_tokens"] += int(r["pt"] or 0)
        total["completion_tokens"] += int(r["ct"] or 0)
        if r["last_at"] and (total["last_used_at"] is None or str(r["last_at"]) > str(total["last_used_at"])):
            total["last_used_at"] = str(r["last_at"])
    return total


async def admin_summary(days: int = 30, top: int = 10) -> dict:
    """Usage across every account over the last `days` (admin only)."""
    days = max(1, min(int(days or 30), 3650))
    top = max(1, min(int(top or 10), 50))
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    from config.database import get_pool
    async with get_pool().acquire() as conn:
        totals = await conn.fetchrow(
            f"SELECT COUNT(*)::int AS uses,"
            f" COUNT(*) FILTER (WHERE outcome='answered')::int AS answered,"
            f" COUNT(*) FILTER (WHERE outcome='refused')::int AS refused,"
            f" COUNT(*) FILTER (WHERE outcome='error')::int AS error,"
            f" COUNT(DISTINCT arq_id)::int AS questionnaires,"
            f" COUNT(DISTINCT session_id)::int AS packages,"
            f" COALESCE(SUM(prompt_tokens),0)::bigint AS prompt_tokens,"
            f" COALESCE(SUM(completion_tokens),0)::bigint AS completion_tokens,"
            f" COALESCE(SUM(cached_tokens),0)::bigint AS cached_tokens,"
            f" COALESCE(ROUND(AVG(latency_ms)),0)::int AS avg_latency_ms,"
            f" COALESCE(MAX(latency_ms),0)::int AS max_latency_ms"
            f" FROM {TABLE} WHERE created_at >= $1", since)
        by_day = await conn.fetch(
            f"SELECT substr(created_at, 1, 10) AS day, COUNT(*)::int AS uses"
            f" FROM {TABLE} WHERE created_at >= $1 GROUP BY 1 ORDER BY 1", since)
        by_detail = await conn.fetch(
            f"SELECT outcome, COALESCE(detail, '') AS detail, COUNT(*)::int AS n"
            f" FROM {TABLE} WHERE created_at >= $1 GROUP BY 1, 2 ORDER BY 3 DESC", since)
        fields = await conn.fetch(
            f"SELECT field_name, COUNT(*)::int AS uses FROM {TABLE}"
            f" WHERE created_at >= $1 AND field_name IS NOT NULL"
            f" GROUP BY field_name ORDER BY uses DESC LIMIT $2", since, top)
        packages = await conn.fetch(
            f"SELECT a.session_id, a.user_id, u.email, COUNT(*)::int AS uses,"
            f" MAX(a.created_at) AS last_used_at"
            f" FROM {TABLE} a LEFT JOIN users u ON u.id = a.user_id"
            f" WHERE a.created_at >= $1 GROUP BY a.session_id, a.user_id, u.email"
            f" ORDER BY uses DESC LIMIT $2", since, top)
    t = dict(totals) if totals else {}
    return {
        "days": days,
        "since": since,
        "totals": {k: (int(v) if v is not None else 0) for k, v in t.items()},
        "by_day": [{"day": r["day"], "uses": int(r["uses"])} for r in by_day],
        "by_outcome_detail": [{"outcome": r["outcome"], "detail": r["detail"] or None,
                               "count": int(r["n"])} for r in by_detail],
        "top_fields": [{"field_name": r["field_name"], "uses": int(r["uses"])} for r in fields],
        "top_packages": [{"session_id": r["session_id"], "user_id": r["user_id"],
                          "owner_email": r["email"], "uses": int(r["uses"]),
                          "last_used_at": r["last_used_at"]} for r in packages],
    }
