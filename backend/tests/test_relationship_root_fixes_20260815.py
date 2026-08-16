# Round 2 - the ROOT causes, not the stamping symptoms (client 2026-08-15).
#
# Round 1 stopped the wrong values reaching the paper but left the source
# corrupt, so 131/127 shipped BLANK identity boxes. The live merge log:
#
#   merge coverage_lines FINAL: [('Property','None','6C7-40-02---26'),
#     ('Liability','$3,954','6C7-40-02---26'), ('Automobile','$2,991','6C7-40-02---26'),
#     ('Umbrella','$3,418','6C7-40-02---26'), ...]
#
# ONE policy number on EIGHT lines. Everything downstream was working from a
# fact whose line->policy relationship had already been destroyed.

import re

import pytest

from services import extraction_service as es
from services import pdf_service as ps
from services.pdf_service import _deterministic_map, _SCHED_SKIP


# The live-run shape: every line carrying the inland-marine policy number.
CORRUPT_LINES = [
    {"line": "Property",              "premium": None,      "policy_number": "6C7-40-02---26"},
    {"line": "Liability",             "premium": "$3,954.00", "policy_number": "6C7-40-02---26"},
    {"line": "Inland Marine",         "premium": "$300.00",   "policy_number": "6C7-40-02---26"},
    {"line": "Automobile",            "premium": "$2,991.00", "policy_number": "6C7-40-02---26"},
    {"line": "Umbrella",              "premium": "$3,418.00", "policy_number": "6C7-40-02---26"},
]

# The pairs the document really prints - verified verbatim by _verify_dec_entries
# and visible on ACORD 125's Q4 grid on the same run.
REAL_ENTRIES = [
    # Two carriers on one package - straight from orbin_ground_truth.json:
    # EMC Property & Casualty issues the GL part, Employers Mutual the rest.
    {"label": "Company", "value": "EMC Property & Casualty Company",
     "owner": "carrier", "section": "GENERAL LIABILITY DECLARATIONS",
     "line_of_business": "Commercial General Liability"},
    {"label": "Company", "value": "EMPLOYERS MUTUAL CASUALTY COMPANY",
     "owner": "carrier", "section": "COMMERCIAL UMBRELLA DECLARATIONS",
     "line_of_business": "Commercial Liability Umbrella"},
    {"label": "Policy Number", "value": "BBC7263",
     "section": "COMMERCIAL GENERAL LIABILITY DECLARATIONS",
     "line_of_business": "Commercial General Liability", "policy_number": "BBC7263"},
    {"label": "Policy Number", "value": "6E7-40-02---26",
     "section": "BUSINESS AUTO DECLARATIONS",
     "line_of_business": "Covered Autos Liability", "policy_number": "6E7-40-02---26"},
    {"label": "Policy Number", "value": "6J7-40-02---26",
     "section": "COMMERCIAL UMBRELLA DECLARATIONS",
     "line_of_business": "Commercial Liability Umbrella", "policy_number": "6J7-40-02---26"},
    {"label": "Policy Number", "value": "6C7-40-02---26",
     "section": "INLAND MARINE DECLARATIONS",
     "line_of_business": "Commercial Inland Marine", "policy_number": "6C7-40-02---26"},
]


def _repaired_facts() -> dict:
    mf = {"coverage_lines": [dict(e) for e in CORRUPT_LINES],
          "dec_page_entries": [dict(e) for e in REAL_ENTRIES]}
    es._repair_coverage_lines_from_entries(mf)
    return mf


def _by_line(mf: dict) -> dict:
    return {e["line"]: e.get("policy_number") for e in mf["coverage_lines"]}


