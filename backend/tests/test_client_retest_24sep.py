"""Client re-test, 22 Sep 2026: the 11 Orbin items, fixed at their root cause.

The 11 Sep fixes passed 1,287 tests on the deployed build while the client's
real three-document package still failed. The tests were not wrong about what
they checked - their fixtures were cleaner than the client's documents:
spaced certificate text where the real OCR runs words together, ISO-only form
numbers where EMC prints its own, a synchronous generation path where
production runs the async worker. Every test here is written from the REAL
shapes: the certificate's own run-together strings, the carrier's own form
numbers, and the real 271-page policy text for the vehicle, garaging and
named-individual readers.

Offline: no database, no LLM (`map_facts_to_form(..., raw_text="")` skips gap
fill). One section per client item.
"""
import copy
import json
import os
import random
import string
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import services.extraction_service as es                     # noqa: E402
import services.pdf_service as ps                            # noqa: E402
from services import normalization as norm                   # noqa: E402
from services.extraction_service import merge_facts, select_primary_truth  # noqa: E402

BACKEND = os.path.join(os.path.dirname(__file__), "..")
REAL_TEXT = os.path.join(BACKEND, "..", "271page_test_data", "271page-testdec.txt")


def _schema(form_id):
    with open(os.path.join(BACKEND, "forms_schemas", f"{form_id}_schema.json"),
              encoding="utf-8") as fh:
        return json.load(fh)


def _env(value):
    return {"value": value, "source": "ai", "confidence": "ai_high"}


def _v(raw):
    return raw.get("value") if isinstance(raw, dict) and "value" in raw else raw


def _real_text():
    if not os.path.exists(REAL_TEXT):
        pytest.skip("the 271-page Orbin text is not in this checkout")
    with open(REAL_TEXT, encoding="utf-8") as fh:
        return fh.read()


# The client's certificate, as its OCR actually reads (run together).
GLUED_GL = "EMCProperty&CasualtyCompany"
GLUED_AUTO = "EmployersMutualCasualtyCo."
GLUED_HOLDER = "ForInformationalPurposesOnly"
GLUED_REMARK = "Note:ReducedUmbrellaLimitfrom$3,000,000to$1,000,000LimitEffective7/25/25."

# The carrier's OWN form numbers the Orbin package prints, and its real
# policy / account numbers.
EMC_FORMS = ["IM 7100 06 04", "IM 7201 10 02", "CU7001A 11-15", "CU7001A(11/15)",
             "CA7450 M", "CA7000A 02-22", "IL 71 31A 04 01", "CG 70 01A 10 12",
             "CG 00 01 04 13", "IM7100(06/04)"]
REAL_POLICIES = ["BBC7263-26", "BBC7263 - 26", "BBC7263", "6E7-40-02---26",
                 "6C7-40-02---26", "6J7-40-02---26", "6E74002", "BOP 7654321 01 26",
                 "SRC-4410982", "LSG-4471102-26", "QPC5519 - 26", "SIM-7730418"]


# =============================================================================
# Item 1 - one company printed with its spaces lost is still one company
# =============================================================================
class TestItem1CarrierIdentity:

    @pytest.mark.parametrize("glued, spaced", [
        (GLUED_GL, "EMC PROPERTY & CASUALTY COMPANY"),
        (GLUED_AUTO, "Employers Mutual Casualty Company"),
        ("EMPLOYERSMUTUALCASUALTYCO", "Employers Mutual Casualty Company"),
        ("EMCPROPERTY&CASUALTYCOMPANY", "EMC Property & Casualty Company"),
    ])
    def test_a_glued_printing_is_the_same_entity(self, glued, spaced):
        assert norm.same_entity_name(glued, spaced)
        assert not norm.entity_identity_conflict([glued, spaced])

    @pytest.mark.parametrize("a, b", [
        ("EMC Property & Casualty Company", "Employers Mutual Casualty Company"),
        ("Orbin Contracting LLC", "Orbin Contracting Inc"),
        (GLUED_GL, GLUED_AUTO),
    ])
    def test_two_real_companies_still_conflict(self, a, b):
        assert not norm.same_entity_name(a, b)
        assert norm.entity_identity_conflict([a, b])

    @pytest.mark.parametrize("value", [
        GLUED_GL, GLUED_AUTO, "Employers Mutual Casualty Co.",
        "Employers Mutual Casualty Company", "EMC Prop & Cas Co"])
    def test_every_emc_printing_is_one_family(self, value):
        """"Co." fell through to 'employers' while "Company" answered 'emc' -
        the "Multiple carriers referenced" warning on one carrier group."""
        assert norm.normalize_carrier(value) == "emc"

    def test_the_glued_agency_is_the_same_agency(self):
        from services.fact_comparison import same_agency
        assert same_agency("CommercialRiskSolutions,Inc.",
                           "COMMERCIAL RISK SOLUTIONS, INC.") is True

    @pytest.mark.parametrize("glued, printed", [
        (GLUED_GL, "EMC Property & Casualty Company"),
        ("CommercialRiskSolutions,Inc.", "Commercial Risk Solutions, Inc."),
    ])
    def test_a_glued_name_is_printed_with_its_spaces(self, glued, printed):
        from services.display_canonicalizer import canonicalize_for_field
        assert canonicalize_for_field("Insurer_FullName_A", glued) == printed

    @pytest.mark.parametrize("brand", ["InTownSuitesLLC", "ThinkSmith Agency", "McDonald",
                                       "iPhone Repair LLC"])
    def test_a_real_glued_brand_is_never_rewritten(self, brand):
        assert norm.deglue_entity_text(brand, for_display=True) == brand


