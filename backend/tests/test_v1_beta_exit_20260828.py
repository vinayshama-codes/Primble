"""test_v1_beta_exit_20260828.py - the V1 BETA EXIT CRITERIA fixes (2026-08-28).

The client issued a beta-exit checklist; verifying it against the CODE (not the
change log) found nine criteria that did not hold. Seven were cleanly fixable
and are pinned here. Each section states the criterion in the client's own
words, the measured defect, and the adversarial case written FIRST - H1-F's
standing lesson, because five of the defects below are of the class "a rule
that is necessary but not sufficient" or "a writer that does not write".

  1. "WC-specific information no longer penalizes non-WC submissions"
     -> cross_form_validator._check_acord186_subcontracting_vs_gl_wc
  2. "Contradictory no-loss evidence remains visible and appropriately capped"
     -> sqs_service claim-count door reads the loss_history TABLE
  3. "Overrides preserve prior values"
     -> form_routes.update_pdf persists a CLEAR (D18)
  4. "Downloads with unresolved issues preserve the open-item state"
     -> audit_service.mark_recommendation_dismissed after Download Anyway
  5. "Material changes trigger full recalculation"
     -> arq_routes schedule PUT rescoring
  6. "Derived values retain derivation lineage"
     -> form_routes._prior_provenance keeps `derived`

("GL/WC class codes never reach the client" is pinned in
tests/test_question_eligibility.py, beside the routing table it guards.)
"""
import ast
import inspect
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("SECRET_KEY", "ci-test-secret")


# ===========================================================================
# 1. "WC-specific information no longer penalizes non-WC submissions"
# ===========================================================================

_GL_ONLY_CONTRACTOR = {
    "applicant_name": "ABC Roofing LLC",
    "operations_description": "Commercial roofing contractor, metro Detroit",
    "total_revenue": "2500000",
    "percent_subcontracted": "40",
}


def _cross_issues(facts, flags, forms):
    from services.cross_form_validator import run_cross_form_validation
    return run_cross_form_validation(dict(facts), dict(flags), set(forms))


def test_a_gl_only_submission_is_never_hard_stopped_for_wc_payroll():
    """THE MEASURED DEFECT, in its literal live shape.

    A GL-only roofing contractor with ACORD 186 selected, 40% subcontracted
    work and no payroll figure raised `high_subcontracting_no_wc_payroll` - a
    HARD STOP reading "no Workers Comp payroll is provided. WC payroll is
    required" - and the package fell 71 -> 60. The submission carries no
    Workers Comp line at all, and the remediation asked for `wc_payroll`, so
    the only way to clear it was to invent a WC figure.
    """
    issues = _cross_issues(
        _GL_ONLY_CONTRACTOR,
        {"has_general_liability": True, "has_workers_comp": False},
        {"ACORD_125", "ACORD_126", "ACORD_186"},
    )
    codes = [i.get("code") or i.get("issue_id") for i in issues]
    assert "high_subcontracting_no_wc_payroll" not in codes, (
        "a submission with no Workers Comp line was hard-stopped for missing "
        f"WC payroll. Issues raised: {codes}"
    )


def test_the_flag_being_absent_is_not_the_same_as_it_being_false():
    """Principle 3 applied to the gate itself: an UNSET flag must behave like
    the honest 'no WC evidence' case, not fall through to the penalty."""
    issues = _cross_issues(
        _GL_ONLY_CONTRACTOR,
        {"has_general_liability": True},          # has_workers_comp absent
        {"ACORD_125", "ACORD_126", "ACORD_186"},
    )
    codes = [i.get("code") or i.get("issue_id") for i in issues]
    assert "high_subcontracting_no_wc_payroll" not in codes


def test_a_real_wc_package_still_gets_the_hard_stop():
    """THE GUARD RAIL, and the reason this fix is a gate and not a deletion.

    The rule is correct WHEN the package carries Workers Comp. A fix that
    silenced it everywhere would trade a false negative for a real one - the
    failure mode this codebase has hit four times.
    """
    issues = _cross_issues(
        _GL_ONLY_CONTRACTOR,
        {"has_general_liability": True, "has_workers_comp": True},
        {"ACORD_125", "ACORD_126", "ACORD_130", "ACORD_186"},
    )
    codes = [i.get("code") or i.get("issue_id") for i in issues]
    assert "high_subcontracting_no_wc_payroll" in codes, (
        "the WC branch must still fire on a package that actually carries "
        f"Workers Comp. Issues raised: {codes}"
    )


