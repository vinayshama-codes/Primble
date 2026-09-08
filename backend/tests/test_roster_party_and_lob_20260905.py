"""Two defects the SYS-09 live run exposed, neither of them SYS-09.

  1. THE CERTIFICATE HOLDER PRINTED AS AN OTHER NAMED INSURED. "Kestrel
     Terminal Authority" came out of `additional_named_insureds` and stamped
     onto ACORD 125 as `NAME (Other Named Insured)` with its own address. An
     Other Named Insured shares the policy, so the form asserted coverage for a
     party the policy does not name.

     An ADDITIONAL INSURED is not an ADDITIONAL NAMED INSURED. "Certificate
     holder is an additional insured with respect to operations" - the single
     most common sentence on a COI, and the one this package printed - grants
     limited status by endorsement and never makes the holder a named insured.

  2. A REFRIGERATED WAREHOUSE WAS SCORED AS A RESTAURANT. `infer_lob` tested
     bare substrings, so "cold storage of packaged FOOD products" answered a
     question about restaurants, and `LOB_RULES["restaurant"]` then charged the
     account for `occupancy_type` - a field a warehouse can never have.

THE SEAM IS THE POINT OF THIS FILE, TWICE OVER. The party filter for defect 1
already existed and was already correct; it was simply unreachable from the
primary document, because `merge_facts` only ran it over the NON-primary ones
and then unioned the primary's uncleaned list back in. Every unit test of the
helper passed while the live form was wrong. So every test below drives
`merge_facts` itself, never the helper alone.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline-test")

import services.pdf_service as ps                                # noqa: E402
from services.extraction_service import (                        # noqa: E402
    _drop_transaction_party_rows, merge_facts, select_primary_truth,
)
from services.sqs_service import (                               # noqa: E402
    LOB_RULES, NAICS_TO_LOB, _lob_from_operations, infer_lob,
)

# ── The live package, verbatim ──────────────────────────────────────────────
HOLDER = "Kestrel Terminal Authority"
APPLICANT = "Harborline Provisions LLC"
AGENCY = "Coastwater Insurance Brokers LLC"
CARRIER = "Granite Harbor Insurance Company"
AFFILIATE = "Harborline Logistics LLC"          # a REAL other named insured

# THE REAL EXTRACTION SHAPE, and the first version of this file did not use it.
#
# The fixture said `certificate_holder_name` at the TOP level. Extraction never
# emits that: the holder's name is the top-level `certificate_holder` (no `_name`
# suffix) and, separately, `risk_transfer.certificate_holder_name` nested inside
# a structured dict that nothing flattens. So 24 tests passed against a shape the
# system cannot produce while the live form still printed the holder.
#
# That is this project's own change-quality bar failing exactly as it warns:
# the fixture was easier than reality. Both real shapes are pinned here now, and
# `test_the_fixture_matches_what_extraction_can_actually_emit` fails the build if
# either drifts from the extraction schema.
_IDENTITY = {
    "applicant_name": APPLICANT,
    "certificate_holder": HOLDER,                       # top-level, no _name
    "risk_transfer": {"certificate_holder_name": HOLDER},   # nested
    "producer_name": AGENCY, "carrier_name": CARRIER,
    "producer_contact_name": "Delphine Ostrander",
}


def _doc(filename, doc_type, **facts):
    return {"filename": filename, "doc_type": doc_type, "text": "x",
            "flags": {}, "facts": dict(_IDENTITY, **facts)}


def _roster(docs):
    mf, _ = merge_facts(docs, select_primary_truth(docs))
    held = mf.get("additional_named_insureds")
    return held.get("value") if isinstance(held, dict) and "value" in held else held


_COI = _doc("coi.pdf", "certificate",
            additional_named_insureds=[HOLDER, AFFILIATE])
_NARRATIVE = _doc("narrative.pdf", "narrative",
                  additional_named_insureds=[HOLDER])


# ── 1. The roster, through the real merge ───────────────────────────────────

def test_the_certificate_holder_is_not_an_other_named_insured():
    """THE REPORTED CASE."""
    assert _roster([_COI, _NARRATIVE]) == [AFFILIATE]


def test_it_holds_on_a_SINGLE_document_session():
    """The configuration the helper could never see: with one document there is
    no `non_primary` list, so `_merge_list_fields` - where the filter used to
    live - is not called at all."""
    assert _roster([_COI]) == [AFFILIATE]


def test_it_holds_whichever_order_the_documents_arrive_in():
    assert _roster([_NARRATIVE, _COI]) == [AFFILIATE]


def test_a_real_affiliate_survives():
    """The guard must not empty the roster. An Other Named Insured is a real
    ACORD concept and a real submission carries them."""
    assert AFFILIATE in (_roster([_COI]) or [])


@pytest.mark.parametrize("party,label", [
    (HOLDER, "certificate holder"),
    (AGENCY, "the producer"),
    (CARRIER, "the carrier"),
    ("Delphine Ostrander", "the producer's contact person"),
    (APPLICANT, "the applicant itself - row A already prints it"),
])
def test_no_transaction_party_reaches_the_roster(party, label):
    assert _roster([_doc("d.pdf", "certificate",
                         additional_named_insureds=[party, AFFILIATE])]) == [AFFILIATE], label


@pytest.mark.parametrize("spelling", [
    HOLDER, HOLDER.upper(), HOLDER.lower(), f"  {HOLDER}  ",
    "Kestrel   Terminal   Authority",
])
def test_spelling_noise_does_not_defeat_the_drop(spelling):
    assert _roster([_doc("d.pdf", "certificate",
                         additional_named_insureds=[spelling, AFFILIATE])]) == [AFFILIATE]


def test_a_DIFFERENT_entity_with_a_similar_name_survives():
    """Fails toward KEEPING a row. `Kestrel Terminal Authority, Inc.` is a
    different legal name, so it is not dropped - the comparison is an identity
    key, never a substring. A missed drop is a visible wrong value a broker can
    fix; a wrong drop is invisible."""
    other = "Kestrel Terminal Authority Holdings LLC"
    assert other in _roster([_doc("d.pdf", "certificate",
                                  additional_named_insureds=[other])])


@pytest.mark.parametrize("rows,expected", [
    ([], []),
    ([None, "", HOLDER, AFFILIATE], [None, "", AFFILIATE]),
    ([123, HOLDER], [123]),
    ([{"name": HOLDER}, {"name": AFFILIATE}], [{"name": AFFILIATE}]),
])
def test_malformed_rows_do_not_crash_the_merge(rows, expected):
    """The list is declared [string]; a model that returns dicts, nulls or
    numbers must not take the merge down with it."""
    assert _drop_transaction_party_rows(
        "additional_named_insureds", list(rows), _IDENTITY) == expected


def test_with_no_identity_facts_nothing_is_dropped():
    """No party to compare against means no opinion - never a blanket delete."""
    assert _drop_transaction_party_rows(
        "additional_named_insureds", [HOLDER], {}) == [HOLDER]


def test_a_short_name_is_never_used_as_a_blocker():
    """"Lee" would collide with half the roster."""
    assert _drop_transaction_party_rows(
        "additional_named_insureds", ["Lee"], {"applicant_name": "Lee"}) == ["Lee"]


def test_the_form_prints_the_affiliate_and_not_the_holder():
    """Through the real stamper, because the field is what the client sees."""
    mf, _ = merge_facts([_COI], select_primary_truth([_COI]))
    path = os.path.join(os.path.dirname(__file__), "..", "forms_schemas",
                        "ACORD_125_schema.json")
    with open(path, encoding="utf-8") as fh:
        schema = json.load(fh)
    res = ps.map_facts_to_form(dict(mf), schema, "ACORD_125")
    mapped = res[0] if isinstance(res, tuple) else res
    assert mapped.get("NamedInsured_FullName_A") == APPLICANT
    assert mapped.get("NamedInsured_FullName_B") == AFFILIATE


# ── 2. The wider class the same hole left open ──────────────────────────────

def test_the_producers_office_is_dropped_from_the_PRIMARY_documents_premises():
    """Not the reported key. The filter has always known how to drop the
    producer's own office from `property_locations`, and it was unreachable
    from the primary document in exactly the same way - so closing the hole for
    one list and not the others would have left the same defect standing."""
    doc = {"filename": "dec.pdf", "doc_type": "dec_page", "text": "x", "flags": {},
           "facts": {
               "producer_address": "9780 S Meridian Blvd STE 400, Englewood, CO 80112",
               "property_locations": [
                   {"address_line1": "9780 S Meridian Blvd STE 400", "address_zip": "80112"},
                   {"address_line1": "2255 Shorebank Ave", "address_zip": "98402"},
               ]}}
    mf, _ = merge_facts([doc], select_primary_truth([doc]))
    assert [r["address_line1"] for r in mf["property_locations"]] == ["2255 Shorebank Ave"]


# ── 2b. The door itself: derived membership, not a list of key names ────────

def test_the_holder_is_found_in_EITHER_place_extraction_writes_it():
    """The bug this door replaced: the guard read `certificate_holder_name` at the
    top level, where it never exists. Both real shapes must work, separately."""
    from services.extraction_service import third_party_identity_names as names
    assert HOLDER in names({"certificate_holder": HOLDER})
    assert HOLDER in names({"risk_transfer": {"certificate_holder_name": HOLDER}})


@pytest.mark.parametrize("facts", [
    {"certificate_holder": HOLDER},
    {"risk_transfer": {"certificate_holder_name": HOLDER}},
    {"certificate_holder": {"value": HOLDER, "confidence": "ai_high"}},
    {"risk_transfer": {"value": {"certificate_holder_name": HOLDER}}},
])
def test_the_roster_drop_works_from_every_real_shape(facts):
    assert _drop_transaction_party_rows(
        "additional_named_insureds", [HOLDER, AFFILIATE],
        dict(facts, applicant_name=APPLICANT)) == [AFFILIATE]


@pytest.mark.parametrize("key,seen", [
    ("certificate_holder", True), ("certificate_holder_name", True),
    ("mortgagee_name", True), ("loss_payee_name", True),
    ("producer_name", True), ("carrier_name", True), ("wc_prior_carrier", True),
    # ...and the same parties' ATTRIBUTES are not identities.
    ("certificate_holder_address", False), ("producer_address", False),
    ("producer_contact_phone", False), ("carrier_naic", False),
    ("certificate_description_of_operations", False),
    # ...and facts that name no party at all.
    ("applicant_name", False), ("operations_description", False),
    ("total_revenue", False),
])
def test_a_key_is_classified_by_what_it_MEANS(key, seen):
    from services.extraction_service import _is_party_identity_key
    assert _is_party_identity_key(key) is seen, key


def test_a_party_name_carrying_its_address_still_matches():
    """The questionnaire asks for the holder's "name and address" in one box, so
    the fact legitimately arrives as both."""
    facts = {"applicant_name": APPLICANT,
             "certificate_holder": f"{HOLDER}, 1201 Port of Tacoma Rd, Tacoma WA 98421"}
    assert _drop_transaction_party_rows(
        "additional_named_insureds", [HOLDER, AFFILIATE], facts) == [AFFILIATE]


@pytest.mark.parametrize("party", ["Acme, Inc.", "Smith, Jones & Co."])
def test_a_comma_in_a_company_name_is_not_an_address(party):
    """The split needs a ZIP after the comma, so a suffix comma never shortens a
    name into something that could match a different company."""
    kept = _drop_transaction_party_rows(
        "additional_named_insureds", ["Acme Holdings LLC", "Smith Brothers LLC"],
        {"certificate_holder": party})
    assert kept == ["Acme Holdings LLC", "Smith Brothers LLC"]


def test_an_additional_insured_is_NOT_blocked_wholesale():
    """OWNER RULING 2026-09-06. An additional insured is not an additional NAMED
    insured, but blocking the whole list can delete a real subsidiary that is
    listed as both. A genuine name with no other third-party role keeps its
    place."""
    facts = {"applicant_name": APPLICANT,
             "risk_transfer": {"additional_insured_names": [AFFILIATE]}}
    assert _drop_transaction_party_rows(
        "additional_named_insureds", [AFFILIATE], facts) == [AFFILIATE]


def test_an_additional_insured_who_is_ALSO_the_holder_is_still_dropped():
    """The other half of that ruling: block on IDENTITY, not on membership. We
    can prove this one is a third party, so it goes."""
    facts = {"applicant_name": APPLICANT, "certificate_holder": HOLDER,
             "risk_transfer": {"additional_insured_names": [HOLDER, AFFILIATE]}}
    assert _drop_transaction_party_rows(
        "additional_named_insureds", [HOLDER, AFFILIATE], facts) == [AFFILIATE]


def test_every_party_identity_fact_is_visible_to_the_door():
    """THE ANTI-ROT GUARD, and the answer to "there can be more than three
    places". Extraction adds, renames and nests keys; a hand-written list of key
    names goes silently dead when it does, which is exactly what happened. This
    walks the REAL extraction schema and fails the build if a party-name key
    appears that the door cannot see."""
    import re as _re
    from services import extraction_service as es
    keys = set(_re.findall(r'"([a-z0-9_]+)"\s*:', es._EXTRACT_SCHEMA))
    assert len(keys) > 100, "the schema scrape found nothing - fix the test"
    role_keys = {k for k in keys
                 if any(t in k for t in es._THIRD_PARTY_ROLE_TOKENS)}
    assert role_keys, "no party keys found at all"
    unseen = {k for k in role_keys
              if k.endswith("_name") and not es._is_party_identity_key(k)}
    assert not unseen, (
        f"these party-name facts are invisible to the blocked-party door: "
        f"{sorted(unseen)} - add the role word or fix the attribute list")


def test_the_fixture_matches_what_extraction_can_actually_emit():
    """The failure underneath the failure: 24 tests passed against a shape the
    system never produces. Both keys this file's fixture uses must exist in the
    real extraction schema, so a rename breaks the build instead of quietly
    making every test above vacuous."""
    from services import extraction_service as es
    assert '"certificate_holder"' in es._EXTRACT_SCHEMA
    assert '"certificate_holder_name"' in es._EXTRACT_SCHEMA
    assert "certificate_holder" in _IDENTITY
    assert "certificate_holder_name" in _IDENTITY["risk_transfer"]
    assert "certificate_holder_name" not in _IDENTITY, (
        "top-level `certificate_holder_name` is the shape that does not exist")


def test_the_merge_runs_the_party_filter_on_the_FINAL_list():
    """THE ANTI-ROT GUARD, and the whole lesson of this file. The helper was
    correct for months while the live form was wrong, because `merge_facts`
    only ever handed it the non-primary documents."""
    import inspect
    from services import extraction_service as es
    src = inspect.getsource(es.merge_facts)
    _, _, tail = src.partition("Apply primary doc as legacy fallback")
    assert "_PARTY_FILTERED_LIST_KEYS" in tail, (
        "the party filter must run AFTER the primary document's lists are "
        "merged in, or the primary bypasses it exactly as it did before")


# ── 2c. The ADDRESS half of the same row ────────────────────────────────────
#
# Dropping the holder's NAME does not clear the address boxes under it. Live run
# 2: gap fill wrote the applicant's suite and the holder's ZIP into row B under a
# blank name. The post-fill net that exists for exactly this was skipping row B.

def _schema_125():
    path = os.path.join(os.path.dirname(__file__), "..", "forms_schemas",
                        "ACORD_125_schema.json")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def test_an_anchorless_row_B_address_is_cleared():
    """THE LIVE CASE. No name in row B, so an address in row B answers a question
    about a company the form does not name."""
    mapped = {
        "NamedInsured_FullName_B": "",
        "NamedInsured_MailingAddress_LineTwo_B": "Ste 300",
        "NamedInsured_MailingAddress_CityName_B": "Tacoma",
        "NamedInsured_MailingAddress_PostalCode_B": "98421",
    }
    gpt = set(mapped)
    got = ps._unanchored_schedule_row_fields(mapped, _schema_125(), gpt)
    assert "NamedInsured_MailingAddress_CityName_B" in got
    assert "NamedInsured_MailingAddress_PostalCode_B" in got


def test_a_row_B_WITH_a_name_is_left_alone():
    """A real other named insured keeps its address."""
    mapped = {
        "NamedInsured_FullName_B": AFFILIATE,
        "NamedInsured_MailingAddress_CityName_B": "Tacoma",
    }
    got = ps._unanchored_schedule_row_fields(mapped, _schema_125(), set(mapped))
    assert not got


def test_row_A_is_still_never_judged():
    """Row A is the APPLICANT, not a list row. Judging it cleared a genuine
    equipment description when this guard was first wired, and `<` alone would
    have reintroduced exactly that on every other schedule."""
    mapped = {"NamedInsured_FullName_A": "",
              "NamedInsured_MailingAddress_CityName_A": "Tacoma"}
    got = ps._unanchored_schedule_row_fields(mapped, _schema_125(), set(mapped))
    assert not got


def test_offset_zero_schedules_are_unchanged_by_the_row_B_fix():
    """`NamedInsured` is the only root whose list starts at row B. Every other
    schedule must judge exactly the rows it judged before."""
    mapped = {"Vehicle_ManufacturersName_A": "",
              "Vehicle_CostNewAmount_A": "58900"}
    got = ps._unanchored_schedule_row_fields(mapped, _schema_125(), set(mapped))
    assert "Vehicle_CostNewAmount_A" not in got, "row A must stay exempt"


def test_only_gap_filled_values_are_cleared():
    """A deterministic value implies the record exists; the net never touches it."""
    mapped = {"NamedInsured_FullName_B": "",
              "NamedInsured_MailingAddress_CityName_B": "Tacoma"}
    got = ps._unanchored_schedule_row_fields(mapped, _schema_125(), set())
    assert not got


# ── 3. The industry classifier ──────────────────────────────────────────────

def test_a_cold_store_is_not_a_restaurant():
    """THE REPORTED CASE, verbatim from the generated package."""
    ops = "Refrigerated warehousing and cold storage of packaged food products."
    assert infer_lob({"operations_description": ops}, {}) == "generic"


@pytest.mark.parametrize("ops,why", [
    ("Apparel manufacturing and wholesale distribution", "'app' inside apparel"),
    ("Appliance repair and installation", "'app' inside appliance"),
    ("Geotechnical engineering and soil testing", "'tech' inside geotechnical"),
    ("Certified technician staffing", "'tech' inside technician"),
    ("Manufacture of platform trailers", "'platform' as a trailer"),
    ("Kitchen cabinet manufacturing", "'kitchen' as a product"),
    ("Delivery of janitorial services to offices", "'delivery' as a verb"),
    ("Food products cold chain logistics", "'food'/'logistics' - neither implies a fleet"),
    ("Frozen food storage and distribution", "'food' again"),
])
def test_a_bare_substring_no_longer_decides_an_industry(ops, why):
    assert infer_lob({"operations_description": ops}, {}) == "generic", why


@pytest.mark.parametrize("ops,expected", [
    ("Full service restaurant and bar", "restaurant"),
    ("Commercial roofing contractor", "contractor"),
    ("Long haul trucking and freight hauling", "transportation"),
    ("Custom software development and SaaS products", "technology"),
    ("RESTAURANT", "restaurant"),
    ("We operate two restaurants", "restaurant"),
])
def test_a_real_industry_is_still_recognised(ops, expected):
    """The fix must not cost the classifications that were right."""
    assert infer_lob({"operations_description": ops}, {}) == expected


@pytest.mark.parametrize("ops,why", [
    ("Janitorial services for grocery, restaurant and retail accounts",
     "THE CLIENT'S OWN EXAMPLE - the words name the CUSTOMERS"),
    ("Provides linens and uniforms for restaurants and hotels", "supplies them"),
    ("Wholesale distribution to restaurant and bar operators", "sells to them"),
])
def test_someone_elses_industry_is_not_the_applicants(ops, why):
    assert infer_lob({"operations_description": ops}, {}) == "generic", why


def test_a_customer_phrase_does_not_swallow_the_applicants_own_trade():
    """The other direction: naming your customers must not erase what YOU do."""
    assert infer_lob(
        {"operations_description": "Software for trucking companies"}, {}) == "technology"


@pytest.mark.parametrize("ops", [
    "Restaurant construction and tenant improvement contractor",
    "Freight hauling and restaurant operations",
    "Roofing contractor and courier services",
])
def test_two_industries_at_once_resolve_to_generic(ops):
    """Ambiguity is answered with the least demanding rule set, never a guess.

    NOTE what does NOT belong in this list, because the first draft got it
    wrong: "Software development FOR restaurants" is not ambiguous. The
    customer-phrase rule strips "restaurants" as somebody else's trade, one
    bucket survives, and `technology` is the correct answer - which is exactly
    what `test_a_customer_phrase_does_not_swallow_the_applicants_own_trade`
    pins. Two industries means two the APPLICANT is in."""
    assert _lob_from_operations(ops.lower()) == "generic"


@pytest.mark.parametrize("value", [
    None, 123, 0, False, ["a", "b"], {"nope": 1}, b"bytes", {"value": None},
])
def test_a_malformed_operations_fact_cannot_take_a_score_down(value):
    """`infer_lob` is called inside both score computations. H1-G is a live run
    that lost its Total Package Score with no reproducible trigger; a
    `.lower()` on a fact that arrived as a list is exactly that shape."""
    assert infer_lob({"operations_description": value}, {}) == "generic"


def test_missing_facts_and_flags_are_safe():
    assert infer_lob({}, {}) == "generic"
    assert infer_lob({"operations_description": "x"}, None) == "generic"


def test_food_manufacturing_naics_is_no_longer_a_restaurant():
    """311 is Food Manufacturing and 312 is Beverage Manufacturing. This file's
    own `_NAICS_SECTOR_INDUSTRY` has always called 31/32/33 manufacturing."""
    for code in ("311", "312"):
        assert code not in NAICS_TO_LOB
    assert infer_lob({"naics_code": "311612",
                      "operations_description": "Meat processing"}, {}) == "generic"
    assert infer_lob({"naics_code": "722511"}, {}) == "restaurant"


def test_every_lob_the_classifier_can_return_has_a_rule_set():
    """A bucket with no `LOB_RULES` entry silently falls back to generic, which
    would make the classification a lie rather than an error."""
    returned = {"generic", "contractor", "restaurant", "transportation", "technology"}
    returned |= set(NAICS_TO_LOB.values())
    assert returned - set(LOB_RULES) <= {"manufacturing"}, (
        "a returnable bucket has no rule set of its own")


def test_the_customer_phrase_door_is_the_shared_one():
    """Reused from `cross_form_validator`, which built it for this identical
    defect on this identical live run. Two copies would drift; the import
    failing silently would restore the bug, so it is asserted, not assumed."""
    from services.cross_form_validator import (
        _CUSTOMER_AFTER_RE, _CUSTOMER_BEFORE_RE,
    )
    assert _CUSTOMER_BEFORE_RE.search("janitorial services for grocery, ")
    assert _CUSTOMER_AFTER_RE.match(" and retail accounts")
