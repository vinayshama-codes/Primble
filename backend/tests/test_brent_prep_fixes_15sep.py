"""15 Sep 2026 - the seven items the Brent-prep audit found, fixed in one pass.

Found by auditing live run 07bb6d10 (policy only) and replaying the client's own
full package e7084347 (policy + COI + narrative) through the current code:

1. ACORD 131 printed the umbrella as $1,000,000 / $1,000,000 (the COI's dated
   reduction) beside a third row "Personal & Advertising Injury $3,000,000" -
   the superseded figure from the original declarations.
2. The cover page called the PACKAGE score the "overall average" and named the
   wrong best form.
3. With the logged-in account unreadable, the EXPIRING broker printed as the
   producer of the new application.
4. The client was asked "Who provided your business insurance most recently?"
   on a package whose only document is the insured's current policy.
5. ACORD 131's SUBSIDIARY row B was asked as the applicant's "full legal name"
   and "what does your business do".
6. "Who is the loss payee on the property policy?" on a package with no
   property coverage.
7. Business start date AND years in business, both asked.

Every fixture below is the client's own data shape, verbatim where it matters.
"""
import asyncio
import copy
import json
import re

import pytest

import services.arq_service as arq
import services.cover_service as cs
import services.extraction_pipeline as ep
import services.pdf_service as ps
from services.extraction_service import (
    _derive_prior_carrier, _fv, _route_producer_identity, merge_facts)
from services.fact_registry import FACT_REGISTRY


def _v(x):
    return x.get("value") if isinstance(x, dict) and "value" in x else x


# ── 1. The umbrella's third limit follows the CURRENT limit ─────────────────
UMB_LINE = "Commercial Liability Umbrella"
UMB_SECTION = "COMMERCIAL LIABILITY UMBRELLA DECLARATIONS"
AMT = "ExcessUmbrella_OtherCoverageLimitAmount_A"
DESC = "ExcessUmbrella_OtherCoverageDescription_A"


def _umbrella_entries(pai="$ 3,000,000"):
    base = {"section": UMB_SECTION, "line_of_business": UMB_LINE,
            "policy_number": "6J7-40-02---26", "owner": "policy"}
    return [
        dict(base, label="Each Occurrence Limit (Liability Coverage)", value="$ 3,000,000"),
        dict(base, label="Personal & Advertising Injury Limit", value=pai),
        dict(base, label="Aggregate Limit (Liability Coverage)", value="$ 3,000,000"),
    ]


def _umbrella_facts(limit, pai="$ 3,000,000", changed=False):
    facts = {"_form_id": "ACORD_131", "dec_page_entries": _umbrella_entries(pai)}
    facts["umbrella_limit"] = ({"value": limit, "prior_value": "$ 3,000,000",
                                "as_of": "7/25/25", "source": "document_amendment"}
                               if changed else limit)
    return facts


class TestUmbrellaThirdLimit:
    def test_the_policy_alone_keeps_its_printed_third_limit(self):
        f = _umbrella_facts("$ 3,000,000")
        assert ps._resolve_umbrella_other_limit(AMT, f) == "$3,000,000"
        assert ps._resolve_umbrella_other_limit(DESC, f) == "Personal & Advertising Injury"

    def test_the_cois_dated_reduction_blanks_the_stale_pair(self):
        """THE LIVE CASE: $1M each occurrence / aggregate beside a $3M P&AI."""
        f = _umbrella_facts("$1,000,000", changed=True)
        assert ps._resolve_umbrella_other_limit(AMT, f) is None
        assert ps._resolve_umbrella_other_limit(DESC, f) is None

    def test_a_sub_limit_below_the_new_limit_survives_the_change(self):
        f = _umbrella_facts("$1,000,000", pai="$ 500,000", changed=True)
        assert ps._resolve_umbrella_other_limit(AMT, f) == "$500,000"

    def test_a_limit_larger_than_the_umbrella_is_impossible(self):
        f = _umbrella_facts("$ 1,000,000")                 # no dated change
        assert ps._resolve_umbrella_other_limit(AMT, f) is None

    def test_no_umbrella_limit_fact_changes_nothing(self):
        f = _umbrella_facts("$ 3,000,000")
        f.pop("umbrella_limit")
        assert ps._resolve_umbrella_other_limit(AMT, f) == "$3,000,000"

    @pytest.mark.parametrize("junk", [None, "", "TBD", {"value": None}, {"value": "x", "prior_value": None}])
    def test_junk_limits_never_raise(self, junk):
        f = _umbrella_facts("$ 3,000,000")
        f["umbrella_limit"] = junk
        ps._resolve_umbrella_other_limit(AMT, f)


