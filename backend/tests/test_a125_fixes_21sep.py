"""A125 kit, test 1 (21 Sep 2026) - the fixes, and the cases they must not break.

Read `improving125-21sep.md` before changing anything here.

I1 - THE PRIOR-CARRIER GRID DELETED THE EXPIRING PROGRAMME
----------------------------------------------------------
`_prior_coverage_grid` discards an entry whose policy number appears in
`coverage_lines`, on the rule "the current policy is not prior coverage". That
rule is right and stays. What was wrong is that **a policy number has no time
axis**: on a renewal being re-marketed to a new carrier, `coverage_lines`
describes the EXPIRING policies - they are the only contracts the documents
detail - so every genuine year-one row matched and was dropped. The A125 kit
measured it: all four expiring policies deleted, and the grid printed policy
year TWO as row one.

The number match is now evidence only when the entry's own term IS the term
being applied for, or when it states no term at all.

THE ADVERSARIAL CASE IS FIRST IN THIS FILE, deliberately. The live 25-page run
this filter was built for put the policies being APPLIED FOR into the grid,
carrying the proposed term itself. Those must still be dropped, and
`test_policies_carrying_the_proposed_term_are_still_dropped` is the proof. A
fix that only makes the new case pass would silently reopen a misstatement of
coverage history on a signed application.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

import services.pdf_service as ps                                  # noqa: E402

PROPOSED_EFF, PROPOSED_EXP = "10/01/2026", "10/01/2027"
EXPIRING_EFF, EXPIRING_EXP = "10/01/2025", "10/01/2026"
YEAR_TWO_EFF, YEAR_TWO_EXP = "10/01/2024", "10/01/2025"

EXPIRING = [
    {"line": "General Liability", "carrier": "Cascadia Harbor Mutual Insurance Company",
     "policy_no": "GL 4471102 25", "premium": "$73,410",
     "effective": EXPIRING_EFF, "expiration": EXPIRING_EXP},
    {"line": "Commercial Property", "carrier": "Cascadia Harbor Mutual Insurance Company",
     "policy_no": "CF 4471104 25", "premium": "$41,265",
     "effective": EXPIRING_EFF, "expiration": EXPIRING_EXP},
    {"line": "Business Auto", "carrier": "Cascadia Harbor Mutual Insurance Company",
     "policy_no": "BA 4471106 25", "premium": "$28,940",
     "effective": EXPIRING_EFF, "expiration": EXPIRING_EXP},
    {"line": "Commercial Umbrella", "carrier": "Sentinel Cascade Excess Indemnity Company",
     "policy_no": "XSU-9920415-25", "premium": "$12,880",
     "effective": EXPIRING_EFF, "expiration": EXPIRING_EXP},
]
YEAR_TWO = [
    {"line": "General Liability", "carrier": "Pinnacle Grange Insurance Company",
     "policy_no": "GL 3318740 24", "premium": "$68,150",
     "effective": YEAR_TWO_EFF, "expiration": YEAR_TWO_EXP},
    {"line": "Commercial Property", "carrier": "Pinnacle Grange Insurance Company",
     "policy_no": "CF 3318742 24", "premium": "$37,900",
     "effective": YEAR_TWO_EFF, "expiration": YEAR_TWO_EXP},
    {"line": "Business Auto", "carrier": "Pinnacle Grange Insurance Company",
     "policy_no": "BA 3318744 24", "premium": "$26,475",
     "effective": YEAR_TWO_EFF, "expiration": YEAR_TWO_EXP},
]


def _facts(prior, *, coverage_lines_term, proposed=True):
    """`coverage_lines` always names the contracts the DOCUMENTS detail."""
    return {
        "effective_date": PROPOSED_EFF if proposed else coverage_lines_term[0],
        "expiration_date": PROPOSED_EXP if proposed else coverage_lines_term[1],
        "prior_coverage_by_line": list(prior),
        "coverage_lines": [
            {"line": e["line"], "carrier": e["carrier"], "naic": None,
             "policy_number": e["policy_no"], "premium": e["premium"],
             "effective_date": coverage_lines_term[0],
             "expiration_date": coverage_lines_term[1]}
            for e in EXPIRING
        ],
    }


# ═════════════════════════════════════════════════════════════════════════════
# THE ADVERSARIAL CASE - FIRST, on purpose
# ═════════════════════════════════════════════════════════════════════════════
def test_policies_carrying_the_proposed_term_are_still_dropped():
    """The defect the filter exists for: the policies being APPLIED FOR leaked
    into the prior grid, carrying the proposed term itself. Still dropped."""
    misfiled = [dict(e, effective=PROPOSED_EFF, expiration=PROPOSED_EXP)
                for e in EXPIRING]
    grid, years = ps._prior_coverage_grid(
        _facts(misfiled, coverage_lines_term=(PROPOSED_EFF, PROPOSED_EXP)))
    assert grid == {}, "a policy dated as the term being applied for is not prior coverage"
    assert years == []


def test_a_matching_number_with_no_term_at_all_is_still_dropped():
    """No term stated means no evidence it is prior. Conservative on purpose -
    this preserves the pre-21-Sep behaviour for an entry we cannot date."""
    undated = [dict(e, effective=None, expiration=None) for e in EXPIRING]
    grid, _ = ps._prior_coverage_grid(
        _facts(undated, coverage_lines_term=(EXPIRING_EFF, EXPIRING_EXP)))
    assert grid == {}


# ═════════════════════════════════════════════════════════════════════════════
# I1 - the case the kit measured
# ═════════════════════════════════════════════════════════════════════════════
def test_the_expiring_programme_survives_and_is_year_one():
    grid, years = ps._prior_coverage_grid(
        _facts(EXPIRING + YEAR_TWO, coverage_lines_term=(EXPIRING_EFF, EXPIRING_EXP)))
    assert years == ["2025", "2024"], "newest documented year is row A"
    row_a = {col: e for (col, row), e in grid.items() if row == 0}
    assert row_a["GeneralLiability"]["policy_no"] == "GL 4471102 25"
    assert row_a["GeneralLiability"]["premium"] == "$73,410"
    assert row_a["Property"]["policy_no"] == "CF 4471104 25"
    assert row_a["Automobile"]["policy_no"] == "BA 4471106 25"


def test_the_umbrella_reaches_the_other_column_with_its_own_carrier():
    """The umbrella sits with a THIRD carrier and has no dedicated column."""
    grid, _ = ps._prior_coverage_grid(
        _facts(EXPIRING + YEAR_TWO, coverage_lines_term=(EXPIRING_EFF, EXPIRING_EXP)))
    other = grid[("OtherLine", 0)]
    assert other["policy_no"] == "XSU-9920415-25"
    assert other["carrier"] == "Sentinel Cascade Excess Indemnity Company"


def test_year_two_lands_in_row_b_with_its_own_carrier():
    grid, _ = ps._prior_coverage_grid(
        _facts(EXPIRING + YEAR_TWO, coverage_lines_term=(EXPIRING_EFF, EXPIRING_EXP)))
    row_b = {col: e for (col, row), e in grid.items() if row == 1}
    assert {e["carrier"] for e in row_b.values()} == {"Pinnacle Grange Insurance Company"}
    assert row_b["GeneralLiability"]["policy_no"] == "GL 3318740 24"
    assert "OtherLine" not in row_b, "no umbrella was carried in year two"


def test_an_undocumented_third_year_is_never_manufactured():
    """The client's own instruction: populate only the year it can substantiate."""
    grid, years = ps._prior_coverage_grid(
        _facts(EXPIRING + YEAR_TWO, coverage_lines_term=(EXPIRING_EFF, EXPIRING_EXP)))
    assert len(years) == 2
    assert not [cell for cell in grid if cell[1] == 2]


