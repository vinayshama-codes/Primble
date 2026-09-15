"""Client Orbin audit 2026-09-11, items 2 / 4 / 5 / 6 / 8 / 10.

Four root causes, one test class each:

  * coverage truth had two channels and only one was gated   -> item 2
  * facts carried no ROLE, so the expiring agency out-voted
    the submitting one on page count                         -> item 4
  * facts and boxes carried no TYPE, so an amount could bind
    to a checkbox and any string could be a rival answer     -> items 5, 10
  * codes had no LINE fence                                  -> item 6
  * party boxes had no entity test                           -> item 8

Written as invariants and shapes, not as the reported sentences - every one of
these defects was first patched as a phrase and came back in another wording.
"""

import json
import os
import random

import pytest

from services.extraction_service import _route_producer_identity
from services.field_mapping_integrity import is_party_name_field, names_a_party
from services.lob_canon import carried_lines_of_business
from services.pdf_service import (
    _cross_line_code_borrows,
    _enforce_post_fill_guards,
    _line_code_witnesses,
    _resolve_submitting_producer,
    _SCHED_SKIP,
    fact_to_form_fields,
)
from services.underwriting_consistency import _drop_values_outside_declared_domain

_SCHEMA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "forms_schemas")


def _schema(form_id):
    with open(os.path.join(_SCHEMA_DIR, f"{form_id}_schema.json"), encoding="utf-8") as fh:
        return json.load(fh)


# ─────────────────────────────────────────────────────────────────────────────
# ITEM 2 - coverage requires affirmative evidence
# ─────────────────────────────────────────────────────────────────────────────
class TestCarriedLinesOfBusiness:

    # The ISO endorsement header, which is a MENU of what the endorsement could
    # attach to. The client's phantom list is this, word for word.
    BOILERPLATE = ["Commercial Property", "Crime and Fidelity", "Workers Compensation",
                   "Farm", "Liquor Liability", "Employment-Related Practices",
                   "Owners and Contractors Protective"]
    REAL = ["Commercial General Liability", "Business Auto", "Inland Marine",
            "Commercial Liability Umbrella"]

    def _facts(self):
        return {
            "lines_of_business": self.REAL + self.BOILERPLATE,
            "coverage_lines": [
                {"line": "General Liability", "carrier": "EMC P&C", "policy_number": "B1"},
                {"line": "Business Auto", "carrier": "EMC", "policy_number": "A1"},
                {"line": "Inland Marine", "carrier": "EMC", "policy_number": "I1"},
                {"line": "Commercial Liability Umbrella", "carrier": "EMC",
                 "policy_number": "U1"},
                {"line": "Commercial Property", "premium": "No Coverage"},
                {"line": "Crime and Fidelity", "premium": "No Coverage"},
                {"line": "Workers Compensation", "premium": "No Coverage"},
            ],
        }

    def test_only_evidenced_lines_are_reported_as_carried(self):
        assert carried_lines_of_business(self._facts(), {}) == self.REAL

    @pytest.mark.parametrize("phantom", BOILERPLATE)
    def test_every_phantom_line_is_dropped(self, phantom):
        assert phantom not in carried_lines_of_business(self._facts(), {})

    def test_a_line_with_a_policy_but_no_premium_still_counts(self):
        """The same lesson as the identity fix: a dec page showing one package
        total leaves every row unpriced, and those lines are still carried."""
        facts = {"lines_of_business": ["Commercial General Liability"],
                 "coverage_lines": [{"line": "General Liability", "carrier": "EMC",
                                     "policy_number": "B1"}]}
        assert carried_lines_of_business(facts, {}) == ["Commercial General Liability"]

    def test_a_coverage_flag_corroborates(self):
        facts = {"lines_of_business": ["Cyber Liability", "Farm"],
                 "coverage_lines": [{"line": "General Liability", "carrier": "X"}]}
        assert carried_lines_of_business(facts, {"has_cyber": True}) == ["Cyber Liability"]

    def test_no_per_line_evidence_at_all_keeps_the_raw_list(self):
        """The legacy branch. A package whose `coverage_lines` never arrived
        must not have its whole inventory blanked."""
        facts = {"lines_of_business": ["Farm", "Liquor Liability"]}
        assert carried_lines_of_business(facts, {}) == ["Farm", "Liquor Liability"]

    @pytest.mark.parametrize("facts", [None, {}, {"lines_of_business": None},
                                       {"lines_of_business": "not a list"},
                                       {"lines_of_business": []}])
    def test_malformed_input_never_raises(self, facts):
        assert carried_lines_of_business(facts, None) == []

    def test_the_cover_page_reads_the_same_door(self):
        from services.cover_service import _cover_lines_of_business
        assert _cover_lines_of_business(self._facts()) == self.REAL


