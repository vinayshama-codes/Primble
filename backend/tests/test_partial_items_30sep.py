"""Orbin 22 Sep feedback - the "done in part" items, finished (30 Sep 2026, night).

Owner's decisions, 30 Sep:
  * Item 7 - a renewal of a programme SEVERAL companies write prints every one of
    them on ACORD 125's CARRIER ("Both names"). ACORD's own tooltip: "the
    insurer's full legal company name(s) ... not the insurer's group name".
  * G2 - a tenant's landlord prints on ACORD 125's additional-interest row A:
    Other = "Landlord", CERTIFICATE REQUIRED, the premises' LOC #.
  * Items 8 / 11 - a ticked line with a blank premium is listed (the prompt).
  * Found on the way - a box the producer types over is the producer's.

Every test drives the real code with the client's own values (session 8739a72a).
"""
from __future__ import annotations

import asyncio
import copy
import inspect
import json
import os
from unittest.mock import patch

import repositories.session_repository as sr
import routes.form_routes as fr
import services.arq_service as arq
import services.extraction_service as es
import services.needs_attention as na
import services.pdf_service as ps
import services.sqs_service as sqs

HERE = os.path.dirname(os.path.abspath(__file__))


def _schema(fid):
    with open(os.path.join(HERE, "..", "forms_schemas", f"{fid}_schema.json"), encoding="utf-8") as fh:
        return json.load(fh)


S125 = _schema("ACORD_125")


def _person(v, source="producer"):
    return {"value": v, "source": source, "confidence": "filled"}


def _stamp(facts, fid="ACORD_125"):
    out = ps.map_facts_to_form(copy.deepcopy(facts), _schema(fid), fid, raw_text="",
                               pre_filled_gpt={"filled_values": {}})
    mapped, conf = out if isinstance(out, tuple) else (out, {})
    return dict(mapped), dict(conf or {})


# ══ Item 7 - CARRIER names every company writing the renewed programme ══════

# The client's own coverage rows (session 8739a72a), trimmed to their shapes:
# two companies, one printed in capitals AND in ordinary case.
_ORBIN_ROWS = [
    {"line": "Property", "carrier": "EMPLOYERS MUTUAL CASUALTY COMPANY",
     "policy_number": None, "premium": None},
    {"line": "Liability", "carrier": "EMC Property & Casualty Company",
     "policy_number": "BBC7263 - 26", "premium": "$3,954.00"},
    {"line": "Inland Marine", "carrier": "EMPLOYERS MUTUAL CASUALTY COMPANY",
     "policy_number": "6C7-40-02---26", "premium": "$300.00"},
    {"line": "Automobile", "carrier": "EMPLOYERS MUTUAL CASUALTY COMPANY",
     "policy_number": "6E7-40-02---26", "premium": "$2,991.00"},
    {"line": "Umbrella", "carrier": "EMPLOYERS MUTUAL CASUALTY COMPANY",
     "policy_number": "6J7-40-02---26", "premium": "$3,418.00"},
    {"line": "Commercial Liability Umbrella", "carrier": "Employers Mutual Casualty Company",
     "policy_number": "6J7-40-02---26", "premium": None},
]
_DEC_DOCS = [{"doc_type": "dec_page", "facts": {}}]
_BOTH = "EMC Property & Casualty Company; Employers Mutual Casualty Company"


def _renewal_facts(**over):
    mf = {
        "coverage_lines": copy.deepcopy(_ORBIN_ROWS),
        "carrier_name": {"value": "EMPLOYERS MUTUAL CASUALTY COMPANY", "source": "ai"},
        "effective_date": {"value": "07/15/2026", "source": "derived"},
        "applicant_name": {"value": "ORBIN CONTRACTING LLC", "source": "ai"},
    }
    mf.update(over)
    es._mark_page_one_current_policy(mf, _DEC_DOCS)
    return mf