class TestCoverageLineRepair:

    def test_the_live_corruption_is_detected(self):
        assert es._coverage_lines_are_self_contradictory(CORRUPT_LINES) is True

    def test_a_healthy_list_is_left_alone(self):
        healthy = [
            {"line": "Umbrella",  "policy_number": "6J7-40-02---26"},
            {"line": "Automobile", "policy_number": "6E7-40-02---26"},
        ]
        assert es._coverage_lines_are_self_contradictory(healthy) is False
        mf = {"coverage_lines": [dict(e) for e in healthy],
              "dec_page_entries": [dict(e) for e in REAL_ENTRIES]}
        es._repair_coverage_lines_from_entries(mf)
        assert _by_line(mf) == {"Umbrella": "6J7-40-02---26",
                                "Automobile": "6E7-40-02---26"}

    def test_each_line_is_re_paired_to_its_own_policy(self):
        got = _by_line(_repaired_facts())
        assert got["Umbrella"] == "6J7-40-02---26"      # the client's headline
        assert got["Automobile"] == "6E7-40-02---26"
        assert got["Liability"] == "BBC7263"
        assert got["Inland Marine"] == "6C7-40-02---26"

    def test_a_line_the_document_cannot_settle_is_cleared_not_guessed(self):
        # "Property" appears in no dec section - blank, never a borrowed number.
        assert _by_line(_repaired_facts())["Property"] is None

    def test_the_section_heading_alone_can_attribute_a_number(self):
        mf = {"coverage_lines": [dict(e) for e in CORRUPT_LINES],
              "dec_page_entries": [
                  {"label": "Policy Number", "value": "6J7-40-02---26",
                   "section": "COMMERCIAL UMBRELLA POLICY DECLARATIONS",
                   "policy_number": "6J7-40-02---26"},
              ]}
        es._repair_coverage_lines_from_entries(mf)
        assert _by_line(mf)["Umbrella"] == "6J7-40-02---26"

    def test_a_form_number_is_never_used_as_a_policy_number(self):
        assert es._looks_like_a_policy_number("6J7-40-02---26") is True
        assert es._looks_like_a_policy_number("BBC7263") is True
        for form_no in ("CG 00 01 04 13", "IM 7100 06 04", "CA 7007 11 20"):
            assert es._looks_like_a_policy_number(form_no) is False

    def test_auto_beats_bare_liability_in_line_canonicalisation(self):
        # "Commercial Auto Liability" is AUTO - the bare word "liability" is the
        # weakest signal there is and must never win.
        assert es._canon_line("Commercial Auto Liability") == "auto"
        assert es._canon_line("Covered Autos Liability") == "auto"
        assert es._canon_line("Commercial General Liability") == "general_liab"
        assert es._canon_line("Commercial Liability Umbrella") == "umbrella"
        assert es._canon_line("Employers Liability") == "workers_comp"

    def test_repaired_lines_flow_through_to_the_forms(self):
        facts = dict(_repaired_facts())
        for form_id, expected in (("ACORD_131", "6J7-40-02---26"),
                                  ("ACORD_127", "6E7-40-02---26"),
                                  ("ACORD_126", "BBC7263"),
                                  ("ACORD_141", "6C7-40-02---26")):
            f = {**facts, "_form_id": form_id}
            assert _deterministic_map("Policy_PolicyNumberIdentifier_A", f) == expected


class TestExpiringPolicyNumber:
    """131's EXPIRING POL # came back BBC7263 - the CURRENT GL policy."""

    def test_a_current_policy_number_is_never_the_expiring_one(self):
        facts = {**_repaired_facts(),
                 "_form_id": "ACORD_131",
                 "prior_policy_number": "BBC7263"}
        assert _deterministic_map("PriorCoverage_PolicyNumberIdentifier_A", facts) is None

    def test_a_genuine_prior_number_for_this_line_stamps(self):
        facts = {**_repaired_facts(), "_form_id": "ACORD_131",
                 "prior_coverage_by_line": [
                     {"line": "Commercial Liability Umbrella", "policy_no": "6J7-40-02---25"},
                     {"line": "Commercial General Liability",  "policy_no": "BBC7263 - 25"},
                 ]}
        assert _deterministic_map(
            "PriorCoverage_PolicyNumberIdentifier_A", facts) == "6J7-40-02---25"

    def test_another_lines_prior_number_is_never_borrowed(self):
        facts = {**_repaired_facts(), "_form_id": "ACORD_131",
                 "prior_coverage_by_line": [
                     {"line": "Commercial General Liability", "policy_no": "BBC7263 - 25"},
                 ]}
        assert _deterministic_map(
            "PriorCoverage_PolicyNumberIdentifier_A", facts) is None

    def test_a_multi_line_package_never_sprays_the_prior_scalar(self):
        facts = {**_repaired_facts(), "_form_id": "ACORD_131",
                 "prior_policy_number": "SOME-OLD-1"}
        assert _deterministic_map(
            "PriorCoverage_PolicyNumberIdentifier_A", facts) is None

    def test_a_single_line_package_still_uses_the_scalar(self):
        facts = {"coverage_lines": [{"line": "Umbrella", "policy_number": "6J7"}],
                 "_form_id": "ACORD_131", "prior_policy_number": "6J7-40-02---25"}
        assert _deterministic_map(
            "PriorCoverage_PolicyNumberIdentifier_A", facts) == "6J7-40-02---25"

    def test_package_forms_are_untouched(self):
        facts = {**_repaired_facts(), "_form_id": "ACORD_125",
                 "prior_policy_number": "OLD-1"}
        assert ps._resolve_section_prior_policy(
            "PriorCoverage_PolicyNumberIdentifier_A", facts) is _SCHED_SKIP


