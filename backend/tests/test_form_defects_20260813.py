"""The five defects on the 2026-08-13 live ACORD 125, fixed by class not by case.

Every fixture below is the client's LITERAL run value. Four of the five defects
were on one page of one form:

    FAX (A/C, No)              303-996-7800   <- the producer's PHONE
    DEPOSIT                    $10,663        <- the total PREMIUM
    NO. OF MEMBERS AND MANAGERS  0            <- an LLC with no members
    Q3 EXPOSURE TO CHEMICALS   Y  "This exclusion applies even if the claims
                                   against any insured allege negligence or
                                   other wrongdoing in:"
    DRIVER INFORMATION SCHEDULE  ticked       <- there is no driver schedule

The fifth is a report, not a guard: dec_index_coverage, which answers "what was
printed on the declarations pages and never reached a form" by subtraction.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

import services.pdf_service as ps                                 # noqa: E402

Q3 = "CommercialPolicy_AnyExposureToFlammableExplosivesChemicalsExplanation_A"

# The client's literal shipped value. If this ever passes the guard again, the
# same box ships the same exclusion clause as an applicant's own statement.
_REPORTED = ("This exclusion applies even if the claims against any insured "
             "allege negligence or other wrongdoing in:")


# ── 1. Policy contract language, by grammatical subject ──────────────────────

def test_the_reported_exclusion_clause_is_rejected():
    assert ps._is_policy_contract_language(Q3, _REPORTED)


@pytest.mark.parametrize("text", [
    # POSITIVE polarity - the shape that walked around every existing pattern.
    "This exclusion applies even if the claims against any insured allege fault.",
    "This endorsement changes the policy and modifies insurance provided under it.",
    "These conditions are amended to include the following provisions for you.",
    "Such coverage shall be excess over any other valid and collectible insurance.",
    "This coverage part is subject to the limits shown in the declarations above.",
    "This policy provides coverage for pollution incidents at described work sites.",
    # NEGATIVE polarity - still caught, as it was before.
    "This insurance does not apply to bodily injury arising out of pollutants.",
])
def test_the_contract_as_the_subject_of_its_own_sentence(text):
    """The RULE, not the incidents. A demonstrative pointing at the document plus
    an operative verb is the policy describing its own machinery - in either
    polarity, on any topic."""
    assert ps._is_policy_contract_language(Q3, text), text


@pytest.mark.parametrize("text", [
    # THE SAFETY CASE. Same subject shape, but a past EVENT rather than an
    # operative verb: this is the applicant's own history and must survive.
    "This policy was cancelled for non-payment of premium in March 2023.",
    "This policy was non-renewed in 2022 because the carrier exited the state.",
    "These conditions were corrected in January 2024 after a loss control visit.",
    # Ordinary applicant answers.
    "We have had no claims involving chemicals in the past five years of work.",
    "The applicant stores paint thinner and solvents in a locked flammables cabinet.",
    "Contractors - Executive Supervisors; sub work in connection with construction.",
])
def test_a_real_applicant_statement_survives(text):
    assert not ps._is_policy_contract_language(Q3, text), text


def test_no_acord_tooltip_is_flagged():
    """FALSE-POSITIVE SWEEP, the same methodology as _rejects_declared_type's.

    ACORD's own field descriptions are the largest corpus of insurance English in
    this repo that is definitionally NOT a value. Zero of them may match, or the
    rule is matching insurance vocabulary rather than sentence structure.
    """
    import glob
    import json
    flagged, checked = [], 0
    for path in glob.glob(os.path.join(
            os.path.dirname(__file__), "..", "forms_schemas", "*.json")):
        with open(path, encoding="utf-8") as fh:
            schema = json.load(fh)
        fields = schema.get("fields", schema)
        items = fields.items() if isinstance(fields, dict) else [
            (x["name"], x) for x in fields]
        for name, meta in items:
            tu = (meta.get("tu") or "") if isinstance(meta, dict) else ""
            if len(tu) < ps._CONTRACT_LANGUAGE_MIN_CHARS:
                continue
            checked += 1
            if ps._POLICY_SELF_SUBJECT_RE.search(tu) or ps._is_dangling_clause(tu):
                flagged.append((name, tu[:70]))
    assert checked > 5000, f"sweep only saw {checked} tooltips - fixture broken"
    assert not flagged, f"{len(flagged)} tooltips flagged, e.g. {flagged[:3]}"


def test_a_clause_cut_off_at_a_colon_is_rejected():
    """Vocabulary-independent: a sentence that promises a list and delivers
    nothing is a fragment lifted out of a policy form's sub-clause."""
    assert ps._is_dangling_clause("allege negligence or other wrongdoing in:")
    # A complete answer that uses a colon is untouched.
    assert not ps._is_dangling_clause(
        "Safety program includes: a written manual, monthly meetings.")


