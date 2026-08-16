# Relationship preservation - client 2026-08-15 ("preserve what each value
# means and where it belongs"). Root causes fixed:
#   RC1 - flat global facts erased policy/line identity (policy numbers crossing
#         lines of business, carrier+NAIC recombined, expiring term stamped as
#         the proposed term, expired-term hard stop on a Renewal);
#   RC2 - no meaning guard on gap-filled amounts (payroll stamped as gross
#         sales, absence converted into $0);
#   RC3 - conflict detection never gated stamping (umbrella $3M stamped while
#         the $3M-vs-$1M picker sat unresolved).
#
# Fixtures use the client's LITERAL Orbin values (replay-client-report-verbatim).

import re
from datetime import datetime, timedelta

import pytest

from services import pdf_service as ps
from services.pdf_service import (
    _deterministic_map,
    _resolve_section_policy_identity,
    _resolve_renewal_proposed_period,
    _resolve_conflicted_fact_blank,
    _enforce_numeric_meaning_gate,
    _SECTION_FORM_LINE_PHRASES,
    _SCHED_SKIP,
)
from services.extraction_service import _route_renewal_dates
from services.sqs_service import validate_policy_term_not_expired, evaluate_stops
from services.underwriting_consistency import (
    unresolved_withheld_keys, CONFLICT_WITHHOLD_KEYS,
)


# ── The Orbin package, per-line (the client's literal values) ────────────────
ORBIN_LINES = [
    {"line": "Liability", "carrier": "EMC Property & Casualty Company",
     "naic": "25186", "policy_number": "BBC7263", "premium": "$3,954",
     "effective_date": "07/15/2025", "expiration_date": "07/15/2026"},
    {"line": "Automobile", "carrier": "Employers Mutual Casualty Company",
     "naic": "21415", "policy_number": "6E7-40-02---26", "premium": "$2,991",
     "effective_date": "07/15/2025", "expiration_date": "07/15/2026"},
    {"line": "Umbrella", "carrier": "Employers Mutual Casualty Company",
     "naic": "21415", "policy_number": "6J7-40-02---26", "premium": "$3,418",
     "effective_date": "07/15/2025", "expiration_date": "07/15/2026"},
    {"line": "Inland Marine", "carrier": "Employers Mutual Casualty Company",
     "naic": "21415", "policy_number": "6C7-40-02---26", "premium": "$300",
     "effective_date": "07/15/2025", "expiration_date": "07/15/2026"},
]


def orbin_facts(form_id: str, **extra) -> dict:
    facts = {
        "coverage_lines": [dict(e) for e in ORBIN_LINES],
        # The package-level merge winners that used to spray everywhere: the
        # AUTO number won policy_number, and the carrier/NAIC scalars were
        # recombined across two different carriers - the reported defect.
        "policy_number": "6E7-40-02---26",
        "carrier_name": "Employers Mutual Casualty Company",
        "carrier_naic": "25186",
        "_form_id": form_id,
    }
    facts.update(extra)
    return facts


# ═════════════════════════════════════════════════════════════════════════════
# Fix 3 - line-scoped policy identity
# ═════════════════════════════════════════════════════════════════════════════