# ── 5. A non-primary row is never asked as the applicant ────────────────────
class TestRowScope:
    @pytest.mark.parametrize("field,expected", [
        ("CommercialStructure_Location_FullName_A", True),
        ("CommercialStructure_Location_FullName_B", False),
        ("NamedInsured_FullName_C", False),
        ("Policy_EffectiveDate_A", True),
        ("applicant_name", True),
        ("", True),
    ])
    def test_scalar_rules_reach(self, field, expected):
        assert ps.scalar_rules_reach(field) is expected

    def test_the_subsidiary_row_is_not_the_applicant(self):
        """The two live questions: 'full legal name' and 'what does your
        business do', both off ACORD 131 row B."""
        assert arq._canonical_key("CommercialStructure_Location_FullName_B") is None
        assert arq._canonical_key("BusinessInformation_OperationsDescription_B") is None
        assert arq._canonical_key("CommercialStructure_Location_FullName_A") is not None

    def test_a_client_answer_is_never_restamped_into_row_B(self):
        assert arq._canonical_keys_for("CommercialStructure_Location_FullName_B") == set()
        assert arq._canonical_keys_for("NamedInsured_FullName_B") == set()

    def test_no_row_B_box_on_any_form_resolves_through_a_scalar_rule(self):
        """Harvested over all 17 schemas - the questionnaire can never again
        answer a row the stamper refuses."""
        canon = arq._canonical_fact_keys()
        bad = []
        for fid, sch in ps._all_form_schemas().items():
            for f in sch:
                if ps.scalar_rules_reach(f):
                    continue
                c = arq._canonical_key(f)
                base = re.sub(r"[_\s]+[a-zA-Z]$", "", f)
                if c is not None and f not in canon and base not in canon:
                    bad.append((fid, f, c))
        assert bad == []

    def test_the_stamper_still_refuses_row_B_the_applicants_name(self):
        facts = {"applicant_name": "ORBIN CONTRACTING LLC"}
        assert ps._deterministic_map("NamedInsured_FullName_B", facts) != "ORBIN CONTRACTING LLC"


# ── 7. One business-age question ────────────────────────────────────────────
def _q(field, canon, audience="client", forms=("ACORD_125",)):
    return {"field_name": field, "audience": audience, "form_ids": list(forms),
            "_canonical_key": canon}


class TestBusinessAge:
    def test_the_date_question_absorbs_the_years_question(self):
        qs = [_q("NamedInsured_BusinessStartDate_A", "business_start_date"),
              _q("years_in_business", "years_in_business", forms=("ACORD_126",)),
              _q("prior_carrier", "prior_carrier")]
        stats = {"merged_removed": 0}
        out = arq._merge_business_age_questions(qs, stats)
        assert [q["field_name"] for q in out] == ["NamedInsured_BusinessStartDate_A", "prior_carrier"]
        assert set(out[0]["form_ids"]) == {"ACORD_125", "ACORD_126"}
        assert stats["merged_removed"] == 1

    def test_years_alone_is_still_asked(self):
        qs = [_q("years_in_business", "years_in_business")]
        assert arq._merge_business_age_questions(qs, {}) == qs

    def test_a_producer_years_question_is_left_where_it_is(self):
        qs = [_q("NamedInsured_BusinessStartDate_A", "business_start_date"),
              _q("years_in_business", "years_in_business", audience="producer")]
        assert len(arq._merge_business_age_questions(qs, None)) == 2

    def test_an_answered_start_date_derives_the_years(self):
        facts = {"business_start_date": {"value": "06/15/2014", "source": "client_arq"}}
        arq._rederive_answer_dependent_facts(facts)
        assert int(_v(facts["years_in_business"])) >= 12
        assert facts["years_in_business"]["evidence_state"] == "derived"

    def test_a_stated_years_value_is_never_overwritten(self):
        facts = {"business_start_date": {"value": "06/15/2014"}, "years_in_business": "3"}
        arq._rederive_answer_dependent_facts(facts)
        assert facts["years_in_business"] == "3"

    def test_derived_years_follow_a_corrected_start_date(self):
        from services.extraction_service import _derive_years_in_business
        facts = {"business_start_date": {"value": "06/15/2014"}}
        arq._rederive_answer_dependent_facts(facts)
        before = int(_v(facts["years_in_business"]))
        facts["business_start_date"] = {"value": "06/15/2020", "source": "producer"}
        arq._rederive_answer_dependent_facts(facts)
        fresh = {"business_start_date": {"value": "06/15/2020"}}
        _derive_years_in_business(fresh)
        assert _v(facts["years_in_business"]) == _v(fresh["years_in_business"])
        assert int(_v(facts["years_in_business"])) < before

    @pytest.mark.parametrize("date", [None, "", "not a date", "01/01/2999"])
    def test_a_date_that_derives_nothing_keeps_the_derived_years(self, date):
        facts = {"business_start_date": {"value": "06/15/2014"}}
        arq._rederive_answer_dependent_facts(facts)
        held = copy.deepcopy(facts["years_in_business"])
        facts["business_start_date"] = None if date is None else {"value": date}
        arq._rederive_answer_dependent_facts(facts)
        assert facts["years_in_business"] == held

    def test_a_new_venture_years_conclusion_is_not_recomputed(self):
        held = {"value": "", "value_state": "not_applicable", "source": "derived",
                "derivation": {"rule": "not_applicable_on_confirmed_new_venture"}}
        facts = {"business_start_date": {"value": "06/15/2014"}, "years_in_business": dict(held)}
        arq._rederive_answer_dependent_facts(facts)
        assert facts["years_in_business"] == held