def test_the_wc_flag_alone_is_enough_to_keep_the_check():
    """Deliberately broader than the five sibling rules, which gate on ACORD
    130 being SELECTED. A package carrying WC that did not select the 130 keeps
    the check; the gate can only ever remove a false stop, never add one."""
    issues = _cross_issues(
        _GL_ONLY_CONTRACTOR,
        {"has_workers_comp": True},
        {"ACORD_125", "ACORD_186"},               # no ACORD 130
    )
    codes = [i.get("code") or i.get("issue_id") for i in issues]
    assert "high_subcontracting_no_wc_payroll" in codes


def test_a_stated_payroll_still_clears_it_on_a_wc_package():
    """Unchanged behaviour: the stop is about a MISSING figure."""
    facts = dict(_GL_ONLY_CONTRACTOR, total_payroll="900000")
    issues = _cross_issues(
        facts,
        {"has_workers_comp": True},
        {"ACORD_125", "ACORD_130", "ACORD_186"},
    )
    codes = [i.get("code") or i.get("issue_id") for i in issues]
    assert "high_subcontracting_no_wc_payroll" not in codes


def test_no_cross_form_rule_demands_wc_information_without_a_wc_gate():
    """THE STRUCTURAL GUARD - the fix, generalised (H1-F lesson 2).

    Fixing the reported rule leaves the CLASS open: any future rule that raises
    a scoring issue naming Workers Comp, without first checking the package
    carries it, reproduces exactly this defect. An advisory is exempt - it
    cannot move a score or set a ceiling - and so is a branch that fires only
    when WC data is PRESENT (`_check_acord101_triggers` is the live example:
    its WC branches read `if wc_pay` / `if flags['wc_gl_class_mismatch']`, so a
    non-WC submission can never reach them).
    """
    from services import cross_form_validator as CFV

    source = inspect.getsource(CFV)
    tree = ast.parse(source)

    scope_gates = ("ACORD_130", "has_workers_comp", "wc_multi_state")
    scoring = ("hard_stop", "soft_warning")
    ungated = []

    def _strings(node):
        return [c.value for c in ast.walk(node)
                if isinstance(c, ast.Constant) and isinstance(c.value, str)]

    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or not node.name.startswith("_check"):
            continue
        literals = _strings(node)
        # Does this rule raise a SCORING issue whose message names Workers Comp?
        names_wc = any(
            ("Workers Comp" in text or "workers comp" in text.lower())
            and len(text) > 40                     # a message, not a key
            for text in literals
        )
        raises_scoring = any(text in scoring for text in literals)
        if not (names_wc and raises_scoring):
            continue
        # The gate must be a CONDITION, never merely a mention. Every one of
        # these rules also names ACORD_130 in its issue's `forms` list, so
        # scanning the whole function body finds a "gate" that gates nothing -
        # this test passed over the unfixed rule until that was corrected.
        conditions = [
            text
            for branch in ast.walk(node) if isinstance(branch, (ast.If, ast.IfExp))
            for text in _strings(branch.test)
        ]
        if not any(gate in text for text in conditions for gate in scope_gates):
            ungated.append(node.name)

    assert not ungated, (
        "these cross-form rules raise a scoring issue naming Workers Comp "
        "without ever checking the package carries a WC line - the "
        "2026-08-28 beta-exit defect, one rule over:\n  "
        + "\n  ".join(sorted(ungated))
    )


# ===========================================================================
# 2. "Contradictory no-loss evidence remains visible and appropriately capped"
# ===========================================================================

_CLAIM_ROW = [{
    "date": "03/15/2024",
    "description": "Slip and fall at job site",
    "paid": "12000",
    "reserved_amount": "2000",
}]
_ATTESTED = {"no_prior_losses": True}
_ESTABLISHED = {
    "applicant_name": "ABC Roofing LLC",
    "years_in_business": "8",
    "loss_history_years": "5",
}


def _p4(facts, flags):
    from services.sqs_service import calculate_p4_loss_history
    result = calculate_p4_loss_history(dict(facts), dict(flags))
    return result[0] if isinstance(result, tuple) else result