class TestSectionPolicyIdentity:

    def test_acord_131_gets_the_umbrella_policy_number(self):
        # The client's headline defect: 131 carried 6E7 (Auto). Never again.
        assert _deterministic_map(
            "Policy_PolicyNumberIdentifier_A", orbin_facts("ACORD_131")
        ) == "6J7-40-02---26"

    def test_acord_127_gets_the_auto_policy_number(self):
        assert _deterministic_map(
            "Policy_PolicyNumberIdentifier_A", orbin_facts("ACORD_127")
        ) == "6E7-40-02---26"

    def test_acord_126_gets_the_gl_policy_number_from_bare_liability_naming(self):
        # Orbin's dec names the GL line just "Liability".
        assert _deterministic_map(
            "Policy_PolicyNumberIdentifier_A", orbin_facts("ACORD_126")
        ) == "BBC7263"

    def test_no_section_form_ever_gets_another_lines_number(self):
        own = {
            "ACORD_131": "6J7-40-02---26",
            "ACORD_127": "6E7-40-02---26",
            "ACORD_137_CA": "6E7-40-02---26",
            "ACORD_137_CO": "6E7-40-02---26",
            "ACORD_126": "BBC7263",
            "ACORD_186": "BBC7263",
            "ACORD_141": "6C7-40-02---26",
            # Contractors Equipment coverage rides the Inland Marine line by
            # declaration (_SECTION_FORM_LINE_PHRASES), so the IM policy number
            # is ITS OWN line's number on the 138s - not a borrow.
            "ACORD_138_CA": "6C7-40-02---26",
            "ACORD_138_CO": "6C7-40-02---26",
        }
        for form_id in _SECTION_FORM_LINE_PHRASES:
            got = _deterministic_map(
                "Policy_PolicyNumberIdentifier_A", orbin_facts(form_id))
            expected = own.get(form_id)
            if expected is not None:
                assert got == expected, f"{form_id}: {got!r} != {expected!r}"
            else:
                # A line the package does not grant (WC, property, cyber, ...):
                # blank, NEVER a borrowed number.
                assert got is None, f"{form_id} borrowed {got!r}"

    def test_carrier_and_naic_stamp_as_a_matched_pair(self):
        # 126 (GL): EMC Property & Casualty <-> 25186.
        assert _deterministic_map(
            "Insurer_FullName_A", orbin_facts("ACORD_126")
        ) == "EMC Property & Casualty Company"
        assert _deterministic_map(
            "Insurer_NAICCode_A", orbin_facts("ACORD_126")) == "25186"
        # 131 (Umbrella): Employers Mutual <-> 21415. The recombined pair the
        # client saw (Employers Mutual with 25186) is structurally impossible.
        assert _deterministic_map(
            "Insurer_FullName_A", orbin_facts("ACORD_131")
        ) == "Employers Mutual Casualty Company"
        assert _deterministic_map(
            "Insurer_NAICCode_A", orbin_facts("ACORD_131")) == "21415"

    def test_untrustworthy_line_list_blanks_the_policy_number(self):
        # The literal 2026-08-12 session shape: ONE policy number (the inland
        # marine's, OCR-spaced) attached to four different lines.
        broken = [dict(e, policy_number="6 C 7 - 4 0 - 0 2---26")
                  for e in ORBIN_LINES]
        facts = {"coverage_lines": broken, "policy_number": "6C7-40-02---26",
                 "_form_id": "ACORD_131"}
        assert _deterministic_map("Policy_PolicyNumberIdentifier_A", facts) is None

    def test_no_coverage_lines_preserves_the_legacy_scalar_path(self):
        # Old sessions without per-line data keep today's behavior exactly.
        facts = {"policy_number": "GLOB-1", "_form_id": "ACORD_131"}
        assert _deterministic_map(
            "Policy_PolicyNumberIdentifier_A", facts) == "GLOB-1"

    def test_single_policy_package_still_fills(self):
        facts = {
            "coverage_lines": [
                {"line": "Umbrella", "premium": "$3,418"},
                {"line": "Liability", "policy_number": "ONE-1", "premium": "$3,954"},
            ],
            "_form_id": "ACORD_131",
        }
        # Umbrella line exists but states no number; the whole package carries
        # exactly one number, so it unambiguously belongs to every line.
        assert _deterministic_map("Policy_PolicyNumberIdentifier_A", facts) == "ONE-1"

    def test_package_application_forms_refuse_one_lines_number(self):
        # SUPERSEDED by the 2026-08-15 independent audit (#2): the header
        # identity of ACORD 125/101 is package-level for the LINE, but a
        # package whose evidenced lines carry SEVERAL distinct policy numbers
        # has NO single package number (ground truth: five candidates), so the
        # scalar - which is one line's number, the AUTO's on Orbin - must not
        # stamp there. Blank, and the Q4 grid still pairs each line with its
        # own number. Legacy sessions without per-line data keep the scalar
        # (pinned in test_remaining_relationship_fixes_20260815).
        for form_id in ("ACORD_125", "ACORD_101"):
            assert _deterministic_map(
                "Policy_PolicyNumberIdentifier_A", orbin_facts(form_id)
            ) is None

    def test_resolver_skips_unrelated_fields_and_missing_context(self):
        assert _resolve_section_policy_identity(
            "NamedInsured_FullName_A", orbin_facts("ACORD_131")) is _SCHED_SKIP
        no_ctx = {k: v for k, v in orbin_facts("ACORD_131").items()
                  if k != "_form_id"}
        assert _resolve_section_policy_identity(
            "Policy_PolicyNumberIdentifier_A", no_ctx) is _SCHED_SKIP

    def test_compute_form_gaps_keeps_identity_fields_away_from_gap_fill(self):
        # Integration: with per-line data present, the 131 header identity is
        # deterministic (right or blank) and never reaches the LLM.
        schema = {
            "Policy_PolicyNumberIdentifier_A":
                {"ft": "/Tx", "tu": "Enter identifier: The policy number.",
                 "required": False},
        }
        facts = {k: v for k, v in orbin_facts("ACORD_131").items()
                 if k != "_form_id"}
        mapped, unmatched, det = ps.compute_form_gaps("ACORD_131", schema, facts)
        assert mapped.get("Policy_PolicyNumberIdentifier_A") == "6J7-40-02---26"
        assert "Policy_PolicyNumberIdentifier_A" not in unmatched