# ─────────────────────────────────────────────────────────────────────────────
# ITEM 4 - the expiring producer is not the submitting producer
# ─────────────────────────────────────────────────────────────────────────────
class TestProducerRole:

    @staticmethod
    def _doc(doc_type, name):
        return {"doc_type": doc_type,
                "facts": {"producer_name": name} if name else {}}

    def test_the_submission_outranks_271_page_headers(self):
        mf = {"producer_name": "Commercial Risk Solutions"}
        _route_producer_identity(mf, [
            self._doc("dec_page", "Commercial Risk Solutions"),
            self._doc("policy", "Commercial Risk Solutions"),
            self._doc("narrative", "ThinkSmith Agency")])
        assert mf["producer_name"] == "ThinkSmith Agency"
        assert mf["expiring_producer_name"] == "Commercial Risk Solutions"

    def test_an_expiring_only_producer_is_recorded_not_removed(self):
        """Nothing in the documents can tell an incumbent broker re-marketing
        their own account from a genuine change of agency, so silence leaves
        `producer_name` exactly as it was."""
        mf = {"producer_name": "CRS Insurance Brokerage"}
        _route_producer_identity(mf, [self._doc("certificate", "CRS Insurance Brokerage")])
        assert mf["producer_name"] == "CRS Insurance Brokerage"
        assert mf["expiring_producer_name"] == "CRS Insurance Brokerage"

    def test_two_submission_documents_disagreeing_is_not_resolved(self):
        mf = {"producer_name": "A Agency"}
        _route_producer_identity(mf, [self._doc("application", "A Agency"),
                                      self._doc("quote", "B Agency")])
        assert mf["producer_name"] == "A Agency"

    def test_one_agency_printed_two_ways_is_one_agency(self):
        mf = {"producer_name": "ThinkSmith Agency, Inc."}
        _route_producer_identity(mf, [
            self._doc("application", "ThinkSmith Agency Inc"),
            self._doc("dec_page", "ThinkSmith Agency, Inc.")])
        assert mf["producer_name"] == "ThinkSmith Agency, Inc."
        assert "expiring_producer_name" not in mf

    @pytest.mark.parametrize("docs", [None, [], "junk", [None, 7], [{}]])
    def test_malformed_docs_never_raise(self, docs):
        mf = {"producer_name": "X"}
        assert _route_producer_identity(mf, docs) == []
        assert mf["producer_name"] == "X"

    def test_the_producer_box_is_an_owned_blank_once_only_the_old_agency_is_known(self):
        facts = {"_form_id": "ACORD_125", "producer_name": "",
                 "expiring_producer_name": "Commercial Risk Solutions"}
        assert _resolve_submitting_producer("Producer_FullName_A", facts) is None

    def test_a_known_submitting_producer_takes_the_normal_path(self):
        facts = {"_form_id": "ACORD_125", "producer_name": "ThinkSmith Agency",
                 "expiring_producer_name": "Commercial Risk Solutions"}
        assert _resolve_submitting_producer(
            "Producer_FullName_A", facts) is _SCHED_SKIP

    def test_a_legacy_session_is_untouched(self):
        facts = {"_form_id": "ACORD_125", "producer_name": "ThinkSmith Agency"}
        assert _resolve_submitting_producer(
            "Producer_FullName_A", facts) is _SCHED_SKIP


