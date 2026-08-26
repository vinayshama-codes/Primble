"""C5 - Source Lineage & E&O Audit Record (client section 5), 2026-08-26.

Covers the new lineage door (services/fact_lineage.py), the enriched audit
export, the 5.12 snapshot triggers, and anti-rot source checks pinning the
evidence-destruction fixes (envelope-preserving edits, previous_value capture,
the retention-job column fix, sqs_history persistence).
"""

import asyncio
import inspect
import json
from pathlib import Path

import pytest

from services import fact_lineage as FL
from services import audit_service as AS

_BACKEND = Path(__file__).resolve().parents[1]


# ── fixtures ─────────────────────────────────────────────────────────────────

def _doc(doc_id, filename, text="", facts=None, excluded=False):
    return {"doc_id": doc_id, "filename": filename, "text": text,
            "facts": facts or {}, "excluded": excluded}


PKG_TEXT = (
    "[Document page 1]\nACME ROOFING LLC\n123 Main Street\n"
    "[Document page 2]\nCOMMERCIAL GENERAL LIABILITY\n"
    "[Document page 14]\nEach Occurrence Limit $ 1,000,000\nAggregate $2,000,000\n"
)
COI_TEXT = (
    "CERTIFICATE OF LIABILITY INSURANCE\n"
    "EACH OCCURRENCE $ 1,000,000\nACME ROOFING LLC\n"
)


def _package_doc():
    return _doc("d1", "Package Policy.pdf", PKG_TEXT, facts={
        "gl_each_occurrence": {"value": "$ 1,000,000", "confidence": "ai_high",
                               "source": "ai"},
        "applicant_name": {"value": "ACME ROOFING LLC", "confidence": "ai_high",
                           "source": "ai"},
        "auto_vin_schedule": [{"vin": "4S4BRCGC9C3217772"}],
    })


def _coi_doc():
    return _doc("d2", "COI.pdf", COI_TEXT, facts={
        "gl_each_occurrence": {"value": "$1,000,000", "confidence": "ai_high",
                               "source": "ai"},
    })


# ── fact_lineage: document + page attribution (5.3-5.6) ──────────────────────

def test_page_located_under_its_marker():
    idx = FL.build_doc_index([_package_doc()])
    srcs = FL.scalar_sources("gl_each_occurrence", "$1,000,000", idx)
    assert len(srcs) == 1
    assert srcs[0]["filename"] == "Package Policy.pdf"
    assert srcs[0]["page"] == 14
    assert srcs[0]["method"] == "extracted"


def test_every_supporting_document_is_retained():
    # 5.4: both the policy and the COI support the limit - keep BOTH, never
    # just the first. The client's own example, verbatim:
    #   "Package Policy.pdf - Page 14 / COI.pdf - Page 1".
    # A markerless document is provably single-page while markers are enabled,
    # so the COI cites page 1.
    idx = FL.build_doc_index([_package_doc(), _coi_doc()])
    srcs = FL.scalar_sources("gl_each_occurrence", "$1,000,000", idx)
    assert [s["filename"] for s in srcs] == ["Package Policy.pdf", "COI.pdf"]
    assert srcs[0]["page"] == 14
    assert srcs[1]["page"] == 1


def test_markerless_text_declines_a_page_when_markers_are_off(monkeypatch):
    # With OCR_PAGE_MARKERS=0 a markerless text could be a 40-page document -
    # a false "page 1" is worse than no page.
    monkeypatch.setattr(FL, "_markers_enabled", lambda: False)
    idx = FL.build_doc_index([_coi_doc()])
    srcs = FL.scalar_sources("gl_each_occurrence", "$1,000,000", idx)
    assert len(srcs) == 1 and srcs[0]["page"] is None


def test_value_absent_everywhere_gets_no_source():
    idx = FL.build_doc_index([_package_doc(), _coi_doc()])
    assert FL.scalar_sources("umbrella_limit", "$5,000,000", idx) == []


def test_short_values_never_cite_evidence():
    # The _TEXT_VERIFY_MIN_CHARS floor: "34" appears in almost any document by
    # accident, and a false citation is worse than none.
    idx = FL.build_doc_index([_doc("d3", "app.pdf", "[Document page 1]\nAge 34\n")])
    assert FL.scalar_sources("num_employees", "34", idx) == []


def test_excluded_documents_do_not_witness():
    d = _package_doc()
    d["excluded"] = True
    idx = FL.build_doc_index([d])
    assert idx == []
    assert FL.scalar_sources("gl_each_occurrence", "$1,000,000", idx) == []