# ── 6. The loss-payee question names no coverage the package lacks ──────────
def test_the_loss_payee_question_does_not_assume_a_property_policy():
    q = FACT_REGISTRY["loss_payee_name"]["question"]
    assert "property policy" not in q.lower()
    assert "vehicle" in q.lower()
    assert "—" not in q                       # no em-dash in client text


# ── 3. An unreadable account never prints the expiring broker ───────────────
CRS = "COMMERCIAL RISK SOLUTIONS, INC."
DEC = {"filename": "2526 Package Policy.pdf", "doc_type": "dec_page", "text": "",
       "facts": {"producer_name": CRS, "producer_contact_name": "Terri Wroblewski",
                 "applicant_name": "ORBIN CONTRACTING LLC"}, "flags": {}}


def _producer_mf():
    return {"producer_name": CRS, "producer_contact_name": "Terri Wroblewski",
            "applicant_name": "ORBIN CONTRACTING LLC"}


class TestProducerWhenTheAccountIsUnreadable:
    def test_the_expiring_broker_is_recorded_and_the_block_left_blank(self):
        mf = _producer_mf()
        _route_producer_identity(mf, [copy.deepcopy(DEC)], account={"unreadable": True})
        assert not _v(mf.get("producer_name"))
        assert not _v(mf.get("producer_contact_name"))
        assert "COMMERCIAL RISK" in str(_v(mf.get("expiring_producer_name")))

    def test_no_account_concept_keeps_todays_behaviour(self):
        mf = _producer_mf()
        _route_producer_identity(mf, [copy.deepcopy(DEC)], account=None)
        assert _v(mf["producer_name"]) == CRS

    def test_a_readable_account_still_decides(self):
        mf = _producer_mf()
        _route_producer_identity(mf, [copy.deepcopy(DEC)],
                                 account={"organization_name": "ThinkSmith Agency LLC",
                                          "full_name": "Michelle Smith"})
        assert "ThinkSmith" in str(_v(mf["producer_name"]))

    def test_the_producer_box_is_an_owned_blank_once_cleared(self):
        facts = {"expiring_producer_name": CRS, "_form_id": "ACORD_125"}
        assert ps._resolve_submitting_producer("Producer_FullName_A", facts) is None
        assert ps._resolve_submitting_producer("Producer_ContactPerson_FullName_A", facts) is None


class TestSubmittingAccountLookup:
    def test_each_state(self, monkeypatch):
        import repositories.user_repository as ur

        async def boom(uid):
            raise RuntimeError("database down")

        async def no_agency(uid):
            return {"organization_name": "  ", "full_name": "X"}

        async def missing(uid):
            return None

        async def ok(uid):
            return {"organization_name": "ThinkSmith Agency LLC", "full_name": "Michelle Smith"}

        for fn, expected in ((boom, {"unreadable": True}), (no_agency, {"unreadable": True}),
                             (missing, {"unreadable": True})):
            monkeypatch.setattr(ur, "get_user_by_id", fn)
            assert asyncio.run(ep._submitting_account_for("u1")) == expected
        monkeypatch.setattr(ur, "get_user_by_id", ok)
        assert asyncio.run(ep._submitting_account_for("u1")) == {
            "organization_name": "ThinkSmith Agency LLC", "full_name": "Michelle Smith"}
        assert asyncio.run(ep._submitting_account_for(None)) is None


