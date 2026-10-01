"""Adversarial review of the needs-attention list (Orbin items 9 / 19), 30 Sep 2026.

Six findings, each fixed and pinned here:
  1. a box the producer typed into after generation stayed "Please verify" /
     "AI held back" (an edit keeps the old label so its highlight persists);
  2. an unanswered HIGH-IMPACT question the list does not name vanished from
     the download review (Figure 33: never bury a high-impact gap);
  3. an ACORD 125 "tick one of these" group became one Missing row per box;
  4. a signed form still asked for its signature;
  5. labels were cut at ACORD's mid-sentence double spaces ("The", "That");
  6. an ACORD 140 COPE gate box was listed twice (its hard-block row + Missing).
"""
from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

import services.field_qa as fq                                       # noqa: E402
import services.needs_attention as na                                # noqa: E402
import services.pdf_service as ps                                    # noqa: E402

FIXTURE = json.loads((BACKEND / "tests" / "fixtures" / "needs_attention_live_30sep.json").read_text())
SCHEMA_DIR = BACKEND / "forms_schemas"
SCHEMA_125 = json.loads((SCHEMA_DIR / "ACORD_125_schema.json").read_text())


def _live_125(tag="b8d6"):
    d = FIXTURE[tag]
    return copy.deepcopy(d["generated_forms"]["ACORD_125"]), d["facts"], d["flags"]


def _by_field(rows):
    return {r["field"]: r for r in rows}


# ── 1. A person's edit leaves the list ──────────────────────────────────────

def test_a_held_back_box_the_producer_filled_leaves_the_list():
    fr, facts, flags = _live_125()
    rows = na.needs_attention(fr, facts, "ACORD_125", flags=flags)
    held = [r for r in rows if r["status"] == na.STATUS_HELD_BACK and not r.get("box_count")]
    assert held, "the live run has held-back boxes"
    box = held[0]["field"]
    state = dict(fr.get("field_state") or fr.get("mapped") or {})
    fr["field_state"] = state
    fr.setdefault("mapped", {})
    state[box] = "Producer typed value"
    fr.setdefault("confidence", {})[box] = "low_confidence"     # an edit keeps the label
    after = _by_field(na.needs_attention(fr, facts, "ACORD_125", flags=flags))
    assert box not in after


def test_an_ai_value_still_asks_to_be_verified_until_edited():
    fr, facts, flags = _live_125()
    state = dict(fr.get("field_state") or fr.get("mapped") or {})
    mapped = dict(fr.get("mapped") or state)
    box = "NamedInsured_Primary_WebsiteAddress_A"
    if box not in SCHEMA_125:
        pytest.skip("box not on this template")
    mapped[box] = state[box] = "www.example.com"
    fr["mapped"], fr["field_state"] = mapped, state
    fr.setdefault("confidence", {})[box] = "low_confidence"
    rows = _by_field(na.needs_attention(fr, facts, "ACORD_125", flags=flags))
    assert rows[box]["status"] == na.STATUS_VERIFY                 # the AI's value
    state[box] = "www.orbin.example"                               # the producer's
    rows = _by_field(na.needs_attention(fr, facts, "ACORD_125", flags=flags))
    assert box not in rows


# ── 2. High-impact unanswered questions stay in the download review ─────────

def _qa(field="Vehicle_Question_ABCCode_A", form="ACORD_127"):
    return {"results": [{"reason_code": "not_answered", "high_impact": True, "form_id": form,
                         "field": field,
                         "message": "ACORD 127: this high-impact question was left blank by the AI."}]}


def test_an_unanswered_high_impact_question_is_never_buried():
    attention = {"forms": [{"form_id": "ACORD_127", "ok": True, "rows": []}]}
    rows = fq.to_recommendation_rows(_qa(), attention)
    assert any(r.get("component") == "ACORD_127" and "left blank by the AI" in (r.get("message") or "")
               for r in rows)
    kept = [r for r in rows if "left blank by the AI" in (r.get("message") or "")]
    assert not any(fq.row_superseded_by_attention(r) for r in kept)


def test_a_box_the_list_names_is_not_reported_twice():
    attention = {"forms": [{"form_id": "ACORD_127", "ok": True,
                            "rows": [{"field": "Vehicle_Question_ABCCode_A", "status": "ai_held_back",
                                      "label": "Question", "page": 2}]}]}
    rows = fq.to_recommendation_rows(_qa(), attention)
    assert not any("left blank by the AI" in (r.get("message") or "") for r in rows)


# ── 3. One row per "tick one of these" group on ACORD 125 ───────────────────

def test_a_tick_group_is_one_row():
    fr = {"mapped": {"NamedInsured_FullName_A": "ORBIN CONTRACTING LLC"}, "confidence": {},
          "schema": SCHEMA_125}
    rows = na.needs_attention(fr, {}, "ACORD_125")
    for set_name, label, _what in na._ACORD125_TICK_GROUPS:
        members = getattr(ps, set_name)
        in_group = [r for r in rows if r["field"] in members]
        assert len(in_group) <= 1, (set_name, [r["field"] for r in in_group])
        if in_group:
            assert in_group[0]["label"] == label
            assert in_group[0]["box_count"] >= 2
            assert in_group[0]["status"] == na.STATUS_MISSING


def test_a_ticked_group_is_not_listed_at_all():
    fr, facts, flags = _live_125()          # Orbin ticks its lines, entity and business type
    rows = na.needs_attention(fr, facts, "ACORD_125", flags=flags)
    for set_name, _label, _what in na._ACORD125_TICK_GROUPS:
        assert not [r for r in rows if r["field"] in getattr(ps, set_name)]


# ── 4. A signed form does not ask for its signature ─────────────────────────

def test_a_signed_form_does_not_ask_for_the_producers_signature():
    fr, facts, flags = _live_125()
    producer_box = "Producer_AuthorizedRepresentative_Signature_A"
    fr.setdefault("confidence", {})[producer_box] = "missing_required"
    before = _by_field(na.needs_attention(fr, facts, "ACORD_125", flags=flags))
    assert producer_box in before and not before[producer_box].get("applicant_step")
    assert "NamedInsured_Signature_A" in before
    fr["signature_applied"] = True
    after = _by_field(na.needs_attention(fr, facts, "ACORD_125", flags=flags))
    assert producer_box not in after                        # the producer signed it
    # The Sign button signs for the PRODUCER only (1 Oct 2026): the applicant's
    # signature and date stay listed - as the applicant's own step, never as a
    # box the producer is told to fill in.
    for f in na.VIEWER_ALWAYS_REQUIRED:
        assert after[f]["applicant_step"] is True, f
        assert not after[f].get("producer_todo"), f


# ── 5. Labels are whole sentences, on every form ────────────────────────────

_FRAGMENTS = {"the", "that", "an", "a", "an explanation of", "expiration date of the previous"}


def test_no_label_is_a_mid_sentence_fragment():
    bad = []
    for path in sorted(SCHEMA_DIR.glob("ACORD_*_schema.json")):
        schema = json.loads(path.read_text())
        for field in schema:
            label = na.box_label(schema, field)
            if label.strip().rstrip(".").lower() in _FRAGMENTS:
                bad.append((path.name, field, label))
    assert not bad, bad[:10]


# ── 6. A COPE gate box is named once, by its hard-block row ─────────────────

def test_a_gate_box_is_left_to_its_hard_block_row():
    fr = {"mapped": {}, "confidence": {"Policy_EffectiveDate_A": "missing_required_gate"}}
    rows = na.needs_attention(fr, {}, "ACORD_140")
    assert "Policy_EffectiveDate_A" not in _by_field(rows)