def test_the_grid_stamps_through_the_real_resolver():
    """Not the helper - the door `compute_form_gaps` and `map_facts_to_form`
    both consult, so the test cannot pass over a resolver nobody calls."""
    facts = _facts(EXPIRING + YEAR_TWO,
                   coverage_lines_term=(EXPIRING_EFF, EXPIRING_EXP))
    cell = ps._resolve_prior_coverage_cell
    assert cell("PriorCoverage_PolicyYear_A", facts) == "2025"
    assert cell("PriorCoverage_PolicyYear_B", facts) == "2024"
    assert cell("PriorCoverage_PolicyYear_C", facts) is None
    assert cell("PriorCoverage_GeneralLiability_PolicyNumberIdentifier_A",
                facts) == "GL 4471102 25"
    assert cell("PriorCoverage_GeneralLiability_TotalPremiumAmount_A",
                facts) == "$73,410"
    assert cell("PriorCoverage_OtherLine_PolicyNumberIdentifier_A",
                facts) == "XSU-9920415-25"
    for f in ("PriorCoverage_GeneralLiability_InsurerFullName_C",
              "PriorCoverage_Property_PolicyNumberIdentifier_C",
              "PriorCoverage_OtherLine_InsurerFullName_B"):
        assert cell(f, facts) is None, f


