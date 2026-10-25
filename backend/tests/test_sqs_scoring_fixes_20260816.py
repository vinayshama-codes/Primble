"""Regression tests for the 2026-08-16 SQS scoring audit.

Covers the defects found while writing the client scoring specification:

  1. Cross-document identity hard stops (applicant name / FEIN / effective /
     expiration) silently stopped capping the score on the first recalculation,
     because both rescore paths rebuild `hard_stops` from evaluate_stops +
     cross_form only and never re-ran `check_doc_consistency`. The card stayed
     on screen while the cap disappeared, so the score rose because a blocker
     stopped counting rather than because anything was fixed.
  5. "Submission blocked" copy on messages that block nothing.

19 Oct 2026 (Brent) shortened the hard-stop list; 20 Oct 2026 (owner) the 60 / 85
caps are back after the 19 Oct "no cap" build. The identity name / FEIN conflicts
still come back on every rescore - they hold the 60 and also block "Submission
Ready" (`ready_blockers`); the policy-date differences are warnings, so they hold 85.

Every test drives the real production functions - no local reimplementation of
the logic under test (see the C23 lesson in CLAUDE.md: a copy of production
logic in a test only proves the copy is self-consistent).
"""

import ast
import inspect
from pathlib import Path

import pytest

from services.sqs_service import (
    HARD_STOP_CAP,
    SOFT_STOP_CAP,
    _resolve_cap,
    calculate_package_sqs,
    calculate_sqs,
    check_doc_consistency,
    doc_consistency_stops,
    final_score_with_credits,
    readiness_fields,
    routing_for_score,
    split_doc_consistency_issues,
    tier_for_score,
)

_BACKEND = Path(__file__).resolve().parents[1]


def _doc(filename: str, **facts):
    return {"filename": filename, "facts": dict(facts)}


# The client-style shape: two documents that disagree on identity fields.
def _conflicting_session():
    return {
        "docs": [
            _doc(
                "dec_page.pdf",
                applicant_name="ORBIN CONTRACTING LLC",
                fein="84-2210987",
                effective_date="07/15/2025",
                expiration_date="07/15/2026",
            ),
            _doc(
                "application.pdf",
                applicant_name="ORBIN CONTRACTING LLC",
                fein="99-1234567",
                effective_date="07/15/2025",
                expiration_date="07/15/2026",
            ),
        ],
        "underwriting_confirmations": {},
    }


# ── 1. The parser ────────────────────────────────────────────────────────────

def test_parser_splits_every_severity_and_strips_the_machine_token():
    hard, soft, info, conflicts = split_doc_consistency_issues([
        "[hard_stop] code=fein_conflict FEIN differs across uploaded documents.",
        "[warning] field=dba_name DBA / trade name differs across documents.",
        "[info] code=name_normalized Applicant name: ACME LLC | Acme, L.L.C.",
    ])
    assert hard == ["FEIN differs across uploaded documents."]
    assert soft == ["DBA / trade name differs across documents."]
    assert info == ["Applicant name: ACME LLC | Acme, L.L.C."]
    # No machine token may survive into anything a user reads.
    for msg in hard + soft + info:
        assert not msg.startswith("code=")
        assert not msg.startswith("field=")
    assert conflicts[0] == {
        "code": "fein_conflict",
        "message": "FEIN differs across uploaded documents.",
        "hard_stop": True,
    }


def test_parser_treats_an_unknown_prefix_as_a_warning_never_a_hard_stop():
    """An unrecognised message must never silently cap a submission at 60."""
    hard, soft, _info, _c = split_doc_consistency_issues(["totally unexpected string"])
    assert hard == []
    assert soft == ["totally unexpected string"]


def test_parser_is_empty_safe():
    assert split_doc_consistency_issues([]) == ([], [], [], [])
    assert split_doc_consistency_issues(None) == ([], [], [], [])


# ── 2. The detector actually reaches the rescore paths ───────────────────────

def test_conflicting_documents_produce_a_hard_stop():
    hard, _soft = doc_consistency_stops(_conflicting_session())
    assert any("FEIN differs" in m for m in hard), hard


def test_confirming_the_value_clears_the_hard_stop():
    """The Data Consistency picker is the resolution path and must work."""
    session = _conflicting_session()
    session["underwriting_confirmations"] = {"fein": "84-2210987"}
    hard, _soft = doc_consistency_stops(session)
    assert not any("FEIN differs" in m for m in hard), hard