class TestIsRenewalBackfill:

    def test_the_documents_own_wording_sets_the_fact(self):
        mf = {}
        es._backfill_is_renewal(mf, "RENEWAL OF: 6E7-40-02---25\nSOME OTHER TEXT")
        assert es._fv(mf, "is_renewal") == "yes"

    def test_an_extracted_value_is_never_overridden(self):
        mf = {"is_renewal": "no"}
        es._backfill_is_renewal(mf, "RENEWAL OF: 6E7-40-02---25")
        assert es._fv(mf, "is_renewal") == "no"

    def test_silence_stays_silent(self):
        mf = {}
        es._backfill_is_renewal(mf, "COMMERCIAL PACKAGE POLICY DECLARATIONS")
        assert "is_renewal" not in mf

    def test_the_orbin_package_says_renewal_nowhere_and_must_not_be_forced(self):
        # Verified against orbin_ground_truth.json: 271 pages, ZERO renewal
        # wording. The only hit is the FORM TITLE "Cancellation And
        # Nonrenewal", which must never be read as "this is a renewal".
        mf = {}
        es._backfill_is_renewal(mf, "IL 02 28 CO Cancellation And Nonrenewal")
        assert "is_renewal" not in mf

    def test_the_backfill_unblocks_the_renewal_date_routing(self):
        from datetime import datetime, timedelta
        past = (datetime.now() - timedelta(days=40)).strftime("%m/%d/%Y")
        mf = {"effective_date": "07/15/2025", "expiration_date": past}
        es._backfill_is_renewal(mf, "RENEWAL OF: 6E7-40-02---25")
        es._route_renewal_dates(mf)
        assert mf.get("renewal_dates_routed") is True
        assert mf["prior_expiration_date"] == past
        # Proposed term derived, not blanked - see the 2026-08-15 regression.
        assert mf["effective_date"]["value"] == past


