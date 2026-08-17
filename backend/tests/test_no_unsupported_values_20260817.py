"""2026-08-17 - "ACORD 125 and 127 contain no unsupported critical values".

Every unsupported value the client found on the 08/17 run, pinned. All through
the real `map_facts_to_form` / `compute_form_gaps` against the real schemas.

THE LIVE-LLM TRAP: every map_facts_to_form call MUST pass `pre_filled_gpt`.
Omitting it routes onto the legacy per-form branch, which fires real LLM calls.
"""
import json
import os
import re

import pytest

import services.pdf_service as P

_HERE = os.path.dirname(os.path.abspath(__file__))


def _schema(fid):
    with open(os.path.join(_HERE, "..", "forms_schemas", f"{fid}_schema.json"),
              encoding="utf-8") as fh:
        return json.load(fh)


def _f(v):
    return {"value": v, "confidence": 0.9}


def _env(vals=None):
    return {"filled_values": dict(vals or {}), "raw_text_fields": set(),
            "question_grounding": {}}


def _fill(fid, facts, inject=None):
    mapped, _ = P.map_facts_to_form(
        dict(facts), _schema(fid), form_id=fid,
        raw_text="POLICY 6E7-40-02---26 BBC7263 - 26",
        pre_filled_gpt=_env(inject))
    return mapped


def _asked(fid, facts):
    _, unmatched, _ = P.compute_form_gaps(fid, _schema(fid), dict(facts))
    return set(unmatched)


# The delivered 08/17 shape: numbers stated, NO premium captured, one policy
# printed two ways, and a coverage PART sitting among the lines.
def _run_facts(**over):
    facts = {
        "applicant_name": _f("Orbin Contracting LLC"),
        "policy_number": _f("6E7-40-02---26"),
        "coverage_lines": [
            {"line": "Liability", "policy_number": "BBC7263 - 26"},
            {"line": "Inland Marine", "policy_number": "6C7-40-02---26"},
            {"line": "Business Auto", "policy_number": "6E74002"},
            {"line": "Covered Autos Liability", "policy_number": "6E7-40-02---26"},
            {"line": "Commercial Liability Umbrella",
             "policy_number": "6J7-40-02---26"},
        ],
    }
    facts.update(over)
    return facts


class TestPackageHeaderNeverTakesOneLinesNumber:
    def test_the_auto_number_is_not_the_package_number(self):
        assert not _fill("ACORD_125", _run_facts()).get(
            "Policy_PolicyNumberIdentifier_A")

    def test_it_is_not_asked_either(self):
        assert "Policy_PolicyNumberIdentifier_A" not in _asked(
            "ACORD_125", _run_facts())

    def test_a_real_single_policy_package_still_stamps(self):
        facts = _run_facts(policy_number=_f("PKG-1"), coverage_lines=[
            {"line": "Commercial General Liability", "premium": "$1",
             "policy_number": "PKG-1"},
            {"line": "Business Auto", "premium": "$2", "policy_number": "PKG-1"}])
        assert _fill("ACORD_125", facts).get(
            "Policy_PolicyNumberIdentifier_A") == "PKG-1"

    def test_legacy_session_keeps_the_scalar(self):
        facts = _run_facts()
        facts.pop("coverage_lines")
        assert _fill("ACORD_125", facts).get(
            "Policy_PolicyNumberIdentifier_A") == "6E7-40-02---26"


class TestOnePolicyPrintedTwiceIsOnePolicy:
    @pytest.mark.parametrize("a,b,same", [
        ("6E74002", "6E7-40-02---26", True),
        ("BBC7263", "BBC7263 - 26", True),
        ("6E74002", "6E74002", True),
        ("6C7-40-02---26", "6J7-40-02---26", False),
        ("POL123", "POL12345", False),        # digits run together: two policies
        ("ABC12", "ABC1234", False),
        ("6E74002", "6C7-40-02---26", False),
    ])
    def test_contract_equivalence(self, a, b, same):
        assert P._same_policy_contract(a, b) is same

    def test_q4_lists_each_policy_once_and_keeps_the_umbrella(self):
        mapped = _fill("ACORD_125", _run_facts())
        pairs = {str(mapped.get(f"OtherPolicy_LineOfBusinessCode_{r}") or ""):
                 str(mapped.get(f"OtherPolicy_PolicyNumberIdentifier_{r}") or "")
                 for r in "ABCD"}
        pairs.pop("", None)
        assert "Commercial Liability Umbrella" in pairs, \
            "the umbrella was displaced by a duplicate printing of the auto policy"
        assert "Covered Autos Liability" not in pairs, \
            "a coverage part is not other insurance"
        assert pairs.get("Business Auto") == "6E74002"
        assert len(pairs) == 4

    def test_no_row_carries_a_number_without_its_line(self):
        mapped = _fill("ACORD_125", _run_facts())
        for r in "ABCD":
            line = str(mapped.get(f"OtherPolicy_LineOfBusinessCode_{r}") or "")
            num = str(mapped.get(f"OtherPolicy_PolicyNumberIdentifier_{r}") or "")
            assert bool(line) == bool(num), f"row {r} is half a relationship"


