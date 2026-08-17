"""2026-08-18 - the three unsupported values left on ACORD 125/127.

Evidence: the client's 08/17 run plus its dec index (338 verified declarations
entries). Each fix here closed a defect that had SURVIVED a previous fix aimed
at the same thing, so every test names the door the defect came back through.

TWO KINDS OF TEST IN HERE, ON PURPOSE - and the difference decides whether a
test may carry this client's literal values:

  * REGRESSION tests replay the reported case VERBATIM ("6E7-40-02---26",
    "loss.mary an", the Q8 quote). The literals are the point: a fix can pass
    every generic test and still fail the case that was reported, which has
    happened on this arc more than once.
  * RULE tests must NOT carry them, because none of these rules depends on a
    carrier's numbering. They use neutral or varied values - other carriers'
    formats, arbitrary padding, arbitrary sentence shapes - so that the test
    asserts the rule rather than the sample.

NO PRODUCTION CODE CONTAINS A CLIENT VALUE. Verified by tokenising services/,
utils/, routes/, config/, models/ and repositories/ and discarding comments and
docstrings: 0 client literals in executable code. The rules are shapes - "is the
term marker printed separated", "is this quantity zero-padded", "is the
grammatical subject an instrument noun".

THE LIVE-LLM TRAP: every map_facts_to_form call MUST pass `pre_filled_gpt`.
"""
import json
import os

import pytest

import services.pdf_service as P

_HERE = os.path.dirname(os.path.abspath(__file__))


def _schema(fid):
    with open(os.path.join(_HERE, "..", "forms_schemas", f"{fid}_schema.json"),
              encoding="utf-8") as fh:
        return json.load(fh)


def _f(v):
    return {"value": v, "confidence": 0.9}


def _fill(fid, facts, inject=None):
    mapped, _ = P.map_facts_to_form(
        dict(facts), _schema(fid), form_id=fid, raw_text="RADIUS NA",
        pre_filled_gpt={"filled_values": dict(inject or {}),
                        "raw_text_fields": set(), "question_grounding": {}})
    return mapped


def _asked(fid, facts):
    _, unmatched, _ = P.compute_form_gaps(fid, _schema(fid), dict(facts))
    return set(unmatched)


_HDR = "Policy_PolicyNumberIdentifier_A"

# The four policies in the client's package, as the dec index records them.
_DEC = [{"label": "Policy Number", "value": "6C7-40-02---26",
         "policy_number": "6C7-40-02---26"},
        {"label": "Policy Number", "value": "BBC7263 - 26",
         "policy_number": "BBC7263 - 26"},
        {"label": "Policy Number", "value": "6E7-40-02---26",
         "policy_number": "6E7-40-02---26"},
        {"label": "Policy Number", "value": "6J7-40-02---26",
         "policy_number": "6J7-40-02---26"}]