def test_writer_names_keep_order_and_prefer_the_ordinary_printing():
    assert es.current_policy_writer_names(_ORBIN_ROWS) == [
        "EMC Property & Casualty Company", "Employers Mutual Casualty Company"]
    # a company printed only in capitals keeps its printing; a row that writes
    # nothing (no number, no premium) names no writer
    rows = [{"carrier": "ACME CASUALTY CO", "policy_number": "A-1"},
            {"carrier": "Beta Insurance Company", "policy_number": None, "premium": None}]
    assert es.current_policy_writer_names(rows) == ["ACME CASUALTY CO"]
    assert es.current_policy_writer_names(None) == [] and es.current_policy_writer_names([]) == []


def test_a_multi_company_renewal_prints_every_writing_company():
    mf = _renewal_facts()
    assert mf.get("renews_current_programme") is True and mf.get("carrier_is_current_policy") is True
    mapped, _ = _stamp(mf)
    assert mapped.get("Insurer_FullName_A") == _BOTH
    # one NAIC box, two companies; several policies, one POLICY NUMBER box
    assert not mapped.get("Insurer_NAICCode_A")
    assert not mapped.get("Policy_PolicyNumberIdentifier_A")
    # the owner the review compares against says the same
    assert ps.authoritative_expected_value("ACORD_125", "Insurer_FullName_A", mf, S125) == _BOTH
    # ...so the "carrier receiving this submission" card no longer fires
    assert sqs._page_one_carrier_printed(mf, None) is True
    assert sqs._page_one_carrier_printed(mf, {"Insurer_FullName_A": _BOTH}) is True


def test_the_insurer_guard_attests_each_listed_company():
    mf = _renewal_facts()
    ok = {"Insurer_FullName_A": _BOTH}
    ps._enforce_post_fill_guards(ok, S125, {**mf, "_form_id": "ACORD_125"})
    assert ok["Insurer_FullName_A"] == _BOTH
    # one company the package never names still blanks the whole box
    bad = {"Insurer_FullName_A": "EMC Property & Casualty Company; Made Up Insurance Company"}
    ps._enforce_post_fill_guards(bad, S125, {**mf, "_form_id": "ACORD_125"})
    assert not bad["Insurer_FullName_A"]
    bad = {"Insurer_FullName_A": "Made Up Insurance Company"}
    ps._enforce_post_fill_guards(bad, S125, {**mf, "_form_id": "ACORD_125"})
    assert not bad["Insurer_FullName_A"]
    # only ACORD 125's page-one CARRIER takes a list: an ACORD 25 insurer row
    # holding two companies is still refused
    roster = {"Insurer_FullName_B": _BOTH}
    ps._enforce_post_fill_guards(roster, _schema("ACORD_25"), {**mf, "_form_id": "ACORD_25"})
    assert not roster["Insurer_FullName_B"]


def test_a_named_addressee_still_outranks_the_joined_names():
    mf = _renewal_facts(submission_carrier_name=_person("EMC Property & Casualty Company"))
    mapped, _ = _stamp(mf)
    assert mapped.get("Insurer_FullName_A") == "EMC Property & Casualty Company"


def test_a_package_that_is_not_a_renewal_keeps_the_old_blank():
    # a quote in the package: not the programme's own paperwork, so no presumption
    mf = {"coverage_lines": copy.deepcopy(_ORBIN_ROWS),
          "carrier_name": {"value": "EMPLOYERS MUTUAL CASUALTY COMPANY", "source": "ai"},
          "effective_date": {"value": "07/15/2026", "source": "derived"}}
    es._mark_page_one_current_policy(mf, _DEC_DOCS + [{"doc_type": "quote", "facts": {}}])
    assert mf.get("renews_current_programme") is not True
    mapped, _ = _stamp(mf)
    assert not mapped.get("Insurer_FullName_A")


def test_one_writing_company_is_unchanged():
    rows = [r for r in copy.deepcopy(_ORBIN_ROWS) if "EMC Property" not in r["carrier"]]
    mf = _renewal_facts(coverage_lines=rows)
    assert mf.get("carrier_is_current_policy") is not True
    mapped, _ = _stamp(mf)
    assert mapped.get("Insurer_FullName_A") == "EMPLOYERS MUTUAL CASUALTY COMPANY"