# ─────────────────────────────────────────────────────────────────────────────
# ITEMS 5 + 10 - an amount is not a tick, and an illegal value is not a rival
# ─────────────────────────────────────────────────────────────────────────────
class TestTypedBindingsAndComparisons:

    def test_a_currency_fact_no_longer_binds_to_a_checkbox(self):
        for form, fields in fact_to_form_fields("gl_aggregate").items():
            schema = _schema(form)
            for f in fields:
                assert (schema.get(f) or {}).get("ft") != "/Btn", (form, f)

    def test_a_choice_fact_still_drives_its_checkboxes(self):
        """ACORD expresses a choice AS checkboxes - that binding is correct and
        must survive."""
        fields = fact_to_form_fields("gl_form_type").get("ACORD_126", ())
        assert "GeneralLiability_ClaimsMadeIndicator_A" in fields
        assert "GeneralLiability_OccurrenceIndicator_A" in fields

    def test_no_measured_fact_anywhere_binds_to_a_checkbox(self):
        from services import fact_registry as fr
        measured = {k for k, m in fr.FACT_REGISTRY.items()
                    if (m or {}).get("validate") in (
                        fr._is_currency, fr._is_date, fr._is_percent,
                        fr._is_positive_int)}
        bad = []
        for key in measured:
            for form, fields in fact_to_form_fields(key).items():
                schema = _schema(form)
                bad += [(key, form, f) for f in fields
                        if (schema.get(f) or {}).get("ft") == "/Btn"]
        assert bad == []

    # THE SHAPE THE LOOP ACTUALLY BUILDS. Written from a live run, 11 Sep.
    #
    # The first version of these tests passed `{"value": ...}` and every one of
    # them was green while the filter was INERT in production: a candidate is a
    # GROUP - `{normalized, display, sources: [{raw, ...}]}` - with no `value`
    # key at all, so the check received None for every candidate and let the
    # whole lot through. The live run printed a card comparing `is_renewal`
    # "true" with "Renewal of BBC7263 - 25".
    #
    # D22, exactly: the fixture was easier than reality. These build the real
    # shape, and `test_the_group_shape_is_the_one_the_engine_builds` below
    # pins it against the engine itself so the two cannot drift again.
    @staticmethod
    def _group(display, *raws):
        return {"normalized": display.lower(), "display": display,
                "sources": [{"doc_id": "1", "filename": "a.pdf", "raw": r}
                            for r in (raws or (display,))]}

    def test_an_illegal_value_is_not_a_rival_answer(self):
        vals = [self._group("Occurrence"),
                self._group("Commercial Liability Umbrella Coverage Form")]
        kept = _drop_values_outside_declared_domain("gl_form_type", vals)
        assert [v["display"] for v in kept] == ["Occurrence"]

    def test_an_open_vocabulary_boolean_is_left_to_the_lexicon(self):
        """`is_renewal` "true" vs "Renewal of BBC7263 - 25" is NOT this
        filter's defect, and claiming it was cost six SYS-07c tests.

        Documents express Yes/No in open vocabulary - "Underwritten", "X", a
        tick - and `yes_no_lexicon` exists to learn those words rather than let
        the system decide. A registry validator applied here deleted the very
        cards that module raises. "Renewal of BBC7263 - 25" is the DOCUMENT's
        way of saying yes: a normalisation job, not a wrong value.

        So the domain check reads a CLOSED option list only. A fact without one
        passes through untouched."""
        vals = [self._group("true"), self._group("Renewal of BBC7263 - 25")]
        assert len(_drop_values_outside_declared_domain("is_renewal", vals)) == 2

    def test_a_non_answer_on_a_closed_list_fact_still_reaches_the_producer(self):
        """An absence is not a wrong value - it is the producer's question."""
        vals = [self._group("Occurrence"), self._group("TBD")]
        assert len(_drop_values_outside_declared_domain("gl_form_type", vals)) == 2

    def test_two_legal_values_still_conflict(self):
        vals = [self._group("Occurrence"), self._group("Claims-Made")]
        assert len(_drop_values_outside_declared_domain("gl_form_type", vals)) == 2

    def test_all_illegal_keeps_everything(self):
        """No basis to prefer one, so the row renders as it does today."""
        vals = [self._group("CG 00 01 04 13"), self._group("IL 00 17 11 98")]
        assert len(_drop_values_outside_declared_domain("gl_form_type", vals)) == 2

    def test_one_bad_printing_never_condemns_a_good_candidate(self):
        """A candidate is legal if ANY of its printings is - one OCR-damaged
        source must not delete a value the other documents print correctly."""
        vals = [self._group("Occurrence", "0ccurrence", "Occurrence"),
                self._group("Claims-Made")]
        assert len(_drop_values_outside_declared_domain("gl_form_type", vals)) == 2

    def test_a_fact_with_no_declared_domain_is_untouched(self):
        vals = [self._group("anything"), self._group("at all")]
        assert len(_drop_values_outside_declared_domain(
            "operations_description", vals)) == 2

    def test_two_spellings_of_one_name_are_both_kept(self):
        vals = [self._group("ORBIN CONTRACTING LLC"),
                self._group("Orbin Contracting, L.L.C.")]
        assert len(_drop_values_outside_declared_domain("applicant_name", vals)) == 2

    def test_the_group_shape_is_the_one_the_engine_builds(self):
        """Drive the REAL engine and assert the filter bites end to end.

        The unit tests above can only prove the filter works on the shape they
        invent. This one takes the shape from the engine, which is the only
        thing that could have caught the live defect.
        """
        from services.underwriting_consistency import (
            assess_underwriting_consistency)
        docs = [
            {"doc_id": "1", "filename": "dec.pdf", "doc_type": "dec_page",
             "text": "", "facts": {"gl_form_type": "Occurrence"}},
            {"doc_id": "2", "filename": "narr.pdf", "doc_type": "narrative",
             "text": "", "facts": {"gl_form_type": "claims-made"}},
        ]
        res = assess_underwriting_consistency(
            docs, {"gl_form_type": "claims-made"}, {})
        by_key = {f.get("fact_key"): f for f in res.get("fields", [])}
        # Two LEGAL values still conflict. If this one ever flips, the
        # filter has over-reached and real disagreements are being hidden.
        assert by_key["gl_form_type"]["status"] == "conflict"
        assert {v.get("display") for v in by_key["gl_form_type"]["values"]} == {
            "Occurrence", "claims-made"}
        docs[1]["facts"]["gl_form_type"] = (
            "Commercial Liability Umbrella Coverage Form")
        res2 = assess_underwriting_consistency(
            docs, {"gl_form_type": "Occurrence"}, {})
        by2 = {f.get("fact_key"): f for f in res2.get("fields", [])}
        assert by2.get("gl_form_type", {}).get("status") != "conflict"


