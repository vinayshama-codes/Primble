# The REMAINING issues from the 2026-08-15 relationship-preservation audit,
# fixed at the root (client Tuesday deliverable, second pass).
#
# EVERY end-to-end test here drives the REAL map_facts_to_form /
# compute_form_gaps with the REAL form schemas and the client's literal Orbin
# values - never `_deterministic_map` alone. That lesson is now paid for twice:
# the ACORD 131 header date was CORRECT at resolver level and wrong on the
# paper, because the umbrella-period override sat between the resolver and the
# stamp. A test that stops at the resolver proves nothing about the form.
#
# The five fixes under test:
#   1. The ACORD 131 umbrella-period override yields to a routed renewal's
#      derived term unless the umbrella's own term verifiably has not ended.
#   2. Guard 2 de-duplicates repeating rows against ALL earlier rows, not row A
#      only (live: INSURER E duplicated INSURER B on the certificate).
#   3. The ACORD 131 UNDERLYING INSURANCE grid is line-scoped-or-blank: each
#      named row from its OWN coverage line, Other Policy rows never fabricated
#      from package scalars (live: the AUTO number paired with the DERIVED
#      renewal dates - an underlying policy record no document prints).
#   4. Coverage a document DECLARES absent ("Workers' Compensation ... No
#      Coverage") suppresses that family's fields everywhere except ACORD 130,
#      which is an application FOR workers comp.
#   5. Producer-assigned certificate identifiers are owned blanks (live: the
#      AUTO policy number in the CERTIFICATE NUMBER box), and a single-letter
#      fragment in a name field is rejected (live: a driver named "E").

import json
import os
import re

import pytest

from services import pdf_service as P
from services.pdf_service import _SCHED_SKIP

_SCHEMA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "forms_schemas")
_SCHEMA_CACHE = {}


def _schema(form_id):
    if form_id not in _SCHEMA_CACHE:
        with open(os.path.join(_SCHEMA_DIR, f"{form_id}_schema.json"),
                  encoding="utf-8") as fh:
            _SCHEMA_CACHE[form_id] = json.load(fh)
    return _SCHEMA_CACHE[form_id]


@pytest.fixture(autouse=True)
def _no_umbrella_probe(monkeypatch):
    """The umbrella-period probe is a live LLM call; tests must be offline and
    deterministic. Facts set umbrella_* directly where a test needs them."""
    monkeypatch.setattr(P, "_fetch_umbrella_period_sync", lambda raw_text: None)


# The client's literal Orbin package shape: four granted lines, two carriers,
# and Workers' Compensation printed as "No Coverage" on the premium table.
def _orbin_lines():
    return [
        {"line": "Workers Compensation", "premium": "No Coverage"},
        {"line": "Inland Marine", "policy_number": "6C7-40-02---26",
         "carrier": "Employers Mutual Casualty Company", "premium": "$300.00",
         "effective_date": "07/15/2025", "expiration_date": "07/15/2026"},
        {"line": "Business Auto", "policy_number": "6E7-40-02---26",
         "carrier": "Employers Mutual Casualty Company", "premium": "$2,991.00",
         "effective_date": "07/15/2025", "expiration_date": "07/15/2026"},
        {"line": "Commercial Liability Umbrella", "policy_number": "6J7-40-02---26",
         "carrier": "Employers Mutual Casualty Company", "premium": "$3,418.00",
         "effective_date": "07/15/2025", "expiration_date": "07/15/2026"},
        {"line": "General Liability", "policy_number": "BBC7263",
         "carrier": "EMC Property & Casualty Company", "premium": "$3,954.00",
         "effective_date": "07/15/2025", "expiration_date": "07/15/2026"},
    ]


def _routed_renewal_facts(**overrides):
    """Facts as merge_facts leaves them AFTER renewal routing on Orbin: the
    expiring term moved to prior_*, the proposed term DERIVED."""
    facts = {
        "is_renewal": {"value": "yes"},
        "renewal_dates_routed": True,
        "effective_date": {"value": "07/15/2026", "confidence": "low_confidence",
                           "source": "derived"},
        "expiration_date": {"value": "07/15/2027", "confidence": "low_confidence",
                            "source": "derived"},
        "prior_effective_date": {"value": "07/15/2025"},
        "prior_expiration_date": {"value": "07/15/2026"},
        "policy_number": {"value": "6E7-40-02---26"},
        "carrier_name": {"value": "Employers Mutual Casualty Company"},
        "coverage_lines": _orbin_lines(),
    }
    facts.update(overrides)
    return facts


_RAW = ("COMMERCIAL UMBRELLA DECLARATIONS. POLICY PERIOD: FROM 07/15/25 TO "
        "07/15/26. ORBIN CONTRACTING LLC, 4800 DAHLIA ST # D13. "
        "EMPLOYERS MUTUAL CASUALTY COMPANY. EMC Property & Casualty Company. "
        "Policy 6E7-40-02---26. Policy 6C7-40-02---26. BBC7263.")


def _env(values):
    """The combined-gap-fill envelope map_facts_to_form actually consumes.

    EVERY map_facts_to_form call in this file passes one (empty when the test
    injects nothing): the combined path is the production path, and omitting it
    routes map_facts_to_form onto the legacy per-form branch, which fires LIVE
    LLM calls - non-deterministic, billable, and a several-minute hang when a
    real API key is configured.
    """
    return {"filled_values": dict(values), "raw_text_fields": set(),
            "question_grounding": {}}


# ── Fix 1: the umbrella-period override vs the routed renewal ────────────────

class TestUmbrellaOverrideRenewalGate:
    def test_131_header_date_is_the_derived_term_not_the_expiring_probe_date(self):
        # The client's literal defect: ACORD 131 printed 07/15/2025 (the
        # expiring term) while 125/127 printed the derived 07/15/2026 - the
        # override re-imported the expiring term through a third door.
        facts = _routed_renewal_facts(
            umbrella_effective_date={"value": "07/15/2025"},
            umbrella_expiration_date={"value": "07/15/2026"},
        )
        mapped, _ = P.map_facts_to_form(facts, _schema("ACORD_131"),
                                        form_id="ACORD_131", raw_text=_RAW,
                                        pre_filled_gpt=_env({}))
        assert mapped.get("Policy_EffectiveDate_A") == "07/15/2026"

    def test_umbrella_own_period_still_wins_when_not_a_renewal(self):
        # The override exists for a reason - an umbrella genuinely runs its own
        # period. A non-renewal must keep the original behaviour byte-for-byte.
        facts = _routed_renewal_facts(
            umbrella_effective_date={"value": "08/01/2025"},
            umbrella_expiration_date={"value": "08/01/2026"},
        )
        del facts["renewal_dates_routed"]
        facts["effective_date"] = {"value": "07/15/2025"}
        mapped, _ = P.map_facts_to_form(facts, _schema("ACORD_131"),
                                        form_id="ACORD_131", raw_text=_RAW,
                                        pre_filled_gpt=_env({}))
        assert mapped.get("Policy_EffectiveDate_A") == "08/01/2025"

    def test_umbrella_future_term_still_wins_on_a_routed_renewal(self):
        # A FUTURE-dated umbrella term on a renewal is plausibly the real
        # renewal umbrella dec - that evidence outranks the derived date.
        facts = _routed_renewal_facts(
            umbrella_effective_date={"value": "08/01/2026"},
            umbrella_expiration_date={"value": "08/01/2027"},
        )
        mapped, _ = P.map_facts_to_form(facts, _schema("ACORD_131"),
                                        form_id="ACORD_131", raw_text=_RAW,
                                        pre_filled_gpt=_env({}))
        assert mapped.get("Policy_EffectiveDate_A") == "08/01/2026"

    def test_acord_25_certificate_keeps_the_existing_policy_dates(self):
        # Certificates document the EXISTING policy: the 25's excess-liability
        # row must keep the umbrella's own (expiring) dates even on a routed
        # renewal - the same exemption _resolve_renewal_proposed_period has.
        facts = _routed_renewal_facts(
            umbrella_effective_date={"value": "07/15/2025"},
            umbrella_expiration_date={"value": "07/15/2026"},
        )
        mapped, _ = P.map_facts_to_form(facts, _schema("ACORD_25"),
                                        form_id="ACORD_25", raw_text=_RAW,
                                        pre_filled_gpt=_env({}))
        assert mapped.get("Policy_ExcessLiability_EffectiveDate_A") == "07/15/2025"
        assert mapped.get("Policy_ExcessLiability_ExpirationDate_A") == "07/15/2026"


# ── Fix 2: Guard 2 de-duplicates against every earlier row ───────────────────

class TestPairwiseRowDedup:
    def test_insurer_duplicate_between_two_non_a_rows_collapses(self):
        # Live 2026-08-15: INSURER E duplicated INSURER B. Row-A-only
        # comparison could not see it. Legacy facts (no coverage_lines) keep
        # the insurer slots gap-fillable, which is how the duplicate arrived.
        facts = {"policy_number": {"value": "6E7-40-02---26"},
                 "carrier_name": {"value": "Employers Mutual Casualty Company"}}
        mapped, _ = P.map_facts_to_form(
            facts, _schema("ACORD_25"), form_id="ACORD_25", raw_text=_RAW,
            pre_filled_gpt=_env({
                "Insurer_FullName_B": "EMC PROPERTY & CASUALTY COMPANY",
                "Insurer_FullName_E": "Emc Property & Casualty Company",
            }))
        # B keeps the value (first occurrence); E - a formatting variant of the
        # SAME carrier - is blanked.
        assert P._same_value_key(mapped.get("Insurer_FullName_B")) == \
            P._same_value_key("EMC Property & Casualty Company")
        assert mapped.get("Insurer_FullName_E") is None

    def test_two_genuinely_different_insurers_in_non_a_rows_both_survive(self):
        facts = {"policy_number": {"value": "6E7-40-02---26"},
                 "carrier_name": {"value": "Employers Mutual Casualty Company"}}
        raw = _RAW + " Fictional Different Insurer Co."
        mapped, _ = P.map_facts_to_form(
            facts, _schema("ACORD_25"), form_id="ACORD_25", raw_text=raw,
            pre_filled_gpt=_env({
                "Insurer_FullName_B": "EMC PROPERTY & CASUALTY COMPANY",
                "Insurer_FullName_E": "Fictional Different Insurer Co",
            }))
        assert mapped.get("Insurer_FullName_B") is not None
        assert mapped.get("Insurer_FullName_E") is not None

    def test_duplicate_of_row_a_still_collapses(self):
        # The original behaviour must survive the generalization.
        facts = {"policy_number": {"value": "6E7-40-02---26"},
                 "carrier_name": {"value": "Employers Mutual Casualty Company"}}
        mapped, _ = P.map_facts_to_form(
            facts, _schema("ACORD_25"), form_id="ACORD_25", raw_text=_RAW,
            pre_filled_gpt=_env({
                "Insurer_FullName_C": "EMPLOYERS MUTUAL CASUALTY COMPANY",
            }))
        assert mapped.get("Insurer_FullName_A") is not None
        assert mapped.get("Insurer_FullName_C") is None

    def test_pairwise_dedup_is_scoped_to_name_fields_only(self):
        # C18's asymmetry: a wrongly DELETED value is invisible; a wrongly
        # repeated one gets fixed by the broker. Repeat-prone data columns
        # that are not schedule-registry-bound (garaging city on a fleet)
        # must gain NO new deletion surface from the pairwise change: a
        # B==C repeat (rows beyond A agreeing with each other) survives
        # exactly as it always did.
        schema = {"Vehicle_PhysicalAddress_CityName_A": {"ft": "/Tx", "tu": "city"},
                  "Vehicle_PhysicalAddress_CityName_B": {"ft": "/Tx", "tu": "city"},
                  "Vehicle_PhysicalAddress_CityName_C": {"ft": "/Tx", "tu": "city"}}
        mapped = {"Vehicle_PhysicalAddress_CityName_A": "Denver",
                  "Vehicle_PhysicalAddress_CityName_B": "Boulder",
                  "Vehicle_PhysicalAddress_CityName_C": "Boulder"}
        P._enforce_post_fill_guards(mapped, schema, {})
        assert mapped["Vehicle_PhysicalAddress_CityName_B"] == "Boulder"
        assert mapped["Vehicle_PhysicalAddress_CityName_C"] == "Boulder"

    def test_schedule_registry_fields_stay_fully_exempt(self):
        # Registry-bound schedule columns may repeat any value in any row -
        # two vehicles genuinely share a model year.
        schema = {"Vehicle_ModelYear_A": {"ft": "/Tx", "tu": "year"},
                  "Vehicle_ModelYear_B": {"ft": "/Tx", "tu": "year"}}
        mapped = {"Vehicle_ModelYear_A": "2012", "Vehicle_ModelYear_B": "2012"}
        P._enforce_post_fill_guards(mapped, schema, {})
        assert mapped["Vehicle_ModelYear_B"] == "2012"


