"""
V1 H7 - Audit / Edit History Completion (client section 12).

The client's ask, in his words: the E&O record must be "generated from real
system history rather than reconstructed later from incomplete current state",
and ONE event/history model must serve product history, debugging, source
lineage and the E&O Audit Record.

These tests pin the four things that were measured broken in H7-A:
  1. all eight of his material events reach the append-only spine (1 of 8 did);
  2. every event carries his seven attributes in a fixed shape;
  3. the record names a HUMAN (it named none, in twelve sections);
  4. one model - `activity_service` writes and reads the spine, not a second
     near-identical table.

Plus the anti-rot layer, which is the point: a new material act that forgets to
reach the spine fails the build rather than being discovered in an E&O claim.
"""
import ast
import inspect
import pathlib
import re

import pytest

import services.audit_history as AH
import services.audit_service as AS

_BACKEND = pathlib.Path(__file__).resolve().parents[1]


def _src(rel: str) -> str:
    return (_BACKEND / rel).read_text(encoding="utf-8", errors="replace")


# ═══════════════════════════════════════════════════════════════════════════
# 1. Role derivation (D51)
# ═══════════════════════════════════════════════════════════════════════════

def test_a_client_answer_is_never_filed_as_a_producer_action():
    """THE attribution bug this rule exists to prevent.

    `arq_service` applies client answers under the SESSION OWNER's user id -
    the client has no account - so deciding role on "is there a user_id" files
    every client answer as a producer action.
    """
    assert AH.derive_role(source="client_arq", user_id="owner-123") == AH.ROLE_CLIENT
    assert AH.derive_role(source="client", user_id="owner-123") == AH.ROLE_CLIENT


def test_role_falls_back_to_system_only_when_nobody_acted():
    assert AH.derive_role(user_id="u1") == AH.ROLE_PRODUCER
    assert AH.derive_role(user_id=None) == AH.ROLE_SYSTEM
    assert AH.derive_role(user_id="  ") == AH.ROLE_SYSTEM
    assert AH.derive_role(source="ai", user_id="u1") == AH.ROLE_SYSTEM


def test_an_explicit_role_wins_but_only_a_valid_one():
    assert AH.derive_role(source="client_arq", role=AH.ROLE_PRODUCER) == AH.ROLE_PRODUCER
    # A typo must not become a role.
    assert AH.derive_role(source="client_arq", role="Producer") == AH.ROLE_CLIENT


def test_no_rbac_role_column_was_invented():
    """D51: role is DERIVED. `users` gains no column, because there is no RBAC
    in this codebase to read - `admin_users` is an email allow-list."""
    ddl = _src("config/database.py")
    users_block = ddl.split("CREATE TABLE IF NOT EXISTS users", 1)[1].split(")", 1)[0]
    assert " role " not in users_block.lower()


# ═══════════════════════════════════════════════════════════════════════════
# 2. The generated-value override - the client's 8th event, DERIVED
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("prior", ["ai_high", "ai_low", "ai", "low_confidence", "ai_verified"])
def test_replacing_a_model_produced_value_is_an_override(prior):
    assert AH.change_kind(prior, "24", "30") == AH.KIND_OVERRIDE


@pytest.mark.parametrize("prior", ["filled", "deterministic", "client_arq", None])
def test_replacing_a_human_value_is_a_correction(prior):
    assert AH.change_kind(prior, "24", "30") == AH.KIND_CORRECTION


@pytest.mark.parametrize("prior", ["ai_high", "low_confidence", "missing_required", None])
def test_a_field_that_was_empty_can_never_have_been_overridden(prior):
    """ORDER BUG, caught while building this (H7-B).

    `previous_source` was consulted before "was there a value at all", so
    filling a BLANK required box whose highlight label happens to be AI-ish
    recorded "the producer overrode an AI-generated value" against a box the AI
    never filled. In an E&O record that is a false statement about a human.
    """
    assert AH.change_kind(prior, None, "30") == AH.KIND_FILL
    assert AH.change_kind(prior, "", "30") == AH.KIND_FILL


def test_clearing_a_value_is_a_retraction_whatever_produced_it():
    assert AH.change_kind("ai_high", "24", "") == AH.KIND_RETRACTION
    assert AH.change_kind("filled", "24", None) == AH.KIND_RETRACTION


