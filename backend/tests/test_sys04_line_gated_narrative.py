"""SYS-04 - line-gated narrative components.

*"Gate line-specific recommendations and loss requirements on evidence that the
line is actually active or intentionally requested. If Workers' Compensation is
not part of the submission, it should not generate Workers' Comp loss
requirements, warnings, or remediation tasks."*

THE TESTS THAT MATTER MOST ARE THE ONES THAT MUST **NOT** DROP. The gate's whole
safety argument is that it removes an ask only on positive evidence of absence,
so the fail-safe cases (unknown data, legacy sessions, conflicting evidence) are
the property being defended - not the happy path.

Two design mistakes were caught by adversarial review before any code was
written, and both have a test here so they cannot come back:

  * ``fact_state.lines_applied_for(["ACORD_133"]) == {"workers_comp"}`` - the
    header-identity table maps ACORD 133 to Workers Comp (its template really is
    the WC Assigned Risk Section) while the rest of the repo sells it as
    Builders Risk. Gating on it would declare WC present on a builders-risk
    package (`test_a_builders_risk_package_is_not_workers_comp`).
  * ``pdf_service._producer_asserts_family`` reads a fact's SOURCE, not its
    VALUE, so it is True for a client who answered "N/A"
    (`test_a_human_stated_absence_is_absence`).

And the fix itself had a trap: `_calculate_narrative_quality` has FOUR return
paths and three union comprehensions that re-key over the full label map, so a
single filter at the top is silently re-expanded to twelve on three of them
(`test_every_return_path_honours_the_gate`).
"""

import random

import pytest

from services import sqs_service as S
from services import line_presence as LP


# ── Fixtures ─────────────────────────────────────────────────────────────────

# The client's own screenshot shape: a GL + Property contractor, no WC anywhere.
REPORTED_NARRATIVE = (
    "ABC Roofing LLC is a family-owned roofing contractor founded in 2009. "
    "Operations include residential re-roofing. Management has 20 years of "
    "experience. Risk controls include a written safety program. No prior "
    "losses. Coverage requested: general liability and commercial property. "
    "One premises, 4000 square feet. 12 full-time employees. We are marketing "
    "this account because the prior carrier non-renewed."
)

WC_LABELS = {"WC Payroll / Class Code Context", "EMOD / XMOD Information"}
WC_KEYS = {"growth_trends", "target_markets"}


def _facts(**extra):
    base = {"account_description": REPORTED_NARRATIVE}
    base.update(extra)
    return base


def _narr(facts, flags, form_ids=None):
    return S._calculate_narrative_quality(
        facts, has_narrative_doc=True, flags=flags, form_ids=form_ids)


# A certificate that lists three real policies and leaves the WC row blank -
# the shape that makes `has_workers_comp` true off preprinted heading text.
CERT_WITH_BLANK_WC = {
    "coverage_lines": [
        {"line": "General Liability", "policy_number": "BBC7263", "premium": "4200"},
        {"line": "Commercial Auto", "policy_number": "6E7-40-02", "premium": "2991"},
        {"line": "Umbrella", "policy_number": "6J7-40-02", "premium": "3418"},
        {"line": "Workers Compensation"},
    ]
}


# ── 1. The reported case ─────────────────────────────────────────────────────

def test_the_reported_case_drops_both_wc_components():
    """The client's literal screenshot: no WC, yet both WC asks were printed."""
    _, comps, _ = _narr(_facts(), {"has_workers_comp": False})
    assert WC_KEYS.isdisjoint(comps), comps
    assert len(comps) == len(S.NARRATIVE_COMPONENT_LABELS) - 2


def test_the_reported_sentence_no_longer_names_workers_comp():
    _, comps, _ = _narr(_facts(), {"has_workers_comp": False})
    msg = S._narrative_gap_message(comps)
    for label in WC_LABELS:
        assert label not in msg, msg


def test_the_reported_case_scores_higher_and_retires_the_card():
    before, _, _ = _narr(_facts(), {})                       # legacy: no gate
    after, _, _ = _narr(_facts(), {"has_workers_comp": False})
    assert after > before
    # The per-form recommendation is emitted only below 80.
    assert before < 80 <= after


def test_employee_payroll_context_is_never_dropped():
    """Payroll / headcount are GL and exposure facts too - not a WC-only ask."""
    _, comps, _ = _narr(_facts(), {"has_workers_comp": False})
    assert "employee_practices" in comps


# ── 2. The fail-safe invariants - these must NEVER drop ──────────────────────

@pytest.mark.parametrize("flags,form_ids,why", [
    ({},                              None,            "flags dict with no coverage keys"),
    (None,                            None,            "flags is None"),
    ({"has_workers_comp": True},      None,            "flag true (a mention proves nothing)"),
    ({"has_workers_comp": None},      None,            "flag present but null"),
    ({"has_workers_comp": False},     ["ACORD_130"],   "WC applied for - intentionally requested"),
    ({"has_workers_comp": "maybe"},   None,            "flag is an unrecognised value"),
])
def test_components_are_kept_without_decisive_absence(flags, form_ids, why):
    _, comps, _ = _narr(_facts(), flags, form_ids)
    assert WC_KEYS <= set(comps), f"{why}: {sorted(comps)}"


def test_a_stated_wc_fact_keeps_the_components():
    _, comps, _ = _narr(_facts(wc_payroll="250000"), {"has_workers_comp": True})
    assert WC_KEYS <= set(comps)


def test_conflicting_evidence_keeps_the_components():
    """Documents grant WC while the flag denies it - Principle 4, never resolve."""
    facts = _facts(wc_payroll="250000")
    assert LP.line_in_submission("workers_comp", facts,
                                 {"has_workers_comp": False}) == LP.UNKNOWN
    _, comps, _ = _narr(facts, {"has_workers_comp": False})
    assert WC_KEYS <= set(comps)


def test_a_thin_coverage_inventory_proves_nothing():
    """Two granted lines is not a census - a GL+Auto package is ordinary."""
    facts = _facts(coverage_lines=[
        {"line": "General Liability", "policy_number": "BBC7263", "premium": "4200"},
        {"line": "Commercial Auto", "policy_number": "6E7-40-02", "premium": "2991"},
    ])
    assert LP.line_in_submission("workers_comp", facts,
                                 {"has_workers_comp": True}) == LP.UNKNOWN
    _, comps, _ = _narr(facts, {"has_workers_comp": True})
    assert WC_KEYS <= set(comps)


