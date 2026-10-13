"""Choice Electric live run (7 Oct 2026, session 9acec031) - four data defects a
fresh extraction showed that Brent's stored run did not:

1. GL limits were the UMBRELLA's own limit ($5,000,000 from the Commercial
   Liability Umbrella declarations). A one-line document's own limit is not
   another line's (`extraction_service._drop_another_lines_limits_on_one_line_
   document`); the GL then reads the umbrella's schedule of underlying insurance.
2. Entity type "Corporation" for an LLC - read off a printed menu by its first
   word, and off a carrier menu with no LLC option. One reading:
   `normalization.settle_document_entity_type`.
3. A pre-form warning pointing at a Data Consistency card that said "nothing to
   confirm" - the card dropped "LLC" as not a legal option.
4. "Multiple carriers referenced across documents" on a package where every
   carrier writes its own line.

Synthetic documents only (shapes copied from the redacted decs, no PII); plus
Brent's stored fixture for the no-regression checks.
"""
import copy
import json
import os

import pytest

from services import extraction_service as es
from services import normalization as nz
from services.sqs_service import check_doc_consistency
from services.submission_integrity import assess_submission_integrity
from services.underwriting_consistency import assess_underwriting_consistency

_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "choice_electric_pol_6oct.json")

_AUTO_MENU = ("BUSINESS AUTO DECLARATIONS\nNamed Insured:\nForm OfBusiness:\n"
              "Corporation X Limited Liability Company Individual\nPartnership Other:\n"
              "In return for the payment of the premium\n")
_EXCESS_MENU = ("EXCESS (FOLLOWING FORM) LIABILITY INSURANCE POLICY\n"
                "2. THE NAMED INSURED IS A:\n"
                "X CORPORATION SOLE PROPRIETOR PARTNERSHIP OR JOINT VENTURE OTHER\n"
                "3. POLICY PERIOD: From 01/01/2025 to 01/01/2026\n")
_UMBRELLA_TEXT = (
    "Umbrella Liability Policy\nItem 1. Insured Name:\nACME ELECTRIC LLC\n"
    "Item 3. The Limits of Insurance, subject to all terms of this policy are:\n"
    "a. Each Occurrence Limit $5,000,000\n"
    "Personal & Advertising Injury Limit (Any one person or organization) $5,000,000\n"
    "b. Aggregates\nProducts - Completed Operations $5,000,000\n"
    "c. Self-Insured Retention 0\n"
    "SCHEDULE OF UNDERLYING INSURANCE\n"
    "Carrier,\nPolicy Number, Type of Limits of\nPolicy Period Policy Liability\n"
    "ALPHA INSURANCE COMPANY General Liability Each Occurrence\n$1,000,000\n"
    "01/01/2025 - 01/01/2026\n"
    "Personal & Advertising Injury (Any one person or organization)\n$1,000,000\n"
    "Aggregates\n$2,000,000 General Aggregate\n$2,000,000 Products - completed operations\n"
    "Aggregate\nALPHA INSURANCE COMPANY Automobile Liability\nEach Accident\n$1,000,000\n"
    "01/01/2025 - 01/01/2026\nForms and Endorsements Schedule\n")


def _env(v):
    return {"value": v, "source": "ai", "confidence": "ai_high"}


def _doc(name, facts, text="", doc_type="dec_page"):
    return {"doc_id": name, "filename": name, "doc_type": doc_type, "text": text,
            "facts": {k: (_env(v) if not isinstance(v, (dict, list)) else v)
                      for k, v in facts.items()},
            "flags": {}}


def _line(line, carrier, premium=None):
    return {"line": line, "carrier": carrier, "premium": premium, "policy_number": None,
            "naic": None, "effective_date": "01/01/2025", "expiration_date": "01/01/2026"}


def _merge(docs):
    docs = copy.deepcopy(docs)
    mf, flags = es.merge_facts(docs, es.select_primary_truth(docs))
    return mf, flags, docs


def _v(facts, key):
    return es._fv(facts, key)


