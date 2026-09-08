"""SYS-09 acceptance criterion, both directions.

    "Client contact values should not overwrite producer/brokerage contact
     values, and vice versa."

The "and vice versa" was the half that was missing. `_resolve_producer_contact`
already refused a producer contact that is an exact copy of the applicant's -
the fabrication case, where a submission states no producer contact and gap fill
reaches for the only contact it can see. Its mirror did not exist, so when
EXTRACTION collapses the two - the ORIGINAL SYS-09 failure - the broker's own
name, phone and email printed in the APPLICANT's contact block and nothing
objected.

WHY BOTH RULES NEED A TIEBREAK. Each refuses a value that is an exact copy of
the other party's. When the two facts are identical, "the other one is the copy"
is true from BOTH sides - so switching the mirror on without one blanked both
blocks and deleted a real contact (measured, not theorised).

`_contact_email_party` settles it structurally: the email's own domain against
each organisation's name. It is deliberately silent when the domain matches both
or neither, and both callers then keep their prior behaviour rather than guess.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline-test")

import services.pdf_service as ps                                # noqa: E402

APPLICANT = "Orbin Contracting LLC"
PRODUCER = "Coastwater Insurance Brokers LLC"
CLIENT = ("Erin Royal", "(206) 555-0188", "eroyal@orbin.com")
BROKER = ("Delphine Ostrander", "(206) 555-0143", "dostrander@coastwaterins.com")

PROD_NAME = "Producer_ContactPerson_FullName_A"
APP_NAME = "NamedInsured_Contact_FullName_A"
PROD_MAIL = "Producer_ContactPerson_EmailAddress_A"
APP_MAIL = "NamedInsured_Contact_PrimaryEmailAddress_A"


def _facts(client=CLIENT, broker=BROKER):
    f = {"applicant_name": APPLICANT, "producer_name": PRODUCER}
    if client:
        f.update(zip(("contact_name", "contact_phone", "contact_email"), client))
    if broker:
        f.update(zip(("producer_contact_name", "producer_contact_phone",
                      "producer_contact_email"), broker))
    return f


def _schema(form):
    path = os.path.join(os.path.dirname(__file__), "..", "forms_schemas",
                        f"{form}_schema.json")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _blocks(facts, form="ACORD_125"):
    res = ps.map_facts_to_form(dict(facts), _schema(form), form, "")
    mapped = res[0] if isinstance(res, tuple) else res
    return mapped


# ── The five role shapes ─────────────────────────────────────────────────────

def test_both_contacts_present_stay_in_their_own_blocks():
    m = _blocks(_facts())
    assert m[PROD_NAME] == "Delphine Ostrander"
    assert m[APP_NAME] == "Erin Royal"
    assert m[PROD_MAIL] == "dostrander@coastwaterins.com"
    assert m[APP_MAIL] == "eroyal@orbin.com"


def test_extraction_collapsed_onto_the_BROKER():
    """THE ORIGINAL SYS-09 FAILURE. Both contact facts carry the broker. The
    broker keeps his own block; the CLIENT block ships blank rather than
    telling the carrier that the brokerage employee is the insured's contact."""
    m = _blocks(_facts(client=BROKER))
    assert m[PROD_NAME] == "Delphine Ostrander"
    assert m[APP_NAME] is None
    assert m[APP_MAIL] is None


def test_a_producer_contact_fabricated_from_the_CLIENT():
    """The direction already guarded, and it must not regress: the applicant's
    contact is corroborated across the submission, so the CLIENT keeps it."""
    m = _blocks(_facts(broker=CLIENT))
    assert m[APP_NAME] == "Erin Royal"
    assert m[PROD_NAME] is None


def test_only_a_client_contact_never_fills_the_producer_block():
    m = _blocks(_facts(broker=None))
    assert m[APP_NAME] == "Erin Royal"
    assert m[PROD_NAME] is None


def test_only_a_producer_contact_never_fills_the_applicant_block():
    m = _blocks(_facts(client=None))
    assert m[PROD_NAME] == "Delphine Ostrander"
    assert m[APP_NAME] is None


def test_the_certificate_carries_only_the_producer_context():
    """ACORD 25 has no applicant-contact block; its CONTACT box is the
    producer's. "Populate each form according to the ACORD field context.\""""
    m = _blocks(_facts(), "ACORD_25")
    assert m[PROD_NAME] == "Delphine Ostrander"
    assert not [k for k, v in m.items()
                if k.startswith("NamedInsured_Contact") and v]


# ── The tiebreak itself ──────────────────────────────────────────────────────

@pytest.mark.parametrize("email,expected", [
    ("eroyal@orbin.com", "applicant"),
    ("dostrander@coastwaterins.com", "producer"),
    ("erin.royal@gmail.com", None),          # neither - no opinion
    ("x@orbin-coastwater.com", None),        # both - no opinion
    ("not-an-email", None),
    ("", None), (None, None), (7, None), ([], None),
])
def test_the_domain_tiebreak(email, expected):
    facts = dict(_facts(), contact_email=email)
    assert ps._contact_email_party(facts) is expected or \
        ps._contact_email_party(facts) == expected


def test_a_silent_tiebreak_changes_nothing():
    """When the domain names neither party the rule abstains, and BOTH blocks
    behave exactly as they did before it existed - never worse."""
    m = _blocks(dict(_facts(client=BROKER), contact_email="someone@gmail.com"))
    assert m[PROD_NAME] == "Delphine Ostrander"


@pytest.mark.parametrize("facts", [None, [], "x", 7, {}])
def test_degenerate_containers_do_not_crash(facts):
    assert ps._contact_email_party(facts) is None


@pytest.mark.parametrize("name", [None, "", 7, [], {}, b"x", True,
                                  "LLC Inc Company The And Of"])
def test_org_tokens_never_raise_and_ignore_bare_suffixes(name):
    assert isinstance(ps._org_tokens_for_domain(name), set)


def test_a_suffix_only_name_cannot_match_every_domain():
    """"Insurance", "Agency", "LLC" are in every third company name; matching on
    them would make the tiebreak fire on unrelated domains."""
    facts = {"applicant_name": "The Company LLC",
             "producer_name": "Insurance Agency Services Inc",
             "contact_email": "someone@insurance-company-llc.com"}
    assert ps._contact_email_party(facts) is None
