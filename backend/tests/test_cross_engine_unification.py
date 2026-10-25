"""One cross-form engine, one severity vocabulary.

Form generation used to call the 16-rule sqs_service.cross_validate() while
update_pdf, the ARQ recalculation and the extraction pipeline all called the
45-rule cross_form_validator. The producer saw a short list at generation that
tripled the moment anything re-scored the session.

The two producers also spell a non-blocking issue differently ("warning" vs
"soft_warning"). The P2 exposure penalty matched only the legacy spelling, so
cross-form warnings from the modern engine cost nothing. Unifying the engines
WITHOUT fixing that would have made a submission score HIGHER after finding
more problems - these tests pin both halves.
"""
import services.sqs_service as sq
from services.cross_form_validator import run_cross_form_validation


def _v(x):
    return {"value": x, "source": "doc"}


FACTS = {
    "applicant_name": _v("Summit Ridge Contracting LLC"),
    "total_revenue": _v("2500000"),
    "total_payroll": _v("1600000"),
    "wc_payroll": _v("1600000"),
    "percent_subcontracted": _v("75"),
    "num_claims": _v("4"),
    "effective_date": _v("2025-07-15"),
    "property_building_value": _v("1850000"),
}
FLAGS = {
    "has_property_coverage": True, "has_building_coverage": True,
    "property_has_peril_deductibles": True, "has_auto_coverage": True,
    "auto_has_hired_nonowned": True, "auto_has_physical_damage": True,
    "is_contractor": True, "has_workers_comp": True, "has_general_liability": True,
}
TRIGGERED = {"ACORD_140", "ACORD_127"}

# The package the score tests read (19 Oct 2026, Brent: a cross-form check asking
# for a detail costs Completeness, a conflict Exposure). On FACTS alone the missing
# coverage details floor Structural at 0, where no cross-form point can move it and
# every test below would pass trivially; Tier 1 / Tier 2 and three coverage limits
# leave the pillar 42 points of room.
SCORED_FACTS = dict(
    FACTS,
    producer_name=_v("Broker Inc"), mailing_address=_v("1 Main St, Denver CO 80202"),
    lines_of_business=_v(["General Liability"]), entity_type=_v("LLC"),
    contact_name=_v("Jo"), fein=_v("12-3456789"), num_employees=_v("40"),
    years_in_business=_v("12"), operations_description=_v("Commercial roofing contractor"),
    naics_code=_v("238160"), gl_limits=_v("$1,000,000 / $2,000,000"),
    auto_liability_limit=_v("$1,000,000"),
    auto_covered_symbols=_v([{"coverage": "liability", "symbols": [1]}]),
)


def _package(cross_issues):
    return sq.calculate_package_sqs(
        facts=SCORED_FACTS, flags=FLAGS, form_results=[],
        cross_issues=cross_issues, hard_stops=[], soft_stops=[],
        session_data={"docs": []}, calculation_stage="form_generated",
    )


def _score(cross_issues):
    return _package(cross_issues)["package_sqs_score"]


def test_both_warning_spellings_are_penalized_identically():
    """The bug: filtering on the literal string "warning" meant every
    cross_form_validator warning scored as if it did not exist."""
    legacy = [{"type": "warning", "message": f"legacy warning {i}"} for i in range(3)]
    modern = [{"type": "soft_warning", "message": f"modern warning {i}"} for i in range(3)]
    assert _score(legacy) == _score(modern)


def test_cross_form_warnings_actually_cost_points():
    """Guards against the filter silently matching nothing: warnings must move
    the score, otherwise the equality test above would pass trivially."""
    modern = [{"type": "soft_warning", "message": f"w{i}"} for i in range(3)]
    assert _score(modern) < _score([])
    # (19 Oct 2026, Brent: a check asking for a detail is Completeness) 3 x 5 there...
    assert [(i["bucket"], i["points"]) for i in sq.completeness_deduction_items(
        SCORED_FACTS, FLAGS, [], modern) if i["fact"] is None] == [("cross_form_details", 15)]
    assert _package(modern)["pillars"]["exposure_consistency"] == 100
    # ...and a conflict between documented exposures is Exposure's, in either spelling.
    for spelling in ("warning", "soft_warning"):
        conflict = [{"type": spelling, "code": "location_address_mismatch", "message": "c"}]
        assert _package(conflict)["pillars"]["exposure_consistency"] == 95, spelling