def test_text_only_support_without_per_doc_fact():
    # The doc's own extraction missed the value but its stored text literally
    # prints it: attributable at the text level, honest method label.
    d = _doc("d4", "dec.pdf", "[Document page 3]\nFEIN 84-2210987\n", facts={})
    idx = FL.build_doc_index([d])
    srcs = FL.scalar_sources("fein", "84-2210987", idx)
    assert len(srcs) == 1 and srcs[0]["method"] == "text" and srcs[0]["page"] == 3


def test_agreement_survives_formatting_differences():
    # The doc's own printing has spaces; the merged fact does not. The
    # comparison door (fact_comparison.values_agree) decides sameness - never
    # a local string equality.
    idx = FL.build_doc_index([_package_doc()])
    srcs = FL.scalar_sources("gl_each_occurrence", "$1,000,000", idx)
    assert srcs and srcs[0]["method"] == "extracted"


def test_list_fact_names_contributing_documents():
    # 5.6: schedules/structured facts get document attribution by contribution.
    idx = FL.build_doc_index([_package_doc(), _coi_doc()])
    srcs = FL.list_sources("auto_vin_schedule", [{"vin": "x"}], idx)
    assert len(srcs) == 1
    assert srcs[0]["filename"] == "Package Policy.pdf"
    assert srcs[0]["rows"] == 1


def test_dispatch_shapes():
    idx = FL.build_doc_index([_package_doc()])
    assert FL.sources_for_fact("anything", None, idx) == []
    assert FL.sources_for_fact("anything", {"value": None}, idx) == []
    assert FL.sources_for_fact("anything", True, idx) == []
    assert FL.sources_for_fact(
        "auto_vin_schedule", {"value": [{"vin": "x"}]}, idx)[0]["rows"] == 1


def test_dict_fact_names_contributing_documents():
    # Live run 2026-08-26: risk_transfer ([structured value]) printed
    # 'Source: unspecified' with no evidence. A structured dict now gets the
    # same contribution attribution a schedule does.
    d = _doc("d6", "app.pdf", "", facts={
        "risk_transfer": {"requires_certificates": "yes"},
    })
    idx = FL.build_doc_index([d])
    srcs = FL.sources_for_fact("risk_transfer", {"a": 1}, idx)
    assert len(srcs) == 1 and srcs[0]["filename"] == "app.pdf"
    # A doc whose own copy is empty contributes nothing.
    assert FL.sources_for_fact("risk_transfer", {"a": 1},
                               FL.build_doc_index([_coi_doc()])) == []


def test_format_source_lines():
    assert FL.format_source({"filename": "Package Policy.pdf", "page": 14}) == \
        "Package Policy.pdf - page 14"
    assert FL.format_source({"filename": "COI.pdf", "page": None}) == "COI.pdf"
    assert FL.format_source({"filename": "app.pdf", "page": None, "rows": 3}) == \
        "app.pdf (3 row(s))"


def test_preamble_before_first_marker_claims_no_page():
    d = _doc("d5", "x.pdf",
             "SCAN COVER SHEET UNIQUEHEADER77\n[Document page 1]\nbody\n")
    idx = FL.build_doc_index([d])
    srcs = FL.scalar_sources("some_fact", "UNIQUEHEADER77", idx)
    assert len(srcs) == 1 and srcs[0]["page"] is None


# ── _flatten_fact: states, derivation, scope reach the export ────────────────

def test_conflicting_state_reaches_the_export_row():
    facts = {
        "total_revenue": {"value": "$2,400,000", "confidence": "ai_high",
                          "source": "ai"},
        "_uw_conflict_keys": ["total_revenue"],
    }
    row = AS._flatten_fact("total_revenue", facts["total_revenue"], facts)
    assert row is not None
    assert row["value_state"] == "conflicting"


def test_a_resolved_conflict_reads_confirmed_not_conflicting():
    # C5-D live finding (2026-08-26): after the producer picked $3,000,000 in
    # Data Consistency, the record printed "UNRESOLVED (conflicting /
    # user_confirmed)" one line under the resolution that settled it - the
    # superset conflict key records that the DOCUMENTS still disagree, which
    # stays true forever. A human resolution settles the FACT.
    facts = {
        "umbrella_limit": {"value": "$3,000,000", "confidence": "client_arq",
                           "source": "user_confirmed"},
        "_uw_conflict_keys": ["umbrella_limit"],
    }
    row = AS._flatten_fact("umbrella_limit", facts["umbrella_limit"], facts)
    assert row["value_state"] == "present"
    assert row["evidence_state"] == "user_confirmed"
    assert row["display_state"] == "CONFIRMED"
    # An UNRESOLVED conflict still reads conflicting - the fix must not widen.
    facts2 = {
        "umbrella_limit": {"value": "$3,000,000", "confidence": "ai_high",
                           "source": "ai"},
        "_uw_conflict_keys": ["umbrella_limit"],
    }
    row2 = AS._flatten_fact("umbrella_limit", facts2["umbrella_limit"], facts2)
    assert row2["value_state"] == "conflicting"


