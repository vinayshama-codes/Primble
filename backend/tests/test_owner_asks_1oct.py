"""The owner's three asks of 1 Oct 2026 (after grading Michelle's 22 points):

1. The producer block: the account's Contact Phone printed as a bare run of
   digits ("7983789751"), and no producer had a mailing address to print -
   Account Settings now holds an AGENCY ADDRESS that prints there.
2. Unanswered Yes / No questions are highlighted while VIEWING a form too
   (pinned in tests/test_viewer_items_10_18_30sep.py).
3. G2 - the landlord: asked as a FOLLOW-UP the moment the client answers that
   the business rents, and for EACH location, not only one premises with Tenant
   confirmed before sending.
"""
import asyncio
import copy
import json
import random
import re
import shutil
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

import services.arq_service as arq
import services.display_canonicalizer as dc
import services.extraction_service as es
import services.follow_ups as fu
import services.pdf_service as ps
import services.premises_interest as pi
from services.answer_options import PREMISES_INTEREST_OPTIONS
from services.arq_receipt_service import build_receipt_payload
from utils.helpers import _parse_address

BACKEND = Path(__file__).resolve().parents[1]
FRONTEND = BACKEND.parent / "frontend" / "src"


def _schema(fid):
    return json.loads((BACKEND / "forms_schemas" / f"{fid}_schema.json").read_text(encoding="utf-8"))


def _src(path):
    return Path(path).read_text(encoding="utf-8")


S125 = _schema("ACORD_125")
TENANT = "Tenant - the business rents its space"
OWNER = "Owner - the business owns the building"


# ══ 1a. Phone numbers: only a bare run of digits is formatted ═════════════════

@pytest.mark.parametrize("raw, want", [
    ("7983789751", "798-378-9751"), ("17983789751", "798-378-9751"),
    (" 3035210561 ", "303-521-0561"),
    ("303-521-0561", "303-521-0561"), ("(303) 521-0561", "(303) 521-0561"),
    ("+91 79837 89751", "+91 79837 89751"), ("303.521.0561", "303.521.0561"),
    ("3035210561 x12", "3035210561 x12"), ("12345", "12345"), ("", ""),
])
def test_only_a_bare_run_of_digits_is_formatted(raw, want):
    assert dc.canonicalize_phone(raw) == want


def test_every_phone_box_on_every_form_and_nothing_else_is_a_phone():
    for path in (BACKEND / "forms_schemas").glob("*_schema.json"):
        for field in json.loads(path.read_text(encoding="utf-8")):
            is_phone = bool(re.search("phonenumber|faxnumber", field, re.I))
            assert (dc.category_for_field(field) == "phone") is is_phone, field


def test_the_account_phone_prints_formatted_on_the_producer_block():
    shown = ps.display_value_for_box("ACORD_125", "Producer_ContactPerson_PhoneNumber_A",
                                     "7983789751", provenance="account")
    assert shown == "798-378-9751"


# ══ 1b. The agency address ═══════════════════════════════════════════════════

def test_the_column_exists_on_a_new_and_an_old_database():
    src = _src(BACKEND / "config" / "database.py")
    create = src[src.index("CREATE TABLE IF NOT EXISTS users"):src.index("for col, definition in [")]
    assert re.search(r"\n\s+agency_address\s+TEXT,", create)
    assert '("agency_address",               "TEXT")' in src       # the ALTER loop


class _FakeConn:
    def __init__(self, log):
        self.log = log

    async def execute(self, sql, *args):
        self.log.append((sql, args))


class _FakePool:
    def __init__(self, log):
        self.log = log

    def acquire(self):
        log = self.log

        class _Ctx:
            async def __aenter__(self_inner):
                return _FakeConn(log)

            async def __aexit__(self_inner, *exc):
                return False
        return _Ctx()


