"""14 Sep 2026 - WHO IS THIS PARTY, AND IN WHAT ROLE (Orbin, client items 11 + 12).

11. The expiring producer (Commercial Risk Solutions / Terri Wroblewski) printed on
    the new application. On the real package NO uploaded document names the
    submitting agency - ThinkSmith Agency / Michelle Smith are the logged-in
    account - so the 11 Sep routing could only RECORD the old agency and every
    form kept printing it. Routing key by key was also unsafe: fed the account it
    stitched ThinkSmith's name onto the old agency's address, phone and e-mail.
12. "For Informational Purposes Only" (the COI's CERTIFICATE HOLDER box) printed as
    an Additional Interest. The box guard caught that one spelling; the FACT
    survived in three keys, and the COI's own OCR spelling slipped the guard.

Fixtures are the real session's per-document values (e7084347), verbatim.
"""
import copy
import inspect
import json
import os
import re

import pytest

from services import extraction_pipeline
from services.extraction_service import (
    _route_producer_identity, drop_non_party_names, merge_facts,
    select_primary_truth)
from services.fact_comparison import same_agency
from services.field_mapping_integrity import names_a_party
from services.pdf_service import (
    _SCHED_SKIP, _SUBMITTING_PRODUCER_BOX_RE, _enforce_post_fill_guards,
    _resolve_submitting_producer, compute_form_gaps)
from services.underwriting_consistency import (
    _producer_block_separated, apply_confirmations,
    assess_underwriting_consistency)

_SCHEMA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "forms_schemas")


