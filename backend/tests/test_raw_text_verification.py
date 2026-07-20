"""
Regression tests for the no-LLM raw-text verification (Figure 26 trust check).

Every value the AI fills is confirmed against the actual uploaded document text:
  * found    -> "ai_verified" -> pink  (AI-OK)
  * not found -> "low_confidence" -> orange (Verify)

The check runs on the PRE-canonicalization value, so display formatting never
breaks the match. Matching is punctuation/case/whitespace-insensitive with a
word-subset fallback, and is deliberately biased AWAY from false "not found"
flags. Yes/No answers and very short values are not verifiable by presence.

Run from backend/:
    python -m pytest tests/test_raw_text_verification.py -v
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.pdf_service import _normalize_for_search, _value_in_raw_text  # noqa: E402
from services.field_qa import run_field_qa  # noqa: E402

# The exact declarations text from the live test documents.
_DOC = (
    "COMMERCIAL PACKAGE DECLARATIONS\n"
    "Named Insured: Cobalt Ridge Manufacturing, LLC\n"
    "Mailing Address: 7740 Foundry Lane, Suite 310, Aurora, Colorado 80011-2245\n"
    "Producer: Northgate Risk Partners\n"
    "Producer Address: 1500 Market Street, Suite 800, Denver, Colorado 80202\n"
    "Annual Gross Sales: $6,150,000\n"
    "Policy Effective Date: 4/1/2026\n"
)
_HAY = _normalize_for_search(_DOC)


# ── Presence check ────────────────────────────────────────────────────────────

def test_verbatim_value_is_found():
    assert _value_in_raw_text("Northgate Risk Partners", _HAY) is True
    assert _value_in_raw_text("1500 Market Street, Suite 800", _HAY) is True


def test_reformatted_value_still_found():
    # Formatting differences must not break the match (this is the whole point).
    # The check runs on the AI's PRE-canonicalization value, which keeps the
    # document's own grouping/punctuation, so these all resolve to a match.
    assert _value_in_raw_text("$6,150,000", _HAY) is True    # currency punctuation
    assert _value_in_raw_text("80011-2245", _HAY) is True    # zip+4 with dash
    assert _value_in_raw_text("4/1/2026", _HAY) is True       # date slashes


def test_absent_value_is_not_found():
    # A value that is NOT in the documents (a guess / possible hallucination).
    assert _value_in_raw_text("Acme Insurance Company", _HAY) is False
    assert _value_in_raw_text("1000 Elsewhere Blvd", _HAY) is False


def test_yes_no_and_short_values_are_not_verifiable():
    # Reasoned-out answers and tiny tokens are never painted "verified".
    for v in ("Yes", "No", "N/A", "CO", "LLC", "X", ""):
        assert _value_in_raw_text(v, _HAY) is False


def test_word_subset_handles_reordering():
    # All significant tokens present, different order -> still found.
    assert _value_in_raw_text("Cobalt Manufacturing Ridge", _HAY) is True


def test_wrong_number_is_not_silently_verified():
    # A hallucinated suite number must NOT pass as verified (guards against the
    # word-subset fallback being too loose).
    assert _value_in_raw_text("1500 Market Street, Suite 999", _HAY) is False


# ── field_qa treats a verified AI value as a pass ─────────────────────────────

def test_field_qa_counts_ai_verified_as_pass():
    gen = {"ACORD_125": {"confidence": {"Producer_FullName_A": "ai_verified"},
                          "mapped": {"Producer_FullName_A": "Northgate Risk Partners"},
                          "schema": {}}}
    r = run_field_qa(gen, merged_facts={})
    assert r["pass_count"] == 1
    assert r["review_count"] == 0 and r["fail_count"] == 0
    assert r["results"] == []  # a pass is counted, never listed as an action item


# ── Evidence gate: keep reworded-but-present explanations, drop invented ones ──
# The evidence gate (Figure 30) blanks "…Explanation" narrative fields the LLM
# did not flag as verbatim. It used to trust ONLY the LLM's self-report, so a
# real answer the LLM lightly reworded (and didn't flag) was deleted even though
# it was in the dec pages. It now also spares any value our independent text
# search confirms is actually present in the documents.

def _fill_explanation(value, raw):
    import config.settings as settings
    settings.ENABLE_EVIDENCE_GATED_FILL = True
    from services.pdf_service import map_facts_to_form
    field = "CommercialPolicy_DemolitionExplanation_A"
    schema = {field: {"required": False}}
    pre = {"filled_values": {field: value}, "raw_text_fields": set()}  # NOT flagged verbatim
    mapped, _ = map_facts_to_form(facts={}, schema=schema, form_id="ACORD_125",
                                  raw_text=raw, pre_filled_gpt=pre)
    return mapped.get(field)


def test_evidence_gate_keeps_explanation_present_in_docs():
    # Value IS in the documents (lightly reworded), LLM did not flag it verbatim.
    raw = "Operations include selective interior demolition and concrete cutting on site."
    kept = _fill_explanation("selective interior demolition and concrete cutting", raw)
    assert kept  # NOT deleted - the real answer survives


def test_evidence_gate_still_drops_invented_explanation():
    # Value is NOT anywhere in the documents (AI-invented prose) -> still dropped.
    raw = "Operations include metal stamping and fabrication of small parts."
    out = _fill_explanation("The applicant performs extensive demolition of high-rise towers", raw)
    assert out is None  # invented prose is still removed - protection intact


# ── Evidence gate now also covers OtherDescription / ResolutionDescription ────
# (was "Explanation" substring only - the client requirement says "yes/no
# questions" broadly, and these are the same shape of field under a different
# ACORD naming suffix).

def test_evidence_required_field_detection_is_broadened():
    from services.pdf_service import _is_evidence_required_field
    assert _is_evidence_required_field("CommercialPolicy_DemolitionExplanation_A")
    assert _is_evidence_required_field("BusinessInformation_BusinessType_OtherDescription_A")
    assert _is_evidence_required_field("CommercialPolicy_JudgementOrLien_ResolutionDescription_A")
    # A core content field must NOT be swept in - it isn't a Yes/No
    # justification, and gating it would wrongly blank legitimate data.
    assert not _is_evidence_required_field("BuildingOccupancy_OperationsDescription_A")
    assert not _is_evidence_required_field("AdditionalInterest_ItemDescription_A")


def _fill_question_and_explanation(question_value, explanation_value, raw):
    import config.settings as settings
    settings.ENABLE_EVIDENCE_GATED_FILL = True
    from services.pdf_service import map_facts_to_form
    q_field = "CommercialPolicy_Question_ABCCode_A"
    exp_field = "CommercialPolicy_AnyExposureToFlammableExplosivesChemicalsExplanation_A"
    # Dict order matters: the schema convention is question immediately
    # followed by its own explanation - see _question_explanation_pairs.
    schema = {q_field: {"required": False}, exp_field: {"required": False}}
    pre = {
        "filled_values": {q_field: question_value, exp_field: explanation_value},
        "raw_text_fields": set(),  # neither flagged verbatim
    }
    mapped, _ = map_facts_to_form(facts={}, schema=schema, form_id="ACORD_125",
                                  raw_text=raw, pre_filled_gpt=pre)
    return mapped.get(q_field), mapped.get(exp_field)


def test_evidence_gate_cascades_blank_to_ungrounded_yes_answer():
    # The LLM checked "Yes" and invented an explanation with zero basis in the
    # uploaded documents. Gating the explanation alone would leave a bare,
    # unexplained "Yes" stamped - the cascade blanks the Yes too.
    raw = "Operations include metal stamping and fabrication of small parts."
    q_val, exp_val = _fill_question_and_explanation(
        "Yes", "Extensive on-site storage of flammable industrial solvents", raw)
    assert exp_val is None
    assert q_val is None


def test_evidence_gate_keeps_yes_when_explanation_is_grounded():
    # Explanation IS in the documents (reworded) - neither field is touched.
    raw = "The facility stores flammable solvents used in the finishing process on site."
    q_val, exp_val = _fill_question_and_explanation(
        "Yes", "flammable solvents on site", raw)
    assert exp_val is not None
    assert q_val == "Yes"


def test_evidence_gate_blanks_ungrounded_no_answer():
    # Tightened 2026-07-12 (found via a live test): the cascade only ever
    # policed AFFIRMATIVE answers, so an AI-inferred "No" the model defaulted
    # to purely because a topic was never mentioned - not because the
    # document said anything negative - slipped through with zero
    # protection. A "No" has no paired Explanation to check groundedness
    # against (only "Yes" responses get explained), so there is no
    # independent way to confirm it's real rather than assumed from silence -
    # it is never kept when AI-inferred, matching the identical policy
    # already applied to an unverifiable "Yes".
    raw = "Operations include metal stamping and fabrication of small parts."
    q_val, exp_val = _fill_question_and_explanation(
        "No", "Extensive on-site storage of flammable industrial solvents", raw)
    assert exp_val is None
    assert q_val is None


# ── Two gaps found via a live ACORD 126 test (2026-07-11) ─────────────────
# The ORIGINAL cascade only fired for an explanation that was filled by the
# LLM and THEN proven fake. A live test surfaced two ways an unsupported
# "Yes" still shipped untouched: the explanation was never attempted at all
# (so nothing was ever "gated" to trigger the cascade), and the LLM falsely
# self-reporting a fabricated value as "raw_text_sourced" (which used to
# bypass independent verification entirely).

def test_evidence_gate_blanks_unexplained_yes_answer():
    # "Yes" is marked but the paired explanation field was never even
    # attempted (absent from filled_values, not just null) - the original
    # cascade never looked at this case since _gated_explanations only
    # tracks explanations that were filled then dropped.
    import config.settings as settings
    settings.ENABLE_EVIDENCE_GATED_FILL = True
    from services.pdf_service import map_facts_to_form
    q_field = "CommercialPolicy_Question_ABCCode_A"
    exp_field = "CommercialPolicy_AnyExposureToFlammableExplosivesChemicalsExplanation_A"
    schema = {q_field: {"required": False}, exp_field: {"required": False}}
    pre = {"filled_values": {q_field: "Yes"}, "raw_text_fields": set()}
    raw = "Operations include metal stamping and fabrication of small parts."
    mapped, _ = map_facts_to_form(facts={}, schema=schema, form_id="ACORD_125",
                                  raw_text=raw, pre_filled_gpt=pre)
    assert mapped.get(q_field) is None


def test_evidence_gate_infers_yes_from_grounded_explanation_left_unmarked():
    # Mirror-image bug found 2026-07-11 (reported from a live test): the
    # Question code was never filled at all, but the paired explanation IS
    # genuinely grounded in the raw document. A real explanation on an
    # "explain all Yes responses" form IS itself the evidence for "Yes" -
    # leaving the Y/N column blank strands real, verified information.
    import config.settings as settings
    settings.ENABLE_EVIDENCE_GATED_FILL = True
    from services.pdf_service import map_facts_to_form
    q_field = "CommercialPolicy_Question_ABCCode_A"
    exp_field = "CommercialPolicy_AnyExposureToFlammableExplosivesChemicalsExplanation_A"
    schema = {q_field: {"required": False}, exp_field: {"required": False}}
    raw = "The facility stores flammable solvents used in the finishing process on site."
    pre = {"filled_values": {exp_field: "flammable solvents on site"}, "raw_text_fields": set()}
    mapped, _ = map_facts_to_form(facts={}, schema=schema, form_id="ACORD_125",
                                  raw_text=raw, pre_filled_gpt=pre)
    assert mapped.get(q_field) == "Y"
    assert mapped.get(exp_field) is not None


def test_evidence_gate_does_not_infer_yes_from_fabricated_explanation():
    # The reverse-inference guard: it must never manufacture a "Yes" out of
    # an explanation that was itself just proven fabricated and dropped.
    import config.settings as settings
    settings.ENABLE_EVIDENCE_GATED_FILL = True
    from services.pdf_service import map_facts_to_form
    q_field = "CommercialPolicy_Question_ABCCode_A"
    exp_field = "CommercialPolicy_AnyExposureToFlammableExplosivesChemicalsExplanation_A"
    schema = {q_field: {"required": False}, exp_field: {"required": False}}
    raw = "Operations include metal stamping and fabrication of small parts."
    pre = {"filled_values": {exp_field: "Extensive on-site storage of flammable industrial solvents"},
           "raw_text_fields": set()}
    mapped, _ = map_facts_to_form(facts={}, schema=schema, form_id="ACORD_125",
                                  raw_text=raw, pre_filled_gpt=pre)
    assert mapped.get(q_field) is None
    assert mapped.get(exp_field) is None


def test_evidence_gate_blanks_ai_inferred_no_with_no_grounding():
    # Direct reproduction of a live-test finding (2026-07-12): most Y/N
    # questions on a real submission are never mentioned by the source
    # document at all. Confirms an AI-inferred "No" on a bare Question-code
    # field (no paired Explanation, no other signal) is blanked rather than
    # defaulted to a confident negative with nothing behind it.
    import config.settings as settings
    settings.ENABLE_EVIDENCE_GATED_FILL = True
    from services.pdf_service import map_facts_to_form
    q_field = "GeneralLiabilityLineOfBusiness_Question_ACDCode_A"  # "any parking facilities owned/rented"
    schema = {q_field: {"required": False}}
    raw = "Operations include metal stamping and fabrication of small parts."
    pre = {"filled_values": {q_field: "N"}, "raw_text_fields": set()}
    mapped, _ = map_facts_to_form(facts={}, schema=schema, form_id="ACORD_126",
                                  raw_text=raw, pre_filled_gpt=pre)
    assert mapped.get(q_field) is None


def test_evidence_gate_blanks_ai_inferred_no_even_when_self_reported_verbatim():
    # Same consistency point as the unpaired-Yes fix: self-report is proven
    # unreliable, so it cannot be the deciding signal for a "No" either.
    import config.settings as settings
    settings.ENABLE_EVIDENCE_GATED_FILL = True
    from services.pdf_service import map_facts_to_form
    q_field = "GeneralLiabilityLineOfBusiness_Question_ACDCode_A"
    schema = {q_field: {"required": False}}
    raw = "Operations include metal stamping and fabrication of small parts."
    pre = {"filled_values": {q_field: "N"}, "raw_text_fields": {q_field}}
    mapped, _ = map_facts_to_form(facts={}, schema=schema, form_id="ACORD_126",
                                  raw_text=raw, pre_filled_gpt=pre)
    assert mapped.get(q_field) is None


def test_evidence_gate_does_not_touch_genuine_yes_when_sibling_no_fields_are_gated():
    # A real, grounded "Yes" + explanation on one question must survive
    # untouched even while unrelated "No" answers elsewhere on the same form
    # are being stripped - the new gate is scoped per-field, not a blanket
    # wipe of the whole Question-code family.
    import config.settings as settings
    settings.ENABLE_EVIDENCE_GATED_FILL = True
    from services.pdf_service import map_facts_to_form
    genuine_q = "GeneralLiabilityLineOfBusiness_Question_ACJCode_A"
    genuine_exp = "GeneralLiabilityLineOfBusiness_OperationsInvolveStoringDisposingTransportingHazardousMaterialExplanation_A"
    ungrounded_no_q = "GeneralLiabilityLineOfBusiness_Question_ACDCode_A"
    schema = {genuine_q: {"required": False}, genuine_exp: {"required": False},
              ungrounded_no_q: {"required": False}}
    raw = "Scrap metal shavings are removed weekly by a licensed hazardous waste hauler."
    pre = {
        "filled_values": {
            genuine_q: "Y",
            genuine_exp: "removed weekly by a licensed hazardous waste hauler",
            ungrounded_no_q: "N",
        },
        "raw_text_fields": set(),
    }
    mapped, _ = map_facts_to_form(facts={}, schema=schema, form_id="ACORD_126",
                                  raw_text=raw, pre_filled_gpt=pre)
    assert mapped.get(genuine_q) == "Y"
    assert mapped.get(genuine_exp) is not None
    assert mapped.get(ungrounded_no_q) is None


def test_evidence_gate_blanks_unpaired_question_code_with_no_verbatim_claim():
    # Structural gap found 2026-07-11: some Y/N questions request an
    # attachment, a structured count, a checkbox, or another entity's name
    # instead of free-text explanation (e.g. ACORD 126's "Foreign products
    # sold... (if YES, attach ACORD 815)"). There is no paired Explanation
    # field for the forward/reverse cascades to reason about, so an
    # unsupported "Y" here had zero protection until this fix required at
    # least the LLM's own verbatim self-report to let it survive.
    import config.settings as settings
    settings.ENABLE_EVIDENCE_GATED_FILL = True
    from services.pdf_service import map_facts_to_form
    q_field = "GeneralLiabilityLineOfBusiness_Question_ABACode_A"  # genuinely unpaired on ACORD 126
    schema = {q_field: {"required": False}}
    raw = "Operations include metal stamping and fabrication of small parts."
    pre = {"filled_values": {q_field: "Y"}, "raw_text_fields": set()}
    mapped, _ = map_facts_to_form(facts={}, schema=schema, form_id="ACORD_126",
                                  raw_text=raw, pre_filled_gpt=pre)
    assert mapped.get(q_field) is None


def test_evidence_gate_blanks_unpaired_question_code_even_when_self_reported_verbatim():
    # Tightened 2026-07-11: the self-report itself is proven unreliable (see
    # test_evidence_gate_does_not_trust_false_verbatim_self_report below), so
    # it cannot be trusted as the ONLY signal for a field with no other way
    # to verify it either. An AI-inferred "Yes" on an unpaired Question code
    # is never kept, full stop - deterministic/client-confirmed values are
    # the only way one of these fields gets filled.
    import config.settings as settings
    settings.ENABLE_EVIDENCE_GATED_FILL = True
    from services.pdf_service import map_facts_to_form
    q_field = "GeneralLiabilityLineOfBusiness_Question_ABACode_A"
    schema = {q_field: {"required": False}}
    raw = "Foreign-sourced fasteners are used as components in assembled products."
    pre = {"filled_values": {q_field: "Y"}, "raw_text_fields": {q_field}}
    mapped, _ = map_facts_to_form(facts={}, schema=schema, form_id="ACORD_126",
                                  raw_text=raw, pre_filled_gpt=pre)
    assert mapped.get(q_field) is None


def test_evidence_gate_does_not_trust_false_verbatim_self_report():
    # The gap-fill LLM can be WRONG about its own "raw_text_sourced" claim -
    # a model that fabricates a sentence can also falsely mark it as copied
    # verbatim. Independent verification must still run and win when raw
    # text is available, instead of trusting the self-report as a bypass.
    import config.settings as settings
    settings.ENABLE_EVIDENCE_GATED_FILL = True
    from services.pdf_service import map_facts_to_form
    field = "CommercialPolicy_DemolitionExplanation_A"
    schema = {field: {"required": False}}
    fabricated = "Extensive on-site storage of flammable industrial solvents"
    raw = "Operations include metal stamping and fabrication of small parts."
    pre = {
        "filled_values": {field: fabricated},
        "raw_text_fields": {field},  # falsely self-reported as verbatim
    }
    mapped, _ = map_facts_to_form(facts={}, schema=schema, form_id="ACORD_125",
                                  raw_text=raw, pre_filled_gpt=pre)
    assert mapped.get(field) is None


# ── Direct-quote grounding for bare Question-code answers ─────────────────────
# Client clarification (2026-07-12): "proof" is not limited to a literal
# "Yes"/"No" string in the document - it's whatever data in the document
# actually answers the question. The gap-fill LLM names the verbatim excerpt
# behind EVERY Question-code answer (question_grounding); that claim is kept
# only when independently confirmed present in the raw text.

def test_evidence_gate_keeps_no_when_independently_grounded():
    # The document explicitly addresses and denies the topic (not silence).
    # A "No" carrying a verified grounding quote must survive.
    import config.settings as settings
    settings.ENABLE_EVIDENCE_GATED_FILL = True
    from services.pdf_service import map_facts_to_form
    q_field = "GeneralLiabilityLineOfBusiness_Question_ACDCode_A"  # parking facilities
    schema = {q_field: {"required": False}}
    raw = ("Q: Any parking facilities owned or rented by the applicant?\n"
           "A: No, the applicant leases a single fabrication unit with no on-site parking lot.")
    pre = {
        "filled_values": {q_field: "No"},
        "raw_text_fields": set(),
        "question_grounding": {q_field: "the applicant leases a single fabrication unit with no on-site parking lot"},
    }
    mapped, _ = map_facts_to_form(facts={}, schema=schema, form_id="ACORD_126",
                                  raw_text=raw, pre_filled_gpt=pre)
    assert mapped.get(q_field) == "No"


def test_evidence_gate_keeps_unpaired_yes_when_independently_grounded():
    # Unpaired Question code (no Explanation field at all) - a grounding
    # quote independently confirmed present in raw text rescues the Yes.
    import config.settings as settings
    settings.ENABLE_EVIDENCE_GATED_FILL = True
    from services.pdf_service import map_facts_to_form
    q_field = "GeneralLiabilityLineOfBusiness_Question_ABACode_A"
    schema = {q_field: {"required": False}}
    raw = "Foreign-sourced fasteners are used as components in assembled products."
    pre = {
        "filled_values": {q_field: "Y"},
        "raw_text_fields": set(),
        "question_grounding": {q_field: "Foreign-sourced fasteners are used as components"},
    }
    mapped, _ = map_facts_to_form(facts={}, schema=schema, form_id="ACORD_126",
                                  raw_text=raw, pre_filled_gpt=pre)
    assert mapped.get(q_field) == "Y"


def test_evidence_gate_rejects_fabricated_grounding_quote():
    # The claimed quote does not actually appear anywhere in the raw text -
    # same protection as the Explanation check: a model that invents an
    # answer can invent a "quote" for it too, so the claim alone is worthless.
    import config.settings as settings
    settings.ENABLE_EVIDENCE_GATED_FILL = True
    from services.pdf_service import map_facts_to_form
    q_field = "GeneralLiabilityLineOfBusiness_Question_ACDCode_A"
    schema = {q_field: {"required": False}}
    raw = "Operations include metal stamping and fabrication of small parts."
    pre = {
        "filled_values": {q_field: "No"},
        "raw_text_fields": set(),
        "question_grounding": {q_field: "The applicant does not lease or own any parking facilities"},
    }
    mapped, _ = map_facts_to_form(facts={}, schema=schema, form_id="ACORD_126",
                                  raw_text=raw, pre_filled_gpt=pre)
    assert mapped.get(q_field) is None


def test_evidence_gate_rejects_boilerplate_quote_reused_across_questions():
    # The same real (non-fabricated) quote claimed as "proof" for 3+
    # unrelated questions is boilerplate asserted as universal justification,
    # not evidence of any one of them - only the first claim survives.
    import config.settings as settings
    settings.ENABLE_EVIDENCE_GATED_FILL = True
    from services.pdf_service import map_facts_to_form
    fields = [
        "GeneralLiabilityLineOfBusiness_Question_ACDCode_A",
        "GeneralLiabilityLineOfBusiness_Question_KAGCode_A",
        "GeneralLiabilityLineOfBusiness_Question_ACECode_A",
    ]
    schema = {f: {"required": False} for f in fields}
    raw = "Ironclad Fabrication & Welding LLC is a metal fabrication and welding contractor."
    reused_quote = "Ironclad Fabrication & Welding LLC is a metal fabrication and welding"
    pre = {
        "filled_values": {f: "No" for f in fields},
        "raw_text_fields": set(),
        "question_grounding": {f: reused_quote for f in fields},
    }
    mapped, _ = map_facts_to_form(facts={}, schema=schema, form_id="ACORD_126",
                                  raw_text=raw, pre_filled_gpt=pre)
    assert all(mapped.get(f) is None for f in fields)


# ── Proof-of-No must be a NEGATIVE, on-topic statement ────────────────────────
# Live ACORD 125 test (2026-07-12): every General Information Y/N question came
# back "No" with a grounding quote. Because the source was a welding-contractor
# document, the model grabbed real-but-irrelevant POSITIVE sentences as "proof"
# (e.g. "metal fabrication and welding contractor" as proof of "not a
# subsidiary"). A presence-only check kept them all. A genuine proof-of-No
# both expresses a negative AND is about the question's subject.

def test_evidence_gate_rejects_no_grounded_by_positive_sentence():
    # The quote is genuinely present in the document but is a POSITIVE
    # descriptive sentence with no negation - not proof of a "No".
    import config.settings as settings
    settings.ENABLE_EVIDENCE_GATED_FILL = True
    from services.pdf_service import map_facts_to_form
    q_field = "CommercialPolicy_Question_AAICode_A"  # "is the applicant a subsidiary?"
    schema = {q_field: {"required": False}}
    raw = "Ironclad Fabrication & Welding LLC is a metal fabrication and welding contractor."
    pre = {
        "filled_values": {q_field: "No"},
        "raw_text_fields": set(),
        "question_grounding": {q_field: "metal fabrication and welding contractor"},
    }
    mapped, _ = map_facts_to_form(facts={}, schema=schema, form_id="ACORD_125",
                                  raw_text=raw, pre_filled_gpt=pre)
    assert mapped.get(q_field) is None


def test_evidence_gate_keeps_no_with_genuine_negative_ontopic_quote():
    # The document explicitly denies the topic: a real proof-of-No survives.
    import config.settings as settings
    settings.ENABLE_EVIDENCE_GATED_FILL = True
    from services.pdf_service import map_facts_to_form
    import json, os
    schema_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "forms_schemas", "ACORD_125_schema.json")
    schema = json.load(open(schema_path, encoding="utf-8"))
    q_field = "CommercialPolicy_Question_KAACode_A"  # policy declined/cancelled/non-renewed
    raw = ("The applicant confirms it has no prior policy cancellations or "
           "non-renewals in the last three years.")
    pre = {
        "filled_values": {q_field: "N"},
        "raw_text_fields": set(),
        "question_grounding": {q_field: "no prior policy cancellations or non-renewals in the last three years"},
    }
    mapped, _ = map_facts_to_form(facts={}, schema=schema, form_id="ACORD_125",
                                  raw_text=raw, pre_filled_gpt=pre)
    assert mapped.get(q_field) == "N"


# ── Evidence gate now also covers high-impact CHECKBOX fields (audit finding) ─
# The gate previously only recognized "_Question_<code>Code_" TEXT fields by
# name shape. ACORD 137_CA/137_CO/138_CA/138_CO express the same HNOA-
# equivalent question as a /Btn checkbox pair instead (e.g.
# Vehicle_HiredBorrowed_YesIndicator_A / _NoIndicator_A, or the opaque numeric
# Vehicle_GarageAndDealersSymbol_TwentyEightIndicator_A on 138). Neither
# matches _QUESTION_CODE_RE, so a hallucinated "Yes" on one of them was never
# blanked by the gate - only soft-flagged for review via is_high_impact_field.
# _is_high_impact_checkbox_field closes that gap.

def test_is_high_impact_checkbox_field_identifies_hnoa_checkboxes():
    from services.pdf_service import _is_high_impact_checkbox_field
    assert _is_high_impact_checkbox_field(
        "Vehicle_HiredBorrowed_YesIndicator_A",
        "Check the box (if applicable): Indicates if hired / borrowed coverage applies.",
        "/Btn",
    )
    assert _is_high_impact_checkbox_field(
        "Vehicle_GarageAndDealersSymbol_TwentyEightIndicator_A",
        "Check the box (if applicable): Indicates hired autos only are covered.",
        "/Btn",
    )
    # A Question-code TEXT field is already covered by the name-shape rule -
    # this predicate should not double-count it (returns False, not an error).
    assert not _is_high_impact_checkbox_field(
        "CommercialVehicleLineOfBusiness_Question_AAJCode_A", "any tooltip", "/Tx",
    )
    # An ordinary checkbox with no high-impact topic is untouched.
    assert not _is_high_impact_checkbox_field(
        "Policy_Status_BoundIndicator_A", "Indicates the policy is bound.", "/Btn",
    )


def _fill_hnoa_checkbox(field, tu, value, question_grounding, raw):
    import config.settings as settings
    settings.ENABLE_EVIDENCE_GATED_FILL = True
    from services.pdf_service import map_facts_to_form
    schema = {field: {"ft": "/Btn", "tu": tu, "required": False}}
    pre = {
        "filled_values": {field: value},
        "raw_text_fields": set(),
        "question_grounding": {field: question_grounding} if question_grounding else {},
    }
    mapped, _ = map_facts_to_form(facts={}, schema=schema, form_id="ACORD_137_CA",
                                  raw_text=raw, pre_filled_gpt=pre)
    return mapped.get(field)


def test_evidence_gate_blanks_ungrounded_yes_on_hnoa_checkbox():
    # The document never mentions hired/borrowed vehicles at all - a "Yes"
    # here is a guess and must be blanked, not stamped onto the PDF.
    out = _fill_hnoa_checkbox(
        "Vehicle_HiredBorrowed_YesIndicator_A",
        "Check the box (if applicable): Indicates if hired / borrowed coverage applies.",
        "Yes", None,
        raw="The applicant operates three company-owned box trucks for local delivery.",
    )
    assert out is None


def test_evidence_gate_keeps_grounded_yes_on_hnoa_checkbox():
    # The document explicitly discusses hired/borrowed coverage and the model
    # cites a real, present quote as its basis - the "Yes" survives.
    out = _fill_hnoa_checkbox(
        "Vehicle_HiredBorrowed_YesIndicator_A",
        "Check the box (if applicable): Indicates if hired / borrowed coverage applies.",
        "Yes",
        "the applicant regularly hires and borrows vehicles for overflow deliveries",
        raw="Per the operations narrative, the applicant regularly hires and borrows "
            "vehicles for overflow deliveries during peak season.",
    )
    assert out == "Yes"


def test_evidence_gate_blanks_ungrounded_yes_on_numeric_symbol_checkbox():
    # 138_CA/138_CO's opaque numeric-symbol variant - no "hired borrowed" in the
    # field name at all, only in the tooltip. Same protection must apply.
    out = _fill_hnoa_checkbox(
        "Vehicle_GarageAndDealersSymbol_TwentyEightIndicator_A",
        "Check the box (if applicable): Indicates hired autos only are covered.",
        "Yes", None,
        raw="The dealership insures its own inventory of vehicles on the lot.",
    )
    assert out is None


def test_evidence_gate_affirmative_unpaired_still_present_only():
    # Regression guard: the negation requirement is scoped to the NEGATIVE
    # branch. An unpaired affirmative "Yes" with a real present quote is still
    # kept on presence alone (it need not contain a negation cue).
    import config.settings as settings
    settings.ENABLE_EVIDENCE_GATED_FILL = True
    from services.pdf_service import map_facts_to_form
    q_field = "GeneralLiabilityLineOfBusiness_Question_ABACode_A"  # unpaired on ACORD 126
    schema = {q_field: {"required": False}}
    raw = "Foreign-sourced fasteners are used as components in assembled products."
    pre = {
        "filled_values": {q_field: "Y"},
        "raw_text_fields": set(),
        "question_grounding": {q_field: "Foreign-sourced fasteners are used as components"},
    }
    mapped, _ = map_facts_to_form(facts={}, schema=schema, form_id="ACORD_126",
                                  raw_text=raw, pre_filled_gpt=pre)
    assert mapped.get(q_field) == "Y"


# ── Evidence gate now covers EVERY Yes/No field, not just Question-code text ──
# fields or the high-impact auto/ownership checkbox subset (client requirement:
# "in all the forms... certain fields where Y/N/Yes/No to be filled... only
# fill if we found concrete evidence"). _is_yes_no_field recognizes three
# schema-driven shapes: the "_Question_<code>Code_" name pattern, ANY /Btn
# checkbox (not just high-impact ones - e.g. ACORD 140's sink-hole / mine-
# subsidence / building-improvement checkboxes had zero protection before
# this), and a plain /Tx field whose own tooltip carries the ACORD "Enter Y
# for a Yes response..." boilerplate (e.g. ACORD 140/25's "...YesNoCode_" /
# "...RefrigeratorMaintenanceCode_" fields, which are Y/N by convention but
# match neither of the other two shapes).

def test_is_yes_no_field_covers_all_three_shapes():
    from services.pdf_service import _is_yes_no_field
    schema = {
        "CommercialPolicy_Question_AADCode_A": {"ft": "/Tx", "tu": "irrelevant"},
        "CommercialPropertyCoverage_SinkHoleCollapse_YesIndicator_A": {
            "ft": "/Btn", "tu": "Check the box (if applicable): sink hole coverage accepted.",
        },
        "CommercialProperty_Spoilage_RefrigeratorMaintenanceCode_A": {
            "ft": "/Tx",
            "tu": "Enter Y for a “Yes” response. Input N for “No” response. Indicates if there is a maintenance contract.",
        },
        "CommercialProperty_Premises_LimitAmount_A": {"ft": "/Tx", "tu": "Enter limit: the building limit."},
        "Producer_FullName_A": {"ft": "/Tx", "tu": "Enter text: the producer's name."},
    }
    assert _is_yes_no_field("CommercialPolicy_Question_AADCode_A", schema) is True
    assert _is_yes_no_field("CommercialPropertyCoverage_SinkHoleCollapse_YesIndicator_A", schema) is True
    assert _is_yes_no_field("CommercialProperty_Spoilage_RefrigeratorMaintenanceCode_A", schema) is True
    # Ordinary dollar/text fields are never swept in.
    assert _is_yes_no_field("CommercialProperty_Premises_LimitAmount_A", schema) is False
    assert _is_yes_no_field("Producer_FullName_A", schema) is False
    # Unknown field (not in schema at all) is safe, never an error.
    assert _is_yes_no_field("SomeFieldNotInSchema_A", schema) is False


def _fill_ordinary_checkbox(field, tu, value, question_grounding, raw, form_id="ACORD_140"):
    import config.settings as settings
    settings.ENABLE_EVIDENCE_GATED_FILL = True
    from services.pdf_service import map_facts_to_form
    schema = {field: {"ft": "/Btn", "tu": tu, "required": False}}
    pre = {
        "filled_values": {field: value},
        "raw_text_fields": set(),
        "question_grounding": {field: question_grounding} if question_grounding else {},
    }
    mapped, _ = map_facts_to_form(facts={}, schema=schema, form_id=form_id,
                                  raw_text=raw, pre_filled_gpt=pre)
    return mapped.get(field)


def test_evidence_gate_blanks_ungrounded_yes_on_ordinary_checkbox():
    # Sink-hole coverage is NOT a "high-impact" (auto/ownership) field and has
    # no "_Question_Code_" name - before this fix, NOTHING gated it, so a
    # gap-fill hallucination here shipped straight onto the PDF untouched.
    out = _fill_ordinary_checkbox(
        "CommercialPropertyCoverage_SinkHoleCollapse_YesIndicator_A",
        "Check the box (if applicable): Indicates that sink hole coverage is accepted.",
        "Yes", None,
        raw="The building is a single-story masonry warehouse with a sprinkler system.",
    )
    assert out is None


def test_evidence_gate_keeps_grounded_yes_on_ordinary_checkbox():
    out = _fill_ordinary_checkbox(
        "CommercialPropertyCoverage_SinkHoleCollapse_YesIndicator_A",
        "Check the box (if applicable): Indicates that sink hole coverage is accepted.",
        "Yes",
        "the insured has accepted sink hole collapse coverage on this location",
        raw="Per the property schedule, the insured has accepted sink hole collapse "
            "coverage on this location.",
    )
    assert out == "Yes"


def test_evidence_gate_blanks_ungrounded_no_on_ordinary_checkbox():
    # The negative branch is symmetric: an ungrounded "No" is blanked too, not
    # just an ungrounded "Yes" - matching the Question-code contract exactly.
    out = _fill_ordinary_checkbox(
        "BuildingFeatures_HistoricalPropertyIndicator_A",
        "Check the box (if applicable): Indicates the property has been designated an historical property.",
        "No", None,
        raw="The building was constructed in 2018 and is a standard retail strip mall.",
    )
    assert out is None


def _fill_yes_no_code_text_field(field, tu, value, question_grounding, raw, form_id="ACORD_140"):
    import config.settings as settings
    settings.ENABLE_EVIDENCE_GATED_FILL = True
    from services.pdf_service import map_facts_to_form
    schema = {field: {"ft": "/Tx", "tu": tu, "required": False}}
    pre = {
        "filled_values": {field: value},
        "raw_text_fields": set(),
        "question_grounding": {field: question_grounding} if question_grounding else {},
    }
    mapped, _ = map_facts_to_form(facts={}, schema=schema, form_id=form_id,
                                  raw_text=raw, pre_filled_gpt=pre)
    return mapped.get(field)


def test_evidence_gate_gates_plain_yes_no_code_text_field():
    # ACORD 140's "...YesNoCode_" / "...RefrigeratorMaintenanceCode_" fields:
    # /Tx (not /Btn), no "_Question_" in the name - recognized ONLY via the
    # schema's own "Enter Y for a Yes response..." tooltip boilerplate.
    tu = ("Enter Y for a “Yes” response. Input N for “No” response. "
          "Indicates if there is a maintenance contract on the refrigeration equipment.")
    field = "CommercialProperty_Spoilage_RefrigeratorMaintenanceCode_A"
    ungrounded = _fill_yes_no_code_text_field(
        field, tu, "Y", None,
        raw="The insured operates a small retail bakery with two display coolers.",
    )
    assert ungrounded is None
    grounded = _fill_yes_no_code_text_field(
        field, tu, "Y", "maintained under a quarterly service contract with CoolTech Refrigeration",
        raw="The refrigeration equipment is maintained under a quarterly service "
            "contract with CoolTech Refrigeration.",
    )
    assert grounded == "Y"


# ── Pairing now also covers the "...OtherIndicator" -> "...OtherDescription" ──
# checkbox convention (10+ forms), which was invisible to _question_explanation
# _pairs before this fix because it only ever looked at "_Question_<code>Code_"
# names. Loads the REAL ACORD_140 schema (not a synthetic one) since the whole
# point is confirming this against the actual field layout, not an assumption
# about it.

def test_question_explanation_pairs_covers_other_indicator_checkboxes():
    import json, os
    from services.pdf_service import _question_explanation_pairs
    schema_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "forms_schemas", "ACORD_140_schema.json")
    schema = json.load(open(schema_path, encoding="utf-8"))
    pairs = _question_explanation_pairs(schema)
    assert pairs.get("BuildingImprovement_OtherIndicator_A") == "BuildingImprovement_OtherDescription_A"
    assert pairs.get("CommercialStructure_WindClass_OtherIndicator_A") == \
        "CommercialStructure_WindClass_OtherDescription_A"


def test_evidence_gate_fills_other_description_when_other_checkbox_grounded():
    # End-to-end: "Other" building-improvement box checked + a grounded
    # description -> both survive, matching the Question-code "Yes always
    # gets its explanation" contract.
    import config.settings as settings
    settings.ENABLE_EVIDENCE_GATED_FILL = True
    from services.pdf_service import map_facts_to_form
    q_field = "BuildingImprovement_OtherIndicator_A"
    exp_field = "BuildingImprovement_OtherDescription_A"
    schema = {
        q_field: {"ft": "/Btn", "tu": "Check the box (if applicable): other improvement.", "required": False},
        exp_field: {"ft": "/Tx", "tu": "Enter text: description of the other improvement.", "required": False},
    }
    raw = "The building's fire suppression system was fully replaced in 2024."
    pre = {
        "filled_values": {q_field: "Yes", exp_field: "fire suppression system was fully replaced in 2024"},
        "raw_text_fields": set(),
    }
    mapped, _ = map_facts_to_form(facts={}, schema=schema, form_id="ACORD_140",
                                  raw_text=raw, pre_filled_gpt=pre)
    assert mapped.get(q_field) == "Yes"
    assert mapped.get(exp_field) is not None


def test_pairing_does_not_chase_coincidental_non_checkbox_adjacency():
    # Audited across all 17 real schemas: two /Tx Yes/No-by-tooltip fields
    # happen to sit directly before an UNRELATED "...Explanation"/
    # "...OtherDescription" field from a different section (schema key order
    # is not always a semantic guarantee for a plain text field the way it is
    # for a checkbox's PDF layout position). Pairing deliberately trusts
    # "_Question_<code>Code_" naming and /Btn type, but NOT the broader
    # tooltip-only Yes/No signal, specifically to avoid these two real cases.
    import json, os
    from services.pdf_service import _question_explanation_pairs
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    schema_126 = json.load(open(os.path.join(backend_dir, "forms_schemas", "ACORD_126_schema.json"),
                                 encoding="utf-8"))
    pairs_126 = _question_explanation_pairs(schema_126)
    assert "PropertyItem_ItemDetail_InstructionGivenCode_A" not in pairs_126

    schema_141 = json.load(open(os.path.join(backend_dir, "forms_schemas", "ACORD_141_schema.json"),
                                 encoding="utf-8"))
    pairs_141 = _question_explanation_pairs(schema_141)
    assert "BuildingProtection_DoubleCylinderDoorLockCode_A" not in pairs_141


# ── Grounding quote: paraphrase fallback (audit finding, live test 2026-07-15) ─
# A live test on ACORD 127 (vehicle maintenance question) showed a genuine,
# clearly-documented "Yes" get wiped, along with its explanation, because the
# gap-fill LLM didn't also duplicate the answer into the Explanation field and
# its own grounding quote was a light paraphrase - not a byte-for-byte match -
# of the real sentence. _quote_grounds_claim's exact-substring-only rule was
# too strict for this case. Fixed with a per-SENTENCE token-coverage fallback
# (_quote_covered_by_sentence) that tolerates a real paraphrase while still
# rejecting a fabricated quote on an undiscussed topic (the 2026-07-12 bug this
# strictness exists to prevent).

def _fill_maintenance_question(quote, raw, include_explanation=False):
    import config.settings as settings
    settings.ENABLE_EVIDENCE_GATED_FILL = True
    from services.pdf_service import map_facts_to_form
    q_field = "CommercialVehicleLineOfBusiness_Question_KADCode_A"
    exp_field = "CommercialVehicleLineOfBusiness_VehicleMaintenanceProgramInOperationExplanation_A"
    schema = {q_field: {"required": False}, exp_field: {"required": False}}
    filled = {q_field: "Y"}
    pre = {
        "filled_values": filled,
        "raw_text_fields": set(),
        "question_grounding": ({q_field: quote} if quote else {}),
    }
    mapped, _ = map_facts_to_form(facts={}, schema=schema, form_id="ACORD_127",
                                  raw_text=raw, pre_filled_gpt=pre)
    return mapped.get(q_field), mapped.get(exp_field)


_MAINTENANCE_DOC = (
    "Bright Horizon Electrical Contractors, LLC operates a documented preventive "
    "maintenance program: all company vehicles receive scheduled inspections "
    "every 5,000 miles performed by an in-house fleet mechanic, with maintenance "
    "logs kept for each vehicle."
)


def test_evidence_gate_keeps_yes_on_exact_quote_with_no_explanation():
    # No paraphrase needed here - locks in the baseline (unaffected by the fix).
    q, exp = _fill_maintenance_question(
        "scheduled inspections every 5,000 miles performed by an in-house fleet mechanic",
        _MAINTENANCE_DOC,
    )
    assert q == "Y" and exp


def test_evidence_gate_keeps_yes_on_paraphrased_quote_with_no_explanation():
    # The actual bug: GPT skips the Explanation field and paraphrases its
    # grounding quote instead of copying it verbatim. Must now survive.
    q, exp = _fill_maintenance_question(
        "vehicles are inspected every 5,000 miles by an in-house mechanic",
        _MAINTENANCE_DOC,
    )
    assert q == "Y" and exp


def test_evidence_gate_still_blanks_yes_with_no_quote_at_all():
    # No evidence whatsoever must still be blanked - the fix only forgives a
    # paraphrase of something real, it does not remove the requirement itself.
    q, exp = _fill_maintenance_question(None, _MAINTENANCE_DOC)
    assert q is None and exp is None


def test_evidence_gate_still_rejects_fabricated_quote_on_undiscussed_topic():
    # Direct reproduction of the 2026-07-12 bug this strictness exists to
    # prevent: a fabricated quote about a topic the document never raises.
    # Must still be rejected even with the paraphrase fallback in place.
    import config.settings as settings
    settings.ENABLE_EVIDENCE_GATED_FILL = True
    from services.pdf_service import map_facts_to_form
    q_field = "GeneralLiabilityLineOfBusiness_Question_ABACode_A"
    schema = {q_field: {"required": False}}
    raw = ("Ironclad Fabrication & Welding LLC is a metal fabrication and welding "
           "contractor. Operations include structural steel work for commercial buildings.")
    pre = {
        "filled_values": {q_field: "N"},
        "raw_text_fields": set(),
        "question_grounding": {q_field: "products under label of others are not sold by the applicant"},
    }
    mapped, _ = map_facts_to_form(facts={}, schema=schema, form_id="ACORD_126",
                                  raw_text=raw, pre_filled_gpt=pre)
    assert mapped.get(q_field) is None


# ── Paraphrase fallback must NOT extend to unpaired questions (live test 2026-07-15) ─
# Found via the same live ACORD 127 test that surfaced the KADCode bug above: once
# the paraphrase fallback existed, a fabricated "Yes" for the (unpaired, "no
# explanation needed" per the form) ICC/PUC filings question survived by reusing
# real words from a COMPLETELY UNRELATED sentence elsewhere in the document -
# reopening the exact 2026-07-12 vulnerability. An unpaired question has no
# Explanation slot to fall back on, so its quote is the ONLY signal and must stay
# held to the strict, exact-match-only bar; only PAIRED questions (a real second
# signal the model chose not to use) get the paraphrase leniency.

def test_paraphrase_fallback_does_not_rescue_fabricated_quote_on_unpaired_question():
    import config.settings as settings
    settings.ENABLE_EVIDENCE_GATED_FILL = True
    from services.pdf_service import map_facts_to_form
    q_field = "CommercialVehicleLineOfBusiness_Question_AAECode_A"  # ICC/PUC filings - unpaired
    schema = {q_field: {"required": False}}
    raw = (
        "Bright Horizon Electrical Contractors, LLC operates a documented preventive "
        "maintenance program: all company vehicles receive scheduled inspections every "
        "5,000 miles performed by an in-house fleet mechanic, with maintenance logs kept "
        "for each vehicle. Bright Horizon Electrical Contractors, LLC performs commercial "
        "and residential electrical installation and repair work within the Fresno, "
        "California metropolitan area."
    )
    # Built entirely from real words lifted from the unrelated operations sentence -
    # shares 75%+ of ITS OWN tokens with that sentence, which is exactly what the
    # paired-question paraphrase fallback would forgive. Must NOT be forgiven here.
    pre = {
        "filled_values": {q_field: "Y"},
        "raw_text_fields": set(),
        "question_grounding": {q_field: "the electrical contractors perform work within the metropolitan area"},
    }
    mapped, _ = map_facts_to_form(facts={}, schema=schema, form_id="ACORD_127",
                                  raw_text=raw, pre_filled_gpt=pre)
    assert mapped.get(q_field) is None


# ── Explanation must not be reused generic boilerplate (live test 2026-07-15) ─
# ACORD 127's hazardous-material question came back "Yes", explained by the
# applicant's generic operations_description sentence - real, present text, but
# about electrical contracting, not hazardous material. _present() only checked
# presence, never relevance, so it accepted the reuse. _is_generic_boilerplate_
# reuse closes this without any keyword/topic matching: it compares the
# candidate explanation's VALUE against the operations_description FACT itself.

_OPS_SENTENCE = (
    "Bright Horizon Electrical Contractors, LLC performs commercial and residential "
    "electrical installation and repair work within the Fresno, California metropolitan area."
)


def test_evidence_gate_rejects_operations_description_reused_as_unrelated_explanation():
    import config.settings as settings
    settings.ENABLE_EVIDENCE_GATED_FILL = True
    from services.pdf_service import map_facts_to_form
    q_field = "CommercialVehicleLineOfBusiness_Question_AAFCode_A"
    exp_field = "CommercialVehicleLineOfBusiness_OperationInvolveTransportingHazardousMaterialsExplanation_A"
    schema = {q_field: {"required": False}, exp_field: {"required": False}}
    facts = {"operations_description": _OPS_SENTENCE}
    pre = {
        "filled_values": {q_field: "Y", exp_field: _OPS_SENTENCE},
        "raw_text_fields": set(),
        "question_grounding": {},
    }
    mapped, _ = map_facts_to_form(facts=facts, schema=schema, form_id="ACORD_127",
                                  raw_text=_OPS_SENTENCE, pre_filled_gpt=pre)
    assert mapped.get(q_field) is None
    assert mapped.get(exp_field) is None


def test_evidence_gate_keeps_a_real_on_topic_explanation():
    # Regression guard: the boilerplate check must not blank a genuine,
    # on-topic explanation just because operations_description also exists.
    import config.settings as settings
    settings.ENABLE_EVIDENCE_GATED_FILL = True
    from services.pdf_service import map_facts_to_form
    q_field = "CommercialVehicleLineOfBusiness_Question_AAFCode_A"
    exp_field = "CommercialVehicleLineOfBusiness_OperationInvolveTransportingHazardousMaterialsExplanation_A"
    schema = {q_field: {"required": False}, exp_field: {"required": False}}
    facts = {"operations_description": _OPS_SENTENCE}
    on_topic = "Vehicles transport corrosive cleaning chemicals between job sites."
    raw = _OPS_SENTENCE + " " + on_topic
    pre = {
        "filled_values": {q_field: "Y", exp_field: on_topic},
        "raw_text_fields": set(),
        "question_grounding": {},
    }
    mapped, _ = map_facts_to_form(facts=facts, schema=schema, form_id="ACORD_127",
                                  raw_text=raw, pre_filled_gpt=pre)
    assert mapped.get(q_field) == "Y"
    assert mapped.get(exp_field) == on_topic


# ── additional_remarks_text carries the same reuse risk (audit 2026-07-16) ───
# The same broad-narrative-fact risk as operations_description: a catch-all
# remarks fact that could equally get recycled as an unrelated question's
# "explanation". Safe to gate - its only legitimate destination (ACORD 101's
# overflow remarks) runs strictly after this check and overwrites regardless.

def test_evidence_gate_rejects_additional_remarks_text_reused_as_unrelated_explanation():
    import config.settings as settings
    settings.ENABLE_EVIDENCE_GATED_FILL = True
    from services.pdf_service import map_facts_to_form
    q_field = "CommercialVehicleLineOfBusiness_Question_AAFCode_A"
    exp_field = "CommercialVehicleLineOfBusiness_OperationInvolveTransportingHazardousMaterialsExplanation_A"
    schema = {q_field: {"required": False}, exp_field: {"required": False}}
    remarks = "Note: this account has a pending name change and a recent ownership transfer, effective next quarter."
    facts = {"additional_remarks_text": remarks}
    pre = {
        "filled_values": {q_field: "Y", exp_field: remarks},
        "raw_text_fields": set(),
        "question_grounding": {},
    }
    mapped, _ = map_facts_to_form(facts=facts, schema=schema, form_id="ACORD_127",
                                  raw_text=remarks, pre_filled_gpt=pre)
    assert mapped.get(q_field) is None
    assert mapped.get(exp_field) is None


# ── Non-adjacent companion promotion (live test 2026-07-15) ───────────────────
# ACORD 127's ownership question (AAJCode) is "explained" by the Name-of-
# Other-Owner schedule (AdditionalInterest_FullName_C/_D), not an adjacent
# Explanation field - a Vehicle_ProducerIdentifier field sits in between in
# the real schema, so the generic adjacency pairing never finds it. Before
# this fix, a genuinely correct, independently-filled owner name did nothing
# to rescue the question's own Y/N from being gated to blank.

def test_ownership_question_promoted_to_yes_when_owner_name_is_genuinely_present():
    import json
    import config.settings as settings
    settings.ENABLE_EVIDENCE_GATED_FILL = True
    from services.pdf_service import map_facts_to_form
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    schema = json.load(open(os.path.join(backend_dir, "forms_schemas", "ACORD_127_schema.json"),
                             encoding="utf-8"))
    q_field = "CommercialVehicleLineOfBusiness_Question_AAJCode_A"
    owner_field = "AdditionalInterest_FullName_C"
    raw = (
        "This is a leased vehicle. Title and registration are held by Meridian Fleet "
        "Leasing, LLC. Meridian Fleet Leasing, LLC is the registered owner on the title, "
        "not the applicant."
    )
    pre = {
        "filled_values": {owner_field: "Meridian Fleet Leasing, LLC"},
        "raw_text_fields": set(),
        "question_grounding": {},
    }
    mapped, _ = map_facts_to_form(facts={}, schema=schema, form_id="ACORD_127",
                                  raw_text=raw, pre_filled_gpt=pre)
    assert mapped.get(q_field) == "Y"
    assert mapped.get(owner_field) == "Meridian Fleet Leasing, LLC"


def test_ownership_question_not_fabricated_when_owner_name_is_empty():
    import json
    import config.settings as settings
    settings.ENABLE_EVIDENCE_GATED_FILL = True
    from services.pdf_service import map_facts_to_form
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    schema = json.load(open(os.path.join(backend_dir, "forms_schemas", "ACORD_127_schema.json"),
                             encoding="utf-8"))
    q_field = "CommercialVehicleLineOfBusiness_Question_AAJCode_A"
    raw = "Vehicle #1 is owned outright by the applicant. No lienholder, no lease."
    pre = {"filled_values": {}, "raw_text_fields": set(), "question_grounding": {}}
    mapped, _ = map_facts_to_form(facts={}, schema=schema, form_id="ACORD_127",
                                  raw_text=raw, pre_filled_gpt=pre)
    assert mapped.get(q_field) is None


# ── Reserved companion values must not double as another question's evidence ──
# (live test 2026-07-15): ACORD 127's "leased to others" question (ABCCode)
# came back "Yes", explained by the exact same vehicle-lease paragraph that
# correctly names Meridian Fleet Leasing, LLC as the OTHER owner for the
# SEPARATE ownership question (AAJCode) - real, present text, but about who
# owns/registers the vehicle, not whether the applicant leases vehicles OUT to
# others. _is_generic_boilerplate_reuse's reserved_values path closes this: a
# value already assigned as one question's own companion answer can't ALSO
# ground an unrelated question's explanation.

def test_leased_to_others_rejects_explanation_reusing_ownership_companion_value():
    import json
    import config.settings as settings
    settings.ENABLE_EVIDENCE_GATED_FILL = True
    from services.pdf_service import map_facts_to_form
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    schema = json.load(open(os.path.join(backend_dir, "forms_schemas", "ACORD_127_schema.json"),
                             encoding="utf-8"))
    owner_field = "AdditionalInterest_FullName_C"
    q4_field = "CommercialVehicleLineOfBusiness_Question_ABCCode_A"
    exp4_field = "CommercialVehicleLineOfBusiness_VehiclesLeasedToOthersExplanation_A"
    bad_explanation = (
        "This is a leased vehicle. Title and registration are held by Meridian Fleet "
        "Leasing, LLC, 900 Corporate Center Drive, Sacramento, California 95833."
    )
    pre = {
        "filled_values": {
            owner_field: "Meridian Fleet Leasing, LLC",
            q4_field: "Yes",
            exp4_field: bad_explanation,
        },
        "raw_text_fields": set(),
        "question_grounding": {},
    }
    mapped, _ = map_facts_to_form(facts={}, schema=schema, form_id="ACORD_127",
                                  raw_text=bad_explanation, pre_filled_gpt=pre)
    assert mapped.get(q4_field) is None
    assert mapped.get(exp4_field) is None
    assert mapped.get(owner_field) == "Meridian Fleet Leasing, LLC"   # untouched


def test_leased_to_others_keeps_a_real_unrelated_answer():
    import json
    import config.settings as settings
    settings.ENABLE_EVIDENCE_GATED_FILL = True
    from services.pdf_service import map_facts_to_form
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    schema = json.load(open(os.path.join(backend_dir, "forms_schemas", "ACORD_127_schema.json"),
                             encoding="utf-8"))
    owner_field = "AdditionalInterest_FullName_C"
    q4_field = "CommercialVehicleLineOfBusiness_Question_ABCCode_A"
    exp4_field = "CommercialVehicleLineOfBusiness_VehiclesLeasedToOthersExplanation_A"
    real_explanation = "The applicant rents out its box truck to a neighboring business on weekends."
    pre = {
        "filled_values": {
            owner_field: "Meridian Fleet Leasing, LLC",
            q4_field: "Yes",
            exp4_field: real_explanation,
        },
        "raw_text_fields": set(),
        "question_grounding": {},
    }
    raw = "Meridian Fleet Leasing, LLC. " + real_explanation
    mapped, _ = map_facts_to_form(facts={}, schema=schema, form_id="ACORD_127",
                                  raw_text=raw, pre_filled_gpt=pre)
    assert mapped.get(q4_field) == "Yes"
    assert mapped.get(exp4_field) == real_explanation


# ── Dependent field without a "Yes" (Guard 6, live test 2026-07-15) ───────────
# ACORD 127's "modified/special equipment?" question has its own DESCRIPTION/
# COST sub-fields with no "Explanation" suffix, so neither the evidence gate
# nor Guard 5 ever checked them. The gap-fill LLM filled DESCRIPTION with a
# sentence lifted from a DIFFERENT vehicle's ownership note even though the
# question itself correctly stayed blank.

def test_modified_equipment_description_blanked_without_parent_yes():
    import json
    import config.settings as settings
    settings.ENABLE_EVIDENCE_GATED_FILL = True
    from services.pdf_service import map_facts_to_form
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    schema = json.load(open(os.path.join(backend_dir, "forms_schemas", "ACORD_127_schema.json"),
                             encoding="utf-8"))
    desc_field = "Vehicle_Question_ModifiedEquipmentDescription_A"
    cost_field = "Vehicle_Question_ModifiedEquipmentCostAmount_A"
    raw = "Vehicle #1 is owned outright by the applicant. No lienholder, no lease."
    pre = {
        "filled_values": {desc_field: "No lienholder, no lease.", cost_field: "$0"},
        "raw_text_fields": set(),
        "question_grounding": {},
    }
    mapped, _ = map_facts_to_form(facts={}, schema=schema, form_id="ACORD_127",
                                  raw_text=raw, pre_filled_gpt=pre)
    assert mapped.get(desc_field) is None
    assert mapped.get(cost_field) is None


def test_modified_equipment_description_kept_with_genuine_parent_yes():
    import json
    import config.settings as settings
    settings.ENABLE_EVIDENCE_GATED_FILL = True
    from services.pdf_service import map_facts_to_form
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    schema = json.load(open(os.path.join(backend_dir, "forms_schemas", "ACORD_127_schema.json"),
                             encoding="utf-8"))
    q_field = "CommercialVehicleLineOfBusiness_Question_AAGCode_A"
    desc_field = "Vehicle_Question_ModifiedEquipmentDescription_A"
    cost_field = "Vehicle_Question_ModifiedEquipmentCostAmount_A"
    raw = "The vehicle has a custom ladder rack mounted on roof, cost $450."
    pre = {
        "filled_values": {
            q_field: "Y",
            desc_field: "Custom ladder rack mounted on roof.",
            cost_field: "$450",
        },
        "raw_text_fields": set(),
        "question_grounding": {q_field: "the vehicle has a custom ladder rack mounted on roof"},
    }
    mapped, _ = map_facts_to_form(facts={}, schema=schema, form_id="ACORD_127",
                                  raw_text=raw, pre_filled_gpt=pre)
    assert mapped.get(desc_field) == "Custom ladder rack mounted on roof."
    assert mapped.get(cost_field) == "$450"


# ── Quote-reuse cap: near-duplicate clustering + generous threshold ──────────
# The cap counts how many DISTINCT Yes/No fields cite the same (near-duplicate)
# grounding quote and blanks all of them once that exceeds
# _EVIDENCE_QUOTE_REUSE_MAX. Two properties are tested here:
#   1. MECHANISM — reworded copies of one sentence are clustered TOGETHER (via
#      token-Jaccard, the same technique Guard 4 uses on values), so reuse is
#      counted correctly even when the model paraphrases its "proof" per field.
#   2. THRESHOLD — moderate reuse SURVIVES (a broad negation legitimately
#      answers several exposure questions "No" once the model can actually read
#      them — root cause was the 80-char tooltip truncation, fixed 2026-07-16),
#      while pathological one-quote-for-everything reuse is still blanked.

def _fill_bare_questions(q_fields, quotes, raw_text, form_id="ACORD_126", answer="No"):
    import json, os
    import config.settings as settings
    settings.ENABLE_EVIDENCE_GATED_FILL = True
    from services.pdf_service import map_facts_to_form
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    schema = json.load(open(os.path.join(backend_dir, "forms_schemas", f"{form_id}_schema.json"),
                             encoding="utf-8"))
    sub_schema, filled, grounding = {}, {}, {}
    for qf, quote in zip(q_fields, quotes):
        sub_schema[qf] = schema[qf]      # bare question, no adjacent explanation
        filled[qf] = answer
        grounding[qf] = quote
    pre = {"filled_values": filled, "raw_text_fields": set(), "question_grounding": grounding}
    mapped, _ = map_facts_to_form(facts={}, schema=sub_schema, form_id=form_id,
                                  raw_text=raw_text, pre_filled_gpt=pre)
    return {q: mapped.get(q) for q in q_fields}


def _gl_question_fields(n):
    import json, os, re
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    schema = json.load(open(os.path.join(backend_dir, "forms_schemas", "ACORD_126_schema.json"),
                             encoding="utf-8"))
    qcode = re.compile(r"_Question_[A-Za-z0-9]+Code_[A-N]$")
    return [k for k in schema if qcode.search(k)][:n]


def test_quote_reuse_cap_allows_moderate_legitimate_reuse():
    # Five distinct exposure questions all answered "No", all citing the SAME
    # broad negation sentence (a narrow-operations applicant legitimately has
    # none of these exposures). Under the pre-tooltip-fix aggressive cap this
    # blanked every one; now moderate reuse (<= _EVIDENCE_QUOTE_REUSE_MAX)
    # survives so real "No" answers are not thrown away.
    qs = _gl_question_fields(5)
    quote = "No parking facilities are owned or rented by the applicant"
    raw = ("No parking facilities are owned or rented by the applicant; "
           "employees park on the public street.")
    result = _fill_bare_questions(qs, [quote] * len(qs), raw)
    kept = sum(1 for v in result.values() if v is not None)
    assert kept == len(qs), f"expected all {len(qs)} kept, got {kept}: {result}"


def test_quote_reuse_cap_still_blanks_pathological_reuse():
    # Backstop intact: one quote cited as "proof" for far more questions than
    # _EVIDENCE_QUOTE_REUSE_MAX is boilerplate-for-everything, not evidence of
    # any one — all uses are blanked. (Bare/unpaired questions require exact
    # grounding, so a single verbatim quote is used for all of them: it grounds
    # cleanly and forms one cluster whose count exceeds the cap.)
    from services.pdf_service import _EVIDENCE_QUOTE_REUSE_MAX
    n = _EVIDENCE_QUOTE_REUSE_MAX + 3
    qs = _gl_question_fields(n)
    assert len(qs) == n, "need enough real question fields for this test"
    quote = "No parking facilities are owned or rented by the applicant"
    raw = ("No parking facilities are owned or rented by the applicant; "
           "employees park on the public street.")
    result = _fill_bare_questions(qs, [quote] * n, raw)
    kept = sum(1 for v in result.values() if v is not None)
    assert kept == 0, f"expected all blanked past the cap, got {kept}: {result}"


def test_quote_reuse_near_duplicate_clustering_counts_rewordings_together():
    # MECHANISM unit check: reworded copies of one sentence are recognised as
    # the SAME quote by token-Jaccard similarity, so they share a reuse count
    # (exact-string counting would treat each as distinct and undercount).
    from services.pdf_service import _sim_tokens, _is_near_duplicate_text
    a = _sim_tokens("No parking facilities are owned or rented by the applicant")
    b = _sim_tokens("Parking facilities are not owned or rented by the applicant")
    c = _sim_tokens("The applicant leases a fabrication unit with no on-site parking lot")
    assert _is_near_duplicate_text(a, b) is True    # rewording of the same claim
    assert _is_near_duplicate_text(a, c) is False   # a genuinely different sentence


def test_quote_reuse_cap_does_not_punish_a_lone_unique_answer():
    # Regression guard: a genuinely unique quote, cited for exactly ONE
    # question and never reused anywhere else, must survive - the cap targets
    # REUSE, not first-time legitimate grounding.
    qf = "GeneralLiabilityLineOfBusiness_Question_ACACode_A"
    quote = "The applicant confirms it has no exposure to radioactive or nuclear materials of any kind"
    raw = "The applicant confirms it has no exposure to radioactive or nuclear materials of any kind."
    result = _fill_bare_questions([qf], [quote], raw)
    assert result[qf] == "No"


# ── A "Yes" must cite evidence unique to it (borrowed-Yes guard, 2026-07-16) ──
# A genuine "Yes" exposure has its OWN specific sentence in the document. A "Yes"
# whose grounding quote is SHARED with another question is almost always a borrow
# (the model reused a sentence meant for a different question, e.g. citing
# "manufactures to customer specifications" as proof of "foreign products used as
# components"). Affirmatives use a tight reuse cap (_EVIDENCE_YES_QUOTE_REUSE_MAX,
# default 1); negatives keep the generous cap because one broad negation may
# genuinely answer several exposure questions "No".

def test_yes_answer_with_shared_quote_is_blanked():
    # Two "Yes" answers citing the SAME sentence -> both blanked (a real Yes has
    # its own specific evidence; a shared quote is a borrow).
    qs = _gl_question_fields(2)
    quote = "the applicant installs and calibrates custom rack systems on customer sites"
    raw = ("After larger installations, the applicant installs and calibrates custom "
           "rack systems on customer sites prior to final acceptance.")
    result = _fill_bare_questions(qs, [quote, quote], raw, answer="Y")
    assert all(v is None for v in result.values()), result


def test_yes_answer_with_unique_quote_is_kept():
    # A single "Yes" with its own unique, document-present quote survives.
    qf = _gl_question_fields(1)[0]
    quote = "the applicant installs and calibrates custom rack systems on customer sites"
    raw = ("After larger installations, the applicant installs and calibrates custom "
           "rack systems on customer sites prior to final acceptance.")
    result = _fill_bare_questions([qf], [quote], raw, answer="Y")
    assert result[qf] == "Y", result


def test_no_answers_sharing_a_broad_negation_are_not_hit_by_the_yes_cap():
    # The tight cap is Yes-ONLY. Several "No" answers may legitimately share one
    # broad negation sentence — they must survive (this is the fabrication-shop
    # "we have none of these exposures" case).
    qs = _gl_question_fields(3)
    quote = "No parking facilities are owned or rented by the applicant"
    raw = ("No parking facilities are owned or rented by the applicant; "
           "employees park on the public street.")
    result = _fill_bare_questions(qs, [quote] * 3, raw, answer="No")
    assert all(v is not None for v in result.values()), result


# ── Compliance question-text extraction ──────────────────────────────────────

def test_compliance_question_text_extraction():
    from services.pdf_service import _compliance_question_text
    # Question-code shape: pull the actual question out of the boilerplate.
    tu1 = ('Enter Y for a “Yes” response. Input N for “No” response. The response to the '
           'question, "Does applicant install, service or demonstrate products?". ')
    assert _compliance_question_text(tu1) == "Does applicant install, service or demonstrate products?"
    # …YesNoCode_ shape (ACORD 140/25): no "the question," clause.
    tu2 = ('Enter Y for a “Yes” response. Input N for “No” response. Indicates if spoilage '
           'coverage applies. ')
    assert _compliance_question_text(tu2) == "Indicates if spoilage coverage applies"


# ── Compliance pass is authoritative: gate never manufactures a "Yes" ─────────
# for a compliance question the pass left blank, even if the general field-fill
# happened to write a grounded value into its paired Explanation field.

def test_gate_does_not_promote_blank_compliance_question_to_yes():
    import json, os
    import config.settings as settings
    settings.ENABLE_EVIDENCE_GATED_FILL = True
    from services.pdf_service import map_facts_to_form
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    schema = json.load(open(os.path.join(backend_dir, "forms_schemas", "ACORD_126_schema.json"),
                             encoding="utf-8"))
    q_field   = "GeneralLiabilityLineOfBusiness_Question_ABFCode_A"   # products of others under label
    exp_field = "GeneralLiabilityLineOfBusiness_ProductsOfOthersSoldUnderApplicantLabelExplanation_A"
    # The compliance pass left the question blank; the general fill wrote a
    # grounded (but off-topic) sentence into the explanation. The gate must NOT
    # promote the question to "Y" — it must blank the stray explanation instead.
    raw = "Every subcontractor is required to submit a certificate of insurance before work."
    pre = {"filled_values": {exp_field: "Every subcontractor is required to submit a certificate of insurance"},
           "raw_text_fields": set(), "question_grounding": {}}
    sub_schema = {q_field: schema[q_field], exp_field: schema[exp_field]}
    mapped, _ = map_facts_to_form(facts={}, schema=sub_schema, form_id="ACORD_126",
                                  raw_text=raw, pre_filled_gpt=pre)
    assert mapped.get(q_field) is None, mapped.get(q_field)
    assert mapped.get(exp_field) is None, mapped.get(exp_field)


# ── Pairing fallback for Description/Cost-shaped dependent fields ────────────
# (audit finding 2026-07-16): a Question-code field with no adjacent
# "...Explanation" field can still have a genuine dependent detail field
# immediately next, just named "...Description"/"...Cost" instead. Confirmed
# by hand against the REAL question text on every real occurrence across all
# 17 schemas: 6 genuine, 1 confirmed coincidental adjacency (excluded).

def test_pairing_fallback_recognizes_all_confirmed_genuine_cases():
    import json
    from services.pdf_service import _question_explanation_pairs
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def _pairs_for(fname):
        schema = json.load(open(os.path.join(backend_dir, "forms_schemas", fname), encoding="utf-8"))
        return _question_explanation_pairs(schema)

    p126 = _pairs_for("ACORD_126_schema.json")
    assert p126.get("GeneralLiabilityLineOfBusiness_Question_KABCode_A") == "AthleticTeam_SportDescription_A"

    p141 = _pairs_for("ACORD_141_schema.json")
    assert p141.get("CrimeLineOfBusiness_Question_KAUCode_A") == \
        "AuditInformation_PhysicalInventory_FrequencyDescription_A"

    p160 = _pairs_for("ACORD_160_schema.json")
    assert p160.get("BusinessOwnersLineOfBusiness_Question_AADCode_A") == "AthleticTeam_SportDescription_A"
    assert p160.get("BusinessOwnersLineOfBusiness_Question_KADCode_A") == \
        "PropertyItem_ItemDetail_ItemDescription_A"

    p186 = _pairs_for("ACORD_186_schema.json")
    assert p186.get("Contractors_Question_ACFCode_A") == "Contractors_Question_KABExposureDescription_A"
    assert p186.get("Contractors_Question_ADDCode_A") == "Contractors_Question_ACCDescription_A"


def test_pairing_fallback_excludes_confirmed_coincidental_adjacency():
    import json
    from services.pdf_service import _question_explanation_pairs
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    schema = json.load(open(os.path.join(backend_dir, "forms_schemas", "ACORD_141_schema.json"),
                             encoding="utf-8"))
    pairs = _question_explanation_pairs(schema)
    # "Is physical access to the computer room restricted?" has nothing to do
    # with "the complete description of the property including merchandise
    # and stock" - real coincidental adjacency, must stay excluded.
    assert pairs.get("CrimeLineOfBusiness_Question_KBJCode_A") != "CrimeInformation_PropertyDescription_A"


def _fill_hazmat_abatement(exp_value, raw):
    import config.settings as settings
    settings.ENABLE_EVIDENCE_GATED_FILL = True
    from services.pdf_service import map_facts_to_form
    q_field = "Contractors_Question_ACFCode_A"
    exp_field = "Contractors_Question_KABExposureDescription_A"
    schema = {q_field: {"ft": "/Tx", "required": False}, exp_field: {"ft": "/Tx", "required": False}}
    pre = {"filled_values": {exp_field: exp_value}, "raw_text_fields": set(), "question_grounding": {}}
    mapped, _ = map_facts_to_form(facts={}, schema=schema, form_id="ACORD_186",
                                  raw_text=raw, pre_filled_gpt=pre)
    return mapped.get(q_field), mapped.get(exp_field)


def test_acord186_hazmat_abatement_blanked_when_description_is_fabricated():
    # Same bug class as ACORD 127's modified-equipment question, on a
    # different form: before this fix, this field had NO gate at all, so a
    # value with zero basis in the document would have been stamped verbatim.
    # (Note: like every Explanation-paired field in this codebase, the gate
    # verifies the text is genuinely GROUNDED, not that it's topically
    # on-point for this exact question - that stronger check is a documented,
    # deliberate trade-off this project has already made elsewhere, not
    # something this fix newly promises.)
    raw = "The applicant performs general contracting and framing work on residential properties."
    q, exp = _fill_hazmat_abatement(
        "invented asbestos abatement claim with zero basis in the document", raw)
    assert q is None and exp is None


def test_acord186_hazmat_abatement_promoted_when_description_is_genuine():
    raw = "The applicant occasionally performs asbestos abatement work in older commercial buildings."
    q, exp = _fill_hazmat_abatement("asbestos abatement work in older commercial buildings", raw)
    assert q == "Y" and exp == "asbestos abatement work in older commercial buildings"