def test_advisories_never_carry_a_penalty():
    """Advisories (UM/UIM not specified, ACORD 101 recommended) are
    informational. They are displayed but must not reduce the score."""
    advisory = [{"type": "advisory", "message": f"advice {i}"} for i in range(4)]
    assert _score(advisory) == _score([])


def test_hard_cross_issues_outweigh_warnings():
    # (19 Oct 2026, Brent: Exposure = conflicts only) the 15 / 5 weights are pinned on a
    # conflict between documented exposures, the bucket the rule keeps them in.
    hard = [{"type": "hard_stop", "code": "location_address_mismatch", "message": "h1"}]
    warn = [{"type": "soft_warning", "code": "location_address_mismatch", "message": "w1"}]
    assert _score(hard) < _score(warn)
    assert (_package(hard)["pillars"]["exposure_consistency"],
            _package(warn)["pillars"]["exposure_consistency"]) == (85, 95)
    # (19 Oct 2026: a hard stop also blocks Submission Ready; the 60 / 85 caps are back since 20 Oct) and only the hard one blocks it.
    assert _package(hard)["ready_blockers"] == ["h1"] and _package(warn)["ready_blockers"] == []


def test_cross_penalty_is_capped():
    """min(hard*15 + warn*5, 20) - a long list must not sink the score without
    bound, or one noisy submission would collapse to zero."""
    # (19 Oct 2026, Brent: Exposure = conflicts only) pinned on conflicts: one costs 15,
    # a second only the 5 left, and the 20 is ONE cap shared with Completeness's
    # cross-form details - conflicts first, so a detail check beside them adds nothing.
    many = [{"type": "hard_stop", "code": "location_address_mismatch", "message": f"h{i}"}
            for i in range(40)]
    few = many[:2]
    assert _score(few) == _score(many)
    assert _score(many[:1]) > _score(few)
    assert _package(many)["pillars"]["exposure_consistency"] == 80
    assert _score(many + [{"type": "soft_warning", "message": "w"}]) == _score(many)


def test_every_emitted_severity_is_understood_by_the_scorer():
    """The root-cause guard. If cross_form_validator ever emits a severity the
    scorer does not recognise, that issue is silently ignored rather than
    failing loudly - exactly how the original defect survived."""
    issues = run_cross_form_validation(FACTS, FLAGS, TRIGGERED)
    assert issues, "scenario should produce cross-form issues"
    emitted = {i.get("type") for i in issues}
    known = set(sq._CROSS_ISSUE_TYPES) | {"advisory"}
    assert emitted <= known, f"scorer does not understand: {emitted - known}"


def test_every_rule_code_has_a_cluster():
    """Any code missing from CLUSTER_MAP silently renders under the meaningless
    "Other validations" heading, which is what the client's dedup/sequencing
    complaint was about. A new rule must come with a cluster."""
    import re
    from services.issue_registry import CLUSTER_MAP

    src = open(cfv_path(), encoding="utf-8").read()
    codes = set(re.findall(r'_issue\(\s*\n?\s*"[a-z_]+",\s*\n?\s*"([a-z0-9_]+)"', src))
    codes |= set(re.findall(r'"code":\s*"([a-z0-9_]+)"', src))
    codes.discard("cross_form")
    assert codes, "no rule codes found - the scraper regex needs updating"

    unmapped = sorted(c for c in codes if c not in CLUSTER_MAP)
    assert not unmapped, f"rule codes with no cluster (add to CLUSTER_MAP): {unmapped}"


def cfv_path():
    import services.cross_form_validator as m
    return m.__file__


def test_generation_engine_matches_the_rescoring_engine():
    """Generation and re-scoring must produce the same issue set for the same
    inputs. Previously generation returned a strict, much smaller subset."""
    full = run_cross_form_validation(FACTS, FLAGS, TRIGGERED)
    legacy = sq.cross_validate(FACTS, FLAGS, list(TRIGGERED))
    # The legacy engine is genuinely weaker - this documents WHY the swap was
    # needed and will start failing if someone reverts generation to it.
    assert len(full) > len(legacy)