# ═════════════════════════════════════════════════════════════════════════════
# Fixes 1 + 2 - renewal term handling
# ═════════════════════════════════════════════════════════════════════════════

def _past_date(days: int) -> str:
    return (datetime.now() - timedelta(days=days)).strftime("%m/%d/%Y")


def _future_date(days: int) -> str:
    return (datetime.now() + timedelta(days=days)).strftime("%m/%d/%Y")


class TestRenewalHardStop:

    def test_expired_term_on_a_renewal_is_a_warning_not_a_hard_stop(self):
        sev, msg = validate_policy_term_not_expired(
            {"expiration_date": _past_date(31), "is_renewal": "yes"})
        assert sev == "soft"
        assert "Renewal" in msg

    def test_expired_term_a_producer_actually_typed_is_still_a_hard_stop(self):
        # SUPERSEDED THE SAME DAY by the Orbin ground truth: the package says
        # "renewal" NOWHERE in 271 pages, so gating this on `is_renewal` alone
        # fixed nothing. What decides it is WHO stated the term - a human
        # proposing a dead period is a real block; a term copied off an
        # uploaded carrier dec page is not. See TestExpiredTermIsAboutWhoSaidIt
        # in test_relationship_root_fixes_20260815.py.
        sev, _msg = validate_policy_term_not_expired({
            "expiration_date": {"value": _past_date(31), "source": "producer",
                                "confidence": "filled"}})
        assert sev == "hard"

    def test_unknown_provenance_fails_toward_asking_not_blocking(self):
        # A bare value with no envelope tells us nothing about who stated it.
        # Blocking a submission on an unknown is the guess this product does
        # not make - it asks instead.
        sev, _msg = validate_policy_term_not_expired(
            {"expiration_date": _past_date(31)})
        assert sev == "soft"

    def test_within_grace_window_stays_soft_either_way(self):
        for facts in ({"expiration_date": _past_date(5)},
                      {"expiration_date": _past_date(5), "is_renewal": "yes"}):
            sev, _msg = validate_policy_term_not_expired(facts)
            assert sev == "soft"

    def test_future_term_raises_nothing(self):
        assert validate_policy_term_not_expired(
            {"expiration_date": _future_date(200), "is_renewal": "yes"}) is None

    def test_evaluate_stops_no_longer_hard_caps_the_orbin_renewal(self):
        hard, soft = evaluate_stops(
            {"expiration_date": _past_date(31), "is_renewal": "yes"}, {})
        assert not any("Policy term already expired" in h for h in hard)
        assert any("Policy term already expired" in s for s in soft)