# ── Fix 3: the ACORD 131 underlying-policy grid ──────────────────────────────

class TestUnderlyingPolicyGrid:
    def test_named_rows_pair_from_their_own_lines(self):
        facts = _routed_renewal_facts()
        mapped, _ = P.map_facts_to_form(facts, _schema("ACORD_131"),
                                        form_id="ACORD_131", raw_text=_RAW,
                                        pre_filled_gpt=_env({}))
        assert mapped.get("UnderlyingPolicy_Automobile_PolicyNumberIdentifier_A") == \
            "6E7-40-02---26"
        assert P._same_value_key(mapped.get("UnderlyingPolicy_Automobile_InsurerFullName_A")) == \
            P._same_value_key("Employers Mutual Casualty Company")
        # The underlying policy's OWN term - never the derived proposed term.
        assert mapped.get("UnderlyingPolicy_Automobile_PolicyEffectiveDate_A") == "07/15/2025"
        assert mapped.get("UnderlyingPolicy_Automobile_PolicyExpirationDate_A") == "07/15/2026"
        assert mapped.get("UnderlyingPolicy_GeneralLiability_PolicyNumberIdentifier_A") == \
            "BBC7263"
        assert P._same_value_key(mapped.get("UnderlyingPolicy_GeneralLiability_InsurerFullName_A")) == \
            P._same_value_key("EMC Property & Casualty Company")

    def test_otherpolicy_rows_never_fabricate_a_pairing(self):
        # THE live defect: gap fill stamped the AUTO policy number next to the
        # DERIVED 07/15/2026-07/15/2027 dates in an Other Policy row - an
        # underlying policy record printed by no document. The rows are owned
        # blanks, and injected values must not survive.
        facts = _routed_renewal_facts()
        mapped, _ = P.map_facts_to_form(
            facts, _schema("ACORD_131"), form_id="ACORD_131", raw_text=_RAW,
            pre_filled_gpt=_env({
                "UnderlyingPolicy_OtherPolicy_PolicyNumberIdentifier_A": "6E7-40-02---26",
                "UnderlyingPolicy_OtherPolicy_PolicyEffectiveDate_A": "07/15/2026",
                "UnderlyingPolicy_OtherPolicy_PolicyExpirationDate_A": "07/15/2027",
                "UnderlyingPolicy_OtherPolicy_InsurerFullName_A": "Employers Mutual Casualty Company",
            }))
        for f in ("UnderlyingPolicy_OtherPolicy_PolicyNumberIdentifier_A",
                  "UnderlyingPolicy_OtherPolicy_PolicyEffectiveDate_A",
                  "UnderlyingPolicy_OtherPolicy_PolicyExpirationDate_A",
                  "UnderlyingPolicy_OtherPolicy_InsurerFullName_A"):
            assert mapped.get(f) is None, f

    def test_underlying_grid_is_excluded_from_gap_fill(self):
        # The model is never even ASKED about the grid when per-line evidence
        # exists - suppression at the question, not the answer.
        facts = _routed_renewal_facts()
        _, unmatched, _ = P.compute_form_gaps("ACORD_131", _schema("ACORD_131"), facts)
        leaked = [f for f in unmatched if P._UNDERLYING_POLICY_RE.match(f)]
        assert leaked == []

    def test_legacy_sessions_without_coverage_lines_are_unchanged(self):
        # No per-line evidence at all -> the resolver must SKIP so the legacy
        # scalar path behaves byte-identically for old sessions.
        facts = {"_form_id": "ACORD_131", "policy_number": {"value": "6E7-40-02---26"}}
        r = P._resolve_underlying_policy_row(
            "UnderlyingPolicy_OtherPolicy_PolicyNumberIdentifier_A", facts)
        assert r is _SCHED_SKIP

    def test_a_line_absent_from_the_evidence_stays_blank(self):
        # Orbin schedules only GL and Auto as underlying. A package whose
        # coverage_lines carries no EL line must leave the EL row blank rather
        # than borrow a neighbour's identity.
        facts = _routed_renewal_facts()
        facts["coverage_lines"] = [e for e in facts["coverage_lines"]
                                   if e["line"] != "Workers Compensation"]
        r = P._resolve_underlying_policy_row(
            "UnderlyingPolicy_EmployersLiability_PolicyNumberIdentifier_A", facts)
        assert r is None


# ── Fix 4: declared-absent coverage suppresses its field family ──────────────

class TestDeclaredAbsentCoverage:
    def test_el_row_and_wc_limits_blank_on_131_when_wc_is_no_coverage(self):
        facts = _routed_renewal_facts()
        mapped, _ = P.map_facts_to_form(
            facts, _schema("ACORD_131"), form_id="ACORD_131", raw_text=_RAW,
            pre_filled_gpt=_env({
                "UnderlyingPolicy_EmployersLiability_PolicyNumberIdentifier_A": "6E7-40-02---26",
                "WorkersCompensationEmployersLiability_EmployersLiability_EachAccidentLimitAmount_A": "$1,000,000",
                "WorkersCompensationEmployersLiability_EmployersLiability_DiseaseEachEmployeeLimitAmount_A": "$1,000,000",
            }))
        assert mapped.get("UnderlyingPolicy_EmployersLiability_PolicyNumberIdentifier_A") is None
        assert mapped.get("WorkersCompensationEmployersLiability_EmployersLiability_EachAccidentLimitAmount_A") is None
        assert mapped.get("WorkersCompensationEmployersLiability_EmployersLiability_DiseaseEachEmployeeLimitAmount_A") is None

    def test_wc_row_blank_on_the_certificate_when_wc_is_no_coverage(self):
        # The live ACORD 25 carried a fully-populated WC row - dates and three
        # EL limits - on a package whose premium table prints "No Coverage".
        facts = _routed_renewal_facts()
        mapped, _ = P.map_facts_to_form(
            facts, _schema("ACORD_25"), form_id="ACORD_25", raw_text=_RAW,
            pre_filled_gpt=_env({
                "Policy_WorkersCompensationAndEmployersLiability_EffectiveDate_A": "07/15/2025",
                "Policy_WorkersCompensationAndEmployersLiability_ExpirationDate_A": "07/15/2026",
                "WorkersCompensationEmployersLiability_EmployersLiability_EachAccidentLimitAmount_A": "$1,000,000",
            }))
        assert mapped.get("Policy_WorkersCompensationAndEmployersLiability_EffectiveDate_A") is None
        assert mapped.get("Policy_WorkersCompensationAndEmployersLiability_ExpirationDate_A") is None
        assert mapped.get("WorkersCompensationEmployersLiability_EmployersLiability_EachAccidentLimitAmount_A") is None

    def test_wc_family_is_excluded_from_gap_fill_when_declared_absent(self):
        facts = _routed_renewal_facts()
        _, unmatched, _ = P.compute_form_gaps("ACORD_25", _schema("ACORD_25"), facts)
        leaked = [f for f in unmatched
                  if f.startswith(("WorkersCompensationEmployersLiability_",
                                   "Policy_WorkersCompensation"))]
        assert leaked == []

    def test_acord_130_is_exempt_it_applies_FOR_workers_comp(self):
        # An application for WC coverage exists precisely because the current
        # package has none - suppression there would blank the whole form.
        facts = dict(_routed_renewal_facts(), _form_id="ACORD_130")
        r = P._resolve_declared_absent_line_row(
            "WorkersCompensationEmployersLiability_EmployersLiability_EachAccidentLimitAmount_A",
            facts)
        assert r is _SCHED_SKIP

    def test_a_granted_wc_entry_defeats_the_denial(self):
        # A client may upload a NEW WC quote alongside a package that dropped
        # WC. A granted entry for the line must defeat the denial entry.
        facts = _routed_renewal_facts()
        facts["coverage_lines"] = facts["coverage_lines"] + [
            {"line": "Workers Compensation", "policy_number": "WC-999",
             "carrier": "Pinnacol Assurance", "premium": "$5,000.00"}]
        assert P._line_declared_absent(
            facts, ("workers compensation", "employers liability")) is False
        r = P._resolve_declared_absent_line_row(
            "WorkersCompensationEmployersLiability_EmployersLiability_EachAccidentLimitAmount_A",
            dict(facts, _form_id="ACORD_25"))
        assert r is _SCHED_SKIP

    def test_absence_of_any_wc_entry_is_not_evidence(self):
        # No entry at all is silence, not a denial - suppressing on silence
        # would delete a coverage the extractor merely missed.
        facts = _routed_renewal_facts()
        facts["coverage_lines"] = [e for e in facts["coverage_lines"]
                                   if e["line"] != "Workers Compensation"]
        assert P._line_declared_absent(
            facts, ("workers compensation", "employers liability")) is False