class TestPackageHeaderCountsPoliciesNotOneFactsOpinion:
    """Round 14 counted only `coverage_lines`. The 08/17 run then printed the
    Auto number again, because that run's numbers arrived through
    `underlying_policies` and the dec index instead."""

    def test_numbers_arriving_only_in_the_dec_index_still_blank_the_header(self):
        facts = {"applicant_name": _f("Orbin Contracting LLC"),
                 "policy_number": _f("6E7-40-02---26"),
                 "coverage_lines": [{"line": "General Liability", "premium": "$3,954"},
                                    {"line": "Commercial Auto", "premium": "$2,991"}],
                 "dec_page_entries": _DEC}
        assert not _fill("ACORD_125", facts).get(_HDR)
        assert _HDR not in _asked("ACORD_125", facts)

    def test_numbers_arriving_only_in_underlying_policies_blank_it_too(self):
        facts = {"applicant_name": _f("Orbin Contracting LLC"),
                 "policy_number": _f("6E7-40-02---26"),
                 "coverage_lines": [{"line": "General Liability", "premium": "$3,954"}],
                 "underlying_policies": [
                     {"line": "Business Auto", "policy_no": "6E74002"},
                     {"line": "General Liability", "policy_no": "BBC7263"}]}
        assert not _fill("ACORD_125", facts).get(_HDR)

    def test_numbers_arriving_only_in_the_prior_grid_blank_it_too(self):
        facts = {"applicant_name": _f("Orbin Contracting LLC"),
                 "policy_number": _f("6E7-40-02---26"),
                 "prior_coverage_by_line": [
                     {"line": "General Liability", "policy_no": "BBC7263"},
                     {"line": "Business Auto", "policy_no": "6E74002"}]}
        assert not _fill("ACORD_125", facts).get(_HDR)

    def test_one_policy_printed_two_ways_is_one_policy_and_still_stamps(self):
        facts = {"applicant_name": _f("Orbin Contracting LLC"),
                 "policy_number": _f("BBC7263"),
                 "coverage_lines": [
                     {"line": "General Liability", "premium": "$1",
                      "policy_number": "BBC7263"},
                     {"line": "Business Auto", "premium": "$2",
                      "policy_number": "BBC7263"}],
                 "dec_page_entries": [
                     {"label": "Policy Number", "value": "BBC7263",
                      "policy_number": "BBC7263"},
                     {"label": "Policy Number", "value": "BBC7263 - 26",
                      "policy_number": "BBC7263 - 26"}]}
        assert _fill("ACORD_125", facts).get(_HDR) == "BBC7263"

    def test_a_session_with_no_per_line_evidence_is_untouched(self):
        facts = {"applicant_name": _f("Orbin Contracting LLC"),
                 "policy_number": _f("6E7-40-02---26")}
        assert _fill("ACORD_125", facts).get(_HDR) == "6E7-40-02---26"

    def test_the_count_reads_every_source_the_forms_read(self):
        """Anti-rot: a future per-line policy source must be counted here too,
        or this defect returns through door number four.

        NEUTRAL VALUES ON PURPOSE. This test is about WHICH SOURCES are read,
        not about any carrier's numbering, so using the client's numbers here
        would imply the rule depends on them. It does not - see
        test_the_rule_holds_for_other_carriers_numbering below.
        """
        found = P._distinct_package_policies(
            {"underlying_policies": [{"policy_no": "AAAA-1"}],
             "dec_page_entries": [{"policy_number": "BBBB-2"}],
             "prior_coverage_by_line": [{"policy_no": "CCCC-3"}],
             "coverage_lines": [{"policy_number": "DDDD-4"}]})
        # Order is not part of the contract - one policy per source is.
        assert set(found) == {"AAAA-1", "BBBB-2", "CCCC-3", "DDDD-4"}

    @pytest.mark.parametrize("numbers,expected", [
        # Arbitrary carrier conventions, none of them this client's. A package
        # is multi-policy whenever its sources name more than one CONTRACT.
        (["GL-2024-00815", "BA-2024-00816"], 2),
        (["WC1234567", "CPP7654321", "UMB0001122"], 3),
        (["77-CBP-901234"], 1),
        # ...and one contract printed with and without its term marker stays ONE,
        # whatever the carrier's format.
        (["GL-2024-00815", "GL-2024-00815 - 26"], 1),
        (["WC1234567", "WC1234567-25"], 1),
        # Digits running together are two policies, not a term marker.
        (["TX-100", "TX-10025"], 2),
    ])
    def test_the_rule_holds_for_other_carriers_numbering(self, numbers, expected):
        found = P._distinct_package_policies(
            {"dec_page_entries": [{"policy_number": n} for n in numbers]})
        assert len(found) == expected, found

    @pytest.mark.parametrize("form_no", [
        "CA 00 01 10 13", "CG 00 01 04 13", "IL 00 17 11 98", "CG 20 10 12 19",
    ])
    def test_an_iso_form_number_is_never_counted_as_a_policy(self, form_no):
        assert P._distinct_package_policies(
            {"dec_page_entries": [{"policy_number": form_no}]}) == []