class TestRenewalDateRouting:

    def test_expired_renewal_term_routes_to_prior_and_derives_the_new_term(self):
        # The expiring term moves to prior_*; the PROPOSED term is derived as
        # "starts when the old one ends", flagged for confirmation. An earlier
        # cut blanked both boxes, which stripped ACORD 125's Tier-1 PROPOSED
        # EFF DATE and made the producer type a date the document answers.
        mf = {"is_renewal": "yes",
              "effective_date": _past_date(396),
              "expiration_date": _past_date(31)}
        _route_renewal_dates(mf)
        assert mf["prior_effective_date"] and mf["prior_expiration_date"]
        assert mf["renewal_dates_routed"] is True
        # Proposed effective == the expiring policy's expiration date.
        assert mf["effective_date"]["value"] == _past_date(31)
        assert mf["effective_date"]["source"] == "derived"
        assert mf["effective_date"]["confidence"] == "low_confidence"
        # ...and a full annual term follows it.
        assert mf["expiration_date"]["value"] == _future_date(334)

    def test_a_derived_renewal_term_is_never_treated_as_producer_asserted(self):
        from services.sqs_service import _dates_are_producer_asserted
        mf = {"is_renewal": "yes", "effective_date": _past_date(396),
              "expiration_date": _past_date(31)}
        _route_renewal_dates(mf)
        assert _dates_are_producer_asserted(mf) is False

    def test_an_odd_length_term_derives_only_the_effective_date(self):
        # A 2-year or stub term is not safely extrapolated - the effective date
        # is still known (the old term ends), the new expiry is not.
        mf = {"is_renewal": "yes", "effective_date": _past_date(900),
              "expiration_date": _past_date(31)}
        _route_renewal_dates(mf)
        assert mf["effective_date"]["value"] == _past_date(31)
        assert "expiration_date" not in mf

    def test_future_term_on_a_renewal_is_untouched(self):
        mf = {"is_renewal": "yes", "effective_date": _future_date(10),
              "expiration_date": _future_date(375)}
        _route_renewal_dates(mf)
        assert mf["effective_date"] and mf["expiration_date"]
        assert "renewal_dates_routed" not in mf

    def test_non_renewal_is_untouched(self):
        mf = {"effective_date": _past_date(396), "expiration_date": _past_date(31)}
        _route_renewal_dates(mf)
        assert mf["effective_date"] and mf["expiration_date"]

    def test_an_extracted_prior_term_is_never_overwritten(self):
        mf = {"is_renewal": "yes",
              "effective_date": _past_date(396), "expiration_date": _past_date(31),
              "prior_effective_date": "07/15/2024",
              "prior_expiration_date": "07/15/2025"}
        _route_renewal_dates(mf)
        assert mf["prior_effective_date"] == "07/15/2024"
        assert mf["prior_expiration_date"] == "07/15/2025"
        # The proposed term is re-derived from the EXPIRING term regardless,
        # so the two namespaces stay distinct.
        assert mf["effective_date"]["source"] == "derived"

    def test_routed_proposed_boxes_are_owned_blanks_on_application_forms(self):
        facts = {"renewal_dates_routed": True, "_form_id": "ACORD_131"}
        assert _resolve_renewal_proposed_period(
            "Policy_EffectiveDate_A", facts) is None
        assert _deterministic_map("Policy_EffectiveDate_A", facts) is None

    def test_a_supplied_proposed_date_stamps(self):
        facts = {"renewal_dates_routed": True, "_form_id": "ACORD_131",
                 "effective_date": "07/15/2026"}
        assert _resolve_renewal_proposed_period(
            "Policy_EffectiveDate_A", facts) == "07/15/2026"

    def test_certificate_forms_are_exempt(self):
        # An ACORD 25/28 documents the EXISTING policy - not owned here.
        facts = {"renewal_dates_routed": True, "_form_id": "ACORD_25"}
        assert _resolve_renewal_proposed_period(
            "Policy_EffectiveDate_A", facts) is _SCHED_SKIP

    def test_not_routed_means_not_owned(self):
        assert _resolve_renewal_proposed_period(
            "Policy_EffectiveDate_A", {"_form_id": "ACORD_131"}) is _SCHED_SKIP