# =============================================================================
# Item 3 - a form number (or the account number) is never a policy number
# =============================================================================
class TestItem3FormNumbers:

    @pytest.mark.parametrize("form", EMC_FORMS)
    def test_every_form_number_the_package_prints_is_recognised(self, form):
        assert norm.looks_like_a_form_number(form)
        assert ps._looks_like_a_form_number(form)
        assert es._looks_like_a_form_number(form)

    @pytest.mark.parametrize("policy", REAL_POLICIES)
    def test_no_real_policy_number_is_mistaken_for_one(self, policy):
        assert not norm.looks_like_a_form_number(policy)

    def test_twenty_thousand_policy_shaped_values_are_never_forms(self):
        rng = random.Random(24)
        shapes = ["LLLddddddd", "LLL-dddddd-dd", "dLd-dd-dd---dd", "LLLdddd-dd",
                  "LL dddddddd", "LLLdddddd", "LL-ddd-ddd", "dd-LL-dddddd-d"]
        for _ in range(20000):
            v = "".join(rng.choice(string.ascii_uppercase) if c == "L"
                        else rng.choice(string.digits) if c == "d" else c
                        for c in rng.choice(shapes))
            assert not norm.looks_like_a_form_number(v), v

    def test_the_account_number_is_refused_only_on_its_own_label(self):
        entries = [{"label": "Account Number", "value": "0482854"},
                   {"label": "POLICY NUMBER", "value": "6E7-40-02---26"}]
        assert norm.is_not_a_policy_number("0482854", entries)
        assert not norm.is_not_a_policy_number("0482854", [])
        assert not norm.is_not_a_policy_number("6E7-40-02---26", entries)

    def test_a_value_printed_as_a_policy_number_is_a_policy_number(self):
        entries = [{"label": "Policy No.", "value": "BM 1234 05 21"}]
        assert norm.looks_like_a_form_number("BM 1234 05 21")
        assert not norm.is_not_a_policy_number("BM 1234 05 21", entries)

    @pytest.mark.parametrize("form", ["CU7001A 11-15", "CA7450 M", "CG 70 01A 10 12"])
    def test_the_card_and_confirmation_refuse_a_carrier_form(self, form):
        from services.underwriting_consistency import _is_form_number_policy_value
        assert _is_form_number_policy_value("policy_number", form)

    def test_the_policy_box_never_prints_a_carrier_form(self):
        f = {"_form_id": "ACORD_127", "policy_number": _env("CU7001A 11-15")}
        mapped, _c = ps.map_facts_to_form(f, _schema("ACORD_127"), form_id="ACORD_127",
                                          raw_text="")
        assert not str(mapped.get("Policy_PolicyNumberIdentifier_A") or "").strip()


class TestItem3OtherPolicyListRestored:
    LINES = [
        {"line": "General Liability", "carrier": "EMC Property & Casualty Company",
         "policy_number": "BBC7263 - 26", "premium": "$3,954.00"},
        {"line": "Commercial Auto", "carrier": "Employers Mutual Casualty Company",
         "policy_number": "6E7-40-02---26", "premium": "$2,991.00"},
        {"line": "Inland Marine", "carrier": "Employers Mutual Casualty Company",
         "policy_number": "6C7-40-02---26", "premium": "$300.00"},
        {"line": "Umbrella", "carrier": "Employers Mutual Casualty Company",
         "policy_number": "6J7-40-02---26", "premium": "$3,418.00"},
        {"line": "Workers' Compensation", "policy_number": "6C7-40-02---26",
         "premium": "No Coverage"},
    ]

    def _facts(self):
        return {"_form_id": "ACORD_125", "coverage_lines": copy.deepcopy(self.LINES),
                "carrier_is_current_policy": True,
                "carrier_name": {"value": "Employers Mutual Casualty Company", "source": "ai"}}

    def test_the_four_policies_print_each_with_its_own_number(self):
        f = self._facts()
        numbers = {ps._resolve_other_policy_cell(f"OtherPolicy_PolicyNumberIdentifier_{r}", f)
                   for r in "ABCD"}
        assert numbers == {"BBC7263 - 26", "6E7-40-02---26", "6C7-40-02---26", "6J7-40-02---26"}

    def test_the_yes_no_follows_the_list(self):
        assert ps._resolve_page_one_receiving_carrier(
            "CommercialPolicy_Question_AAHCode_A", self._facts()) == "Y"

    def test_a_denied_line_takes_no_row(self):
        f = self._facts()
        labels = {ps._resolve_other_policy_cell(f"OtherPolicy_LineOfBusinessCode_{r}", f)
                  for r in "ABCD"}
        assert not any("compensation" in str(x or "").lower() for x in labels)