# =============================================================================
# 2. Entity type - the legal-form designator in a name
# =============================================================================
@pytest.mark.parametrize("name,family", [
    ("CHOICE ELECTRIC LLC", "llc"),
    ("Choice Electric, L.L.C.", "llc"),
    ("ChoiceElectricLLC", "llc"),
    ("Smith Law PLLC", "llc"),
    ("Acme Electric Limited Liability Company", "llc"),
    ("Acme Inc.", "corporation"),
    ("Acme Incorporated", "corporation"),
    ("Acme Corp", "corporation"),
    ("Acme Holdings LP", "partnership"),
    ("Acme Partners LLP", "partnership"),
    ("Acme Company", None),           # "Company" names no single family
    ("Acme Ltd", None),
    ("Acme Corp of America", None),   # the designator must CLOSE the name
    ("John Smith DBA Sparky Electric", None),
    ("LLC", None),                    # a bare designator is not a name
    ("", None),
    (None, None),
])
def test_name_legal_form(name, family):
    got = nz.name_legal_form(name)
    assert (got[0] if got else None) == family


# =============================================================================
# 2. Entity type - a menu value is only its ticked option
# =============================================================================
@pytest.mark.parametrize("text,value,expected", [
    # the box precedes its caption: X ticks the option AFTER it
    (_AUTO_MENU, "Corporation", "Limited Liability Company"),
    (_AUTO_MENU, "Limited Liability Company", "Limited Liability Company"),
    # a mark that opens the line ticks the first option
    (_EXCESS_MENU, "Corporation", "Corporation"),
    # a mark closing the line ticks the option before it
    ("Form of Business:\nCorporation Limited Liability Company X\n", "Corporation",
     "Limited Liability Company"),
    # box glyphs
    ("Entity:\n\u2610 Corporation \u2612 LLC \u2610 Partnership\n", "Corporation",
     "Limited Liability Company"),
    ("[ ] Corporation [X] Partnership\n", "Corporation", "Partnership"),
])
def test_a_menu_value_is_its_ticked_option(text, value, expected):
    got, _rule = nz.settle_document_entity_type(value, text, [], [])
    assert got == expected


def test_a_menu_without_one_tick_reads_nothing():
    untick = "Form of Business:\nCorporation Limited Liability Company Individual\n"
    assert nz.settle_document_entity_type("Corporation", untick)[0] is None
    two = "X Corporation X Limited Liability Company Individual\n"
    assert nz.settle_document_entity_type("Corporation", two)[0] is None


def test_a_stated_value_or_one_off_any_menu_is_left_as_read():
    stated = ("Entity Type: Corporation\n"
              "Form of Business:\nCorporation Limited Liability Company Individual\n")
    assert nz.settle_document_entity_type("Corporation", stated) == ("Corporation", None)
    prose = "The named insured is organised as a Corporation under Colorado law.\n"
    assert nz.settle_document_entity_type("Corporation", prose) == ("Corporation", None)
    # one option word on a line of other words is not a menu
    wc = ("Item 1. Name of Insured and Address, For Additional Named Insureds, "
          "Individual Partnership\nCorporation or\nFEIN\n")
    assert nz.settle_document_entity_type("Corporation", wc) == ("Corporation", None)
    assert nz.settle_document_entity_type(None, _AUTO_MENU) == (None, None)
    assert nz.settle_document_entity_type("Statutory", _AUTO_MENU) == ("Statutory", None)


# =============================================================================
# 2. Entity type - the designator decides between incompatible families
# =============================================================================
def test_designator_overrides_an_incompatible_reading():
    # Travelers' menu has no LLC option - the name decides
    got, rule = nz.settle_document_entity_type("Corporation", _EXCESS_MENU, [],
                                               ["CHOICE ELECTRIC LLC"])
    assert (got, rule) == ("Limited Liability Company", "name_designator")
    assert nz.settle_document_entity_type("LLC", "", ["Acme Inc"])[0] == "Corporation"
    assert nz.settle_document_entity_type("Partnership", "", ["Acme LLC"])[0] == \
        "Limited Liability Company"