class TestNumericMeaningGateRoundTwo:
    """Two live escapes on the 2026-08-15 fresh run, both on ACORD 131."""

    SCHEMA = {
        "BusinessInformation_AnnualGrossSalesAmount_A":
            {"ft": "/Tx", "tu": "Enter amount: The annual gross sales."},
        "ExcessUmbrella_EmployeeBenefits_LimitAmount_A":
            {"ft": "/Tx", "tu": "Enter amount: The employee benefits liability limit."},
    }

    def test_subcontract_total_cost_cannot_become_gross_sales(self):
        # ACORD 131 shipped ANN GROSS SALES = $350,000, which is GL class
        # 91585's "Prem Basis: Total Cost". orbin_ground_truth: the box must be
        # blank, and this figure is the package's strongest revenue decoy.
        facts = {"gl_class_code_schedule": [
            {"class_code": "91585", "premium_basis": "Total Cost",
             "exposure_amount": "$350,000"}]}
        mapped = {"BusinessInformation_AnnualGrossSalesAmount_A": "$350,000"}
        ps._enforce_numeric_meaning_gate(mapped, self.SCHEMA, facts, set(mapped))
        assert mapped["BusinessInformation_AnnualGrossSalesAmount_A"] is None

    def test_the_one_letter_basis_codes_are_honoured(self):
        facts = {"gl_class_code_schedule": [
            {"premium_basis": "C", "exposure_amount": "$350,000"}]}
        mapped = {"BusinessInformation_AnnualGrossSalesAmount_A": "$350,000"}
        ps._enforce_numeric_meaning_gate(mapped, self.SCHEMA, facts, set(mapped))
        assert mapped["BusinessInformation_AnnualGrossSalesAmount_A"] is None

    def test_a_real_gross_sales_basis_still_fills(self):
        facts = {"gl_class_code_schedule": [
            {"premium_basis": "Gross Sales", "exposure_amount": "$350,000"}]}
        mapped = {"BusinessInformation_AnnualGrossSalesAmount_A": "$350,000"}
        ps._enforce_numeric_meaning_gate(mapped, self.SCHEMA, facts, set(mapped))
        assert mapped["BusinessInformation_AnnualGrossSalesAmount_A"] == "$350,000"

    def test_one_real_zero_no_longer_unlocks_every_fabricated_zero(self):
        # The umbrella's SIR really is $0 - and that single legitimate zero let
        # ACORD 131 ship Employee Benefits Liability limits of $0/$0/$0 for a
        # coverage this policy does not carry.
        facts = {"dec_page_entries": [
            {"label": "Self-Insured Retention", "value": "$0"}]}
        mapped = {"ExcessUmbrella_EmployeeBenefits_LimitAmount_A": "$0"}
        ps._enforce_numeric_meaning_gate(mapped, self.SCHEMA, facts, set(mapped))
        assert mapped["ExcessUmbrella_EmployeeBenefits_LimitAmount_A"] is None

    def test_a_zero_stated_for_THAT_kind_of_figure_still_fills(self):
        facts = {"dec_page_entries": [
            {"label": "Employee Benefits Limit", "value": "$0"}]}
        mapped = {"ExcessUmbrella_EmployeeBenefits_LimitAmount_A": "$0"}
        ps._enforce_numeric_meaning_gate(mapped, self.SCHEMA, facts, set(mapped))
        assert mapped["ExcessUmbrella_EmployeeBenefits_LimitAmount_A"] == "$0"


class TestExpiredTermIsAboutWhoSaidIt:
    """The Orbin package never says "renewal", so gating the expired-term hard
    stop on `is_renewal` alone would have fixed nothing. What actually matters
    is whether a HUMAN proposed the term or the pipeline copied it off an
    uploaded carrier document."""

    def _past(self, days=40):
        from datetime import datetime, timedelta
        return (datetime.now() - timedelta(days=days)).strftime("%m/%d/%Y")

    def test_dates_read_off_a_document_are_a_warning_not_a_hard_stop(self):
        from services.sqs_service import validate_policy_term_not_expired
        # The exact envelope the live run produced.
        facts = {"expiration_date": {"value": self._past(), "confidence": "ai_high",
                                     "source": "ai"}}
        sev, msg = validate_policy_term_not_expired(facts)
        assert sev == "soft"
        assert "uploaded policy document" in msg

    def test_producer_typed_dates_keep_the_hard_stop(self):
        from services.sqs_service import validate_policy_term_not_expired
        facts = {"expiration_date": {"value": self._past(), "confidence": "filled",
                                     "source": "producer"}}
        sev, _msg = validate_policy_term_not_expired(facts)
        assert sev == "hard"

    def test_renewal_wording_is_a_warning_even_when_producer_typed(self):
        from services.sqs_service import validate_policy_term_not_expired
        facts = {"is_renewal": "yes",
                 "expiration_date": {"value": self._past(), "confidence": "filled",
                                     "source": "producer"}}
        sev, msg = validate_policy_term_not_expired(facts)
        assert sev == "soft"
        assert "Renewal" in msg

    def test_the_orbin_run_no_longer_hard_caps_the_package(self):
        from services.sqs_service import evaluate_stops
        facts = {"expiration_date": {"value": "07/15/26", "confidence": "ai_high",
                                     "source": "ai"}}
        hard, soft = evaluate_stops(facts, {})
        assert not any("already expired" in h for h in hard)
        assert any("already expired" in s for s in soft)

    def test_a_future_term_still_raises_nothing(self):
        from datetime import datetime, timedelta
        from services.sqs_service import validate_policy_term_not_expired
        future = (datetime.now() + timedelta(days=200)).strftime("%m/%d/%Y")
        assert validate_policy_term_not_expired(
            {"expiration_date": {"value": future, "source": "ai"}}) is None