# ═════════════════════════════════════════════════════════════════════════════
# The fix must be value-independent - the SHAPE decides, never the spelling
# ═════════════════════════════════════════════════════════════════════════════
def test_the_rule_reads_the_term_not_the_values():
    """Same shapes, wholly different carriers, numbers and lines. The outcome
    must be identical - it is the TERM that decides, not what anything is
    called. (D22: a fixture easier than reality proves nothing.)"""
    alt_expiring = [
        {"line": "General Liability", "carrier": "Zzz Mutual", "policy_no": "X-1",
         "premium": "$1", "effective": EXPIRING_EFF, "expiration": EXPIRING_EXP},
        {"line": "Business Auto", "carrier": "Zzz Mutual", "policy_no": "X-2",
         "premium": "$2", "effective": EXPIRING_EFF, "expiration": EXPIRING_EXP},
    ]
    facts = {
        "effective_date": PROPOSED_EFF, "expiration_date": PROPOSED_EXP,
        "prior_coverage_by_line": alt_expiring,
        "coverage_lines": [
            {"line": e["line"], "policy_number": e["policy_no"],
             "carrier": e["carrier"], "premium": e["premium"],
             "effective_date": EXPIRING_EFF, "expiration_date": EXPIRING_EXP}
            for e in alt_expiring],
    }
    grid, years = ps._prior_coverage_grid(facts)
    assert years == ["2025"]
    assert grid[("GeneralLiability", 0)]["policy_no"] == "X-1"
    assert grid[("Automobile", 0)]["policy_no"] == "X-2"


# ═════════════════════════════════════════════════════════════════════════════
# I3 / I4 - Guard 12: an explanation that is its own question, and an
#           undated resolution
# ═════════════════════════════════════════════════════════════════════════════
import json                                                        # noqa: E402
from pathlib import Path                                           # noqa: E402

_SCHEMA_125 = json.loads(
    (Path(__file__).resolve().parents[1] / "forms_schemas" /
     "ACORD_125_schema.json").read_text(encoding="utf-8"))

_FLAM_Q = "CommercialPolicy_Question_ABCCode_A"
_FLAM_E = "CommercialPolicy_AnyExposureToFlammableExplosivesChemicalsExplanation_A"
_LIEN_Q = "CommercialPolicy_Question_KALCode_A"
_LIEN_E = "CommercialPolicy_JudgementOrLienExplanation_A"
_FIRE_RES = "CommercialPolicy_UncorrectedFireCodeViolation_ResolutionDescription_A"
_FIRE_DATE = "CommercialPolicy_UncorrectedFireCodeViolation_ResolutionDate_A"
_LIEN_RES = "CommercialPolicy_JudgementOrLien_ResolutionDescription_A"
_LIEN_DATE = "CommercialPolicy_JudgementOrLien_ResolutionDate_A"

REAL_FLAM = ("Oxygen, acetylene and propane cylinders are stored in a "
             "ventilated exterior cage at Location 002. There is no bulk "
             "flammable liquid storage at any location.")