def test_an_empty_submission_keeps_everything():
    assert LP.line_in_submission("workers_comp", {}, {}) == LP.UNKNOWN
    assert set(S.applicable_narrative_components({}, {})) == set(S.NARRATIVE_COMPONENT_LABELS)


# ── 3. The adversarial cases that killed the first design ────────────────────

def test_a_builders_risk_package_is_not_workers_comp():
    """ACORD 133's identity table says workers_comp; this gate must not read it.

    `fact_state.lines_applied_for(["ACORD_133"])` returns {"workers_comp"} and
    `fact_equivalence.fact_line("builders_risk_project_cost")` returns
    "workers_comp" - both live, both contaminated. A builders-risk-only package
    must still be treated as having no Workers Comp.
    """
    facts = _facts(builders_risk_project_cost="500000",
                   builders_risk_project_address="14 Mill Road")
    assert LP.line_in_submission("workers_comp", facts,
                                 {"has_workers_comp": False},
                                 ["ACORD_133"]) == LP.ABSENT
    _, comps, _ = _narr(facts, {"has_workers_comp": False}, ["ACORD_133"])
    assert WC_KEYS.isdisjoint(comps)


def test_acord_133_is_not_a_workers_comp_application_form():
    """Its identity is contradictory in this repo (D-AP), so it grants nothing."""
    prof = LP.line_profile("workers_comp")
    assert "ACORD_133" not in prof.application_forms


@pytest.mark.parametrize("answer", ["N/A", "not applicable", "no coverage"])
def test_a_human_stated_absence_is_absence(answer):
    facts = _facts(wc_xmod=answer)
    assert LP.line_in_submission("workers_comp", facts,
                                 {"has_workers_comp": True}) == LP.ABSENT


def test_a_certificate_with_a_blank_wc_row_reads_as_absent():
    """The reported shape even when the mention-based flag is wrongly true."""
    facts = _facts(**CERT_WITH_BLANK_WC)
    assert LP.line_in_submission("workers_comp", facts,
                                 {"has_workers_comp": True}) == LP.ABSENT
    _, comps, _ = _narr(facts, {"has_workers_comp": True})
    assert WC_KEYS.isdisjoint(comps)


def test_a_certificate_with_a_real_wc_row_is_present():
    lines = list(CERT_WITH_BLANK_WC["coverage_lines"])[:3]
    lines.append({"line": "Workers Compensation",
                  "policy_number": "WC-9931", "premium": "8100"})
    facts = _facts(coverage_lines=lines)
    assert LP.line_in_submission("workers_comp", facts,
                                 {"has_workers_comp": True}) == LP.PRESENT
    _, comps, _ = _narr(facts, {"has_workers_comp": True})
    assert WC_KEYS <= set(comps)


def test_an_explicit_denial_is_absence():
    facts = _facts(coverage_lines=[
        {"line": "Workers Compensation", "premium": "No Coverage"}])
    assert LP.line_in_submission("workers_comp", facts,
                                 {"has_workers_comp": True}) == LP.ABSENT


def test_applying_for_wc_beats_every_absence_signal():
    """Selecting ACORD 130 is the client's 'intentionally requested'."""
    facts = _facts(wc_xmod="N/A", **CERT_WITH_BLANK_WC)
    assert LP.line_in_submission("workers_comp", facts,
                                 {"has_workers_comp": False},
                                 ["acord_130"]) == LP.PRESENT     # case-insensitive


# ── 4. The four-return-path proof ────────────────────────────────────────────

def _profile(*present):
    return {k: {"present": True, "evidence": "stated in the narrative"}
            for k in present}


def test_every_return_path_honours_the_gate():
    """All four returns, not just the keyword-scan one.

    A single filter at the top of the function is silently re-expanded to
    twelve by the three union comprehensions and by the three returns that
    build from `NARRATIVE_COMPONENT_LABELS` directly. Each path is driven here
    by the input that reaches it.
    """
    absent = {"has_workers_comp": False}
    paths = {
        # 1. no narrative text, but a stored LLM profile with evidence
        "profile_only": ({}, {**absent, "narrative_profile":
                              _profile("account_overview", "operations")}),
        # 2. no text, no profile, but a marketing reason
        "carrier_only": ({"carrier_marketing_reason": "rate increase"}, absent),
        # 3. no text, no profile, no marketing reason
        "empty":        ({}, absent),
        # 4. the ordinary keyword-scan path
        "scan":         (_facts(), absent),
    }
    for name, (facts, flags) in paths.items():
        _, comps, _ = _narr(facts, flags)
        assert WC_KEYS.isdisjoint(comps), f"{name} leaked WC components: {sorted(comps)}"
        assert set(comps) <= set(S.NARRATIVE_COMPONENT_LABELS), name


def test_the_profile_path_denominator_shrinks_too():
    """Path 1 computes its own component_pct - it must use the gated length."""
    flags = {"has_workers_comp": False,
             "narrative_profile": _profile(*[
                 k for k in S.NARRATIVE_COMPONENT_LABELS if k not in WC_KEYS])}
    score, comps, _ = _narr({}, flags)
    assert WC_KEYS.isdisjoint(comps)
    # Every applicable component present -> the component half is 100%.
    assert all(comps.values())
    assert score >= 60


# ── 5. Properties and fuzz - the answer to "we do not know what the data is" ──

_VALUE_POOL = [
    None, "", "0", "None", "none", "N/A", "n/a", "not applicable", "unknown",
    "TBD", "no coverage", "None - never carried", 0, 1, False, True, 250000,
    "250,000", "0.88", {"value": None}, {"value": "N/A"}, {"value": "8810"},
    [], {}, ["8810"], "  ", "\n", "NO", "yes",
]
_KEY_POOL = [
    "wc_payroll", "wc_xmod", "wc_class_codes", "wc_officer_exclusions",
    "employers_liability_limits", "total_payroll", "num_employees",
    "builders_risk_project_cost", "gl_each_occurrence", "account_description",
    "operations_description", "coverage_lines", "dec_page_entries", "_form_id",
]
_FLAG_POOL = [True, False, None, 0, 1, "true", "false", "", "maybe", [], {}]
_FORM_POOL = [None, [], ["ACORD_125"], ["ACORD_130"], ["ACORD_133"],
              ["ACORD_125", "ACORD_140"], ["acord_130"], [None], [123],
              "ACORD_130", 7]