# =============================================================================
# Item 2 - a line the package does not carry is never offered, compared or ticked
# =============================================================================
class TestItem2CarriedLines:
    ROWS = [{"line": "Liability", "premium": "$3,954.00", "policy_number": "BBC7263-26"},
            {"line": "Inland Marine", "premium": "$300.00", "policy_number": "6C7-40-02---26"},
            {"line": "Automobile", "premium": "$2,991.00", "policy_number": "6E7-40-02---26"},
            {"line": "Umbrella", "premium": "$3,418.00", "policy_number": "6J7-40-02---26"},
            {"line": "Property", "premium": "No Coverage"},
            {"line": "Workers Compensation", "premium": "No Coverage"},
            # the ISO endorsement MENU rows, one carrying the GL footer number
            {"line": "Liquor Liability Coverage Part", "policy_number": "BBC7263"},
            {"line": "Pollution Liability Coverage Part", "naic": "21415"}]

    def test_menu_rows_and_denied_lines_are_not_carried(self):
        from services.lob_canon import line_is_carried
        facts = {"coverage_lines": copy.deepcopy(self.ROWS)}
        for fam in ("liquor", "pollution", "property", "workers_comp", "crime"):
            assert line_is_carried(fam, facts, {}) is False, fam
        for fam in ("general_liab", "auto", "umbrella", "inland_marine"):
            assert line_is_carried(fam, facts, {}) is True, fam

    def test_no_evidence_means_cannot_tell(self):
        from services.lob_canon import line_is_carried
        assert line_is_carried("property", {}, {}) is None

    @pytest.mark.parametrize("key, fam", [("property_building_value", "property"),
                                          ("year_built", "property"),
                                          ("gl_aggregate", "general_liab"),
                                          ("wc_payroll", "workers_comp"),
                                          ("applicant_name", None)])
    def test_a_fact_knows_its_line(self, key, fam):
        from services.lob_canon import fact_line_family
        assert fact_line_family(key) == fam

    def test_the_declared_denial_records_false_flags(self):
        flags = {}
        es.apply_declared_absent_downgrades(
            flags, {}, "Property - No Coverage\nWorkers Compensation - No Coverage")
        assert flags.get("has_property_coverage") is False
        assert flags.get("has_workers_comp") is False

    def test_building_values_are_not_compared_on_a_package_with_no_property(self):
        from services.underwriting_consistency import assess_underwriting_consistency
        docs = [
            {"doc_id": "a", "filename": "dec.pdf", "doc_type": "dec_page", "text": "",
             "facts": {"property_building_value": _env("$250,000"),
                       "coverage_lines": copy.deepcopy(self.ROWS)}},
            {"doc_id": "b", "filename": "nar.pdf", "doc_type": "narrative", "text": "",
             "facts": {"property_building_value": _env("$400,000")}}]
        mf = {"coverage_lines": copy.deepcopy(self.ROWS),
              "property_building_value": _env("$250,000")}
        res = assess_underwriting_consistency(docs, mf, {},
                                              flags={"has_property_coverage": False})
        assert not [f for f in res["fields"] if f["fact_key"] == "property_building_value"]

    def test_the_generation_gate_never_blocks_a_package_with_no_property(self):
        from routes.form_routes import enforce_building_value_gate
        session = {"facts": {"coverage_lines": copy.deepcopy(self.ROWS)},
                   "flags": {"has_property_coverage": False},
                   "underwriting_consistency": {"fields": [
                       {"fact_key": "property_building_value", "review_required": True,
                        "label": "Building Value"}]}}
        enforce_building_value_gate(session)          # must not raise

    def test_the_125_line_ticks_never_tick_a_denied_or_menu_line(self):
        facts = {"_form_id": "ACORD_125", "coverage_lines": copy.deepcopy(self.ROWS),
                 "has_property_coverage": False, "has_workers_comp": False}
        boxes = ps._evidenced_standard_lob_boxes(facts) or frozenset()
        assert not any(("Property" in b and "Commercial" in b) or "Liquor" in b
                       or "WorkersCompensation" in b for b in boxes)

    def test_the_coverage_terms_row_never_lists_a_phantom_line(self):
        from services.sqs_service import check_doc_consistency
        dec = {"doc_id": "a", "filename": "dec.pdf", "doc_type": "dec_page", "text": "",
               "facts": {"lines_of_business": ["Liability", "Automobile", "Farm",
                                               "Liquor Liability", "Employment Practices",
                                               "Owners and Contractors Protective"],
                         "coverage_lines": copy.deepcopy(self.ROWS)}}
        coi = {"doc_id": "b", "filename": "coi.pdf", "doc_type": "certificate", "text": "",
               "facts": {"lines_of_business": ["General Liability", "Automobile Liability"]}}
        out = " ".join(check_doc_consistency([dec, coi]))
        for phantom in ("Farm", "Liquor", "Employment Practices", "Owners and Contractors"):
            assert phantom not in out


# =============================================================================
# Item 5 / 10 - values are compared only as the same field, line and period
# =============================================================================
def _group(display):
    return {"normalized": display.lower(), "display": display, "sources": [{"raw": display}]}


