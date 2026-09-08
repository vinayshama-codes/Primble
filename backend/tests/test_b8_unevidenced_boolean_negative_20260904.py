"""B8 - a two-way boolean's `false` is SILENCE, not "No".

Found by the SYS-07 live test kit, run 1 (2026-09-04). NOT SYS-07, and NOT
caused by it - verified: before SYS-07 `cyber_controls_mfa` resolved to
KIND_TEXT and `compare("True", "False")` returned `conflict` there too.

WHAT THE PRODUCER SAW
    Cyber Controls Mfa       "True" (dec page)  vs  "False" (certificate)
    Cyber Controls Backups   "True" (dec page)  vs  "False" (certificate)

The certificate never mentions multi-factor authentication or backups at all.
Extraction manufactured a negative out of silence and the picker reported two
"documents disagree" cards - V1 core principle 3, *"Missing does not mean No"*,
inverted, plus an 85 cap for a package with nothing wrong with it.

WHY THE EXISTING GUARD DID NOT FIRE
    LLM call 1 declares a boolean fact one of two ways:
      `boolean or null`  -> the model is TOLD to answer null when the document
                            is silent, so a `false` is a real No
                            (`TRISTATE_BOOLEAN_FACTS`)
      bare `boolean`     -> the model cannot say "not mentioned", so a `false`
                            is indistinguishable from silence  <- B8
    The protection for the second case was `isinstance(v, bool)` in
    `_auto_scalar_keys` - a TYPE test. The model returned the STRINGS
    "True" / "False", so it never applied.

    A GUARD KEYED ON A TYPE IS ONLY AS GOOD AS THE MODEL'S WILLINGNESS TO
    HONOUR THAT TYPE. The rule is now keyed on the DECLARATION plus the VALUE.

OWNER'S RULING (live run 1)
    "if any document indicates yes or no and there is nothing related mentioned
     in another doc then take yes/no from that doc, but if there is a conflict
     then show"

    So the negatives are dropped ONLY when some document actually answered. If
    every document is silent, nothing changes - which is what keeps the blast
    radius at zero for every fact that merges to `false` today.
"""
import pytest

from services import fact_comparison as fc
from services.extraction_service import (
    BOOLEAN_FACT_KEYS, TRISTATE_BOOLEAN_FACTS, _merge_list_fields,
    unevidenced_boolean_negative as U,
)
from services.underwriting_consistency import (
    assess_underwriting_consistency, _auto_scalar_keys,
)

_DEC = "A1_package_policy_words.pdf"
_CERT = "A2_certificate_marks.pdf"


def _docs(dec_value, cert_value, key="cyber_controls_mfa"):
    return [
        {"doc_id": "1", "filename": _DEC, "doc_type": "policy", "text": "",
         "facts": {"applicant_name": "Northgate Provisions Group LLC",
                   key: dec_value}},
        {"doc_id": "2", "filename": _CERT, "doc_type": "certificate", "text": "",
         "facts": {"applicant_name": "Northgate Provisions Group LLC",
                   key: cert_value}},
    ]


def _cards(dec_value, cert_value, key="cyber_controls_mfa"):
    docs = _docs(dec_value, cert_value, key)
    res = assess_underwriting_consistency(docs, dict(docs[0]["facts"]), {})
    return [(f["fact_key"], [v["display"] for v in f["values"]])
            for f in res["fields"] if f.get("review_required")]


# ─────────────────────────────────────────────────────────────────────────────
# The reported cards
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("key", ["cyber_controls_mfa", "cyber_controls_backups"])
@pytest.mark.parametrize("cert_value", ["False", "false", "FALSE", False, "N", "no", "0"])
def test_the_live_run_cards_are_gone(key, cert_value):
    """MUST NEVER FAIL: run 1's literal pair, through the real picker."""
    assert _cards("True", cert_value, key) == []


def test_the_silent_documents_negative_is_not_even_a_candidate_key():
    keys = _auto_scalar_keys(_docs("True", "False"), exclude=set())
    assert "cyber_controls_mfa" not in keys or _cards("True", "False") == []
    # A key whose ONLY appearance is an unevidenced negative never opens a row.
    assert "cyber_controls_mfa" not in _auto_scalar_keys(
        _docs("False", "False"), exclude=set())


# ─────────────────────────────────────────────────────────────────────────────
# What must NOT change - the rule is narrow by construction
# ─────────────────────────────────────────────────────────────────────────────

