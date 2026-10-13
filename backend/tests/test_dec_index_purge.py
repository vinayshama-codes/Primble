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
        # extraction_pipeline (5 Oct 2026, G1 skeptic). `_finalize_pipeline`
        # STORES the declarations' auto-liability reading
        # (`_auto_liability_dec_reading`) while the entries exist - the merge,
        # and every re-run, which re-merges the per-document copies the purge
        # never touches. It is the reason the split door reads the same answer
        # after the purge; with no entries it writes nothing.
        "extraction_pipeline.py",
        # fact_comparison `_issue_date_of` (24 Sep 2026, client item 9). Reads a
        # declarations page's own "Date of Issue" entry so a dec RE-ISSUED
        # after a dated change is not taken as the change's older side. It runs
        # in the merge and in every re-run, i.e. also after generation - and it
        # reads the PER-DOCUMENT `doc["facts"]["dec_page_entries"]`, which the
        # purge never deletes (only the merged session fact goes). Same answer
        # both sides of the purge; with no entry it returns None and the
        # inception date stands - exactly the pre-change behaviour.
        "fact_comparison.py",
        # form_addition (UX-05, 2026-09-08). The only mention there is the module
        # docstring, and it is there because this module is the FIRST thing that
        # deliberately generates a form AFTER the purge has run: the producer
        # adds a missing ACORD form from a validation finding.
        #
        # DECIDED, not waved through. It reads no entries itself - it calls
        # `compute_form_gaps` / `combined_gap_fill`, and pdf_service's Stage A
        # simply finds no index, so every field walks the raw document. That IS
        # the pre-2026-08-13 pipeline. Measured blast radius of running without
        # the index, across all 17 schemas: 9 of 5,852 fields degrade to a blank
        # or a shorter printing of the same policy number, and no field ever gets
        # a wrong value (see form_routes' own purge comment).
        #
        # So an added form is very slightly thinner than its siblings and never
        # wrong. Rebuilding the index would mean re-running LLM call 1 over the
        # whole package to add one form - the wrong trade, and it would undo the
        # PII minimisation the purge exists for.
        "form_addition.py",
        # needs_attention (30 Sep 2026, Orbin items 9 / 19). DOES run after
        # generation - the side panel and the pre-download review read it. It
        # reads the entries for ONE thing: the WORDING of an "AI held back"
        # reason ("Your documents print it as "AGENT PHONE""). Status, counts,
        # values and scores never depend on it. After the purge the entry read
        # finds nothing and the reason falls back to the fact match or the
        # plain sentence - thinner wording, never a different row.
        "needs_attention.py",
        # underwriting_consistency (14 Sep 2026, Orbin). DOES run after
        # generation - the Data Consistency card is rebuilt on every pipeline
        # re-run. `_verified_contracts` reads the entries' policy numbers so a
        # carrier FORM reference (`CU7001A 11-15`) that no verified contract
        # names is not offered as a policy number. Purge-safe on both counts
        # the fact_equivalence entry above records: it also reads the
        # PER-DOCUMENT copies, which the purge never touches, and with no index
        # it has no opinion - the card behaves exactly as before the filter.
        "underwriting_consistency.py",
        # session_documents (Choice Electric #25, 7 Oct 2026). DOES run after
        # generation - documents added to a package, or a document excluded /
        # reclassified once forms exist. DECIDED: it never keeps the index. The
        # re-merge rebuilds it from the PER-DOCUMENT copies the purge never
        # touches; the door compares what the engine prints with the index the
        # forms were stamped with (rebuilt the same way, through the merge, for
        # the documents before the change) against the index after it - so a
        # box moves exactly as a regeneration would move it - and then deletes
        # the merged index again in the same write when the purge is on.
        "session_documents.py",
        # umbrella_layers (Choice Electric #4, 7 Oct 2026 - one ACORD 131 per
        # umbrella-family layer). DOES run after generation (every restamp of a
        # layer's copy reads its view). DECIDED: it never NEEDS the index - it
        # only FILTERS the entries out of a layer's view (another layer's
        # contract stays off this copy). After the purge there is nothing to
        # filter and the view is the same minus an absent key: purge-safe.
        "umbrella_layers.py",
        # policy_lines (Choice Electric #9, 7 Oct 2026 - "Policies in this
        # submission"). DOES run after generation: a producer corrects or adds a
        # policy once forms exist. It reads the entries for ONE thing - the
        # policy-number door (`normalization.is_not_a_policy_number`: a number the
        # declarations label as a form or account number is refused). After the
        # purge it reads the PER-DOCUMENT copies, which the purge never touches:
        # the same answer both sides. Purge-safe.
        "policy_lines.py",
        # wc_premiums (Choice Electric #7, 7 Oct 2026 - ACORD 130's premiums).
        # DECIDED: it reads the index only at MERGE (`derive_wc_premiums`) and
        # stores what the stamper needs in the private `_wc_premiums` fact, which
        # the purge never deletes - exactly the `dec_states_payroll_basis`
        # pattern. Its other read is a document's OWN per-document entries (which
        # line a document is about). Purge-safe.
        "wc_premiums.py",
        # form_dry_run (Choice Electric #27, 7 Oct 2026 - "Before you generate").
        # DECIDED: runs BEFORE generation only - `pre_form_dry_run` returns None
        # and its route refuses once `generated_forms` exist (the download review
        # is the live list then). Its read (`documents_name_it`: a verified
        # declarations entry names a box's fact, so gap fill can still fill it)
        # therefore always sees the index, which is purged only AFTER
        # generation. Purge-safe.
        "form_dry_run.py",
        # ai_role_guards (round 5, 7 Oct 2026). Runs inside `map_facts_to_form`,
        # i.e. during generation, and after it only where a form is stamped
        # again (form_addition, session_documents' re-stamp). DECIDED: the index
        # is never the reason to REFUSE. The count rule's index is a WITNESS that
        # keeps a count, so with no index the rule stands down (no opinion); the
        # premium rule uses an entry only to set an occurrence aside as another
        # line's, so with no index an occurrence stays in play and the box KEEPS
        # its value. Purge-safe: fewer refusals after the purge, never more -
        # pinned by test_round5_ai_role_guards_7oct.py::TestPurgedIndex.
        "ai_role_guards.py",
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