class TestItem10ComparisonGuardrails:

    @pytest.mark.parametrize("key, values, remaining", [
        ("is_renewal", ["true", "Renewal of BBC7263 - 25"], 1),
        ("is_renewal", ["true", "RENEWAL OF: 6E7-40-02---25"], 1),
        ("hired_auto_indicator", ["true", "$1,000,000"], 1),
        ("auto_hired_nonowned", ["true", "Hired Auto Liability $1,000,000"], 1),
        ("umbrella_follow_form", ["Yes", "CU7001A 11-15"], 1),
        ("gl_aggregate", ["$2,000,000", "Yes"], 1),
        # a GENUINE disagreement still conflicts
        ("is_renewal", ["true", "This policy is not a renewal"], 2),
        ("hired_auto_indicator", ["Yes", "No coverage for hired autos"], 2),
        ("gl_aggregate", ["$2,000,000", "$1,000,000"], 2),
    ])
    def test_a_value_of_another_kind_is_not_a_rival(self, key, values, remaining):
        from services.fact_equivalence import _KIND_CACHE
        from services.underwriting_consistency import _drop_values_of_another_kind
        _KIND_CACHE.clear()
        assert len(_drop_values_of_another_kind(key, [_group(v) for v in values])) == remaining

    def test_an_expiring_dec_and_a_new_application_are_two_periods(self):
        from services.sqs_service import check_doc_consistency
        dec = {"doc_id": "a", "filename": "dec.pdf", "doc_type": "dec_page", "text": "",
               "facts": {"effective_date": _env("07/15/2025"),
                         "expiration_date": _env("07/15/2026")}}
        app = {"doc_id": "b", "filename": "app.pdf", "doc_type": "application", "text": "",
               "facts": {"effective_date": _env("07/15/2026"),
                         "expiration_date": _env("07/15/2027")}}
        assert not [i for i in check_doc_consistency([dec, app]) if "date_conflict" in i]

    def test_two_decs_that_disagree_still_conflict(self):
        from services.sqs_service import check_doc_consistency
        a = {"doc_id": "a", "filename": "a.pdf", "doc_type": "dec_page", "text": "",
             "facts": {"effective_date": _env("07/15/2025")}}
        b = {"doc_id": "b", "filename": "b.pdf", "doc_type": "certificate", "text": "",
             "facts": {"effective_date": _env("08/01/2025")}}
        assert [i for i in check_doc_consistency([a, b]) if "date_conflict" in i]

    def test_a_card_about_one_line_offers_only_that_lines_numbers(self):
        """Replayed from the Run B session (sess.json shape): the dec printed the
        GL number without its prefix, so the GL line holds two printings and a
        GL-scoped card is right. The loss run lists the AUTO number on its
        General Liability row (the policy a claim sat under). Read as a line
        printing, it put 6E7-40-02---26 on the GL card as the SUGGESTED answer.
        A loss run witnesses no line schedule (`document_witnesses`)."""
        from services.underwriting_consistency import assess_underwriting_consistency

        def _doc(i, role, lines, pn=None):
            f = {"coverage_lines": lines}
            if pn:
                f["policy_number"] = _env(pn)
            return {"doc_id": i, "filename": f"{i}.pdf", "doc_type": role, "text": "", "facts": f}

        docs = [
            _doc("dec", "dec_page", [
                {"line": "Commercial General Liability", "policy_number": "7263-26",
                 "carrier": "EMC Property & Casualty Company", "premium": "$6,720"},
                {"line": "Commercial Automobile Liability", "policy_number": "6E7-40-02---26",
                 "carrier": "Employers Mutual Casualty Company", "premium": "$2,991"}]),
            _doc("coi", "certificate", [
                {"line": "General Liability", "policy_number": "BBC7263-26",
                 "carrier": "EMC Property & Casualty Company"},
                {"line": "Automobile Liability", "policy_number": "6E7-40-02---26",
                 "carrier": "Employers Mutual Casualty Company"}], pn="BBC7263-26"),
            _doc("lr", "loss_run", [
                {"line": "Business Auto", "policy_number": "6E7 40 02 26"},
                {"line": "General Liability", "policy_number": "6E7 40 02 26"}],
                pn="6E7 40 02 26"),
        ]
        docs = copy.deepcopy(docs)
        mf, flags = merge_facts(docs, select_primary_truth(docs))
        rows = assess_underwriting_consistency(docs, mf, {}, flags=flags)["fields"]
        row = next((f for f in rows if f["fact_key"] == "policy_number"
                    and f["status"] == "conflict"), None)
        if row is None:
            return                     # the two GL printings folded: nothing to offer
        assert row["conflict_scope"] == ["general_liab"]
        offered = {es._amount_key(g["display"]) or g["display"] for g in row["values"]}
        assert not any("6E7" in str(v).upper() for v in offered), offered
        assert "6E7" not in str(row.get("suggested_value") or "").upper()

    def test_the_aggregate_other_basis_box_is_an_owned_blank(self):
        box = "GeneralLiability_GeneralAggregate_LimitAppliesToCode_A"
        assert ps._first_rule_fact(box) is None
        assert ps._is_authoritative_blank_field(box, {"_form_id": "ACORD_126"})

    def test_umbrella_follow_form_is_declared_yes_no(self):
        from services.normalization import is_yes_no_field
        assert is_yes_no_field("umbrella_follow_form")