def test_derivation_and_scope_ride_the_row():
    facts = {
        "years_in_business": {
            "value": "12", "confidence": "deterministic", "source": "derived",
            "derivation": {"rule": "years_in_business_from_start_date",
                           "inputs": ["business_start_date"]},
        },
        "_scoped": {"years_in_business": [
            {"value": "12", "scope": {"line": "general_liability",
                                      "policy_number": "BOP123"}},
        ]},
    }
    row = AS._flatten_fact("years_in_business", facts["years_in_business"], facts)
    assert row["derivation"]["rule"] == "years_in_business_from_start_date"
    assert row["scope"][0]["policy_number"] == "BOP123"


# ── the export itself (async, no DB) ─────────────────────────────────────────

def _patch_async(monkeypatch, module, name, value):
    async def _f(*a, **k):
        return value
    monkeypatch.setattr(module, name, _f)


def test_export_reads_docs_and_excludes_machinery(monkeypatch):
    session = {
        "user_id": "u1",
        "created_at": "2026-08-26T00:00:00+00:00",
        "docs": [_package_doc(), _coi_doc()],
        "facts": {
            "gl_each_occurrence": {"value": "$1,000,000",
                                   "confidence": "ai_high", "source": "ai"},
            "_scoped": {"gl_each_occurrence": []},
            "_rejected_facts": {"expiration_date": "term length unknown"},
            "dec_page_entries": [{"label": "x", "value": "y"}],
            # Bare booleans are pipeline markers (live run 2026-08-26:
            # renewal_dates_routed / dec_states_payroll_basis rendered as
            # 'True / Source: unspecified') - they must never render.
            "renewal_dates_routed": True,
        },
        "generated_forms": {"ACORD_125": {}},
    }
    import repositories.session_repository as SR
    import services.arq_receipt_service as RS
    _patch_async(monkeypatch, SR, "get_processing_session", session)
    _patch_async(monkeypatch, RS, "get_receipts_for_session", [])
    for name, val in [
        ("get_marketing_reason", None), ("get_dismissed_recommendations", []),
        ("get_producer_answers", []), ("get_issue_statuses", []),
        ("get_download_audit_log", []), ("get_field_change_log", []),
        ("get_underwriting_confirmations", []),
        ("get_package_download_log", []), ("get_audit_events", []),
    ]:
        _patch_async(monkeypatch, AS, name, val)

    export = asyncio.run(AS.get_audit_trail_export("s1"))

    # 5.2: documents come from session["docs"] - the old read of the never-
    # persisted `doc_summary` key printed "(none recorded)" on every export.
    assert [dd["filename"] for dd in export["documents"]] == \
        ["Package Policy.pdf", "COI.pdf"]
    assert export["documents"][0]["uploaded_at"]  # session fallback at minimum

    # 5.3-5.5: the fact row carries document + page evidence.
    facts_by_key = {r["fact"]: r for r in export["inputs"]}
    srcs = facts_by_key["gl_each_occurrence"]["sources"]
    assert {s["filename"] for s in srcs} == {"Package Policy.pdf", "COI.pdf"}

    # Machinery never renders as captured inputs.
    assert "_scoped" not in facts_by_key
    assert "_rejected_facts" not in facts_by_key
    assert "dec_page_entries" not in facts_by_key
    assert "renewal_dates_routed" not in facts_by_key

    # "What remained unresolved": refusals surface with their reason.
    assert export["rejected_facts"] == \
        [{"fact": "expiration_date", "reason": "term length unknown"}]

    # The new payload keys exist even when empty (renderer contract).
    for key in ("package_downloads", "conflict_resolutions", "client_receipts",
                "audit_events", "sqs_snapshots", "answered_recommendations"):
        assert key in export