@pytest.mark.parametrize("value,name", [
    ("LLC", "Acme LLC"),                       # agrees
    ("Limited Liability Company", "Acme L.L.C."),
    ("S Corporation", "Acme Inc"),             # compatible: an Inc can elect S
    ("Non-Profit Corporation", "Acme Inc"),
    ("Corporation", "Acme Company"),           # no designator
    ("Corporation", "Acme Electric"),
])
def test_designator_leaves_compatible_readings(value, name):
    assert nz.settle_document_entity_type(value, "", [name]) == (value, None)


def test_designator_from_the_package_only_for_one_insured():
    # the document names nobody; the package names one insured -> its designator
    assert nz.settle_document_entity_type("Corporation", "", [], ["Acme LLC", "ACME LLC"])[0] \
        == "Limited Liability Company"
    # two insureds in the package -> no designator, nothing changes
    assert nz.settle_document_entity_type(
        "Corporation", "", [], ["Acme LLC", "Beta Builders Inc"]) == ("Corporation", None)
    # the document's own name has none; the package's SAME insured has one
    assert nz.settle_document_entity_type(
        "Corporation", "", ["Acme Electric"], ["Acme Electric LLC", "Beta Inc"])[0] \
        == "Limited Liability Company"
    # two designators for one insured -> nothing decided
    assert nz.settle_document_entity_type(
        "Corporation", "", [], ["Acme LLC", "Acme Inc"]) == ("Corporation", None)


def _entity_package():
    return [
        _doc("auto.pdf", {"applicant_name": "ACME ELECTRIC LLC", "entity_type": "Corporation",
                          "coverage_lines": [_line("Commercial Auto", "ALPHA INSURANCE COMPANY")],
                          "carrier_name": "ALPHA INSURANCE COMPANY"}, _AUTO_MENU),
        _doc("excess.pdf", {"entity_type": "Corporation", "umbrella_limit": "$4,000,000",
                            "coverage_lines": [_line("Excess (Following Form) Liability",
                                                     "GAMMA CASUALTY COMPANY")],
                            "carrier_name": "GAMMA CASUALTY COMPANY"}, _EXCESS_MENU),
        _doc("umbrella.pdf", {"applicant_name": "ACME ELECTRIC LLC", "entity_type": "LLC",
                              "umbrella_limit": "$5,000,000",
                              "coverage_lines": [_line("Commercial Liability Umbrella",
                                                       "ALPHA MUTUAL INSURANCE COMPANY")],
                              "carrier_name": "ALPHA MUTUAL INSURANCE COMPANY"}, _UMBRELLA_TEXT),
    ]


@pytest.mark.parametrize("order", ["stored", "reversed"])
def test_merged_entity_type_is_llc_and_every_reader_agrees(order):
    docs = _entity_package()
    if order == "reversed":
        docs = list(reversed(docs))
    mf, flags, docs = _merge(docs)
    assert nz.entity_family(_v(mf, "entity_type")) == "llc"
    for d in docs:
        assert nz.entity_family(_v(d["facts"], "entity_type")) == "llc", d["filename"]
    assert not [i for i in check_doc_consistency(docs, set())
                if "field=entity_type" in i and not i.startswith("[info]")]
    assert "Entity type differs across documents" not in \
        assess_submission_integrity(docs)["reasons"]
    uc = assess_underwriting_consistency(docs, mf, {}, flags=flags)
    row = next(f for f in uc["fields"] if f["fact_key"] == "entity_type")
    assert row["status"] != "conflict"


def test_integrity_reads_the_same_way_before_the_merge():
    # A document added after forms is integrity-checked before any merge.
    docs = copy.deepcopy(_entity_package())
    assert "Entity type differs across documents" not in \
        assess_submission_integrity(docs)["reasons"]


def test_the_entity_settle_is_idempotent_and_keeps_a_person():
    mf1, _f, docs = _merge(_entity_package())
    mf2, _f, docs2 = _merge(docs)
    assert _v(mf1, "entity_type") == _v(mf2, "entity_type")
    assert [_v(d["facts"], "entity_type") for d in docs] == \
        [_v(d["facts"], "entity_type") for d in docs2]
    docs = _entity_package()
    docs[0]["facts"]["entity_type"] = {"value": "Corporation", "source": "producer"}
    _mf, _f, out = _merge(docs)
    assert _v(out[0]["facts"], "entity_type") == "Corporation"


