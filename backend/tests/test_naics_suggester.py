"""Figure 20: business-specific NAICS / SIC suggestion candidates.

Guards the two properties that matter most:
  - a suggestion is DERIVED from the business, never a fixed example; and
  - a suggestion is never silently promoted into an answer.
"""

import pytest

from services import naics_suggester as ns


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def test_roofing_business_gets_roofing_code():
    picks = ns.suggestions_for("naics", "We install residential roofing and gutters in Austin.")
    assert picks, "a plainly described roofer must produce a candidate"
    assert picks[0]["code"] == "238160"
    assert picks[0]["confidence"] == "high"


def test_sic_kind_returns_sic_width_code():
    picks = ns.suggestions_for("sic", "We install residential roofing and gutters.")
    assert picks[0]["code"] == "1761"
    assert len(picks[0]["code"]) == 4


def test_naics_codes_are_six_digits():
    picks = ns.suggestions_for("naics", "commercial bakery producing bread wholesale")
    assert picks
    assert all(len(p["code"]) == 6 and p["code"].isdigit() for p in picks)


def test_a_bakery_is_never_told_it_is_a_roofer():
    """The exact defect from the client screenshot: one hard-coded example."""
    picks = ns.suggestions_for("naics", "We are a wholesale bakery producing bread and pastry.")
    assert picks
    assert all(p["code"] != "238160" for p in picks)


def test_different_businesses_get_different_answers():
    roof = ns.suggestions_for("naics", "roofing contractor, shingle replacement")
    law  = ns.suggestions_for("naics", "we are a law firm, attorneys practicing litigation")
    assert roof and law
    assert roof[0]["code"] != law[0]["code"]


def test_unrecognized_business_yields_no_suggestion():
    """No match must mean silence, never a guess (blank over wrong)."""
    assert ns.suggestions_for("naics", "zzzq wibblefrotz interdimensional widgets") == []


def test_empty_and_garbage_input_are_safe():
    for bad in ("", "   ", None, 12345, "!!!! ??? ***"):
        assert ns.suggestions_for("naics", bad) == []


def test_legal_entity_words_alone_do_not_match():
    """'Acme Holdings LLC' describes nothing - it must not score."""
    assert ns.suggestions_for("naics", "Acme Holdings LLC, Inc, Corporation") == []


def test_business_name_alone_can_match_a_trade():
    picks = ns.suggestions_for("naics", "Statewide Roofing LLC")
    assert picks and picks[0]["code"] == "238160"


def test_generic_words_only_produce_low_confidence():
    """'contractor' alone is a weak keyword: shown, but never as a likely match."""
    picks = ns.suggestions_for("naics", "we are a contractor doing general work")
    for p in picks:
        assert p["confidence"] in ("low", "medium")
        assert p["confidence"] != "high"


def test_at_most_three_suggestions():
    picks = ns.suggestions_for("naics", "construction contractor concrete masonry roofing plumbing electrical painting")
    assert len(picks) <= 3


def test_confidence_is_always_a_known_value():
    picks = ns.suggestions_for("naics", "auto repair mechanic shop brakes oil change")
    assert picks
    assert all(p["confidence"] in ("high", "medium", "low") for p in picks)


def test_substring_does_not_falsely_match():
    """'bar' must not fire on 'barge' or 'barrier' - whole words only."""
    picks = ns.suggestions_for("naics", "we manufacture barrier systems and barge components")
    assert all("Bar or drinking" not in p["label"] for p in picks)


# ---------------------------------------------------------------------------
# Negation
#
# Found in live testing: a full-service restaurant picked up a phantom "Bar or
# drinking establishment" candidate purely from the sentence disclaiming one
# ("There is no nightclub, no dance floor..."). Insurance applications describe
# a risk as much by what it excludes as by what it does.
# ---------------------------------------------------------------------------