def test_a_typed_claim_contradicts_a_no_loss_attestation():
    """THE MEASURED DEFECT. The same claim scored two different ways depending
    on which box it was typed into - and the MORE explicit evidence (the
    client's own claims table) was the one that counted for nothing."""
    from services.loss_history_state import asserted_claims

    facts = dict(_ESTABLISHED, loss_history=_CLAIM_ROW)
    assert asserted_claims(facts) == (1, 14000.0)
    assert _p4(facts, _ATTESTED) == 45, (
        "a claim typed into the loss_history table must contradict a no-loss "
        "attestation exactly as num_claims does"
    )


def test_the_two_sources_agree_on_the_same_claim():
    """Parity, both directions - the scalar and the table are two spellings of
    one fact and must not score differently."""
    scalar = _p4(dict(_ESTABLISHED, num_claims="1"), _ATTESTED)
    table = _p4(dict(_ESTABLISHED, loss_history=_CLAIM_ROW), _ATTESTED)
    assert scalar == table == 45


def test_one_claim_stated_twice_is_not_two_claims():
    """A loss run stating 3 claims and a table listing those 3 rows is ONE set
    of facts printed twice. `asserted_claims` takes a MAXIMUM, never a sum -
    the C23/B1 lesson about counting printings as separate evidence."""
    from services.loss_history_state import asserted_claims

    both = dict(_ESTABLISHED, num_claims="1", loss_history=_CLAIM_ROW)
    claims, _ = asserted_claims(both)
    assert claims == 1, "double counted: {0}".format(claims)
    assert _p4(both, _ATTESTED) == 45


def test_an_empty_row_never_manufactures_a_claim():
    """THE ADVERSARIAL CASE, written first (H1-F lesson 2).

    The mirror of the bug is worse than the bug: a half-typed or empty row
    inventing a claim would cap a genuinely clean submission at 45 and call the
    insured's attestation a contradiction. A row counts only on POSITIVE
    content.
    """
    from services.loss_history_state import asserted_claims

    for rows in (
        [],
        [{"date": "", "description": "", "paid": ""}],
        [{"date": None, "description": None}],
        [{}],
        ["not a dict"],
        [{"date": "", "description": "", "paid": "$0"}],
    ):
        facts = dict(_ESTABLISHED, loss_history=rows)
        assert asserted_claims(facts) == (0, 0.0), "invented a claim"
        assert _p4(facts, _ATTESTED) == 60, "false conflict"


def test_a_partial_row_still_counts_when_it_says_something_real():
    """Positive content is enough - the insured should not have to complete
    every column before their own claim is believed."""
    from services.loss_history_state import asserted_claims

    for rows, expected in (
        ([{"description": "Slip and fall"}], 1),
        ([{"date": "03/15/2024"}], 1),
        ([{"paid": "5000"}], 1),
        ([{"line_of_business": "General Liability"}], 1),
        ([{"description": "Slip and fall"}, {"date": "01/02/2023"}], 2),
    ):
        claims, _ = asserted_claims(dict(_ESTABLISHED, loss_history=rows))
        assert claims == expected, "{0} -> {1}".format(rows, claims)


def test_the_rows_are_read_through_the_fact_envelope():
    """Facts arrive wrapped ({"value": [...]}) as often as bare - D2's envelope.
    Reading only the bare shape would make the door work in tests and fail in
    production, which is the seam H1's standing lesson 1 is about."""
    from services.loss_history_state import asserted_claims

    wrapped = dict(_ESTABLISHED, loss_history={"value": _CLAIM_ROW})
    assert asserted_claims(wrapped) == (1, 14000.0)
    assert _p4(wrapped, _ATTESTED) == 45


def test_a_typed_claim_blocks_a_new_venture_not_applicable():
    """The SECOND consumer of the same blindness (client 2.10 'contradictory
    source information'). A confirmed New Venture carrying a typed claim row
    used to resolve Loss History to Not Applicable, excusing the pillar
    entirely on evidence that the applicant HAD prior operations."""
    from services.loss_history_state import (
        loss_history_not_applicable, prior_operations_evidence,
    )

    confirmed = {"new_venture_confirmed": True}
    assert loss_history_not_applicable({}, confirmed) is True

    facts = {"loss_history": _CLAIM_ROW}
    assert loss_history_not_applicable(facts, confirmed) is not True
    assert "prior claims recorded" in prior_operations_evidence(facts, confirmed)