# ── 4. The prior carrier is the carrier of the expiring policies ────────────
LINES = [
    {"line": "Inland Marine", "carrier": "EMPLOYERS MUTUAL CASUALTY COMPANY",
     "policy_number": "6C7-40-02---26", "premium": "$300.00"},
    {"line": "Commercial General Liability", "carrier": "EMC Property & Casualty Company",
     "policy_number": "BBC7263 - 26", "premium": "$3,954.00"},
    {"line": "COVERED AUTOS LIABILITY", "carrier": "EMPLOYERS MUTUAL CASUALTY COMPANY",
     "policy_number": "6E7-40-02---26", "premium": "$ 1,496.00"},
    {"line": "Commercial Liability Umbrella", "carrier": "EMPLOYERS MUTUAL CASUALTY COMPANY",
     "policy_number": "6J7-40-02---26", "premium": "$ 3,418.00"},
    {"line": "Property"},
    {"line": "Workers' Compensation"},
    {"line": "Commercial Inland Marine", "carrier": "Employers Mutual Casualty Company"},
]


def _doc(lines, role="dec_page"):
    return {"filename": f"{role}.pdf", "doc_type": role, "text": "",
            "facts": {"coverage_lines": copy.deepcopy(lines)}, "flags": {}}


class TestPriorCarrier:
    def test_the_expiring_policies_name_it(self):
        mf = {}
        got = _derive_prior_carrier(mf, [_doc(LINES)])
        assert got == "EMPLOYERS MUTUAL CASUALTY COMPANY / EMC Property & Casualty Company"
        assert mf["prior_carrier"]["evidence_state"] == "derived"
        assert mf["prior_carrier"]["derivation"]["rule"] == "carrier_of_the_expiring_policies"

    def test_a_quote_names_the_carrier_applied_to_never_the_prior_one(self):
        assert _derive_prior_carrier({}, [_doc(LINES, role="quote")]) is None

    def test_a_stated_prior_carrier_wins(self):
        mf = {"prior_carrier": "Travelers"}
        assert _derive_prior_carrier(mf, [_doc(LINES)]) is None
        assert mf["prior_carrier"] == "Travelers"

    def test_a_persons_none_is_respected(self):
        mf = {"prior_carrier": {"value": "", "value_state": "explicit_no"}}
        assert _derive_prior_carrier(mf, [_doc(LINES)]) is None

    def test_no_coverage_rows_name_nobody(self):
        rows = [{"line": "Property"}, {"line": "Crime and Fidelity", "carrier": "X Mutual"}]
        assert _derive_prior_carrier({}, [_doc(rows)]) is None

    def test_through_the_merge(self):
        d = _doc(LINES)
        mf, _ = merge_facts([d], d)
        assert "EMPLOYERS MUTUAL CASUALTY" in str(_fv(mf, "prior_carrier"))

    @pytest.mark.parametrize("junk", [None, "x", [None], [{"carrier": None}], {"a": 1}])
    def test_junk_never_raises(self, junk):
        _derive_prior_carrier({}, [{"doc_type": "dec_page", "facts": {"coverage_lines": junk}}])

    def test_the_derived_carrier_is_no_evidence_against_a_new_venture(self):
        # It is the CURRENT policy's carrier, filled so the client is not asked -
        # nobody named a prior carrier, so a New Venture confirmation stands.
        from services.loss_history_state import (
            PRIOR_CARRIER_DERIVATION_RULE, prior_operations_evidence)
        mf = {}
        _derive_prior_carrier(mf, [_doc(LINES)])
        assert mf["prior_carrier"]["derivation"]["rule"] == PRIOR_CARRIER_DERIVATION_RULE
        assert "a prior carrier is named" not in prior_operations_evidence(mf, {})

    @pytest.mark.parametrize("named", ["Travelers", {"value": "Travelers", "source": "producer"},
                                       {"value": "Travelers", "source": "dec_page"}])
    def test_a_named_prior_carrier_still_is(self, named):
        from services.loss_history_state import prior_operations_evidence
        assert "a prior carrier is named" in prior_operations_evidence({"prior_carrier": named}, {})