# =============================================================================
# 3. A Data Consistency warning always has a card to confirm
# =============================================================================
@pytest.mark.parametrize("a,b", [
    ("Corporation", "LLC"),
    ("LLC", "Partnership"),
    ("Corporation", "Limited Liability Company"),
])
def test_a_warning_pointing_at_data_consistency_has_a_live_card(a, b):
    # no names, no menus: the documents genuinely disagree
    docs = [_doc("one.pdf", {"entity_type": a,
                             "mailing_address": "1 Main St, Denver, CO 80202"}),
            _doc("two.pdf", {"entity_type": b,
                             "mailing_address": "900 Elm Ave, Boulder, CO 80301"})]
    mf, flags, docs = _merge(docs)
    issues = check_doc_consistency(docs, set())
    uc = assess_underwriting_consistency(docs, mf, {}, flags=flags)
    status = {f["fact_key"]: f["status"] for f in uc["fields"]}
    pointing = [i for i in issues if "Data Consistency" in i
                and not i.startswith("[info]")]
    assert pointing, issues
    for msg in pointing:
        key = msg.split("field=", 1)[1].split()[0] if "field=" in msg else None
        if key:
            assert status.get(key) not in (None, "consistent"), (key, msg, status.get(key))


def test_llc_is_a_legal_entity_type_on_the_card():
    from services.underwriting_consistency import _declared_domain_check
    legal = _declared_domain_check("entity_type")
    for v in ("LLC", "Limited Liability Company", "L.L.C.", "Corporation", "Corp"):
        assert legal(v), v
    assert not legal("Commercial General Liability Coverage Form")


# =============================================================================
# 1. A one-line document's own limit is not another line's
# =============================================================================
def _gl_package(umbrella_gl="$5,000,000", gl_dec=None, schedule=True):
    umb = {"applicant_name": "ACME ELECTRIC LLC", "umbrella_limit": "$5,000,000",
           "umbrella_sir": "0",
           "coverage_lines": [_line("Commercial Liability Umbrella",
                                    "ALPHA MUTUAL INSURANCE COMPANY", "$17,082.00")],
           "carrier_name": "ALPHA MUTUAL INSURANCE COMPANY",
           "auto_liability_limit": "$1,000,000"}
    if umbrella_gl:
        for k in ("gl_limits", "gl_each_occurrence", "gl_aggregate", "gl_products_aggregate",
                  "gl_personal_advertising_injury"):
            umb[k] = umbrella_gl
    text = _UMBRELLA_TEXT if schedule else _UMBRELLA_TEXT.split("SCHEDULE OF")[0]
    pkg = {"applicant_name": "ACME ELECTRIC LLC",
           "coverage_lines": [_line("Commercial General Liability", "ALPHA INSURANCE COMPANY",
                                    "$16,818.00"),
                              _line("Commercial Inland Marine", "ALPHA INSURANCE COMPANY",
                                    "$900.00")],
           "carrier_name": "ALPHA INSURANCE COMPANY"}
    if gl_dec:
        pkg.update(gl_dec)
    return [_doc("package.pdf", pkg, "COMMON POLICY DECLARATIONS\n"),
            _doc("umbrella.pdf", umb, text)]


@pytest.mark.parametrize("order", ["stored", "reversed"])
def test_the_umbrella_limit_never_becomes_the_gl_limit(order):
    docs = _gl_package()
    if order == "reversed":
        docs = list(reversed(docs))
    mf, _f, out = _merge(docs)
    assert _v(mf, "gl_each_occurrence") == "$1,000,000"
    assert _v(mf, "gl_aggregate") == "$2,000,000"
    assert _v(mf, "gl_products_aggregate") == "$2,000,000"
    assert _v(mf, "gl_personal_advertising_injury") == "$1,000,000"
    assert "5,000,000" not in str(_v(mf, "gl_limits") or "")
    assert _v(mf, "umbrella_limit") == "$5,000,000"
    # the underlying auto limit printed on the umbrella is not its own limit
    assert _v(mf, "auto_liability_limit") == "$1,000,000"
    umb = next(d for d in out if d["filename"] == "umbrella.pdf")
    assert _v(umb["facts"], "gl_each_occurrence") is None   # the per-document copy too