@pytest.mark.parametrize("typed, stored", [
    ("  1450 Larimer St,  Suite 210, Denver, CO 80202 ", "1450 Larimer St, Suite 210, Denver, CO 80202"),
    ("B-12 Sector 62, Noida, UP 201301", "B-12 Sector 62, Noida, UP 201301"),
    ("", ""),                                                     # clears it
])
def test_the_profile_stores_a_clean_address(typed, stored):
    from fastapi import HTTPException  # noqa: F401
    from models.schemas import UpdateProfileRequest
    import routes.auth_routes as ar
    log: list = []
    with patch.object(ar, "get_pool", lambda: _FakePool(log)):
        out = asyncio.run(ar.update_profile(UpdateProfileRequest(agency_address=typed),
                                            current_user={"id": "u1"}))
    assert out == {"success": True, "agency_address": stored}
    assert log[0][0] == "UPDATE users SET agency_address=$1 WHERE id=$2"
    assert log[0][1] == (stored, "u1")


@pytest.mark.parametrize("typed", ["<script>alert(1)</script>", "12345 67890", "{x}"])
def test_the_profile_refuses_what_is_not_an_address(typed):
    from fastapi import HTTPException
    from models.schemas import UpdateProfileRequest
    import routes.auth_routes as ar
    with patch.object(ar, "get_pool", lambda: _FakePool([])):
        with pytest.raises(HTTPException) as e:
            asyncio.run(ar.update_profile(UpdateProfileRequest(agency_address=typed),
                                          current_user={"id": "u1"}))
    assert e.value.status_code == 400


def test_the_settings_screen_and_me_carry_it():
    me = _src(BACKEND / "routes" / "auth_routes.py")
    assert '"agency_address": current_user.get("agency_address", "") or "",' in me
    modal = _src(FRONTEND / "components" / "account" / "AccountSettingsModal.jsx")
    assert "Agency Address" in modal and "agency_address: agencyAddress.trim() || null," in modal
    assert "Printed as the producer mailing address on your ACORD forms." in modal


def test_the_account_profile_carries_the_address(monkeypatch):
    import repositories.user_repository as ur
    from services import extraction_pipeline as ep

    async def _user(uid):
        return {"organization_name": "Astrea It services", "full_name": "Vinay Sharma",
                "email": "v@x.com", "phone": "7983789751",
                "agency_address": " 1450 Larimer St, Denver, CO 80202 "}
    monkeypatch.setattr(ur, "get_user_by_id", _user)
    prof = asyncio.run(ep._submitting_account_for("u1"))
    assert prof["address"] == "1450 Larimer St, Denver, CO 80202"


_CRS = "COMMERCIAL RISK SOLUTIONS, INC."
_ACCOUNT = {"organization_name": "Astrea It services", "full_name": "Vinay Sharma",
            "email": "v@x.com", "phone": "7983789751", "address": "1450 Larimer St, Denver, CO 80202"}


def _v(x):
    return x.get("value") if isinstance(x, dict) else x


def test_the_login_s_address_fills_the_producer_block_when_no_document_names_an_agency():
    mf = {"applicant_name": "ORBIN CONTRACTING LLC"}
    es._route_producer_identity(mf, [{"doc_type": "dec_page", "facts": {}, "flags": {}}], account=_ACCOUNT)
    assert _v(mf["producer_address"]) == _ACCOUNT["address"]


def test_the_login_s_address_goes_with_the_login_when_the_dec_names_another_agency():
    dec = {"doc_type": "dec_page", "text": "", "flags": {},
           "facts": {"producer_name": _CRS, "producer_address": "999 Other Rd, Aurora, CO 80011"}}
    mf = {"producer_name": _CRS, "producer_address": "999 Other Rd, Aurora, CO 80011"}
    es._route_producer_identity(mf, [dec], account=_ACCOUNT)
    assert "Astrea" in str(_v(mf["producer_name"]))
    assert _v(mf["producer_address"]) == _ACCOUNT["address"]
    assert "999 Other Rd" in str(_v(mf.get("expiring_producer_address")))