def test_both_confidence_vocabularies_are_covered_by_one_list():
    """There are two confidence vocabularies (the FACT envelope's and the FORM
    highlight's) and a caller may hold either. Asking call sites to translate is
    how they drifted apart; the classifier knows both."""
    assert {"ai_high", "ai_low"} <= set(AH._AI_SOURCES)          # fact envelope
    assert {"low_confidence", "ai_verified"} <= set(AH._AI_SOURCES)  # form highlight
    # `filled` means deterministic-or-human in BOTH and must never be an override.
    assert "filled" not in AH._AI_SOURCES


def test_the_dead_fieldmap_stub_is_not_used_as_a_provenance_signal():
    """`_load_fieldmap` returns ({}, set()) - a stub. Anything keying AI
    provenance off its `ai_set` is reading an always-empty set."""
    from services.pdf_service import _load_fieldmap
    assert _load_fieldmap("ACORD_125") == ({}, set())


def test_prior_provenance_prefers_the_fact_envelope_and_never_guesses():
    from routes.form_routes import _prior_provenance
    facts = {"num_employees": {"value": "24", "confidence": "ai_high", "source": "ai"}}
    # 1. the envelope states provenance - it wins over the highlight label
    assert _prior_provenance(facts, "num_employees", "filled") == "ai_high"
    # 2. no canonical fact -> the highlight label is the fallback
    assert _prior_provenance(facts, None, "low_confidence") == "low_confidence"
    # 3. an EMPTY envelope value is an absence, not an AI value
    assert _prior_provenance({"k": {"value": "", "confidence": "ai_high"}}, "k", None) is None
    # 4. a legacy bare string destroyed its provenance - say nothing, don't guess
    assert _prior_provenance({"k": "24"}, "k", None) is None


# ═══════════════════════════════════════════════════════════════════════════
# 3. The envelope - the client's seven attributes, in fixed positions
# ═══════════════════════════════════════════════════════════════════════════

_SEVEN = ("fact_key", "field_name", "previous_value", "new_value",
          "actor_id", "role", "reason", "action")


def test_every_envelope_carries_the_seven_attributes():
    env = AH.build_change_envelope(
        event_type=AH.EVENT_FIELD_CHANGED, action=AH.ACTION_EDITED,
        fact_key="num_employees", field_name="X", previous_value="24",
        new_value="30", previous_source="ai_high", source="producer",
        user_id="u1", reason="corrected from payroll register",
    )
    for key in _SEVEN:
        assert key in env, key
    assert env["role"] == AH.ROLE_PRODUCER
    assert env["change_kind"] == AH.KIND_OVERRIDE
    # timestamp is the ROW's created_at, written by the spine - never a value
    # the caller can disagree with.
    assert "timestamp" not in env and "occurred_at" not in env


def test_the_seven_attributes_can_never_hide_inside_detail():
    """They went missing the first time by living in free-form payloads."""
    env = AH.build_change_envelope(
        event_type=AH.EVENT_RECOMMENDATION_DISMISSED,
        action=AH.ACTION_DISMISSED, user_id="u1", reason="not applicable",
        detail={"rec_id": "rec_1", "role": "IGNORED", "reason": "IGNORED"},
    )
    assert env["reason"] == "not applicable"
    assert env["role"] == AH.ROLE_PRODUCER
    assert env["detail"]["rec_id"] == "rec_1"


def test_blank_and_missing_values_normalise_to_one_spelling():
    env = AH.build_change_envelope(event_type=AH.EVENT_FIELD_CHANGED,
                                   previous_value="   ", new_value=None)
    assert env["previous_value"] is None and env["new_value"] is None


def test_values_are_clipped_exactly_like_the_change_log():
    """The spine and `field_source_audit` carry the SAME values; clipping them
    differently would make one section of the record contradict another."""
    assert AH.VALUE_MAX == 2000
    env = AH.build_change_envelope(event_type=AH.EVENT_FIELD_CHANGED,
                                   new_value="x" * 5000)
    assert len(env["new_value"]) == 2000


# ═══════════════════════════════════════════════════════════════════════════
# 4. Reading the spine - both shapes, and the actor
# ═══════════════════════════════════════════════════════════════════════════