class TestCarrierIsPerLine:
    """orbin_ground_truth: EMC Property & Casualty issues the GL part while
    Employers Mutual issues Inland Marine, Auto and Umbrella. One scalar
    carrier cannot be right on every form."""

    def test_each_line_gets_its_own_carrier(self):
        mf = _repaired_facts()
        got = {e["line"]: e.get("carrier") for e in mf["coverage_lines"]}
        assert got["Liability"] == "EMC Property & Casualty Company"
        assert got["Umbrella"] == "EMPLOYERS MUTUAL CASUALTY COMPANY"

    def test_the_gl_form_shows_the_gl_carrier(self):
        facts = {**_repaired_facts(), "_form_id": "ACORD_126"}
        assert _deterministic_map(
            "Insurer_FullName_A", facts) == "EMC Property & Casualty Company"

    def test_the_umbrella_form_shows_the_umbrella_carrier(self):
        facts = {**_repaired_facts(), "_form_id": "ACORD_131"}
        assert _deterministic_map(
            "Insurer_FullName_A", facts) == "EMPLOYERS MUTUAL CASUALTY COMPANY"

    def test_naic_stays_blank_because_the_package_never_prints_one(self):
        # Ground truth: "no NAIC number is printed anywhere in all 271 pages".
        # The client's 25186 / 21415 are industry knowledge, NOT in the source -
        # so any NAIC on these forms was fabricated, and blank is the only
        # correct answer.
        for form_id in ("ACORD_126", "ACORD_131", "ACORD_127"):
            facts = {**_repaired_facts(), "_form_id": form_id,
                     "carrier_naic": "25186"}
            assert _deterministic_map("Insurer_NAICCode_A", facts) is None


class TestIntraDocumentLimitConflict:

    def test_two_different_umbrella_limits_withhold_the_stamped_value(self):
        mf = {"umbrella_limit": "$3,000,000"}
        es._flag_intra_document_limit_conflicts(
            mf, {"umbrella_limit": ["$3,000,000", "$1,000,000"]})
        assert mf.get("_uw_conflicted_keys") == ["umbrella_limit"]

    def test_one_amount_in_two_spellings_is_not_a_conflict(self):
        mf = {"umbrella_limit": "$3,000,000"}
        es._flag_intra_document_limit_conflicts(
            mf, {"umbrella_limit": ["$ 3,000,000", "3000000"]})
        assert not mf.get("_uw_conflicted_keys")

    def test_no_rivals_means_no_withhold(self):
        mf = {"umbrella_limit": "$3,000,000"}
        es._flag_intra_document_limit_conflicts(mf, {})
        assert not mf.get("_uw_conflicted_keys")

    def test_a_withheld_limit_stamps_blank_on_the_form(self):
        from services.alias_stamper import _ALIAS_MAPS, CANONICAL_TO_EXTRACTION
        fields = [f for f, c in (_ALIAS_MAPS.get("ACORD_131") or {}).items()
                  if CANONICAL_TO_EXTRACTION.get(c) == "umbrella_limit"]
        assert fields
        facts = {"umbrella_limit": "$3,000,000", "_form_id": "ACORD_131",
                 "_uw_conflicted_keys": ["umbrella_limit"]}
        for f in fields:
            assert _deterministic_map(f, facts) is None