def _schema(form_id):
    with open(os.path.join(_SCHEMA_DIR, f"{form_id}_schema.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _env(value):
    return {"value": value, "source": "ai", "confidence": "ai_high"}


def _v(raw):
    return raw.get("value") if isinstance(raw, dict) and "value" in raw else raw


FIO = "For Informational Purposes Only"
THINKSMITH = {"organization_name": "ThinkSmith Agency LLC", "full_name": "Michelle Smith"}
OLD_AGENCY = re.compile(
    r"(?i)commercial risk|\bcrs\b|wroblewski|meridian|996-7800|757-7719|crsdenver")


def _orbin_docs():
    dec = {"doc_id": "dec", "filename": "2526 Package Policy (Complete Copy).pdf",
           "doc_type": "dec_page", "text": "", "flags": {},
           "facts": {
               "applicant_name": _env("ORBIN CONTRACTING LLC"),
               "producer_name": _env("COMMERCIAL RISK SOLUTIONS, INC."),
               "producer_address": _env(
                   "9780 S MERIDIAN BLVD STE 400, ENGLEWOOD, CO 80112-6072"),
               "producer_contact_phone": _env("303-996-7800"),
           }}
    coi = {"doc_id": "coi", "filename": "CRS COI FIO - Orbin CERT ONLY.pdf",
           "doc_type": "certificate", "text": "", "flags": {},
           "facts": {
               "applicant_name": _env("Orbin Contracting, LLC"),
               "producer_name": _env("CRS Insurance Brokerage"),
               "producer_address": _env("9780 S Meridian Blvd Suite 400, Englewood, CO 80112"),
               "producer_contact_name": _env("Terri Wroblewski"),
               "producer_contact_phone": _env("303-996-7800"),
               "producer_contact_email": _env("twroblewski@crsdenver.com"),
               "producer_fax": _env("303-757-7719"),
               "certificate_holder": _env(FIO),
               "certificate_description_of_operations": _env(FIO),
               "risk_transfer": {"certificate_holder_name": FIO, "mortgagee_name": None,
                                 "loss_payee_name": None, "additional_insured_names": []},
           }}
    nar = {"doc_id": "nar",
           "filename": "ORBIN CONTRACTING LLC submission narrative-20260530144518.pdf",
           "doc_type": "narrative", "text": "", "flags": {},
           "facts": {"applicant_name": _env("Orbin Contracting LLC")}}
    return [dec, coi, nar]


def _merge(docs=None, account=None):
    docs = docs if docs is not None else _orbin_docs()
    mf, _ = merge_facts(docs, select_primary_truth(docs), submitting_account=account)
    return mf, docs


# ─────────────────────────────────────────────────────────────────────────────
# ONE AGENCY, SEVERAL PRINTINGS
# ─────────────────────────────────────────────────────────────────────────────
class TestSameAgency:

    @pytest.mark.parametrize("a,b", [
        ("COMMERCIAL RISK SOLUTIONS, INC.", "CRS Insurance Brokerage"),
        ("CRS Insurance Brokerage", "COMMERCIAL RISK SOLUTIONS, INC."),
        ("ThinkSmith Agency LLC", "ThinkSmith Agency"),
        ("ThinkSmith Agency, Inc.", "Think Smith Agency"),
    ])
    def test_one_agency_printed_two_ways(self, a, b):
        assert same_agency(a, b) is True

    @pytest.mark.parametrize("a,b", [
        ("ThinkSmith Agency LLC", "COMMERCIAL RISK SOLUTIONS, INC."),
        ("ThinkSmith Agency LLC", "CRS Insurance Brokerage"),
        ("Smith Agency", "SA Insurance"),      # an initialism needs 2+ real words
    ])
    def test_different_agencies(self, a, b):
        assert same_agency(a, b) is False

    @pytest.mark.parametrize("a,b", [("", "X Agency"), (None, "X"),
                                     ("Insurance Agency", "ThinkSmith"), (5, []),
                                     ("N/A", "CRS Insurance Brokerage"),
                                     ("A Agency", "B Agency")])   # single letters are noise
    def test_cannot_tell_is_none_never_a_difference(self, a, b):
        assert same_agency(a, b) is None

    @pytest.mark.parametrize("a,b", [
        ("Marsh", "Marsh & McLennan Agency LLC"),
        ("Smith Agency", "Smith & Jones Insurance"),
        ("Denver Risk Advisors", "Denver Metro Insurance"),
    ])
    def test_a_shortened_printing_is_never_called_different(self, a, b):
        """An account typed as "Marsh" against a dec printing "Marsh &
        McLennan Agency LLC" must not be read as a change of agency - that
        would wipe the real agency's address and phone off the form."""
        assert same_agency(a, b) is None
        assert same_agency(b, a) is None

    def test_a_shortened_account_name_moves_nothing(self):
        base, _ = _merge(account=None)
        mf, _ = _merge(account={"organization_name": "Commercial Risk",
                                "full_name": "Someone Else"})
        assert _v(mf.get("producer_name")) == _v(base.get("producer_name"))
        assert _v(mf.get("producer_address")) == _v(base.get("producer_address"))


# ─────────────────────────────────────────────────────────────────────────────
# ITEM 11 - the submitting producer, and the block moves whole
# ─────────────────────────────────────────────────────────────────────────────
class TestProducerRouting:

    def test_the_orbin_package_files_under_the_logged_in_agency(self):
        mf, _ = _merge(account=THINKSMITH)
        assert _v(mf["producer_name"]) == "ThinkSmith Agency LLC"
        assert _v(mf["producer_contact_name"]) == "Michelle Smith"
        assert _v(mf["expiring_producer_name"]) == "COMMERCIAL RISK SOLUTIONS, INC."
        assert _v(mf["expiring_producer_contact_name"]) == "Terri Wroblewski"
        assert _v(mf["expiring_producer_contact_email"]) == "twroblewski@crsdenver.com"

    def test_no_old_agency_value_survives_in_the_submitting_block(self):
        """The chimera the key-by-key route produced: the new agency's name
        over the old agency's address, phone, fax and e-mail."""
        mf, _ = _merge(account=THINKSMITH)
        for key in ("producer_name", "producer_address", "producer_contact_name",
                    "producer_contact_phone", "producer_contact_email", "producer_fax"):
            assert not OLD_AGENCY.search(str(_v(mf.get(key)) or "")), key
        for key in ("producer_address", "producer_contact_phone",
                    "producer_contact_email", "producer_fax"):
            assert key not in mf, key

    def test_the_account_value_says_where_it_came_from(self):
        mf, _ = _merge(account=THINKSMITH)
        env = mf["producer_name"]
        assert env["source"] == "account"
        assert env["evidence_state"] == "user_confirmed"

    def test_without_an_account_nothing_changes(self):
        mf, _ = _merge(account=None)
        assert _v(mf["producer_name"]) == "COMMERCIAL RISK SOLUTIONS, INC."
        assert _v(mf["producer_contact_name"]) == "Terri Wroblewski"

    @pytest.mark.parametrize("org", ["Commercial Risk Solutions, Inc.",
                                     "CRS Insurance Brokerage"])
    def test_an_incumbent_re_marketing_its_own_account_changes_nothing(self, org):
        base, _ = _merge(account=None)
        mf, _ = _merge(account={"organization_name": org, "full_name": "Terri Wroblewski"})
        for key in ("producer_name", "producer_address", "producer_contact_name",
                    "producer_contact_phone", "producer_contact_email", "producer_fax"):
            assert _v(mf.get(key)) == _v(base.get(key)), key

    def test_a_submission_document_outranks_the_account(self):
        docs = _orbin_docs()
        docs.append({"doc_id": "app", "filename": "app.pdf", "doc_type": "application",
                     "text": "", "flags": {},
                     "facts": {"producer_name": _env("Cascade Risk Partners"),
                               "producer_contact_name": _env("Dana Whitfield")}})
        mf, _ = _merge(docs, account=THINKSMITH)
        assert _v(mf["producer_name"]) == "Cascade Risk Partners"
        assert _v(mf["producer_contact_name"]) == "Dana Whitfield"
        assert "producer_address" not in mf
        assert _v(mf["expiring_producer_name"]) == "COMMERCIAL RISK SOLUTIONS, INC."

    def test_the_submission_route_is_atomic_too(self):
        mf = {"producer_name": "Commercial Risk Solutions",
              "producer_address": "9780 S MERIDIAN BLVD STE 400"}
        _route_producer_identity(mf, [
            {"doc_type": "dec_page",
             "facts": {"producer_name": "Commercial Risk Solutions",
                       "producer_address": "9780 S MERIDIAN BLVD STE 400"}},
            {"doc_type": "narrative", "facts": {"producer_name": "ThinkSmith Agency"}}])
        assert mf["producer_name"] == "ThinkSmith Agency"
        assert "producer_address" not in mf
        assert mf["expiring_producer_address"] == "9780 S MERIDIAN BLVD STE 400"

    def test_no_producer_in_any_document_is_left_as_it_was(self):
        docs = [{"doc_id": "d", "filename": "d.pdf", "doc_type": "dec_page", "text": "",
                 "flags": {}, "facts": {"applicant_name": _env("ORBIN CONTRACTING LLC")}}]
        mf, _ = _merge(docs, account=THINKSMITH)
        assert "producer_name" not in mf

    @pytest.mark.parametrize("acct", [
        {}, {"organization_name": "  "}, "junk", 7,
        {"organization_name": "N/A", "full_name": "X Y"},
        {"organization_name": "TBD", "full_name": "X Y"},
        {"organization_name": "none", "full_name": "X Y"}])
    def test_an_account_without_an_agency_is_ignored(self, acct):
        base, _ = _merge(account=None)
        mf, _ = _merge(account=acct)
        assert _v(mf.get("producer_name")) == _v(base.get("producer_name"))

    # ── found by fuzzing 6,000 random packages (14 Sep) ─────────────────────
    def test_a_submission_document_naming_no_agency_lends_nothing(self):
        """A narrative mentioning the current broker's contact must not put
        that person under the new agency."""
        docs = _orbin_docs()
        docs[2]["facts"]["producer_contact_name"] = _env("Terri Wroblewski")
        mf, _ = _merge(docs, account=THINKSMITH)
        assert _v(mf["producer_contact_name"]) == "Michelle Smith"

    def test_two_submitting_agencies_stitch_nothing(self):
        mf = {"producer_name": "A Agency", "producer_address": "ADDR A"}
        _route_producer_identity(mf, [
            {"doc_type": "application",
             "facts": {"producer_name": "A Agency", "producer_address": "ADDR A"}},
            {"doc_type": "quote",
             "facts": {"producer_name": "B Agency", "producer_address": "ADDR B"}}])
        assert mf == {"producer_name": "A Agency", "producer_address": "ADDR A"}

    def test_an_agency_with_no_identity_is_ignored_not_trusted(self):
        docs = _orbin_docs()
        docs.append({"doc_id": "lr", "filename": "lr.pdf", "doc_type": "loss_run",
                     "text": "", "flags": {},
                     "facts": {"producer_name": _env("Insurance Agency"),
                               "producer_fax": _env("555-0000")}})
        mf, _ = _merge(docs, account=THINKSMITH)
        assert _v(mf["producer_name"]) == "ThinkSmith Agency LLC"
        assert "producer_fax" not in mf

    def test_a_submission_document_naming_no_agency_wins_no_key(self):
        """Fuzzing, per-key path: an unnamed narrative's contact replaced the
        named agency's own contact."""
        mf = {"producer_name": "ThinkSmith Agency LLC",
              "producer_contact_name": "Michelle Smith"}
        _route_producer_identity(mf, [
            {"doc_type": "dec_page",
             "facts": {"producer_name": "ThinkSmith Agency LLC",
                       "producer_contact_name": "Michelle Smith"}},
            {"doc_type": "application", "facts": {"producer_name": "ThinkSmith Agency LLC"}},
            {"doc_type": "narrative", "facts": {"producer_contact_name": "Terri Wroblewski"}}])
        assert mf["producer_contact_name"] == "Michelle Smith"

    def test_the_submitting_agencys_own_value_still_replaces_an_unnamed_one(self):
        """The per-key swap is kept where it is right: the application's own
        address beats one from a loss run that names no agency."""
        mf = {"producer_name": "A Agency", "producer_address": "ADDR-LOSS-RUN"}
        _route_producer_identity(mf, [
            {"doc_type": "loss_run", "facts": {"producer_address": "ADDR-LOSS-RUN"}},
            {"doc_type": "application",
             "facts": {"producer_name": "A Agency", "producer_address": "ADDR-A"}}])
        assert mf["producer_address"] == "ADDR-A"

    def test_a_different_contact_at_the_same_agency_still_wins(self):
        mf = {"producer_name": "ThinkSmith Agency", "producer_contact_name": "Dana Whitfield"}
        _route_producer_identity(mf, [
            {"doc_type": "dec_page",
             "facts": {"producer_name": "ThinkSmith Agency",
                       "producer_contact_name": "Dana Whitfield"}},
            {"doc_type": "application",
             "facts": {"producer_name": "ThinkSmith Agency, Inc.",
                       "producer_contact_name": "Michelle Smith"}}])
        assert mf["producer_contact_name"] == "Michelle Smith"
        assert same_agency(mf["producer_name"], "ThinkSmith Agency") is True
        assert not _producer_block_separated(mf)

    def test_the_pipeline_hands_the_account_to_the_merge(self):
        # The account lookup moved into `_submitting_account_for` (15 Sep 2026,
        # so an unreadable account is told apart from no account); the seam is
        # the same: the pipeline reads the logged-in account and hands it over.
        src = inspect.getsource(extraction_pipeline._finalize_pipeline)
        assert "submitting_account=_submitting_account" in src
        assert "_submitting_account_for(user_id)" in src
        assert "get_user_by_id" in inspect.getsource(extraction_pipeline._submitting_account_for)


class TestProducerBoxes:

    @pytest.mark.parametrize("form_id", ["ACORD_125", "ACORD_25", "ACORD_127"])
    def test_every_form_prints_the_submitting_agency_and_nothing_of_the_old(self, form_id):
        mf, _ = _merge(account=THINKSMITH)
        schema = _schema(form_id)
        mapped, unmatched, _det = compute_form_gaps(form_id, schema, mf)
        stamped = {f: v for f, v in mapped.items() if f.startswith("Producer_") and v}
        assert stamped.get("Producer_FullName_A") == "ThinkSmith Agency LLC"
        for field, value in stamped.items():
            assert not OLD_AGENCY.search(str(value)), (field, value)
        # Nothing of the producer block is left for gap fill to re-read off
        # the old agency's page headers.
        assert not [f for f in unmatched if f.startswith("Producer_")]

    def test_the_printed_name_beside_the_signature_is_the_submitter(self):
        mf, _ = _merge(account=THINKSMITH)
        mapped, _u, _d = compute_form_gaps("ACORD_125", _schema("ACORD_125"), mf)
        assert mapped.get("Producer_AuthorizedRepresentative_FullName_A") == "Michelle Smith"
        assert mapped.get("Producer_ContactPerson_FullName_A") == "Michelle Smith"

    def test_a_contact_box_reads_its_own_fact_not_the_agency_name(self):
        """The old pattern's `\\w+` swallowed the row letter, so every
        ContactPerson box looked up `producer_name` instead of its own fact."""
        facts = {"producer_name": "ThinkSmith Agency",
                 "expiring_producer_name": "Commercial Risk Solutions",
                 "producer_contact_email": ""}
        assert _resolve_submitting_producer(
            "Producer_ContactPerson_EmailAddress_A", facts) is None
        facts["producer_contact_email"] = "michelle@thinksmith.example"
        assert _resolve_submitting_producer(
            "Producer_ContactPerson_EmailAddress_A", facts) is _SCHED_SKIP

    def test_the_incumbent_path_is_untouched(self):
        facts = {"producer_name": "COMMERCIAL RISK SOLUTIONS, INC.",
                 "expiring_producer_name": "CRS Insurance Brokerage"}
        for field in ("Producer_FullName_A", "Producer_MailingAddress_LineOne_A",
                      "Producer_PhoneNumber_A", "Producer_ContactPerson_FullName_A"):
            assert _resolve_submitting_producer(field, facts) is _SCHED_SKIP

    def test_every_producer_box_on_every_form_is_owned(self):
        """Anti-rot: a Producer_ box the resolver cannot see is a box gap fill
        can fill from the old agency's page headers."""
        import glob
        seen = 0
        for path in glob.glob(os.path.join(_SCHEMA_DIR, "ACORD_*_schema.json")):
            for name in json.load(open(path, encoding="utf-8")):
                if not name.startswith("Producer_") \
                        or name.startswith("Producer_AuthorizedRepresentative_Signature"):
                    continue
                seen += 1
                assert _SUBMITTING_PRODUCER_BOX_RE.match(name), name
        assert seen > 60


class TestProducerCard:

    def test_the_card_is_not_offered_once_the_roles_are_separated(self):
        mf, docs = _merge(account=THINKSMITH)
        res = assess_underwriting_consistency(docs, mf, {})
        assert not [f for f in res["fields"] if str(f["fact_key"]).startswith("producer_")]
        # still ASSESSED, so detect_source_conflicts does not re-report it
        assert "producer_name" in res["assessed_keys"]

    @pytest.mark.parametrize("facts,expected", [
        ({"producer_name": "ThinkSmith Agency LLC",
          "expiring_producer_name": "COMMERCIAL RISK SOLUTIONS, INC."}, True),
        ({"producer_name": "COMMERCIAL RISK SOLUTIONS, INC.",
          "expiring_producer_name": "CRS Insurance Brokerage"}, False),
        ({"producer_name": "X Agency"}, False),
        ({}, False), (None, False),
    ])
    def test_separated_means_a_different_agency(self, facts, expected):
        assert _producer_block_separated(facts) is expected

    def test_a_stored_confirmation_of_the_old_agency_cannot_put_it_back(self):
        """The real session's picker confirmation, verbatim."""
        mf, docs = _merge(account=THINKSMITH)
        out = apply_confirmations(mf, {"producer_name": "COMMERCIAL RISK SOLUTIONS, INC."},
                                  docs=docs)
        assert _v(out["producer_name"]) == "ThinkSmith Agency LLC"
        assert _v(out["expiring_producer_name"]) == "COMMERCIAL RISK SOLUTIONS, INC."

    def test_a_confirmation_naming_the_submitting_agency_still_applies(self):
        mf, docs = _merge(account=THINKSMITH)
        out = apply_confirmations(mf, {"producer_name": "ThinkSmith Agency, LLC"}, docs=docs)
        assert _v(out["producer_name"]) == "ThinkSmith Agency, LLC"


# ─────────────────────────────────────────────────────────────────────────────
# ITEM 12 - a holder fact must name a party
# ─────────────────────────────────────────────────────────────────────────────
class TestNonPartyHolder:

    def test_the_placeholder_leaves_every_fact_it_reached(self):
        facts = copy.deepcopy(_orbin_docs()[1]["facts"])
        cleared = drop_non_party_names(facts)
        assert "certificate_holder" not in facts
        assert facts["risk_transfer"]["certificate_holder_name"] is None
        assert "certificate_description_of_operations" not in facts
        assert len(cleared) == 3

    def test_no_merged_fact_carries_the_placeholder(self):
        mf, docs = _merge(account=THINKSMITH)
        blob = json.dumps(mf, default=str).lower()
        assert "informational purposes" not in blob
        # the persisted per-document copy the picker reads is cleaned too
        assert "certificate_holder" not in docs[1]["facts"]

    @pytest.mark.parametrize("holder", [
        "Kestrel Terminal Authority, 1201 Port of Tacoma Rd, Tacoma WA 98421",
        "Wells Fargo Equipment Finance, Inc.", "City of Aurora", "John A. Smith",
        "Bank of the Front Range, N.A.", "First National Bank, ISAOA/ATIMA"])
    def test_a_real_holder_is_kept(self, holder):
        facts = {"certificate_holder": _env(holder), "mortgagee_name": holder}
        assert drop_non_party_names(facts) == []
        assert _v(facts["certificate_holder"]) == holder

    def test_only_prose_facts_are_swept_for_the_same_text(self):
        facts = {"mortgagee_name": "Not Applicable", "wc_xmod": "Not Applicable",
                 "operations_description": "Not Applicable"}
        drop_non_party_names(facts)
        assert "mortgagee_name" not in facts
        assert facts["wc_xmod"] == "Not Applicable"     # another fact's real answer
        assert "operations_description" not in facts

    def test_the_additional_insured_list_is_not_judged(self):
        facts = {"risk_transfer": {"additional_insured_names": [
            "Ridgeline as additional insured", "City and County of Denver"]}}
        drop_non_party_names(facts)
        assert len(facts["risk_transfer"]["additional_insured_names"]) == 2

    @pytest.mark.parametrize("facts", [None, "x", 5, [], {}, {"risk_transfer": "junk"},
                                       {"certificate_holder": None}])
    def test_malformed_input_never_raises(self, facts):
        assert drop_non_party_names(facts) == []


class TestLookAlikePlaceholders:
    """A third-party "name" made only of ACORD's own form vocabulary and a
    certificate's status words names nobody (0 of 547 stored real names refused)."""

    @pytest.mark.parametrize("value", [
        "Proof of Insurance", "Sample Certificate", "Specimen", "Holder Of Record",
        "Agency Copy", "File Copy", "Insured's Records", "Commercial General Liability",
        "Ongoing And Completed Operations", "Evidence Only", "Evidence of Insurance",
        "Landlord", "Lessor", "Tenant", "FORINFORMATIONALPURPOSESONLY",
        "FORINFORMATIONPURPOSESONLY", "EVIDENCEOFINSURANCE"])
    def test_refused_as_a_third_party(self, value):
        assert names_a_party(value, third_party=True) is False

    @pytest.mark.parametrize("value", [
        "United Rentals", "Summit Ridge", "Ridgeline", "Cascade Metal Works",
        "Premier Builders", "Quality Construction", "Liberty Mutual", "Farm Credit East",
        "Sunbelt Rentals", "Enterprise Fleet Management", "KESTRELTERMINALAUTHORITY",
        "UNITEDRENTALS", "CATERPILLARFINANCIALSERVICES", "Wells Fargo Bank, N.A."])
    def test_real_third_parties_are_kept(self, value):
        assert names_a_party(value, third_party=True) is True

    def test_the_vocabulary_rule_is_live(self):
        from services.field_mapping_integrity import _acord_vocabulary
        fields, tips = _acord_vocabulary()
        assert len(fields) > 500 and len(tips) > 1000

    def test_an_insureds_own_ordinary_name_is_never_judged_by_vocabulary(self):
        assert names_a_party("Commercial Roofing") is True
        assert names_a_party("Commercial Roofing", respace=True) is True

    def test_a_gap_filled_insured_box_is_re_spaced(self):
        box = "NamedInsured_Contact_FullName_A"
        mapped = {box: "ForInformationalPurposesOnly"}
        _enforce_post_fill_guards(mapped, _schema("ACORD_125"), {}, gpt_filled_set={box})
        assert mapped[box] is None

    @pytest.mark.parametrize("value", ["Proof of Insurance", "Holder Of Record",
                                       "Commercial General Liability", "Owner"])
    def test_a_gap_filled_insured_contact_box_refuses_look_alikes(self, value):
        box = "NamedInsured_Contact_FullName_A"
        mapped = {box: value}
        _enforce_post_fill_guards(mapped, _schema("ACORD_125"), {}, gpt_filled_set={box})
        assert mapped[box] is None

    def test_a_gap_filled_insured_contact_keeps_a_real_person(self):
        box = "NamedInsured_Contact_FullName_A"
        mapped = {box: "Erin Royal"}
        _enforce_post_fill_guards(mapped, _schema("ACORD_125"), {}, gpt_filled_set={box})
        assert mapped[box] == "Erin Royal"

    def test_the_applicants_own_name_is_never_re_spaced(self):
        box = "NamedInsured_FullName_A"
        mapped = {box: "OnTimeDelivery"}                  # deterministic, glued
        _enforce_post_fill_guards(mapped, _schema("ACORD_125"), {}, gpt_filled_set=set())
        assert mapped[box] == "OnTimeDelivery"

    def test_lease_roles_are_roles(self):
        from services.normalization import is_party_role_label
        for role in ("Landlord", "LESSOR", "tenant", "Property Owner"):
            assert is_party_role_label(role)


class TestRemainingPartyIssues:

    def test_an_account_that_is_the_insured_is_not_the_producer(self):
        base, _ = _merge(account=None)
        mf, _ = _merge(account={"organization_name": "Orbin Contracting LLC",
                                "full_name": "Erin Royal"})
        assert _v(mf.get("producer_name")) == _v(base.get("producer_name"))

    def test_without_a_login_one_agency_per_block(self):
        mf = {"producer_name": "Commercial Risk Solutions", "producer_fax": "FAX-CASCADE",
              "producer_address": "ADDR-CRS"}
        _route_producer_identity(mf, [
            {"doc_type": "dec_page", "facts": {"producer_name": "Commercial Risk Solutions",
                                               "producer_address": "ADDR-CRS"}},
            {"doc_type": "loss_run", "facts": {"producer_name": "Cascade Risk Partners",
                                               "producer_fax": "FAX-CASCADE"}}])
        assert "producer_fax" not in mf
        assert mf["producer_address"] == "ADDR-CRS"

    def test_a_value_an_unnamed_document_states_is_left_alone(self):
        mf = {"producer_name": "Commercial Risk Solutions", "producer_fax": "FAX-X"}
        _route_producer_identity(mf, [
            {"doc_type": "dec_page", "facts": {"producer_name": "Commercial Risk Solutions"}},
            {"doc_type": "loss_run", "facts": {"producer_name": "Cascade Risk Partners",
                                               "producer_fax": "FAX-X"}},
            {"doc_type": "endorsement", "facts": {"producer_fax": "FAX-X"}}])
        assert mf["producer_fax"] == "FAX-X"

    def test_one_agency_printed_two_ways_is_not_a_card(self):
        mf, docs = _merge(account=None)
        res = assess_underwriting_consistency(docs, mf, {})
        assert not [f for f in res["fields"]
                    if f["fact_key"] == "producer_name" and f["status"] == "conflict"]

    def test_two_real_agencies_still_conflict(self):
        docs = _orbin_docs()
        docs[1]["facts"]["producer_name"] = _env("Cascade Risk Partners")
        mf, docs = _merge(docs, account=None)
        res = assess_underwriting_consistency(docs, mf, {})
        assert [f for f in res["fields"]
                if f["fact_key"] == "producer_name" and f["status"] == "conflict"]

    def test_an_uploaded_coi_is_not_a_certificate_request(self):
        from services.cross_form_validator import _check_certificate_requested_but_missing as chk
        flags = {"has_certificate_request": True, "is_certificate_doc": True}
        assert chk({}, flags, {"ACORD_125"}) == []
        assert chk({"certificate_holder": "Kestrel Terminal Authority"}, flags, {"ACORD_125"})
        assert chk({}, {"has_certificate_request": True}, {"ACORD_125"})

    def test_the_certificate_checklist_item_reads_a_real_holder(self):
        from services.sqs_service import risk_transfer_check
        items = risk_transfer_check({"certificate_holder": "Kestrel Terminal Authority"}, {}, [])
        assert [i for i in items if i["check"] == "certificate_of_insurance"]
        assert not [i for i in risk_transfer_check({}, {}, [])
                    if i["check"] == "certificate_of_insurance"]

    def test_a_placeholder_holder_is_an_owned_blank_on_acord_25(self):
        mf, _ = _merge(account=THINKSMITH)
        assert "certificate_holder" in (mf.get("_rejected_facts") or {})
        mapped, unmatched, _d = compute_form_gaps("ACORD_25", _schema("ACORD_25"), mf)
        for box in ("CertificateHolder_FullName_A", "CertificateHolder_MailingAddress_LineOne_A"):
            assert not mapped.get(box)
            assert box not in unmatched

    def test_a_real_holder_still_stamps(self):
        from services.pdf_service import _resolve_rejected_party_box
        facts = {"certificate_holder": "Kestrel Terminal Authority",
                 "_rejected_facts": {"certificate_holder": "x"}}
        assert _resolve_rejected_party_box("CertificateHolder_FullName_A", facts) is _SCHED_SKIP
        assert _resolve_rejected_party_box("CertificateHolder_FullName_A", {}) is _SCHED_SKIP


class TestRunTogetherOcr:

    def test_the_cois_own_ocr_spelling_is_refused_for_a_third_party(self):
        assert names_a_party("ForInformationalPurposesOnly", third_party=True) is False

    def test_the_insureds_own_boxes_are_judged_exactly_as_before(self):
        assert names_a_party("ForInformationalPurposesOnly") is True

    @pytest.mark.parametrize("value", [
        "CRSInsuranceBrokerage", "OrbinContracting,LLC", "EMCProperty&CasualtyCompany",
        "McCarthyBuildingCompanies", "Kiewit", "InTownSuitesLLC"])
    def test_run_together_real_names_survive(self, value):
        assert names_a_party(value, third_party=True) is True

    def test_the_interest_box_refuses_the_ocr_spelling(self):
        mapped = {"AdditionalInterest_FullName_A": "ForInformationalPurposesOnly"}
        _enforce_post_fill_guards(mapped, _schema("ACORD_127"), {},
                                  gpt_filled_set=set(mapped))
        assert mapped["AdditionalInterest_FullName_A"] is None

    def test_the_named_insured_box_is_untouched(self):
        mapped = {"NamedInsured_FullName_A": "Orbin Contracting LLC"}
        _enforce_post_fill_guards(mapped, _schema("ACORD_125"), {},
                                  gpt_filled_set=set(mapped))
        assert mapped["NamedInsured_FullName_A"] == "Orbin Contracting LLC"