def _fuzz_cases(n, seed=20260905):
    rnd = random.Random(seed)
    for _ in range(n):
        facts = {rnd.choice(_KEY_POOL): rnd.choice(_VALUE_POOL)
                 for _ in range(rnd.randint(0, 5))}
        flags = {}
        if rnd.random() < 0.8:
            flags["has_workers_comp"] = rnd.choice(_FLAG_POOL)
        if rnd.random() < 0.3:
            flags["narrative_profile"] = rnd.choice([None, {}, "x", 5,
                                                     _profile("operations")])
        yield facts, (flags if rnd.random() < 0.9 else None), rnd.choice(_FORM_POOL)


FUZZ_N = 1500


def test_fuzz_the_gate_never_raises_and_never_invents_a_component():
    for facts, flags, form_ids in _fuzz_cases(FUZZ_N):
        applicable = S.applicable_narrative_components(facts, flags, form_ids)
        assert set(applicable) <= set(S.NARRATIVE_COMPONENT_LABELS)
        # Only line-bearing components may ever be dropped.
        dropped = set(S.NARRATIVE_COMPONENT_LABELS) - set(applicable)
        assert dropped <= set(S.NARRATIVE_COMPONENT_LINES)


def test_fuzz_the_scorer_never_raises_and_stays_in_range():
    for facts, flags, form_ids in _fuzz_cases(FUZZ_N):
        score, comps, substance = S._calculate_narrative_quality(
            facts, has_narrative_doc=bool(facts), flags=flags, form_ids=form_ids)
        assert isinstance(score, int) and 0 <= score <= 100
        assert 0 <= substance <= 100
        assert set(comps) <= set(S.NARRATIVE_COMPONENT_LABELS)
        assert set(comps) == set(S.applicable_narrative_components(
            facts, flags, form_ids)), "breakdown keys must equal the denominator"


def test_fuzz_line_presence_only_ever_answers_its_vocabulary():
    for facts, flags, form_ids in _fuzz_cases(FUZZ_N):
        answer = LP.line_in_submission("workers_comp", facts, flags, form_ids)
        assert answer in LP.ANSWERS


def test_fuzz_gating_never_lowers_the_score():
    """Dropping an ABSENT component can only remove a penalty, never add one."""
    for facts, flags, form_ids in _fuzz_cases(FUZZ_N):
        gated, _, _ = S._calculate_narrative_quality(
            facts, has_narrative_doc=True, flags=flags, form_ids=form_ids)
        ungated, _, _ = S._calculate_narrative_quality(
            facts, has_narrative_doc=True, flags=None, form_ids=None)
        if set(S.applicable_narrative_components(facts, flags, form_ids)) != \
                set(S.NARRATIVE_COMPONENT_LABELS):
            assert gated >= ungated, (facts, flags, form_ids, gated, ungated)


@pytest.mark.parametrize("line", ["", None, "not_a_line", "WORKERS_COMP",
                                  "workers comp", 7, [], {}])
def test_an_undescribed_line_is_unknown(line):
    assert LP.line_in_submission(line, {}, {}) == LP.UNKNOWN
    assert LP.line_is_absent(line, {}, {}) is False


def test_line_is_absent_is_false_for_unknown():
    """The asymmetry callers depend on: never `not line_is_present(...)`."""
    assert LP.line_in_submission("workers_comp", {}, {}) == LP.UNKNOWN
    assert LP.line_is_absent("workers_comp", {}, {}) is False


# ── 6. One door - the scorer and the questionnaire cannot drift ──────────────

def test_the_questionnaire_holds_no_second_copy_of_the_wc_component_set():
    """SYS-04's root cause was two copies of this rule with opposite effects.

    Asserted over the AST, not the source text - a comment explaining the old
    name must not fail the build, and a string containing the new one must not
    pass it.
    """
    import ast
    import inspect
    import textwrap
    from services import arq_service

    tree = ast.parse(textwrap.dedent(inspect.getsource(
        arq_service._maybe_inject_narrative_enrichment_questions)))
    assigned = {
        t.id for node in ast.walk(tree) if isinstance(node, ast.Assign)
        for t in node.targets if isinstance(t, ast.Name)
    }
    assert "_WC_ONLY_COMPS" not in assigned, "the local copy is back"
    assert "applicable_narrative_components" in _called_names(tree), \
        "the questionnaire must ask the shared door"


def test_the_questionnaire_stops_asking_when_the_line_is_absent():
    from services import arq_service
    questions = []
    arq_service._maybe_inject_narrative_enrichment_questions(
        questions, _facts(), {"has_workers_comp": False})
    asked = {q["field_name"] for q in questions}
    assert "narrative_growth_trends" not in asked
    assert "narrative_target_markets" not in asked


def test_the_questionnaire_still_asks_when_wc_is_applied_for():
    from services import arq_service
    questions = []
    arq_service._maybe_inject_narrative_enrichment_questions(
        questions, _facts(), {"has_workers_comp": False},
        form_ids=["ACORD_130"])
    asked = {q["field_name"] for q in questions}
    assert {"narrative_growth_trends", "narrative_target_markets"} <= asked


# ── 7. Anti-rot ──────────────────────────────────────────────────────────────

def test_every_gated_component_names_a_described_line():
    """A component gated on a line nobody described would never be droppable."""
    for comp, line in S.NARRATIVE_COMPONENT_LINES.items():
        assert comp in S.NARRATIVE_COMPONENT_LABELS, comp
        assert line in LP.described_lines(), (comp, line)


def _called_names(tree):
    """Every function name actually CALLED in an AST, bare or attribute."""
    import ast
    out = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if isinstance(fn, ast.Name):
            out.add(fn.id)
        elif isinstance(fn, ast.Attribute):
            out.add(fn.attr)
    return out


def _imported_names(tree):
    """Every name pulled in by an import, under its ORIGINAL name and its alias."""
    import ast
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                out.add(alias.name.rsplit(".", 1)[-1])
                if alias.asname:
                    out.add(alias.asname)
    return out