# ── 2. A second box claiming a value the document printed once ───────────────

_PHONE = "303-996-7800"
_TOTAL = "$10,663.00"
_ENTRIES = [
    {"label": "Agent Phone", "value": _PHONE, "owner": "producer",
     "section": "COMMON POLICY DECLARATIONS"},
    {"label": "Total Policy Premium", "value": _TOTAL, "owner": "policy",
     "section": "COMMON POLICY DECLARATIONS"},
]


# The REAL ACORD 125 name. The first cut of this test used
# `Producer_PhoneNumber_A`, which exists on no schema - it passed, while an
# end-to-end replay of the same values did nothing at all. Note the parents
# differ (`Producer_ContactPerson` vs `Producer`), which is why this guard keys
# off the LEAF name rather than the parent path.
_PHONE_FIELD = "Producer_ContactPerson_PhoneNumber_A"


def test_the_producers_phone_is_blanked_out_of_the_fax_box():
    mapped = {_PHONE_FIELD: _PHONE, "Producer_FaxNumber_A": _PHONE}
    src = ps._second_claim_on_a_single_printed_value(
        "Producer_FaxNumber_A", mapped, {"Producer_FaxNumber_A"}, _ENTRIES)
    assert src == _PHONE_FIELD


def test_every_field_named_in_this_file_exists_on_a_real_schema():
    """ANTI-ROT. A fixture naming a field ACORD does not have is a test that can
    only ever pass, and it cost one end-to-end replay to notice."""
    import glob
    import json
    known = set()
    for path in glob.glob(os.path.join(
            os.path.dirname(__file__), "..", "forms_schemas", "*.json")):
        with open(path, encoding="utf-8") as fh:
            schema = json.load(fh)
        fields = schema.get("fields", schema)
        known.update(fields.keys() if isinstance(fields, dict)
                     else (x["name"] for x in fields))
    for field in (_PHONE_FIELD, "Producer_FaxNumber_A", Q3,
                  "Policy_Payment_DepositAmount_A",
                  "Policy_Payment_EstimatedTotalAmount_A",
                  "NamedInsured_LegalEntity_MemberManagerCount_A",
                  "Policy_SectionAttached_DriverInformationScheduleIndicator_A"):
        assert field in known, f"{field} is on no ACORD schema"


def test_the_total_premium_is_blanked_out_of_the_deposit_box():
    mapped = {"Policy_Payment_EstimatedTotalAmount_A": _TOTAL,
              "Policy_Payment_DepositAmount_A": _TOTAL}
    src = ps._second_claim_on_a_single_printed_value(
        "Policy_Payment_DepositAmount_A", mapped,
        {"Policy_Payment_DepositAmount_A"}, _ENTRIES)
    assert src == "Policy_Payment_EstimatedTotalAmount_A"


def test_two_limits_that_legitimately_agree_are_untouched():
    """THE REASON THE OBVIOUS RULE WAS THROWN AWAY.

    A $1,000,000/$1,000,000 GL policy is ordinary, and both fields sit under the
    same parent with different leaf names - so "same parent, equal value, blank
    the second" deletes a real limit. The declarations print the value under TWO
    labels, and that is what separates the cases.
    """
    entries = [
        {"label": "Each Occurrence Limit", "value": "$1,000,000",
         "section": "GENERAL LIABILITY DECLARATIONS", "owner": "policy"},
        {"label": "Personal & Advertising Injury Limit", "value": "$1,000,000",
         "section": "GENERAL LIABILITY DECLARATIONS", "owner": "policy"},
    ]
    mapped = {"GeneralLiability_BodilyInjury_EachOccurrenceLimitAmount_A": "$1,000,000",
              "GeneralLiability_BodilyInjury_AggregateLimitAmount_A": "$1,000,000"}
    assert ps._second_claim_on_a_single_printed_value(
        "GeneralLiability_BodilyInjury_AggregateLimitAmount_A", mapped,
        {"GeneralLiability_BodilyInjury_AggregateLimitAmount_A"}, entries) is None


def test_the_same_question_asked_in_two_sections_is_untouched():
    """Identical LEAF names are two sections asking one question; they are
    supposed to agree."""
    entries = [{"label": "Named Insured", "value": "ORBIN CONTRACTING LLC",
                "section": None, "owner": "applicant"}]
    mapped = {"NamedInsured_FullName_A": "ORBIN CONTRACTING LLC",
              "Insured_FullName_A": "ORBIN CONTRACTING LLC"}
    assert ps._second_claim_on_a_single_printed_value(
        "Insured_FullName_A", mapped, {"Insured_FullName_A"}, entries) is None