def test_pre_h7_events_still_render_as_history():
    """C5-A's five event types predate the envelope. They are REAL history and
    must not be dropped for being written before the shape existed."""
    row = {"event_type": "documents_uploaded", "user_id": "u1",
           "created_at": "2026-08-27T10:00:00Z",
           "event_data": {"document_count": 2, "facts_extracted": 47}}
    out = AH.normalize_event(row, {"u1": {"id": "u1", "name": "Vinay", "email": "v@x.com"}})
    assert out["legacy"] is True
    assert out["actor_name"] == "Vinay"
    assert out["role"] == AH.ROLE_PRODUCER
    assert out["detail"]["document_count"] == 2
    assert out["occurred_at"] == "2026-08-27T10:00:00Z"


def test_an_unresolvable_actor_still_renders_as_its_id():
    """An E&O record that silently omits an actor is worse than one showing a
    raw identifier."""
    row = {"event_type": "field_changed", "user_id": "ghost", "created_at": "T",
           "event_data": AH.build_change_envelope(
               event_type=AH.EVENT_FIELD_CHANGED, user_id="ghost")}
    out = AH.normalize_event(row, {})
    assert out["actor_id"] == "ghost" and out["actor_name"] == "ghost"


def test_actor_ids_are_collected_from_both_the_row_and_the_envelope():
    rows = [
        {"user_id": "a", "event_data": {}},
        {"user_id": None, "event_data": {"schema": 1, "actor_id": "b"}},
        {"user_id": "c", "event_data": {"schema": 1, "actor_id": "d"}},
        "not-a-dict",
    ]
    assert AH.actor_ids_in(rows) == {"a", "b", "c", "d"}


def test_normalize_survives_a_junk_payload():
    for bad in (None, "text", 5, []):
        out = AH.normalize_event({"event_type": "x", "created_at": "T",
                                  "event_data": bad}, {})
        assert out["event_type"] == "x" and out["detail"] == {}


# ═══════════════════════════════════════════════════════════════════════════
# 5. ANTI-ROT: every material event has a writer that reaches the spine
# ═══════════════════════════════════════════════════════════════════════════

def test_all_eight_client_events_reach_the_spine():
    """H7-A measured 1 of 8. If a future change stops emitting one of these,
    this fails rather than the gap being found in an E&O claim."""
    # Scanned across the whole service+route layer, not one file: a writer may
    # legitimately live where the act happens (client answers are applied in
    # arq_service, not audit_service).
    blob = "".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in sorted((_BACKEND / "services").glob("*.py"))
        + sorted((_BACKEND / "routes").glob("*.py"))
        if path.name != "audit_history.py"          # the vocabulary, not a writer
    )
    missing = [e for e in sorted(AH.MATERIAL_CHANGE_EVENTS)
               if f"EVENT_{e.upper()}" not in blob and f'"{e}"' not in blob]
    assert missing == [], f"material events with no writer on the spine: {missing}"


_MUST_EMIT = {
    "log_field_change":                    AH.EVENT_FIELD_CHANGED,
    "mark_recommendation_dismissed":       AH.EVENT_RECOMMENDATION_DISMISSED,
    "mark_recommendation_answer_recorded": AH.EVENT_RECOMMENDATION_ANSWERED,
    "set_issue_status":                    AH.EVENT_ISSUE_STATUS_CHANGED,
    "log_underwriting_confirmation":       AH.EVENT_CONFLICT_RESOLVED,
    "log_integrity_resolution":            AH.EVENT_PRODUCER_OVERRIDE,
    "log_document_reclassified":           AH.EVENT_PRODUCER_OVERRIDE,
    "log_download_with_open_recs":         AH.EVENT_PACKAGE_DOWNLOADED,
}


@pytest.mark.parametrize("fn_name,event", sorted(_MUST_EMIT.items()))
def test_the_writer_emits_from_inside_not_from_a_route(fn_name, event):
    """D49: emitted by the writer the action already goes through. A route can
    forget; a writer the act must pass cannot."""
    src = inspect.getsource(getattr(AS, fn_name))
    assert "record_material_change" in src, f"{fn_name} does not reach the spine"
    const = f"EVENT_{event.upper()}"
    assert const in src, f"{fn_name} does not emit {event}"