def test_the_presence_door_never_uses_a_contaminated_route():
    """`fact_line` and `lines_applied_for` both answer workers_comp for ACORD 133.

    Asserted over the AST so the module docstring - which must be free to NAME
    these functions in order to explain why they are refused - cannot fail the
    build, and so a rename cannot smuggle one back in.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(LP))
    used = _called_names(tree) | _imported_names(tree)
    for banned in ("lines_applied_for", "fact_line", "coverage_flag_supported",
                   "_producer_asserts_family", "_line_entry_grants_coverage"):
        assert banned not in used, f"{banned} is contaminated - see D-AO / D-AP"


def test_the_label_map_is_never_mutated():
    before = dict(S.NARRATIVE_COMPONENT_LABELS)
    S.applicable_narrative_components(_facts(), {"has_workers_comp": False})
    _narr(_facts(), {"has_workers_comp": False})
    assert S.NARRATIVE_COMPONENT_LABELS == before


def test_session_form_ids_never_raises():
    for bad in [None, {}, {"recommendations": "x"}, {"generated_forms": 7},
                {"generated_forms": {"ACORD_130": {}}}, {"selected_forms": [1, None]}]:
        assert isinstance(S.session_form_ids(bad), list)
    assert "ACORD_130" in S.session_form_ids({"generated_forms": {"ACORD_130": {}}})
    assert "ACORD_126" in S.session_form_ids(
        None, [{"form_id": "ACORD_126"}])


# ── 8. Downstream consumers never name a dropped component ───────────────────

def test_no_consumer_prints_a_dropped_label():
    _, comps, _ = _narr(_facts(), {"has_workers_comp": False})
    gap = S._narrative_gap_message(comps)
    absent_labels = [S.NARRATIVE_COMPONENT_LABELS[k]
                     for k, present in comps.items() if not present]
    for label in WC_LABELS:
        assert label not in gap
        assert label not in absent_labels


def test_package_top_recommendations_do_not_ask_for_workers_comp():
    pkg = S.calculate_package_sqs(
        facts=_facts(), flags={"has_workers_comp": False}, form_results=[],
        cross_issues=[], hard_stops=[], soft_stops=[],
        session_data={"docs": [], "facts": _facts()},
    )
    blob = str(pkg.get("top_recommendations") or "")
    for label in WC_LABELS:
        assert label not in blob, blob


# ── 9. The flag reconciliation - SYS-04's other half ─────────────────────────
#
# The narrative gate alone did not satisfy the criteria. `has_workers_comp` is
# set on a MENTION, and every OTHER WC consumer reads it: measured on a
# GL+Property roofing contractor with no WC facts, a wrongly-true flag cost the
# package 3 SQS points and the Exposure pillar 14. Fixing the flag once at the
# seam is one rule in one place instead of five gated consumers.

CERT_FACTS = {
    "account_description": "ABC Roofing LLC, roofing contractor since 2009.",
    "operations_description": "Residential re-roofing",
    "num_employees": "12",
    **CERT_WITH_BLANK_WC,
}


def test_a_blank_certificate_row_demotes_the_mention_flag():
    flags = {"has_workers_comp": True}
    changed = LP.reconcile_line_flags(flags, CERT_FACTS)
    assert changed == {"has_workers_comp": "demoted"}
    assert flags["has_workers_comp"] is False


def test_the_demotion_restores_the_exposure_pillar():
    def _pillars(flags):
        pkg = S.calculate_package_sqs(
            facts=CERT_FACTS, flags=flags, form_results=[], cross_issues=[],
            hard_stops=[], soft_stops=[],
            session_data={"docs": [], "facts": CERT_FACTS})
        return pkg["package_sqs_score"], pkg["pillars"]["exposure_consistency"]

    wrong = _pillars({"has_workers_comp": True})
    fixed_flags = {"has_workers_comp": True}
    LP.reconcile_line_flags(fixed_flags, CERT_FACTS)
    fixed = _pillars(fixed_flags)
    assert fixed[0] > wrong[0], (wrong, fixed)
    assert fixed[1] > wrong[1], (wrong, fixed)


def test_a_genuine_wc_package_keeps_its_flag():
    facts = dict(CERT_FACTS, wc_payroll="250000")
    facts["coverage_lines"] = CERT_WITH_BLANK_WC["coverage_lines"][:3] + [
        {"line": "Workers Compensation", "policy_number": "WC-9931",
         "premium": "8100"}]
    flags = {"has_workers_comp": True}
    assert LP.reconcile_line_flags(flags, facts) == {}
    assert flags["has_workers_comp"] is True


def test_applying_for_wc_restores_a_dropped_flag():
    """`update_pdf` only ever demotes - without this a real WC application
    whose flag was reconciled away at extraction time loses every deduction."""
    flags = {"has_workers_comp": False}
    changed = LP.reconcile_line_flags(flags, CERT_FACTS, ["ACORD_130"])
    assert changed == {"has_workers_comp": "restored"}
    assert flags["has_workers_comp"] is True


def test_reconciliation_never_invents_a_flag_that_was_absent():
    """A key the caller never carried must not appear - only True->False and
    an explicit False->True are in scope."""
    flags = {}
    assert LP.reconcile_line_flags(flags, CERT_FACTS, ["ACORD_130"]) == {}
    assert flags == {}


def test_reconciliation_is_idempotent_and_never_raises():
    for facts, flags, form_ids in _fuzz_cases(600, seed=77):
        working = dict(flags or {})
        first = LP.reconcile_line_flags(working, facts, form_ids)
        snapshot = dict(working)
        second = LP.reconcile_line_flags(working, facts, form_ids)
        assert working == snapshot, (facts, flags, first, second)
        assert set(second) <= set(first) | set()


def test_reconciliation_ignores_a_non_dict_flags_bag():
    for bad in (None, [], "flags", 7):
        assert LP.reconcile_line_flags(bad, CERT_FACTS) == {}


def test_the_xmod_question_offers_an_absence_option():
    """SYS-04 residue #1: a free-text sentence loses its meaning, so the escape
    hatch is an OPTION whose text `fact_state` already reads as an absence."""
    from services.answer_options import options_for
    from services.fact_state import value_state_of
    opts = options_for("wc_xmod")
    assert opts, "wc_xmod must offer choices"
    absent = [o for o in opts
              if value_state_of({"wc_xmod": o}, "wc_xmod") == "not_applicable"]
    assert absent, f"no option reads as an absence: {opts}"
    for option in absent:
        assert LP.line_in_submission(
            "workers_comp", {"wc_xmod": option},
            {"has_workers_comp": True}) == LP.ABSENT


# ── 10. ACORD 133 identity - the contamination that fed the WC flag ──────────

def test_acord_133_metadata_matches_its_own_template():
    """Its template's first page is the Workers Comp Assigned Risk section and
    67 of its 136 schema fields are WorkersCompensation*. The forms_database
    entry used to call it a Builders Risk Application, which shipped that WC
    PDF to construction projects."""
    import json
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    meta = json.loads((root / "forms_database" / "ACORD_133.json").read_text(encoding="utf-8"))
    assert "workers comp" in meta["form_name"].lower()
    assert meta["matching_flags"] == ["has_workers_comp"]
    assert meta["coverage_types"] == ["workers_comp"]

    schema = json.loads((root / "forms_schemas" / "ACORD_133_schema.json").read_text(encoding="utf-8"))
    fields = schema if isinstance(schema, list) else schema.get("fields", schema)
    names = [f.get("name", "") for f in fields] if isinstance(fields, list) else list(fields)
    assert sum(1 for n in names if n.startswith("WorkersCompensation")) > 50
    assert not [n for n in names if "Builder" in n and "AssignedRisk" not in n]


def test_builders_risk_facts_no_longer_claim_a_workers_comp_form():
    """The seven builders_risk_* facts declared forms={"ACORD_133"}, which made
    `fact_equivalence.fact_line` answer "workers_comp" for every one of them and
    `coverage_flag_supported("has_workers_comp", ...)` return True on a
    builders-risk-only package."""
    from services.fact_registry import FACT_REGISTRY
    from services.fact_equivalence import fact_line
    from services.coverage_evidence import coverage_flag_supported, _line_evidence_keys

    br = [k for k in FACT_REGISTRY if k.startswith("builders_risk_")]
    assert br, "the builders_risk facts vanished"
    for key in br:
        assert "ACORD_133" not in (FACT_REGISTRY[key].get("forms") or set()), key
        assert fact_line(key) is None, key
    assert coverage_flag_supported(
        "has_workers_comp", {"builders_risk_project_cost": "500000"}, []) is False
    assert not [k for k in _line_evidence_keys("workers_comp")
                if k.startswith("builders_risk_")]


# ── 11. The loss-run conflict false positive (live run 2026-09-05) ───────────
#
# Nine sessions out of nine printed "Conflicting - attested no losses but loss
# runs show claims" on packages containing NO loss run, whose narrative read
# "the applicant reports no prior losses or claims in the last five years".
# `_loss_history_conflict`'s own docstring has always said the contradiction
# must come from ACTUAL loss-run claims; the code never checked one existed.

_ATTESTED = {"narrative_states_no_losses": True}


def _ai(value):
    """A fact envelope exactly as `extraction_service` writes one."""
    return {"value": str(value), "confidence": "ai_high", "source": "ai"}


def test_an_uncorroborated_model_claim_raises_no_conflict():
    """The reported shape: a model-authored claim figure, no loss run, no row."""
    assert S._loss_history_conflict({"num_claims": _ai(3)}, _ATTESTED) is False
    assert S._loss_history_conflict({"total_incurred": _ai(42000)}, _ATTESTED) is False


def test_a_bare_claim_scalar_is_left_alone():
    """THE GATE IS NARROW BY DESIGN. A bare scalar carries no provenance, so
    nothing can be asserted about who supplied it - the pre-2026-09-05 behaviour
    stands rather than an inference about an inference. Three existing tests pin
    this (`test_the_two_sources_agree_on_the_same_claim`,
    `test_r08_conflict_is_created`,
    `test_loss_conflict_caps_score_and_recommends_reconcile`)."""
    assert S._loss_history_conflict({"num_claims": "3"}, _ATTESTED) is True


def test_a_loss_run_valuation_age_corroborates():
    """A valuation age is only derivable from an actual loss run, never prose."""
    facts = {"num_claims": _ai(3), "loss_run_age_days": "30"}
    assert S._loss_history_conflict(facts, _ATTESTED) is True


def test_a_real_loss_run_still_raises_the_conflict():
    assert S._loss_history_conflict({"num_claims": _ai(3)}, _ATTESTED, True) is True


def test_a_typed_claim_row_still_raises_the_conflict():
    """The V1 BETA EXIT (2026-08-28) path - a claim the producer or client TYPED
    contradicts an attestation with no loss run uploaded anywhere. It must
    survive this gate untouched."""
    facts = {"num_claims": _ai(1),
             "loss_history": [{"date": "03/12/2024",
                               "description": "water damage", "paid": "8200"}]}
    assert S._loss_history_conflict(facts, _ATTESTED) is True


def test_a_human_typed_claim_count_still_raises_the_conflict():
    facts = {"num_claims": {"value": "2", "source": "producer"}}
    assert S._loss_history_conflict(facts, _ATTESTED) is True


def test_an_empty_claims_table_corroborates_nothing():
    """A half-typed or empty row asserts nothing - inventing a claim from one
    would be the mirror of the bug being fixed."""
    facts = {"num_claims": _ai(3),
             "loss_history": [{}, {"date": ""}, {"paid": "0"}]}
    assert S._loss_history_conflict(facts, _ATTESTED) is False


def test_no_attestation_means_no_conflict_however_corroborated():
    assert S._loss_history_conflict({"num_claims": _ai(3)}, {}, True) is False


def test_the_conflict_gate_never_raises():
    from services.loss_history_state import claims_are_corroborated
    for facts, flags, _ in _fuzz_cases(600, seed=915):
        assert isinstance(claims_are_corroborated(facts, False), bool)
        assert isinstance(S._loss_history_conflict(facts, flags or {}), bool)
    for bad in (None, [], "facts", 7):
        assert claims_are_corroborated(bad) is False


# ── 12. WC language must not appear on a package with no Workers Comp ────────

def test_a_gl_only_finding_is_not_filed_under_a_workers_comp_heading():
    """Live run: a GL+Property contractor with no WC saw the cluster heading
    "WC / GL class code alignment" over a single GL item. A cluster TITLE is
    language, and the client's criterion covers language."""
    from services.issue_registry import classify_legacy
    code, cluster, _tier = classify_legacy(
        "GL coverage detected but no class codes found", "soft_warning")
    assert code == "legacy_gl_no_class_codes", code
    assert "WC" not in cluster and "Workers" not in cluster, cluster


