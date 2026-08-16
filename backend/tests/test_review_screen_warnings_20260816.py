# The producer's own review-screen session, 2026-08-16 (run f50825ae), pinned
# with the literal values from the screen.
#
#   W1  THREE "Umbrella policy period alignment" issues, none of them real:
#       "Umbrella effective date (07/15/25) does not match GL/policy effective
#       date (07/15/2026)". The umbrella dates come off the umbrella's own DEC
#       (so on a renewal: the EXPIRING term); effective_date after
#       _route_renewal_dates is the DERIVED PROPOSED term. Expiring vs
#       proposed - the client's chronology rule broken inside a validator.
#   W2  ...and UNRESOLVABLE: the fix panel offers the two dates it compared, so
#       07/15/2026 -> 09/15/2026 just re-raised it as 09/15/2027. No value the
#       producer can type makes an expiring term equal a proposed one.
#   W3  "GL coverage detected but no revenue or payroll found" on a package
#       whose GL schedule states Prem Basis: Payroll / Exposure: $39,300.
#   W4  The $3M/$1M umbrella conflict stamping $3M unchallenged.

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

import services.cross_form_validator as cfv                      # noqa: E402
import services.sqs_service as sq                                # noqa: E402
import services.extraction_service as es                         # noqa: E402


# ── W1/W2: the umbrella period check compares like with like ─────────────────

_ORBIN_RENEWAL = {
    # what _route_renewal_dates leaves behind on this package
    "is_renewal": "yes",
    "renewal_dates_routed": True,
    "prior_effective_date": "07/15/2025",
    "prior_expiration_date": "07/15/2026",
    "effective_date": "07/15/2026",        # DERIVED proposed term
    "expiration_date": "07/15/2027",
    # read off the umbrella's own dec page = the EXPIRING term
    "umbrella_effective_date": "07/15/25",
    "umbrella_expiration_date": "07/15/26",
    "umbrella_limit": "$3,000,000",
}
_FLAGS = {"has_umbrella": True, "has_general_liability": True}
_TRIGGERED = {"ACORD_125", "ACORD_131"}


def _period_issues(facts):
    return [i for i in cfv._check_umbrella_attachment_stack(
        facts, _FLAGS, _TRIGGERED)
        if "period" in i.get("code", "") or "misaligned" in i.get("code", "")]


def test_the_producers_three_false_misalignments_are_gone():
    """THE LITERAL SCREEN: 07/15/25 vs 07/15/2026 and 07/15/26 vs 07/15/2027,
    where the umbrella aligns perfectly with the EXPIRING package term."""
    assert _period_issues(dict(_ORBIN_RENEWAL)) == []


def test_the_comparison_uses_the_expiring_term_on_a_routed_renewal():
    eff, exp, label = cfv._package_period_on_umbrella_footing(dict(_ORBIN_RENEWAL))
    assert (eff, exp) == ("07/15/2025", "07/15/2026")
    assert "expiring" in label


def test_a_genuine_misalignment_on_a_renewal_still_fires():
    """The check must not be neutered - an umbrella whose term matches NEITHER
    the expiring nor the proposed package term is still wrong."""
    facts = dict(_ORBIN_RENEWAL,
                 umbrella_effective_date="03/01/25",
                 umbrella_expiration_date="03/01/26")
    assert _period_issues(facts)


def test_a_non_renewal_is_completely_unchanged():
    """No routing -> the old comparison, byte for byte."""
    facts = {"effective_date": "07/15/2026", "expiration_date": "07/15/2027",
             "umbrella_effective_date": "01/01/2026",
             "umbrella_expiration_date": "01/01/2027"}
    eff, exp, label = cfv._package_period_on_umbrella_footing(facts)
    assert (eff, exp, label) == ("07/15/2026", "07/15/2027", "GL/policy")
    assert _period_issues(facts)


def test_a_routed_renewal_with_no_prior_term_stands_down():
    """No comparable term means no comparison - never a fall-back to the
    proposed term, which is the footing mismatch this fix exists to end."""
    facts = dict(_ORBIN_RENEWAL)
    facts.pop("prior_effective_date")
    facts.pop("prior_expiration_date")
    assert _period_issues(facts) == []