# ═════════════════════════════════════════════════════════════════════════════
# Fix 4 - numeric meaning gate
# ═════════════════════════════════════════════════════════════════════════════

_SALES_FIELD = "BusinessInformation_AnnualGrossSalesAmount_A"
_FOREIGN_FIELD = "BusinessInformation_ForeignGrossSalesAmount_A"
_PAYROLL_FIELD = "BusinessInformation_TotalPayrollAmount_A"

_GATE_SCHEMA = {
    _SALES_FIELD: {"ft": "/Tx", "tu": "Enter amount: The annual gross sales."},
    _FOREIGN_FIELD: {"ft": "/Tx",
                     "tu": "Enter amount: The estimated annual foreign gross sales."},
    _PAYROLL_FIELD: {"ft": "/Tx", "tu": "Enter amount: The total payroll."},
}

_ORBIN_WITNESS_FACTS = {
    # $39,300 is stated by the document ONLY as payroll exposure (GL class
    # 91580) - the client's literal example.
    "gl_class_code_schedule": [
        {"class_code": "91580",
         "classification": "Contractors - Executive Supervisors",
         "premium_basis": "Payroll", "exposure_amount": "$39,300"},
    ],
    "dec_page_entries": [
        {"label": "Payroll / Exposure", "value": "$39,300", "owner": "policy"},
    ],
}


class TestNumericMeaningGate:

    def test_payroll_witnessed_amount_cannot_enter_a_sales_box(self):
        mapped = {_SALES_FIELD: "$39,300"}
        _enforce_numeric_meaning_gate(
            mapped, _GATE_SCHEMA, dict(_ORBIN_WITNESS_FACTS), {_SALES_FIELD})
        assert mapped[_SALES_FIELD] is None

    def test_the_same_amount_stays_in_a_payroll_box(self):
        mapped = {_PAYROLL_FIELD: "$39,300"}
        _enforce_numeric_meaning_gate(
            mapped, _GATE_SCHEMA, dict(_ORBIN_WITNESS_FACTS), {_PAYROLL_FIELD})
        assert mapped[_PAYROLL_FIELD] == "$39,300"

    def test_an_amount_also_stated_as_sales_is_kept(self):
        facts = {
            "dec_page_entries": [
                {"label": "Payroll", "value": "$39,300"},
                {"label": "Gross Sales", "value": "$39,300"},
            ],
        }
        mapped = {_SALES_FIELD: "$39,300"}
        _enforce_numeric_meaning_gate(mapped, _GATE_SCHEMA, facts, {_SALES_FIELD})
        assert mapped[_SALES_FIELD] == "$39,300"

    def test_unwitnessed_amounts_are_left_alone(self):
        mapped = {_SALES_FIELD: "$120,000"}
        _enforce_numeric_meaning_gate(
            mapped, _GATE_SCHEMA, dict(_ORBIN_WITNESS_FACTS), {_SALES_FIELD})
        assert mapped[_SALES_FIELD] == "$120,000"

    def test_fabricated_zero_is_blanked(self):
        # "$0 Foreign Gross Sales even though the source documents do not
        # establish that foreign sales are zero" - absence is not an answer.
        mapped = {_FOREIGN_FIELD: "$0"}
        _enforce_numeric_meaning_gate(
            mapped, _GATE_SCHEMA, dict(_ORBIN_WITNESS_FACTS), {_FOREIGN_FIELD})
        assert mapped[_FOREIGN_FIELD] is None

    def test_a_stated_zero_survives(self):
        facts = {"dec_page_entries": [{"label": "Foreign Gross Sales", "value": "$0"}]}
        mapped = {_FOREIGN_FIELD: "$0"}
        _enforce_numeric_meaning_gate(mapped, _GATE_SCHEMA, facts, {_FOREIGN_FIELD})
        assert mapped[_FOREIGN_FIELD] == "$0"

    def test_non_numeric_conventions_are_untouched(self):
        mapped = {_SALES_FIELD: "Included"}
        _enforce_numeric_meaning_gate(
            mapped, _GATE_SCHEMA, dict(_ORBIN_WITNESS_FACTS), {_SALES_FIELD})
        assert mapped[_SALES_FIELD] == "Included"

    def test_deterministic_fills_are_never_touched(self):
        mapped = {_SALES_FIELD: "$39,300"}
        _enforce_numeric_meaning_gate(
            mapped, _GATE_SCHEMA, dict(_ORBIN_WITNESS_FACTS), set())
        assert mapped[_SALES_FIELD] == "$39,300"