# =============================================================================
# Item 9 - the umbrella's dated reduction, read off the REAL certificate OCR
# =============================================================================
class TestItem9UmbrellaChange:

    @pytest.mark.parametrize("sentence, frm, to", [
        (GLUED_REMARK, "$3,000,000", "$1,000,000"),
        ("Umbrella limit reduced from $3,000,000 to $1,000,000 eff 7/25/2025",
         "$3,000,000", "$1,000,000"),
        ("Umbrella $1,000,000 (reduced from $3,000,000 as of 7/25/25)",
         "$3,000,000", "$1,000,000"),
        ("UMBRELLA LIMIT CHANGED TO $1M EFFECTIVE 07/25/25", None, "$1M"),
        ("The umbrella limit was reduced to $1,000,000 effective 7/25/25", None, "$1,000,000"),
        ("Umbrella decreased to 1M eff. 7-25-25", None, "1M"),
        ("Umbrella limit reduced from 3M to 1M effective 7/25/25", "3M", "1M"),
    ])
    def test_every_phrasing_is_read(self, sentence, frm, to):
        from services.narrative_facts import mine_statements
        st = [x for x in mine_statements(sentence) if x["kind"] == "amendment"]
        assert st and st[0]["subject"] == "umbrella_limit"
        assert st[0]["from"] == frm and st[0]["to"] == to
        assert st[0]["as_of"] and st[0]["asserted"] is True

    @pytest.mark.parametrize("sentence", [
        "The umbrella limit was not reduced from $3,000,000 to $1,000,000",
        "Insured requests the umbrella limit be reduced to $1,000,000 effective 7/25/25"])
    def test_an_unasserted_change_is_never_a_change(self, sentence):
        from services.narrative_facts import mine_statements
        assert all(x.get("asserted") is False for x in mine_statements(sentence))

    def test_a_premium_change_is_never_read_as_the_limit(self):
        from services.narrative_facts import mine_statements
        assert not mine_statements("Umbrella premium reduced from $3,418 to $3,000 effective 7/25/25")

    def test_ordinary_prose_is_untouched_by_the_respacer(self):
        from services.narrative_facts import respace_glued_prose
        s = "The applicant is a commercial general contractor based in Denver, Colorado."
        assert respace_glued_prose(s) == s

    @pytest.mark.parametrize("value, amount", [("$3 million", 3000000), ("$1M", 1000000),
                                               ("$1,000,000 Each Occurrence / $1,000,000 Aggregate",
                                                1000000)])
    def test_amounts_keep_their_multiplier(self, value, amount):
        assert es._amount_key(value) == amount

    def test_two_different_figures_are_no_single_figure(self):
        assert es._amount_key("$1,000,000 / $2,000,000") is None

    # -- end to end, through the real merge ------------------------------------
    DEC = {"doc_id": "dec", "filename": "dec.pdf", "doc_type": "dec_page", "text": "",
           "facts": {"umbrella_limit": _env("$ 3,000,000"),
                     "umbrella_effective_date": {"value": "07/15/2025"},
                     "umbrella_expiration_date": {"value": "07/15/2026"},
                     "effective_date": {"value": "07/15/25"},
                     "expiration_date": {"value": "07/15/26"}}}
    COI = {"doc_id": "coi", "filename": "coi.pdf", "doc_type": "certificate", "text": "",
           "facts": {"umbrella_limit": _env("$1,000,000"),
                     "umbrella_effective_date": {"value": "7/15/2025"},
                     "umbrella_expiration_date": {"value": "7/15/2026"}}}
    NAR = {"doc_id": "nar", "filename": "nar.pdf", "doc_type": "narrative", "text": "",
           "facts": {"umbrella_limit": _env("$1,000,000")}}

    def _run(self, docs):
        docs = copy.deepcopy(docs)
        mf, flags = merge_facts(docs, select_primary_truth(docs))
        return mf, flags, docs

    def _with(self, remark, where="certificate_description_of_operations", order=None):
        dec, coi, nar = (copy.deepcopy(d) for d in (self.DEC, self.COI, self.NAR))
        if remark:
            coi["facts"][where] = {"value": remark, "source": "ai"}
        return [dec, coi, nar] if order is None else [
            {"dec": dec, "coi": coi, "nar": nar}[k] for k in order]

    @pytest.mark.parametrize("docs_kw", [
        {"remark": GLUED_REMARK},
        {"remark": GLUED_REMARK, "where": "additional_remarks_text"},
        {"remark": "UMBRELLA LIMIT CHANGED TO $1M EFFECTIVE 07/25/25"},
        {"remark": GLUED_REMARK, "order": ["dec", "nar", "coi"]},
    ])
    def test_the_merge_stamps_the_current_limit(self, docs_kw):
        mf, flags, docs = self._run(self._with(**docs_kw))
        assert es._amount_key(_v(mf["umbrella_limit"])) == 1000000
        assert mf["umbrella_limit"].get("source") == "document_amendment"
        for fid in ("ACORD_131", "ACORD_25"):
            mapped, _c = ps.map_facts_to_form({**mf, **(flags or {})}, _schema(fid),
                                              form_id=fid, raw_text="")
            limits = {str(v) for k, v in mapped.items()
                      if v not in (None, "", "UNMATCHED")
                      and ("Umbrella" in k or "ExcessUmbrella" in k)
                      and ("Limit" in k or "Amount" in k)}
            assert limits and all(es._amount_key(v) == 1000000 for v in limits), (fid, limits)

    def test_a_narrative_repeating_the_note_first_does_not_defeat_it(self):
        docs = self._with(GLUED_REMARK, order=["dec", "nar", "coi"])
        docs[1]["facts"]["additional_remarks_text"] = {"value": GLUED_REMARK, "source": "ai"}
        mf, _f, _d = self._run(docs)
        assert mf["umbrella_limit"].get("source") == "document_amendment"

    def test_no_sentence_stays_a_conflict_and_the_card_suggests_what_prints(self):
        from services.underwriting_consistency import assess_underwriting_consistency
        mf, flags, docs = self._run(self._with(None))
        row = next(f for f in assess_underwriting_consistency(docs, mf, {}, flags=flags)["fields"]
                   if f["fact_key"] == "umbrella_limit")
        assert row["status"] == "conflict"
        assert es._amount_key(row["suggested_value"]) == es._amount_key(_v(mf["umbrella_limit"]))

    def test_a_withheld_umbrella_hides_its_equal_other_limit(self):
        facts = {"_form_id": "ACORD_131", "umbrella_limit": _env("$3,000,000"),
                 "_uw_conflicted_keys": ["umbrella_limit"]}
        assert ps._umbrella_other_limit_superseded(facts, "$3,000,000")