def test_export_survives_a_retention_tombstone(monkeypatch):
    session = {"user_id": "u1",
               "facts": {"purged": True, "purged_at": "x", "reason": "retention_policy",
                         "tier": "free"},
               "docs": [], "generated_forms": {}}
    import repositories.session_repository as SR
    import services.arq_receipt_service as RS
    _patch_async(monkeypatch, SR, "get_processing_session", session)
    _patch_async(monkeypatch, RS, "get_receipts_for_session", [])
    for name in ("get_marketing_reason", "get_dismissed_recommendations",
                 "get_producer_answers", "get_issue_statuses",
                 "get_download_audit_log", "get_field_change_log",
                 "get_underwriting_confirmations", "get_package_download_log",
                 "get_audit_events"):
        _patch_async(monkeypatch, AS, name, [] if name != "get_marketing_reason" else None)
    export = asyncio.run(AS.get_audit_trail_export("s1"))
    # The tombstone's own keys must not render as captured fact rows.
    assert export["inputs"] == []


# ── 5.12 snapshot triggers ───────────────────────────────────────────────────

def _pkg(raw=80, displayed=75, pillars=None, ceiling=None, reason=None):
    return {"raw_sqs_score": raw, "package_sqs_score": displayed,
            "pillars": pillars or {"structural_completeness": 90,
                                   "exposure_consistency": 70},
            "cap_applied": ceiling, "cap_reason": reason,
            "tier": "B", "calculation_stage": "form_generated",
            "weights_version": "v", "score_trace": {"arithmetic": {}}}


def test_every_512_trigger_fires_and_noise_does_not():
    base = AS._snapshot_signature(_pkg())
    assert not AS._snapshots_differ(base, AS._snapshot_signature(_pkg()))
    assert AS._snapshots_differ(base, AS._snapshot_signature(_pkg(raw=81)))
    assert AS._snapshots_differ(base, AS._snapshot_signature(_pkg(displayed=76)))
    assert AS._snapshots_differ(base, AS._snapshot_signature(
        _pkg(pillars={"structural_completeness": 91, "exposure_consistency": 70})))
    assert AS._snapshots_differ(base, AS._snapshot_signature(
        _pkg(ceiling=60, reason="invalid policy period")))
    withc = AS._snapshot_signature(_pkg(ceiling=60, reason="a"))
    assert AS._snapshots_differ(withc, AS._snapshot_signature(_pkg(ceiling=60, reason="b")))
    assert AS._snapshots_differ(withc, AS._snapshot_signature(_pkg()))  # ceiling removed
    # The appended remediation sentence is presentation, not substance - the
    # live run showed it fabricating a "reason changed" snapshot.
    a = AS._snapshot_signature(_pkg(
        ceiling=85, reason="Physical damage deductibles not specified."))
    b = AS._snapshot_signature(_pkg(
        ceiling=85, reason="Physical damage deductibles not specified. "
                           "Fix: Review and correct this before proceeding."))
    assert not AS._snapshots_differ(a, b)


def test_snapshot_skips_unchanged_but_never_skips_a_download(monkeypatch):
    stored = []

    async def _log(session_id, user_id, event_type, event_data=None):
        stored.append({"event_type": event_type, "event_data": event_data})
        return True

    async def _events(session_id, event_type=None):
        return [e for e in stored if e["event_type"] == (event_type or e["event_type"])]

    monkeypatch.setattr(AS, "log_audit_event", _log)
    monkeypatch.setattr(AS, "get_audit_events", _events)

    assert asyncio.run(AS.log_sqs_snapshot_if_changed("s", "u", _pkg(), "form_generated"))
    # Same signature again: no new snapshot (5.12 "not after every invisible
    # calculation").
    assert not asyncio.run(AS.log_sqs_snapshot_if_changed("s", "u", _pkg(), "form_edited"))
    # A download always snapshots.
    assert asyncio.run(AS.log_sqs_snapshot_if_changed("s", "u", _pkg(), "package_downloaded"))
    # A moved score snapshots again.
    assert asyncio.run(AS.log_sqs_snapshot_if_changed("s", "u", _pkg(displayed=80), "form_edited"))
    assert len(stored) == 3
    # D33: the snapshot body is the scorer's own trace, stored not recomputed.
    assert "score_trace" in stored[0]["event_data"]


def test_empty_package_never_snapshots():
    assert not asyncio.run(AS.log_sqs_snapshot_if_changed("s", "u", None, "form_edited"))
    assert not asyncio.run(AS.log_sqs_snapshot_if_changed("s", "u", {}, "package_downloaded"))


# ── anti-rot: the evidence-destruction fixes stay fixed ──────────────────────

def _src(rel):
    return (_BACKEND / rel).read_text(encoding="utf-8", errors="replace")


def test_update_pdf_writes_a_provenance_envelope_not_a_bare_string():
    src = _src("routes/form_routes.py")
    assert '"source": "producer"' in src
    # The old destructive write must not come back.
    assert "updated_facts[fact_key] = val_str if val_str" not in src