def test_agreeing_documents_produce_no_stops():
    session = _conflicting_session()
    session["docs"][1]["facts"]["fein"] = "84-2210987"
    hard, soft = doc_consistency_stops(session)
    assert hard == []
    assert soft == []


def test_a_single_document_can_never_conflict_with_itself():
    session = _conflicting_session()
    session["docs"] = session["docs"][:1]
    assert doc_consistency_stops(session) == ([], [])


def test_excluded_documents_are_not_compared():
    session = _conflicting_session()
    session["docs"][1]["excluded"] = True
    assert doc_consistency_stops(session) == ([], [])


@pytest.mark.parametrize("session", [
    None, {}, {"docs": None}, {"docs": [{"no_facts": 1}, {"no_facts": 2}]},
    {"docs": "not-a-list"},
])
def test_malformed_sessions_fail_open_and_never_raise(session):
    """A rescore must never break because a legacy session stored an old shape."""
    assert doc_consistency_stops(session) == ([], [])


def test_formatting_differences_alone_are_not_a_conflict():
    """Normalisation-aware: 07/15/25 and 7/15/2025 are the same date."""
    session = _conflicting_session()
    session["docs"][1]["facts"]["fein"] = "84-2210987"
    session["docs"][1]["facts"]["effective_date"] = "7/15/25"
    hard, _soft = doc_consistency_stops(session)
    assert hard == [], hard


# ── 3. Anti-rot: both rescore paths must keep calling the detector ───────────
# This is the point of the fix. If someone later rebuilds the stop list without
# the cross-document detector, the cap silently disappears again and no
# behavioural test would necessarily catch it on a fixture with no conflict.

# 22 Oct 2026 (build 23, Z28 E "named, not fixed"): both rescore paths take
# EVERY list from the stops door, which re-runs this detector (and the picker,
# source and OCR ones they never ran) - the TESTS below pinned the old inline
# copy, so they now pin the door. The structural twin for every package scorer
# is tests/test_build23_stops-after-forms.py.

def _door_runs_the_detector():
    from services import stops_now as _sn
    return "doc_consistency_stops(" in inspect.getsource(_sn.stops_now)


def test_arq_rescore_path_reruns_the_cross_document_detector():
    from services.arq_service import recalculate_session_scores
    src = inspect.getsource(recalculate_session_scores)
    assert "stops_now(" in src and _door_runs_the_detector(), (
        "recalculate_session_scores rebuilds hard_stops from scratch; without "
        "doc_consistency_stops the identity conflicts stop capping the score."
    )


def test_producer_edit_path_reruns_the_cross_document_detector():
    from routes import form_routes as _fr
    src = inspect.getsource(_fr.update_pdf)
    assert "stops_now({**session" in src and _door_runs_the_detector(), (
        "The update-pdf rescore rebuilds hard_stops from scratch; without "
        "doc_consistency_stops the identity conflicts stop capping the score."
    )


def test_every_rebuild_of_the_stop_list_is_accounted_for():
    """Find any OTHER place that rebuilds hard_stops from evaluate_stops.

    Guards against a third rescore path being added later with the same hole.
    Any new site must either call doc_consistency_stops or be added here
    deliberately, with a reason. (22 Oct 2026: the recalculation and the field
    edit no longer rebuild their own - they read the stops door.)
    """
    known = {
        # Extraction owns the ORIGINAL run of all three detectors.
        ("services/extraction_pipeline.py", "_finalize_pipeline"),
    }
    found = set()
    for rel in ("services/arq_service.py", "routes/form_routes.py",
                "services/extraction_pipeline.py", "services/form_service.py"):
        path = _BACKEND / rel
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            body = ast.dump(node)
            if "'evaluate_stops'" in body and "hard_stops" in body:
                found.add((rel, node.name))
    # Self-check first: an empty harvest would make this test pass vacuously,
    # which is exactly the trap C25 documents in CLAUDE.md.
    assert found >= known, (
        f"Harvester found {found} but expected at least {known} - the AST walk "
        "has stopped seeing real call sites, so this test proves nothing."
    )
    unexpected = found - known
    assert not unexpected, (
        f"New stop-list rebuild site(s) found: {unexpected}. Each must re-run "
        "the cross-document identity detector or the 60 cap silently vanishes."
    )


