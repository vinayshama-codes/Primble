"""The declarations index is deleted once forms exist.

Owner's product rule, 2026-08-13: "once any form is generated, user cannot go
back in that same package to generate another form, they have to restart new
package." That removes the only reason the index was being kept - re-generating
a different ACORD form off the same extraction - and it is PII (names, addresses,
identifiers), ~33 KB a session, which on the professional tier the nightly facts
sweep skips entirely.

These tests pin the CONTRACT rather than the plumbing: every consumer runs at or
before generation, nothing after generation reads it, and the purge degrades to
the pre-Stage-A pipeline rather than breaking if a second generation ever happens.
"""
import ast
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

import services.pdf_service as ps                                 # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]
ROUTES = (BACKEND / "routes" / "form_routes.py").read_text(encoding="utf-8")


def test_the_purge_uses_the_atomic_retraction_path():
    """`delete_facts` exists precisely because the facts merge is ADDITIVE - a
    key merely absent from an update is preserved. Read-modify-write from the
    stale session dict this request opened with would clobber anything the
    extraction pipeline wrote in between."""
    assert 'delete_facts=["dec_page_entries"]' in ROUTES


def test_the_purge_only_runs_when_a_form_was_actually_generated():
    assert "_PURGE_DEC_INDEX_AFTER_GENERATION and results" in ROUTES


def test_the_purge_is_not_on_the_lite_generation_path():
    """`lite_generate_internal` also generates forms - silently, for scoring and
    ARQ - and runs BEFORE the producer chooses anything. Purging there would
    leave the real generation with no index at all.

    Checked structurally: the purge call must sit inside `select_forms_bulk`.
    """
    tree = ast.parse(ROUTES)
    owners = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            body = ast.get_source_segment(ROUTES, node) or ""
            if "delete_facts=[\"dec_page_entries\"]" in body:
                owners.append(node.name)
    assert owners == ["select_forms_bulk"], owners


def test_the_kill_switch_exists_and_defaults_on():
    """The DEFAULT is on, which is what "defaults on" means.

    CORRECTED 2026-08-14: this used to assert the module's runtime value, so it
    failed whenever a developer legitimately set PURGE_DEC_INDEX_AFTER_GENERATION=0
    - which is exactly what you do to inspect the index on a live run, and is
    the documented way to do it. A test that breaks when the kill switch is
    used is testing the developer's .env, not the code.
    """
    assert 'os.getenv(\n        "PURGE_DEC_INDEX_AFTER_GENERATION", "1")' in ROUTES \
        or '"PURGE_DEC_INDEX_AFTER_GENERATION", "1"' in ROUTES, (
        "the purge no longer defaults to ON")
    assert "PURGE_DEC_INDEX_AFTER_GENERATION" in ROUTES


# ── The contract that makes deleting safe ────────────────────────────────────

