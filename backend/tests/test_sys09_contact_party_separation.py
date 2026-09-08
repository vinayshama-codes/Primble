"""SYS-09 - separate the CLIENT's contact from the BROKERAGE's contact.

Client P0: *"Separate client contact and brokerage contact when populating
ACORD forms."* Two manifestations, opposite directions, one class:

  (A) The Data Consistency picker offered the BROKERAGE's contact person as a
      candidate for the APPLICANT's `contact_name`, conflicting against the real
      one. Package: a COI issued by the brokerage + the applicant's own
      submission narrative.

  (B) The generated ACORD 125 printed the correct agency NAME above the
      APPLICANT's contact person, phone, email and street address. Package:
      the SYS-07 kit (Northgate / Meridian Coast), live 2026-09-05.

THE TRAP THIS FILE EXISTS TO PIN. The obvious fix for (A) - blind a certificate
to `contact_name` in `fact_comparison._ROLE_BLIND_FACTS` - is a REGRESSION on
its own, and the arithmetic is what proves it:

  * `_DOC_TYPE_PRIORITY` ranks `certificate` 7th and `narrative` 21st, so
    `select_primary_truth` makes the COI the PRIMARY document of that package.
  * `merge_facts` applied role-blinding to `non_primary` only; the primary's
    facts were written with `mf[k] = v`, consulting nothing.
  * The PICKER, however, filters every active document - primary included.

So blinding alone removes the certificate's candidate from the picker (the
conflict row disappears) while its wrong value still wins the merge and still
stamps. The producer loses the one screen the value could have been corrected
on. Both halves ship together or neither does.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline-test")

import services.pdf_service as ps                            # noqa: E402
from services.extraction_service import (                    # noqa: E402
    merge_facts, select_primary_truth,
)
from services.fact_comparison import document_witnesses      # noqa: E402

# ── The client's own package, verbatim from the SYS-09 screenshot ───────────
# The surname on the correct value was redacted to "[LastName]" in the report.
_COI_CONTACT = "Terri Wroblewski"          # the BROKERAGE's own contact person
_APPLICANT_CONTACT = "Erin Whitfield"      # the APPLICANT's own contact person
_BROKERAGE = "CRS Insurance Brokerage"

_CERT = {
    "filename": "CRS COI FIO - Orbin CERT ONLY.pdf",
    "doc_type": "certificate",
    "text": "CERTIFICATE OF LIABILITY INSURANCE",
    "facts": {"contact_name": _COI_CONTACT, "producer_name": _BROKERAGE},
    "flags": {},
}
_NARRATIVE = {
    "filename": "ORBIN CONTRACTING LLC submission narrative-20260530144518.pdf",
    "doc_type": "narrative",
    "text": "SUBMISSION NARRATIVE",
    "facts": {"contact_name": _APPLICANT_CONTACT,
              "applicant_name": "ORBIN CONTRACTING LLC"},
    "flags": {},
}


def _merged(docs):
    facts, _flags = merge_facts(docs, select_primary_truth(docs))
    v = facts.get("contact_name")
    return v.get("value") if isinstance(v, dict) and "value" in v else v


# ── 1. The premise the whole fix rests on ───────────────────────────────────

def test_the_certificate_really_is_the_primary_document():
    """If this ever stops being true the rest of manifestation A changes shape,
    so it is pinned rather than assumed. certificate ranks 7th, narrative 21st."""
    assert select_primary_truth([_CERT, _NARRATIVE])["doc_type"] == "certificate"
    assert select_primary_truth([_NARRATIVE, _CERT])["doc_type"] == "certificate"


def test_a_certificate_cannot_witness_the_applicants_own_contact():
    """Structural, not stylistic: ACORD 25 has exactly three contact fields and
    all three are Producer_ContactPerson_*; its NamedInsured block carries a
    name and a mailing address and nothing else. There is no box on a
    certificate in which an applicant's contact person can be printed."""
    for key in ("contact_name", "contact_phone", "contact_email"):
        assert document_witnesses("certificate", key) is False


def test_the_certificates_own_producer_block_is_still_a_witness():
    """The other half of the ruling. Naming the issuing agency is what a
    certificate is FOR - blinding that would break the ACORD 25 roster."""
    for key in ("producer_name", "producer_address", "producer_contact_name",
                "policy_number", "carrier_name", "effective_date"):
        assert document_witnesses("certificate", key) is True


def test_acord_25_has_no_applicant_contact_field_at_all():
    """The evidence behind the blind entry, re-read from the real schema so a
    future schema change cannot leave the rule standing on a stale premise."""
    path = os.path.join(os.path.dirname(__file__), "..", "forms_schemas",
                        "ACORD_25_schema.json")
    with open(path, encoding="utf-8") as fh:
        schema = json.load(fh)
    names = list(schema.keys()) if isinstance(schema, dict) else \
        [f.get("name") for f in schema]
    contacts = [n for n in names if n and "Contact" in n]
    assert contacts, "ACORD 25 must still have contact fields"
    assert all(n.startswith("Producer_ContactPerson_") for n in contacts), contacts