# ── Fix 5: certificate identifiers + name fragments ──────────────────────────

class TestCertificateAndNameFragments:
    def test_certificate_number_is_never_a_policy_number(self):
        # Live: the CERTIFICATE NUMBER box shipped the AUTO policy number. The
        # tooltip reads "the producer assigned number for the certificate" - no
        # uploaded document can state it.
        facts = _routed_renewal_facts()
        mapped, _ = P.map_facts_to_form(
            facts, _schema("ACORD_25"), form_id="ACORD_25", raw_text=_RAW,
            pre_filled_gpt=_env({
                "CertificateOfInsurance_CertificateNumberIdentifier_A": "6E7-40-02---26",
            }))
        assert mapped.get("CertificateOfInsurance_CertificateNumberIdentifier_A") is None

    def test_certificate_number_excluded_from_gap_fill(self):
        facts = _routed_renewal_facts()
        _, unmatched, _ = P.compute_form_gaps("ACORD_25", _schema("ACORD_25"), facts)
        assert "CertificateOfInsurance_CertificateNumberIdentifier_A" not in unmatched

    def test_a_producer_supplied_certificate_number_still_stamps(self):
        # The ownership is "not extractable", not "never fillable": a dedicated
        # fact (producer-supplied) must flow through.
        facts = dict(_routed_renewal_facts(),
                     certificate_number={"value": "CRS-2026-0042"})
        mapped, _ = P.map_facts_to_form(facts, _schema("ACORD_25"),
                                        form_id="ACORD_25", raw_text=_RAW,
                                        pre_filled_gpt=_env({}))
        assert mapped.get("CertificateOfInsurance_CertificateNumberIdentifier_A") == \
            "CRS-2026-0042"

    def test_single_letter_name_fragment_is_blanked(self):
        # Live: ACORD 127 printed a driver named "E" on a package with NO
        # driver schedule. Name-family fields that are still gap-fillable
        # reject a one-letter fragment.
        facts = {"policy_number": {"value": "6E7-40-02---26"},
                 "carrier_name": {"value": "Employers Mutual Casualty Company"}}
        mapped, _ = P.map_facts_to_form(
            facts, _schema("ACORD_25"), form_id="ACORD_25", raw_text=_RAW + " E.",
            pre_filled_gpt=_env({"Insurer_FullName_B": "E"}))
        assert mapped.get("Insurer_FullName_B") is None

    def test_initial_fields_legitimately_keep_one_letter_on_a_named_row(self):
        # The fragment guard exempts Initial fields - but only a NAMED driver
        # row keeps its cells at all (Guard 2b). Without a driver schedule the
        # name columns are owned blanks, so a "named row" can only come from a
        # real schedule - guard-level is where the keep-semantics live.
        mapped = {"Driver_GivenName_A": "Erin",
                  "Driver_OtherGivenNameInitial_A": "E",
                  "Driver_MailingAddress_CityName_A": "Denver"}
        P._enforce_post_fill_guards(
            mapped,
            {"Driver_GivenName_A": {"ft": "/Tx"},
             "Driver_OtherGivenNameInitial_A": {"ft": "/Tx"},
             "Driver_MailingAddress_CityName_A": {"ft": "/Tx"}}, {})
        assert mapped["Driver_GivenName_A"] == "Erin"
        assert mapped["Driver_OtherGivenNameInitial_A"] == "E"
        assert mapped["Driver_MailingAddress_CityName_A"] == "Denver"

    def test_driver_identity_columns_stay_owned_blank_without_a_schedule(self):
        # Discovered while fixing: with no auto_driver_schedule fact the driver
        # identity columns are ALREADY authoritative blanks - the phantom "E"
        # driver cannot recur through the ask-the-model path. Pin it.
        facts = {"policy_number": {"value": "6E7-40-02---26"}}
        _, unmatched, det = P.compute_form_gaps("ACORD_127", _schema("ACORD_127"), facts)
        assert "Driver_GivenName_A" not in unmatched
        assert "Driver_GivenName_A" in det


# ── ROUND 6: defects the FRESH run of 2026-08-15 proved live ─────────────────
# The live merge names lines the way the PACKAGE prints them - the premium
# table's bare "Liability" - and RULE 16 drops denied lines from
# coverage_lines entirely, so the Workers' Compensation denial survives only
# as a dec-page entry. Both shapes broke round-5 behavior on the real run.

def _live_shaped_lines():
    """coverage_lines as the LIVE run carries them: bare premium-table names,
    the GL part additionally present under its own name, and NO WC row."""
    return [
        {"line": "Property", "premium": None},
        {"line": "Liability", "premium": "$3,954.00",
         "carrier": "Employers Mutual Casualty Company",
         "effective_date": "07/15/2025", "expiration_date": "07/15/2026"},
        {"line": "General Liability", "premium": "$3,954.00",
         "carrier": "EMC Property & Casualty Company", "policy_number": "BBC7263",
         "effective_date": "07/15/2025", "expiration_date": "07/15/2026"},
        {"line": "Automobile", "premium": "$2,991.00",
         "carrier": "Employers Mutual Casualty Company",
         "effective_date": "07/15/2025", "expiration_date": "07/15/2026"},
        {"line": "Umbrella", "premium": "$3,418.00", "policy_number": "6J7-40-02---26",
         "carrier": "Employers Mutual Casualty Company",
         "effective_date": "07/15/2025", "expiration_date": "07/15/2026"},
        {"line": "Inland Marine", "premium": "$300.00",
         "carrier": "Employers Mutual Casualty Company", "policy_number": "6C7-40-02---26",
         "effective_date": "07/15/2025", "expiration_date": "07/15/2026"},
    ]


_WC_DENIAL_ENTRY = {"label": "Workers' Compensation", "value": "No Coverage",
                    "owner": "carrier"}


class TestBareGenericLineNames:
    def test_bare_liability_line_cannot_fill_the_el_row(self):
        # THE fresh-run defect: the EL underlying row printed the Liability
        # row's carrier and dates because "Liability" satisfied the phrases
        # ("workers compensation", "employers liability") by token subset.
        facts = _routed_renewal_facts(coverage_lines=_live_shaped_lines())
        mapped, _ = P.map_facts_to_form(
            facts, _schema("ACORD_131"), form_id="ACORD_131", raw_text=_RAW,
            pre_filled_gpt=_env({}))
        for f in ("UnderlyingPolicy_EmployersLiability_InsurerFullName_A",
                  "UnderlyingPolicy_EmployersLiability_PolicyEffectiveDate_A",
                  "UnderlyingPolicy_EmployersLiability_PolicyExpirationDate_A",
                  "UnderlyingPolicy_EmployersLiability_PolicyNumberIdentifier_A"):
            assert mapped.get(f) is None, f

    def test_auto_and_gl_rows_still_fill_from_bare_line_names(self):
        # The canon classifier places "Automobile" and "Liability"; specific
        # rows must keep working on the live naming.
        facts = _routed_renewal_facts(coverage_lines=_live_shaped_lines())
        mapped, _ = P.map_facts_to_form(
            facts, _schema("ACORD_131"), form_id="ACORD_131", raw_text=_RAW,
            pre_filled_gpt=_env({}))
        assert P._same_value_key(mapped.get("UnderlyingPolicy_Automobile_InsurerFullName_A")) == \
            P._same_value_key("Employers Mutual Casualty Company")
        # Two liability-classed entries carry two different carriers - the GL
        # carrier is ambiguous and must stay blank; the policy number is
        # stated by exactly one of them and fills.
        assert mapped.get("UnderlyingPolicy_GeneralLiability_InsurerFullName_A") is None
        assert mapped.get("UnderlyingPolicy_GeneralLiability_PolicyNumberIdentifier_A") == "BBC7263"


class TestDenialRecordedOnlyInDecEntries:
    def test_dec_entry_denial_alone_suppresses_the_wc_family(self):
        # RULE 16 keeps denied lines OUT of coverage_lines, so on the live run
        # the only denial evidence is the premium-table dec entry. The 25's WC
        # row and the 131 EL limits must still suppress from that alone.
        facts = _routed_renewal_facts(coverage_lines=_live_shaped_lines(),
                                      dec_page_entries=[_WC_DENIAL_ENTRY])
        mapped25, _ = P.map_facts_to_form(
            facts, _schema("ACORD_25"), form_id="ACORD_25", raw_text=_RAW,
            pre_filled_gpt=_env({
                "Policy_WorkersCompensationAndEmployersLiability_EffectiveDate_A": "07/15/2025",
                "WorkersCompensationEmployersLiability_EmployersLiability_EachAccidentLimitAmount_A": "$1,000,000",
            }))
        assert mapped25.get("Policy_WorkersCompensationAndEmployersLiability_EffectiveDate_A") is None
        assert mapped25.get("WorkersCompensationEmployersLiability_EmployersLiability_EachAccidentLimitAmount_A") is None
        mapped131, _ = P.map_facts_to_form(
            facts, _schema("ACORD_131"), form_id="ACORD_131", raw_text=_RAW,
            pre_filled_gpt=_env({
                "WorkersCompensationEmployersLiability_EmployersLiability_DiseaseEachEmployeeLimitAmount_A": "$1,000,000",
            }))
        assert mapped131.get("WorkersCompensationEmployersLiability_EmployersLiability_DiseaseEachEmployeeLimitAmount_A") is None

    def test_granted_wc_line_still_defeats_a_dec_entry_denial(self):
        facts = _routed_renewal_facts(
            coverage_lines=_live_shaped_lines() + [
                {"line": "Workers Compensation", "policy_number": "WC-999",
                 "carrier": "Pinnacol Assurance", "premium": "$5,000.00"}],
            dec_page_entries=[_WC_DENIAL_ENTRY])
        assert P._line_declared_absent(
            facts, ("workers compensation", "employers liability")) is False

    def test_a_non_wc_dec_entry_denial_does_not_suppress_wc(self):
        # "Property: No Coverage" must not blank the WC family.
        facts = _routed_renewal_facts(
            coverage_lines=_live_shaped_lines(),
            dec_page_entries=[{"label": "Property", "value": "No Coverage",
                               "owner": "carrier"}])
        assert P._line_declared_absent(
            facts, ("workers compensation", "employers liability")) is False