def test_a_carrier_named_after_generation_moves_question_4_with_it():
    mf = _renewal_facts()
    mapped, conf = _stamp(mf)
    gen = {"ACORD_125": {"schema": S125, "field_state": dict(mapped),
                         "confidence": dict(conf), "client_filled_fields": []}}
    numbers = [mapped.get(f"OtherPolicy_PolicyNumberIdentifier_{r}") for r in "ABCD"]
    assert set(numbers) == {"BBC7263 - 26", "6C7-40-02---26", "6E7-40-02---26", "6J7-40-02---26"}
    # the producer names ONE company after the forms exist
    mf["submission_carrier_name"] = _person("EMC Property & Casualty Company")
    touched = arq._refresh_acord125_page_one(gen, mf, _DEC_DOCS)
    state = gen["ACORD_125"]["field_state"]
    assert touched == ["ACORD_125"]
    assert state["Insurer_FullName_A"] == "EMC Property & Casualty Company"
    assert state["OtherPolicy_PolicyNumberIdentifier_A"] == "BBC7263 - 26"
    for r in "BCD":
        assert not state.get(f"OtherPolicy_PolicyNumberIdentifier_{r}"), r
        assert not state.get(f"OtherPolicy_LineOfBusinessCode_{r}"), r
    assert state["CommercialPolicy_Question_AAHCode_A"] == "Y"


# ══ G2 - the landlord on ACORD 125's additional-interest row ════════════════

_ROW = {"address": "4800 DAHLIA STREET D13, DENVER CO. 80216-3121",
        "address_line1": "4800 DAHLIA ST", "address_line2": "# D13", "address_city": "DENVER",
        "address_state": "CO", "address_zip": "80216-3121", "location_number": "1",
        "is_owner": None, "is_tenant": None, "is_other_interest": None,
        "other_interest_description": None}
_TENANT = "Tenant - the business rents its space"
_OWNER = "Owner - the business owns the building"
_LANDLORD = "Dahlia Street Properties LLC"
_LANDLORD_ADDR = "1200 Blake St, Suite 4, Denver, CO 80202"
_ROW_A = sorted(b for b in S125 if b.startswith("AdditionalInterest_") and b.endswith("_A"))


def _tenant_facts(**over):
    f = {"applicant_name": {"value": "ORBIN CONTRACTING LLC", "source": "ai"},
         "property_locations": [dict(_ROW)],
         "premises_interest": _person(_TENANT),
         "landlord_name": _person(_LANDLORD),
         "landlord_address": _person(_LANDLORD_ADDR),
         "has_property_coverage": False}
    f.update(over)
    return f


_EXPECTED_ROW = {
    "AdditionalInterest_FullName_A": _LANDLORD,
    "AdditionalInterest_MailingAddress_LineOne_A": "1200 Blake St",
    "AdditionalInterest_MailingAddress_CityName_A": "Denver",
    "AdditionalInterest_MailingAddress_StateOrProvinceCode_A": "CO",
    "AdditionalInterest_MailingAddress_PostalCode_A": "80202",
    "AdditionalInterest_Interest_OtherIndicator_A": "Yes",
    "AdditionalInterest_Interest_OtherDescription_A": "Landlord",
    "AdditionalInterest_CertificateRequiredIndicator_A": "Yes",
    "AdditionalInterest_Item_LocationProducerIdentifier_A": "1",
}


def test_the_landlord_prints_on_the_interest_row_through_every_door():
    facts = _tenant_facts()
    with ps._schema_context(S125):
        det = {b: ps._deterministic_map(b, {**facts, "_form_id": "ACORD_125"}) for b in _ROW_A}
    _m, unmatched, _d = ps.compute_form_gaps("ACORD_125", S125, dict(facts))
    mapped, _ = _stamp(facts)
    for box, want in _EXPECTED_ROW.items():
        assert det[box] == want, box
        assert mapped.get(box) == want, box
    assert mapped.get("AdditionalInterest_MailingAddress_LineTwo_A") in ("Suite 4", "Ste 4")
    # the rest of the row is the landlord's owned blank - never a gap-fill guess
    assert not [b for b in _ROW_A if b in unmatched]
    for box in ("AdditionalInterest_Interest_AdditionalInsuredIndicator_A",
                "AdditionalInterest_Interest_MortgageeIndicator_A",
                "AdditionalInterest_AccountNumberIdentifier_A"):
        assert det[box] is None and not mapped.get(box), box
    # row B (ACORD 125's NAME OF TRUST) is not the landlord's
    assert not mapped.get("AdditionalInterest_FullName_B")