def test_every_consumer_of_the_index_runs_at_or_before_generation():
    """ANTI-ROT. The purge is only safe while nothing downstream reads the
    entries. If someone adds a post-generation consumer, this fails and they
    have to decide deliberately rather than discover it in production.

    Consumers are located by grep across the service layer, so a NEW one shows
    up here whether or not its author knew about this test.
    """
    hits = []
    for path in sorted((BACKEND / "services").glob("*.py")) + \
            sorted((BACKEND / "routes").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            if "dec_page_entries" in line and not line.strip().startswith("#"):
                hits.append(f"{path.name}:{i}")
    # The known set, each verified to run at or before generation. Adding a line
    # here is a decision: state where it runs and why the purge is still safe.
    known_files = {
        "extraction_service.py",   # the schema, the merge, the verification
        "pdf_service.py",          # Stage A index, the duplicate guard, exclusion,
                                   # and the fabricated-interest borrow pool (runs
                                   # during generation, before the purge)
        "form_routes.py",          # the coverage report and this purge
        "text_selection.py",       # the rescue net, during gap fill
        # fact_equivalence.PackageContext (2026-08-17). THIS ONE DOES RUN AFTER
        # GENERATION - every producer answer re-runs the pipeline - so it was
        # measured rather than waved through:
        #   * `coverage_lines` SURVIVES the purge and carries the policy
        #     numbers. Verified on a real session: stripping dec_page_entries
        #     left contracts={BBC7263-26, 6E7-40-02---26, 6J7-40-02---26,
        #     6C7-40-02---26} and is_multi_contract still True.
        #   * PER-DOCUMENT `dec_page_entries` are untouched by the purge, which
        #     only deletes the MERGED session fact. Second, independent source.
        # So the multi-contract signal survives and no extra data is retained.
        # Degrades safely in any case: no evidence means no opinion, which is
        # exactly today's behaviour.
        # NOTED, out of scope: the purge is therefore less complete than its
        # comment implies - the per-document copies remain. That is a
        # data-minimisation question for the owner, not a correctness one.
        "fact_equivalence.py",
        "sqs_service.py",          # GL exposure warning: reads entries live, and
                                   # the purge-surviving dec_states_payroll_basis
                                   # fact on post-generation recalcs - same answer
                                   # both sides of the purge by construction
        # audit_service (C5, 2026-08-26). Runs AFTER generation (the E&O export
        # is on-demand) but is an EXCLUSION, not a consumer: the export's
        # captured-inputs loop SKIPS the `dec_page_entries` key so the internal
        # index never renders as a junk "[N row(s) captured] / Source:
        # unspecified" row. When the purge has already deleted the key the skip
        # is a no-op. Nothing here reads the entries' content, so the purge
        # stays safe.
        "audit_service.py",
        # coverage_evidence (V1 H1, 2026-08-26). DOES run after generation
        # (every recalculation re-scores the package) and is therefore built
        # the same way sqs_service's GL exposure warning is: each of its two
        # entry reads is the LAST fallback behind a fact `merge_facts` derives
        # WHILE THE ENTRIES STILL EXIST (`_derive_from_dec_entries_h1`:
        # auto_radius_of_operation, wc_payroll_period, wc_xmod_applicability).
        # After the purge the derived fact answers first and the entry read
        # finds nothing - same answer both sides of the purge by construction,
        # pinned by test_h1_coverage_gap_closure.py::
        # test_dec_entry_signals_survive_the_purge_through_derived_facts.
        "coverage_evidence.py",
    }
    unexpected = [h for h in hits if h.split(":")[0] not in known_files]
    assert not unexpected, (
        f"new dec_page_entries consumer(s) {unexpected} - if any of them runs "
        "AFTER form generation, the purge in select_forms_bulk deletes data they "
        "need. Decide, then update this list.")


def test_a_missing_index_simply_turns_stage_a_off():
    """The degradation path, executed rather than asserted about. A session whose
    index has been purged must fall back to the pre-2026-08-13 pipeline - every
    field walking the raw document - not raise, and not silently blank a form."""
    assert ps._render_dec_index(None) == ""
    assert ps._dec_index_chunks(None, 100_000) == []
    # And the guard that consults the index abstains rather than erroring.
    assert ps._second_claim_on_a_single_printed_value(
        "Producer_FaxNumber_A",
        {"Producer_ContactPerson_PhoneNumber_A": "303-996-7800",
         "Producer_FaxNumber_A": "303-996-7800"},
        {"Producer_FaxNumber_A"}, None) is None


def test_the_coverage_summary_survives_the_purge():
    """`dec_index_coverage` is written BEFORE the purge and is not a fact, so it
    is untouched by `delete_facts`. It is what still answers "what did the
    declarations print that never reached a form" after the entries are gone."""
    order_report = ROUTES.index('"dec_index_coverage": _dec_cov')
    order_purge = ROUTES.index('delete_facts=["dec_page_entries"]')
    assert order_report < order_purge, (
        "the purge must not run before the coverage report is persisted")


@pytest.mark.parametrize("entries", [None, [], "junk"])
def test_the_report_is_honest_about_an_absent_index(entries):
    report = ps.dec_index_coverage(entries, ["anything"])
    assert report["recorded"] == 0 and report["unused"] == []