# ── 2. The cover page's SQS paragraph agrees with its own table ─────────────
RANKED = [("ACORD_131", 77), ("ACORD_126", 74), ("ACORD_137_CO", 70),
          ("ACORD_127", 69), ("ACORD_125", 62)]


class TestCoverParagraph:
    def test_the_live_average_sentence_is_replaced(self):
        live = ("The overall average SQS of 63/100 reflects a submission that is "
                "structurally acceptable but weakened by major narrative and loss-history deficiencies.")
        t = cs._checked_sqs_reasoning(live, RANKED, 63, True)
        assert "average" not in t.lower() and "package SQS is 63/100" in t

    def test_the_live_wrong_best_form_is_replaced(self):
        live = ("Scores were held down by low loss history alignment. ACORD 126 performed "
                "best at 74 due to stronger exposure consistency.")
        assert "126 performed best" not in cs._checked_sqs_reasoning(live, RANKED, 63, True)

    def test_true_claims_survive(self):
        t = "The package SQS is 63/100. ACORD 131 scored highest at 77. ACORD 125 was the weakest at 62."
        assert cs._checked_sqs_reasoning(t, RANKED, 63, True) == t

    def test_a_tie_at_the_top_accepts_either_form(self):
        ranked = [("ACORD_126", 77), ("ACORD_131", 77), ("ACORD_125", 60)]
        t = "ACORD 126 scored best."
        assert cs._checked_sqs_reasoning(t, ranked, 70, True) == t

    def test_the_state_edition_is_matched(self):
        ranked = [("ACORD_131", 77), ("ACORD_137_CO", 55)]
        t = "ACORD 137 CO was the weakest form."
        assert cs._checked_sqs_reasoning(t, ranked, 60, True) == t

    def test_an_average_is_allowed_when_it_is_one(self):
        t = "The average form SQS is 70/100."
        assert cs._checked_sqs_reasoning(t, RANKED, 70, False) == t

    def test_the_deterministic_sentence(self):
        assert cs._deterministic_sqs_reasoning(RANKED, 63, True) == (
            "The package SQS is 63/100. Form scores run from 62 (ACORD 125) to 77 "
            "(ACORD 131). Scores below 75 indicate fields requiring manual review.")

    def _run(self, monkeypatch, reply):
        captured = {}

        async def fake_chat(model, messages, max_tokens=None):
            captured["prompt"] = messages[0]["content"]
            if isinstance(reply, Exception):
                raise reply
            return json.dumps(reply)

        async def no_cache(key):
            return None

        async def no_set(key, val):
            return None

        monkeypatch.setattr(cs, "groq_chat", fake_chat)
        monkeypatch.setattr(cs, "_cache_get", no_cache)
        monkeypatch.setattr(cs, "_cache_set", no_set)
        sqs = {fid: {"sqs_score": sc} for fid, sc in RANKED}
        out = asyncio.run(cs.generate_ai_cover_narrative(
            {"applicant_name": "Orbin Contracting LLC"}, {}, sqs, list(sqs), "Org",
            package_score=63))
        return captured.get("prompt", ""), out

    def test_the_prompt_names_the_score_and_the_ranking(self, monkeypatch):
        prompt, out = self._run(monkeypatch, {"narrative": "n", "ai_block": {},
                                              "sqs_reasoning": "The overall average SQS of 63/100."})
        assert "Overall Average SQS" not in prompt
        assert "Package SQS: 63/100" in prompt
        assert "Form scores, highest first: ACORD 131 77, ACORD 126 74" in prompt
        assert "average" not in out["sqs_reasoning"].lower()

    def test_the_failure_fallback_is_the_package_sentence(self, monkeypatch):
        _prompt, out = self._run(monkeypatch, RuntimeError("model down"))
        assert out["sqs_reasoning"].startswith("The package SQS is 63/100.")


def test_prior_carrier_lists_one_company_printed_two_ways_once():
    """THE LIVE SHAPE (client package e7084347): 'Employers Mutual Casualty
    Co.' on one row, 'EMPLOYERS MUTUAL CASUALTY COMPANY' on the others. The
    first cut listed the same company twice."""
    rows = copy.deepcopy(LINES) + [{"line": "Commercial Auto",
                                    "carrier": "Employers Mutual Casualty Co.",
                                    "policy_number": "6E7-40-02---26", "premium": "$2,991.00"}]
    assert _derive_prior_carrier({}, [_doc(rows)]) == (
        "EMPLOYERS MUTUAL CASUALTY COMPANY / EMC Property & Casualty Company")