def test_negated_noun_does_not_create_a_candidate():
    text = ("The applicant operates a full service restaurant with table service. "
            "There is no nightclub, no dance floor, and no live entertainment.")
    picks = ns.suggestions_for("naics", text)
    assert picks and picks[0]["code"] == "722511"
    assert all("Bar or drinking" not in p["label"] for p in picks)


def test_negation_does_not_suppress_the_real_trade():
    """Doc A style: real trade plus several exclusionary sentences."""
    text = ("The applicant installs and replaces residential roofing systems. "
            "No manufacturing is performed. No work is performed above three stories.")
    picks = ns.suggestions_for("naics", text)
    assert picks and picks[0]["code"] == "238160"
    assert picks[0]["confidence"] == "high"


def test_a_genuine_bar_still_matches():
    """The negation guard must not make positive evidence unreachable."""
    picks = ns.suggestions_for("naics", "operates a neighborhood bar and cocktail lounge serving liquor")
    assert picks and picks[0]["code"] == "722410"
    assert picks[0]["confidence"] == "high"


def test_negation_is_clause_scoped_not_sentence_scoped():
    """A positive clause beside a negated one must survive."""
    picks = ns.suggestions_for("naics", "we do commercial roofing, no residential work")
    assert picks and picks[0]["code"] == "238160"


def test_stacked_negations_in_one_sentence_all_drop():
    text = "General office operations. No auto repair, no body shop, no machine shop on premises."
    picks = ns.suggestions_for("naics", text)
    assert all(p["label"] not in
               ("Automotive repair and maintenance", "Automotive body and paint shop", "Machine shop")
               for p in picks)


def test_negation_helper_keeps_positive_clauses():
    kept = ns._strip_negated_clauses("We install roofing. There is no nightclub.")
    assert "roofing" in kept.lower()
    assert "nightclub" not in kept.lower()


def test_negation_helper_is_safe_on_junk():
    for bad in ("", None, "   ", ",,,,", "no"):
        assert isinstance(ns._strip_negated_clauses(bad), str)


# ---------------------------------------------------------------------------
# Fact assembly
# ---------------------------------------------------------------------------

def _fv(facts, key):
    v = facts.get(key)
    if isinstance(v, dict) and "value" in v:
        v = v.get("value")
    return v


def test_business_text_reads_fact_envelopes():
    facts = {"operations_description": {"value": "commercial plumbing contractor"}}
    text = ns.business_text_from_facts(facts, _fv)
    assert "plumbing" in text.lower()
    assert ns.suggestions_for("naics", text)[0]["code"] == "238220"


def test_business_text_survives_missing_and_malformed_facts():
    for bad in ({}, None, {"operations_description": None}, {"operations_description": {}}):
        assert ns.business_text_from_facts(bad, _fv) == "" or isinstance(
            ns.business_text_from_facts(bad, _fv), str
        )


def test_business_text_falls_back_to_secondary_descriptions():
    """Thin main description, real trade wording in the WC blurb."""
    facts = {
        "operations_description": "services",
        "wc_description_of_operations": "electrician performing commercial wiring",
    }
    picks = ns.suggestions_for("naics", ns.business_text_from_facts(facts, _fv))
    assert picks and picks[0]["code"] == "238210"


# ---------------------------------------------------------------------------
# Hint copy
# ---------------------------------------------------------------------------

def test_hint_names_the_detected_business_code():
    hint = ns.hint_for("naics", ns.suggest("residential roofing contractor"))
    assert hint and "238160" in hint


def test_hint_always_offers_the_blank_escape_hatch():
    """The client explicitly praised 'you can leave it blank'. Never lose it."""
    hint = ns.hint_for("naics", ns.suggest("residential roofing contractor"))
    assert "blank" in hint.lower()


def test_hint_marks_the_code_as_unconfirmed():
    hint = ns.hint_for("naics", ns.suggest("residential roofing contractor"))
    assert "suggestion" in hint.lower()
    assert "confirm" in hint.lower()


def test_hint_has_no_em_dash():
    """Project UI copy rule: hyphen-minus only."""
    hint = ns.hint_for("naics", ns.suggest("residential roofing contractor"))
    assert "—" not in hint