# ── 2. Manifestation A, through the real merge ──────────────────────────────

def test_the_brokerages_contact_no_longer_overwrites_the_applicants():
    """THE REPORTED CASE. Before: the COI is primary, so its producer-side
    contact person was written over the narrative's correct applicant contact
    with no role check at all."""
    assert _merged([_CERT, _NARRATIVE]) == _APPLICANT_CONTACT


def test_it_holds_whichever_order_the_documents_arrive_in():
    assert _merged([_NARRATIVE, _CERT]) == _APPLICANT_CONTACT


def test_a_blind_primary_is_still_allowed_to_be_the_SOLE_source():
    """THE NARROWING, and the reason this fix cannot lose data. A role-blind
    primary may not OVERWRITE a sighted witness; it is still free to be the only
    one. So the change can only ever swap one document's value for another's -
    never blank a fact that nothing else supplies."""
    assert _merged([_CERT]) == _COI_CONTACT


def test_a_single_document_package_is_untouched():
    """`non_primary` is empty, so the role gate never ran there before and does
    not run now. Stated as its own case because it is the shape most sessions
    actually have."""
    assert _merged([_NARRATIVE]) == _APPLICANT_CONTACT


def test_the_certificates_producer_name_still_survives_the_merge():
    """The fix must not cost the certificate the facts it genuinely carries."""
    facts, _ = merge_facts([_CERT, _NARRATIVE],
                           select_primary_truth([_CERT, _NARRATIVE]))
    got = facts.get("producer_name")
    got = got.get("value") if isinstance(got, dict) and "value" in got else got
    assert got == _BROKERAGE


def test_an_empty_rival_value_does_not_disarm_the_primary():
    """A sighted witness that says nothing is not a witness. The primary must
    still supply the value rather than yielding to a blank."""
    quiet = dict(_NARRATIVE, facts={"contact_name": "",
                                    "applicant_name": "ORBIN CONTRACTING LLC"})
    assert _merged([_CERT, quiet]) == _COI_CONTACT


def test_an_unknown_document_role_still_witnesses_everything():
    """Fail-open is load-bearing: an unrecognised doc_type must contribute
    everything, so this mechanism can only ever REMOVE a value, never invent.

    (Asserted at the door, not through the merge: an unknown type is not in
    `_DOC_TYPE_PRIORITY`, so swapping it in also changes which document becomes
    primary - the first draft of this test moved two variables at once and said
    so incorrectly. The merge-level proof is the test below, which holds the
    primary slot fixed.)"""
    assert document_witnesses("something_new_we_have_not_classified",
                              "contact_name") is True


def test_THE_PROOF_THE_GATE_BITES_a_sighted_primary_still_overwrites():
    """One variable, changed once: the primary document's ROLE.

    A declarations page is the insured's own policy document and is NOT blind to
    `contact_name`, so as primary it still overwrites the narrative - the exact
    unconditional-overwrite path that produced the client's screenshot. Swap
    that same primary for a certificate, which cannot state an applicant's
    contact person, and the correct value survives. The role gate is the entire
    difference, and without it both lines below return the primary's value."""
    dec = {"filename": "dec.pdf", "doc_type": "dec_page", "text": "DECLARATIONS",
           "facts": {"contact_name": "Priya Raghunathan"}, "flags": {}}

    assert select_primary_truth([dec, _NARRATIVE])["doc_type"] == "dec_page"
    assert _merged([dec, _NARRATIVE]) == "Priya Raghunathan"

    assert select_primary_truth([_CERT, _NARRATIVE])["doc_type"] == "certificate"
    assert _merged([_CERT, _NARRATIVE]) == _APPLICANT_CONTACT


# ── 3. Manifestation B - the producer's own boxes on the form ───────────────
#
# Live 2026-09-05: the ACORD 125 producer block printed the right agency name
# over the applicant's contact person and address.

_NORTHGATE = {
    "applicant_name": "Northgate Provisions LLC",
    "producer_name": "Meridian Coast Insurance Brokers LLC",
    "contact_name": "Dana Whitcomb",
    "contact_phone": "(253) 555-0172",
    "contact_email": "dwhitcomb@northgateprovisions.com",
    "mailing_address": "1420 Harborgate Way, Ste 300, Tacoma, WA 98402",
}

_PRODUCER_CONTACT_FIELDS = (
    "Producer_ContactPerson_FullName_A",
    "Producer_ContactPerson_PhoneNumber_A",
    "Producer_ContactPerson_EmailAddress_A",
)
_PRODUCER_MAILING_FIELDS = (
    "Producer_MailingAddress_LineOne_A",
    "Producer_MailingAddress_LineTwo_A",
    "Producer_MailingAddress_CityName_A",
    "Producer_MailingAddress_StateOrProvinceCode_A",
    "Producer_MailingAddress_PostalCode_A",
)