@pytest.mark.parametrize("address, parts", [
    ("1450 Larimer St, Suite 210, Denver, CO 80202",
     {"LineOne": "1450 Larimer St", "LineTwo": "Suite 210", "CityName": "Denver",
      "StateOrProvinceCode": "CO", "PostalCode": "80202"}),
    ("1450 Larimer St Suite 210 Denver CO 80202-1234",
     {"LineOne": "1450 Larimer St", "LineTwo": "Suite 210", "CityName": "Denver",
      "StateOrProvinceCode": "CO", "PostalCode": "80202-1234"}),
    ("B-12 Sector 62, Noida, UP 201301",
     {"LineOne": "B-12 Sector 62", "CityName": "Noida", "StateOrProvinceCode": "UP",
      "PostalCode": "201301"}),
])
def test_the_address_prints_in_its_boxes(address, parts):
    facts = {"producer_name": es._account_producer_envelope("Astrea It services"),
             "producer_address": es._account_producer_envelope(address),
             "producer_contact_phone": es._account_producer_envelope("7983789751"),
             "applicant_name": {"value": "Orbin Contracting LLC"}}
    mapped, _ = ps.map_facts_to_form(copy.deepcopy(facts), S125, form_id="ACORD_125", raw_text="x",
                                     pre_filled_gpt={"filled_values": {}, "raw_text_fields": set(),
                                                     "question_grounding": {}})
    for part, want in parts.items():
        assert mapped[f"Producer_MailingAddress_{part}_A"] == want, part
    assert mapped["Producer_ContactPerson_PhoneNumber_A"] == "798-378-9751"


# ══ 1c. A ZIP corrects a US state only: an Indian PIN printed "DC" ═══════════

@pytest.mark.parametrize("address, state", [
    ("B-12 Sector 62, Noida, UP 201301", "UP"),            # a PIN is not a ZIP
    ("4800 Dahlia St # D13, Denver, MO 80216-3121", "CO"),  # the US correction still works
    ("1450 Larimer St, Denver, CO 80202", "CO"),
    ("10 Rue X, Paris, FR 75001", "FR"),                     # not a US state: left alone
])
def test_the_zip_corrects_only_a_us_state(address, state):
    assert _parse_address(address).get("state") == state


# ══ 3. G2 - follow-ups ═══════════════════════════════════════════════════════

def test_a_follow_up_is_shown_only_on_its_values():
    q = {"field_name": "landlord_name", "show_if": fu.show_if("premises_interest", [TENANT])}
    assert fu.follow_up_shown(q, {"premises_interest": TENANT})
    assert fu.follow_up_shown(q, {"premises_interest": {"value": f"  {TENANT} "}})
    for other in (OWNER, "Other: licensee", "", None, "tenant"):
        assert not fu.follow_up_shown(q, {"premises_interest": other})
    assert not fu.follow_up_shown(q, {})
    assert fu.follow_up_shown({"field_name": "x"}, {})                # no condition
    assert not fu.follow_up_shown({"show_if": "garbage"}, {})


@pytest.mark.parametrize("raw, ok", [
    ({"field": "premises_interest", "any_of": [TENANT]}, True),
    ({"field": "", "any_of": [TENANT]}, False), ({"field": "p", "any_of": []}, False),
    ({"field": "p", "any_of": "Tenant"}, False), ("x", False), (None, False),
    ({"field": "p" * 500, "any_of": ["v" * 500] * 40}, True),
])
def test_a_request_borne_condition_is_bounded(raw, ok):
    got = fu.sanitize_show_if(raw)
    assert (got is not None) is ok
    if got:
        assert len(got["field"]) <= 128 and len(got["any_of"]) <= 12
        assert all(len(v) <= 200 for v in got["any_of"])


@pytest.mark.parametrize("seed", range(30))
def test_follow_ups_always_land_right_after_their_parent(seed):
    rng = random.Random(seed)
    qs = [{"field_name": f"q{i}"} for i in range(6)]
    kids = []
    for parent in rng.sample(qs, 3):
        for j in range(rng.randint(1, 2)):
            kids.append({"field_name": f"{parent['field_name']}_k{j}",
                         "show_if": fu.show_if(parent["field_name"], [TENANT])})
    orphan = {"field_name": "orphan", "show_if": fu.show_if("gone", [TENANT])}
    mixed = qs + kids + [orphan]
    rng.shuffle(mixed)
    out = fu.ordered_follow_ups(fu.without_orphans(mixed))
    names = [q["field_name"] for q in out]
    assert "orphan" not in names and len(out) == len(qs) + len(kids)
    for k in kids:
        parent = k["show_if"]["field"]
        i, j = names.index(parent), names.index(k["field_name"])
        assert j > i and all(n.startswith(parent) for n in names[i:j + 1])


def _facts(rows, **extra):
    return {"property_locations": {"value": rows, "source": "ai"}, **extra}