def test_the_contractor_form_reason_names_wc_only_when_wc_is_present():
    import inspect
    from services import form_service
    src = inspect.getsource(form_service)
    assert "supplements GL & WC" not in src, \
        "the ACORD 186 reason must not hard-code Workers Comp"


# ── 13. The row that is not a claim (live session data, 2026-09-05) ──────────
#
# Found in the stored facts of W1, W3 and W4 - identical on all three. The
# extraction model wrote the NO-LOSS SENTENCE into the claims TABLE as a row,
# and `asserted_claims` counted any non-blank detail column, so the sentence
# saying there are no claims became a claim that contradicted the attestation it
# restates. `claims_are_corroborated` could not help: a typed row IS
# corroboration, and this looked like one.

_NO_LOSS_ROW = [{"date": None, "claim_date": None,
                 "description": "no prior losses or claims in the last five years",
                 "amount": None, "paid": None}]
_REAL_ROW = [{"date": "03/15/2024", "description": "Slip and fall at job site",
              "paid": "12000", "reserved_amount": "2000"}]


def test_the_attestation_restated_in_the_claims_table_is_not_a_claim():
    from services.loss_history_state import asserted_claims
    assert asserted_claims({"loss_history": _NO_LOSS_ROW}) == (0, 0.0)
    assert S._loss_history_conflict({"loss_history": _NO_LOSS_ROW}, _ATTESTED) is False