def _guard(mapped: dict) -> dict:
    ps._enforce_post_fill_guards(mapped, _SCHEMA_125, {}, None)
    return mapped


# ── the false-positive controls come FIRST ──────────────────────────────────
def test_a_real_explanation_is_never_blanked():
    out = _guard({_FLAM_Q: "Y", _FLAM_E: REAL_FLAM})
    assert out[_FLAM_E] == REAL_FLAM
    assert out[_FLAM_Q] == "Y"


def test_an_echo_followed_by_a_real_explanation_survives_whole():
    """It answers the box. Blanking it would lose real data - the C47 lesson:
    a direct answer to a yes/no question is mostly the question's own words."""
    val = ("Any exposure to flammables, explosives, chemicals? Yes - oxygen, "
           "acetylene and propane cylinders are stored in a ventilated "
           "exterior cage at Location 002.")
    assert _guard({_FLAM_Q: "Y", _FLAM_E: val})[_FLAM_E] == val


def test_an_explanation_with_no_question_mark_is_never_touched():
    val = "Cylinders are stored in a ventilated exterior cage at Location 002"
    assert _guard({_FLAM_Q: "Y", _FLAM_E: val})[_FLAM_E] == val


def test_a_dated_resolution_is_kept():
    out = _guard({_LIEN_Q: "Y", _LIEN_E: "A mechanics lien was recorded on "
                                         "08/14/2023 over disputed retainage.",
                  _LIEN_DATE: "02/27/2024",
                  _LIEN_RES: "Lien released following negotiated settlement"})
    assert out[_LIEN_RES] == "Lien released following negotiated settlement"
    assert out[_LIEN_DATE] == "02/27/2024"


# ── the defects ─────────────────────────────────────────────────────────────
def test_an_explanation_that_is_only_its_own_question_is_blanked():
    for q, e, val in (
        (_FLAM_Q, _FLAM_E, "Any exposure to flammables, explosives, chemicals?: Y"),
        (_LIEN_Q, _LIEN_E, "Has applicant had a judgment or lien?: Y"),
        ("CommercialPolicy_Question_KANCode_A",
         "CommercialPolicy_ApplicantOwnLeaseOperateDronesExplanation_A",
         "Does applicant own, lease or operate any drones?: Y"),
    ):
        assert _guard({q: "Y", e: val})[e] is None, e


def test_the_echo_is_caught_across_a_spelling_difference():
    """The live value printed 'judgment'; ACORD's tooltip says 'judgement'.
    A symmetric similarity score reads 0.36 on that pair and lets it through -
    which is why this is a one-way containment test."""
    assert _guard({_LIEN_Q: "Y",
                   _LIEN_E: "Has applicant had a judgment or lien?: Y"})[_LIEN_E] is None


def test_an_undated_resolution_is_blanked():
    """Question 8's RESOLUTION came back 'Abatement is scheduled, the premises
    has not yet been re-inspected' - a sentence that DENIES a resolution, in
    the box that asserts one. RESOLVE DATE was correctly blank."""
    out = _guard({
        "CommercialPolicy_Question_AAFCode_A": "Y",
        "CommercialPolicy_UncorrectedFireCodeViolationExplanation_A":
            "Gresham Fire Marshal notice dated 05/19/2025 cites an obstructed "
            "sprinkler head in the mezzanine rack area at Location 002.",
        "CommercialPolicy_UncorrectedFireCodeViolation_OccurrenceDate_A": "05/19/2025",
        _FIRE_RES: "Abatement is scheduled, the premises has not yet been re-inspected.",
    })
    assert out[_FIRE_RES] is None
    assert out.get(_FIRE_DATE) in (None, "")
    # the explanation and the occurrence date are untouched - they are stated
    assert out["CommercialPolicy_UncorrectedFireCodeViolation_OccurrenceDate_A"] == "05/19/2025"
    assert out["CommercialPolicy_UncorrectedFireCodeViolationExplanation_A"]


