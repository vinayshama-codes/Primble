"""
Regression tests for Submission Integrity Validation (Beta Report §4.1).

Locks in:
  • Multi-insured detection by applicant-name clusters and by distinct FEINs
    (the Beta Test 1 three-insured package must PAUSE).
  • Normalization-aware name clustering: "ORBIN CONTRACTING LLC" vs
    "Orbin Contracting, LLC" is the SAME insured (no false pause).
  • The orphan-doc strong-divergence escalation: a document whose name+FEIN
    failed to extract, but which carries its OWN different mailing address and
    carrier/policy, escalates to LOW (the Orbin-CO-dec + unrelated-125 case)
    WITHOUT flagging a genuine supporting doc that shares the insured's
    address/carrier.

Pure assessor — no DB, no network.

Run from backend/:
    python tests/test_submission_integrity.py
or:
    python -m pytest tests/test_submission_integrity.py -v
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.submission_integrity import (  # noqa: E402
    assess_submission_integrity, cluster_documents,
    STATUS_HIGH, STATUS_MEDIUM, STATUS_LOW,
)


def _doc(doc_id, name=None, fein=None, mailing="", policy="", carrier="",
         entity="", doc_type="dec_page"):
    return {
        "doc_id": doc_id,
        "filename": f"{doc_id}.pdf",
        "doc_type": doc_type,
        "facts": {
            "applicant_name": name,
            "fein": fein,
            "entity_type": entity,
            "mailing_address": mailing,
            "policy_number": policy,
            "carrier_name": carrier,
        },
    }


# ── The four originally-documented cases (must remain stable) ─────────────────

def test_three_insured_beta_package_pauses():
    v = assess_submission_integrity([
        _doc("d1", "Womens Bar Association", "11-1111111"),
        _doc("d2", "Wake County", "22-2222222"),
        _doc("d3", "Company ABC", "33-3333333"),
    ])
    assert v["status"] == STATUS_LOW
    assert v["review_required"] is True
    assert len(v["detected_entities"]) >= 2


def test_orbin_llc_punctuation_variants_do_not_pause():
    # "ORBIN CONTRACTING LLC" vs "Orbin Contracting, LLC" — same insured, same FEIN.
    v = assess_submission_integrity([
        _doc("d1", "ORBIN CONTRACTING LLC", "47-1823650"),
        _doc("d2", "Orbin Contracting, LLC", "47-1823650"),
    ])
    assert v["review_required"] is False
    assert v["status"] in (STATUS_HIGH, STATUS_MEDIUM)


def test_distinct_feins_pause():
    v = assess_submission_integrity([
        _doc("d1", "Acme", "11-1111111"),
        _doc("d2", "Acme", "99-9999999"),
    ])
    assert v["status"] == STATUS_LOW
    assert v["review_required"] is True


def test_single_document_never_pauses():
    v = assess_submission_integrity([_doc("d1", "Acme", "11-1111111")])
    assert v["review_required"] is False
    assert v["status"] == STATUS_HIGH


def test_no_documents_does_not_crash():
    v = assess_submission_integrity([])
    assert v["review_required"] is False


# ── Both names present → multi-insured (the happy-path detection) ─────────────

def test_two_distinct_named_insureds_pause():
    v = assess_submission_integrity([
        _doc("d1", "ORBIN CONTRACTING LLC", "47-1823650",
             mailing="4800 Dahlia St, Denver, CO 80216", carrier="EMC"),
        _doc("d2", "Gupta Enterprises Pvt Ltd", None,
             mailing="Plot 45, Udyog Vihar, Delhi", carrier="HDFC ERGO"),
    ])
    assert v["status"] == STATUS_LOW
    assert v["review_required"] is True


# ── Orphan-doc strong-divergence escalation (the fix) ────────────────────────

def test_orphan_doc_with_divergent_address_and_carrier_pauses():
    # Doc 2's name AND fein failed to extract, but it brings a different mailing
    # address + carrier + policy → likely a separate submission → must pause.
    v = assess_submission_integrity([
        _doc("d1", "ORBIN CONTRACTING LLC", "47-1823650",
             mailing="4800 Dahlia St, Denver, CO 80216",
             policy="CPP-2025-00447", carrier="Employers Mutual Casualty"),
        _doc("d2", None, None,
             mailing="Plot 45, Udyog Vihar, Delhi 110020",
             policy="POL-11223344-26", carrier="HDFC ERGO General Insurance"),
    ])
    assert v["status"] == STATUS_LOW
    assert v["review_required"] is True
    assert v["signals"]["has_unidentified_doc"] is True


def test_orphan_supporting_doc_sharing_identity_does_not_pause():
    # A loss run with no name/FEIN but the SAME address + carrier is a genuine
    # supporting doc — must NOT pause.
    v = assess_submission_integrity([
        _doc("d1", "ORBIN CONTRACTING LLC", "47-1823650",
             mailing="4800 Dahlia St, Denver, CO 80216",
             carrier="Employers Mutual Casualty"),
        _doc("d2", None, None,
             mailing="4800 Dahlia St, Denver, CO 80216",
             carrier="Employers Mutual Casualty", doc_type="loss_run"),
    ])
    assert v["review_required"] is False


def test_single_insured_renewal_with_prior_carrier_no_hard_pause():
    # Same insured (name + FEIN match) across dec + renewal app that references a
    # different (prior) carrier/policy → soft review at most, never a hard pause.
    v = assess_submission_integrity([
        _doc("d1", "ORBIN CONTRACTING LLC", "47-1823650",
             mailing="4800 Dahlia St, Denver, CO 80216",
             policy="CPP-2025-00447", carrier="Employers Mutual"),
        _doc("d2", "Orbin Contracting, LLC", "47-1823650",
             mailing="4800 Dahlia Street, Denver, CO 80216",
             policy="NEW-2026-1", carrier="Travelers"),
    ])
    assert v["review_required"] is False
    assert v["status"] in (STATUS_HIGH, STATUS_MEDIUM)


# ── Override audit record shape ──────────────────────────────────────────────

def test_verdict_exposes_signals_and_documents():
    v = assess_submission_integrity([
        _doc("d1", "Acme Co", "11-1111111", mailing="1 Main St, Austin, TX 78701"),
        _doc("d2", "Acme Co", "11-1111111", mailing="1 Main St, Austin, TX 78701"),
    ])
    assert "signals" in v and "documents" in v
    assert v["signals"]["document_count"] == 2
    # FEIN is masked to last 4 only (PII).
    for d in v["documents"]:
        assert d["fein"] is None or len(d["fein"]) == 4


# ── Fix #1: soft-divergence path is normalization-aware (no formatting noise) ──
# Same insured (same FEIN + name), differing ONLY by formatting/synonym/alias in
# the soft fields. These must NOT raise a "differs across documents" review note.

def test_address_formatting_variants_do_not_flag_soft_divergence():
    v = assess_submission_integrity([
        _doc("d1", "Orbin Contracting LLC", "47-1823650",
             mailing="4800 DAHLIA ST #D13, Denver, CO 80216"),
        _doc("d2", "Orbin Contracting LLC", "47-1823650",
             mailing="4800 Dahlia Street D13, Denver, CO 80216"),
    ])
    assert v["review_required"] is False
    assert v["status"] == STATUS_HIGH
    assert not any("address" in r.lower() for r in v["reasons"])


def test_entity_synonym_does_not_flag_soft_divergence():
    v = assess_submission_integrity([
        _doc("d1", "Orbin Contracting", "47-1823650", entity="LLC", mailing="4800 Dahlia St"),
        _doc("d2", "Orbin Contracting", "47-1823650", entity="Limited Liability Company",
             mailing="4800 Dahlia St"),
    ])
    assert v["review_required"] is False
    assert v["status"] == STATUS_HIGH
    assert not any("entity" in r.lower() for r in v["reasons"])


def test_carrier_alias_does_not_flag_soft_divergence():
    v = assess_submission_integrity([
        _doc("d1", "Orbin Contracting", "47-1823650",
             carrier="EMC Property & Casualty Company", mailing="1 Main St"),
        _doc("d2", "Orbin Contracting", "47-1823650",
             carrier="Employers Mutual Casualty Company", mailing="1 Main St"),
    ])
    assert v["review_required"] is False
    assert v["status"] == STATUS_HIGH
    assert not any("carrier" in r.lower() for r in v["reasons"])


def test_materially_different_address_still_flags_medium():
    # A genuinely different street is still surfaced (non-blocking) — we only
    # silenced FORMATTING noise, not real divergence.
    v = assess_submission_integrity([
        _doc("d1", "Orbin Contracting", "47-1823650", mailing="4800 Dahlia St, Denver, CO"),
        _doc("d2", "Orbin Contracting", "47-1823650", mailing="1200 Broadway Ave, Denver, CO"),
    ])
    assert v["status"] == STATUS_MEDIUM
    assert v["review_required"] is False
    assert any("address" in r.lower() for r in v["reasons"])


# ── Fix #3: cluster_documents (used by 'Create separate submissions') ─────────

def test_cluster_documents_splits_three_insureds():
    groups = cluster_documents([
        _doc("d1", "Womens Bar Association", "11-1111111"),
        _doc("d2", "Wake County", "22-2222222"),
        _doc("d3", "Company ABC", "33-3333333"),
    ])
    identified = [g for g in groups if not g["unidentified"]]
    assert len(identified) == 3
    all_ids = sorted(i for g in groups for i in g["doc_ids"])
    assert all_ids == ["d1", "d2", "d3"]


def test_cluster_documents_groups_same_insured():
    groups = cluster_documents([
        _doc("d1", "ORBIN CONTRACTING LLC", "47-1823650"),
        _doc("d2", "Orbin Contracting, LLC", "47-1823650"),
    ])
    identified = [g for g in groups if not g["unidentified"]]
    assert len(identified) == 1
    assert sorted(identified[0]["doc_ids"]) == ["d1", "d2"]


def test_cluster_documents_preserves_unidentified():
    groups = cluster_documents([
        _doc("d1", "Orbin Contracting LLC", "47-1823650"),
        _doc("d2", None, None, doc_type="loss_run"),  # nameless supporting doc
    ])
    unident = [g for g in groups if g["unidentified"]]
    assert len(unident) == 1
    assert "d2" in unident[0]["doc_ids"]


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = failed = 0
    for fn in fns:
        try:
            fn()
            passed += 1
            print(f"  ok   {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL {fn.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  ERR  {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(fns)} passed" + (f", {failed} FAILED" if failed else ""))
    sys.exit(1 if failed else 0)