# ── 4. Copy: nothing is blocked, so nothing may claim to be ──────────────────

def test_no_user_facing_message_claims_the_submission_is_blocked():
    """Hard stops cap the score at 60 and block the Submission Ready status
    (19 Oct 2026). They do not gate generation or download."""
    docs = _conflicting_session()["docs"]
    docs[0]["facts"]["effective_date"] = "01/01/2025"
    for msg in check_doc_consistency(docs):
        assert "submission blocked" not in msg.lower(), msg


def test_the_fein_conflict_still_matches_its_hard_stop_pattern():
    """The reworded copy must keep matching _ALWAYS_HARD_PATTERNS."""
    from services.sqs_service import _ALWAYS_HARD_PATTERNS, classify_stops
    hard, _soft = doc_consistency_stops(_conflicting_session())
    assert hard
    assert any(p in hard[0] for p in _ALWAYS_HARD_PATTERNS), hard[0]
    # A non-property submission must not downgrade an identity conflict.
    _can_proceed, remaining, _downgraded = classify_stops(hard, {})
    assert remaining == hard


# ── 5. The raw score survives the cap (defect 2) ─────────────────────────────

def test_the_owners_worked_example_65_capped_to_60_then_plus_10_is_75():
    """Owner's literal rule, 2026-08-16 - this test must never be relaxed.

    Raw 65 with a hard stop open displays 60 while the real 65 is retained.
    Clear the stops and earn 10 points and the result is 75, NOT 70 - because
    credits are added to the RAW score, never to the already-capped one.
    """
    raw = 65
    # While the hard stop is open.
    assert final_score_with_credits(raw, 0, HARD_STOP_CAP) == 60
    # Credit earned while still capped - the ceiling still binds.
    assert final_score_with_credits(raw, 10, HARD_STOP_CAP) == 60
    # Stops cleared: the full earned value is released.
    assert final_score_with_credits(raw, 10, None) == 75
    # The cap an open hard stop resolves to is that same 60 (restored 20 Oct 2026).
    cap, _reason = _resolve_cap(["a hard stop"], [])
    assert cap == HARD_STOP_CAP
    assert final_score_with_credits(raw, 0, cap) == 60
    assert final_score_with_credits(raw, 10, cap) == 60


def test_a_cap_is_a_ceiling_and_never_a_floor():
    """A submission already below the cap keeps its own value."""
    assert final_score_with_credits(42, 0, HARD_STOP_CAP) == 42
    assert final_score_with_credits(78, 0, SOFT_STOP_CAP) == 78
    assert final_score_with_credits(94, 0, SOFT_STOP_CAP) == 85
    # The caps the stops resolve to clamp only a score above them (20 Oct 2026).
    for hard, soft, held in ((["h"], [], 60), ([], ["w"], 85)):
        cap, _reason = _resolve_cap(hard, soft)
        assert final_score_with_credits(94, 0, cap) == held
        assert final_score_with_credits(42, 0, cap) == 42


def test_credits_can_never_push_a_score_over_100():
    assert final_score_with_credits(98, 40, None) == 100


@pytest.mark.parametrize("bad", [None, 0])
def test_final_score_is_none_safe(bad):
    assert final_score_with_credits(bad, bad, None) == 0


def test_hard_beats_soft_and_stops_never_stack():
    cap_one, reason_one = _resolve_cap(["one hard stop"], ["a warning"])
    cap_many, _ = _resolve_cap(["h1", "h2", "h3"], ["w1", "w2"])
    assert cap_one == cap_many == HARD_STOP_CAP      # never stacks
    assert reason_one == "one hard stop"             # the reason is recorded
    assert _resolve_cap([], ["only a warning"])[0] == SOFT_STOP_CAP
    assert _resolve_cap([], [])[0] is None
    # (19 Oct 2026, Brent: a hard stop blocks Submission Ready) - the blocker is recorded, and never stacks.
    one = readiness_fields(95, ["one hard stop"])
    many = readiness_fields(95, ["h1", "h2", "h3"])
    assert one["ready_blockers"] == ["one hard stop"]     # the reason is recorded
    assert one["submission_ready"] is many["submission_ready"] is False
    assert tier_for_score(95, 1) == tier_for_score(95, 3)  # one or three, the same status
    assert routing_for_score(95, 1) == routing_for_score(95, 3) == "priority_review"