def _row(n, line1, **kw):
    return {"location_number": str(n), "address_line1": line1, "address_city": "Denver",
            "address_state": "CO", "address_zip": "80202", **kw}


def _premises_qs(facts, forms=("ACORD_125",)):
    qs: list = []
    arq._maybe_inject_premises_questions(qs, facts, {}, list(forms), {})
    return {q["field_name"]: q for q in qs}


def test_one_location_asks_the_landlord_as_follow_ups_of_the_interest():
    qs = _premises_qs(_facts([_row(1, "1 Main St")]))
    assert list(qs) == ["premises_interest", "landlord_name", "landlord_address"]
    assert qs["premises_interest"]["options"] == list(PREMISES_INTEREST_OPTIONS)
    for f in ("landlord_name", "landlord_address"):
        assert qs[f]["show_if"] == {"field": "premises_interest", "any_of": [TENANT]}


def test_one_location_already_rented_or_owned():
    rented = _premises_qs(_facts([_row(1, "1 Main St", is_tenant=True)]))
    assert list(rented) == ["landlord_name", "landlord_address"]
    assert not any(q.get("show_if") for q in rented.values())
    assert _premises_qs(_facts([_row(1, "1 Main St", is_owner=True)])) == {}
    told = _facts([_row(1, "1 Main St", is_tenant=True)],
                  landlord_name={"value": "Main Street Properties LLC", "source": "client_arq"},
                  landlord_address={"value": "100 Main St, Austin, TX 78701", "source": "client_arq"})
    assert _premises_qs(told) == {}
    assert _premises_qs(_facts([_row(1, "1 Main St")]), forms=("ACORD_126",)) == {}
    assert _premises_qs(_facts([])) == {}


def test_each_location_is_asked_by_its_own_address():
    facts = _facts([_row(1, "1 Main St"), _row(2, "2 Oak Ave", is_tenant=True),
                    _row(3, "3 Elm Rd", is_owner=True),
                    _row(4, "4 Pine Ct", is_tenant=True, landlord_name="Pine Holdings LLC",
                         landlord_address="9 Pine Ct, Denver, CO 80202")])
    qs = _premises_qs(facts)
    assert list(qs) == ["premises_interest@loc1", "landlord_name@loc1", "landlord_address@loc1",
                        "landlord_name@loc2", "landlord_address@loc2"]
    assert "1 Main St" in qs["premises_interest@loc1"]["question"]
    assert qs["landlord_name@loc1"]["show_if"]["field"] == "premises_interest@loc1"
    assert "2 Oak Ave" in qs["landlord_name@loc2"]["question"] and "show_if" not in qs["landlord_name@loc2"]
    assert all(q["_is_curated_client"] for q in qs.values())


def test_hidden_follow_ups_are_not_on_the_receipt():
    questions = [{"field_name": "premises_interest", "question": "Own or rent?"},
                 {"field_name": "landlord_name", "question": "Landlord?",
                  "show_if": fu.show_if("premises_interest", [TENANT])}]
    owned = build_receipt_payload({"questions": questions, "answers": {"premises_interest": OWNER}})
    assert [i["field_name"] for i in owned["items"]] == ["premises_interest"]
    rented = build_receipt_payload({"questions": questions,
                                    "answers": {"premises_interest": TENANT, "landlord_name": "Main LLC"}})
    assert [i["kind"] for i in rented["items"]] == ["answer", "answer"]
    counts = arq.response_counts(questions, owned["items"])
    assert counts["questions_asked"] == 1 and counts["questions_answered"] == 1


def _two_location_session():
    rows = [_row(1, "1 Main St"), _row(2, "2 Oak Ave")]
    return {
        "generated_forms": {"ACORD_125": {
            "schema": S125,
            "field_state": {"CommercialStructure_Location_PhysicalAddress_LineOne_A": "1 Main St",
                            "CommercialStructure_Location_PhysicalAddress_LineOne_B": "2 Oak Ave"},
            "confidence": {"CommercialStructure_Location_PhysicalAddress_LineOne_A": "filled",
                           "CommercialStructure_Location_PhysicalAddress_LineOne_B": "filled"},
        }},
        "facts": _facts(rows), "flags": {},
    }