def test_no_suggestion_means_no_hint_override():
    assert ns.hint_for("naics", []) is None


# ---------------------------------------------------------------------------
# Wiring into question generation
# ---------------------------------------------------------------------------

@pytest.fixture
def suggestions_on(monkeypatch):
    """Turn the V1 kill switch back on for the tests that prove the machinery.

    C3 3.13 (2026-08-25) made `ENABLE_CLASSIFICATION_SUGGESTIONS` default OFF -
    "do not generate a classification recommendation in V1", with classification
    assistance deferred to Section 19. The enrichment itself must keep working,
    or Section 19 inherits dead code, so these tests flip the flag rather than
    being deleted.
    """
    import config.settings as _settings
    monkeypatch.setattr(_settings, "ENABLE_CLASSIFICATION_SUGGESTIONS", True,
                        raising=False)
    return True


def test_suggestions_are_off_by_default_in_v1():
    """C3 3.13: no classification recommendation is generated in V1.

    Verified with the flag at its shipped default, so this fails the build if
    someone flips it on without a product decision.
    """
    from config.settings import ENABLE_CLASSIFICATION_SUGGESTIONS
    from services.arq_service import _attach_classification_suggestions
    assert ENABLE_CLASSIFICATION_SUGGESTIONS is False, (
        "C3 3.13 defers classification assistance to Section 19"
    )
    qs = [{"field_name": "naics_code", "question": "NAICS?", "hint": "old hint"}]
    _attach_classification_suggestions(
        qs, {"operations_description": "residential roofing contractor"})
    assert "suggestions" not in qs[0], "no candidates may be generated in V1"
    assert qs[0]["hint"] == "old hint", "the hint must not be rewritten either"


def test_attach_enriches_naics_question(suggestions_on):
    from services.arq_service import _attach_classification_suggestions
    qs = [{"field_name": "naics_code", "question": "NAICS?", "hint": "old hint"}]
    _attach_classification_suggestions(qs, {"operations_description": "residential roofing contractor"})
    assert qs[0]["suggestions"][0]["code"] == "238160"
    assert "238160" in qs[0]["hint"]


def test_attach_resolves_via_canonical_key(suggestions_on):
    from services.arq_service import _attach_classification_suggestions
    qs = [{"field_name": "ACORD_125_x", "_canonical_key": "sic_code", "question": "SIC?", "hint": "h"}]
    _attach_classification_suggestions(qs, {"operations_description": "residential roofing contractor"})
    assert qs[0]["suggestions"][0]["code"] == "1761"


def test_attach_never_writes_an_answer():
    """The whole safety property: enrichment must not fill anything."""
    from services.arq_service import _attach_classification_suggestions
    qs = [{"field_name": "naics_code", "question": "NAICS?", "hint": "h"}]
    _attach_classification_suggestions(qs, {"operations_description": "residential roofing contractor"})
    for banned in ("current_value", "value", "answer", "default"):
        assert banned not in qs[0]


def test_attach_leaves_unrelated_questions_untouched():
    from services.arq_service import _attach_classification_suggestions
    qs = [
        {"field_name": "applicant_name", "question": "Name?", "hint": "orig"},
        {"field_name": "annual_revenue", "question": "Revenue?", "hint": "orig2"},
    ]
    before = [dict(q) for q in qs]
    _attach_classification_suggestions(qs, {"operations_description": "residential roofing contractor"})
    assert qs == before


def test_attach_keeps_original_hint_when_business_is_unknown():
    from services.arq_service import _attach_classification_suggestions
    qs = [{"field_name": "naics_code", "question": "NAICS?", "hint": "original fallback"}]
    _attach_classification_suggestions(qs, {"operations_description": "zzzq wibblefrotz"})
    assert qs[0]["hint"] == "original fallback"
    assert "suggestions" not in qs[0]