# =============================================================================
# Item 6 - strict line separation, on EVERY generation path
# =============================================================================
class TestItem6LineSeparation:

    def test_no_generation_call_skips_the_one_scoped_door(self):
        """render.yaml runs production async (worker.py), and the worker gave
        each form an unscoped whole-document gap fill - item 6 on exactly the
        path the client runs. The two essentials paths did the same. Every call
        to `process_single_form`, anywhere, must hand it the shared line-scoped
        answers (`form_service.shared_gap_fill`); a two-argument call is the
        defect's shape, and a new path added that way fails here."""
        import ast
        skip = {".venv", "tests", "scripts", "node_modules", "__pycache__", "tmp"}
        offenders, seen = [], 0
        for root, dirs, files in os.walk(BACKEND):
            dirs[:] = [d for d in dirs if d not in skip and not d.startswith(".")]
            for name in files:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(root, name)
                with open(path, encoding="utf-8") as fh:
                    tree = ast.parse(fh.read())
                for node in ast.walk(tree):
                    if not isinstance(node, ast.Call):
                        continue
                    fn = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                    if fn == "process_single_form":
                        given = len(node.args) + len(node.keywords)
                    elif fn == "run_in_executor":
                        idx = next((i for i, a in enumerate(node.args)
                                    if getattr(a, "id", None) == "process_single_form"), None)
                        if idx is None:
                            continue
                        given = len(node.args) - idx - 1
                    else:
                        continue
                    seen += 1
                    if given < 3:
                        offenders.append(f"{os.path.relpath(path, BACKEND)}:{node.lineno}")
        assert seen >= 5, "the harvester found too few call sites - it is blind"
        assert not offenders, offenders
        with open(os.path.join(BACKEND, "services", "form_service.py"), encoding="utf-8") as fh:
            src = fh.read()
        assert "build_line_page_scopes" in src and "line_scopes=line_scopes" in src

    def test_the_worker_passes_the_scoped_answers_to_each_form(self):
        with open(os.path.join(BACKEND, "worker.py"), encoding="utf-8") as fh:
            src = fh.read()
        assert "(per_form_pre_filled or {}).get(fid)" in src

    def _witness_facts(self):
        return {"_form_id": "ACORD_127",
                "gl_class_code_schedule": [{"class_code": "91580", "basis": "Payroll"}],
                "auto_vin_schedule": [{"vin": "4S4BRCGC9C3217772", "class_code": "91580"}],
                "dec_page_entries": [
                    {"label": "Class Code", "value": "91580",
                     "line_of_business": "General Liability", "section": "GL Schedule"},
                    {"label": "CLASS", "value": "7383",
                     "line_of_business": "Commercial Auto", "section": "Auto Schedule"}]}

    def test_a_gl_class_the_model_wrote_on_the_vehicle_is_blanked(self):
        out = ps._cross_line_code_borrows({"Vehicle_RateClassCode_A": "91580"}, {},
                                          self._witness_facts())
        assert "Vehicle_RateClassCode_A" in out

    def test_the_vehicles_own_class_is_kept(self):
        f = self._witness_facts()
        f["auto_vin_schedule"] = [{"vin": "X", "class_code": "7383"}]
        assert not ps._cross_line_code_borrows({"Vehicle_RateClassCode_A": "7383"}, {}, f)

    def test_one_source_alone_never_blanks(self):
        f = self._witness_facts()
        f["gl_class_code_schedule"] = []
        assert not ps._cross_line_code_borrows({"Vehicle_RateClassCode_A": "91580"}, {}, f)

    def test_a_borrowed_zone_code_is_blanked(self):
        schema = _schema("ACORD_127")
        facts = {"_form_id": "ACORD_127",
                 "dec_page_entries": [{"label": "DRIVE OTHER CAR - TERRITORY",
                                       "value": "104 6679",
                                       "line_of_business": "Commercial Auto"}]}
        mapped = {"Vehicle_FarthestZoneCode_A": "6679", "Vehicle_RatingTerritoryCode_A": "111"}
        ps._enforce_post_fill_guards(mapped, schema, facts)
        assert not mapped.get("Vehicle_FarthestZoneCode_A")

    @pytest.mark.parametrize("value, blanked", [
        ("Uninsured/Underinsured Motorists", True), ("Commercial Auto Liability", True),
        ("Drive Other Car", True), ("Inland Marine - Installation Floater", True),
        ("Hired and Non-Owned Auto Liability", False), ("Liquor Liability", False),
        ("Stop Gap Employers Liability", False)])
    def test_another_policys_coverage_is_not_the_gl_forms_other(self, value, blanked):
        schema = _schema("ACORD_126")
        field = next(f for f in schema if ps._OTHER_COVERAGE_DESCRIPTION_RE.search(f))
        mapped = {field: value}
        ps._enforce_post_fill_guards(mapped, schema, {"_form_id": "ACORD_126"},
                                     gpt_filled_set={field})
        assert (not mapped.get(field)) is blanked

    @pytest.mark.parametrize("box", [
        "UnderlyingCoverage_Coverage_LiquorLiabilityIndicator_A",
        "UnderlyingCoverage_Coverage_PollutionLiabilityIndicator_A",
        "UnderlyingCoverage_Coverage_ProfessionalLiabilityIndicator_A"])
    def test_an_uncarried_underlying_coverage_is_never_ticked_on_131(self, box):
        facts = {"_form_id": "ACORD_131", "coverage_lines": copy.deepcopy(TestItem2CarriedLines.ROWS)}
        assert ps._resolve_uncarried_coverage_part(box, facts) is None