def test_the_landlord_steps_aside_everywhere_else():
    cases = {
        "owner": _tenant_facts(premises_interest=_person(_OWNER)),
        "no name": _tenant_facts(landlord_name=None),
        "a 'none' name": _tenant_facts(landlord_name=_person("None")),
        "two locations": _tenant_facts(property_locations=[dict(_ROW), dict(_ROW, location_number="2")]),
        "a loss payee holds the row": _tenant_facts(loss_payee_name=_person("First Bank", "ai")),
        "a document interest holds the row": _tenant_facts(
            additional_interests=[{"name": "First Bank", "interest_type": "Mortgagee"}]),
    }
    for why, facts in cases.items():
        assert ps.landlord_interest_row({**facts, "_form_id": "ACORD_125"}) is None, why
        assert ps._resolve_landlord_interest_row(
            "AdditionalInterest_FullName_A", {**facts, "_form_id": "ACORD_125"}) is ps._SCHED_SKIP, why
    # other forms never
    assert ps.landlord_interest_row({**_tenant_facts(), "_form_id": "ACORD_126"}) is None


def test_an_address_that_does_not_parse_goes_on_line_one():
    row = ps.landlord_interest_row({**_tenant_facts(landlord_address=_person("noida 22")),
                                    "_form_id": "ACORD_125"})
    assert row["line1"] == "noida 22" and not row["city"] and not row["zip"]
    row = ps.landlord_interest_row({**_tenant_facts(landlord_address=None), "_form_id": "ACORD_125"})
    assert row["name"] == _LANDLORD and not row["line1"]


def test_the_owners_own_landlord_answer_prints_whatever_its_shape():
    # the owner's live values (session 8739a72a): a lowercase name with an
    # initial and an address that parses to nothing - a person's answer is theirs
    facts = _tenant_facts(landlord_name=_person("vinay p"), landlord_address=_person("noida 22"))
    mapped, _ = _stamp(facts)
    # display canonicalization prints names / addresses in title case, as everywhere
    assert str(mapped.get("AdditionalInterest_FullName_A")).lower() == "vinay p"
    assert str(mapped.get("AdditionalInterest_MailingAddress_LineOne_A")).lower() == "noida 22"
    assert mapped.get("AdditionalInterest_Interest_OtherDescription_A") == "Landlord"
    assert mapped.get("AdditionalInterest_CertificateRequiredIndicator_A") == "Yes"
    # ...while the same guard still blanks boilerplate NO person gave
    junk = {"AdditionalInterest_FullName_A": "For Informational Purposes Only"}
    ps._enforce_post_fill_guards(junk, S125, {"_form_id": "ACORD_125"},
                                 gpt_filled_set={"AdditionalInterest_FullName_A"})
    assert not junk["AdditionalInterest_FullName_A"]
    assert ps._a_person_typed("VINAY P", facts) and not ps._a_person_typed("vinay", facts)


def test_the_role_guard_keeps_the_interest_kind_and_still_protects_names():
    kind_box = "AdditionalInterest_Interest_OtherDescription_A"
    assert ps._rejects_role_or_arrangement(kind_box, S125[kind_box], "Landlord") is None
    assert ps._rejects_role_or_arrangement(
        "AdditionalInterest_FullName_A", S125["AdditionalInterest_FullName_A"], "Certificate Holder")
    assert ps._rejects_role_or_arrangement(
        "AdditionalInterest_FullName_A", S125["AdditionalInterest_FullName_A"], "Landlord")
    # exactly the seven "other type of additional interest" boxes are exempt
    exempt = []
    for fid in ("ACORD_125", "ACORD_126", "ACORD_127", "ACORD_140", "ACORD_28", "ACORD_130", "ACORD_131"):
        for f, meta in _schema(fid).items():
            if ps._INTEREST_KIND_BOX_RE.search(str((meta or {}).get("tu") or "")):
                exempt.append(f)
    assert exempt and all(f.startswith("AdditionalInterest_Interest_OtherDescription_") for f in exempt)