def test_the_claim_count_has_one_owner():
    """Anti-rot: the scorer must ASK the door, never re-read the scalars
    itself. Two copies of "how many claims are there" is how this defect
    survived - the same shape as C1's five comparison sites."""
    import inspect
    from services import sqs_service

    source = inspect.getsource(sqs_service._loss_history_conflict)
    assert "asserted_claims" in source, (
        "_loss_history_conflict must read the claim count through "
        "loss_history_state.asserted_claims, so the loss_history table stays "
        "visible to it"
    )


# ===========================================================================
# 3. "Overrides preserve prior values" - a CLEAR must actually clear
# ===========================================================================

def test_the_additive_merge_cannot_clear_a_fact():
    """The root cause, pinned so the fix cannot be 'simplified' back out.

    `resolve_facts_write` deliberately skips None/empty so an in-flight writer
    can never blank another's value. That is correct AND it means a clear is
    impossible through `updates["facts"]` alone - the retraction has to be
    stated separately (D18).
    """
    from repositories.session_repository import resolve_facts_write

    current = {"facts": {"num_employees": {"value": "24", "source": "ai"}}}
    merged = resolve_facts_write(current, {"num_employees": None}, "sid")
    assert merged["num_employees"]["value"] == "24", (
        "if the additive merge ever starts honouring None, the delete_facts "
        "retraction in update_pdf is no longer the mechanism and this fix "
        "needs re-reading"
    )


def test_update_pdf_retracts_a_cleared_fact_explicitly():
    """The route must pass the cleared keys to `delete_facts` - the only
    mechanism that genuinely removes a fact (D18). Before this, a clear was
    audited as "removed a value" while the store kept the old one, the next
    recalculation scored it as present, and the restamp could put it back on
    the form."""
    import inspect
    from routes import form_routes

    source = inspect.getsource(form_routes.update_pdf)
    assert "delete_facts=_cleared_fact_keys" in source
    assert "_cleared_fact_keys = sorted(" in source


def test_a_cleared_key_is_read_off_the_final_state_not_the_loop():
    """Two ACORD fields can map to one fact. A request that clears one and
    fills the other must KEEP the value - `delete_facts` is applied after the
    merge, so collecting the key at clear-time would delete what the same
    request just wrote."""
    import inspect
    from routes import form_routes

    source = inspect.getsource(form_routes.update_pdf)
    assert "if updated_facts.get(k) is None" in source, (
        "the cleared set must be derived from the FINAL updated_facts, never "
        "appended inside the field loop"
    )


# ===========================================================================
# 4. "Downloads preserve the open-item state" - dismiss after Download Anyway
# ===========================================================================

def test_a_dismiss_still_lands_after_a_download_anyway():
    """`log_download_with_open_recs` stamps action='downloaded_anyway' on every
    unresolved row. The dismiss upsert's `WHERE action IS NULL` therefore made
    every later dismiss a silent no-op - it matched nothing while still
    returning True and appending `recommendation_dismissed` to the event spine,
    so the table and the history contradicted each other and the credit
    reverted on the next rescore."""
    import inspect
    from services import audit_service

    source = inspect.getsource(audit_service.mark_recommendation_dismissed)
    assert "action = 'downloaded_anyway'" in source, (
        "the dismiss upsert must accept a row already stamped by a "
        "Download Anyway - it is a marker that the producer shipped with the "
        "item open, not a terminal resolution"
    )


def test_the_three_terminal_writers_agree_on_what_is_terminal():
    """Parity. `mark_recommendation_resolved` and
    `mark_recommendation_answer_recorded` already accepted `downloaded_anyway`;
    the dismiss writer was the odd one out, which is exactly why nobody noticed
    it. One rule, three copies - keep them the same."""
    import inspect
    from services import audit_service

    clause = "action = 'downloaded_anyway'"
    for writer in (
        audit_service.mark_recommendation_dismissed,
        audit_service.mark_recommendation_resolved,
        audit_service.mark_recommendation_answer_recorded,
    ):
        assert clause in inspect.getsource(writer), (
            "{0} disagrees with its siblings about whether a downloaded_anyway "
            "row may still be acted on".format(writer.__name__)
        )