# =============================================================================
# Item 7 - Colorado auto: the 127 names its 137
# =============================================================================
class TestItem7StateAutoForm:
    FACTS = {"mailing_address": "4800 DAHLIA ST # D13, DENVER, CO 80216-3121"}
    FLAGS = {"has_auto_coverage": True}

    def test_a_127_without_its_137_is_named_with_a_one_click_add(self):
        from services.cross_form_validator import _check_acord127_state_section
        out = _check_acord127_state_section(self.FACTS, self.FLAGS, {"ACORD_125", "ACORD_127"})
        assert out and out[0]["code"] == "acord127_missing_state_137"
        assert out[0]["type"] == "advisory"                 # never a score cap
        assert out[0]["resolution"].get("add_forms") == ["ACORD_137_CO"]

    def test_silent_when_the_137_is_selected(self):
        from services.cross_form_validator import _check_acord127_state_section
        assert not _check_acord127_state_section(
            self.FACTS, self.FLAGS, {"ACORD_127", "ACORD_137_CO"})

    def test_the_state_comes_from_where_the_vehicles_are_garaged(self):
        from services.form_service import _supported_state_forms
        facts = {"mailing_address": "100 Main St, Houston, TX 77002",
                 "auto_garaging_addresses": ["4800 DAHLIA ST, DENVER, CO 80216"]}
        assert _supported_state_forms(facts, {}) == ["CO"]

    def test_the_selection_screen_ticks_the_137_with_the_127(self):
        with open(os.path.join(BACKEND, "..", "frontend", "src", "components", "form",
                               "AcordModal.jsx"), encoding="utf-8") as fh:
            src = fh.read()
        assert "stateAutoCompanions" in src and "declinedStateAutoForms" in src


# =============================================================================
# Item 4 - the new application's producer is the login, never the old agency
# =============================================================================
FIO = "For Informational Purposes Only"
THINKSMITH = {"organization_name": "ThinkSmith Agency LLC", "full_name": "Michelle Smith",
              "email": "michelle@thinksmith.example", "phone": "(303) 555-0142"}


def _party_docs():
    dec = {"doc_id": "dec", "filename": "policy.pdf", "doc_type": "dec_page", "text": "",
           "flags": {}, "facts": {
               "applicant_name": _env("ORBIN CONTRACTING LLC"),
               "producer_name": _env("COMMERCIAL RISK SOLUTIONS, INC."),
               "producer_address": _env("9780 S MERIDIAN BLVD STE 400, ENGLEWOOD, CO 80112-6072"),
               "producer_contact_phone": _env("303-996-7800")}}
    coi = {"doc_id": "coi", "filename": "coi.pdf", "doc_type": "certificate", "text": "",
           "flags": {}, "facts": {
               "applicant_name": _env("Orbin Contracting, LLC"),
               "producer_name": _env("CommercialRiskSolutions,Inc."),
               "producer_contact_name": _env("Terri Wroblewski"),
               "producer_contact_phone": _env("303-996-7800"),
               "producer_contact_email": _env("twroblewski@crsdenver.com"),
               "certificate_holder": _env(GLUED_HOLDER),
               "applicant_contacts": [{"name": "Terri Wroblewski", "phone": "303-996-7800"}]}}
    nar = {"doc_id": "nar", "filename": "narrative.pdf", "doc_type": "narrative", "text": "",
           "flags": {}, "facts": {
               "applicant_name": _env("Orbin Contracting LLC"),
               "producer_name": _env("Commercial Risk Solutions")}}
    return [dec, coi, nar]


class TestItem4Producer:

    def _merge(self, account, docs=None):
        docs = docs or _party_docs()
        mf, _ = merge_facts(docs, select_primary_truth(docs), submitting_account=account)
        return mf

    def test_the_login_is_the_producer_even_when_the_narrative_names_the_old_broker(self):
        mf = self._merge(THINKSMITH)
        assert _v(mf["producer_name"]) == "ThinkSmith Agency LLC"
        assert _v(mf["producer_contact_name"]) == "Michelle Smith"
        assert _v(mf["producer_contact_email"]) == "michelle@thinksmith.example"
        assert _v(mf["producer_contact_phone"]) == "(303) 555-0142"
        assert "producer_address" not in mf
        assert _v(mf.get("expiring_producer_name"))

    @pytest.mark.parametrize("org", ["N/A", "TBD", "none", "  "])
    def test_a_non_answer_org_never_prints_the_old_agency(self, org):
        mf = self._merge({"organization_name": org, "full_name": "X Y"})
        assert not _v(mf.get("producer_name"))
        assert "Terri" not in str(_v(mf.get("producer_contact_name")) or "")

    def test_under_an_unreadable_login_the_new_brokers_own_application_decides(self):
        """The incumbent rule refuses only the agency the expiring programme
        prints - an application naming a DIFFERENT agency is still the
        submitter, and the narrative naming the incumbent is not a rival."""
        docs = _party_docs()
        docs.append({"doc_id": "app", "filename": "app.pdf", "doc_type": "application",
                     "text": "", "flags": {}, "facts": {
                         "producer_name": _env("ThinkSmith Agency LLC"),
                         "producer_contact_name": _env("Michelle Smith")}})
        mf = self._merge({"organization_name": "N/A", "full_name": "X Y"}, docs)
        assert _v(mf["producer_name"]) == "ThinkSmith Agency LLC"
        assert _v(mf["producer_contact_name"]) == "Michelle Smith"

    def test_with_no_login_at_all_the_documents_still_decide(self):
        """Offline callers have no account concept: an incumbent re-marketing
        its own account stays its own producer, as before."""
        mf = self._merge(None)
        assert "Commercial Risk" in str(_v(mf.get("producer_name")))

    def test_a_lower_case_org_is_still_the_users_agency(self):
        mf = self._merge({"organization_name": "thinksmith", "full_name": "Michelle Smith"})
        assert _v(mf["producer_name"]) == "thinksmith"

    def test_an_agency_is_never_the_prior_carrier(self):
        docs = _party_docs()
        docs[0]["facts"]["prior_carrier"] = _env("Commercial Risk Solutions, Inc.")
        mf = self._merge(THINKSMITH, docs)
        assert "Commercial Risk" not in str(_v(mf.get("prior_carrier")) or "")

    def test_the_old_agent_is_never_the_applicants_contact(self):
        mf = self._merge(THINKSMITH)
        contacts = _v(mf.get("applicant_contacts")) or []
        assert not any("Wroblewski" in str(c) for c in contacts)