def _apply(session, answers, questions):
    arq_row = {"id": "arq-1", "status": "submitted", "session_id": "s1",
               "answers": answers, "questions": questions}
    saved: dict = {}

    async def _upd(_sid, payload, delete_facts=None):
        saved.update(payload)

    with patch.object(arq, "get_arq_by_id", AsyncMock(return_value=arq_row)), \
         patch("repositories.session_repository.get_processing_session", AsyncMock(return_value=session)), \
         patch("repositories.session_repository.upd_processing_session", _upd):
        ok, _upd_list = asyncio.run(arq.apply_arq_answers_to_session("arq-1", "s1"))
    assert ok
    return saved


def test_per_location_answers_land_on_their_rows_and_boxes():
    session = _two_location_session()
    questions = []
    arq._maybe_inject_premises_questions(questions, session["facts"], {}, ["ACORD_125"], {})
    answers = {"premises_interest@loc1": OWNER,
               "landlord_name@loc1": "Should Not Land LLC",          # hidden: loc1 is owned
               "premises_interest@loc2": TENANT,
               "landlord_name@loc2": "Oak Holdings LLC",
               "landlord_address@loc2": "77 Oak Ave, Denver, CO 80202"}
    saved = _apply(session, answers, questions)
    rows = pi.premises_rows(saved["facts"])
    assert rows[0]["is_owner"] is True and not rows[0].get("landlord_name")
    assert rows[1]["is_tenant"] is True and rows[1]["landlord_name"] == "Oak Holdings LLC"
    form = saved["generated_forms"]["ACORD_125"]
    state, conf = form["field_state"], form["confidence"]
    assert str(state["CommercialStructure_InsuredInterest_OwnerIndicator_A"]).strip()
    assert str(state["CommercialStructure_InsuredInterest_TenantIndicator_B"]).strip()
    assert conf["CommercialStructure_InsuredInterest_TenantIndicator_B"] == "client_arq"
    # the documents' address stays the documents' - never relabelled as the client's
    assert conf["CommercialStructure_Location_PhysicalAddress_LineOne_B"] == "filled"
    # the one rented location's landlord prints on the 125's interest row, with its LOC #
    assert state["AdditionalInterest_FullName_A"] == "Oak Holdings LLC"
    assert state["AdditionalInterest_Item_LocationProducerIdentifier_A"] == "2"


def test_two_landlords_are_recorded_and_none_is_squeezed_into_the_one_row():
    facts = _facts([_row(1, "1 Main St", is_tenant=True, landlord_name="Main LLC"),
                    _row(2, "2 Oak Ave", is_tenant=True, landlord_name="Oak LLC")])
    assert len(pi.located_landlords(facts)) == 2
    assert ps.landlord_interest_row({**facts, "_form_id": "ACORD_125"}) is None
    one = _facts([_row(1, "1 Main St", is_tenant=True, landlord_name="Main LLC"),
                  _row(2, "2 Oak Ave", is_owner=True)])
    got = ps.landlord_interest_row({**one, "_form_id": "ACORD_125"})
    assert got["name"] == "Main LLC" and got["location"] == "1"


def test_a_single_premises_landlord_after_owner_is_not_applied():
    session = {"generated_forms": {"ACORD_125": {"schema": S125, "field_state": {}, "confidence": {}}},
               "facts": _facts([_row(1, "1 Main St")]), "flags": {}}
    questions = []
    arq._maybe_inject_premises_questions(questions, session["facts"], {}, ["ACORD_125"], {})
    saved = _apply(session, {"premises_interest": OWNER, "landlord_name": "Not Theirs LLC"}, questions)
    assert not saved["facts"].get("landlord_name")


def test_the_send_and_client_view_carry_the_condition():
    src = _src(BACKEND / "routes" / "arq_routes.py")
    assert src.count("_cond = sanitize_show_if(q.get(SHOW_IF_KEY))") == 2
    assert "clean_questions = ordered_follow_ups(without_orphans(clean_questions))" in src