def test_attach_is_safe_with_no_facts():
    from services.arq_service import _attach_classification_suggestions
    qs = [{"field_name": "naics_code", "question": "NAICS?", "hint": "h"}]
    for bad in ({}, None):
        _attach_classification_suggestions(qs, bad)
        assert qs[0]["hint"] == "h"


def test_attach_is_safe_with_empty_question_list():
    from services.arq_service import _attach_classification_suggestions
    _attach_classification_suggestions([], {"operations_description": "roofing"})


# ---------------------------------------------------------------------------
# Assistant prompt exposure
# ---------------------------------------------------------------------------

def test_assistant_field_block_carries_suggestions_as_unconfirmed():
    from routes.arq_routes import _assistant_field_block
    block = _assistant_field_block({
        "question": "Do you know your NAICS code?",
        "field_name": "naics_code",
        "field_type": "code",
        "code_digits": 6,
        "suggestions": [{"code": "238160", "label": "Roofing contractor", "confidence": "high"}],
    })
    assert "238160" in block
    assert "NOT confirmed" in block
    assert "agent" in block


# ---------------------------------------------------------------------------
# Serialization chain
#
# The chips failed in live testing even though generation was correct: the
# personalized hint survived (a plain string on the entry dict) while the
# candidates were dropped by the send-time whitelist, so nothing was ever
# stored and the client had nothing to render. These guard every hop.
# ---------------------------------------------------------------------------

def test_suggestion_sanitizer_keeps_valid_candidates():
    from routes.arq_routes import _sanitize_suggestions
    out = _sanitize_suggestions([{"code": "238160", "label": "Roofing contractor", "confidence": "high"}])
    assert out == [{"code": "238160", "label": "Roofing contractor", "confidence": "high"}]


def test_suggestion_sanitizer_rejects_junk():
    from routes.arq_routes import _sanitize_suggestions
    for bad in (None, [], "238160", {}, [None], ["x"], [{"label": "no code"}], [{"code": "  "}]):
        assert _sanitize_suggestions(bad) == []


def test_suggestion_sanitizer_downgrades_unknown_confidence():
    from routes.arq_routes import _sanitize_suggestions
    out = _sanitize_suggestions([{"code": "238160", "label": "R", "confidence": "certain"}])
    assert out[0]["confidence"] == "low"


def test_suggestion_sanitizer_strips_markup_and_caps_length():
    from routes.arq_routes import _sanitize_suggestions
    out = _sanitize_suggestions([{
        "code": "<b>238160</b>", "label": "<script>x</script>Roofing", "confidence": "high",
    }])
    assert "<" not in out[0]["code"] and "<" not in out[0]["label"]


def test_suggestion_sanitizer_caps_at_three():
    from routes.arq_routes import _sanitize_suggestions
    out = _sanitize_suggestions([{"code": str(100000 + i), "label": "x", "confidence": "low"} for i in range(9)])
    assert len(out) == 3


def test_both_question_serializers_preserve_suggestions():
    """The exact defect: send_arq dropped `suggestions` while keeping `hint`.

    Reads the two serializer bodies and asserts each one routes the key through
    the shared sanitizer. A source-level check is crude, but these builders are
    inline in async DB-backed routes, and the alternative - passing only when
    both are hand-inspected - is what let the bug ship in the first place.
    """
    import inspect
    from routes import arq_routes

    for fn in (arq_routes.send_arq, arq_routes.client_view):
        body = inspect.getsource(fn)
        assert '"hint"' in body, f"{fn.__name__}: expected a hint key to compare against"
        assert "_sanitize_suggestions(" in body, (
            f"{fn.__name__} does not carry `suggestions` through to the client. "
            "Every question serializer between generation and the questionnaire "
            "must preserve it, or the chips silently vanish while the hint stays."
        )


def test_assistant_field_block_unchanged_without_suggestions():
    from routes.arq_routes import _assistant_field_block
    block = _assistant_field_block({
        "question": "What is your legal business name?",
        "field_name": "applicant_name",
        "field_type": "text",
    })
    assert "SUGGESTION" not in block.upper()