# =============================================================================
# Item 8 - text that names nobody never fills a party box
# =============================================================================
class TestItem8Parties:
    PLACEHOLDERS = [FIO, GLUED_HOLDER, "FOR INFORMATIONAL PURPOSES ONLY", "Evidence Only",
                    "See Attached", "Certificate Holder", "To Whom It May Concern",
                    "As Required By Written Contract", "Any person or organization", "Same"]
    REAL = ["Wells Fargo Equipment Finance", "City of Aurora", "Kestrel Terminal Authority",
            "Will County", "On Deck Capital", "For Rent Properties LLC", "Covers Unlimited Inc",
            "Insured Title Agency", "3M", "May Department Stores Co", "Evidence Holdings LLC"]

    @pytest.mark.parametrize("key", ["loss_payee_name", "certificate_holder", "mortgagee_name"])
    def test_a_human_answer_naming_nobody_is_refused(self, key):
        from services.answer_semantics import interpret_answer
        for text in self.PLACEHOLDERS[:5]:
            assert not interpret_answer(key, text).accepted, text
        for text in self.REAL[:3]:
            assert interpret_answer(key, text).accepted, text

    def test_the_party_test_separates_real_names_from_placeholders(self):
        from services.field_mapping_integrity import names_a_party
        assert not [v for v in self.REAL if not names_a_party(v, third_party=True)]
        assert not [v for v in self.PLACEHOLDERS if names_a_party(v, third_party=True)]

    def test_placeholder_rows_leave_the_rosters_and_the_lender_keeps_row_a(self):
        f = {"additional_named_insureds": [GLUED_HOLDER, "Cedar Bluff Holdings LLC"],
             "additional_interests": [{"name": FIO},
                                      {"name": "Wells Fargo Equipment Finance",
                                       "address_line_one": "800 Walnut St"}]}
        es.drop_non_party_names(f)
        assert f["additional_named_insureds"] == ["Cedar Bluff Holdings LLC"]
        assert f["additional_interests"][0]["name"] == "Wells Fargo Equipment Finance"


# =============================================================================
# Item 11 - what the policy prints is confirmed, never asked again
# =============================================================================
class TestItem11DoNotReAsk:
    DEC_ROW = {"year": "2012", "make": "SUBARU", "model": "OUTBACK SEDAN",
               "vin": "4S4BRCGC9C3217772"}

    @pytest.mark.parametrize("row, folds", [
        ({"year": "2012", "make": "Subaru", "model": "Outback"}, True),
        ({"year": 2012, "model": "Subaru Outback"}, True),
        ({"year": "2012", "make": "subaru", "model": "Out-back"}, True),
        ({"year": "2012", "make": "Subaru", "body_type": "Wagon"}, True),
        ({"year": "2012", "make": "Subaru", "model": "Forester"}, False),
        ({"year": "2019", "make": "Subaru", "model": "Outback"}, False),
        ({"year": "2012", "make": "Ford", "model": "F-150"}, False)])
    def test_one_car_in_two_documents_is_one_row(self, row, folds):
        kept = es._fold_unkeyed_into_matching_rows([dict(self.DEC_ROW)], [row])
        assert (not kept) is folds

    def test_the_vehicle_is_rebuilt_from_the_real_policy_when_extraction_missed_it(self):
        text = _real_text()
        mf = {}
        es._backfill_vehicle_rows_from_text(mf, [{"text": text}])
        es._backfill_vehicle_codes_from_text(mf, [{"text": text}])
        row = _v(mf["auto_vin_schedule"])[0]
        assert row["vin"] == "4S4BRCGC9C3217772" and row["year"] == "2012"
        assert row["make"] == "Subaru" and "Outback" in row["model"]
        assert row["class_code"] == "7383" and row["territory"] == "111"

    def test_an_extracted_vehicle_is_never_replaced(self):
        mf = {"auto_vin_schedule": [dict(self.DEC_ROW)]}
        assert es._backfill_vehicle_rows_from_text(mf, [{"text": "2019 FORD F-150 VIN "
                                                        "1FT7W2BT5KEC12345"}]) == []

    def test_garaging_is_read_off_the_real_vehicle_block(self):
        mf = {}
        assert es._backfill_garaging_from_vehicle_block(mf, [{"text": _real_text()}]) == \
            "4800 DAHLIA STREET D13, DENVER, CO 80216-3121"

    @pytest.mark.parametrize("name", ["ROYAL, ERIN", "Erin Royal", "ERIN ROYAL", "Royal Erin"])
    def test_the_drive_other_car_individual_is_found_in_any_word_order(self, name):
        from services.named_individuals import printing_roles, _norm
        assert "named" in printing_roles(name, [_norm(_real_text())])

    def test_confirm_items_are_pre_ticked_outside_the_cap(self):
        from services.question_classifier import apply_default_selection
        qs = [{"field_name": f"q{i}", "audience": "client", "priority": "critical"}
              for i in range(12)]
        qs.append({"field_name": "schedule::auto_vin_schedule", "audience": "client",
                   "priority": "optional", "confirm": True})
        apply_default_selection(qs, cap=12)
        assert qs[-1]["default_selected"] is True
        assert sum(1 for q in qs[:12] if q["default_selected"]) == 12