def test_previous_value_is_never_hardcoded_none_again():
    src = _src("routes/audit_routes.py")
    assert "previous_value=None," not in src
    assert "_prev_fact_val" in src and "_pre_facts" in src


def test_retention_job_targets_the_real_column():
    src = _src("services/scheduler_service.py")
    assert "jsonb_set(ps.data, '{facts}'" in src
    assert "SET    facts =" not in src


def test_six_month_retention_ruling_is_implemented():
    # OWNER 2026-08-26 (Q18): the E&O record is kept for 6 months. Three
    # concrete consequences, each pinned:
    src = _src("services/scheduler_service.py")
    # 1. audit_events is swept on its own knob, floored at 180 days.
    assert "DELETE FROM audit_events" in src
    assert 'max(int(_os.getenv("AUDIT_EVENTS_RETENTION_DAYS", "180")), 180)' in src
    # 2. No tier's facts purge undercuts the 6-month window (free was 30).
    assert '"free":       180' in src
    # 3. The operational audit tables keep a floor at or above 6 months.
    assert '_os.getenv("AUDIT_LOG_RETENTION_DAYS", "365")' in src


def test_sqs_history_is_passed_at_every_package_persist():
    # The scorer builds the history; the repository's append-only merge only
    # engages when the key is passed EXPLICITLY. Each recompute path must pass
    # it or delta_this_session regresses to permanent 0.
    for rel in ("routes/form_routes.py", "worker.py", "services/arq_service.py"):
        path = (_BACKEND / rel).resolve()
        assert '"sqs_history"' in path.read_text(encoding="utf-8", errors="replace"), rel


def test_answered_at_column_and_writer_exist():
    from models.schemas import SQS_RECOMMENDATION_AUDIT_STATEMENTS
    joined = " ".join(SQS_RECOMMENDATION_AUDIT_STATEMENTS)
    assert "answered_at" in joined
    assert "answered_at" in inspect.getsource(AS.mark_recommendation_answer_recorded)


def test_audit_events_table_is_registered_and_append_only():
    from models.schemas import AUDIT_EVENT_STATEMENTS
    joined = " ".join(AUDIT_EVENT_STATEMENTS)
    assert "CREATE TABLE IF NOT EXISTS audit_events" in joined
    assert "audit_events" in inspect.getsource(AS.init_audit_tables) or \
        "AUDIT_EVENT_STATEMENTS" in inspect.getsource(AS.init_audit_tables)
    # Append-only: no UPDATE or DELETE against audit_events anywhere in the
    # audit service.
    svc = _src("services/audit_service.py")
    assert "UPDATE audit_events" not in svc
    assert "DELETE FROM audit_events" not in svc


def test_draft_downloads_keep_the_open_items_list():
    src = _src("routes/download_routes.py")
    assert src.count('"open_recommendations": unresolved_recs') == 2


def test_client_answer_apply_logs_field_changes():
    src = _src("services/arq_service.py")
    assert 'source="client_arq"' in src
    assert "client_answers_applied" in src


def test_reopen_preserves_prior_state_in_the_event_log():
    src = _src("routes/audit_routes.py")
    assert "recommendation_reopened" in src
    assert "prior_action_at" in src


# ── 5.7: deriving writers stamp rule + inputs on the envelope ────────────────

def test_years_in_business_carries_its_derivation():
    from services.extraction_service import _derive_years_in_business
    mf = {"business_start_date": {"value": "01/15/2010", "confidence": "ai_high",
                                  "source": "ai"}}
    _derive_years_in_business(mf)
    env = mf.get("years_in_business")
    assert isinstance(env, dict)
    assert env["source"] == "derived"
    assert env["derivation"]["rule"] == "years_since_business_start_date"
    assert env["derivation"]["inputs"] == ["business_start_date"]


def test_renewal_routed_proposed_date_carries_its_derivation():
    from services.extraction_service import _route_renewal_dates
    mf = {"is_renewal": {"value": "yes", "confidence": "ai_high", "source": "ai"},
          "effective_date": {"value": "07/15/2024", "confidence": "ai_high",
                             "source": "ai"},
          "expiration_date": {"value": "07/15/2025", "confidence": "ai_high",
                              "source": "ai"}}
    _route_renewal_dates(mf)
    env = mf.get("effective_date")
    assert isinstance(env, dict) and env["source"] == "derived"
    # The client's own 5.7 worked example: proposed effective date, derived
    # from the prior expiration by the renewal routing rule.
    assert env["derivation"]["rule"] == "renewal_routing_prior_expiration"
    assert "prior_expiration_date" in env["derivation"]["inputs"]
