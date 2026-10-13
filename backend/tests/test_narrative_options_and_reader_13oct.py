"""Owner, 13 Oct 2026: "user wont know what is happening ... can our system interpret their language ...
use multiselect options" - then: "fix these properly".

  1. The option IS the classification; a starter with nothing real after it (or "TBD") is no content -
     stripped before storing and scoring, refused in the window.
  2. One meaning-based reading of the saved narrative credits an item only with a word-for-word quote.
  3. The keyword pass stays first; the reading only adds. Off / failing = keywords alone.
Also: the fix window holds the page still while it scrolls.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

import services.narrative_reader as nr
from services.sqs_service import _calculate_narrative_quality, narrative_gap_options

_FRONT = Path(__file__).resolve().parents[2] / "frontend" / "src"

_BASE = ("Account overview: Choice Electric LLC is a family-owned electrical contractor in business since 2008. "
         "Loss history: loss free for five years. Risk controls: written safety program. Renewal of the "
         "program with the same umbrella limits. Annual revenue about $4.5M. Owners are licensed electricians.")


# ── 1. unfinished starters ───────────────────────────────────────────────────
@pytest.mark.parametrize("line,kept", [
    ("Scope of work: primarily ", False),
    ("Scope of work: primarily TBD", False),
    ("Scope of work: primarily -", False),
    ("Scope of work: primarily commercial remodels", True),
    ("Account Overview:", False),
    ("Account Overview: family-owned electrical contractor in Denver", True),
    ("Ownership: in business since 2008", True),
])
def test_an_unfinished_starter_is_not_content(line, kept):
    out = nr.strip_unfinished_starters(_BASE + "\n" + line)
    assert (line.strip() in out) is kept
    assert _BASE in out


def test_the_door_never_stores_an_unfinished_starter():
    import services.arq_service as arq
    stored = {}

    async def _get(_sid):
        return {"facts": {"additional_remarks_text": {"value": _BASE, "source": "producer"}}}

    async def _apply(_sid, field, value, **_k):
        stored[field] = value
        return True, []

    async def _noop(_sid):
        return None

    with patch("repositories.session_repository.get_processing_session", _get), \
         patch.object(arq, "apply_producer_answer_to_session", _apply), \
         patch.object(arq, "store_narrative_reading", _noop):
        assert asyncio.run(arq.append_producer_narrative("s", "Scope of work: primarily "))[0] is False
        assert asyncio.run(arq.append_producer_narrative(
            "s", "Scope of work: primarily commercial remodels\nCoverage requested: "))[0] is True
    assert stored["additional_remarks_text"].endswith("Scope of work: primarily commercial remodels")
    assert "Coverage requested" not in stored["additional_remarks_text"]


# ── 2. the meaning-based reading, evidence-gated ─────────────────────────────
def test_a_quote_not_in_the_text_credits_nothing():
    text = _BASE + " Most of our jobs are commercial remodels for property managers."
    reply = {"items": {
        "depth:specific_operations_detail": {"covered": True, "quote": "Most of our jobs are commercial remodels"},
        "topic:management": {"covered": True, "quote": "the owners have 30 years of experience"},   # invented
        "depth:loss_context": {"covered": True, "quote": "loss"},                                    # too short
        "topic:nonsense": {"covered": True, "quote": "Choice Electric LLC"},                         # unknown id
        "topic:operations": {"covered": False, "quote": "electrical contractor"},
    }}
    assert set(nr.gate_reply(reply, text)) == {"depth:specific_operations_detail"}


def test_a_paraphrase_is_credited_through_the_reading_only_for_that_text():
    from services.extraction_service import _narrative_remarks_text
    text = _BASE + " Most of our jobs are commercial remodels for property managers."
    facts = {"additional_remarks_text": {"value": text, "source": "producer"}}
    flags = {"has_workers_comp": False}
    score_kw, _c, sub_kw = _calculate_narrative_quality(facts, flags=flags)
    assert "The scope of work" in str(narrative_gap_options({}, _narrative_remarks_text(facts)))
    facts["_narrative_reading"] = {"text_hash": nr.text_hash(_narrative_remarks_text(facts)),
                                   "items": {"depth:specific_operations_detail": "Most of our jobs"}}
    score_ai, _c2, sub_ai = _calculate_narrative_quality(facts, flags=flags)
    assert sub_ai > sub_kw and score_ai >= score_kw
    # a different text (an edit, an undo) is a different reading
    facts["additional_remarks_text"]["value"] = text + " Extra."
    assert _calculate_narrative_quality(facts, flags=flags)[2] == sub_kw


def test_the_reading_is_stored_beside_the_text_it_read_and_never_fails_a_save():
    import services.arq_service as arq
    writes = []
    text = _BASE + " Most of our jobs are commercial remodels."

    async def _get(_sid):
        return {"facts": {"additional_remarks_text": {"value": text, "source": "producer"}}}

    async def _upd(_sid, updates, **_k):
        writes.append(updates)

    async def _read(_t):
        return {"depth:specific_operations_detail": "Most of our jobs"}

    async def _broken(_t):
        raise RuntimeError("network")

    with patch("repositories.session_repository.get_processing_session", _get), \
         patch("repositories.session_repository.upd_processing_session", _upd), \
         patch.object(nr, "read_narrative", _read):
        asyncio.run(arq.store_narrative_reading("s"))
    assert writes[0]["facts"]["_narrative_reading"]["text_hash"] == nr.text_hash(text)
    with patch("repositories.session_repository.get_processing_session", _get), \
         patch("repositories.session_repository.upd_processing_session", _upd), \
         patch.object(nr, "read_narrative", _broken):
        asyncio.run(arq.store_narrative_reading("s"))          # no raise
    assert len(writes) == 1


def test_switched_off_or_no_key_means_keywords_alone():
    with patch.dict(os.environ, {"NARRATIVE_READER": "0"}):
        assert asyncio.run(nr.read_narrative("anything at all")) is None


# ── 1 + scroll: the window ───────────────────────────────────────────────────
def test_the_window_refuses_an_unfinished_starter_and_holds_the_page(tmp_path):
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    gaps = [{"key": "depth:specific_operations_detail", "starter": "Scope of work: primarily "},
            {"key": "depth:coverage", "starter": "Coverage requested: "}]
    script = tmp_path / "t.mjs"
    script.write_text(f"""import * as P from {json.dumps((_FRONT / 'utils' / 'fixProgress.js').as_uri())};