def test_a_real_claim_row_is_still_a_claim():
    from services.loss_history_state import asserted_claims
    claims, incurred = asserted_claims({"loss_history": _REAL_ROW})
    assert claims == 1 and incurred == 14000.0
    assert S._loss_history_conflict({"loss_history": _REAL_ROW}, _ATTESTED) is True


def test_one_real_row_beside_the_restated_attestation_still_conflicts():
    """The suppression is per ROW, never per table - a genuine claim filed
    alongside the boilerplate must not be swallowed with it."""
    facts = {"loss_history": _NO_LOSS_ROW + _REAL_ROW}
    assert S._loss_history_conflict(facts, _ATTESTED) is True


@pytest.mark.parametrize("description", [
    "Slip and fall at job site",
    "water damage to stockroom",
    "rear-end collision, no injuries",
    "No injuries reported on this claim",
])
def test_a_claim_description_mentioning_no_is_still_a_claim(description):
    """The detector must not swallow real claim text that happens to say "no"."""
    from services.loss_history_state import _row_states_a_claim
    assert _row_states_a_claim({"description": description}) is True


@pytest.mark.parametrize("description", [
    "no prior losses or claims in the last five years",
    "No Known Losses",
    "loss-free",
])
def test_an_attestation_phrasing_is_never_a_claim(description):
    from services.loss_history_state import _row_states_a_claim
    assert _row_states_a_claim({"description": description}) is False


def test_money_always_wins_over_the_description():
    """A row carrying a real amount is a claim whatever its description says."""
    from services.loss_history_state import _row_states_a_claim
    assert _row_states_a_claim(
        {"description": "No Known Losses", "paid": "5000"}) is True


def test_both_claim_readers_share_the_one_row_door():
    """`asserted_claims` and `claims_are_corroborated` must never disagree about
    whether a row is a claim - that split is what let this defect survive the
    first fix."""
    import ast
    import inspect
    import textwrap
    from services import loss_history_state as LH
    for fn in (LH.asserted_claims, LH.claims_are_corroborated):
        tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
        assert "_row_states_a_claim" in _called_names(tree), fn.__name__


# ── 14. SYS-02 - "Check if none" must reach a fact ───────────────────────────
#
# The client: "Loss History remains at 40 even when 'Check if none' is correctly
# populated." `update_pdf` wrote a producer's edit back by walking
# `_ACORD_FIELD_RULES`, and the whole LossHistory family is absent from it - so
# the tick updated the PDF and the field state and never touched a fact, and the
# re-score that follows recomputed the identical number.

_ATTEST_BOX = "LossHistory_NoPriorLossesIndicator_A"


def test_the_check_if_none_box_maps_to_the_fact_the_scorer_reads():
    from services.pdf_service import writeback_fact_for_field
    assert writeback_fact_for_field(_ATTEST_BOX) == \
        "loss_history_no_prior_losses_indicator"


@pytest.mark.parametrize("sent,stored", [
    ("Yes", "Yes"), ("On", "Yes"), ("X", "Yes"), ("1", "Yes"),
    ("Off", "No"), ("", "No"), (None, "No"), ("No", "No"),
])
def test_a_checkbox_export_value_becomes_a_word_the_scorer_understands(sent, stored):
    """A /Btn sends "Yes" or "Off". "Off" reads as neither true nor false to
    `attested_true`, so it is normalised here rather than guessed at by every
    reader downstream."""
    from services.pdf_service import normalize_writeback_value
    assert normalize_writeback_value(_ATTEST_BOX, sent) == stored


def test_ticking_the_box_moves_the_loss_history_pillar():
    """The client's literal report. 40 is the narrative-only score; an
    attestation is 60, or 85 on a business of 1-5 years (Brent 2026-08-24)."""
    narrative_only = {"narrative_states_no_losses": True}
    ticked = {"loss_history_no_prior_losses_indicator":
              {"value": "Yes", "confidence": "filled", "source": "producer"}}
    assert S.calculate_p4_loss_history({}, narrative_only)[0] == 40
    assert S.calculate_p4_loss_history(ticked, narrative_only)[0] == 60
    assert S.calculate_p4_loss_history(
        dict(ticked, years_in_business="3"), narrative_only)[0] == 85


def test_unticking_the_box_retracts_the_attestation():
    """An untick is an explicit No, not a blank - a blank would read as "never
    answered" and silently keep the attested score."""
    unticked = {"loss_history_no_prior_losses_indicator":
                {"value": "No", "confidence": "filled", "source": "producer"}}
    assert S.calculate_p4_loss_history(
        unticked, {"narrative_states_no_losses": True})[0] == 40


def test_the_writeback_table_never_shadows_a_stamping_rule():
    """It is consulted ONLY when no `_ACORD_FIELD_RULES` pattern matched, and it
    must stay that way - an overlap would silently change what Pass 1 stamps."""
    from services.pdf_service import _ACORD_FIELD_RULES, _FORM_FIELD_WRITEBACK
    rules = [p for p, f in _ACORD_FIELD_RULES if f and not str(f).startswith("_")]
    for pattern, _fact in _FORM_FIELD_WRITEBACK:
        assert not [r for r in rules if r in pattern or pattern in r], pattern