class TestAQuantityIsNeverZeroPadded:
    """RADIUS printed 07 - the comp/collision symbol - while the auto dec states
    RADIUS = NA twice."""

    def _facts(self):
        return {"applicant_name": _f("Orbin Contracting LLC"),
                "auto_vin_schedule": [{"vin": "4S4BRCGC9C3217772"}],
                "auto_covered_symbols": [
                    {"coverage": "Comprehensive", "symbols": [7]},
                    {"coverage": "Collision", "symbols": [7]}]}

    @pytest.mark.parametrize("field", ["Vehicle_RadiusOfUse_A",
                                       "Vehicle_SeatingCapacityCount_A"])
    def test_a_zero_padded_code_is_rejected(self, field):
        assert not _fill("ACORD_127", self._facts(), {field: "07"}).get(field)

    @pytest.mark.parametrize("value", ["7", "50", "200", "1"])
    def test_a_real_radius_survives_even_when_it_equals_the_symbol(self, value):
        """The first cut compared RADIUS to the symbol cell and deleted a
        genuine 7-mile radius on a vehicle whose symbol is 7. The padding is the
        tell; the sibling is not."""
        assert _fill("ACORD_127", self._facts(),
                     {"Vehicle_RadiusOfUse_A": value}).get(
                         "Vehicle_RadiusOfUse_A") == value

    @pytest.mark.parametrize("value", ["5", "15", "7"])
    def test_a_real_seating_capacity_survives(self, value):
        assert _fill("ACORD_127", self._facts(),
                     {"Vehicle_SeatingCapacityCount_A": value}).get(
                         "Vehicle_SeatingCapacityCount_A") == value

    def test_the_code_column_borrows_still_fire(self):
        facts = dict(self._facts(), gl_class_code_schedule=[{"class_code": "91580"}])
        mapped = _fill("ACORD_127", facts,
                       {"Vehicle_SpecialIndustryClassCode_A": "91580",
                        "Vehicle_NetRatingFactor_A": "07"})
        assert not mapped.get("Vehicle_SpecialIndustryClassCode_A")
        assert not mapped.get("Vehicle_NetRatingFactor_A")


class TestQ8HoldHarmless:
    """Two independent faults in one answer, so two independent rules."""

    CLIENT = ("Additional insured provisions apply when required by written "
              "contract, written agreement, or written permit; insurance is prid "
              "will not seek contribution when agreed in writing; waiver of "
              "recovery applies only when agreed in writing and executed prior "
              "to loss.mary an")

    def test_the_stitch_seam_is_detected(self):
        assert P._quote_has_a_concatenation_seam(self.CLIENT)

    def test_the_policy_provision_subject_is_detected(self):
        assert P._POLICY_SELF_SUBJECT_RE.search(self.CLIENT)

    @pytest.mark.parametrize("quote", [
        "Additional insured provisions apply when required by written contract.",
        "Waiver of recovery applies only when agreed in writing.",
        "Blanket waiver of subrogation applies when required by contract.",
        "Coverage applies to leased autos only.",
        "These conditions apply to all covered autos.",
        "This exclusion applies even if the claims allege negligence.",
    ])
    def test_a_bare_instrument_noun_subject_is_contract_language(self, quote):
        assert P._POLICY_SELF_SUBJECT_RE.search(quote)

    @pytest.mark.parametrize("quote", [
        # The LEGITIMATE Yes for this very question - it must survive.
        "The applicant signed a hold harmless agreement with the general contractor.",
        "The applicant has waivers of subrogation in place with three general contractors.",
        "The applicant does not have any subsidiaries.",
        "Subcontractors are required to carry coverage.",
        "This policy was cancelled for non-payment in 2022.",
        "The applicant transports hazardous materials to job sites.",
        "No parking facilities are owned or rented by the applicant.",
        "A judgment was entered against the applicant in 2023.",
        "Employees use personal vehicles for company errands twice weekly.",
        "The insured hauls construction debris within a 50 mile radius.",
        "Crime Coverage Policy No. BBC7263",
        "COMPREHENSIVE ACV 1000 DED",
        "There is no nightclub, no dance floor, and no live entertainment.",
        # ACORD's OWN tooltip. Making the determiner optional flagged 14 of
        # these until adjacency was required; test_no_acord_tooltip_is_flagged
        # is the full 5,852-tooltip sweep that caught it.
        "Enter deductible: The deductible amount that is to apply to this "
        "subject of insurance.",
    ])
    def test_real_evidence_and_acord_wording_survive(self, quote):
        assert not P._POLICY_SELF_SUBJECT_RE.search(quote)
        assert not P._quote_has_a_concatenation_seam(quote)

    @pytest.mark.parametrize("quote", [
        "Contact us at www.orbin.com for details.",
        "Write to claims@emcins.com within 30 days.",
        "See https://emcins.com/forms for the schedule.",
    ])
    def test_a_url_or_email_is_not_a_seam(self, quote):
        assert not P._quote_has_a_concatenation_seam(quote)

    def test_the_gate_carries_both_rules(self):
        with open(os.path.join(_HERE, "..", "services", "pdf_service.py"),
                  encoding="utf-8") as fh:
            src = fh.read()
        assert "stitched_quote" in src
        assert "elided_quote" in src
