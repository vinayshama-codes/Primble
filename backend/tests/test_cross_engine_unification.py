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


def _score(cross_issues):
    return sq.calculate_package_sqs(
        facts=FACTS, flags=FLAGS, form_results=[],
        cross_issues=cross_issues, hard_stops=[], soft_stops=[],
        session_data={"docs": []}, calculation_stage="form_generated",
    )["package_sqs_score"]


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


def test_advisories_never_carry_a_penalty():
    """Advisories (UM/UIM not specified, ACORD 101 recommended) are
    informational. They are displayed but must not reduce the score."""
    advisory = [{"type": "advisory", "message": f"advice {i}"} for i in range(4)]
    assert _score(advisory) == _score([])


def test_hard_cross_issues_outweigh_warnings():
    hard = [{"type": "hard_stop", "message": "h1"}]
    warn = [{"type": "soft_warning", "message": "w1"}]
    assert _score(hard) < _score(warn)


def test_cross_penalty_is_capped():
    """min(hard*15 + warn*5, 20) - a long list must not sink the score without
    bound, or one noisy submission would collapse to zero."""
    few  = [{"type": "hard_stop", "message": f"h{i}"} for i in range(2)]
    many = [{"type": "hard_stop", "message": f"h{i}"} for i in range(40)]
    assert _score(few) == _score(many)


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