def test_nothing_is_blamed_when_both_holders_came_from_gap_fill():
    """If we cannot say which one copied, nothing moves."""
    mapped = {"Producer_PhoneNumber_A": _PHONE, "Producer_FaxNumber_A": _PHONE}
    both = {"Producer_PhoneNumber_A", "Producer_FaxNumber_A"}
    assert ps._second_claim_on_a_single_printed_value(
        "Producer_FaxNumber_A", mapped, both, _ENTRIES) is None


@pytest.mark.parametrize("entries", [None, [], "junk", [1, 2]])
def test_no_index_no_ruling(entries):
    """Degrades to the pre-Stage-A behaviour rather than guessing."""
    mapped = {"Producer_PhoneNumber_A": _PHONE, "Producer_FaxNumber_A": _PHONE}
    assert ps._second_claim_on_a_single_printed_value(
        "Producer_FaxNumber_A", mapped, {"Producer_FaxNumber_A"}, entries) is None


def test_a_value_the_declarations_never_printed_is_not_judged():
    """The guard rules on printed evidence only. A value absent from the index
    is somebody else's problem (the ownership and grounding guards)."""
    mapped = {"Producer_PhoneNumber_A": "720-555-0000",
              "Producer_FaxNumber_A": "720-555-0000"}
    assert ps._second_claim_on_a_single_printed_value(
        "Producer_FaxNumber_A", mapped, {"Producer_FaxNumber_A"}, _ENTRIES) is None


# ── 3. A count of something that must exist ──────────────────────────────────

def test_an_llc_cannot_have_zero_members():
    f = "NamedInsured_LegalEntity_MemberManagerCount_A"
    assert ps._rejects_impossible_count(f, "0")
    assert ps._rejects_impossible_count(f, 0)
    assert ps._rejects_impossible_count(f, "0.00")


def test_a_real_member_count_survives():
    f = "NamedInsured_LegalEntity_MemberManagerCount_A"
    for good in ("1", "2", 3, "12"):
        assert not ps._rejects_impossible_count(f, good), good
    assert not ps._rejects_impossible_count(f, "")
    assert not ps._rejects_impossible_count(f, None)


def test_zero_is_still_a_valid_answer_everywhere_else():
    """Scoped hard on purpose. A count that CAN be zero - losses, claims,
    vehicles - must never be added to `_NONZERO_COUNT_FIELDS`."""
    for f in ("LossHistory_TotalLossesCount_A", "Vehicle_NumberOfVehicles_A",
              "GeneralLiability_ClaimCount_A"):
        assert not ps._rejects_impossible_count(f, "0"), f


# ── 4. The declarations coverage report ──────────────────────────────────────

_COV_ENTRIES = [
    {"label": "Named Insured", "value": "ORBIN CONTRACTING LLC",
     "section": "COMMON POLICY DECLARATIONS", "owner": "applicant"},
    {"label": "Total Policy Premium", "value": "$10,663.00",
     "section": "COMMON POLICY DECLARATIONS", "owner": "policy"},
    {"label": "Audit Basis", "value": "Payroll",
     "section": "GENERAL LIABILITY SCHEDULE", "owner": "policy"},
    {"label": "Program Code", "value": "CGL-7263",
     "section": "GENERAL LIABILITY SCHEDULE", "owner": "policy"},
]


def test_the_report_names_what_never_reached_a_form():
    report = ps.dec_index_coverage(
        _COV_ENTRIES, ["ORBIN CONTRACTING LLC", "$10,663.00", "Denver"])
    assert report["recorded"] == 4
    assert report["stamped"] == 2
    unused = {u["label"] for u in report["unused"]}
    assert unused == {"Audit Basis", "Program Code"}


def test_the_report_is_grouped_by_section():
    """"the GL SCHEDULE page contributed 0 of its 2 values" is actionable;
    "2 values unused" is not."""
    report = ps.dec_index_coverage(_COV_ENTRIES, ["ORBIN CONTRACTING LLC"])
    assert report["sections"]["GENERAL LIABILITY SCHEDULE"] == {
        "recorded": 2, "stamped": 0}
    assert report["sections"]["COMMON POLICY DECLARATIONS"]["recorded"] == 2


def test_matching_ignores_formatting():
    """`$10,663.00` stamped as `10663.00` is still the same value reaching the
    form. Both sides fold through the same normalizer the presence checks use."""
    report = ps.dec_index_coverage(
        [{"label": "Total Policy Premium", "value": "$10,663.00"}],
        ["10 663 00"])
    assert report["stamped"] == 1


def test_the_report_never_raises_and_never_edits():
    for junk in (None, [], "x", [1], [{"label": "a"}], [{"value": "b"}]):
        out = ps.log_dec_index_coverage(junk, ["anything"])
        assert out["recorded"] == 0
    original = [dict(e) for e in _COV_ENTRIES]
    ps.log_dec_index_coverage(_COV_ENTRIES, ["ORBIN CONTRACTING LLC"])
    assert _COV_ENTRIES == original