def test_cross_form_issues_cap_the_package_too():
    cap, reason = _resolve_cap([], [], hard_cross=["cross-form conflict"])
    assert cap == HARD_STOP_CAP
    assert reason == "cross-form conflict"
    facts = {"applicant_name": "ORBIN CONTRACTING LLC", "effective_date": "07/15/2025"}
    pkg = calculate_package_sqs(
        facts=facts, flags={}, form_results=[], hard_stops=[], soft_stops=[],
        cross_issues=[{"type": "hard_stop", "code": "x", "message": "cross-form conflict"}],
        session_data={},
    )
    # The package holds the same 60 and names it (no hard_stops card carries it)...
    assert pkg["cap_applied"] == HARD_STOP_CAP and pkg["cap_reason"] == "cross-form conflict"
    assert pkg["cap_hard_stops"] == ["cross-form conflict"]
    assert pkg["package_sqs_score"] == min(pkg["raw_sqs_score"], HARD_STOP_CAP)
    # ...and (19 Oct 2026) it blocks Submission Ready, named by its own message; a warning never does.
    assert pkg["ready_blockers"] == ["cross-form conflict"]
    warned = calculate_package_sqs(
        facts=facts, flags={}, form_results=[], hard_stops=[], soft_stops=[],
        cross_issues=[{"type": "soft_warning", "code": "y", "message": "cross-form warning"}],
        session_data={},
    )
    assert warned["ready_blockers"] == []


def test_scorers_report_the_uncapped_score_and_the_reason():
    facts = {"applicant_name": "ORBIN CONTRACTING LLC", "effective_date": "07/15/2025"}
    flags = {}
    stop = "Umbrella detected but no underlying GL or Auto limits found"

    form = calculate_sqs(
        facts=facts, flags=flags, mapped_data={"a": "x"}, form_schema={"a": {}},
        selected_form_ids=["ACORD_125"], hard_stops=[stop], soft_stops=[],
        tier2_score=60, form_id="ACORD_125",
    )
    pkg = calculate_package_sqs(
        facts=facts, flags=flags, form_results=[form], cross_issues=[],
        hard_stops=[stop], soft_stops=[], session_data={},
    )
    for result, key in ((form, "sqs_score"), (pkg, "package_sqs_score")):
        assert result["cap_applied"] == HARD_STOP_CAP
        assert result["cap_reason"] == stop
        assert result[key] <= HARD_STOP_CAP
        # The real number is retained rather than overwritten.
        assert result["raw_sqs_score"] >= result[key]
        # (19 Oct 2026, Brent: a hard stop blocks Submission Ready) - the reason is the blocker too.
        assert result["ready_blockers"] == [stop]
        assert result["open_hard_stops"] == 1 and result["submission_ready"] is False


# ── 6. Form and package remain SEPARATE calculations ─────────────────────────

def test_form_and_package_scores_stay_independently_computed():
    """The cap work must not converge the two scorers.

    P1 and P2 use different models by design (the form uses a per-ACORD
    checklist, the package uses tier1/tier2/fill-rate and a deduction model).
    P3/P4/P6 legitimately share one implementation.
    """
    facts = {
        "applicant_name": "ORBIN CONTRACTING LLC", "mailing_address": "12 Main St, Austin TX",
        "effective_date": "07/15/2025", "expiration_date": "07/15/2026",
        "lines_of_business": ["General Liability"], "entity_type": "LLC",
        "contact_name": "Jo", "producer_name": "ACME Agency", "total_revenue": "1000000",
        "operations_description": "roofing contractor", "gl_limits": "$1,000,000",
        "gl_each_occurrence": "$1,000,000",
    }
    flags = {"has_general_liability": True}
    form = calculate_sqs(
        facts=facts, flags=flags, mapped_data={"a": "x"}, form_schema={"a": {}},
        selected_form_ids=["ACORD_125"], hard_stops=[], soft_stops=[],
        tier2_score=60, form_id="ACORD_125",
    )
    pkg = calculate_package_sqs(
        facts=facts, flags=flags, form_results=[form], cross_issues=[],
        hard_stops=[], soft_stops=[], session_data={},
    )
    assert form["breakdown"]["structural_completeness"] != pkg["pillars"]["structural_completeness"]
    assert form["breakdown"]["exposure_consistency"] != pkg["pillars"]["exposure_consistency"]
    # 2026-08-24: asserting the two HEADLINES are unequal was wrong - two
    # independently computed weighted sums may legitimately collide on one
    # fixture (they did, 65 == 65, after the C2 loss-history renumbering
    # shifted both scores for different reasons; the pillar asserts above
    # still prove the models differ). Guard the real property structurally:
    # the package headline reconstructs from the PACKAGE's own pillars, so a
    # regression that copies the form headline into the package would mismatch.
    from services.sqs_service import SPEC_PILLAR_WEIGHTS, _weighted_pillar_sum
    assert pkg["raw_sqs_score"] == _weighted_pillar_sum(pkg["pillars"], SPEC_PILLAR_WEIGHTS)


