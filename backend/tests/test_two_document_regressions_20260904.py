"""Two defects that only appear once a SECOND document is uploaded.

Both were found on the SYS-05 live kit, both were invisible on a single-document
submission, and both are the same shape as a defect this codebase has already
fixed once: a PER-DOCUMENT signal answering a PACKAGE-LEVEL question.

`producer_fields_exempt` records that shape in its own correction #1 - it keyed
on `_doc_type`, which is the PRIMARY document's type, so a package of dec page +
application was exempted from producer name even though the application prints
it. The remedy there was `_only_dec_page`, computed by the pipeline over EVERY
active document. Both fixes here take the same remedy.
"""
import json
import os

import pytest

from services.extraction_service import (
    _derive_operations_description_from_locations as derive_ops,
)
from services.pdf_service import map_facts_to_form
from services.sqs_service import certificate_only_package, key_details

OPS = "Refrigerated trucking and cold storage warehousing of food products"

_FULL_FACTS = {
    "applicant_name": "Marisol Freight & Cold Storage LLC",
    "mailing_address": "4820 Harborgate Way, Suite 260, Tacoma, WA 98421",
    "effective_date": "10/03/2026",
    "entity_type": "Limited Liability Company",
    "contact_name": "Priya Raghunathan",
    "lines_of_business": ["General Liability", "Business Auto"],
    "fein": "47-6120933", "operations_description": OPS,
    "total_revenue": "14300000", "num_employees": "62",
    "years_in_business": "17", "naics_code": "493120",
}


# ── 1. A supporting certificate must not collapse the whole checklist ───────
#
# LIVE, SYS-05 run 2 (2026-09-04): "Key details in place" went from 12 items to
# 8 the moment a certificate was uploaded beside the declarations page. Mailing
# address, lines of business, entity type and contact information all left the
# list - while the generated ACORD 125 printed every one of them correctly. The
# data was right; only the checklist was wrong.
#
# `_tier1_items` collapses Tier 1 to two items on `is_certificate_doc`, which is
# a PER-DOCUMENT flag ("this document IS an ACORD 25/28"). Flags merge across
# the package, so one supporting COI spoke for the whole submission.

def _in_place(flags):
    return set(key_details(_FULL_FACTS, flags)["satisfied"])


_TIER1_LABELS = {"Applicant mailing address", "Lines of business requested",
                 "Business entity type", "Contact information"}


def test_a_certificate_beside_a_dec_page_keeps_the_full_checklist():
    """The reported case. `_only_certificate` is False - the package also has a
    declarations page - so the full Tier 1 checklist applies."""
    assert _TIER1_LABELS <= _in_place({"is_certificate_doc": True,
                                       "_only_certificate": False})


def test_a_legacy_session_without_the_flag_also_keeps_it():
    """Sessions written before `_only_certificate` existed have no such key.
    Absent means False, which can only ever ADD checklist items - never hide
    one. Same migration direction `_only_dec_page` took."""
    assert _TIER1_LABELS <= _in_place({"is_certificate_doc": True})


def test_a_genuine_certificate_only_submission_still_gets_the_short_list():
    """The collapse is RIGHT here: a COI cannot carry an application's details,
    and scoring it down for that marks a submission for what its document type
    can never state."""
    got = _in_place({"is_certificate_doc": True, "_only_certificate": True})
    assert not (_TIER1_LABELS & got)
    assert "Applicant legal name" in got and "Proposed effective date" in got


def test_needing_a_certificate_is_not_the_same_as_being_one():
    """MY OWN FIRST FIX WAS INCOMPLETE, and the live run caught it.

    I gated `is_certificate_doc` and left `has_certificate_request` alone,
    reasoning it was already package-level. It is - but it answers a DIFFERENT
    question. The extraction prompt sets it when a document "lists a certificate
    holder", and the SYS-05 certificate names Cascade Terminal Authority. So the
    checklist stayed collapsed and the live re-run still read 8 items.

    A full commercial package routinely needs a COI for a landlord or a
    terminal. Needing one is not being one. Fixing one signal and assuming the
    other was safe is the same mistake as the bug itself: a flag that answers
    question A deciding question B.
    """
    assert _TIER1_LABELS <= _in_place({"has_certificate_request": True,
                                       "_only_certificate": False})
    assert _TIER1_LABELS <= _in_place({"has_certificate_request": True,
                                       "_only_dec_page": True})


def test_the_live_two_document_package_gets_the_full_checklist():
    """Both flags true at once - the exact shape of the live run: a dec page
    plus a certificate that names its holder."""
    assert _TIER1_LABELS <= _in_place({"is_certificate_doc": True,
                                       "has_certificate_request": True,
                                       "_only_certificate": False})