def test_a_genuinely_terminal_action_is_still_never_overwritten():
    """The guard rail: relaxing the clause must not let a dismiss undo a
    resolution or re-credit itself."""
    import inspect
    from services import audit_service

    source = inspect.getsource(audit_service.mark_recommendation_dismissed)
    assert "sqs_recommendation_audit.action IS NULL" in source, (
        "the upsert must still refuse rows carrying a terminal action"
    )
    assert "action = 'dismissed'" not in source.split("WHERE")[-1]


# ===========================================================================
# 5. "Material changes trigger full recalculation" - the schedule save
# ===========================================================================

def test_the_schedule_save_rescores_the_session():
    """The producer schedule pre-load wrote facts and restamped forms but never
    rescored, so pre-loading `wc_class_codes` / `auto_vin_schedule` /
    `auto_drivers` changed the very facts the H1 deductions read and left the
    score stale until an unrelated trigger rebuilt it."""
    import inspect
    from routes import arq_routes

    source = inspect.getsource(arq_routes.save_session_schedule_route)
    assert "recalculate_session_scores" in source


def test_the_schedule_rescore_cannot_fail_the_save():
    """Non-fatal, as on every other write path: the save has already succeeded
    and been audited, so a scoring failure must not turn a persisted change
    into a 500."""
    import inspect
    from routes import arq_routes

    source = inspect.getsource(arq_routes.save_session_schedule_route)
    assert "rescore failed (non-fatal)" in source
    assert "except Exception as _re" in source


# ===========================================================================
# 6. "Derived values retain derivation lineage"
# ===========================================================================

def test_an_override_of_a_derived_value_records_it_as_derived():
    """`confidence` was consulted before `source`, and a derived fact carries
    both - so the derivation was overwritten by the confidence label on every
    override and the E&O record lost how the value was produced."""
    from routes.form_routes import _prior_provenance

    for confidence in ("deterministic", "low_confidence", "filled", None):
        facts = {"years_in_business": {
            "value": "8", "source": "derived", "confidence": confidence,
        }}
        assert _prior_provenance(facts, "years_in_business", None) == "derived", (
            "derived lineage lost when confidence={0!r}".format(confidence)
        )


def test_a_derived_override_is_not_recorded_as_an_ai_override():
    """A derivation is deterministic and document-grounded. Filing it as
    "overrode an AI-generated value" would be a false statement about the
    producer in an E&O record - the same class H7-B fixed when an empty field
    was called an override."""
    from services.audit_history import change_kind, KIND_OVERRIDE, KIND_CORRECTION

    assert change_kind("derived", previous_value="8", new_value="9") == KIND_CORRECTION
    # ...and the AI case it must not disturb (verified live in H7-D).
    assert change_kind("ai_high", previous_value="8", new_value="9") == KIND_OVERRIDE


def test_the_ai_and_blank_provenance_paths_are_untouched():
    """H7-D verified both of these on the owner's own record. This fix must not
    move them."""
    from routes.form_routes import _prior_provenance

    ai = {"num_employees": {"value": "24", "source": "ai", "confidence": "ai_high"}}
    assert _prior_provenance(ai, "num_employees", None) == "ai_high"

    blank = {"num_employees": {"value": "", "source": "ai", "confidence": "ai_high"}}
    assert _prior_provenance(blank, "num_employees", None) is None

    legacy = {"num_employees": "24"}
    assert _prior_provenance(legacy, "num_employees", None) is None


# ===========================================================================
# 7. "Equivalent coverage terminology does not create false warnings"
#    - the bare abbreviations GL / WC / BAP (OWNER RULING 2026-08-28, D9)
# ===========================================================================

def test_the_three_ruled_abbreviations_canonicalise():
    """`GL`, `WC` and `BAP` are the shorthand a broker actually types, and all
    three returned None - so the most common abbreviations in the business were
    "terminology not covered by a known rule" (client 1.7). Logged as O2 since
    2026-08-26, held for the product approval D9 requires, ruled 2026-08-28."""
    from services.lob_canon import canon_line

    assert canon_line("GL") == "general_liab"
    assert canon_line("WC") == "workers_comp"
    assert canon_line("BAP") == "auto"
    # Case and surrounding whitespace are the cleaner's job, not the caller's.
    for text in ("gl", " GL ", "Gl"):
        assert canon_line(text) == "general_liab"


