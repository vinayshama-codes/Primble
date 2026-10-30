"""Expert go/no-go review, 29 Oct 2026: an outside ACORD form (807 D&O) read by
Transcriber through ACORD's shared dictionary must not feed package facts that
belong to its own line."""
from services.acord_intake.read import boxes_to_facts
from services.acord_intake.reverse_map import box_targets


def _copy(boxes):
    return {"form_id": "ACORD_807", "copy": 1, "pages": [0, 1, 2], "kind": "transcriber",
            "boxes": dict(boxes), "kinds": {k: "text" for k in boxes}, "box_page": {k: 1 for k in boxes},
            "raw": {}, "confidence": {}, "source": "transcriber"}


_807 = {
    "NamedInsured_FullName_A": "Ridgeline Mechanical Services LLC",
    "Policy_EffectiveDate_A": "01/15/2027",
    "Policy_ExpirationDate_A": "01/15/2028",
    "Insurer_FullName_A": "Larkspur Specialty Insurance Company",
    "Insurer_NAICCode_A": "38145",
    "Policy_PolicyNumberIdentifier_A": "DOL-2290417-25",
    "NamedInsured_FullName_B": "Gregory Hale",          # the 807's signer
    "NamedInsured_Title_A": "Managing Member",
    "Subsidiary_OrganizationName_A": "Ridgeline Mechanical Wyoming LLC",
    "FinancialStatement_PriorYear_TotalRevenueAmount_A": "7,910,000",
    "DirectorsAndOfficersCoverage_DirectorsAndOfficers_RequestedPerClaimLimitAmount_A": "2,000,000",
}


def test_807_term_is_not_the_package_proposed_term():
    assert box_targets("ACORD_807", "Policy_EffectiveDate_A") == []
    assert box_targets("ACORD_807", "Policy_ExpirationDate_A") == []
    facts, _ = boxes_to_facts([_copy(_807)])
    assert "effective_date" not in facts and "expiration_date" not in facts


def test_our_own_125_still_states_the_proposed_term():
    assert box_targets("ACORD_125", "Policy_EffectiveDate_A")[0]["fact"] == "effective_date"


def test_807_signer_and_subsidiary_are_not_additional_named_insureds():
    facts, _ = boxes_to_facts([_copy(_807)])
    assert not facts.get("additional_named_insureds")
    assert box_targets("ACORD_125", "NamedInsured_FullName_B")      # 125's row B still reads


def test_807_line_values_never_reach_package_facts():
    facts, _ = boxes_to_facts([_copy(_807)])
    for k in ("carrier_name", "carrier_naic", "policy_number", "total_revenue", "annual_revenue",
              "gl_each_occurrence", "umbrella_limit", "coverage_lines"):
        assert not facts.get(k), k
    assert facts["applicant_name"]["value"] == "Ridgeline Mechanical Services LLC"


# ── a bound is not the number ────────────────────────────────────────────────
import pytest
from services.answer_semantics import interpret_answer


@pytest.mark.parametrize("key,raw", [("num_employees", "under 50"), ("years_in_business", "less than 1"),
                                     ("total_revenue", "over $5M"), ("num_employees", "more than 10"),
                                     ("total_revenue", "up to $2,000,000")])
def test_a_bound_is_refused_not_stored_as_the_figure(key, raw):
    r = interpret_answer(key, raw, facts={})
    assert not r.accepted and r.value == ""


@pytest.mark.parametrize("key,raw,val", [("num_employees", "50", "50"), ("years_in_business", "0", "0"),
                                         ("total_revenue", "$0", "0"), ("num_employees", "12 full time", "12")])
def test_plain_figures_still_read(key, raw, val):
    r = interpret_answer(key, raw, facts={})
    assert r.accepted and r.value == val


def test_sole_proprietor_may_answer_no_fein():
    r = interpret_answer("fein", "None", facts={"entity_type": "Sole Proprietorship"})
    assert r.accepted and r.value_state == "not_applicable"
    assert not interpret_answer("fein", "None", facts={"entity_type": "LLC"}).accepted