class TestSmallDollarMeaningGate:
    def test_a_dollar_marked_small_figure_is_gated(self):
        # Fresh run: "$34" - the umbrella's TRIA terrorism premium - stamped
        # into FOREIGN GROSS SALES. The old unconditional amt<100 skip waved
        # every small figure past the gate.
        facts = _routed_renewal_facts(
            dec_page_entries=[{"label": "Terrorism Premium (Certified Acts)",
                               "value": "$34.00", "owner": "carrier"}])
        mapped, _ = P.map_facts_to_form(
            facts, _schema("ACORD_131"), form_id="ACORD_131",
            raw_text=_RAW + " Terrorism Premium (Certified Acts) $34.00.",
            pre_filled_gpt=_env({"BusinessInformation_ForeignGrossSalesAmount_A": "$34"}))
        assert mapped.get("BusinessInformation_ForeignGrossSalesAmount_A") is None

    def test_a_bare_small_count_still_skips_the_gate(self):
        # Counts and percent-shaped noise (no dollar marker) stay out of scope.
        schema = {"BusinessInformation_FullTimeEmployeeCount_A":
                  {"ft": "/Tx", "tu": "Enter amount: employees"}}
        mapped = {"BusinessInformation_FullTimeEmployeeCount_A": "34"}
        facts = {"dec_page_entries": [{"label": "Terrorism Premium",
                                       "value": "$34.00", "owner": "carrier"}]}
        P._enforce_numeric_meaning_gate(
            mapped, schema, facts, {"BusinessInformation_FullTimeEmployeeCount_A"})
        assert mapped["BusinessInformation_FullTimeEmployeeCount_A"] == "34"


class TestCertificateOtherRow:
    def test_other_row_documents_the_leftover_line_with_its_own_term(self):
        # Fresh run: the OTHER row paired the IM number 6C7-40-02---26 with
        # the DERIVED 07/15/2026-07/15/2027 dates and a fabricated SUBR "Y".
        # The one leftover granted line (Inland Marine) owns the row with its
        # OWN in-force term; the waiver and limit cells never fabricate.
        facts = _routed_renewal_facts()      # canonical Orbin lines incl. IM
        mapped, _ = P.map_facts_to_form(
            facts, _schema("ACORD_25"), form_id="ACORD_25", raw_text=_RAW,
            pre_filled_gpt=_env({
                "OtherPolicy_PolicyEffectiveDate_A": "07/15/2026",
                "OtherPolicy_PolicyExpirationDate_A": "07/15/2027",
                "OtherPolicy_SubrogationWaivedCode_A": "Y",
                "OtherPolicy_CoverageLimitAmount_A": "$3,000,000",
            }))
        assert mapped.get("OtherPolicy_PolicyNumberIdentifier_A") == "6C7-40-02---26"
        assert mapped.get("OtherPolicy_PolicyEffectiveDate_A") == "07/15/2025"
        assert mapped.get("OtherPolicy_PolicyExpirationDate_A") == "07/15/2026"
        assert mapped.get("OtherPolicy_OtherPolicyDescription_A") == "Inland Marine"
        assert mapped.get("OtherPolicy_SubrogationWaivedCode_A") is None
        assert mapped.get("OtherPolicy_CoverageLimitAmount_A") is None

    def test_other_row_blank_when_several_leftover_lines_compete(self):
        facts = _routed_renewal_facts()
        facts["coverage_lines"] = facts["coverage_lines"] + [
            {"line": "Property", "policy_number": "PROP-1",
             "carrier": "Employers Mutual Casualty Company", "premium": "$1,000.00"}]
        for f in ("OtherPolicy_PolicyNumberIdentifier_A",
                  "OtherPolicy_PolicyEffectiveDate_A",
                  "OtherPolicy_OtherPolicyDescription_A"):
            assert P._resolve_certificate_other_row(f, dict(facts, _form_id="ACORD_25")) is None

    def test_other_row_legacy_sessions_unchanged(self):
        facts = {"_form_id": "ACORD_25", "policy_number": {"value": "6E7-40-02---26"}}
        assert P._resolve_certificate_other_row(
            "OtherPolicy_PolicyNumberIdentifier_A", facts) is _SCHED_SKIP


# ── ROUND 7: the third fresh run's remaining root causes ─────────────────────

def _third_run_lines():
    """The live shape that kept WC/EL content alive: bare names, no WC row,
    and a REQUIREMENT-shaped Employers Liability entry - a carrier name beside
    required limits, with no premium and no policy number (the umbrella's
    schedule-of-underlying-requirements wording, emitted as a line)."""
    return [
        {"line": "Liability", "premium": "$3,954.00",
         "carrier": "Employers Mutual Casualty Company",
         "effective_date": "07/15/2025", "expiration_date": "07/15/2026"},
        {"line": "General Liability", "premium": "$3,954.00",
         "carrier": "EMC Property & Casualty Company", "policy_number": "BBC7263",
         "effective_date": "07/15/2025", "expiration_date": "07/15/2026"},
        {"line": "Automobile", "premium": "$2,991.00",
         "carrier": "Employers Mutual Casualty Company",
         "effective_date": "07/15/2025", "expiration_date": "07/15/2026"},
        {"line": "Umbrella", "premium": "$3,418.00", "policy_number": "6J7-40-02---26",
         "carrier": "Employers Mutual Casualty Company",
         "effective_date": "07/15/2025", "expiration_date": "07/15/2026"},
        {"line": "Inland Marine", "premium": "$300.00",
         "carrier": "Employers Mutual Casualty Company", "policy_number": "6C7-40-02---26",
         "effective_date": "07/15/2025", "expiration_date": "07/15/2026"},
        {"line": "Employers Liability",
         "carrier": "Employers Mutual Casualty Company", "limit": "$1,000,000"},
    ]


class TestRequirementShapedEntries:
    def test_a_limits_only_el_entry_cannot_fill_the_el_row(self):
        # Third fresh run: EL row printed the carrier + $1M limits from an
        # entry with no premium and no policy number. A mention, not a policy.
        facts = _routed_renewal_facts(coverage_lines=_third_run_lines())
        mapped, _ = P.map_facts_to_form(
            facts, _schema("ACORD_131"), form_id="ACORD_131", raw_text=_RAW,
            pre_filled_gpt=_env({
                "WorkersCompensationEmployersLiability_EmployersLiability_EachAccidentLimitAmount_A": "$1,000,000",
            }))
        assert mapped.get("UnderlyingPolicy_EmployersLiability_InsurerFullName_A") is None
        assert mapped.get("UnderlyingPolicy_EmployersLiability_PolicyEffectiveDate_A") is None
        assert mapped.get("WorkersCompensationEmployersLiability_EmployersLiability_EachAccidentLimitAmount_A") is None

    def test_the_wc_row_on_the_certificate_dies_with_it(self):
        facts = _routed_renewal_facts(coverage_lines=_third_run_lines())
        mapped, _ = P.map_facts_to_form(
            facts, _schema("ACORD_25"), form_id="ACORD_25", raw_text=_RAW,
            pre_filled_gpt=_env({
                "Policy_WorkersCompensationAndEmployersLiability_EffectiveDate_A": "07/15/2025",
                "WorkersCompensationEmployersLiability_EmployersLiability_DiseasePolicyLimitAmount_A": "$1,000,000",
            }))
        assert mapped.get("Policy_WorkersCompensationAndEmployersLiability_EffectiveDate_A") is None
        assert mapped.get("WorkersCompensationEmployersLiability_EmployersLiability_DiseasePolicyLimitAmount_A") is None

    def test_a_premium_carrying_wc_policy_still_flows(self):
        facts = _routed_renewal_facts(
            coverage_lines=_third_run_lines() + [
                {"line": "Workers Compensation", "policy_number": "WC-999",
                 "carrier": "Pinnacol Assurance", "premium": "$5,000.00"}])
        r = P._resolve_declared_absent_line_row(
            "WorkersCompensationEmployersLiability_EmployersLiability_EachAccidentLimitAmount_A",
            dict(facts, _form_id="ACORD_25"))
        assert r is _SCHED_SKIP

    def test_a_thin_inventory_suppresses_nothing(self):
        # One granted line is not a coverage census.
        facts = _routed_renewal_facts(coverage_lines=[_third_run_lines()[0]])
        assert P._line_absent_from_package(
            facts, ("workers compensation", "employers liability")) is False


class TestEblAndModOwnership:
    def test_ebl_family_blank_when_the_package_carries_no_ebl(self):
        # Third fresh run: NAME OF BENEFIT PROGRAM = "Business Auto Coverage
        # Form"; earlier runs filled the EBL block with the GL limits.
        facts = _routed_renewal_facts(coverage_lines=_third_run_lines())
        mapped, _ = P.map_facts_to_form(
            facts, _schema("ACORD_131"), form_id="ACORD_131", raw_text=_RAW,
            pre_filled_gpt=_env({
                "ExcessUmbrella_EmployeeBenefits_ProgramName_A": "Business Auto Coverage Form",
                "ExcessUmbrella_EmployeeBenefits_EachEmployeeLimitAmount_A": "$1,000,000",
            }))
        assert mapped.get("ExcessUmbrella_EmployeeBenefits_ProgramName_A") is None
        assert mapped.get("ExcessUmbrella_EmployeeBenefits_EachEmployeeLimitAmount_A") is None

    def test_modification_factor_is_owned_blank(self):
        facts = _routed_renewal_facts(coverage_lines=_third_run_lines())
        mapped, _ = P.map_facts_to_form(
            facts, _schema("ACORD_131"), form_id="ACORD_131", raw_text=_RAW,
            pre_filled_gpt=_env({
                "UnderlyingPolicy_GeneralLiability_ModificationFactor_A": "33.211",
                "UnderlyingPolicy_OtherPolicy_ModificationFactor_A": "$500",
            }))
        assert mapped.get("UnderlyingPolicy_GeneralLiability_ModificationFactor_A") is None
        assert mapped.get("UnderlyingPolicy_OtherPolicy_ModificationFactor_A") is None


class TestDependentRowsWithoutTheirTrigger:
    def test_watercraft_rows_and_tail_date_blank_without_a_yes(self):
        facts = _routed_renewal_facts(coverage_lines=_third_run_lines())
        mapped, _ = P.map_facts_to_form(
            facts, _schema("ACORD_131"), form_id="ACORD_131", raw_text=_RAW,
            pre_filled_gpt=_env({
                "Watercraft_OwnedCount_A": "1", "Watercraft_Length_A": "2012",
                "Watercraft_Horsepower_A": "26680",
                "UnderlyingPolicy_GeneralLiability_TailCoverageEffectiveDate_A": "07/15/2026",
                "ExcessUmbrella_ProposedRetroactiveDate_A": "07/15/2025",
                "ExcessUmbrella_CurrentRetroactiveDate_A": "07/15/2025",
            }))
        for f in ("Watercraft_OwnedCount_A", "Watercraft_Length_A", "Watercraft_Horsepower_A",
                  "UnderlyingPolicy_GeneralLiability_TailCoverageEffectiveDate_A",
                  "ExcessUmbrella_ProposedRetroactiveDate_A",
                  "ExcessUmbrella_CurrentRetroactiveDate_A"):
            assert mapped.get(f) is None, f

    def test_an_affirmative_claims_made_election_keeps_its_retro_date(self):
        # Guard-level: end-to-end an UNGROUNDED claims-made "Yes" dies at the
        # evidence gate and its dependents rightly follow; a genuine election
        # keeps them.
        mapped = {"ExcessUmbrella_ClaimsMadeIndicator_A": "Yes",
                  "ExcessUmbrella_ProposedRetroactiveDate_A": "07/15/2025"}
        P._enforce_post_fill_guards(
            mapped,
            {"ExcessUmbrella_ClaimsMadeIndicator_A": {"ft": "/Btn"},
             "ExcessUmbrella_ProposedRetroactiveDate_A": {"ft": "/Tx"}}, {})
        assert mapped["ExcessUmbrella_ProposedRetroactiveDate_A"] == "07/15/2025"


