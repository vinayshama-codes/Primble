"""Client 2026-08-17 items 1 and 2: false conflicts, and insurance context.

Every fixture uses the client's LITERAL values, or the literal values produced
by the four probe uploads (sessions fd1dcf66 / 14ee33d1 / 2cf0e39e / 3bf00996),
per the standing replay-client-report-verbatim rule.

THE GATE ON THE WHOLE ARC is ``TestTheUmbrellaConflictSurvives``. Killing false
conflicts too hard would kill the one conflict the client praised, so if those
tests do not pass, nothing here ships.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

import pytest                                                     # noqa: E402

from services.fact_equivalence import (                           # noqa: E402
    SAME, DIFFERENT, INCOMPARABLE, PackageContext, equivalent_index,
    fact_line, is_prose, money_amounts, names_a_foreign_line, same_fact,
    value_kind,
)


# ── The client's four literal examples ───────────────────────────────────────

@pytest.mark.parametrize("field,a,b", [
    ("gl_aggregate",          "$2,000,000", "$2,000,000 General Aggregate"),
    ("gl_each_occurrence",    "$1,000,000", "$1,000,000 Each Occurrence"),
    ("gl_products_aggregate", "$2,000,000",
     "$2,000,000 Products & Completed Operations Aggregate"),
    ("physical_address", "4800 DAHLIA ST # D13, DENVER, CO 80216-3121",
     "Denver, Colorado"),
])
def test_the_clients_four_examples_are_no_longer_conflicts(field, a, b):
    assert same_fact(field, a, b) == SAME
    assert same_fact(field, b, a) == SAME, "must not depend on document order"


# ── THE GATE ─────────────────────────────────────────────────────────────────

class TestTheUmbrellaConflictSurvives:
    """$3,000,000 (dec page) vs $1,000,000 (COI) is a REAL disagreement about a
    legal limit. Round 13 got it firing live for the first time and the client
    called it out as correct. Every rule added on 2026-08-17 must leave it
    alone."""

    def test_pure_value_test(self):
        assert same_fact("umbrella_limit", "$3,000,000", "$1,000,000") == DIFFERENT

    def test_survives_the_group_filter(self):
        assert equivalent_index("umbrella_limit",
                                ["$3,000,000", "$1,000,000"], None) is None

    def test_survives_even_with_full_package_context(self):
        ctx = PackageContext({"dec_page_entries": [
            {"label": "Each Occurrence Limit", "value": "$3,000,000",
             "line_of_business": "Commercial Umbrella",
             "policy_number": "6J7-40-02---26"},
            {"label": "Policy Number", "value": "BBC7263-26",
             "line_of_business": "General Liability",
             "policy_number": "BBC7263-26"},
        ]})
        assert ctx.is_multi_contract
        assert equivalent_index("umbrella_limit",
                                ["$3,000,000", "$1,000,000"], ctx) is None

    def test_no_rule_merges_two_different_amounts_on_any_money_field(self):
        for field in ("gl_aggregate", "gl_each_occurrence", "total_revenue",
                      "property_building_value", "auto_liability_limit",
                      "umbrella_limit", "cyber_limit", "total_payroll"):
            assert same_fact(field, "$1,000,000", "$2,000,000") == DIFFERENT
            assert same_fact(field, "$0", "$1,000") == DIFFERENT


@pytest.mark.parametrize("field,a,b", [
    ("umbrella_limit",   "$3,000,000", "$1,000,000"),
    ("gl_aggregate",     "$2,000,000", "$3,000,000"),
    ("total_revenue",    "$1,500,000", "$2,400,000"),
    ("num_employees",    "47", "62"),
    ("applicant_name",   "ORBIN CONTRACTING LLC", "ORBIN CONTRACTING INC"),
    ("physical_address", "Denver, Colorado", "Aurora, Colorado"),
    ("effective_date",   "07/15/2025", "09/01/2025"),
    ("policy_number",    "BBC7263-26", "6E7-40-02---26"),
    ("carrier_name",     "EMC Property & Casualty Company",
     "Employers Mutual Casualty Company"),
])
def test_genuine_differences_are_never_silenced(field, a, b):
    assert same_fact(field, a, b) == DIFFERENT


# ── The eight equivalence families found by the 2026-08-17 sweep ─────────────

@pytest.mark.parametrize("field,a,b", [
    # money + words (the client-reported family)
    ("gl_aggregate",         "$2,000,000", "$2,000,000 (any one premises)"),
    ("gl_fire_damage_limit", "$100,000",   "$100,000 any one fire"),
    ("cyber_limit",          "$500,000",   "$500,000 per claim"),
    ("umbrella_limit",       "$3,000,000", "USD 3,000,000.00"),
    ("umbrella_limit",       "$3,000,000", "3M"),
    ("gl_aggregate",         "$2,000,000", "$2,000,000."),
    ("total_payroll",        "$620,000",   "620,000 dollars"),
    ("total_revenue",        "$1,500,000", "$ 1,500,000"),
    # contact formats
    ("producer_phone",       "303-996-7800", "3039967800"),
    ("contact_phone",        "303-996-7800", "303-996-7800 x212"),
    ("applicant_website",    "orbin.com",    "www.orbin.com"),
    ("applicant_website",    "orbin.com",    "https://orbin.com"),
    ("contact_email",        "Sam@Orbin.com", "sam@orbin.com"),
    # dates, including a field whose key does NOT end in _date
    ("effective_date",       "07/15/2025", "7/15/25"),
    ("effective_date",       "07/15/2025", "July 15, 2025"),
    ("policy_period",        "07/15/2025", "7/15/25"),
    # yes / no
    ("hired_auto_indicator", "Yes", "Y"),
    ("hired_auto_indicator", "Yes", "true"),
    # code + printed description, and a code LIST
    ("gl_class_code",        "91580", "91580 Contractors - Executive Supervisors"),
    ("naics_code",           "238160", "238160 Roofing Contractors"),
    ("auto_covered_symbols", "1, 7", "01/07"),
    # number + unit, percent, abbreviation, entity spelling, address shapes
    ("auto_radius_of_operation", "50", "50 miles"),
    ("num_employees",        "47", "47 full-time"),
    ("percent_subcontracted", "30%", "30"),
    ("mailing_state",        "CO", "Colorado"),
    ("valuation_method",     "RCV", "Replacement Cost"),
    ("applicant_name",       "ORBIN CONTRACTING LLC", "Orbin Contracting, L.L.C."),
    ("carrier_name",         "EMC Property & Casualty Company",
     "EMC Property and Casualty Co"),
    ("mailing_address",      "4800 Dahlia Street", "4800 Dahlia St"),
    ("mailing_address",      "4800 Dahlia St # D13", "4800 Dahlia St Ste D13"),
    ("policy_number",        "BBC7263-26", "BBC7263 - 26"),
    ("policy_number",        "6C7-40-02---26", "6 C 7 - 4 0 - 0 2---26"),
    ("contractor_type",      "Commercial roofing contractor", "Commercia"),
])
def test_equivalence_families(field, a, b):
    assert same_fact(field, a, b) == SAME, f"{field}: {a!r} vs {b!r}"


# ── The guards that keep the rules from over-reaching ────────────────────────

class TestGuards:
    def test_a_composite_amount_is_never_flattened(self):
        assert len(money_amounts("$1,000,000 / $2,000,000")) == 2
        assert same_fact("gl_limits", "$1,000,000 / $2,000,000",
                         "$1,000,000") == DIFFERENT

    def test_a_real_orbin_table_row_is_a_composite(self):
        """Verbatim from the Orbin dec index - one row carrying a row number, a
        limit AND a premium. Reading it as one amount would merge unrelated
        cells, so the money rule must see MORE THAN ONE and stand down."""
        assert len(money_amounts("02 $ 5,000 EACH INSURED . 35.00")) > 1

    def test_a_code_prefix_needs_a_word_boundary(self):
        """91580 and 915801 are different class codes at different rates."""
        assert same_fact("gl_class_code", "91580", "915801") == DIFFERENT

    def test_a_fragment_matching_two_hosts_is_not_merged(self):
        """"Denver, Colorado" sits inside BOTH street addresses. That is not
        evidence the two streets are one place - the fragment stays put and the
        genuine two-address conflict survives."""
        assert equivalent_index("physical_address", [
            "4800 Dahlia St, Denver, CO 80216",
            "900 Elm St, Denver, CO 80202",
            "Denver, Colorado",
        ]) is None

    def test_a_fragment_matching_exactly_one_host_does_merge(self):
        assert equivalent_index("physical_address", [
            "4800 Dahlia St, Denver, CO 80216", "Denver, Colorado",
        ]) is not None

    def test_prose_is_incomparable_not_different(self):
        a = ("The Commercial Umbrella limit under policy 6J7-40-02---26 was "
             "reduced from $3,000,000 to $1,000,000 effective 07/25/2025. "
             "General Liability policy BBC7263-26 remains in force through "
             "07/15/2026 with a general aggregate of $2,000,000.")
        b = ("Loss history: the insured reports two claims in the prior five "
             "years. A water damage claim dated 03/14/2023 was paid at $18,400 "
             "and is closed. The insured confirms no subsidiaries.")
        assert is_prose(a) and is_prose(b)
        assert same_fact("additional_remarks_text", a, b) == INCOMPARABLE
        assert equivalent_index("additional_remarks_text", [a, b]) == {1: 0}

    def test_a_short_free_text_value_is_still_comparable(self):
        """The prose floor must not swallow ordinary field values."""
        assert not is_prose("Commercial roofing contractor performing "
                            "re-roofing and repair on commercial structures")


# ── Client item 2: insurance context ─────────────────────────────────────────

class TestForeignLineValues:
    def test_the_clients_literal_case(self):
        assert names_a_foreign_line("gl_form_type", "BUSINESS AUTO COVERAGE FORM")
        assert not names_a_foreign_line("gl_form_type",
                                        "Commercial General Liability")

    def test_a_legal_value_naming_no_line_is_untouched(self):
        for v in ("Occurrence", "Claims-Made"):
            assert not names_a_foreign_line("gl_form_type", v)

    def test_package_level_facts_have_no_line_and_are_never_filtered(self):
        """ACORD 125/101 are deliberately absent from the section-form table, so
        these are package-level. Filtering them on a line they do not have would
        blank correct values."""
        for k in ("policy_number", "effective_date", "expiration_date",
                  "total_revenue", "applicant_name"):
            assert fact_line(k) is None
            assert not names_a_foreign_line(k, "BUSINESS AUTO COVERAGE FORM")

    def test_a_carrier_name_containing_a_coverage_word_is_never_dropped(self):
        """REGRESSION, caught by the suite on 2026-08-17. The first cut derived
        a line for `carrier_name` (its forms are 125 + 126) and then read the
        word "Property" inside "EMC Property & Casualty Company" as the Property
        line - deleting a real carrier and killing Round 10's conflict. Two
        independent guards now prevent it; this pins both."""
        assert fact_line("carrier_name") is None                 # guard 1
        for v in ("EMC Property & Casualty Company",
                  "Employers Mutual Casualty Company",
                  "Great American Umbrella Insurance Co",
                  "Ohio Casualty Marine Group"):
            assert not names_a_foreign_line("carrier_name", v)   # guard 1
            assert not names_a_foreign_line("applicant_name", v) # guard 2
        assert not names_a_foreign_line("mailing_address",
                                        "12 Marine Parkway, Denver CO")

    def test_the_rule_is_symmetric_across_lines(self):
        assert names_a_foreign_line("auto_liability_limit",
                                    "Commercial General Liability")
        assert not names_a_foreign_line("umbrella_limit", "$3,000,000")

    def test_an_amount_never_names_a_line(self):
        for k in ("gl_aggregate", "auto_liability_limit", "wc_payroll"):
            for v in ("$1,000,000", "2,000,000", "$0"):
                assert not names_a_foreign_line(k, v)


class TestPackageContext:
    ENTRIES = [
        {"label": "General Liability Policy Number", "value": "BBC7263-26",
         "policy_number": "BBC7263-26", "line_of_business": "General Liability"},
        {"label": "General Liability Premium", "value": "$6,720",
         "policy_number": "BBC7263-26", "line_of_business": "General Liability"},
        {"label": "Commercial Auto Policy Number", "value": "6E7-40-02---26",
         "policy_number": "6E7-40-02---26", "line_of_business": "Commercial Auto"},
        {"label": "Commercial Auto Premium", "value": "$2,991",
         "policy_number": "6E7-40-02---26", "line_of_business": "Commercial Auto"},
        {"label": "Total Policy Premium", "value": "$10,663",
         "policy_number": None, "line_of_business": None},
    ]

    def _ctx(self):
        return PackageContext({"dec_page_entries": self.ENTRIES})

    def test_multi_contract_is_detected(self):
        assert self._ctx().is_multi_contract

    def test_two_policy_numbers_from_two_contracts_are_not_a_conflict(self):
        assert equivalent_index("policy_number",
                                ["BBC7263-26", "6E7-40-02---26"],
                                self._ctx()) is not None

    def test_an_umbrella_limit_is_not_a_component_of_anything(self):
        """REGRESSION. The first cut asked only "is this line-attributed?", so
        the umbrella's own $3,000,000 counted as a "component" and merged with
        the COI's $1,000,000 - silently destroying the gate conflict. Evidence
        is now required on BOTH sides."""
        ctx = self._ctx()
        assert not ctx.is_component_of("$3,000,000", "$1,000,000")
        assert not ctx.is_component_of("$1,000,000", "$3,000,000")

    def test_a_line_premium_is_a_component_of_the_package_total(self):
        """Probe run C: $10,663 is the package total, $2,991 the Commercial Auto
        line premium, printed on the same page. One is part of the other."""
        assert self._ctx().is_component_of("$2,991", "$10,663")
        assert equivalent_index("total_policy_premium",
                                ["$10,663", "$2,991"], self._ctx()) is not None

    def test_two_printings_of_one_contract_join(self):
        assert self._ctx().same_contract_printing("6E7-40-02---26", "6E74002")

    def test_an_unrelated_number_does_not_join(self):
        assert not self._ctx().same_contract_printing("BBC7263-26", "6E74002")

    def test_no_index_means_no_opinion(self):
        """A package with no dec index behaves exactly as it does today."""
        empty = PackageContext({}, [])
        assert not empty.is_multi_contract
        assert not empty.different_owners("BBC7263-26", "6E7-40-02---26")
        assert not empty.is_component_of("$2,991", "$10,663")
        assert equivalent_index("policy_number",
                                ["BBC7263-26", "6E7-40-02---26"], empty) is None


# ── Structural properties of the filter ──────────────────────────────────────

class TestTheFilterCanOnlyRemoveConflicts:
    def test_it_never_splits_a_group(self):
        assert equivalent_index("gl_aggregate", ["$2,000,000"]) is None

    def test_empty_values_are_incomparable_never_different(self):
        assert same_fact("gl_aggregate", "", "$1,000,000") == INCOMPARABLE
        assert same_fact("gl_aggregate", None, None) == INCOMPARABLE

    def test_a_missing_field_key_does_not_raise(self):
        for bad in (None, "", "   "):
            equivalent_index(bad, ["a", "b"])
            same_fact(bad, "a", "b")


class TestValueKindDerivation:
    @pytest.mark.parametrize("key,expected", [
        ("gl_aggregate", "money"), ("total_revenue", "money"),
        ("num_employees", "count"), ("percent_subcontracted", "percent"),
        ("effective_date", "date"), ("fein", "fein"),
        ("producer_phone", "phone"), ("applicant_website", "url"),
        ("contact_email", "email"), ("applicant_name", "name"),
        ("carrier_name", "name"), ("mailing_address", "address"),
        ("policy_number", "identifier"), ("gl_class_code", "code"),
        ("naics_code", "code"), ("mailing_state", "state"),
        ("additional_remarks_text", "narrative"),
        ("operations_description", "narrative"),
        ("hired_auto_indicator", "yesno"),
    ])
    def test_kinds(self, key, expected):
        assert value_kind(key) == expected

    def test_policy_number_is_an_identifier_not_a_count(self):
        """"number" was in the count-token set, so policy_number classified as a
        count and its OCR-spacing and short-printing pairs both failed the
        sweep. Pinned so it cannot come back."""
        assert value_kind("policy_number") == "identifier"
        assert value_kind("certificate_number") == "identifier"
        assert value_kind("num_employees") == "count"

    def test_every_currency_fact_in_the_registry_types_as_money(self):
        """ANTI-ROT. 51 facts declare _is_currency. One that does not resolve to
        money is being compared as TEXT, which is the original defect."""
        from services.fact_registry import FACT_REGISTRY
        misses = [
            k for k, v in FACT_REGISTRY.items()
            if getattr(v.get("validate"), "__name__", "") == "_is_currency"
            and value_kind(k) != "money"
        ]
        assert not misses, f"currency facts compared as text: {misses}"