def test_the_undated_resolution_rule_is_derived_from_the_schema():
    """Not a hand-list: every `…ResolutionDescription` with a `…ResolutionDate`
    on the same row is covered, so a new pair on any form is covered the day it
    appears."""
    pairs = [f for f in _SCHEMA_125
             if "ResolutionDescription_" in f
             and f.replace("ResolutionDescription_", "ResolutionDate_") in _SCHEMA_125]
    assert len(pairs) >= 6
    out = _guard({f: "something" for f in pairs})
    assert all(out[f] is None for f in pairs)


# ═════════════════════════════════════════════════════════════════════════════
# I7 - attachments name what THIS package contains
# ═════════════════════════════════════════════════════════════════════════════
# RULING (21 Sep 2026): the ACORD ATTACHMENTS block asks what accompanies the
# application PRIMBLE produces. The uploaded file's own cover sheet describes a
# DIFFERENT submission - a broker's old attachment list cannot say what will be
# stapled to ours. A box ticks only when this package provably contains what it
# names: a form we generate, or a schedule we fill.
#
# SCOPE: `*_Attachment_*` ONLY. `Policy_SectionAttached_*` already has an owner
# (`_resolve_section_attached_indicator` + `_INDICATOR_RULES`) and its own
# partition test in test_run5_authorship_and_attachment.py. The first cut of
# this resolver claimed that family too and shadowed four boxes that fill
# correctly today - with a WEAKER rule than the one already there. The suite
# caught it; see that file before widening this.
_PKG = "_package_form_ids"


def test_a_stated_attachment_list_does_not_tick_anything_by_itself():
    """The kit's document lists five attachments. Generating ACORD 125 alone,
    every box stays blank - this is the ruling, not a miss."""
    facts = {_PKG: ["ACORD_125"]}
    for f in ("CommercialPolicy_Attachment_ContractorsSupplementIndicator_A",
              "CommercialPolicy_Attachment_StatementOfValuesIndicator_A",
              "CommercialPolicy_Attachment_LossSummaryIndicator_A",
              "CommercialPolicy_Attachment_AdditionalInterestScheduleIndicator_A"):
        assert ps._resolve_attachment_indicator(f, facts) is None, f


def test_a_form_we_generate_ticks_its_own_box():
    facts = {_PKG: ["ACORD_125", "ACORD_186"]}
    assert ps._resolve_attachment_indicator(
        "CommercialPolicy_Attachment_ContractorsSupplementIndicator_A", facts) == "Y"
    assert ps._resolve_attachment_indicator(
        "CommercialPolicy_Attachment_StatementOfValuesIndicator_A", facts) is None


def test_a_schedule_we_fill_ticks_its_own_box_on_acord_127():
    """24 Sep 2026 (owner's live run): this pinned the box TICKED for one
    vehicle and one driver. ACORD's own tooltips say the boxes mean "additional
    vehicles appear on the attached ACORD 129" / "additional drivers ... ACORD
    163" - the schedule overflowed the 127's own rows (4 / 13). One Subaru
    printed "ACORD 129 attached"; nothing was attached."""
    one = {_PKG: ["ACORD_125", "ACORD_127"],
           "auto_vin_schedule": [{"year": "2019", "make": "FORD", "vin": "1FT"}],
           "auto_drivers": [{"name": "Erin Royal", "license_number": "12-345"}]}
    veh = "CommercialVehicleLineOfBusiness_Attachment_VehicleScheduleIndicator_A"
    drv = ("CommercialVehicleLineOfBusiness_Attachment_"
           "CommercialAutoDriverInformationScheduleIndicator_A")
    assert ps._resolve_attachment_indicator(veh, one) is None
    assert ps._resolve_attachment_indicator(drv, one) is None
    many = dict(one, auto_vin_schedule=[{"vin": f"V{i}"} for i in range(5)],
                auto_drivers=[{"name": f"D{i}", "license_number": f"L{i}"} for i in range(14)])
    assert ps._resolve_attachment_indicator(veh, many) == "Y"
    assert ps._resolve_attachment_indicator(drv, many) == "Y"