class TestLinesOfBusinessGridIsEvidenceDriven:
    def _boxes(self, fid="ACORD_125"):
        schema = _schema(fid)
        return [k for k in schema if k.startswith("Policy_LineOfBusiness_")
                and schema[k].get("ft") == "/Btn" and "Other" not in k]

    def test_cyber_is_not_ticked_from_a_general_liability_exclusion(self):
        mapped = _fill("ACORD_125", _run_facts(),
                       {"Policy_LineOfBusiness_CyberAndPrivacy_A": "Yes"})
        assert not mapped.get("Policy_LineOfBusiness_CyberAndPrivacy_A")

    def test_no_enumerated_box_is_asked_of_the_model(self):
        asked = _asked("ACORD_125", _run_facts())
        assert not [b for b in self._boxes() if b in asked]

    def test_a_bare_liability_row_does_not_tick_three_boxes(self):
        """'Liability' fits General, Fiduciary AND Liquor - so it places none."""
        mapped = _fill("ACORD_125", _run_facts())
        assert not mapped.get("Policy_LineOfBusiness_FiduciaryLiabilityIndicator_A")
        assert not mapped.get("Policy_LineOfBusiness_LiquorLiabilityIndicator_A")

    def test_the_lines_the_package_does_carry_still_tick(self):
        mapped = _fill("ACORD_125", _run_facts())
        for box in ("BusinessAutoIndicator", "CommercialInlandMarineIndicator",
                    "UmbrellaIndicator"):
            assert mapped.get(f"Policy_LineOfBusiness_{box}_A") == "Yes", box

    def test_an_existing_flag_still_ticks_its_box(self):
        mapped = _fill("ACORD_125", _run_facts(has_general_liability=_f("yes")))
        assert mapped.get(
            "Policy_LineOfBusiness_CommercialGeneralLiability_A") == "Yes"

    def test_legacy_session_behaviour_is_unchanged(self):
        facts = _run_facts(has_cyber=_f("yes"))
        facts.pop("coverage_lines")
        assert _fill("ACORD_125", facts).get(
            "Policy_LineOfBusiness_CyberAndPrivacy_A") == "Yes"


class TestMemberManagerCount:
    def test_it_is_never_filled(self):
        mapped = _fill("ACORD_125", _run_facts(entity_type=_f("llc")),
                       {"NamedInsured_LegalEntity_MemberManagerCount_A": "1"})
        assert not mapped.get("NamedInsured_LegalEntity_MemberManagerCount_A")

    def test_it_is_not_asked(self):
        assert "NamedInsured_LegalEntity_MemberManagerCount_A" not in _asked(
            "ACORD_125", _run_facts(entity_type=_f("llc")))

    def test_the_llc_box_itself_is_untouched(self):
        mapped = _fill("ACORD_125", _run_facts(entity_type=_f("llc")))
        assert mapped.get(
            "NamedInsured_LegalEntity_LimitedLiabilityCorporationIndicator_A") == "Yes"


class TestElidedQuoteIsNotACitation:
    ELIDED = re.compile(r"\.\.\.|…")
    CLIENT_Q8 = ("Blanket Additional Insured status ... on a primary and "
                 "noncontributory basis when required as an additional insured "
                 "under the contract agreement.")

    def test_the_client_q8_quote_is_elided(self):
        assert self.ELIDED.search(self.CLIENT_Q8)

    @pytest.mark.parametrize("quote", [
        "The applicant does not have any subsidiaries.",
        "Subcontractors are required to carry coverage.",
        "Crime Coverage Policy No. BBC7263",
        "COMPREHENSIVE ACV 1000 DED",
        "PRIV PASSENGER - COMM CLASS: 7383",
        "There is no nightclub, no dance floor, and no live entertainment.",
        "A judgment was entered against the applicant in 2023.",
    ])
    def test_real_evidence_contains_no_ellipsis(self, quote):
        assert not self.ELIDED.search(quote)

    def test_the_gate_actually_carries_the_rule(self):
        src = os.path.join(_HERE, "..", "services", "pdf_service.py")
        with open(src, encoding="utf-8") as fh:
            assert "elided_quote" in fh.read()