def _generated(facts):
    mapped, conf = _stamp(facts)
    return {"ACORD_125": {"schema": S125, "field_state": mapped, "confidence": conf,
                          "client_filled_fields": []}}


def _run(store, coro_fn):
    async def _get(_sid, include_pdf=False):
        return copy.deepcopy(store)

    async def _upd(_sid, payload, delete_facts=None):
        for k, v in (payload or {}).items():
            store[k] = v
        for k in delete_facts or ():
            (store.get("facts") or {}).pop(k, None)
        return True

    with patch.object(sr, "get_processing_session", _get), \
         patch.object(sr, "upd_processing_session", _upd):
        return asyncio.run(coro_fn())


def test_a_landlord_answered_after_generation_prints_at_once_and_reopen_clears_it():
    before = _tenant_facts(landlord_name=None, landlord_address=None)
    store = {"facts": copy.deepcopy(before), "flags": {}, "generated_forms": _generated(before)}
    assert not store["generated_forms"]["ACORD_125"]["field_state"].get("AdditionalInterest_FullName_A")
    ok, _ = _run(store, lambda: arq.apply_producer_answer_to_session("sid-g2", "landlord_name", _LANDLORD))
    assert ok is True
    form = store["generated_forms"]["ACORD_125"]
    assert form["field_state"]["AdditionalInterest_FullName_A"] == _LANDLORD
    assert form["field_state"]["AdditionalInterest_Interest_OtherDescription_A"] == "Landlord"
    assert form["field_state"]["AdditionalInterest_CertificateRequiredIndicator_A"] == "Yes"
    assert form["confidence"]["AdditionalInterest_FullName_A"] == "producer"
    written = {"AdditionalInterest_FullName_A", "AdditionalInterest_Interest_OtherIndicator_A",
               "AdditionalInterest_Interest_OtherDescription_A",
               "AdditionalInterest_CertificateRequiredIndicator_A",
               "AdditionalInterest_Item_LocationProducerIdentifier_A"}
    assert all(form["confidence"].get(b) == "producer" for b in written)
    ok, _ = _run(store, lambda: arq.clear_producer_answer_from_session("sid-g2", "landlord_name"))
    assert ok is True
    form = store["generated_forms"]["ACORD_125"]
    for box in _EXPECTED_ROW:
        assert not form["field_state"].get(box), box
    # what the landlord wrote leaves with its label; the address boxes it never
    # wrote (no address was given) keep whatever generation gave them
    for box in written:
        assert box not in form["confidence"], box


def test_a_premises_that_stops_being_a_tenancy_clears_only_the_landlords_values():
    tenant = _tenant_facts()
    gen = _generated(tenant)
    state = gen["ACORD_125"]["field_state"]
    state["AdditionalInterest_MailingAddress_CityName_A"] = "Boulder"      # someone else's edit
    owner = dict(tenant, premises_interest=_person(_OWNER))
    touched = arq._refresh_acord125_landlord(gen, tenant, owner, "producer")
    assert touched == ["ACORD_125"]
    assert not state.get("AdditionalInterest_FullName_A")
    assert not state.get("AdditionalInterest_Interest_OtherDescription_A")
    assert state["AdditionalInterest_MailingAddress_CityName_A"] == "Boulder"
    # nothing to do when neither side holds the row
    assert arq._refresh_acord125_landlord(gen, owner, owner, "producer") == []


def test_a_client_landlord_answer_prints_in_the_clients_colour():
    before = _tenant_facts(landlord_name=None, landlord_address=None)
    gen = _generated(before)
    after = dict(before, landlord_name=_person(_LANDLORD, "client_arq"))
    arq._refresh_acord125_landlord(gen, before, after, "client_arq")
    form = gen["ACORD_125"]
    assert form["field_state"]["AdditionalInterest_FullName_A"] == _LANDLORD
    assert form["confidence"]["AdditionalInterest_FullName_A"] == "client_arq"
    assert "AdditionalInterest_FullName_A" in form["client_filled_fields"]
    # and the client questionnaire path calls the refresh
    src = inspect.getsource(arq.apply_arq_answers_to_session)
    assert "_refresh_acord125_landlord(generated, _facts_before_answers, facts" in src


# ══ Items 8 / 11 - a ticked line with a blank premium is listed ═════════════