def test_package_score_is_not_an_average_of_the_form_scores():
    facts = {"applicant_name": "ACME LLC", "effective_date": "07/15/2025"}
    flags = {}
    forms = [
        calculate_sqs(
            facts=facts, flags=flags, mapped_data={"a": "x"}, form_schema={"a": {}},
            selected_form_ids=[fid], hard_stops=[], soft_stops=[],
            tier2_score=60, form_id=fid,
        )
        for fid in ("ACORD_125", "ACORD_126", "ACORD_140")
    ]
    pkg = calculate_package_sqs(
        facts=facts, flags=flags, form_results=forms, cross_issues=[],
        hard_stops=[], soft_stops=[], session_data={},
    )
    avg = round(sum(f["sqs_score"] for f in forms) / len(forms))
    assert pkg["package_sqs_score"] != avg, (
        "The package score must be computed independently, never averaged."
    )


# ── 7. One tier ladder (defect 8) ────────────────────────────────────────────

def test_exactly_90_is_submission_ready():
    """Owner decision 2026-08-16: 90 and above is Submission Ready.

    This boundary used to disagree with itself - both scorers said `> 90` while
    audit_routes and BOTH frontend readiness surfaces said `>= 90`, so a
    submission on exactly 90 showed "Almost There" on its tier chip and
    "Ready to Send Submission" on the banner next to it.
    """
    assert tier_for_score(89)[1] == "Almost There"
    assert tier_for_score(90)[1] == "Submission Ready"
    assert tier_for_score(91)[1] == "Submission Ready"


def test_the_route_helper_uses_the_same_ladder_as_the_scorers():
    from routes.audit_routes import _grade_from_score
    for score in range(0, 101):
        assert _grade_from_score(score) == tier_for_score(score), score


def test_grade_letter_and_readiness_label_agree_at_90():
    """The "A" grade already began at 90; the label now matches it."""
    assert tier_for_score(90)[0] == "A"
    assert tier_for_score(90)[1] == "Submission Ready"


def test_no_inline_tier_ladder_survives_anywhere():
    """Every tier label must come from tier_for_score - no fourth copy."""
    import inspect
    import services.sqs_service as S
    for fn in (S.calculate_sqs, S.calculate_package_sqs,
               S.calculate_package_sqs_spec_compliant):
        src = inspect.getsource(fn)
        assert '"Submission Ready" if' not in src, f"{fn.__name__} has its own ladder"
        assert '("Submission Ready"' not in src, f"{fn.__name__} has its own ladder"