def test_no_schedule_means_blank_never_the_umbrella():
    mf, _f, _o = _merge(_gl_package(schedule=False))
    for k in ("gl_each_occurrence", "gl_aggregate", "gl_limits"):
        assert _v(mf, k) is None, k


def test_the_gl_own_declarations_win():
    mf, _f, _o = _merge(_gl_package(gl_dec={"gl_each_occurrence": "$1,000,000",
                                            "gl_aggregate": "$2,000,000"}))
    assert _v(mf, "gl_each_occurrence") == "$1,000,000"
    assert _v(mf, "gl_aggregate") == "$2,000,000"


@pytest.mark.parametrize("order", ["stored", "reversed"])
def test_orbin_shape_three_million_umbrella_over_one_million_gl(order):
    gl = _doc("gl.pdf", {"applicant_name": "ORBIN CONTRACTING LLC",
                         "gl_each_occurrence": "$1,000,000", "gl_aggregate": "$2,000,000",
                         "coverage_lines": [_line("Commercial General Liability", "EMC",
                                                  "$4,000")]})
    umb = _doc("umb.pdf", {"applicant_name": "ORBIN CONTRACTING LLC",
                           "umbrella_limit": "$3,000,000", "gl_each_occurrence": "$3,000,000",
                           "gl_aggregate": "$3,000,000",
                           "coverage_lines": [_line("Commercial Liability Umbrella", "EMC",
                                                    "$2,000")]})
    docs = [gl, umb] if order == "stored" else [umb, gl]
    mf, _f, _o = _merge(docs)
    assert _v(mf, "gl_each_occurrence") == "$1,000,000"
    assert _v(mf, "gl_aggregate") == "$2,000,000"
    assert _v(mf, "umbrella_limit") == "$3,000,000"


def test_what_the_one_line_rule_never_touches():
    f = es._drop_another_lines_limits_on_one_line_document
    # a different amount (the scheduled underlying GL) stays
    d = _doc("u.pdf", {"umbrella_limit": "$5,000,000", "gl_each_occurrence": "$1,000,000",
                       "coverage_lines": [_line("Commercial Liability Umbrella", "X Co")]})
    assert f(d) == [] and _v(d["facts"], "gl_each_occurrence") == "$1,000,000"
    # a document covering two families is the C23 settle's case
    d = _doc("p.pdf", {"umbrella_limit": "$5,000,000", "gl_each_occurrence": "$5,000,000",
                       "coverage_lines": [_line("Commercial Liability Umbrella", "X Co"),
                                          _line("Commercial General Liability", "X Co")]})
    assert f(d) == []
    # a person's answer
    d = _doc("u.pdf", {"umbrella_limit": "$5,000,000",
                       "gl_each_occurrence": {"value": "$5,000,000", "source": "producer"},
                       "coverage_lines": [_line("Commercial Liability Umbrella", "X Co")]})
    assert f(d) == []
    # a deductible / attachment is not a limit, either side
    d = _doc("u.pdf", {"umbrella_limit": "$1,000,000", "umbrella_attachment_point": "$1,000,000",
                       "gl_deductible": "$1,000,000",
                       "coverage_lines": [_line("Commercial Liability Umbrella", "X Co")]})
    assert f(d) == []
    d = _doc("u.pdf", {"umbrella_attachment_point": "$1,000,000",
                       "gl_each_occurrence": "$1,000,000",
                       "coverage_lines": [_line("Commercial Liability Umbrella", "X Co")]})
    assert f(d) == []                         # no own LIMIT to compare with
    # no coverage rows / malformed input
    assert f(_doc("x.pdf", {"gl_each_occurrence": "$5,000,000"})) == []
    assert f(None) == [] and f({}) == []
    # an auto-only declarations page's own CSL read as a GL limit
    d = _doc("a.pdf", {"auto_liability_limit": "$1,000,000", "gl_each_occurrence": "$1,000,000",
                       "coverage_lines": [_line("Commercial Auto", "X Co")]})
    assert f(d) and _v(d["facts"], "gl_each_occurrence") is None


