"""Round 13 - the 2026-08-16 client audit of the fresh Orbin run.

Every test drives the REAL production path (`map_facts_to_form` /
`compute_form_gaps` against the real schemas) with the client's literal values.
Resolver-level assertions have proven twice not to reflect what ships.

THE LIVE-LLM TRAP: every `map_facts_to_form` call MUST pass `pre_filled_gpt`.
Omitting it routes onto the legacy per-form branch, which fires real LLM calls -
non-deterministic, billable, and a multi-minute hang.
"""
import json
import os
import re

import pytest

import services.pdf_service as P

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCHEMAS = os.path.join(_HERE, "..", "forms_schemas")


def _schema(form_id):
    with open(os.path.join(_SCHEMAS, f"{form_id}_schema.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _env(values=None):
    return {"filled_values": dict(values or {}), "raw_text_fields": set(),
            "question_grounding": {}}


def _f(v):
    return {"value": v, "confidence": 0.9}


_RAW = ("COMMERCIAL PACKAGE DECLARATIONS. POLICY PERIOD 07/15/25 TO 07/15/26. "
        "ORBIN CONTRACTING LLC, 4800 DAHLIA ST # D13, DENVER CO 80216-3121. "
        "EMPLOYERS MUTUAL CASUALTY COMPANY. EMC Property & Casualty Company.")


def _fill(form_id, facts, injected=None):
    mapped, _ = P.map_facts_to_form(dict(facts), _schema(form_id),
                                    form_id=form_id, raw_text=_RAW,
                                    pre_filled_gpt=_env(injected))
    return mapped


def _asked(form_id, facts):
    _, unmatched, _ = P.compute_form_gaps(form_id, _schema(form_id), dict(facts))
    return set(unmatched)


# The fact shape of the delivered 2026-08-16 run, derived FROM the PDFs: the
# 131 underlying grid printed both numbers with terms, `underlying_policies`
# carries no dates, and Q4 printed only the two lines whose own entry had a
# number. So coverage_lines lost the auto/GL numbers and the dedicated fact
# kept them.
def _run_facts(**over):
    facts = {
        "applicant_name": _f("Orbin Contracting LLC"),
        "carrier_name": _f("Employers Mutual Casualty Company"),
        "is_renewal": _f("true"),
        "effective_date": _f("07/15/2026"),
        "expiration_date": _f("07/15/2027"),
        "prior_effective_date": _f("07/15/2025"),
        "prior_expiration_date": _f("07/15/2026"),
        "coverage_lines": [
            {"line": "Commercial General Liability", "premium": "$3,954",
             "carrier": "EMC Property & Casualty Company"},
            {"line": "Business Auto", "premium": "$2,991",
             "carrier": "Employers Mutual Casualty Company"},
            {"line": "Commercial Inland Marine", "premium": "$300",
             "policy_number": "6C7-40-02---26"},
            {"line": "Commercial Liability Umbrella", "premium": "$3,418",
             "policy_number": "6J7-40-02---26"},
        ],
        "underlying_policies": [
            {"line": "Business Auto", "limit": "$1,000,000",
             "carrier": "Employers Mutual Casualty Company", "policy_no": "6E74002"},
            {"line": "General Liability", "limit": "$1,000,000",
             "carrier": "EMC Property & Casualty Company", "policy_no": "BBC7263"},
        ],
    }
    facts.update(over)
    return facts


# ── Fix 1: `underlying_policies` is per-line evidence on every surface ───────

class TestUnderlyingPoliciesReachesEverySurface:
    def test_127_header_carries_its_own_line_number(self):
        """The reported regression: blank, while ACORD 131 printed 6E74002
        from the very fact the 127 header never asked."""
        mapped = _fill("ACORD_127", _run_facts())
        assert mapped.get("Policy_PolicyNumberIdentifier_A") == "6E74002"

    def test_131_still_prints_both_underlying_rows_correctly_paired(self):
        mapped = _fill("ACORD_131", _run_facts())
        assert mapped.get("UnderlyingPolicy_Automobile_PolicyNumberIdentifier_A") == "6E74002"
        assert mapped.get("UnderlyingPolicy_GeneralLiability_PolicyNumberIdentifier_A") == "BBC7263"

    def test_131_header_keeps_the_umbrellas_own_number(self):
        """The umbrella is never underlying to itself, so no underlying row may
        ever supply the 131 header - the client's defect #1."""
        mapped = _fill("ACORD_131", _run_facts())
        assert mapped.get("Policy_PolicyNumberIdentifier_A") == "6J7-40-02---26"

    def test_q4_grid_prints_all_four_policies(self):
        mapped = _fill("ACORD_125", _run_facts())
        pairs = {
            str(mapped.get(f"OtherPolicy_LineOfBusinessCode_{r}") or ""):
            str(mapped.get(f"OtherPolicy_PolicyNumberIdentifier_{r}") or "")
            for r in "ABCD"
        }
        assert pairs.get("Business Auto") == "6E74002"
        assert pairs.get("Commercial General Liability") == "BBC7263"
        assert pairs.get("Commercial Inland Marine") == "6C7-40-02---26"
        assert pairs.get("Commercial Liability Umbrella") == "6J7-40-02---26"

    def test_a_corrupt_umbrella_row_never_feeds_a_section_header(self):
        facts = _run_facts(underlying_policies=[
            {"line": "Commercial Liability Umbrella", "carrier": "X",
             "policy_no": "WRONG-9999"}])
        mapped = _fill("ACORD_131", facts)
        assert mapped.get("Policy_PolicyNumberIdentifier_A") == "6J7-40-02---26"

    def test_a_form_number_is_never_accepted(self):
        facts = _run_facts(underlying_policies=[
            {"line": "Business Auto", "policy_no": "CA 00 01 10 13"}])
        mapped = _fill("ACORD_127", facts)
        assert not mapped.get("Policy_PolicyNumberIdentifier_A")

    def test_two_disagreeing_rows_for_one_line_settle_nothing(self):
        facts = _run_facts(underlying_policies=[
            {"line": "Business Auto", "policy_no": "6E74002"},
            {"line": "Business Auto", "policy_no": "9Z99999"}])
        mapped = _fill("ACORD_127", facts)
        assert not mapped.get("Policy_PolicyNumberIdentifier_A")

    def test_no_underlying_fact_leaves_legacy_behaviour_untouched(self):
        facts = _run_facts()
        facts.pop("underlying_policies")
        mapped = _fill("ACORD_127", facts)
        assert not mapped.get("Policy_PolicyNumberIdentifier_A")


class TestPriorCarrierGridOnARenewal:
    def test_grid_derives_from_the_expiring_underlying_policies(self):
        mapped = _fill("ACORD_125", _run_facts())
        # Carrier names are compared case-insensitively: display
        # canonicalisation title-cases them on the way to the page, which is
        # cosmetic and not what this test is about.
        assert (mapped.get("PriorCoverage_GeneralLiability_InsurerFullName_A") or "").lower() == \
            "emc property & casualty company"
        assert mapped.get("PriorCoverage_GeneralLiability_PolicyNumberIdentifier_A") == "BBC7263"
        assert (mapped.get("PriorCoverage_Automobile_InsurerFullName_A") or "").lower() == \
            "employers mutual casualty company"
        assert mapped.get("PriorCoverage_Automobile_PolicyNumberIdentifier_A") == "6E74002"

    def test_the_expiring_term_is_stamped_never_the_proposed_one(self):
        """Client requirement 6: expiring, proposed and application dates stay
        distinct. The prior grid is the EXPIRING term by definition."""
        mapped = _fill("ACORD_125", _run_facts())
        assert mapped.get("PriorCoverage_GeneralLiability_EffectiveDate_A") == "07/15/2025"
        assert mapped.get("PriorCoverage_GeneralLiability_ExpirationDate_A") == "07/15/2026"

    def test_premium_is_never_invented(self):
        mapped = _fill("ACORD_125", _run_facts())
        assert not mapped.get("PriorCoverage_GeneralLiability_TotalPremiumAmount_A")

    def test_not_a_renewal_derives_nothing(self):
        facts = _run_facts(is_renewal=_f("false"))
        mapped = _fill("ACORD_125", facts)
        assert not mapped.get("PriorCoverage_Automobile_PolicyNumberIdentifier_A")

    def test_no_routed_prior_term_derives_nothing(self):
        facts = _run_facts()
        facts.pop("prior_effective_date")
        mapped = _fill("ACORD_125", facts)
        assert not mapped.get("PriorCoverage_Automobile_PolicyNumberIdentifier_A")

    def test_a_real_prior_fact_still_wins(self):
        facts = _run_facts(prior_coverage_by_line=[
            {"line": "General Liability", "carrier": "Old Mutual",
             "policy_no": "OLD-123", "effective": "07/15/2024",
             "expiration": "07/15/2025"}])
        mapped = _fill("ACORD_125", facts)
        assert mapped.get("PriorCoverage_GeneralLiability_PolicyNumberIdentifier_A") == "OLD-123"


# ── Fix 2: a line of business must be proven, not merely unrefuted ──────────

class TestOtherLineOfBusinessNeedsPositiveEvidence:
    @pytest.mark.parametrize("name", [
        "Premium for Attached Items 4.",     # the client's literal row
        "Premium for Endorsements",          # the client's literal row
        "Drive Other Car",                   # the previous run's fabrication
        "Total Advance Premium",
        "Terrorism Surcharge",
    ])
    def test_a_premium_label_is_not_a_line_of_business(self, name):
        facts = _run_facts()
        facts["coverage_lines"] = facts["coverage_lines"] + [
            {"line": name, "premium": "$322"}]
        mapped = _fill("ACORD_125", facts)
        printed = {str(mapped.get(
            f"Policy_LineOfBusiness_OtherLineOfBusinessDescription_{r}") or "")
            for r in "ABCDEF"}
        assert name not in printed

    @pytest.mark.parametrize("name", [
        "Employment Practices Liability", "Kidnap and Ransom Liability",
    ])
    def test_a_genuine_specialty_line_still_prints(self, name):
        facts = _run_facts()
        facts["coverage_lines"] = facts["coverage_lines"] + [
            {"line": name, "premium": "$1,200", "policy_number": "SPEC-1"}]
        mapped = _fill("ACORD_125", facts)
        printed = {str(mapped.get(
            f"Policy_LineOfBusiness_OtherLineOfBusinessDescription_{r}") or "")
            for r in "ABCDEF"}
        assert name in printed

    @pytest.mark.parametrize("name", [
        "Pollution Liability", "Professional Liability",
        "Employee Benefits Liability",
    ])
    def test_the_pre_existing_coverage_part_denylist_still_owns_these(self, name):
        """MEASURED, not endorsed. The positive test says these ARE lines of
        business, but the older coverage-PART denylist drops them first because
        "pollution" / "professional" / "benefits" all appear in ACORD's own
        Coverage-family field names. That predates this round and is left
        alone: loosening it would print MORE values, which is the opposite of
        what the client asked for. Pinned so the behaviour is a decision rather
        than a surprise the next time someone reads _other_lob_row_names."""
        assert P._names_a_line_of_business(name)
        facts = _run_facts()
        facts["coverage_lines"] = facts["coverage_lines"] + [
            {"line": name, "premium": "$1,200", "policy_number": "SPEC-1"}]
        printed = {str(_fill("ACORD_125", facts).get(
            f"Policy_LineOfBusiness_OtherLineOfBusinessDescription_{r}") or "")
            for r in "ABCDEF"}
        assert name not in printed

    def test_the_indicator_and_the_description_move_together(self):
        facts = _run_facts()
        facts["coverage_lines"] = facts["coverage_lines"] + [
            {"line": "Premium for Endorsements", "premium": "$457"}]
        mapped = _fill("ACORD_125", facts)
        for r in "ABCDEF":
            if not mapped.get(f"Policy_LineOfBusiness_OtherLineOfBusinessDescription_{r}"):
                assert not mapped.get(f"Policy_LineOfBusiness_OtherIndicator_{r}")


# ── Fix 3: the physical-damage deductibles, and ACV in a dollar box ─────────

class TestVehicleDeductiblesAndValuation:
    def _auto_facts(self, **over):
        facts = {
            "applicant_name": _f("Orbin Contracting LLC"),
            "auto_deductible_comp": _f("$1,000"),
            "auto_deductible_collision": _f("$1,000"),
            "auto_vin_schedule": [{"vin": "4S4BRCGC9C3217772", "year": "2012",
                                   "make": "Subaru", "model": "Outback"}],
        }
        facts.update(over)
        return facts

    def test_both_deductibles_stamp_on_the_real_row(self):
        mapped = _fill("ACORD_127", self._auto_facts())
        assert mapped.get(
            "Vehicle_Coverage_ComprehensiveOrSpecifiedCauseOfLossDeductibleAmount_A") == "$1,000"
        assert mapped.get("Vehicle_Collision_DeductibleAmount_A") == "$1,000"

    def test_a_phantom_row_stays_blank(self):
        mapped = _fill("ACORD_127", self._auto_facts())
        assert not mapped.get(
            "Vehicle_Coverage_ComprehensiveOrSpecifiedCauseOfLossDeductibleAmount_B")

    def test_no_fleet_evidence_changes_nothing(self):
        facts = self._auto_facts()
        facts.pop("auto_vin_schedule")
        mapped = _fill("ACORD_127", facts)
        assert not mapped.get("Vehicle_Collision_DeductibleAmount_A")

    def test_acv_does_not_land_in_the_amount_box(self):
        """The client's literal case: the word ACV in the AA/ST AMT box while
        the ACV checkbox two cells away stayed unticked."""
        mapped = _fill("ACORD_127", self._auto_facts(),
                       {"Vehicle_Coverage_AgreedOrStatedAmount_A": "ACV"})
        assert not mapped.get("Vehicle_Coverage_AgreedOrStatedAmount_A")

    def test_a_real_stated_amount_survives(self):
        mapped = _fill("ACORD_127", self._auto_facts(),
                       {"Vehicle_Coverage_AgreedOrStatedAmount_A": "$26,680"})
        assert mapped.get("Vehicle_Coverage_AgreedOrStatedAmount_A") == "$26,680"


class TestAmountConventionsSurviveTheCheckboxRule:
    """C46's lesson as an executable guard: this rule must never blank a value
    convention. The first cut rejected 'Included' on 73 ACORD 160 fields."""

    @pytest.mark.parametrize("value", [
        "Included", "Statutory", "Excluded", "Waived", "See schedule", "N/A",
        "None", "Refer to policy", "INCLUDED", "STATUTORY", "TBD", "NIL",
    ])
    def test_no_amount_convention_is_ever_rejected(self, value):
        offenders = []
        for form_id in ("ACORD_160", "ACORD_28", "ACORD_140", "ACORD_127",
                        "ACORD_125", "ACORD_131"):
            schema = _schema(form_id)
            for fname, meta in schema.items():
                if not isinstance(meta, dict):
                    continue
                if P._tooltip_declared_type(meta) not in (
                        "amount", "limit", "deductible", "percentage", "rate"):
                    continue
                if P._rejects_declared_type(fname, meta, value, schema) and not \
                        P._rejects_declared_type(fname, meta, value):
                    offenders.append(f"{form_id}:{fname}")
        assert not offenders, f"{value!r} newly rejected on {offenders[:5]}"


# ── Fix 4: the umbrella is not underlying to itself ────────────────────────

class TestUnderlyingCoverageGrid:
    def test_the_umbrella_is_never_its_own_underlying_coverage(self):
        mapped = _fill("ACORD_131", _run_facts())
        descs = {str(mapped.get(f"UnderlyingCoverage_Coverage_OtherDescription_{r}") or "")
                 for r in "ABCD"}
        assert "Commercial Liability Umbrella" not in descs

    def test_additional_interests_is_never_ticked(self):
        """No fact in the registry can state it, so anything there is invented."""
        mapped = _fill("ACORD_131", _run_facts(),
                       {"UnderlyingCoverage_Coverage_AdditionalInterestsIndicator_A": "Yes"})
        assert not mapped.get("UnderlyingCoverage_Coverage_AdditionalInterestsIndicator_A")

    def test_it_is_not_asked_either(self):
        assert "UnderlyingCoverage_Coverage_AdditionalInterestsIndicator_A" \
            not in _asked("ACORD_131", _run_facts())

    def test_a_real_leftover_liability_line_does_fill_an_other_row(self):
        facts = _run_facts()
        facts["coverage_lines"] = facts["coverage_lines"] + [
            {"line": "Liquor Liability", "premium": "$900", "policy_number": "LQ-1"}]
        mapped = _fill("ACORD_131", facts)
        descs = {str(mapped.get(f"UnderlyingCoverage_Coverage_OtherDescription_{r}") or "")
                 for r in "ABCD"}
        assert "Liquor Liability" in descs


# ── Fix 5/6: an address is not a name; a symbol is not a rating credit ─────

class TestValueShapeGuards:
    @pytest.mark.parametrize("bad", [
        "4800 Dahlia St # D13 Denver, Co 80216-3121",
        "4800 DAHLIA STREET D13, DENVER CO. 80216-3121",
    ])
    def test_an_address_never_lands_in_a_name_box(self, bad):
        mapped = _fill("ACORD_131", _run_facts(),
                       {"CommercialStructure_Location_FullName_A": bad})
        assert not mapped.get("CommercialStructure_Location_FullName_A")

    @pytest.mark.parametrize("good", [
        "Orbin Contracting LLC", "EMC Property & Casualty Company",
        "Employers Mutual Casualty Company", "Commercial Risk Solutions, Inc.",
        "St. Jude Medical Inc", "3M Company", "7-Eleven Inc",
        "Wayne Drive Enterprises",
    ])
    def test_a_real_company_name_is_never_seen_as_an_address(self, good):
        """Asserted on the predicate, not end to end: the 131 location-name box
        is already owned by a resolver, so an injected value never reaches the
        guard there and an end-to-end assertion would pass vacuously."""
        assert not P._looks_like_street_address(good)

    def test_the_comp_symbol_is_not_a_net_vehicle_credit(self):
        facts = {"applicant_name": _f("Orbin Contracting LLC"),
                 "auto_vin_schedule": [{"vin": "4S4BRCGC9C3217772"}],
                 "auto_covered_symbols": [
                     {"coverage": "Comprehensive", "symbols": [7]},
                     {"coverage": "Collision", "symbols": [7]}]}
        mapped = _fill("ACORD_127", facts, {"Vehicle_NetRatingFactor_A": "07"})
        assert mapped.get("Vehicle_ComprehensiveSymbolCode_A"), \
            "fixture precondition: the symbol must actually stamp"
        # "07" against a stamped "7" - the same symbol, and the guard must not
        # be defeated by a cosmetic leading zero.
        assert not mapped.get("Vehicle_NetRatingFactor_A")

    def test_a_real_rating_factor_survives(self):
        facts = {"applicant_name": _f("Orbin Contracting LLC"),
                 "auto_vin_schedule": [{"vin": "4S4BRCGC9C3217772"}],
                 "auto_covered_symbols": [
                     {"coverage": "Comprehensive", "symbols": [7]}]}
        mapped = _fill("ACORD_127", facts, {"Vehicle_NetRatingFactor_A": "1.15"})
        assert mapped.get("Vehicle_NetRatingFactor_A") == "1.15"


# ── The Y/N explanations: the explanation IS the grounding quote ───────────

class TestPolicyFormWordingIsNotEvidence:
    CLIENT_Q9 = (
        "ANY INDIVIDUAL NAMED IN THE SCHEDULE AND HIS OR HER SPOUSE, WHILE A "
        "RESIDENT OF THE SAME HOUSEHOLD, ARE 'INSUREDS' WHILE USING ANY COVERED "
        "'AUTO' DESCRIBED IN PARAGRAPH B.1. OF THIS ENDORSEMENT.")

    @pytest.mark.parametrize("quote", [
        CLIENT_Q9,
        "The following is added to Paragraph A.1. of SECTION II",
        "Subject to the terms and conditions of this policy",
        "as defined in Section V of this coverage form",
        "coverage is provided under Paragraph C.2. of this endorsement",
    ])
    def test_policy_wording_is_rejected(self, quote):
        assert P._quote_is_policy_form_wording(quote)

    @pytest.mark.parametrize("quote", [
        "The applicant does not have any subsidiaries.",
        "Subcontractors are required to carry coverage.",
        "The applicant transports hazardous materials to job sites.",
        "No parking facilities are owned or rented by the applicant.",
        "Employees use personal vehicles for company errands twice weekly.",
        "A judgment was entered against the applicant in 2023.",
        "Crime Coverage Policy No. BBC7263",
        "There is no nightclub, no dance floor, and no live entertainment.",
        "The insured hauls construction debris within a 50 mile radius.",
        "This policy was cancelled for non-payment in 2022.",
        "The business began operations on 03/15/2018.",
    ])
    def test_genuine_applicant_evidence_survives(self, quote):
        assert not P._quote_is_policy_form_wording(quote)


# ── Anti-rot: read what is written ─────────────────────────────────────────

class TestReadWhatIsWritten20260816:
    """The 2026-08-07 phantom-fact-key defect has now recurred twice. Every
    fact key this round's resolvers consume is pinned against the extraction
    schema that writes it."""

    KEYS = ("underlying_policies", "prior_coverage_by_line", "coverage_lines",
            "auto_vin_schedule", "auto_deductible_comp",
            "auto_deductible_collision", "is_renewal", "prior_effective_date",
            "prior_expiration_date")

    def test_every_consumed_key_is_written_by_extraction(self):
        src = os.path.join(_HERE, "..", "services", "extraction_service.py")
        with open(src, encoding="utf-8") as fh:
            text = fh.read()
        missing = [k for k in self.KEYS if f'"{k}"' not in text]
        assert not missing, f"resolvers read keys nothing writes: {missing}"

    def test_the_underlying_row_subkeys_match_the_extraction_schema(self):
        src = os.path.join(_HERE, "..", "services", "extraction_service.py")
        with open(src, encoding="utf-8") as fh:
            text = fh.read()
        m = re.search(r'"underlying_policies":\s*\[\{([^}]+)\}\]', text)
        assert m, "underlying_policies is no longer declared in the schema"
        declared = set(re.findall(r'"(\w+)":', m.group(1)))
        for sub in ("line", "carrier", "policy_no"):
            assert sub in declared, f"{sub!r} is not what extraction writes"