def test_the_auto_and_wc_check_is_untouched():
    """Those dates come off their own dec pages, so they share the umbrella's
    footing by construction - the sibling check must keep firing."""
    facts = dict(_ORBIN_RENEWAL, auto_effective_date="01/01/25",
                 auto_expiration_date="01/01/26")
    issues = cfv._check_umbrella_period_vs_auto_wc(
        facts, {"has_umbrella": True, "has_auto_coverage": True},
        {"ACORD_127", "ACORD_131"})
    assert any("auto" in i.get("code", "") for i in issues)


# ── W1b: the LEGACY engine held a second copy of the same rule ───────────────
# Reported after C64 shipped: the screen STILL showed "Umbrella and GL policy
# periods misaligned" - this copy's own wording, from sqs_service - because
# fixing cross_form_validator left the legacy twin comparing expiring against
# proposed, and the legacy engine is the one that drives the 60/85 caps.
# Third time this duplication has cost a fix (Auto hired/non-owned symbols,
# Umbrella SIR - both in CLAUDE.md).

def test_the_legacy_engine_emits_neither_misalignment_on_this_renewal():
    _h, soft = sq.evaluate_stops(dict(_ORBIN_RENEWAL), dict(_FLAGS))
    assert not [s for s in soft if "misalign" in s.lower()]


def test_the_legacy_engine_still_reports_a_genuine_misalignment():
    facts = dict(_ORBIN_RENEWAL, umbrella_effective_date="03/01/25",
                 umbrella_expiration_date="03/01/26")
    _h, soft = sq.evaluate_stops(facts, dict(_FLAGS))
    assert [s for s in soft if "misalign" in s.lower()]


def test_the_legacy_engine_delegates_instead_of_reimplementing():
    """ANTI-ROT. Two copies of one rule is the defect; the legacy engine must
    ASK for the comparable term, never derive its own."""
    import inspect
    src = inspect.getsource(sq.evaluate_stops)
    assert "_package_period_on_umbrella_footing" in src


# ── W1c: removing a false warning must not leave SILENCE ─────────────────────
# The producer, after the misalignment was fixed: "if there are real warnings
# and hard stops then why are you hiding them". Correct instinct. The umbrella's
# stated term IS the expiring one and no document states the term being applied
# for - a genuine gap that had no voice once the false misalignment was gone.

def test_the_expiring_underlying_lines_are_recorded():
    mf = {"is_renewal": "yes", "effective_date": "07/15/2025",
          "expiration_date": "07/15/2026",
          "umbrella_expiration_date": "07/15/26",
          "auto_expiration_date": "07/15/26"}
    es._route_renewal_dates(mf)
    assert set(mf.get("renewal_lines_expiring") or []) == {"Umbrella", "Auto"}


def test_a_future_dated_underlying_term_is_not_flagged():
    """A line that already carries its renewal term is not unknown."""
    mf = {"is_renewal": "yes", "effective_date": "07/15/2025",
          "expiration_date": "07/15/2026",
          "umbrella_expiration_date": "07/15/2099"}
    es._route_renewal_dates(mf)
    assert "Umbrella" not in (mf.get("renewal_lines_expiring") or [])


def test_the_unknown_proposed_umbrella_term_is_reported():
    facts = dict(_ORBIN_RENEWAL, renewal_lines_expiring=["Umbrella"])
    _h, soft = sq.evaluate_stops(facts, dict(_FLAGS))
    hits = [s for s in soft if "proposed policy term is not stated" in s]
    assert len(hits) == 1, soft


def test_the_new_warning_never_caps_the_score():
    """Recommended, not a hard stop - the producer's SQS must not be capped at
    60 by an unknown the documents simply do not answer."""
    facts = dict(_ORBIN_RENEWAL, renewal_lines_expiring=["Umbrella"])
    hard, _soft = sq.evaluate_stops(facts, dict(_FLAGS))
    assert not [h for h in hard if "proposed policy term" in h]