@pytest.mark.parametrize("order", ["stored", "reversed"])
def test_brents_stored_package_does_not_regress(order):
    docs = copy.deepcopy(json.load(open(_FIXTURE))["docs"])
    if order == "reversed":
        docs = list(reversed(docs))
    mf, flags, docs = _merge(docs)
    assert _v(mf, "gl_each_occurrence") == "$1,000,000"
    assert _v(mf, "gl_aggregate") == "$2,000,000"
    assert _v(mf, "umbrella_limit") == "$5,000,000"
    # his 125 ticked Corporation: the auto dec ticks LLC, the name is an LLC
    assert nz.entity_family(_v(mf, "entity_type")) == "llc"
    assert assess_submission_integrity(docs)["reasons"] == []


# =============================================================================
# 4. Several carriers is a package; two carriers on ONE line is the signal
# =============================================================================
def _carrier_doc(name, line, carrier, insured="ACME ELECTRIC LLC"):
    return _doc(name, {"applicant_name": insured, "carrier_name": carrier,
                       "coverage_lines": [_line(line, carrier)]})


def test_each_carrier_on_its_own_line_is_not_a_signal():
    docs = [_carrier_doc("gl.pdf", "Commercial General Liability", "ALPHA INSURANCE COMPANY"),
            _carrier_doc("cy.pdf", "Cyber", "DELTA AMERICAN INSURANCE COMPANY"),
            _carrier_doc("ep.pdf", "Employment Practices Liability", "FEDERAL INSURANCE COMPANY"),
            _carrier_doc("um.pdf", "Commercial Liability Umbrella", "ALPHA MUTUAL INSURANCE COMPANY"),
            _carrier_doc("xs.pdf", "Excess (Following Form) Liability", "GAMMA CASUALTY COMPANY")]
    assert "Multiple carriers referenced across documents" not in \
        assess_submission_integrity(docs)["reasons"]


def test_two_carriers_on_one_line_still_signal():
    docs = [_carrier_doc("a.pdf", "Commercial General Liability", "ALPHA INSURANCE COMPANY"),
            _carrier_doc("b.pdf", "General Liability", "OMEGA CASUALTY COMPANY")]
    assert "Multiple carriers referenced across documents" in \
        assess_submission_integrity(docs)["reasons"]
    # two umbrella-LAYER policies from two companies
    docs = [_carrier_doc("a.pdf", "Commercial Liability Umbrella", "ALPHA INSURANCE COMPANY"),
            _carrier_doc("b.pdf", "Commercial Umbrella", "OMEGA CASUALTY COMPANY")]
    assert "Multiple carriers referenced across documents" in \
        assess_submission_integrity(docs)["reasons"]


def test_an_unplaceable_carrier_is_compared_as_before():
    docs = [_carrier_doc("a.pdf", "Commercial General Liability", "ALPHA INSURANCE COMPANY"),
            _doc("b.pdf", {"applicant_name": "ACME ELECTRIC LLC",
                           "carrier_name": "OMEGA CASUALTY COMPANY"})]
    assert "Multiple carriers referenced across documents" in \
        assess_submission_integrity(docs)["reasons"]


def test_one_carrier_group_on_one_line_is_not_a_signal():
    docs = [_carrier_doc("a.pdf", "Commercial General Liability",
                         "EMC Property & Casualty Company"),
            _carrier_doc("b.pdf", "General Liability", "Employers Mutual Casualty Company")]
    assert "Multiple carriers referenced across documents" not in \
        assess_submission_integrity(docs)["reasons"]


def test_different_insureds_still_pause():
    docs = [_carrier_doc("a.pdf", "Commercial General Liability", "ALPHA INSURANCE COMPANY"),
            _carrier_doc("b.pdf", "Cyber", "DELTA AMERICAN INSURANCE COMPANY",
                         insured="WAKE COUNTY BUILDERS INC")]
    v = assess_submission_integrity(docs)
    assert v["status"] == "low" and v["review_required"]
