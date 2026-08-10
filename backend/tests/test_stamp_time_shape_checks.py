"""Stamp-time shape checking and unanchored entity rows.

Client report (ACORD 125, Orbin Contracting):
  #8  "The FEIN field contains 0482854. That is the EMC account number, not the
       insured's FEIN."
  #11 ""Claim Reporting: (888) 362-2255" in an email field ... phone information
       has been placed into email fields."
  #10 "Remove incomplete Other Named Insured records: a second LLC indicator,
       partial FEIN 84-, a member/manager range of 0-25, another partial address
       record without a corresponding named insured. These are not usable
       records."

`fact_registry._is_fein` ("9 digits, with or without hyphen") has been correct
all along and never ran: `pdf_service` imports `FACT_REGISTRY` for its KEYS only.

BEHAVIOUR IS DEMOTE, NOT BLANK. The value stays on the form and its trust label
drops to `low_confidence`, which the highlight layer paints orange ("Verify").
The real defect on the client's form was not only the bad FEIN - it was that
`0482854` was painted PINK, i.e. `ai_verified`, which this codebase defines as
"AI-filled AND confirmed present in the uploaded documents". Asserting verified
on an unverifiable value is worse than the value.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline-test")

import services.pdf_service as ps                        # noqa: E402

_SCHEMA_DIR = os.path.join(os.path.dirname(__file__), "..", "forms_schemas")


def _acord125():
    with open(os.path.join(_SCHEMA_DIR, "ACORD_125_schema.json"), encoding="utf-8") as fh:
        return json.load(fh)


# ── Shape checking ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("field,value", [
    ("NamedInsured_TaxIdentifier_A", "0482854"),                    # client #8
    ("NamedInsured_TaxIdentifier_B", "84-"),                        # client #10
    ("Producer_ContactPerson_EmailAddress_A", "ERIN ROYAL"),        # client #1
    ("NamedInsured_Contact_PrimaryEmailAddress_A",
     "Claim Reporting: (888) 362-2255"),                            # client #11
])
def test_client_reported_values_are_flagged(field, value):
    assert ps._shape_violation(field, value) is not None


@pytest.mark.parametrize("field,value", [
    ("NamedInsured_TaxIdentifier_A", "84-2210987"),
    ("NamedInsured_TaxIdentifier_A", "842210987"),
    ("Producer_ContactPerson_EmailAddress_A", "erin.royal@crsinc.com"),
    ("NamedInsured_Primary_WebsiteAddress_A", "www.orbincontracting.com"),
    # C22's rule: an amount box legitimately holds prose. Currency validators are
    # deliberately NOT enforced against form fields.
    ("GeneralLiability_EachOccurrenceLimit_A", "Statutory"),
    ("GeneralLiability_EachOccurrenceLimit_A", "Included"),
    ("GeneralLiability_EachOccurrenceLimit_A", "See schedule"),
    ("Policy_EffectiveDate_A", "07/15/2025"),
    ("CommercialPolicy_OperationsDescription_A", "Commercial general contractor"),
])
def test_legitimate_values_are_never_flagged(field, value):
    assert ps._shape_violation(field, value) is None


def test_the_carrier_website_is_a_shape_pass_not_a_shape_failure():
    """`Www.emcins.com` IS a valid URL. What is wrong with it is OWNERSHIP - the
    carrier's site in the applicant's box - which the entity guard handles.
    Keeping the two concerns separate matters: a shape check that tried to judge
    whose website it is would have no basis to do so."""
    assert ps._shape_violation(
        "NamedInsured_Primary_WebsiteAddress_A", "Www.emcins.com") is None


def _shape_checked_fields():
    import glob
    return [
        (path, f) for path in glob.glob(os.path.join(_SCHEMA_DIR, "*_schema.json"))
        for f in json.load(open(path, encoding="utf-8"))
        if ps._shape_violation(f, "zzz-not-valid-anything")
    ]


def test_the_check_is_narrowly_scoped():
    """STANDING GUARD on blast radius. Only fields with a legally-defined shape
    and no legitimate prose alternative are checked. If this count jumps, a
    validator was enforced that should not have been.

    192 as of the postal-code and count tokens (2026-08-09): 113 employee/member
    counts, 59 postal codes, 16 e-mail addresses, 4 websites. Each addition is
    swept against every type-appropriate legitimate value on every field it
    touches before the bound moves - see `test_the_swept_scope_has_no_false_positives`.
    """
    touched = _shape_checked_fields()
    assert 150 <= len(touched) <= 230, (
        f"{len(touched)} fields are shape-checked; expected ~192. Review the "
        "validator set before accepting a change here."
    )


def test_no_checkbox_is_ever_shape_checked():
    """THE NEAR MISS. ACORD 133's `Policy_NoPreviousCoverage_EmployeeCountIndicator_A`
    is a /Btn that merely MENTIONS an employee count. A substring match ran the
    count validator over its tick value and would have blanked it."""
    offenders = [
        (os.path.basename(path), f) for path, f in _shape_checked_fields()
        if json.load(open(path, encoding="utf-8"))[f].get("ft") != "/Tx"
    ]
    assert offenders == [], offenders


def test_the_swept_scope_has_no_false_positives():
    """C22's precedent: a blanking rule ships only after a cross-product sweep of
    every type-appropriate legitimate value against every field it can touch."""
    legitimate = {
        "email": ["john.doe@orbin.com", "a@b.co", "ERIN.ROYAL@emcins.com"],
        "url": ["www.orbin.com", "https://orbin.com", "http://www.a-b.co.uk/x"],
        # A Canadian code is legitimate - two of these boxes sit beside an
        # AdditionalInterest_MailingAddress_CountryCode field.
        "zip": ["80216", "80216-3121", "802163121", "M5H 2N2", "m5h2n2"],
        # "1,200" and "approx. 25" are imprecise, not impossible.
        "count": ["25", "0", "1,200", "1200", "approx. 25", "25 (average)"],
    }
    failures = []
    for path, field in _shape_checked_fields():
        for token, kind in ps._NAME_SHAPE_TOKENS:
            if not any(seg.endswith(token) for seg in field.split("_")):
                continue
            for value in legitimate[kind]:
                if ps._shape_violation(field, value):
                    failures.append((field, value))
    assert failures == [], failures[:10]
    assert len(_shape_checked_fields()) > 100, "harvest is empty - test is vacuous"


@pytest.mark.parametrize("field,value", [
    ("CommercialStructure_PhysicalAddress_PostalCode_B", "4800 D"),
    ("CommercialStructure_PhysicalAddress_PostalCode_D", "Denve"),
    ("NamedInsured_LegalEntity_MemberManagerCount_B", "0 - 25"),
    ("NamedInsured_LegalEntity_MemberManagerCount_A", "LLC"),
    ("BusinessInformation_FullTimeEmployeeCount_A", "10 to 20"),
])
def test_the_live_run_address_fragments_and_ranges_are_refused(field, value):
    assert ps._shape_violation(field, value) is not None


def test_empty_and_malformed_input_is_survivable():
    for value in (None, "", "   "):
        assert ps._shape_violation("NamedInsured_TaxIdentifier_A", value) is None


# ── Unanchored entity rows ───────────────────────────────────────────────────

ORPHAN_ROW = {
    "NamedInsured_FullName_A": "Orbin Contracting LLC",
    "NamedInsured_TaxIdentifier_A": "84-2210987",
    "NamedInsured_FullName_B": "",
    "NamedInsured_TaxIdentifier_B": "84-",
    "NamedInsured_LegalEntity_MemberManagerCount_B": "0 - 25",
    "NamedInsured_MailingAddress_LineOne_B": "4800 Dahlia St D13",
}


def test_client_reported_orphan_row_is_flagged():
    flagged = ps._unanchored_entity_row_fields(ORPHAN_ROW, _acord125())
    assert flagged == {
        "NamedInsured_TaxIdentifier_B",
        "NamedInsured_LegalEntity_MemberManagerCount_B",
        "NamedInsured_MailingAddress_LineOne_B",
    }


def test_a_named_second_insured_is_untouched():
    """The fix must not penalise a real second named insured."""
    mapped = dict(ORPHAN_ROW, NamedInsured_FullName_B="Orbin Equipment Leasing LLC")
    assert ps._unanchored_entity_row_fields(mapped, _acord125()) == set()


def test_row_a_is_never_questioned():
    """Row A is the primary record. Even with a missing name it is not an
    artefact of the repeating-slot prompt."""
    mapped = {"NamedInsured_FullName_A": "", "NamedInsured_TaxIdentifier_A": "84-2210987"}
    assert ps._unanchored_entity_row_fields(mapped, _acord125()) == set()


def test_rows_without_a_name_box_have_no_anchor_and_are_left_alone():
    """A building or vehicle row legitimately has data and no "name". Grouping by
    raw name prefix instead of the verified entity prefixes would have swept
    CommercialStructure_* rows in here."""
    schema = _acord125()
    structure_rows = {
        f: "value" for f in schema
        if f.startswith("CommercialStructure_") and f.endswith("_B")
    }
    assert structure_rows, "no CommercialStructure row B in the schema"
    assert ps._unanchored_entity_row_fields(structure_rows, schema) == set()


def test_scope_is_bounded_across_all_forms():
    """STANDING GUARD: 27 non-primary entity rows on 9 forms. A jump means the
    entity prefix set or the anchor rule changed."""
    import glob
    import re
    total = 0
    for path in glob.glob(os.path.join(_SCHEMA_DIR, "*_schema.json")):
        schema = json.load(open(path, encoding="utf-8"))
        rows = set()
        for field in schema:
            m = ps._SCHED_ROW_RE.match(field)
            if not m or m.group(2) == "A":
                continue
            entity = ps._field_entity(m.group(1))
            if entity and m.group(1).endswith("FullName"):
                rows.add((entity, m.group(2)))
        total += len(rows)
    assert total == 27, f"expected 27 non-primary entity rows, found {total}"


# ── The label is the point ───────────────────────────────────────────────────

def test_a_bad_value_can_never_be_labelled_verified():
    """`ai_verified` means "confirmed present in the uploaded documents" and
    paints PINK. The client's fabricated FEIN was pink. A shape failure must
    outrank every other label, including `filled`, which paints nothing at all.
    """
    order = ps.map_facts_to_form.__doc__ or ""
    assert "Confidence labels feed the highlight layer" in order
    # The behavioural assertion: the demotion set is consulted before the others.
    import inspect
    src = inspect.getsource(ps.map_facts_to_form)
    shape_at = src.index("if field in _shape_failures")
    verified_at = src.index('confidence[field] = "ai_verified"')
    filled_at = src.index('confidence[field] = "filled"')
    assert shape_at < filled_at < verified_at, (
        "a shape failure must be checked before `filled` and `ai_verified`"
    )