def test_a_failed_history_write_never_undoes_the_act_it_records():
    """The act is already persisted by the time the event is written. Every
    emit sits in its OWN try/except so a spine failure cannot be reported as
    'the change was not recorded' (D35)."""
    for fn_name in _MUST_EMIT:
        src = inspect.getsource(getattr(AS, fn_name))
        idx = src.index("record_material_change")
        # the emit must be inside a try, with its own except
        assert "try:" in src[:idx], fn_name
        assert "except" in src[idx:], fn_name


def test_the_spine_stays_append_only():
    """The whole property that makes it usable as history."""
    for rel in ("services/audit_service.py", "services/activity_service.py",
                "services/audit_history.py"):
        src = _src(rel)
        assert "UPDATE audit_events" not in src, rel
        assert "DELETE FROM audit_events" not in src, rel


def test_record_material_change_refuses_a_sessionless_event():
    """`audit_events.session_id` is NOT NULL - a sessionless call would raise
    inside the writer and be swallowed, looking like a recorded event."""
    src = inspect.getsource(AS.record_material_change)
    assert "if not session_id" in src


# ═══════════════════════════════════════════════════════════════════════════
# 6. ONE MODEL (D50) - activity_service is an adapter, not a second store
# ═══════════════════════════════════════════════════════════════════════════

def test_activity_writes_the_spine_not_its_own_table():
    src = _src("services/activity_service.py")
    assert "INSERT INTO activity_events" not in src
    assert "INSERT INTO audit_events" in src
    assert "VISIBILITY_PRODUCT" in src


def test_the_activity_feed_reads_the_spine_and_keeps_the_legacy_rows():
    """Producers must not lose feed history to the migration."""
    src = inspect.getsource(__import__("services.activity_service",
                                       fromlist=["get_user_activity"]).get_user_activity)
    assert "FROM audit_events" in src
    assert "FROM activity_events" in src, "legacy rows dropped from the feed"
    assert "UNION ALL" in src
    assert "visibility=$3" in src, "E&O events would flood the producer's feed"


def test_the_nine_product_event_names_are_unchanged():
    """ActivityLogModal renders per type and falls back to the raw name with a
    grey dot, so renaming any of these silently degrades the live feed. One
    model does not mean one event NAME."""
    ui = (_BACKEND.parent / "frontend/src/components/account/ActivityLogModal.jsx"
          ).read_text(encoding="utf-8", errors="replace")
    for event in sorted(AH.PRODUCT_VISIBLE_EVENTS):
        assert f"{event}:" in ui, f"{event} is not rendered by the Activity Log"
    assert len(AH.PRODUCT_VISIBLE_EVENTS) == 9


def test_activity_service_still_exports_every_constant_its_callers_import():
    """The constants moved to the one vocabulary; the re-export is what keeps
    every existing `from services.activity_service import EVENT_*` working."""
    import services.activity_service as A
    for name in ("EVENT_FORMS_GENERATED", "EVENT_SQS_SCORED", "EVENT_ARQ_SENT",
                 "EVENT_ARQ_OPENED", "EVENT_ARQ_IN_PROGRESS",
                 "EVENT_ARQ_SUBMITTED", "EVENT_ANSWERS_APPLIED",
                 "EVENT_REMINDER_SENT", "EVENT_DOWNLOAD"):
        assert hasattr(A, name), name
        assert getattr(A, name) == getattr(AH, name)


def test_every_record_event_call_site_still_resolves():
    """AST sweep: the adapter changed destination, not signature."""
    offenders = []
    for rel in ("routes/arq_routes.py", "routes/download_routes.py",
                "routes/form_routes.py"):
        tree = ast.parse(_src(rel))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "record_event"):
                # user_id, session_id, event_type are positional
                if len(node.args) < 3:
                    offenders.append(f"{rel}:{node.lineno}")
    assert offenders == [], offenders


def test_snapshot_dedupe_is_not_disturbed_by_the_new_event_types():
    """5.12's dedupe reads back the LAST `sqs_snapshot`. It filters by type, so
    the H7 events cannot make it compare against a foreign signature."""
    src = inspect.getsource(AS.log_sqs_snapshot_if_changed)
    assert 'event_type="sqs_snapshot"' in src


# ═══════════════════════════════════════════════════════════════════════════
# 7. The record names a human, and shows the overrides it used to hide
# ═══════════════════════════════════════════════════════════════════════════