class TestFactWitnessesAndValueCategory:
    def test_the_package_total_premium_cannot_become_gross_sales(self):
        # Third fresh run: ANN GROSS SALES = $10,663 - the package total this
        # pipeline itself reconciled. Facts are witnesses now.
        facts = _routed_renewal_facts(coverage_lines=_third_run_lines(),
                                      total_policy_premium={"value": "$10,663.00"})
        mapped, _ = P.map_facts_to_form(
            facts, _schema("ACORD_131"), form_id="ACORD_131",
            raw_text=_RAW + " $10,663.00.",
            pre_filled_gpt=_env({"BusinessInformation_AnnualGrossSalesAmount_A": "$10,663"}))
        assert mapped.get("BusinessInformation_AnnualGrossSalesAmount_A") is None

    def test_a_line_premium_cannot_become_a_property_value(self):
        # Third fresh run: CARE, CUSTODY, CONTROL VALUE = $300, the IM premium.
        facts = _routed_renewal_facts(coverage_lines=_third_run_lines())
        mapped, _ = P.map_facts_to_form(
            facts, _schema("ACORD_131"), form_id="ACORD_131",
            raw_text=_RAW + " $300.00.",
            pre_filled_gpt=_env({"CareCustodyAndControl_Property_ValueAmount_A": "$300"}))
        assert mapped.get("CareCustodyAndControl_Property_ValueAmount_A") is None


class TestTelematicsSubFields:
    def test_q17_sub_fields_blank_without_a_yes(self):
        # Fourth fresh run: Q17 blank, yet "100%" monitored, "Virus and
        # Hacking" and "NAMES OF INDIVIDUALS ERIN ROYAL" in the sub-fields.
        facts = _routed_renewal_facts(coverage_lines=_third_run_lines())
        mapped, _ = P.map_facts_to_form(
            facts, _schema("ACORD_127"), form_id="ACORD_127",
            raw_text=_RAW + " 100% Virus and Hacking NAMES OF INDIVIDUALS ERIN ROYAL.",
            pre_filled_gpt=_env({
                "CommercialVehicleLineOfBusiness_ElectronicDataMonitoringDevice_FleetMonitoredPercent_A": "100%",
                "CommercialVehicleLineOfBusiness_ElectronicDataMonitoringDevice_AdditionalDescription_A":
                    "NAMES OF INDIVIDUALS ERIN ROYAL",
                "CommercialVehicleLineOfBusiness_ElectronicDataMonitoringDevice_OtherDesciption_A":
                    "Virus and Hacking",
            }))
        for f in ("CommercialVehicleLineOfBusiness_ElectronicDataMonitoringDevice_FleetMonitoredPercent_A",
                  "CommercialVehicleLineOfBusiness_ElectronicDataMonitoringDevice_AdditionalDescription_A",
                  "CommercialVehicleLineOfBusiness_ElectronicDataMonitoringDevice_OtherDesciption_A"):
            assert mapped.get(f) is None, f

    def test_a_yes_keeps_the_sub_fields(self):
        mapped = {"CommercialVehicleLineOfBusiness_KAHCode_A": "Y",
                  "CommercialVehicleLineOfBusiness_ElectronicDataMonitoringDevice_FleetMonitoredPercent_A": "100%"}
        P._enforce_post_fill_guards(
            mapped,
            {"CommercialVehicleLineOfBusiness_KAHCode_A": {"ft": "/Tx"},
             "CommercialVehicleLineOfBusiness_ElectronicDataMonitoringDevice_FleetMonitoredPercent_A": {"ft": "/Tx"}},
            {})
        assert mapped["CommercialVehicleLineOfBusiness_ElectronicDataMonitoringDevice_FleetMonitoredPercent_A"] == "100%"


class TestPhantomDriverRowAndInsurerRoster:
    def test_a_driver_row_without_a_name_carries_nothing(self):
        # Third fresh run: "R" + the garaging city printed as driver 1 on a
        # package whose ground truth has NO driver schedule.
        facts = _routed_renewal_facts(coverage_lines=_third_run_lines())
        mapped, _ = P.map_facts_to_form(
            facts, _schema("ACORD_127"), form_id="ACORD_127",
            raw_text=_RAW + " R Denver CO 80216-3121.",
            pre_filled_gpt=_env({
                "Driver_OtherGivenNameInitial_A": "R",
                "Driver_MailingAddress_CityName_A": "Denver",
                "Driver_MailingAddress_StateOrProvinceCode_A": "CO",
            }))
        assert mapped.get("Driver_OtherGivenNameInitial_A") is None
        assert mapped.get("Driver_MailingAddress_CityName_A") is None
        assert mapped.get("Driver_MailingAddress_StateOrProvinceCode_A") is None

    def test_an_unattested_insurer_never_seats_on_the_roster(self):
        # Third fresh run: INSURER E = "Employers Property & Casualty Company",
        # a blend of the two real names - a carrier that does not exist.
        facts = _routed_renewal_facts(coverage_lines=_third_run_lines())
        mapped, _ = P.map_facts_to_form(
            facts, _schema("ACORD_25"), form_id="ACORD_25",
            raw_text=_RAW + " Employers Property & Casualty Company.",
            pre_filled_gpt=_env({
                "Insurer_FullName_C": "Emc Property & Casualty Company",
                "Insurer_FullName_E": "Employers Property & Casualty Company",
            }))
        assert P._same_value_key(mapped.get("Insurer_FullName_C")) == \
            P._same_value_key("EMC Property & Casualty Company")
        assert mapped.get("Insurer_FullName_E") is None


# ── ROUND 8: the independent audit's findings (2026-08-15) ───────────────────

class TestPackageHeaderPairGuard:
    def test_the_clients_recombined_naic_never_stamps(self):
        # Audit #1: Employers Mutual + EMC P&C's 25186 - the client's literal
        # recombination - still stamped on 125/25 via the flat scalars.
        # Pairing is a property of the PAIR, not of the form.
        facts = _routed_renewal_facts(carrier_naic={"value": "25186"})
        for form in ("ACORD_125", "ACORD_25"):
            mapped, _ = P.map_facts_to_form(
                facts, _schema(form), form_id=form, raw_text=_RAW,
                pre_filled_gpt=_env({}))
            assert mapped.get("Insurer_NAICCode_A") is None, form

    def test_an_attested_pair_naic_still_stamps(self):
        lines = _orbin_lines()
        for e in lines:
            if str(e.get("carrier", "")).startswith("Employers"):
                e["naic"] = "21415"
        facts = _routed_renewal_facts(coverage_lines=lines)
        mapped, _ = P.map_facts_to_form(
            facts, _schema("ACORD_125"), form_id="ACORD_125", raw_text=_RAW,
            pre_filled_gpt=_env({}))
        assert mapped.get("Insurer_NAICCode_A") == "21415"

    def test_no_single_package_number_means_a_blank_header(self):
        # Audit #2: the 125 header carried the AUTO number deterministically.
        # Ground truth: five candidates, no package policy number.
        facts = _routed_renewal_facts()
        mapped, _ = P.map_facts_to_form(
            facts, _schema("ACORD_125"), form_id="ACORD_125", raw_text=_RAW,
            pre_filled_gpt=_env({}))
        assert mapped.get("Policy_PolicyNumberIdentifier_A") is None

    def test_a_true_package_number_still_stamps(self):
        lines = [dict(e, policy_number="PKG-001") for e in _orbin_lines()
                 if e.get("premium") not in (None, "No Coverage")]
        facts = _routed_renewal_facts(coverage_lines=lines,
                                      policy_number={"value": "PKG-001"})
        mapped, _ = P.map_facts_to_form(
            facts, _schema("ACORD_125"), form_id="ACORD_125", raw_text=_RAW,
            pre_filled_gpt=_env({}))
        assert mapped.get("Policy_PolicyNumberIdentifier_A") == "PKG-001"

    def test_legacy_sessions_keep_the_scalar_path(self):
        facts = {"_form_id": "ACORD_125", "policy_number": {"value": "6E7-40-02---26"},
                 "carrier_naic": {"value": "21415"}}
        assert P._resolve_package_header_identity(
            "Policy_PolicyNumberIdentifier_A", facts) is _SCHED_SKIP
        assert P._resolve_package_header_identity(
            "Insurer_NAICCode_A", facts) is _SCHED_SKIP


class TestPairedCellsAndLineNames:
    def test_inland_marine_is_not_a_persons_name(self):
        # Audit #3: Guard 3 blanked "Inland Marine" from the Q4 LINE OF
        # BUSINESS cell as "looks like a person's name", stranding the number.
        assert P._rejects_declared_type(
            "OtherPolicy_LineOfBusinessCode_A",
            {"tu": "Enter code: The line of business."}, "Inland Marine") is None
        assert P._rejects_declared_type(
            "OtherPolicy_LineOfBusinessCode_A",
            {"tu": "Enter code: The line of business."}, "Erin Royal") is not None

    def test_a_broken_pair_drops_both_halves(self):
        # Dropping half a relationship must drop the other half.
        schema = {"OtherPolicy_LineOfBusinessCode_A": {"ft": "/Tx"},
                  "OtherPolicy_PolicyNumberIdentifier_A": {"ft": "/Tx"}}
        mapped = {"OtherPolicy_LineOfBusinessCode_A": None,
                  "OtherPolicy_PolicyNumberIdentifier_A": "6C7-40-02---26"}
        P._enforce_post_fill_guards(mapped, schema, {})
        assert mapped["OtherPolicy_PolicyNumberIdentifier_A"] is None

    def test_a_complete_pair_survives(self):
        schema = {"OtherPolicy_LineOfBusinessCode_A": {"ft": "/Tx"},
                  "OtherPolicy_PolicyNumberIdentifier_A": {"ft": "/Tx"}}
        mapped = {"OtherPolicy_LineOfBusinessCode_A": "Inland Marine",
                  "OtherPolicy_PolicyNumberIdentifier_A": "6C7-40-02---26"}
        P._enforce_post_fill_guards(mapped, schema, {})
        assert mapped["OtherPolicy_LineOfBusinessCode_A"] == "Inland Marine"
        assert mapped["OtherPolicy_PolicyNumberIdentifier_A"] == "6C7-40-02---26"