def test_every_scored_fact_with_a_box_can_be_written_back():
    """THE CLASS, MEASURED - and it is why the table above has one row.

    Of the fact keys `sqs_service` reads, exactly one has an ACORD box (via the
    alias maps) and no `_ACORD_FIELD_RULES` pattern covering it. If a second
    ever appears, a producer will be able to edit that box and watch the score
    not move - the SYS-02 defect, reborn. Fail the build then, not later.
    """
    import glob
    import json
    import os
    import re
    from services.pdf_service import _ACORD_FIELD_RULES, _FORM_FIELD_WRITEBACK

    backend = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(backend, "services", "sqs_service.py"),
               encoding="utf-8").read()
    scored = set(re.findall(r"_fv\(facts,\s*[\"']([a-z0-9_]+)[\"']", src))
    scored |= set(re.findall(r"facts\.get\(\s*[\"']([a-z0-9_]+)[\"']", src))

    rules = [p for p, f in _ACORD_FIELD_RULES if f and not str(f).startswith("_")]
    covered = {f for _p, f in _FORM_FIELD_WRITEBACK}

    gaps = {}
    for path in glob.glob(os.path.join(backend, "forms_aliases", "*_alias.json")):
        for field, canonical in json.load(open(path, encoding="utf-8")).items():
            if canonical not in scored or canonical in covered:
                continue
            if any(pattern in field for pattern in rules):
                continue
            gaps.setdefault(canonical, set()).add(field)
    assert not gaps, (
        "these scored facts have an ACORD box a producer can edit and NO "
        "write-back - editing the box will not move the score (SYS-02): "
        + repr({k: sorted(v)[:2] for k, v in gaps.items()}))


# ── 15. The "Check if none" box must not attest on the client's PROSE tier ───
#
# Live 2026-09-05: the box shipped TICKED on a package scoring 40, so the
# producer could not attest - the input was blocked by our own guess. That IS
# the client's SYS-02 report ("Loss History remains at 40 even when 'Check if
# none' is correctly populated"): the box was correctly populated, by us.
#
# The client has ruled three times that a narrative mention is not an
# attestation - his SQS spec's two adjacent lines (attested 60 / narrative prose
# 45), the 1 Sep regression gate ("a CONFIRMED no-loss state updates both form
# requirements and Loss History scoring"), and his ACORD 125 point 5.

_BOX = "LossHistory_NoPriorLossesIndicator_A"


def _human(value):
    return {"value": value, "confidence": "filled", "source": "producer"}


def test_a_narrative_mention_never_ticks_the_attestation_box():
    """The reported case. Prose is the client's 45/40 tier, not his 60 tier."""
    from services.pdf_service import no_loss_attestation_verdict as verdict
    assert verdict({"narrative_states_no_losses": True}) is None


def test_a_zero_claim_count_never_ticks_the_box():
    """"We found no claims" is not "they attested none" (Principle 3) - and
    RULE 12b now makes the model emit "0" on every no-loss statement, so this
    route would tick almost every package."""
    from services.pdf_service import no_loss_attestation_verdict as verdict
    assert verdict({"narrative_states_no_losses": True, "num_claims": "0"}) is None


def test_a_real_attestation_still_ticks_it():
    from services.pdf_service import no_loss_attestation_verdict as verdict
    assert verdict({"loss_history_no_prior_losses_indicator": "Yes"}) == "Yes"
    assert verdict({"no_prior_losses": True}) == "Yes"


def test_real_claims_untick_it():
    """Never attest "none" above a populated claims table on the same form."""
    from services.pdf_service import no_loss_attestation_verdict as verdict
    assert verdict({"num_claims": "3"}) == "No"
    assert verdict({"total_incurred": "42000"}) == "No"


@pytest.mark.parametrize("answer,expected", [("Yes", "Yes"), ("No", "No")])
def test_a_human_answer_outranks_the_derivation(answer, expected):
    """Without this the box RE-TICKS on the next generation after a producer
    unticked it - our inference silently overwriting a person (D18)."""
    from services.pdf_service import no_loss_attestation_verdict as verdict
    facts = {"narrative_states_no_losses": True, "num_claims": "0",
             "loss_history_no_prior_losses_indicator": _human(answer)}
    assert verdict(facts) == expected


def test_the_box_is_an_owned_blank_not_a_gap_fill_guess():
    """Silence must leave the box EMPTY, never hand it to the model."""
    from services.pdf_service import _resolve_no_loss_checkbox_owned as owned
    assert owned(_BOX, {"narrative_states_no_losses": True}) is None


def test_prose_in_the_raw_text_is_not_an_attestation_either():
    """`_resolve_no_loss_indicator` used to tick on `detect_no_loss_assertion`
    over the raw document text - the same prose tier by a different route."""
    from services.pdf_service import _resolve_no_loss_indicator as resolve
    assert resolve(_BOX, {}, "The applicant reports no prior losses.") == "UNMATCHED"


def test_the_box_and_the_score_read_the_same_definition():
    """The old docstring claimed they were "impossible to disagree by
    construction" and they disagreed on screen. Assert the PROPERTY over the
    states that matter, not the claim."""
    from services.pdf_service import no_loss_attestation_verdict as verdict
    for facts, flags in [
        ({"narrative_states_no_losses": True}, {"narrative_states_no_losses": True}),
        ({"loss_history_no_prior_losses_indicator": "Yes"}, {}),
        ({"no_prior_losses": True}, {"no_prior_losses": True}),
        ({}, {}),
    ]:
        box_says_attested = verdict(facts) == "Yes"
        scored = S.calculate_p4_loss_history(facts, flags)[0]
        score_says_attested = scored >= 60
        assert box_says_attested == score_says_attested, (facts, verdict(facts), scored)


def test_both_checkbox_resolvers_share_the_one_door():
    """Two functions decided this box and both carried the same defect."""
    import ast
    import inspect
    import textwrap
    from services import pdf_service as PS
    for fn in (PS._derive_no_prior_losses_indicator, PS._resolve_no_loss_indicator):
        tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
        assert "no_loss_attestation_verdict" in _called_names(tree), fn.__name__


# ── 16. The adversarial safety sweep, wired into the build ───────────────────
#
# `backend/scripts/fuzz_sys04_safety.py` drives every SYS-04 door against the
# shapes a MESSY extraction produces - OCR-mangled line names ("Workers
# Compensat1on", "W0rkers Compensation", "WC"), envelopes where scalars are
# expected, nulls, wrong types, malformed rows, "No Coverage" in a premium
# column. 100,000 iterations were run by hand at 0 violations; this runs a
# smaller slice on every build so a future edit cannot quietly break a property.
#
# TWO ORACLE BUGS WERE FOUND AND FIXED WHILE BUILDING IT, and both would have
# read as product failures:
#   * the generator built a granted WC row, then dropped `coverage_lines` from
#     the facts by a later coin-flip - the row existed nowhere, and the oracle
#     still insisted the package carried WC (1,082 phantom failures);
#   * the oracle passed a RAW fact envelope to `_attests_no_loss` while the code
#     unwraps it with `_fv` (237 phantom failures).
# An oracle that watches the generator instead of the finished artefact is not
# an independent oracle.