def test_every_export_reader_selects_its_actor():
    """H7-A: user_id was stored in five tables, SELECTed in two, rendered in
    none. A reader that drops the column makes the actor unrenderable."""
    for fn in (AS.get_field_change_log, AS.get_download_audit_log,
               AS.get_dismissed_recommendations, AS.get_issue_statuses,
               AS.get_producer_answers, AS.get_underwriting_confirmations,
               AS.get_integrity_audit_log):
        assert "user_id" in inspect.getsource(fn), fn.__name__


def test_the_export_resolves_actors_once_and_attaches_them():
    src = inspect.getsource(AS.get_audit_trail_export)
    assert "resolve_actors" in src
    assert "_with_actor" in src
    assert '"history"' in src


def test_resolve_actors_is_one_round_trip_not_one_per_row():
    """Every field edit writing a user lookup would put a query on the hottest
    path in the app for something the reader can do once."""
    src = inspect.getsource(AS.resolve_actors)
    assert "ANY($1::text[])" in src
    assert src.count("await conn.fetch") == 1


def test_submission_integrity_audit_finally_has_a_reader():
    """It had three writers and NO reader anywhere - the same defect C5-A fixed
    for `underwriting_confirmation_audit`, recurring one table over. Two of the
    client's 'producer override' events lived here, recorded and invisible."""
    readers = []
    for path in sorted((_BACKEND / "services").glob("*.py")) + \
                sorted((_BACKEND / "routes").glob("*.py")):
        text = path.read_text(encoding="utf-8", errors="replace")
        if re.search(r"FROM\s+submission_integrity_audit", text):
            readers.append(path.name)
    assert readers, "submission_integrity_audit still has no reader"
    assert "audit_service.py" in readers


def test_the_integrity_reader_excludes_the_systems_own_verdict():
    """`integrity_assessed` is the system's verdict, not a human act; the
    resolution row already carries the verdict it acted on."""
    src = inspect.getsource(AS.get_integrity_audit_log)
    assert "integrity_assessed" in src and "<>" in src


def test_the_record_renders_the_actor_and_the_history():
    ui = (_BACKEND.parent / "frontend/src/components/form/AcordModal.jsx"
          ).read_text(encoding="utf-8", errors="replace")
    assert "COMPLETE HISTORY (chronological)" in ui
    assert "PRODUCER OVERRIDES" in ui
    assert "_auditWho" in ui
    # "Changed by: producer edit" was a METHOD, not an actor.
    assert 'Changed by: ${_auditWho(' in ui
    # One history view, not two - the old EVENT LOG rendered the same rows with
    # less on each.
    assert 'lines.push("EVENT LOG")' not in ui


# ═══════════════════════════════════════════════════════════════════════════
# 8. Nothing C5 shipped was broken on the way
# ═══════════════════════════════════════════════════════════════════════════

def test_the_mutable_workflow_tables_were_not_turned_into_history():
    """D49: they stay mutable. dismiss-credit, the download gate, the issue rail
    and reopen all read them as CURRENT STATE and must keep doing so - replacing
    them with projections touches C1, C3, C5, H1 and H2 at once."""
    svc = _src("services/audit_service.py")
    assert "ON CONFLICT (session_id, rec_id) DO UPDATE" in svc
    assert "ON CONFLICT (session_id, issue_id) DO UPDATE" in svc
    # reopen is still the only writer that can clear an action
    assert "SET action=NULL" in svc


def test_the_new_columns_are_additive_on_both_paths():
    """config/database.py convention: CREATE for a fresh database, ALTER for an
    existing one - no manual migration step, ever."""
    from models.schemas import AUDIT_EVENT_STATEMENTS, FIELD_SOURCE_AUDIT_STATEMENTS
    ae = " ".join(AUDIT_EVENT_STATEMENTS)
    fs = " ".join(FIELD_SOURCE_AUDIT_STATEMENTS)
    def _create_block(statements):
        # The CREATE is the first statement; a CHECK constraint contains its own
        # ")" so the block cannot be found by splitting on the first one.
        return next(s for s in statements if "CREATE TABLE" in s)

    ae_create = _create_block(AUDIT_EVENT_STATEMENTS)
    fs_create = _create_block(FIELD_SOURCE_AUDIT_STATEMENTS)
    for col in ("package_label", "visibility"):
        assert f"ADD COLUMN IF NOT EXISTS {col}" in ae, col
        assert col in ae_create, f"{col} missing from CREATE"
    for col in ("previous_source", "reason"):
        assert f"ADD COLUMN IF NOT EXISTS {col}" in fs, col
        assert col in fs_create, f"{col} missing from CREATE"