class TestGateWitnessHardening:
    def test_component_premiums_are_witnessed_from_the_schedule(self):
        # Audit #4: page 211's vocabulary defeated the keyword table. A
        # premium COLUMN needs no vocabulary - it is a premium by construction.
        w = P._build_amount_witnesses({"gl_class_code_schedule": [
            {"class_code": "91585", "premium_basis": "Total Cost",
             "exposure_amount": "$350,000", "all_other_premium": "$803"},
            {"class_code": "policy", "gl_elite_extension_premium": "$500"}]})
        assert w.get(500) == {"premium"}
        assert w.get(803) == {"premium"}

    def test_acords_own_prem_abbreviation_categorizes(self):
        assert P._amount_category("All Other Advance Prem") == "premium"

    def test_a_component_premium_cannot_become_a_limit(self):
        facts = _routed_renewal_facts(gl_class_code_schedule=[
            {"class_code": "policy", "gl_elite_extension_premium": "$500"}])
        schema = {"GeneralLiability_OtherCoverageLimitAmount_A":
                  {"ft": "/Tx", "tu": "Enter amount: The limit for the other coverage."}}
        mapped = {"GeneralLiability_OtherCoverageLimitAmount_A": "$500"}
        P._enforce_numeric_meaning_gate(
            mapped, schema, facts, {"GeneralLiability_OtherCoverageLimitAmount_A"})
        assert mapped["GeneralLiability_OtherCoverageLimitAmount_A"] is None


class TestCensusSafety:
    def test_a_two_line_package_suppresses_nothing(self):
        # Audit #5: GL+Auto-only packages are common - two lines and no
        # mention of WC is an inference, not the document's census.
        lines = [e for e in _orbin_lines()
                 if e.get("line") in ("General Liability", "Business Auto")]
        assert P._line_absent_from_package(
            {"coverage_lines": lines},
            ("workers compensation", "employers liability")) is False

    def test_a_producer_answer_defeats_the_census(self):
        facts = _routed_renewal_facts(
            wc_el_each_accident={"value": "$500,000", "source": "producer"})
        r = P._resolve_declared_absent_line_row(
            "WorkersCompensationEmployersLiability_EmployersLiability_EachAccidentLimitAmount_A",
            dict(facts, _form_id="ACORD_25"))
        assert r is _SCHED_SKIP


class TestUnderlyingOtherPolicyLeftover:
    def test_a_real_fourth_underlying_line_fills_the_other_row(self):
        # Audit #6: a legitimate further liability policy - own carrier,
        # number, premium - was unconditionally blanked.
        facts = _routed_renewal_facts(coverage_lines=_orbin_lines() + [
            {"line": "Cyber Liability", "policy_number": "CYB-777",
             "carrier": "Beazley Insurance Company", "premium": "$1,200.00",
             "effective_date": "07/15/2025", "expiration_date": "07/15/2026"}])
        f = dict(facts, _form_id="ACORD_131")
        assert P._resolve_underlying_policy_row(
            "UnderlyingPolicy_OtherPolicy_PolicyNumberIdentifier_A", f) == "CYB-777"
        assert P._resolve_underlying_policy_row(
            "UnderlyingPolicy_OtherPolicy_InsurerFullName_A", f) == \
            "Beazley Insurance Company"
        assert P._resolve_underlying_policy_row(
            "UnderlyingPolicy_OtherPolicy_PolicyEffectiveDate_A", f) == "07/15/2025"

    def test_an_unplaceable_extra_line_keeps_the_row_blank(self):
        facts = _routed_renewal_facts(coverage_lines=_orbin_lines() + [
            {"line": "Builders Risk", "policy_number": "BR-1",
             "carrier": "Somebody", "premium": "$900.00"}])
        f = dict(facts, _form_id="ACORD_131")
        assert P._resolve_underlying_policy_row(
            "UnderlyingPolicy_OtherPolicy_PolicyNumberIdentifier_A", f) is None


class TestPriorTermAtomicity:
    def test_a_partially_known_prior_term_is_never_completed(self):
        # Audit #7: genuine prior_effective_date 07/15/2024 + routing built a
        # 2024-2026 prior term no document states.
        from services import extraction_service as ES
        mf = {"is_renewal": {"value": "yes"},
              "effective_date": {"value": "07/15/2025"},
              "expiration_date": {"value": "07/15/2026"},
              "prior_effective_date": {"value": "07/15/2024"}}
        ES._route_renewal_dates(mf)
        assert mf.get("prior_expiration_date") is None
        assert mf["prior_effective_date"]["value"] == "07/15/2024"

    def test_an_empty_prior_pair_still_routes_together(self):
        from services import extraction_service as ES
        mf = {"is_renewal": {"value": "yes"},
              "effective_date": {"value": "07/15/2025"},
              "expiration_date": {"value": "07/15/2026"}}
        ES._route_renewal_dates(mf)
        assert mf["prior_effective_date"]["value"] == "07/15/2025"
        assert mf["prior_expiration_date"]["value"] == "07/15/2026"


class TestPriorGridFallback:
    def _facts_with_grid(self, grid_term=("07/15/2025", "07/15/2026")):
        lines = [dict(e) for e in _orbin_lines()]
        for e in lines:
            if e.get("line") == "Business Auto":
                e.pop("policy_number", None)
        return _routed_renewal_facts(
            coverage_lines=lines,
            prior_coverage_by_line=[
                {"line": "Automobile", "policy_no": "6E74002",
                 "effective": grid_term[0], "expiration": grid_term[1]}])

    def test_127_header_fills_from_a_term_matched_prior_row(self):
        # Audit ("the real remaining root cause"): 127's header shipped blank
        # while the same number sat in prior_coverage_by_line. On a renewal
        # the expiring policy IS the in-force policy - when the terms match.
        mapped, _ = P.map_facts_to_form(
            self._facts_with_grid(), _schema("ACORD_127"), form_id="ACORD_127",
            raw_text=_RAW, pre_filled_gpt=_env({}))
        assert mapped.get("Policy_PolicyNumberIdentifier_A") == "6E74002"

    def test_a_term_mismatched_prior_row_never_fills_the_header(self):
        # A genuinely OLD policy's number must not stamp as current.
        mapped, _ = P.map_facts_to_form(
            self._facts_with_grid(grid_term=("07/15/2023", "07/15/2024")),
            _schema("ACORD_127"), form_id="ACORD_127",
            raw_text=_RAW, pre_filled_gpt=_env({}))
        assert mapped.get("Policy_PolicyNumberIdentifier_A") is None


# ── ROUND 9: the audit's second pass ─────────────────────────────────────────

def _grid_rows():
    return [
        {"line": "Automobile", "policy_no": "6E74002",
         "carrier": "Employers Mutual Casualty Co",
         "effective": "07/15/2025", "expiration": "07/15/2026"},
        {"line": "General Liability", "policy_no": "BBC7263",
         "carrier": "EMC Property & Casualty Company",
         "effective": "07/15/2025", "expiration": "07/15/2026"},
    ]


class TestNaicRosterRows:
    def test_a_fabricated_naic_on_row_b_dies_and_the_name_survives(self):
        # Round 9's Tuesday-blocker: "077" - not NAIC-shaped, printed nowhere
        # in 271 pages - stamped beside the second real carrier in INSURER B.
        facts = _routed_renewal_facts()
        mapped, _ = P.map_facts_to_form(
            facts, _schema("ACORD_25"), form_id="ACORD_25", raw_text=_RAW,
            pre_filled_gpt=_env({
                "Insurer_FullName_B": "EMC Property & Casualty Company",
                "Insurer_NAICCode_B": "077"}))
        assert mapped.get("Insurer_NAICCode_B") is None
        assert P._same_value_key(mapped.get("Insurer_FullName_B")) == \
            P._same_value_key("EMC Property & Casualty Company")

    def test_rows_beyond_a_are_never_asked_when_carriers_are_evidenced(self):
        facts = _routed_renewal_facts()
        _, unmatched, _ = P.compute_form_gaps("ACORD_25", _schema("ACORD_25"), facts)
        leaked = [f for f in unmatched
                  if re.match(r"^Insurer_NAICCode_[B-Z]$", f)]
        assert leaked == []

    def test_the_guard_kills_a_malformed_naic_even_in_legacy_sessions(self):
        mapped = {"Insurer_FullName_B": "Some Carrier", "Insurer_NAICCode_B": "077"}
        P._enforce_post_fill_guards(
            mapped, {"Insurer_FullName_B": {"ft": "/Tx"},
                     "Insurer_NAICCode_B": {"ft": "/Tx"}}, {})
        assert mapped["Insurer_NAICCode_B"] is None

    def test_a_naic_with_no_carrier_in_its_row_is_unpaired(self):
        mapped = {"Insurer_NAICCode_C": "21415"}
        P._enforce_post_fill_guards(
            mapped, {"Insurer_NAICCode_C": {"ft": "/Tx"}}, {})
        assert mapped["Insurer_NAICCode_C"] is None


class TestSpecialtyLeftoverUnInerted:
    def test_a_liquor_policy_fills_the_131_other_underlying_row(self):
        # Round 9: _canon_line buckets every specialty liability line into
        # general_liab, which made the leftover rule inert. A distinguishing
        # token beyond the generic GL vocabulary marks its own line.
        facts = _routed_renewal_facts(coverage_lines=_orbin_lines() + [
            {"line": "Liquor Liability", "policy_number": "LIQ-5",
             "carrier": "Founders Insurance", "premium": "$800.00",
             "effective_date": "07/15/2025", "expiration_date": "07/15/2026"}])
        f = dict(facts, _form_id="ACORD_131")
        assert P._resolve_underlying_policy_row(
            "UnderlyingPolicy_OtherPolicy_PolicyNumberIdentifier_A", f) == "LIQ-5"

    def test_a_plainly_generic_gl_name_is_not_a_leftover(self):
        leftovers, _ = P._specialty_leftover_lines(
            [{"line": "Commercial General Liability", "premium": "$1.00",
              "policy_number": "GL-1"}], frozenset({"auto"}))
        assert leftovers == []