def test_the_client_page_uses_one_visible_list():
    page = _src(FRONTEND / "components" / "arq" / "ClientQuestionnaire.jsx")
    assert "const visibleQuestions = useMemo(() => shownQuestions(questions, answers), [questions, answers]);" in page
    assert "progressCounts(visibleQuestions," in page and "visibleQuestions.map((q) => {" in page
    # (Orbin item 14, 1 Oct night - the TEST changed: the signature question's
    # "signed" marker is added to the shown answers; hidden answers still drop)
    assert "answers: { ...answersForShown(questions, answers), ...signed }" in page
    assert not re.search(r"\bquestions\.(map|forEach|filter)\(", page)
    modal = _src(FRONTEND / "components" / "form" / "AcordModal.jsx")
    assert "(allQuestions || []).filter(q => !q.follow_up_of)" in modal
    assert "? !!selectedQuestions[q.follow_up_of] : !!selectedQuestions[q.field_name]" in modal


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_page_and_the_server_agree_on_what_was_shown(tmp_path):
    cases = [
        [{"show_if": {"field": "p", "any_of": [TENANT]}}, {"p": TENANT}],
        [{"show_if": {"field": "p", "any_of": [TENANT]}}, {"p": f" {TENANT} "}],
        [{"show_if": {"field": "p", "any_of": [TENANT]}}, {"p": OWNER}],
        [{"show_if": {"field": "p", "any_of": [TENANT]}}, {}],
        [{"field_name": "x"}, {}],
        [{"show_if": {"field": "p", "any_of": ["A", "B"]}}, {"p": "B"}],
    ]
    script = tmp_path / "check.mjs"
    script.write_text(
        f"import * as F from {json.dumps((FRONTEND / 'utils' / 'followUps.js').as_uri())};\n"
        f"const cases = {json.dumps(cases)};\n"
        "console.log(JSON.stringify(cases.map(([q, a]) => F.followUpShown(q, a))));\n", encoding="utf-8")
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout) == [fu.follow_up_shown(q, a) for q, a in cases]


def test_a_formatted_phone_is_not_a_mismatch_in_the_download_review():
    """Owner's download review, 1 Oct night: "shows 798-378-9751 but the source
    value is 7983789751" - the display formatter's own output read as a
    mismatch. A phone / fax compares by its digits; a different number still
    fails, and nothing else changes."""
    from services.field_qa import _value_matches as m
    assert m("producer_phone", "798-378-9751", "7983789751")
    assert m("contact_phone", "(303) 555-0100", "1-303-555-0100")
    assert m("producer_fax", "303.555.0100", "3035550100")
    assert not m("producer_phone", "798-378-9752", "7983789751")
    assert not m("applicant_name", "Orbin Contracting LLC", "Royal Builders LLC")
    assert not m("phone_type", "Mobile", "Office")              # a word, not a number


def test_the_landlord_follows_an_interest_question_another_generator_already_added():
    """Owner's live run, 1 Oct night (session 55325284): the list already held
    "own or rent?" from another generator, so the landlord follow-ups were
    skipped and picking Tenant showed nothing. They now attach to the question
    whoever added it - once, never a second interest question."""
    existing = {"field_name": "premises_interest", "question": "own or rent?", "_canonical_key": "premises_interest"}
    qs = [dict(existing)]
    arq._maybe_inject_premises_questions(qs, _facts([_row(1, "1 Main St")]), {}, ["ACORD_125"], {})
    names = [q["field_name"] for q in qs]
    assert names.count("premises_interest") == 1
    assert names[1:] == ["landlord_name", "landlord_address"]
    for q in qs[1:]:
        assert q["show_if"] == {"field": "premises_interest", "any_of": [TENANT]}
    # two locations: the same for a per-location question already present
    loc2 = {"field_name": "premises_interest@loc2", "_canonical_key": "premises_interest@loc2"}
    qs2 = [dict(loc2)]
    arq._maybe_inject_premises_questions(qs2, _facts([_row(1, "1 Main St", is_owner=True), _row(2, "2 Oak Ave")]),
                                         {}, ["ACORD_125"], {})
    by = {q["field_name"]: q for q in qs2}
    assert [q["field_name"] for q in qs2].count("premises_interest@loc2") == 1
    assert by["landlord_name@loc2"]["show_if"]["field"] == "premises_interest@loc2"
    # never without ACORD 125, and never when the interest is already known
    assert _premises_qs(_facts([_row(1, "1 Main St")]), forms=("ACORD_126",)) == {}