def test_log_field_changes_new_arguments_are_optional():
    """Eight existing call sites must keep working untouched; only update_pdf
    has the prior confidence to hand."""
    sig = inspect.signature(AS.log_field_change)
    for name in ("previous_source", "reason"):
        assert sig.parameters[name].default is None, name


def test_the_activity_feed_shape_the_ui_consumes_is_unchanged():
    src = inspect.getsource(__import__("services.activity_service",
                                       fromlist=["get_user_activity"]).get_user_activity)
    for col in ("id", "session_id", "package_label", "event_type",
                "event_data", "created_at"):
        assert col in src, col


# ═══════════════════════════════════════════════════════════════════════════
# 9. Defects the FIRST LIVE RUN exposed (H7-D, 2026-08-27)
# ═══════════════════════════════════════════════════════════════════════════

def test_a_confirm_prompt_retires_on_either_answer():
    """THE OWNER'S REPORTED BUG: "i solved an issue, reopened and submitted
    with diff answer then it is not getting saved".

    It WAS saved - fact, envelope and audit row were all correct on the live
    record. The card lied. `_NEW_VENTURE_CONFIRM_REC` was appended whenever
    loss history was absent, with no reference to whether it had been answered:
    "Yes" makes the pillar Not Applicable so the rec stops being generated and
    the card closes, but "No" changes nothing the scorer reads, so the rec came
    back identical, auto-resolve had nothing to stamp, and the card reappeared
    Open with an empty dropdown.

    The class: a confirm-X prompt that only ONE of its two answers can retire.
    """
    from services.sqs_service import calculate_p4_loss_history, _NEW_VENTURE_CONFIRM_REC

    def asks(facts, flags):
        _, recs = calculate_p4_loss_history(dict(facts), dict(flags))
        return any(_NEW_VENTURE_CONFIRM_REC in r for r in recs), recs

    base = {"applicant_name": {"value": "Marrow Ridge Mechanical LLC"}}

    asked, _ = asks(base, {})
    assert asked, "an unanswered new-venture question must still be asked"

    answered_no = {**base, "new_venture_indicator": {
        "value": "No - the business has prior operations", "source": "producer"}}
    asked, recs = asks(answered_no, {"new_venture_confirmed": False})
    assert not asked, "answering NO must retire the prompt - this is the bug"
    # ...and the REAL gap must survive: the producer still has no loss history.
    assert any("No loss history provided" in r for r in recs), \
        "silencing the prompt must not silence the genuine loss-history gap"

    # A blank is not an answer (Principle 3: missing does not mean No).
    asked, _ = asks({**base, "new_venture_indicator": {"value": "   "}}, {})
    assert asked


def test_a_no_op_is_never_recorded_as_a_modification():
    """LIVE RUN: submitting the SAME answer twice produced
    `"No ..." -> "No ..."  /  Change: corrected an existing entry` - a record
    stating the producer altered something they did not."""
    src = inspect.getsource(AS.log_field_change)
    assert "record_unchanged" in src
    assert "_prev_cmp == _new_cmp" in src
    sig = inspect.signature(AS.log_field_change)
    assert sig.parameters["record_unchanged"].default is False


def test_the_schedule_paths_opt_out_of_the_no_op_guard():
    """A schedule's before/after is a ROW COUNT. Editing a VIN in row 2 of a
    three-row fleet leaves "3 row(s)" -> "3 row(s)" while genuinely changing the
    data, so the guard would delete a real modification."""
    for rel in ("routes/audit_routes.py", "routes/arq_routes.py"):
        src = _src(rel)
        assert "record_unchanged=True" in src, rel
        assert "schedule::" in src, rel