class TestQ4PriorGridRecovery:
    def test_the_grid_prints_every_policy_with_a_recoverable_number(self):
        # Round 9: "the Q4 grid prints 1 of 4" - lines whose numbers the
        # summary lost recover them from term-matched prior-grid rows.
        lines = [dict(e) for e in _orbin_lines()
                 if e.get("line") != "Workers Compensation"]
        for e in lines:
            if e.get("line") == "Business Auto":
                e.pop("policy_number", None)      # the summary lost it
        facts = _routed_renewal_facts(coverage_lines=lines,
                                      prior_coverage_by_line=_grid_rows())
        f = dict(facts, _form_id="ACORD_125")
        got = {}
        for row in ("A", "B", "C", "D"):
            ln = P._deterministic_map(f"OtherPolicy_LineOfBusinessCode_{row}", f)
            num = P._deterministic_map(f"OtherPolicy_PolicyNumberIdentifier_{row}", f)
            if ln or num:
                got[str(ln)] = str(num)
        assert got.get("Business Auto") == "6E74002"      # recovered, term-matched
        assert got.get("General Liability") == "BBC7263"
        assert got.get("Commercial Liability Umbrella") == "6J7-40-02---26"
        assert got.get("Inland Marine") == "6C7-40-02---26"

    def test_underlying_gl_carrier_rescued_from_the_prior_grid(self):
        # Two liability-classed entries with two carriers used to mean a
        # permanent blank; the term-matched grid row settles it.
        facts = _routed_renewal_facts(
            coverage_lines=_orbin_lines() + [
                {"line": "Liability", "premium": "$3,954.00",
                 "carrier": "Employers Mutual Casualty Company",
                 "effective_date": "07/15/2025", "expiration_date": "07/15/2026"}],
            prior_coverage_by_line=_grid_rows())
        f = dict(facts, _form_id="ACORD_131")
        assert P._same_value_key(P._resolve_underlying_policy_row(
            "UnderlyingPolicy_GeneralLiability_InsurerFullName_A", f)) == \
            P._same_value_key("EMC Property & Casualty Company")


class TestRatingRowBorrows:
    def test_same_row_and_cross_schedule_borrows_are_blanked(self):
        mapped = {"Vehicle_RateClassCode_A": "7383",
                  "Vehicle_RatingTerritoryCode_A": "111",
                  "Vehicle_SpecialIndustryClassCode_A": "91585",
                  "Vehicle_PrimaryLiabilityRatingFactor_A": "7383",
                  "Vehicle_NetRatingFactor_A": "111",
                  "Vehicle_FarthestZoneCode_A": "111"}
        P._enforce_post_fill_guards(
            mapped, {k: {"ft": "/Tx"} for k in mapped},
            {"gl_class_code_schedule": [{"class_code": "91585"}]})
        for f in ("Vehicle_SpecialIndustryClassCode_A",
                  "Vehicle_PrimaryLiabilityRatingFactor_A",
                  "Vehicle_NetRatingFactor_A", "Vehicle_FarthestZoneCode_A"):
            assert mapped[f] is None, f
        assert mapped["Vehicle_RateClassCode_A"] == "7383"
        assert mapped["Vehicle_RatingTerritoryCode_A"] == "111"

    def test_genuine_rating_values_survive(self):
        mapped = {"Vehicle_RateClassCode_A": "7383",
                  "Vehicle_RatingTerritoryCode_A": "111",
                  "Vehicle_SpecialIndustryClassCode_A": "8391",
                  "Vehicle_PrimaryLiabilityRatingFactor_A": "1.25",
                  "Vehicle_FarthestZoneCode_A": "002"}
        P._enforce_post_fill_guards(
            mapped, {k: {"ft": "/Tx"} for k in mapped}, {})
        assert mapped["Vehicle_SpecialIndustryClassCode_A"] == "8391"
        assert mapped["Vehicle_PrimaryLiabilityRatingFactor_A"] == "1.25"
        assert mapped["Vehicle_FarthestZoneCode_A"] == "002"


class TestLabelEchoRows:
    def test_the_forms_own_limit_vocabulary_cannot_occupy_an_other_row(self):
        mapped = {
            "GeneralLiability_OtherCoverageLimitDescription_A": "General Aggregate Limit",
            "GeneralLiability_OtherCoverageLimitAmount_A": "$2,000,000",
            "ExcessUmbrella_OtherCoverageDescription_A": "Commercial Liability Umbrella",
            "ExcessUmbrella_OtherCoverageLimitAmount_A": "$3,000,000",
        }
        P._enforce_post_fill_guards(
            mapped, {k: {"ft": "/Tx"} for k in mapped}, {})
        for f in mapped:
            assert mapped[f] is None, f

    def test_a_genuine_other_coverage_survives(self):
        mapped = {"GeneralLiability_OtherCoverageDescription_A": "Employee Benefits Liability",
                  "GeneralLiability_OtherCoverageDescription_B": "Stop Gap"}
        P._enforce_post_fill_guards(
            mapped, {k: {"ft": "/Tx"} for k in mapped}, {})
        assert mapped["GeneralLiability_OtherCoverageDescription_A"] == "Employee Benefits Liability"
        assert mapped["GeneralLiability_OtherCoverageDescription_B"] == "Stop Gap"


# ── ROUND 10: the conflict layer's blindness, and the latent landmines ───────

class TestStrictEntityConflict:
    def test_the_two_real_carriers_finally_conflict(self):
        # The root of client complaint #2: normalize_carrier reduced both real
        # carriers to "emc", so the reconciler pronounced the documents
        # consistent and the picker never opened.
        import services.underwriting_consistency as UC
        docs = [
            {"doc_id": "1", "filename": "package.pdf", "doc_type": "policy",
             "facts": {"carrier_name": "Employers Mutual Casualty Company"}, "text": ""},
            {"doc_id": "2", "filename": "coi.pdf", "doc_type": "certificate",
             "facts": {"carrier_name": "EMC Property & Casualty Company"}, "text": ""},
        ]
        res = UC.assess_underwriting_consistency(docs, {}, {})
        row = next(f for f in res["fields"] if f["fact_key"] == "carrier_name")
        assert row["status"] == "conflict" and row["review_required"]
        assert len(row["values"]) == 2

    def test_an_llc_and_an_inc_are_different_covered_parties(self):
        import services.underwriting_consistency as UC
        docs = [
            {"doc_id": "1", "filename": "a.pdf", "doc_type": "policy",
             "facts": {"applicant_name": "Orbin Contracting LLC"}, "text": ""},
            {"doc_id": "2", "filename": "b.pdf", "doc_type": "certificate",
             "facts": {"applicant_name": "Orbin Contracting Inc"}, "text": ""},
        ]
        res = UC.assess_underwriting_consistency(docs, {}, {})
        row = next(f for f in res["fields"] if f["fact_key"] == "applicant_name")
        assert row["status"] == "conflict" and row["review_required"]

    def test_formatting_and_truncation_variants_stay_consistent(self):
        # The promotion must add ZERO new noise: casing/punctuation, the
        # spelled-out suffix, and a suffixless truncation are the same entity.
        import services.underwriting_consistency as UC
        docs = [
            {"doc_id": "1", "filename": "a.pdf", "doc_type": "policy",
             "facts": {"applicant_name": "ORBIN CONTRACTING LLC",
                       "carrier_name": "Travelers Indemnity Company"}, "text": ""},
            {"doc_id": "2", "filename": "b.pdf", "doc_type": "certificate",
             "facts": {"applicant_name": "Orbin Contracting, Limited Liability Company",
                       "carrier_name": "Travelers"}, "text": ""},
        ]
        res = UC.assess_underwriting_consistency(docs, {}, {})
        for key in ("applicant_name", "carrier_name"):
            row = next(f for f in res["fields"] if f["fact_key"] == key)
            assert row["status"] == "consistent", key

    def test_the_comparator_itself(self):
        from services.normalization import entity_identity_conflict
        assert entity_identity_conflict(
            ["Hartford Fire Insurance Company",
             "Hartford Casualty Insurance Company"]) is True
        assert entity_identity_conflict(
            ["Nationwide Mutual Insurance Company",
             "Nationwide Property & Casualty Insurance Company"]) is True
        assert entity_identity_conflict(
            ["EMC Insurance Company", "EMC Insurance Companies"]) is False


class TestGateExposureBoxes:
    def test_the_clients_exposure_survives_the_gate(self):
        # Audit round 10 #3: ACORD's Exposure tooltip mentions "premium", so
        # the gate classified the box as premium and deleted the client's own
        # $39,300 payroll exposure as a cross-category borrow.
        schema = _schema("ACORD_126")
        fld = "GeneralLiability_Hazard_Exposure_A"
        facts = {"gl_class_code_schedule": [
            {"class_code": "91580", "premium_basis": "Payroll",
             "exposure_amount": "$39,300"}]}
        mapped = {fld: "$39,300"}
        P._enforce_numeric_meaning_gate(mapped, schema, facts, {fld})
        assert mapped[fld] == "$39,300"
        # And the ORIGINAL defect stays fixed: payroll into a SALES box dies.
        mapped2 = {"BusinessInformation_AnnualGrossSalesAmount_A": "$39,300"}
        P._enforce_numeric_meaning_gate(
            mapped2,
            {"BusinessInformation_AnnualGrossSalesAmount_A":
             {"tu": "Enter amount: gross sales"}},
            facts, {"BusinessInformation_AnnualGrossSalesAmount_A"})
        assert mapped2["BusinessInformation_AnnualGrossSalesAmount_A"] is None


class TestGuard4OwnAddress:
    def test_a_single_location_business_keeps_its_address_everywhere(self):
        # Audit round 10 #4: mailing == physical == premises is the ordinary
        # single-location case; Guard 4 called it boilerplate and deleted the
        # address from every box at once.
        addr = "4800 Dahlia St # D13, Denver, CO 80216-3121"
        mapped = {"NamedInsured_MailingAddress_LineOne_A": addr,
                  "CommercialStructure_PhysicalAddress_LineOne_A": addr,
                  "Vehicle_GaragingAddress_LineOne_A": addr}
        P._enforce_post_fill_guards(
            mapped, {k: {"ft": "/Tx"} for k in mapped},
            {"mailing_address": {"value": addr}})
        assert all(mapped.values())

    def test_real_boilerplate_still_dies(self):
        sentence = "coverage is subject to all terms and conditions of the policy"
        mapped = {"NamedInsured_RemarkText_A": sentence,
                  "CommercialProperty_RemarkText_A": sentence}
        P._enforce_post_fill_guards(
            mapped, {k: {"ft": "/Tx"} for k in mapped}, {})
        assert not any(mapped.values())