def _reaches_gap_fill(field, facts):
    """Mirrors the routing decision in `map_facts_to_form` - the seam the
    2026-08-09 lesson says a resolver test must go through, not around."""
    result = ps._deterministic_map(field, facts)
    if not (result == "UNMATCHED" or ps._is_empty_llm_value(result)):
        return False
    return not ps._is_authoritative_blank_field(field, facts)


@pytest.mark.parametrize("field", _PRODUCER_CONTACT_FIELDS)
def test_producer_contact_boxes_are_never_asked_of_the_model(field):
    """THE LIVE CASE. This package states no producer contact anywhere, so the
    only contact a field-level gap fill can find is the applicant's own."""
    assert not _reaches_gap_fill(field, _NORTHGATE)


@pytest.mark.parametrize("field", _PRODUCER_MAILING_FIELDS)
def test_producer_address_boxes_are_never_asked_of_the_model(field):
    assert not _reaches_gap_fill(field, _NORTHGATE)


@pytest.mark.parametrize("field", _PRODUCER_CONTACT_FIELDS)
def test_a_real_producer_contact_still_stamps(field):
    """The resolver must step ASIDE on a genuine fact - an owned blank that
    swallows real data is a worse bug than the one being fixed."""
    facts = dict(_NORTHGATE, producer_contact_name="Alan Reyes",
                 producer_contact_phone="(206) 555-0143",
                 producer_contact_email="areyes@meridiancoast.com")
    assert ps._resolve_producer_contact(field, facts) is ps._SCHED_SKIP


def test_one_producer_contact_fact_opens_the_whole_family():
    """Same contract as the applicant mirror: the family is owned only when the
    party has NO contact of its own, not when one component is missing."""
    facts = dict(_NORTHGATE, producer_contact_phone="(206) 555-0143")
    for field in _PRODUCER_CONTACT_FIELDS:
        assert ps._resolve_producer_contact(field, facts) is ps._SCHED_SKIP


def test_a_real_producer_address_still_stamps_its_parse():
    facts = dict(_NORTHGATE,
                 producer_address="88 Ledger Street, Suite 410, Seattle, WA 98101")
    assert ps._deterministic_map(
        "Producer_MailingAddress_CityName_A", facts) == "Seattle"
    assert ps._deterministic_map(
        "Producer_MailingAddress_StateOrProvinceCode_A", facts) == "WA"


def test_the_applicants_own_contact_block_is_unaffected():
    """The mirror resolver must keep working exactly as it did - this fix adds
    a second guard, it does not re-cut the first."""
    assert ps._resolve_applicant_contact(
        "NamedInsured_Contact_FullName_A", _NORTHGATE) is ps._SCHED_SKIP
    assert ps._resolve_applicant_contact(
        "NamedInsured_Contact_FullName_A", {}) is None


def test_the_producer_resolvers_do_not_claim_another_partys_box():
    """A resolver that over-matches would blank boxes it has no business in."""
    for field in ("NamedInsured_Contact_FullName_A",
                  "NamedInsured_MailingAddress_LineOne_A",
                  "AdditionalInterest_Primary_FaxNumber_A",
                  "Producer_AuthorizedRepresentative_FullName_A",
                  "CommercialPolicy_OperationsDescription_A"):
        assert ps._resolve_producer_contact(field, {}) is ps._SCHED_SKIP
        assert ps._resolve_producer_mailing(field, {}) is ps._SCHED_SKIP


def test_the_producer_contact_regex_covers_every_form_that_has_the_family():
    """ACORD 130 adds CellPhoneNumber and 133 carries an EmailAddress on row C -
    a hand-listed field set would have missed both."""
    for field in ("Producer_ContactPerson_CellPhoneNumber_A",   # ACORD 130
                  "Producer_ContactPerson_EmailAddress_C"):     # ACORD 133
        assert ps._resolve_producer_contact(field, {}) is None


# ── 4. Anti-rot: the two directions must stay symmetric ─────────────────────

def test_both_party_contact_guards_are_registered():
    """The whole defect was one direction of a symmetric rule being guarded and
    the other not. If a future edit drops either registration, the resolver
    keeps returning None and an UNREGISTERED None means 'ask the model'."""
    for name in ("_resolve_applicant_contact", "_resolve_producer_contact",
                 "_resolve_producer_mailing"):
        assert name in ps._AUTHORITATIVE_BLANK_RESOLVERS, name
        assert callable(getattr(ps, name, None)), name


def test_the_merge_consults_the_role_gate_on_the_primary_document_too():
    """The seam, asserted structurally. A rule enforced on one branch of the
    merge and not the other is the defect class this codebase keeps paying for -
    and here it was literally the same function, two loops apart."""
    import inspect
    from services import extraction_service as es
    src = inspect.getsource(es.merge_facts)
    head, _, tail = src.partition("Apply primary doc as legacy fallback")
    assert "document_witnesses" in head, "the non-primary gate must still exist"
    assert "_p_witnesses" in tail, (
        "the primary-document loop must consult the role gate as well")