def test_backend_and_frontend_agree_on_the_readiness_boundary():
    """The frontend readiness surfaces must use the same rule as the backend."""
    fe = _BACKEND.parent / "frontend" / "src" / "components" / "form" / "AcordModal.jsx"
    if not fe.exists():
        return
    src = fe.read_text(encoding="utf-8")
    # (19 Oct 2026, Brent: a hard stop blocks Submission Ready) - both surfaces read the server's flag first.
    assert 'const ready = typeof s?.submission_ready === "boolean" ? s.submission_ready : avg >= 90;' in src, (
        "session-list readiness no longer reads submission_ready (old payloads: >= 90)"
    )
    assert '{submissionReady(packageSqs) ? "Ready to Send Submission"' in src, (
        "submission banner no longer uses submissionReady; backend submission_ready does"
    )
    import json
    import shutil
    import subprocess
    if shutil.which("node") is None:
        return
    util = _BACKEND.parent / "frontend" / "src" / "utils" / "formatters.js"
    run = subprocess.run(["node", "--input-type=module", "-e", (
        f"import {{ submissionReady }} from {json.dumps(util.as_uri())};"
        "console.log(JSON.stringify([null, {package_sqs_score: 95, submission_ready: false},"
        "{package_sqs_score: 95, submission_ready: true}, {package_sqs_score: 90},"
        "{package_sqs_score: 89}, {sqs_score: 91}].map(submissionReady)));")],
        capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    # the server's flag wins; an old payload falls back to the same 90 tier_for_score uses
    assert json.loads(run.stdout) == [False, False, True, True, False, True]
    assert tier_for_score(90)[1] == "Submission Ready" and tier_for_score(89)[1] != "Submission Ready"


# ── 8. One score everywhere (defect 3) ───────────────────────────────────────

def test_no_surface_averages_the_form_scores_as_the_submission_score():
    """Averaging survives ONLY as a labelled fallback, never as the preferred path.

    Four surfaces used to average the per-form scores and present the result as
    the submission score. Each must now read the real package score first.
    """
    checks = [
        ("routes/form_routes.py",              "package_sqs_score"),
        ("routes/download_routes.py",          "package_sqs_score"),
        ("services/cover_service.py",          "package_score"),
        ("repositories/session_repository.py", "package_sqs_score"),
    ]
    for rel, needle in checks:
        src = (_BACKEND / rel).read_text(encoding="utf-8")
        assert needle in src, f"{rel} no longer reads the package score"

    fe = _BACKEND.parent / "frontend" / "src" / "components" / "form" / "AcordModal.jsx"
    if fe.exists():
        src = fe.read_text(encoding="utf-8")
        assert "package_sqs_score" in src, "sessions list must read the package score"
        assert "avgSqs" not in src, "the old average helper is still referenced"


def test_cover_narrative_prefers_the_package_score_over_an_average():
    import inspect
    from services.cover_service import generate_ai_cover_narrative
    sig = inspect.signature(generate_ai_cover_narrative)
    assert "package_score" in sig.parameters
    src = inspect.getsource(generate_ai_cover_narrative)
    assert "if package_score is not None" in src


# ── 9. The retained-for-imports scorer must not drift ────────────────────────

def test_the_legacy_package_scorer_is_unreachable_from_production():
    """calculate_package_sqs_spec_compliant is retained for imports only.

    It is a second copy of the package scorer. If production ever starts calling
    it, two scorers are live at once - the exact duplication that let the
    umbrella-SIR and auto-symbol bugs survive their first fix.
    """
    callers = []
    for path in list((_BACKEND / "services").rglob("*.py")) + \
                list((_BACKEND / "routes").rglob("*.py")) + \
                list((_BACKEND / "repositories").rglob("*.py")):
        src = path.read_text(encoding="utf-8")
        for line in src.splitlines():
            if "calculate_package_sqs_spec_compliant" in line and not line.strip().startswith("#"):
                if line.strip().startswith("def "):
                    continue
                callers.append(f"{path.name}: {line.strip()[:70]}")
    assert not callers, f"Legacy package scorer is now reachable: {callers}"


def test_both_package_scorers_share_one_cap_rule_and_one_tier_ladder():
    import inspect
    import re
    import services.sqs_service as S
    # The one cap door (restored 20 Oct 2026): hard wins, and no scorer may grow a ceiling of its own.
    assert S._resolve_cap(["h"], ["s"], hard_cross=["c"]) == (S.HARD_STOP_CAP, "h")
    for fn in (S.calculate_package_sqs, S.calculate_package_sqs_spec_compliant, S.calculate_sqs):
        src = inspect.getsource(fn)
        assert "_resolve_cap" in src, f"{fn.__name__} has its own cap copy"
        code = "\n".join(line.split("#")[0] for line in src.splitlines())
        assert not re.search(r"min\([^)]*\b(60|85)\b", code), (
            f"{fn.__name__} still carries an inline cap"
        )
        # One readiness ladder and one routing rule, both reading the open hard stops.
        assert "tier_for_score(" in code, f"{fn.__name__} has its own tier ladder"
        assert "routing_for_score(" in code, f"{fn.__name__} has its own routing rule"