class TestRepeatedValueAcrossRows:
    """ACORD 25 shipped the identical carrier in five INSURER slots."""

    def test_one_name_in_two_spellings_is_caught(self):
        # The live ACORD 25: row A carried the merge winner in CAPS while gap
        # fill wrote title case into C-F reading the same carrier off the same
        # document. Five INSURER slots, one insurer.
        import json
        schema = json.load(open("forms_schemas/ACORD_25_schema.json", encoding="utf-8"))
        mapped = {
            "Insurer_FullName_A": "EMPLOYERS MUTUAL CASUALTY COMPANY",
            "Insurer_FullName_C": "Employers Mutual Casualty Company",
            "Insurer_FullName_D": "Employers  Mutual, Casualty Company",
        }
        ps._enforce_post_fill_guards(mapped, schema, {}, set(mapped))
        assert mapped["Insurer_FullName_A"] == "EMPLOYERS MUTUAL CASUALTY COMPANY"
        assert mapped["Insurer_FullName_C"] is None
        assert mapped["Insurer_FullName_D"] is None

    def test_two_genuinely_different_insurers_both_survive(self):
        # ORBIN REALLY HAS TWO. EMC Property & Casualty (GL) and Employers
        # Mutual Casualty (IM/Auto/Umbrella) must BOTH be listable - collapsing
        # them would hide a real second carrier from a certificate holder.
        import json
        schema = json.load(open("forms_schemas/ACORD_25_schema.json", encoding="utf-8"))
        mapped = {
            "Insurer_FullName_A": "EMC Property & Casualty Company",
            "Insurer_FullName_B": "Employers Mutual Casualty Company",
        }
        ps._enforce_post_fill_guards(mapped, schema, {}, set(mapped))
        assert mapped["Insurer_FullName_B"] == "Employers Mutual Casualty Company"

    def test_the_key_treats_formatting_as_formatting(self):
        assert ps._same_value_key("EMC Property & Casualty Co.") == \
               ps._same_value_key("emc property  casualty co")
        assert ps._same_value_key("EMC Property") != ps._same_value_key("Employers Mutual")


class TestDecEntryFallbackForPolicyNumber:
    """Live 2026-08-15: ACORD 25's Umbrella row printed 6J7-40-02---26 (from gap
    fill reading raw text) while ACORD 131's OWN header shipped blank, because
    `coverage_lines` could not attribute the number and the deterministic path
    had no second source. The verified dec entries had it the whole time."""

    ENTRIES = [
        {"label": "Policy Number", "value": "6J7-40-02---26",
         "policy_number": "6J7-40-02---26",
         "section": "COMMERCIAL UMBRELLA DECLARATIONS", "owner": "policy"},
        {"label": "Policy Number", "value": "6E7-40-02---26",
         "policy_number": "6E7-40-02---26",
         "section": "BUSINESS AUTO DECLARATIONS", "owner": "policy"},
    ]

    def _facts(self, form_id):
        # coverage_lines deliberately USELESS - the same number on every line,
        # exactly the live shape - so only the entries can answer.
        return {
            "coverage_lines": [
                {"line": "Umbrella", "policy_number": "6C7-40-02---26"},
                {"line": "Automobile", "policy_number": "6C7-40-02---26"},
            ],
            "dec_page_entries": [dict(e) for e in self.ENTRIES],
            "_form_id": form_id,
        }

    def test_the_umbrella_form_finds_its_own_number(self):
        assert _deterministic_map(
            "Policy_PolicyNumberIdentifier_A", self._facts("ACORD_131")
        ) == "6J7-40-02---26"

    def test_the_auto_form_finds_its_own_number(self):
        assert _deterministic_map(
            "Policy_PolicyNumberIdentifier_A", self._facts("ACORD_127")
        ) == "6E7-40-02---26"

    def test_a_line_the_entries_do_not_name_stays_blank(self):
        assert _deterministic_map(
            "Policy_PolicyNumberIdentifier_A", self._facts("ACORD_130")) is None

    def test_two_numbers_for_one_line_stay_blank_rather_than_guess(self):
        f = self._facts("ACORD_131")
        f["dec_page_entries"].append(
            {"label": "Policy Number", "value": "6X9-99-99---26",
             "policy_number": "6X9-99-99---26",
             "section": "COMMERCIAL UMBRELLA DECLARATIONS", "owner": "policy"})
        assert _deterministic_map("Policy_PolicyNumberIdentifier_A", f) is None

    def test_no_entries_means_no_invention(self):
        f = self._facts("ACORD_131")
        f["dec_page_entries"] = []
        assert _deterministic_map("Policy_PolicyNumberIdentifier_A", f) is None