def test_a_certificate_only_submission_that_also_names_a_holder_still_collapses():
    """Both signals true AND the package really is certificate-only - the case
    the short checklist exists for."""
    assert not (_TIER1_LABELS & _in_place({"is_certificate_doc": True,
                                           "has_certificate_request": True,
                                           "_only_certificate": True}))


def test_a_dec_page_package_is_unchanged():
    assert _TIER1_LABELS <= _in_place({"_only_dec_page": True})


@pytest.mark.parametrize("flags,want", [
    ({"_only_certificate": True}, True),
    ({"_only_certificate": False}, False),
    ({}, False), (None, False), ({"_only_certificate": "yes"}, False),
])
def test_certificate_only_package_reads_strictly(flags, want):
    assert certificate_only_package(flags) is want


def test_the_pipeline_computes_the_flag_over_EVERY_active_document():
    """The seam. A per-document signal answering a package question is the whole
    defect, so the flag has to be built from the full active list."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "services",
                            "extraction_pipeline.py"), encoding="utf-8").read()
    i = src.index('mflags["_only_certificate"]')
    block = src[i:i + 220]
    assert "_active_types" in block, "must read every active document, not the primary"
    assert "all(" in block and "bool(_active_types)" in block, (
        "an empty document list is not 'only certificates'")


# ── 2. Operations stated against the PREMISES, not the applicant ───────────
#
# Measured 2026-09-04 by driving the real stamper: with the scalar present both
# the premises row AND "Description of Primary Operations" fill. With the value
# only on `property_locations[0]`, the premises row fills and the PRIMARY
# OPERATIONS box on ACORD 125 ships BLANK - the binding is one-directional.

def _schema():
    p = os.path.join(os.path.dirname(__file__), "..", "forms_schemas",
                     "ACORD_125_schema.json")
    s = json.load(open(p, encoding="utf-8"))
    return s.get("fields") or s


def _stamped(facts):
    r = map_facts_to_form(facts, _schema(), "ACORD_125")
    m = r[0] if isinstance(r, tuple) else r
    return (bool(m.get("BuildingOccupancy_OperationsDescription_A")),
            bool(m.get("CommercialPolicy_OperationsDescription_A")))


def _value(facts):
    v = facts.get("operations_description")
    return v.get("value") if isinstance(v, dict) else v


def test_the_primary_operations_box_no_longer_ships_blank():
    """The reproduced gap. Before: premises FILLED, primary operations BLANK."""
    facts = {"applicant_name": "X",
             "property_locations": [{"address_line1": "A",
                                     "operations_description": OPS}]}
    derive_ops(facts)
    assert _value(facts) == OPS
    assert _stamped(facts) == (True, True)


def test_premises_that_agree_derive_one_applicant_level_fact():
    facts = {"property_locations": [
        {"address_line1": "A", "operations_description": OPS},
        {"address_line1": "B", "operations_description": "  Refrigerated  trucking and cold storage warehousing of food products "},
    ]}
    derive_ops(facts)
    assert _value(facts) == OPS, "whitespace and case must not defeat agreement"


def test_premises_that_DISAGREE_derive_nothing():
    """Two premises describing different operations is a real distinction, and
    the ACORD's per-location boxes already carry it. Collapsing them into one
    applicant-level sentence would invent a fact (Principle 4)."""
    facts = {"property_locations": [
        {"address_line1": "A", "operations_description": OPS},
        {"address_line1": "B", "operations_description": "Retail bakery"},
    ]}
    derive_ops(facts)
    assert _value(facts) is None


def test_a_stated_value_is_never_overwritten():
    facts = {"operations_description": "Stated by the applicant",
             "property_locations": [{"address_line1": "A",
                                     "operations_description": OPS}]}
    derive_ops(facts)
    assert _value(facts) == "Stated by the applicant"


def test_the_derivation_labels_its_own_provenance():
    """Principle 6 - a derived value must never look like a stated one."""
    facts = {"property_locations": [{"address_line1": "A",
                                     "operations_description": OPS}]}
    derive_ops(facts)
    env = facts["operations_description"]
    assert env["source"] == "derived" and env["evidence_state"] == "derived"
    assert env["derivation"]["inputs"] == ["property_locations"]


def test_it_reads_an_envelope_inside_a_row():
    facts = {"property_locations": [{"address_line1": "A",
                                     "operations_description": {"value": OPS}}]}
    derive_ops(facts)
    assert _value(facts) == OPS


@pytest.mark.parametrize("facts", [
    {}, {"property_locations": None}, {"property_locations": []},
    {"property_locations": "not a list"}, {"property_locations": [None, "x", 7]},
    {"property_locations": [{"address_line1": "A"}]},
    {"property_locations": [{"operations_description": "   "}]},
])
def test_nothing_to_derive_is_safe_and_silent(facts):
    derive_ops(facts)
    assert _value(facts) is None


def test_an_acord_125_is_not_scored_as_a_certificate_because_a_COI_was_uploaded():
    """THIRD SITE of the same defect, found by grepping for the flag after the
    live re-run rather than by another round trip.

    `calculate_sqs` set `is_cert_only = fid == "ACORD_25" or
    flags["is_certificate_doc"]`. The second half is per-document and flags
    merge, so any uploaded COI graded the ACORD 125 against the CERTIFICATE
    checklist (applicant / effective date / policy number) instead of its own.
    That does not mis-score a form slightly; it grades the wrong form.
    """
    import inspect
    from services import sqs_service as sq
    src = inspect.getsource(sq.calculate_sqs)
    i = src.index("is_cert_only =")
    block = src[i:i + 200]
    assert "certificate_only_package" in block, (
        "the package signal must ask whether the SUBMISSION is certificate-only")
    assert 'fid == "ACORD_25"' in block, (
        "scoring the ACORD 25 itself must still use the certificate checklist")


def test_all_three_sites_read_the_same_door():
    """One question, one answer. Three copies of 'is this a certificate
    submission' is the duplication class that cost this codebase the Umbrella
    SIR and auto-symbol bugs - each survived its first fix because a second copy
    went unchanged."""
    import inspect
    from services import sqs_service as sq
    for fn in (sq._tier1_items, sq.calculate_sqs):
        src = inspect.getsource(fn)
        if "is_certificate_doc" in src:
            assert "certificate_only_package" in src, (
                f"{fn.__name__} reads is_certificate_doc without the package door")


# ── 3. Guard 4 was deleting a field's OWN value ────────────────────────────
#
# THE ACTUAL CAUSE of the blank operations boxes, found by driving
# `_enforce_post_fill_guards` rather than by another live round trip.
#
# Guard 4 CLUSTERS values by near-duplicate similarity but then demanded BYTE
# EQUALITY against the field's own deterministic value to exempt it - fuzzy to
# accuse, exact to acquit. So a stamped value differing from its fact by one
# character was blanked AS BOILERPLATE BLEED while being the field's own data.
#
# Reproduced exactly: one trailing period blanked BOTH operations boxes on
# ACORD 125 while the Additional Interest item description survived - the live
# symptom, character for character. It fires hardest on MULTI-DOCUMENT packages,
# where two sources supply near-identical wording.

_GUARD_FACTS = {
    "applicant_name": "Marisol Freight & Cold Storage LLC",
    "operations_description": OPS,
    "property_locations": [{"address_line1": "4820 Harborgate Way",
                            "operations_description": OPS}],
}


def _guarded(stamped):
    from services.pdf_service import _enforce_post_fill_guards
    m = {"BuildingOccupancy_OperationsDescription_A": stamped,
         "CommercialPolicy_OperationsDescription_A": stamped,
         "AdditionalInterest_ItemDescription_A": "Refrigerated trucking and cold storage"}
    _enforce_post_fill_guards(m, _schema(), _GUARD_FACTS, "ACORD_125")
    return m


@pytest.mark.parametrize("label,stamped", [
    ("byte-identical", OPS),
    ("trailing period - THE LIVE CASE", OPS + "."),
    ("display-canonicalised casing", OPS.title()),
    ("whitespace normalised", "  " + OPS.replace(" ", "  ") + " "),
    ("the second document's extra sentence",
     OPS + ". Certificate holder is an additional insured."),
])
def test_a_field_keeps_its_own_value_however_it_was_normalised(label, stamped):
    m = _guarded(stamped)
    assert m["CommercialPolicy_OperationsDescription_A"], label
    assert m["BuildingOccupancy_OperationsDescription_A"], label


def test_real_boilerplate_bleed_is_still_blanked():
    """The guard is not weakened. A field with no deterministic value of its own
    still returns None and is still blanked - the actual bleed case."""
    from services.pdf_service import _enforce_post_fill_guards
    boiler = ("This policy is subject to the terms conditions and exclusions "
              "stated in the form attached hereto")
    m = {"CommercialPolicy_OperationsDescription_A": boiler,
         "NamedInsured_LegalEntity_OtherDescription_A": boiler,
         "AdditionalInterest_ItemDescription_A": boiler}
    _enforce_post_fill_guards(m, _schema(), _GUARD_FACTS, "ACORD_125")
    assert not any(m.values()), "genuine cross-field bleed must still be removed"


def test_ownership_containment_is_directional_and_token_exact():
    """Containment accepts "the field's value PLUS more", never "text that
    merely resembles it" - every significant word of the field's own value has
    to be present."""
    from services.pdf_service import _sim_tokens
    det = _sim_tokens(OPS)
    assert det <= _sim_tokens(OPS + ". Certificate holder is an additional insured.")
    assert not (det <= _sim_tokens("Refrigerated trucking only"))
    assert not (det <= _sim_tokens("Cold storage warehousing"))


# ── 4. THE ACTUAL CAUSE of the blank operations boxes ──────────────────────
#
# Found by running the REAL session's facts through the REAL stamper, after five
# predictions made from the code were all wrong. The guard named itself in the
# log the moment INFO logging was on:
#
#   truncated_copy blanked=CommercialPolicy_OperationsDescription_A
#     value='Refrigerated trucking and cold storage w...'
#     - it is the cut-off head of '...warehousing of food p...', which we hold in full
#
# `_is_truncated_copy_of_a_held_value` blanks a narrative that is a PREFIX of
# another held value. On the two-document package:
#
#   operations_description                = "...warehousing of food products"
#   certificate_description_of_operations = "...warehousing of food products.
#                                            Certificate holder is an additional
#                                            insured with respect to..."
#
# The second is the first PLUS A NEW SENTENCE - a certificate appends its own
# additional-insured wording to the same opening description. Two different
# facts sharing an opening sentence, not one value cut in half.
# `_normalize_for_search` strips punctuation, so the sentence boundary that
# tells them apart was invisible.

def test_a_certificate_narrative_does_not_blank_the_operations_description():
    """THE LIVE CASE, verbatim from the session that shipped both boxes empty."""
    from services.pdf_service import _is_truncated_copy_of_a_held_value as trunc
    cert = (OPS + ". Certificate holder is an additional insured with respect "
                  "to operations at the terminal, as required by written contract.")
    facts = {"operations_description": OPS,
             "certificate_description_of_operations": cert}
    assert trunc("CommercialPolicy_OperationsDescription_A", OPS, {}, facts) is None
    assert trunc("BuildingOccupancy_OperationsDescription_A", OPS, {}, facts) is None


def test_a_genuine_truncation_is_still_blanked():
    """The guard keeps its job: a value cut off mid-word, whose full text is
    held elsewhere, is still removed."""
    from services.pdf_service import _is_truncated_copy_of_a_held_value as trunc
    stump = "Refrigerated trucking and cold sto"
    facts = {"operations_description": OPS}
    assert trunc("CommercialPolicy_OperationsDescription_A", stump, {}, facts) == OPS


@pytest.mark.parametrize("shorter,longer,cut_off", [
    (OPS, OPS + ". Certificate holder is an additional insured.", False),
    ("Refrigerated trucking and cold sto", OPS, True),
    ("Refrigerated trucking and cold storage", OPS, True),
    (OPS + ".", OPS + ". And more text follows here.", False),
    ("We install roofing", "We install roofing! Also gutters and siding.", False),
    ("Do we install roofing", "Do we install roofing? Yes we do all of it.", False),
    ("The applicant operates a refrigerated w",
     "The applicant operates a refrigerated warehouse in Tacoma", True),
    (OPS, OPS, False),
    ("", OPS, False),
    (OPS, "", False),
])
def test_truncation_is_decided_at_the_sentence_boundary(shorter, longer, cut_off):
    """A real truncation stops mid-word or mid-clause; a complete statement
    stops at a sentence boundary. H1-F's rule: a test that is necessary but not
    sufficient needs a structural second condition."""
    from services.pdf_service import _is_cut_off_mid_sentence
    assert _is_cut_off_mid_sentence(shorter, longer) is cut_off


def test_the_new_condition_can_only_ever_REFUSE_to_blank():
    """It narrows the guard, never widens it - so it can cost a truncation
    catch and can never delete a value the old code kept."""
    import inspect
    from services.pdf_service import _is_truncated_copy_of_a_held_value as trunc
    src = inspect.getsource(trunc)
    assert "_is_cut_off_mid_sentence(text, str(other))" in src, (
        "the sentence-boundary test must gate the return, not replace it")
    assert "hay.startswith(needle)" in src, "the prefix test must still be required"