class TestUnderlyingPoliciesFactConsumed:
    def test_the_dedicated_fact_fills_where_the_summary_is_silent(self):
        # Audit round 10 #6 consumed the fact; audit round 12 #3 corrected the
        # RANKING to a cross-check. Here the summary states no number, so the
        # fact's BBC7263 stamps - but the two sources DISAGREE on the carrier,
        # and disagreement on a line's identity is a conflict, not a ranking:
        # the carrier ships blank and the questionnaire asks.
        facts = {"_form_id": "ACORD_131",
                 "coverage_lines": [
                     {"line": "Liability", "premium": "$1.00",
                      "carrier": "Wrong Company Entirely"}],
                 "underlying_policies": [
                     {"line": "General Liability",
                      "carrier": "EMC Property & Casualty Company",
                      "policy_no": "BBC7263", "limit": "$1,000,000"}]}
        assert P._resolve_underlying_policy_row(
            "UnderlyingPolicy_GeneralLiability_PolicyNumberIdentifier_A",
            facts) == "BBC7263"
        assert P._resolve_underlying_policy_row(
            "UnderlyingPolicy_GeneralLiability_InsurerFullName_A",
            facts) is None

    def test_the_fact_works_without_coverage_lines_at_all(self):
        facts = {"_form_id": "ACORD_131",
                 "underlying_policies": [
                     {"line": "Business Auto",
                      "carrier": "Employers Mutual Casualty Company",
                      "policy_no": "6E74002"}]}
        assert P._resolve_underlying_policy_row(
            "UnderlyingPolicy_Automobile_PolicyNumberIdentifier_A",
            facts) == "6E74002"


class TestWcScheduleReachesTheForm:
    def test_class_codes_bind_to_real_acord_130_fields(self):
        # Audit round 10 #5: extracted WC class codes were captured, validated,
        # asked about - and bound to field names that exist on no schema.
        facts = {"wc_class_codes": [
            {"code": "5403", "description": "Carpentry",
             "payroll": "$120,000", "rate": "8.5"}]}
        assert P._resolve_schedule_row(
            "WorkersCompensation_RateClass_ClassificationCode_A", facts) == "5403"
        assert P._resolve_schedule_row(
            "WorkersCompensation_RateClass_RemunerationAmount_A", facts) == "$120,000"
        assert P._resolve_schedule_row(
            "WorkersCompensation_RateClass_Rate_A", facts) == "8.5"


class TestUmbrellaOwnElections:
    def test_um_uim_medpay_never_borrow_the_autos_limits(self):
        # Audit round 10, open door #1: 131 page 6 carried the underlying
        # auto's $1M/$1M/$5,000 on every live run.
        facts = _routed_renewal_facts()
        mapped, _ = P.map_facts_to_form(
            facts, _schema("ACORD_131"), form_id="ACORD_131", raw_text=_RAW,
            pre_filled_gpt=_env({
                "ExcessUmbrella_UninsuredMotorists_LimitAmount_A": "$1,000,000",
                "ExcessUmbrella_UnderinsuredMotorists_LimitAmount_A": "$1,000,000",
                "ExcessUmbrella_MedicalPayments_LimitAmount_A": "$5,000",
            }))
        for f in ("ExcessUmbrella_UninsuredMotorists_LimitAmount_A",
                  "ExcessUmbrella_UnderinsuredMotorists_LimitAmount_A",
                  "ExcessUmbrella_MedicalPayments_LimitAmount_A"):
            assert mapped.get(f) is None, f

    def test_an_umbrella_scoped_fact_still_stamps(self):
        facts = _routed_renewal_facts(
            umbrella_um_limit={"value": "$2,000,000"})
        r = P._resolve_umbrella_um_election(
            "ExcessUmbrella_UninsuredMotorists_LimitAmount_A",
            dict(facts, _form_id="ACORD_131"))
        assert r == "$2,000,000"


class TestAdvertisersCensus:
    def test_media_used_print_is_dead(self):
        # Audit round 10, open door #2: fabricated on three of four runs.
        facts = _routed_renewal_facts()
        mapped, _ = P.map_facts_to_form(
            facts, _schema("ACORD_131"), form_id="ACORD_131", raw_text=_RAW,
            pre_filled_gpt=_env({"AdvertisersLiability_MediaUsedCode_A": "Print"}))
        assert mapped.get("AdvertisersLiability_MediaUsedCode_A") is None


# ── ROUND 11: the last verified leftovers ────────────────────────────────────

class TestVehicleFleetGrid:
    def test_the_grid_is_owned_when_the_real_fleet_schedule_exists(self):
        # Four runs, four different junks in these 56 cells ("PRIV PASSENGER"
        # as cargo, the "0 - 25" band, fabricated zeros, IM class names). The
        # auto schedule IS the fleet evidence; the grid ships blank.
        facts = _routed_renewal_facts(
            auto_vin_schedule=[{"year": "2012", "make": "Subaru",
                                "vin": "4S4BRCGC9C3217772"}])
        mapped, _ = P.map_facts_to_form(
            facts, _schema("ACORD_131"), form_id="ACORD_131", raw_text=_RAW,
            pre_filled_gpt=_env({
                "VehicleFleet_PrivatePassenger_PropertyHauledDescription_A": "PRIV PASSENGER",
                "VehicleFleet_Truck_Light_NonOwnedCount_A": "0 - 25",
            }))
        assert mapped.get(
            "VehicleFleet_PrivatePassenger_PropertyHauledDescription_A") is None
        assert mapped.get("VehicleFleet_Truck_Light_NonOwnedCount_A") is None
        _, unmatched, _ = P.compute_form_gaps(
            "ACORD_131", _schema("ACORD_131"), facts)
        assert [f for f in unmatched if f.startswith("VehicleFleet_")] == []

    def test_legacy_sessions_without_a_schedule_are_unchanged(self):
        assert P._resolve_vehicle_fleet_grid(
            "VehicleFleet_PrivatePassenger_OwnedCount_A", {}) is _SCHED_SKIP


class TestWcOfficersReachTheForm:
    def test_officers_bind_to_real_acord_130_fields(self):
        facts = {"wc_officers": [
            {"name": "Jane Roe", "title": "President", "ownership_pct": "60"}]}
        assert P._resolve_schedule_row(
            "WorkersCompensation_Individual_FullName_A", facts) == "Jane Roe"
        assert P._resolve_schedule_row(
            "WorkersCompensation_Individual_TitleRelationshipCode_A", facts) == "President"
        assert P._resolve_schedule_row(
            "WorkersCompensation_Individual_OwnershipPercent_A", facts) == "60"


# ── ROUND 12: the phantom key, the accidental blank, the unvalidated rank ────

class TestReadWhatIsWritten:
    _RESOLVER_READ_FACT_KEYS = (
        "auto_vin_schedule", "coverage_lines", "dec_page_entries",
        "prior_coverage_by_line", "underlying_policies",
        "wc_officers", "wc_class_codes",
        "umbrella_um_limit", "umbrella_uim_limit",
        "umbrella_medical_payments_limit",
        "umbrella_effective_date", "umbrella_expiration_date",
        "total_policy_premium", "umbrella_limit",
    )

    def test_every_fact_a_resolver_reads_is_written_by_extraction(self):
        # The 2026-08-07 phantom-key class, widened per audit round 12: a
        # resolver reading a fact nothing writes is silently dead. Every fact
        # key the relationship resolvers consume must appear in the extraction
        # source (schema/prompt/merge), so a rename or a typo fails the build.
        src_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "services", "extraction_service.py")
        with open(src_path, encoding="utf-8") as fh:
            src = fh.read()
        missing = [k for k in self._RESOLVER_READ_FACT_KEYS if k not in src]
        assert missing == [], f"resolver reads fact(s) nothing writes: {missing}"

    def test_the_phantom_key_is_gone_from_pdf_service(self):
        src_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "services", "pdf_service.py")
        with open(src_path, encoding="utf-8") as fh:
            assert "auto_vehicle_schedule" not in fh.read()

    def test_fleet_grid_fires_on_the_key_extraction_writes(self):
        facts = _routed_renewal_facts(
            auto_vin_schedule=[{"year": "2012", "make": "Subaru",
                                "vin": "4S4BRCGC9C3217772"}])
        _, unmatched, _ = P.compute_form_gaps(
            "ACORD_131", _schema("ACORD_131"), facts)
        assert [f for f in unmatched if f.startswith("VehicleFleet_")] == []


class TestUnderlyingSourcesCrossChecked:
    def test_disagreeing_sources_blank_the_row(self):
        # The audit's literal reproduction: the fact confidently wrong, the
        # repaired summary right - the round-10 ranking printed 'Wrong Carrier
        # Inc' and the AUTO number on the umbrella form.
        facts = {"_form_id": "ACORD_131",
                 "coverage_lines": [
                     {"line": "General Liability", "premium": "$3,954.00",
                      "carrier": "EMC Property & Casualty Company",
                      "policy_number": "BBC7263"}],
                 "underlying_policies": [
                     {"line": "General Liability",
                      "carrier": "WRONG CARRIER INC",
                      "policy_no": "6E7-40-02---26"}]}
        assert P._resolve_underlying_policy_row(
            "UnderlyingPolicy_GeneralLiability_InsurerFullName_A", facts) is None
        assert P._resolve_underlying_policy_row(
            "UnderlyingPolicy_GeneralLiability_PolicyNumberIdentifier_A", facts) is None

    def test_agreeing_sources_stamp(self):
        facts = {"_form_id": "ACORD_131",
                 "coverage_lines": [
                     {"line": "General Liability", "premium": "$3,954.00",
                      "carrier": "EMC Property & Casualty Company",
                      "policy_number": "BBC7263"}],
                 "underlying_policies": [
                     {"line": "General Liability",
                      "carrier": "EMC Property and Casualty Company",
                      "policy_no": "BBC7263"}]}
        assert P._resolve_underlying_policy_row(
            "UnderlyingPolicy_GeneralLiability_PolicyNumberIdentifier_A",
            facts) == "BBC7263"
        assert P._resolve_underlying_policy_row(
            "UnderlyingPolicy_GeneralLiability_InsurerFullName_A",
            facts) is not None


class TestUmbrellaUmIsNowCapturable:
    def test_the_three_election_keys_are_in_the_extraction_schema(self):
        # Round 10's fix was right by accident - the resolver read facts
        # nothing wrote, so a genuine umbrella UM election could never be
        # captured. The keys are now in the extraction schema with a scoping
        # rule (never the underlying auto's figures).
        src_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "services", "extraction_service.py")
        with open(src_path, encoding="utf-8") as fh:
            src = fh.read()
        for key in ("umbrella_um_limit", "umbrella_uim_limit",
                    "umbrella_medical_payments_limit"):
            assert key in src, key


# ── Anti-rot: the new resolvers stay in the authoritative-blank contract ─────

def test_new_resolvers_are_registered_authoritative():
    for name in ("_resolve_declared_absent_line_row",
                 "_resolve_underlying_policy_row",
                 "_resolve_certificate_producer_ids",
                 "_resolve_certificate_other_row",
                 "_resolve_package_header_identity",
                 "_resolve_umbrella_um_election",
                 "_resolve_vehicle_fleet_grid"):
        assert name in P._AUTHORITATIVE_BLANK_RESOLVERS, name
        assert callable(getattr(P, name))