_AUTO_TICK = "Policy_LineOfBusiness_BusinessAutoIndicator_A"
_GL_TICK = "Policy_LineOfBusiness_CommercialGeneralLiability_A"
_AUTO_PREMIUM = "CommercialVehicleLineOfBusiness_PremiumAmount_A"
_GL_PREMIUM = "GeneralLiabilityLineOfBusiness_TotalPremiumAmount_A"
_TOTAL = "Policy_Payment_EstimatedTotalAmount_A"


def test_every_125_line_pairs_with_its_own_premium_box_and_no_other_form_has_pairs():
    pairs = ps.lob_premium_box_pairs(S125)
    assert len(pairs) == 15 and len(set(pairs.values())) == 15
    assert pairs[_AUTO_TICK] == _AUTO_PREMIUM and pairs[_GL_TICK] == _GL_PREMIUM
    for fid in ("ACORD_126", "ACORD_127", "ACORD_131", "ACORD_160", "ACORD_186"):
        assert ps.lob_premium_box_pairs(_schema(fid)) == {}, fid


def _form(state):
    return {"schema": S125, "field_state": dict(state), "mapped": dict(state),
            "confidence": {}, "client_filled_fields": []}


def test_a_ticked_line_with_no_premium_is_a_producer_todo():
    fr125 = _form({_AUTO_TICK: "Yes", _GL_TICK: "Yes", _GL_PREMIUM: "3,954"})
    rows = na.needs_attention(fr125, {}, "ACORD_125")
    premium_rows = {r["field"]: r for r in rows if r.get("producer_todo")}
    assert set(premium_rows) == {_AUTO_PREMIUM, _TOTAL}
    auto = premium_rows[_AUTO_PREMIUM]
    assert auto["status"] == na.STATUS_MISSING and auto["score_effect"] == 0
    assert auto["what_to_do"] == "Enter it on the form if you know it."
    assert "business auto" in auto["label"].lower() and "_" not in auto["label"]
    # nothing to list once every ticked line and the total are filled, or nothing is ticked
    full = _form({_AUTO_TICK: "Yes", _AUTO_PREMIUM: "2,991", _TOTAL: "2,991"})
    assert not [r for r in na.needs_attention(full, {}, "ACORD_125") if r.get("producer_todo")]
    assert not [r for r in na.needs_attention(_form({}), {}, "ACORD_125") if r.get("producer_todo")]


def test_premium_todos_stay_off_the_underwriters_cover_page():
    fr125 = _form({_AUTO_TICK: "Yes"})
    rows = na.needs_attention(fr125, {}, "ACORD_125")
    recs = na.attention_recommendation_rows({"forms": [{"form_id": "ACORD_125", "rows": rows}]})
    todo = [r for r in recs if r["rec_id"].endswith("_missing_producer")]
    assert todo and na.is_producer_todo_row(todo[0]["rec_id"])
    assert "premium" in todo[0]["message"].lower()
    gaps = [r for r in recs if r["rec_id"].endswith("_missing")]
    assert all(not na.is_producer_todo_row(r["rec_id"]) for r in gaps)


# ══ A box the producer types over is the producer's ═════════════════════════

def test_a_typed_value_is_the_producers_and_leaves_the_clients_list():
    conf = {"A": "low_confidence", "B": "ai_verified", "C": "missing_required",
            "D": "client_arq", "E": "low_confidence", "F": "client_arq"}
    client = {"D", "F"}
    fr.label_producer_edits(conf, client, {"A": "Y", "B": "Acme", "C": "5", "D": "Retyped",
                                           "E": "", "F": None})
    assert conf["A"] == conf["B"] == conf["C"] == conf["D"] == "producer"
    assert "D" not in client
    # a CLEARED box keeps the old rule: low_confidence unless client / required
    assert conf["E"] == "low_confidence" and conf["F"] == "client_arq" and "F" in client


def test_update_pdf_uses_the_rule_and_saves_the_clients_list():
    src = inspect.getsource(fr.update_pdf)
    assert "label_producer_edits(confidence, _client_filled, req.field_updates)" in src
    assert '"client_filled_fields": sorted(_client_filled)' in src
    assert "so pink highlights persist" not in src