def test_a_tri_state_false_is_a_real_no_and_still_conflicts():
    """`boolean or null` means the model COULD have said "not addressed" and
    chose `false` instead. That is the document saying No, and principle 4 says
    a real disagreement stays visible."""
    assert "additional_insured_required" in TRISTATE_BOOLEAN_FACTS
    assert not U("additional_insured_required", "False")
    assert _cards("True", "False", "additional_insured_required") == [
        ("additional_insured_required", ["True", "False"])]


def test_an_affirmative_is_always_evidence():
    for v in ("True", True, "Yes", "X", "1"):
        assert not U("cyber_controls_mfa", v)


def test_a_fact_that_is_not_a_declared_boolean_is_untouched():
    """`auto_hired_nonowned` is `string or null` - its "No" is a real answer."""
    assert not U("auto_hired_nonowned", "No")
    assert not U("applicant_name", "No")
    assert not U("", "No")
    assert not U("some_key_no_schema_declares", "No")
    assert _cards("Yes", "No", "auto_hired_nonowned") == [
        ("auto_hired_nonowned", ["Yes", "No"])]


def test_the_declaration_sets_are_derived_and_disjoint_in_the_right_direction():
    assert TRISTATE_BOOLEAN_FACTS <= BOOLEAN_FACT_KEYS
    assert len(BOOLEAN_FACT_KEYS) > len(TRISTATE_BOOLEAN_FACTS) > 0
    # Nothing hand-listed: every key comes from LLM call 1's own schema string.
    assert "cyber_controls_mfa" in BOOLEAN_FACT_KEYS
    assert "cyber_controls_mfa" not in TRISTATE_BOOLEAN_FACTS


def test_one_door_for_both_the_picker_and_the_merge():
    from services.underwriting_consistency import unevidenced_boolean_negative as _uc
    assert _uc("cyber_controls_mfa", "False") is True
    assert _uc("additional_insured_required", "False") is False


# ─────────────────────────────────────────────────────────────────────────────
# The merge half - the picker retiring the question is not enough on its own
# ─────────────────────────────────────────────────────────────────────────────

def _merge(*fact_dicts):
    return _merge_list_fields(
        [{"_chunk_idx": i, "facts": f, "flags": {}}
         for i, f in enumerate(fact_dicts)], [])["facts"]


def test_the_document_that_answered_wins_the_merge():
    """Without this the picker would correctly stop ASKING while the merge
    still ELECTED the silent document's false and stamped "No" on the form -
    the question retired and the wrong answer kept."""
    assert _merge({"cyber_controls_mfa": "True"},
                  {"cyber_controls_mfa": "False"})["cyber_controls_mfa"] == "True"


def test_the_answer_wins_however_many_silent_chunks_repeat_the_false():
    """The merge scores on frequency, so silence repeated three times used to
    out-vote the one document that answered."""
    merged = _merge({"cyber_controls_mfa": "False"},
                    {"cyber_controls_mfa": "False"},
                    {"cyber_controls_mfa": "False"},
                    {"cyber_controls_mfa": "True"})
    assert merged["cyber_controls_mfa"] == "True"


def test_when_every_document_is_silent_nothing_changes_at_all():
    """THE BLAST-RADIUS ARGUMENT. A fact that merges to `false` today still
    merges to `false`, so no stamped box, no flag and no score moves. The rule
    only ever settles a CONTEST between an answer and a silence."""
    assert _merge({"cyber_controls_mfa": "False"},
                  {"cyber_controls_mfa": "False"})["cyber_controls_mfa"] == "False"
    assert _merge({"cyber_controls_mfa": False},
                  {"cyber_controls_mfa": False})["cyber_controls_mfa"] is False


def test_the_merge_leaves_a_tri_state_contest_alone():
    merged = _merge({"additional_insured_required": "True"},
                    {"additional_insured_required": "False"})
    assert merged["additional_insured_required"] == "True"
    assert "False" in (merged.get("_merge_rejected") or {}).get(
        "additional_insured_required", []), (
        "the loser must survive as a rejected candidate so the picker can "
        "still raise the real disagreement")


def test_the_merge_leaves_a_real_yes_no_string_fact_alone():
    merged = _merge({"auto_hired_nonowned": "Yes"},
                    {"auto_hired_nonowned": "No"})
    assert "No" in (merged.get("_merge_rejected") or {}).get(
        "auto_hired_nonowned", [])


def test_ordinary_facts_are_completely_untouched():
    assert _merge({"applicant_name": "Acme Contracting LLC"},
                  {"applicant_name": "Acme Contracting LLC"}
                  )["applicant_name"] == "Acme Contracting LLC"
    assert _merge({"gl_each_occurrence": "$1,000,000"},
                  {"gl_each_occurrence": "$1,000,000"}
                  )["gl_each_occurrence"] == "$1,000,000"