def test_adversarial_safety_sweep():
    import importlib.util
    import os
    import random as _random

    backend = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(backend, "scripts", "fuzz_sys04_safety.py")
    spec = importlib.util.spec_from_file_location("fuzz_sys04_safety", path)
    fuzz = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fuzz)

    from services.loss_history_state import asserted_claims, claims_are_corroborated
    from services.pdf_service import _attests_no_loss
    from services.sqs_service import _fv

    rnd = _random.Random(4242)
    all_keys = set(S.NARRATIVE_COMPONENT_LABELS)
    for _ in range(3000):
        facts, flags, form_ids, wc_real = fuzz.build(rnd)

        verdict = LP.line_in_submission("workers_comp", facts, flags, form_ids)
        comps = S.applicable_narrative_components(facts, flags, form_ids)
        score, breakdown, _s = S._calculate_narrative_quality(
            facts, has_narrative_doc=True, flags=flags, form_ids=form_ids)
        snapshot = dict(flags)
        LP.reconcile_line_flags(snapshot, facts, form_ids)

        # P4 - totality
        assert verdict in LP.ANSWERS
        assert isinstance(score, int) and 0 <= score <= 100
        assert set(comps) <= all_keys and set(breakdown) == set(comps)

        # P1 - never suppress WC on a package that really carries it
        if wc_real:
            demoted = (flags.get("has_workers_comp") is not False
                       and snapshot.get("has_workers_comp") is False)
            assert verdict != LP.ABSENT, (facts, flags, form_ids)
            assert all_keys <= set(comps), (facts, flags, form_ids)
            assert not demoted, (facts, flags, form_ids)

        # P2 - a loss conflict needs corroborated claim evidence
        if S._loss_history_conflict(facts, flags):
            claims, incurred = asserted_claims(facts)
            assert (claims > 0 or incurred > 0), (facts, flags)
            assert claims_are_corroborated(facts, False), (facts, flags)

        # P3 - the attestation box never ticks without an attestation or a human
        from services.pdf_service import no_loss_attestation_verdict
        merged = {**facts, **flags}
        if no_loss_attestation_verdict(merged) == "Yes":
            raw = merged.get("loss_history_no_prior_losses_indicator")
            human = (isinstance(raw, dict)
                     and str(raw.get("source") or "").lower()
                     in {"producer", "client_arq", "user", "human", "client"})
            genuine = (
                _attests_no_loss(_fv(merged, "loss_history_no_prior_losses_indicator"))
                or _attests_no_loss(_fv(merged, "no_prior_losses")))
            assert human or genuine, (facts, flags)


# ── 17. SYS-02: the client's three evidence states must stay distinct ────────
#
# > "a narrative stating no losses, a client confirming no losses, and carrier
# >  loss runs not being provided are different evidence states and should not
# >  be collapsed into the same result."
#
# The first two already had their own buckets. The third fell into "unknown"
# alongside "we know nothing" - and because the panel prints the internal label
# above the client bucket, it rendered as:
#
#     No loss runs available      <- correct
#     Unknown                     <- contradicting the line above it

def _state_and_label(facts, flags):
    state = S._get_loss_history_state(facts, flags)
    return state, S.CLIENT_LOSS_STATE_LABELS.get(S._client_loss_state(state), "?")


def test_the_clients_three_evidence_states_are_all_distinct():
    narrative = _state_and_label({}, {"narrative_states_no_losses": True})
    confirmed = _state_and_label(
        {"loss_history_no_prior_losses_indicator":
         {"value": "Yes", "source": "producer", "confidence": "filled"}},
        {"narrative_states_no_losses": True})
    no_runs = _state_and_label(
        {"loss_run_status": "not available", "no_loss_runs_available": "Yes"}, {})

    assert narrative[1] == "None stated"
    assert confirmed[1] == "None corroborated"
    assert no_runs[1] == "Loss runs not provided"
    labels = {narrative[1], confirmed[1], no_runs[1]}
    assert len(labels) == 3, f"collapsed: {labels}"
    assert "Unknown" not in labels


def test_no_state_is_labelled_unknown_while_its_own_label_states_a_fact():
    """THE CLASS, not the reported case. The panel prints the internal label
    directly above the client bucket, so a bucket reading "Unknown" over a label
    that describes a known state is self-contradictory on screen. Only
    `no_information` may be Unknown."""
    offenders = []
    for state, internal in S.LOSS_HISTORY_STATE_LABELS.items():
        bucket = S._client_loss_state(state)
        if S.CLIENT_LOSS_STATE_LABELS.get(bucket) != "Unknown":
            continue
        if state != "no_information":
            offenders.append((state, internal))
    assert not offenders, (
        "these states describe something known but render as 'Unknown': "
        + repr(offenders))


def test_every_internal_state_has_a_client_bucket_and_a_label():
    for state in S.LOSS_HISTORY_STATE_LABELS:
        bucket = S._client_loss_state(state)
        assert bucket in S.CLIENT_LOSS_STATE_LABELS, (state, bucket)
        assert S.CLIENT_LOSS_STATE_LABELS[bucket].strip(), bucket


def test_the_original_five_client_words_are_untouched():
    """The five were client-approved. Widening the vocabulary is only defensible
    while the original buckets still say exactly what he approved."""
    for bucket, label in (("none_stated", "None stated"),
                          ("none_corroborated", "None corroborated"),
                          ("loss_runs_attached", "Loss runs attached"),
                          ("losses_extracted", "Losses extracted"),
                          ("unknown", "Unknown")):
        assert S.CLIENT_LOSS_STATE_LABELS[bucket] == label


def test_relabelling_moved_no_score():
    """Display only - the states and the rubric are untouched."""
    assert S.calculate_p4_loss_history({}, {"narrative_states_no_losses": True})[0] == 40
    assert S.calculate_p4_loss_history(
        {"loss_history_no_prior_losses_indicator":
         {"value": "Yes", "source": "producer", "confidence": "filled"}},
        {"narrative_states_no_losses": True})[0] == 60
    assert S.calculate_p4_loss_history(
        {"loss_run_status": "not available", "no_loss_runs_available": "Yes"}, {})[0] == 25