def test_a_two_letter_abbreviation_is_matched_as_a_WHOLE_TOKEN():
    """THE ADVERSARIAL CASE, and the reason this needed a ruling rather than a
    one-line append.

    `_SPECIFIC` and `_GL_PHRASES` match by SUBSTRING (`p in s`) - safe for a
    multi-word phrase, catastrophic for a two-letter one. Measured before the
    fix was written: "burglary and theft" (a CRIME line), "plate glass" (a
    PROPERTY line) and "roofing shingles" (a roofer's own trade) all CONTAIN
    "gl"; "showcase" and "newcastle" contain "wc". Appending "gl" to the GL
    phrase list would have read every one of them as General Liability - a
    normalisation change silencing or inventing a coverage line, which is
    exactly the harm D9 exists to prevent (and which this codebase has already
    done twice: G3 and B14).
    """
    from services.lob_canon import canon_line

    for text in ("Burglary and theft", "Plate glass", "Roofing shingles",
                 "Glazing contractors", "Single premium", "englobal"):
        assert canon_line(text) != "general_liab", (
            "{0!r} was read as General Liability - the abbreviation is "
            "matching as a substring".format(text)
        )

    for text in ("Showcase coverage", "Newcastle Mutual"):
        assert canon_line(text) != "workers_comp", (
            "{0!r} was read as Workers Comp".format(text)
        )

    assert canon_line("Baptist church property") != "auto"


def test_excess_still_outranks_an_abbreviation():
    """Order is load-bearing. Abbreviations are checked AFTER `_SPECIFIC`, so
    "Excess GL" resolves the same way "Excess General Liability" always has.
    Checking them first would let an excess policy masquerade as the primary
    line it sits over - the C23 defect, which put a $3,000,000 umbrella limit
    into the GL boxes."""
    from services.lob_canon import canon_line

    assert canon_line("Excess GL") == "umbrella"
    assert canon_line("Excess General Liability") == "umbrella"
    assert canon_line("GL Umbrella") == "umbrella"
    assert canon_line("WC Excess") == "umbrella"


def test_the_ruling_covers_exactly_three_abbreviations():
    """D9 is not repealed, only applied once. A fourth abbreviation is a fresh
    product decision - this test fails the build if one is added quietly."""
    from services.lob_canon import _ABBREVIATIONS

    assert {a for _, group in _ABBREVIATIONS for a in group} == {"gl", "wc", "bap"}


def test_the_existing_vocabulary_did_not_move():
    """Regression: every phrase that canonicalised before must still
    canonicalise to the same family. Measured at 0 changes."""
    from services.lob_canon import canon_line

    unchanged = {
        "Commercial General Liability": "general_liab",
        "General Liability": "general_liab",
        "CGL": "general_liab",
        "Liability": "general_liab",
        "Workers Compensation": "workers_comp",
        "Workers' Comp": "workers_comp",
        "Employers Liability": "workers_comp",
        "Business Auto": "auto",
        "Commercial Auto": "auto",
        "Automobile Liability": "auto",
        "Umbrella": "umbrella",
        "Excess Liability": "umbrella",
        "Professional Liability": "professional",
        "Employment Practices": "epli",
        "Pollution": "pollution",
        "Inland Marine": "inland_marine",
        "Property": "property",
        "Crime": "crime",
        "Cyber": "cyber",
        "Liquor": "liquor",
        "Employee Benefits": "employee_benefits",
        "Widget Liability": None,
        "": None,
    }
    moved = {k: canon_line(k) for k, v in unchanged.items() if canon_line(k) != v}
    assert not moved, "families moved: {0}".format(moved)


def test_an_abbreviated_line_no_longer_reads_as_unrecognised_terminology():
    """The client-visible symptom, end to end. `unmapped_material_lines` routes
    a coverage part it cannot place to the producer for review (client 1.7's
    second half, G2). A carried line printed "GL" used to land there - Primble
    telling the producer it did not recognise the most common abbreviation in
    commercial insurance."""
    from services.lob_canon import unmapped_material_lines, denied_families

    carried = [{"line": "GL", "premium": "$2,500", "limit": "$1,000,000"}]
    assert unmapped_material_lines(carried) == []

    # ...and an abbreviated line can now be DENIED like any other (1.7's
    # "No Coverage must not become an active line"), which it never could
    # while canon_line returned None for it.
    denied = [{"line": "WC", "premium": "", "limit": "", "note": "No Coverage"}]
    assert "workers_comp" in denied_families(denied)