# ─────────────────────────────────────────────────────────────────────────────
# ITEM 6 - a code belongs to the line whose schedule prints it
# ─────────────────────────────────────────────────────────────────────────────
class TestCrossLineCodes:

    FACTS = {
        "_form_id": "ACORD_127",
        "gl_class_code_schedule": [
            {"class_code": "91580", "classification": "Contractors", "territory": "005"},
            {"class_code": "91585", "classification": "Subcontracted"}],
        "wc_class_codes": [{"code": "5403", "state": "CO"}],
        "auto_vin_schedule": [{"vin": "4S4BRCGC9C3217772", "rate_class_code": "7383"}],
    }

    def test_the_witness_index_is_derived_from_the_fact_keys(self):
        w = _line_code_witnesses(self.FACTS)
        assert w["91580"] == {"general_liab"}
        assert w["5403"] == {"workers_comp"}
        assert w["7383"] == {"auto"}

    @pytest.mark.parametrize("value,blanked", [
        ("91580", True),    # a GL contractor class - the client's report
        ("5403", True),     # a WC class code
        ("005", True),      # a GL territory
        ("7383", False),    # the vehicle's own class
    ])
    def test_the_vehicle_rating_row(self, value, blanked):
        mapped = {"Vehicle_RateClassCode_A": value}
        _enforce_post_fill_guards(mapped, _schema("ACORD_127"), self.FACTS,
                                  gpt_filled_set=set(mapped))
        assert (mapped["Vehicle_RateClassCode_A"] is None) is blanked

    def test_it_fences_the_auto_form_against_gl_codes(self):
        """The direction the client reported, and the one that works."""
        facts = dict(self.FACTS, _form_id="ACORD_126")
        mapped = {"GeneralLiability_Hazard_ClassCode_A": "7383"}
        _enforce_post_fill_guards(mapped, _schema("ACORD_126"), facts,
                                  gpt_filled_set=set(mapped))
        assert mapped["GeneralLiability_Hazard_ClassCode_A"] is None

    def test_the_fence_is_BIDIRECTIONAL_since_v19(self):
        """WAS one-directional. Live run 1 (11 Sep) measured the cost, v19 paid it.

        `_line_code_witnesses` reads code-bearing sub-keys off schedule facts.
        Before v19 the extraction schema declared NO class / code / territory
        column on ANY auto schedule:

            gl_class_code_schedule   class_code, classification, territory  OK
            wc_class_codes           code                                   OK
            auto_vin_schedule        year make model vin body_type gvw      NONE

        So a GL code landing in a vehicle box was caught and a VEHICLE code
        landing in a GL box could not be - nothing witnessed it. Live: ACORD
        126's hazard grid printed the vehicle class `7398` twice, and the Drive
        Other Car territory `6679` once, on a package whose auto schedule
        carried neither.

        v19 adds `class_code` and `territory` to `auto_vin_schedule`. Both
        directions are now witnessed, and BOTH are asserted here.

        The first version of this test asserted the symmetric case and passed
        while the code could not do it, because the FIXTURE invented
        `rate_class_code` on the vehicle row - a key the schema did not
        produce. D22. Every fixture below uses only v19-declared sub-keys, and
        `test_every_witness_subkey_is_declared_in_the_extraction_schema` fails
        the build if that stops being true.
        """
        auto = {"_form_id": "ACORD_126",
                "auto_vin_schedule": [{"vin": "1FT7W2BT5KEC12345",
                                       "make": "Ford", "year": "2019",
                                       "model": "F-250",
                                       "class_code": "7398",
                                       "territory": "6679",
                                       "coll_symbol": "07",
                                       "comp_symbol": "07"}]}
        witnesses = _line_code_witnesses(auto)
        assert witnesses.get("7398") == {"auto"}, witnesses
        assert witnesses.get("6679") == {"auto"}, witnesses

        # ...and the vehicle's own numbers are now refused by the GL form.
        mapped = {"CommercialGeneralLiability_ClassificationCode_A": "7398",
                  "CommercialGeneralLiability_TerritoryCode_A": "6679"}
        _enforce_post_fill_guards(mapped, _schema("ACORD_126"), auto,
                                  gpt_filled_set=set(mapped))
        assert mapped["CommercialGeneralLiability_ClassificationCode_A"] is None
        assert mapped["CommercialGeneralLiability_TerritoryCode_A"] is None

    def test_a_real_gl_code_still_survives_on_the_gl_form(self):
        """The other half of bidirectional: widening the fence must not start
        blanking the GL form's OWN codes. The client's 91580 / 91585 printed
        correctly on ACORD 126 in live run 1 and must keep doing so."""
        facts = {"_form_id": "ACORD_126",
                 "gl_class_code_schedule": [{"class_code": "91580",
                                             "classification": "Contractors"},
                                            {"class_code": "91585",
                                             "classification": "Carpentry"}],
                 "auto_vin_schedule": [{"vin": "4S4BRCGC9C3217772",
                                        "class_code": "7383"}]}
        mapped = {"CommercialGeneralLiability_ClassificationCode_A": "91580",
                  "CommercialGeneralLiability_ClassificationCode_B": "91585"}
        _enforce_post_fill_guards(mapped, _schema("ACORD_126"), facts,
                                  gpt_filled_set=set(mapped))
        assert mapped["CommercialGeneralLiability_ClassificationCode_A"] == "91580"
        assert mapped["CommercialGeneralLiability_ClassificationCode_B"] == "91585"

    def test_every_witness_subkey_is_declared_in_the_extraction_schema(self):
        """THE ANTI-ROT GUARD for the defect class this session hit THREE times.

        Every one was a check reading a key the extraction schema never emits,
        with a test fixture that invented the key:

          1. `_drop_values_outside_declared_domain` read `group["value"]`
          2. `_LINE_EVIDENCE_KEYS` includes "limit"; `coverage_lines` has none
          3. the witness index reads `*class*` off `auto_vin_schedule`

        This fails the build if a schedule fact that CAN witness stops
        declaring the sub-key that lets it, and it prints the full witness
        census so the asymmetry above can never be assumed away again.
        """
        import re as _re
        src = open(os.path.join(
            os.path.dirname(_SCHEMA_DIR), "services", "extraction_service.py"),
            encoding="utf-8").read()
        declared = {}
        for m in _re.finditer(r'"([a-z_]+)":\s*\[\{(.*?)\}\]', src):
            declared[m.group(1)] = _re.findall(r'"([a-z_]+)"\s*:', m.group(2))
        # The two the guard is DOCUMENTED to rely on must keep their columns.
        assert any(_re.search(r"(code|class|territory)", s)
                   for s in declared.get("gl_class_code_schedule", [])), \
            "gl_class_code_schedule lost its code column - the guard goes blind"
        assert any(_re.search(r"(code|class|territory)", s)
                   for s in declared.get("wc_class_codes", [])), \
            "wc_class_codes lost its code column - the guard goes blind"
        # v19 CLOSED the auto side, and the fence's other direction now
        # depends on it. Losing these two columns would silently restore the
        # one-directional limit AND un-fill ACORD 127's CLASS box, so the
        # requirement is asserted rather than assumed.
        _auto_cols = declared.get("auto_vin_schedule", [])
        assert "class_code" in _auto_cols, (
            "auto_vin_schedule lost `class_code` - ACORD 127's CLASS box falls "
            "back to gap fill and the cross-line fence goes one-directional "
            "again (live run 1: a GL contractor class on the Subaru)")
        assert "territory" in _auto_cols, (
            "auto_vin_schedule lost `territory` - nothing witnesses a Drive "
            "Other Car territory and 6679 returns to the GL hazard grid")

    def test_no_witness_means_no_opinion(self):
        mapped = {"Vehicle_RateClassCode_A": "91580"}
        _enforce_post_fill_guards(mapped, _schema("ACORD_127"),
                                  {"_form_id": "ACORD_127"},
                                  gpt_filled_set=set(mapped))
        assert mapped["Vehicle_RateClassCode_A"] == "91580"

    def test_a_code_two_lines_share_is_never_judged(self):
        facts = {"_form_id": "ACORD_127",
                 "gl_class_code_schedule": [{"class_code": "1234"}],
                 "auto_vin_schedule": [{"rate_class_code": "1234"}]}
        assert _cross_line_code_borrows(
            {"Vehicle_RateClassCode_A": "1234"}, {}, facts) == {}

    def test_short_values_are_never_judged(self):
        facts = {"_form_id": "ACORD_127",
                 "gl_class_code_schedule": [{"class_code": "12"}]}
        assert _cross_line_code_borrows(
            {"Vehicle_RateClassCode_A": "12"}, {}, facts) == {}

    @pytest.mark.parametrize("facts", [None, {}, "junk", {"gl_class_code_schedule": "x"}])
    def test_malformed_facts_never_raise(self, facts):
        assert _line_code_witnesses(facts) == {}