const g = {json.dumps(gaps)};
console.log(JSON.stringify([
  P.unfinishedStarters("Intro.\\nScope of work: primarily ", g).map((x) => x.key),
  P.unfinishedStarters("Scope of work: primarily TBD", g).map((x) => x.key),
  P.unfinishedStarters("Scope of work: primarily commercial remodels\\nCoverage requested: same limits", g).length,
]));
""", encoding="utf-8")
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout) == [["depth:specific_operations_detail"], ["depth:specific_operations_detail"], 0]
    src = (_FRONT / "components" / "form" / "ResolutionModal.jsx").read_text(encoding="utf-8")
    assert "const open = unfinishedStarters(text, resolution.gaps);" in src
    # the page is held still and every wheel over the overlay stays in the window (owner, twice)
    assert "html.style.overflow = 'hidden';" in src and "body.style.overflow = 'hidden';" in src
    assert "el.addEventListener('wheel', onWheel, { passive: false });" in src
    assert "if (!card || !card.contains(e.target)) { e.preventDefault(); return; }" in src
    assert "<div ref={overlayRef} role=\"dialog\"" in src and "<div ref={cardRef} style={card}" in src
    assert src.count("overscrollBehavior: 'contain'") == 2


def test_the_count_says_what_it_is_made_of(tmp_path):
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    script = tmp_path / "c.mjs"
    script.write_text(f"""import * as R from {json.dumps((_FRONT / 'utils' / 'recommendations.js').as_uri())};
console.log(JSON.stringify([
  R.considerText({{ score: [1], forms: {{ count: 1 }}, count: 2 }}),
  R.considerText({{ score: [1, 2], forms: {{ count: 0 }}, count: 2 }}),
  R.considerText({{ score: [], forms: {{ count: 3 }}, count: 3 }}),
]));
""", encoding="utf-8")
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout) == ["1 to raise your score · 1 your forms need",
                                      "2 to raise your score", "3 your forms need"]
    rec = (_FRONT / "components" / "form" / "review" / "Recommendations.jsx").read_text(encoding="utf-8")
    # The forms group's badge also counts the form choices not yet ticked (13 Oct 2026,
    # the SQS without forms - "Add ACORD 25" is listed in this group).
    assert '{formsBadge > 0 && <span className="rec-count">{formsBadge}</span>}' in rec
    assert "const formsBadge = rec.forms.count + (formsExist ? 0 : (rec.choicesOpen || 0));" in rec
    byg = (_FRONT / "components" / "form" / "review" / "BeforeYouGenerate.jsx").read_text(encoding="utf-8")
    assert "status === DRY_RUN_READY && count > 0 && !bare && (" in byg


def test_a_reply_without_the_prefix_still_credits_its_items():
    """Measured on gpt-5.4-mini: the same prompt returned prefixed ids once and bare ids the next time."""
    text = "We wire offices. Every electrician goes through monthly safety meetings and arc-flash training."
    reply = {"items": {"risk_controls": {"covered": True, "quote": "monthly safety meetings and arc-flash training"},
                       "operations": {"covered": True, "quote": "We wire offices"}}}
    got = set(nr.gate_reply(reply, text))
    assert got == {"topic:risk_controls", "depth:risk_controls", "topic:operations"}