# ═════════════════════════════════════════════════════════════════════════════
# Fix 5 - unresolved conflicts stamp blank
# ═════════════════════════════════════════════════════════════════════════════

def _uw_result(review_required: bool) -> dict:
    return {"fields": [{
        "fact_key": "umbrella_limit", "label": "Umbrella / Excess Limit",
        "status": "conflict" if review_required else "consistent",
        "review_required": review_required,
    }]}


class TestConflictWithhold:

    def test_umbrella_limit_is_a_withhold_key(self):
        assert "umbrella_limit" in CONFLICT_WITHHOLD_KEYS

    def test_unresolved_conflict_is_withheld(self):
        assert unresolved_withheld_keys(_uw_result(True), {}) == ["umbrella_limit"]

    def test_confirmation_clears_the_withhold(self):
        assert unresolved_withheld_keys(
            _uw_result(True), {"umbrella_limit": "$1,000,000"}) == []

    def test_consistent_values_are_not_withheld(self):
        assert unresolved_withheld_keys(_uw_result(False), {}) == []

    def test_alias_bridged_umbrella_fields_stamp_blank_while_conflicted(self):
        # Find the real ACORD 131 fields whose alias canonical bridges to
        # umbrella_limit - the boxes that stamped $3M on the client's run.
        from services.alias_stamper import _ALIAS_MAPS, CANONICAL_TO_EXTRACTION
        bridge_fields = [
            f for f, canonical in (_ALIAS_MAPS.get("ACORD_131") or {}).items()
            if CANONICAL_TO_EXTRACTION.get(canonical) == "umbrella_limit"
        ]
        assert bridge_fields, "ACORD_131 alias map lost its umbrella-limit fields"
        facts = {"umbrella_limit": "$3,000,000",
                 "_uw_conflicted_keys": ["umbrella_limit"],
                 "_form_id": "ACORD_131"}
        for field in bridge_fields:
            assert _resolve_conflicted_fact_blank(field, facts) is None
            assert _deterministic_map(field, facts) is None

    def test_alias_stamper_skips_withheld_facts(self):
        from services.alias_stamper import (
            stamp_form_fields, _ALIAS_MAPS, CANONICAL_TO_EXTRACTION,
        )
        bridge_fields = [
            f for f, canonical in (_ALIAS_MAPS.get("ACORD_131") or {}).items()
            if CANONICAL_TO_EXTRACTION.get(canonical) == "umbrella_limit"
        ]
        facts = {"umbrella_limit": "$3,000,000",
                 "_uw_conflicted_keys": ["umbrella_limit"]}
        assert stamp_form_fields("ACORD_131", facts, bridge_fields) == {}
        # And without the withhold the same fields stamp normally.
        filled = stamp_form_fields(
            "ACORD_131", {"umbrella_limit": "$3,000,000"}, bridge_fields)
        assert set(filled) == set(bridge_fields)

    def test_no_withhold_means_no_interception(self):
        assert _resolve_conflicted_fact_blank(
            "Policy_PolicyNumberIdentifier_A",
            {"policy_number": "X-1"}) is _SCHED_SKIP

    def test_the_fact_itself_stays_for_scoring(self):
        # Only the stamped output is withheld - SQS pillars keep reading the
        # fact (regression guard: never delete the fact to blank the box).
        facts = {"umbrella_limit": "$3,000,000",
                 "_uw_conflicted_keys": ["umbrella_limit"]}
        assert facts["umbrella_limit"] == "$3,000,000"
        _resolve_conflicted_fact_blank("ExcessUmbrella_UmbrellaEachOccurrenceAmount_A", facts)
        assert facts["umbrella_limit"] == "$3,000,000"