def test_the_new_warning_is_classified_and_resolvable():
    """A row with no cluster, no tier or no resolution renders a dead button -
    the exact defect the legacy-rules work exists to prevent."""
    from services.issue_registry import classify_legacy, resolution_for
    msg = ("Renewal: the umbrella's proposed policy term is not stated in the "
           "documents - confirm the proposed effective and expiration dates.")
    code, cluster, tier = classify_legacy(msg, "soft")[:3]
    assert code == "legacy_umbrella_renewal_term_unknown"
    assert cluster == "Umbrella policy period alignment"
    assert tier == "recommended"
    res = resolution_for(code) or {}
    assert res.get("mode") == "field"
    assert res.get("facts") == ["umbrella_effective_date",
                                "umbrella_expiration_date"]


# ── W3: the GL exposure basis is stated by the class schedule ────────────────

def test_the_class_schedule_answers_the_gl_exposure_question():
    """THE LITERAL WARNING, on the client's literal schedule row."""
    facts = {"gl_class_code_schedule": [
        {"location": "001", "class_code": "91580",
         "premium_basis": "Payroll", "exposure_amount": "$39,300"}]}
    assert sq._dec_entries_state_payroll(facts)
    _h, soft = sq.evaluate_stops(facts, {"has_general_liability": True})
    assert not any("no revenue or payroll" in s for s in soft)


def test_a_schedule_row_with_no_amount_is_not_an_exposure_basis():
    facts = {"gl_class_code_schedule": [
        {"class_code": "91580", "premium_basis": "Payroll",
         "exposure_amount": None}]}
    assert not sq._dec_entries_state_payroll(facts)


def test_the_payroll_flag_is_derived_before_the_backfill_can_fail():
    """ANTI-ROT. Both lines used to sit after the backfill in ONE try block, so
    any exception there took the flag down with the entries."""
    import inspect
    src = inspect.getsource(es.merge_facts)
    assert src.index('mf["dec_states_payroll_basis"] = True') < \
        src.index("_backfill_empty_facts_from_entries(mf, _verified)")


# ── W4: every stated umbrella limit is a conflict witness ────────────────────

_COI_NARRATIVE = ("Per the certificate dated 07/25/2025, the Umbrella limit "
                  "was reduced from $3,000,000 to $1,000,000 effective 7/25/25. "
                  "The change endorsement was not located in the file.")


def test_the_cois_reduction_sentence_yields_both_amounts():
    got = es._stated_umbrella_limits({"additional_remarks_text": _COI_NARRATIVE})
    keys = {es._amount_key(v) for v in got}
    assert {3_000_000, 1_000_000} <= keys


def test_the_conflict_is_withheld_even_when_the_merge_rejected_nothing():
    """THE CLIENT'S CASE: one document in, no merge reject, and $3M stamped
    unchallenged. The narrative disagrees, so the box is withheld."""
    mf = {"umbrella_limit": "$3,000,000", "additional_remarks_text": _COI_NARRATIVE}
    es._flag_intra_document_limit_conflicts(mf, {})
    assert "umbrella_limit" in (mf.get("_uw_conflicted_keys") or [])
    assert mf["umbrella_limit"] == "$3,000,000"   # the FACT is untouched


def test_agreement_never_manufactures_a_conflict():
    mf = {"umbrella_limit": "$3,000,000",
          "additional_remarks_text": "The Umbrella limit is $3,000,000."}
    es._flag_intra_document_limit_conflicts(mf, {})
    assert not mf.get("_uw_conflicted_keys")


def test_an_unrelated_amount_cannot_manufacture_a_conflict():
    """Only sentences NAMING the umbrella/excess line are read, and only
    7-digit-plus amounts - a GL limit or a premium cannot fabricate one."""
    mf = {"umbrella_limit": "$3,000,000",
          "additional_remarks_text": ("General Liability each occurrence is "
                                      "$1,000,000. Total premium $10,663.")}
    es._flag_intra_document_limit_conflicts(mf, {})
    assert not mf.get("_uw_conflicted_keys")