def test_confirming_an_unchanged_conflict_prints_no_arrow():
    """C5-D fix 7 killed `Chosen: $3M (was: $3M)` in the resolutions section.
    Under D16 the suggested value stamps BEFORE confirmation, so the history
    section reintroduced it as `"$3,000,000" -> "$3,000,000"` one layer up."""
    src = inspect.getsource(AS.log_underwriting_confirmation)
    assert "_prev = (previous_value" in src
    assert "previous_value=_prev" in src


def test_the_no_reason_sentinel_is_never_printed_as_a_reason():
    """The live record read `Reason: No reason provided`, which states that the
    producer gave one. One named sentinel, shared with the credit predicate so
    the score and the record cannot disagree about what counts as a reason."""
    assert "No reason provided" in AS._NO_REASON_SENTINELS
    assert None in AS._NO_REASON_SENTINELS and "" in AS._NO_REASON_SENTINELS
    assert "_NO_REASON_SENTINELS" in inspect.getsource(AS.dismiss_earned_credit)
    assert "_NO_REASON_SENTINELS" in inspect.getsource(AS.mark_recommendation_dismissed)
    # the predicate itself must be unchanged in behaviour
    assert AS.dismiss_earned_credit("No reason provided", 5) is False
    assert AS.dismiss_earned_credit("Carrier confirmed no losses", 5) is True


def test_the_fill_rate_delta_is_hidden_but_not_deleted():
    """Owner 2026-08-27: hide it, keep the backend. Same treatment as
    SHOW_COMPLETION_METRICS - the markup stays so it can be flipped back."""
    ui = (_BACKEND.parent / "frontend/src/components/form/AcordModal.jsx"
          ).read_text(encoding="utf-8", errors="replace")
    assert "const SHOW_FILL_RATE_DELTA = false;" in ui
    assert "SHOW_FILL_RATE_DELTA && fillDelta != null" in ui
    # the markup must NOT have been deleted
    assert "Quality Fill Rate: {fillBefore}% → {fillAfter}%" in ui


def test_a_machine_null_is_never_a_competing_value():
    """LIVE RUN 2026-08-27: the picker reported
    *"Policy Effective Date: documents disagree (09/17/2026, null)"* and the
    same for the expiration - TWO false hard stops capping a perfectly
    consistent package at 60, because `_normalize("null", "date")` returned the
    truthy string `'null'` and sailed through every `if not norm` guard.

    The module already knew the rule - its own scalar reader drops
    ""/"null"/"none" - it just never ran on the candidate-building paths.
    Principle 3: lack of evidence must never become a value.
    """
    import services.underwriting_consistency as UC
    for raw in ("null", "NULL", "None", "none", " null ", "", "   "):
        for kind in ("date", "identity", "currency", "integer"):
            assert UC._normalize(raw, kind, "effective_date") is None, (raw, kind)
    # ...and a real value that merely STARTS with one of those words survives.
    for raw in ("Nonesuch Holdings LLC", "Nonprofit Alliance Inc"):
        assert UC._normalize(raw, "identity", "applicant_name")
    assert UC._normalize("09/17/2026", "date", "effective_date")
    assert UC._normalize("$3,000,000", "currency", "umbrella_limit")


def test_the_session_score_delta_is_hidden_but_not_deleted():
    """Owner 2026-08-27, after asking whether the client had requested it.

    Checked against the SOURCES, not our notes: SQS_Scoring_Specification has no
    "this session" / "delta" / "started at" / "progress" requirement, and client
    section 7 - the score-PRESENTATION section - asks only for a qualitative
    status label, remediation progress shown separately, and the numeric SQS in
    the dedicated results experience. The panel was ours, and it had been
    structurally dead (delta permanently 0) until C5-A fixed `sqs_history`.

    Hidden, never deleted - and the BACKEND must stay, because the 5.12 audit
    snapshots and the narrative's model context both read it.
    """
    ui = (_BACKEND.parent / "frontend/src/components/form/AcordModal.jsx"
          ).read_text(encoding="utf-8", errors="replace")
    assert "const SHOW_SESSION_SCORE_DELTA = false;" in ui
    assert "SHOW_SESSION_SCORE_DELTA && packageSqs" in ui
    # markup preserved
    assert "pts this session" in ui and "Started at" in ui
    # backend untouched
    import services.sqs_service as S
    assert '"delta_this_session"' in _src("services/sqs_service.py")
    assert hasattr(S, "generate_sqs_narrative")