def test_the_box_is_not_ticked_when_the_schedule_is_empty():
    facts = {_PKG: ["ACORD_125", "ACORD_127"], "auto_vin_schedule": [],
             "auto_drivers": []}
    assert ps._resolve_attachment_indicator(
        "CommercialVehicleLineOfBusiness_Attachment_VehicleScheduleIndicator_A",
        facts) is None


def test_a_legacy_session_with_no_package_list_behaves_exactly_as_before():
    """Every box an owned blank - the pre-21-Sep behaviour, never a guess."""
    for f in ("CommercialPolicy_Attachment_ContractorsSupplementIndicator_A",
              "CommercialVehicleLineOfBusiness_Attachment_VehicleScheduleIndicator_A"):
        assert ps._resolve_attachment_indicator(f, {}) is None


def test_this_resolver_never_claims_the_section_attached_family():
    """That family has its own owner and its own partition test. Claiming it
    here shadowed four boxes that fill correctly today."""
    for f in ("Policy_SectionAttached_VehicleScheduleIndicator_A",
              "Policy_SectionAttached_OpenCargoIndicator_A",
              "Policy_SectionAttached_InstallationBuildersRiskIndicator_A"):
        assert ps._resolve_attachment_indicator(f, {}) is ps._SCHED_SKIP, f


def test_no_attachment_field_on_any_form_can_reach_gap_fill():
    """ANTI-ROT. `Attachment_` was removed from `_is_nonfillable_field` when
    this resolver took the family over. The first cut of the regex matched only
    ACORD 125's prefix and left 11 `<LineOfBusiness>_Attachment_*` boxes on
    126/127/130/140 owned by nothing - an invention surface opened by the fix
    meant to close one. This sweeps all 17 real schemas so it cannot recur."""
    import json as _json
    from pathlib import Path as _Path
    d = _Path(__file__).resolve().parents[1] / "forms_schemas"
    harvested, leaked = 0, []
    for p in sorted(d.glob("ACORD_*_schema.json")):
        for f in _json.loads(p.read_text(encoding="utf-8")):
            if "_Attachment_" not in f:
                continue
            harvested += 1
            if ps._resolve_attachment_indicator(f, {}) is ps._SCHED_SKIP \
                    and not ps._is_nonfillable_field(f):
                leaked.append(f"{p.stem}:{f}")
    assert harvested >= 39, f"harvest looks wrong: {harvested}"
    assert not leaked, f"{len(leaked)} attachment box(es) owned by nothing: {leaked[:6]}"


# ═════════════════════════════════════════════════════════════════════════════
# I16 - the audit box takes ACORD's CODE, not the document's word
# ═════════════════════════════════════════════════════════════════════════════
def test_the_audit_period_word_becomes_its_acord_code():
    f = "Policy_Audit_FrequencyCode_A"
    for raw, code in (("Annual", "A"), ("annual", "A"), ("Quarterly", "Q"),
                      ("Monthly", "M"), ("Other", "O")):
        assert ps._resolve_audit_frequency(f, {"audit_period": raw}) == code, raw


def test_semi_annual_is_not_coded_as_annual():
    """"semi-annual" CONTAINS "annual", so the obvious ordering silently codes a
    semi-annual audit as annual - which changes how often the carrier audits the
    payroll this premium is rated on."""
    f = "Policy_Audit_FrequencyCode_A"
    for raw in ("Semi-Annual", "semi annual", "Biannual", "bi-annual"):
        assert ps._resolve_audit_frequency(f, {"audit_period": raw}) == "S", raw


def test_a_period_with_no_acord_code_is_an_owned_blank_not_the_raw_word():
    assert ps._resolve_audit_frequency(
        "Policy_Audit_FrequencyCode_A", {"audit_period": "At expiration"}) is None


def test_a_value_already_in_code_form_passes_through():
    for raw in ("A", "s", "Q"):
        assert ps._resolve_audit_frequency(
            "Policy_Audit_FrequencyCode_A", {"audit_period": raw}) == raw.upper()