# ─────────────────────────────────────────────────────────────────────────────
# ITEM 8 - a party box must hold a party
# ─────────────────────────────────────────────────────────────────────────────
class TestPartyIdentity:

    REAL = ["ORBIN CONTRACTING LLC", "Kestrel Terminal Authority",
            "First National Bank of Denver", "John A. Smith", "City of Aurora",
            "Wells Fargo Equipment Finance, Inc.", "The Bank of New York Mellon",
            "Smith & Sons Construction", "CO DEPT OF TRANSPORTATION", "Jane Doe",
            "U.S. Bank National Association", "Denver Public Schools",
            "Caterpillar Financial Services Corp", "Acme",
            "Kestrel Terminal Authority, 1201 Port of Tacoma Rd, Tacoma WA 98421"]
    NOT_A_PARTY = ["For Informational Purposes Only", "If applicable",
                   "THIS CERTIFICATE IS ISSUED AS A MATTER OF INFORMATION ONLY",
                   "As respects the work performed", "Subject to the terms",
                   "See policy", "Coverage is provided", "per written contract",
                   "in favor of the certificate holder", "Named insured is included",
                   "This certificate does not confer rights", "for informational purposes",
                   "none", "TBD", "Insured is an additional insured"]

    @pytest.mark.parametrize("value", REAL)
    def test_real_parties_are_accepted(self, value):
        assert names_a_party(value) is True

    @pytest.mark.parametrize("value", NOT_A_PARTY)
    def test_boilerplate_is_refused(self, value):
        assert names_a_party(value) is False

    @pytest.mark.parametrize("value", [None, "", "  ", 42, [], {}])
    def test_junk_is_refused_without_raising(self, value):
        assert names_a_party(value) is False

    def test_the_client_reported_value_is_blanked_on_the_form(self):
        mapped = {"AdditionalInterest_FullName_A": "For Informational Purposes Only"}
        _enforce_post_fill_guards(mapped, _schema("ACORD_125"), {},
                                  gpt_filled_set=set(mapped))
        assert mapped["AdditionalInterest_FullName_A"] is None

    def test_a_real_additional_interest_survives(self):
        mapped = {"AdditionalInterest_FullName_A": "Wells Fargo Equipment Finance, Inc."}
        _enforce_post_fill_guards(mapped, _schema("ACORD_125"), {},
                                  gpt_filled_set=set(mapped))
        assert mapped["AdditionalInterest_FullName_A"] == \
            "Wells Fargo Equipment Finance, Inc."

    def test_a_non_party_box_is_not_policed(self):
        mapped = {"GeneralLiability_Hazard_Classification_A":
                  "For Informational Purposes Only"}
        _enforce_post_fill_guards(mapped, _schema("ACORD_126"), {},
                                  gpt_filled_set=set(mapped))
        assert mapped["GeneralLiability_Hazard_Classification_A"] == \
            "For Informational Purposes Only"

    def test_the_party_box_detector_is_derived_from_acord_naming(self):
        import glob
        seen = 0
        for path in glob.glob(os.path.join(_SCHEMA_DIR, "ACORD_*_schema.json")):
            for name in json.load(open(path, encoding="utf-8")):
                if is_party_name_field(name):
                    seen += 1
                    assert "Name" in name
        assert seen > 40

    def test_a_random_sweep_never_accepts_a_clause(self):
        rnd = random.Random(11)
        openers = ["For", "If", "Subject to", "As respects", "This", "Per",
                   "In accordance with", "Where", "When", "Pursuant to"]
        tails = ["only", "applicable", "required", "attached", "as noted"]
        bad = []
        for _ in range(500):
            phrase = (f"{rnd.choice(openers)} the "
                      f"{rnd.choice(['policy', 'contract', 'certificate', 'coverage'])} "
                      f"{rnd.choice(tails)}")
            if names_a_party(phrase):
                bad.append(phrase)
        assert bad == []
