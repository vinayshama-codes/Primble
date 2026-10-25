"""Build 25 lane C (23 Oct 2026) - Brent's 23 Oct answers, items 5 and 6.

Item 5 (Z34-1 #6, part P): the insured's state comes only from insured
evidence, PER COVERAGE - "Do not use the carrier's letterhead, headquarters, or
address to determine the insured's state ... If we cannot verify the correct
state from insured-specific information, leave it unverified and ask". The
model's `state_of_operations` never counts on its own; a person's answer to the
state question does. The recommender's logic is untouched - only its input.

Item 6 (Z34-2 Q3): "Users only need to see relevant information. The audit
record is fine." No "AI held back" list anywhere a user looks; a refused Yes/No
question or a detail with a fact / table behind it is Missing; the refused value
itself stays in the audit record only.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
FRONTEND = BACKEND.parent / "frontend" / "src"
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

from services import extraction_service as es                         # noqa: E402
from services import form_service as fs                               # noqa: E402
from services import needs_attention as na                            # noqa: E402
from services.cross_form_validator import _check_acord127_state_section  # noqa: E402

_FIX = BACKEND / "tests" / "fixtures"
AUTO = {"has_auto_coverage": True}


def _ai(value):
    return {"value": value, "source": "ai", "confidence": "ai_high"}


def _person(value):
    return {"value": value, "source": "producer"}


def _recs(facts, flags=AUTO, text=""):
    return {r["form_id"] for r in fs.match_forms_deterministic(facts, dict(flags), text=text)}


def _card(facts, triggered, flags=AUTO):
    return [i for i in _check_acord127_state_section(facts, dict(flags), set(triggered))]


# ══ Item 5 - the state, per coverage, from insured evidence ═══════════════════

@pytest.mark.parametrize("value, codes", [
    ("CO", {"CO"}), ("Colorado", {"CO"}), ("CO, CA", {"CO", "CA"}),
    ("Colorado and Wyoming", {"CO", "WY"}), ("4800 Dahlia St, Denver, CO 80216", {"CO"}),
    ("1450 California Street, Suite 900, Denver, CO 80202", {"CO"}),
    (["CO", "TX"], {"CO", "TX"}), (_ai("PA"), {"PA"}), ("N/A", set()), ("", set()), (None, set()),
])
def test_state_codes_of_reads_codes_names_lists_and_addresses(value, codes):
    assert fs.state_codes_of(value) == codes


def test_a_letterhead_only_state_never_adds_a_form_and_is_asked():
    facts = {"state_of_operations": _ai("CO")}          # a carrier's Denver office, say
    assert "ACORD_137_CO" not in _recs(facts)
    assert fs.state_unverified(facts, fs.COVERAGE_AUTO)
    card = _card(facts, {"ACORD_125", "ACORD_127"})
    assert [c["code"] for c in card] == ["auto_state_unverified"]
    assert card[0]["type"] == "advisory"                # an ask, never a score cap
    res = card[0]["resolution"]
    assert res["mode"] == "field" and res["facts"] == ["state_of_operations"]


@pytest.mark.parametrize("facts", [
    {"mailing_address": "4800 Dahlia St, Denver, CO 80216"},
    {"auto_garaging_addresses": ["DENVER, CO 80221"]},
    {"locations": ["200 16th St, Denver, CO 80202"]},
    {"state_of_operations": _person("CO")},
])
def test_insured_evidence_of_co_still_gives_137_co(facts):
    assert "ACORD_137_CO" in _recs(facts)
    assert not _card(facts, {"ACORD_127"}) or _card(facts, {"ACORD_127"})[0]["code"] != "auto_state_unverified"


def test_the_autos_state_is_where_they_are_garaged_not_another_lines():
    # garaging outranks the insured's address (the autos' own evidence)
    facts = {"mailing_address": "4800 Dahlia St, Denver, CO 80216",
             "auto_garaging_addresses": ["100 Main St, Houston, TX 77002"]}
    assert fs.coverage_states(facts, fs.COVERAGE_AUTO) == {"TX"}
    assert "ACORD_137_CO" not in _recs(facts)
    # WC's CO payroll is the WC line's state - not the autos' (no universal state)
    wc_only = {"wc_payroll_by_state": {"CO": "$2,626,500"}}
    assert fs.coverage_states(wc_only, fs.COVERAGE_WC) == {"CO"}
    assert fs.state_unverified(wc_only, fs.COVERAGE_AUTO)
    assert fs.coverage_states(wc_only) == {"CO"}          # every insured state, together


def test_the_model_reading_is_never_counted_even_beside_other_states():
    facts = {"mailing_address": "1 A St, Reno, NV 89501", "state_of_operations": _ai("CO")}
    assert fs.coverage_states(facts) == {"NV"}
    assert fs._collect_states(facts, fs.COVERAGE_GL) == {"NV"}
    # backed by insured evidence it picks the primary state among several
    both = {"mailing_address": "1 A St, Reno, NV 89501", "locations": ["200 16th St, Denver, CO 80202"],
            "state_of_operations": _ai("CO")}
    assert fs._infer_primary_state(both) == "CO"
    assert fs._infer_primary_state({"state_of_operations": _ai("CO")}) is None


def test_the_answer_box_takes_states_and_refuses_anything_else():
    from services.answer_routing import answer_mode
    from services.fact_registry import FACT_REGISTRY, answer_refusal
    entry = FACT_REGISTRY["state_of_operations"]
    assert entry["tier"] is None and entry["validate"] is None   # unscored; the merge never keys on it
    for ok in ("CO", "co", "Colorado", "CO, CA", "Colorado and Wyoming"):
        assert answer_refusal(entry, ok) == "", ok
    for bad in ("N/A", "PA office", "Denver", "123", ""):
        assert answer_refusal(entry, bad), bad
    assert answer_mode("state_of_operations")["mode"] == "field"


def test_the_merge_drops_an_unbacked_model_state_and_keeps_a_persons():
    doc = lambda facts: {"filename": "d.pdf", "facts": dict(facts), "flags": {}, "text": ""}  # noqa: E731
    docs = [doc({"state_of_operations": "PA"})]
    es._drop_non_insured_states(docs)
    assert "state_of_operations" not in docs[0]["facts"]
    assert "no insured document" in json.dumps(docs[0]["facts"].get("_rejected_facts") or {})
    kept = [doc({"state_of_operations": {"value": "PA", "source": "producer"}})]
    es._drop_non_insured_states(kept)
    assert kept[0]["facts"]["state_of_operations"]["value"] == "PA"


def test_a_state_restricted_box_reads_its_own_coverage(monkeypatch):
    import services.state_restricted_boxes as srb
    monkeypatch.setattr(srb, "restricted_boxes", lambda _fid: {"X_A": frozenset({"WI"})})
    facts = {"locations": ["1 Main St, Denver, CO 80202"], "wc_payroll_by_state": {"WI": "$1"}}
    assert srb.outside_its_state("ACORD_126", "X_A", facts) is True      # GL: its premises are CO
    assert srb.outside_its_state("ACORD_131", "X_A", facts) is False     # every state: WI is one
    # the model's letterhead WI never puts a GL box "inside" Wisconsin
    letterhead = {"mailing_address": "1 Main St, Denver, CO 80202", "state_of_operations": _ai("WI")}
    assert srb.outside_its_state("ACORD_126", "X_A", letterhead) is True
    assert srb.outside_its_state("ACORD_126", "X_A", {"state_of_operations": _ai("CO")}) is False


# ── The saved fixtures: which packages' recommended forms change ─────────────

def _merged(docs):
    d = copy.deepcopy(docs)
    return es.merge_facts(d, es.select_primary_truth(d))


@pytest.fixture(scope="module")
def choice_electric():
    return json.load(open(_FIX / "choice_electric_pol_6oct.json"))["docs"]


def test_choice_electric_seven_decs_keep_137_co(choice_electric):
    mf, flags = _merged(choice_electric)
    assert es._fv(mf, "state_of_operations") == "CO"     # MI / PA / AZ / IN letterheads dropped
    assert "ACORD_137_CO" in _recs(mf, flags)


def test_choice_electric_as_805049a7_ran_is_asked_not_pa(choice_electric):
    # The auto policy held back and the WC table lost to extraction: only
    # carrier letterheads stated a state. Before: the merge settled on a
    # letterhead (PA / AZ); now nothing is asserted and the producer is asked.
    docs = [copy.deepcopy(d) for d in choice_electric if "Business Auto" not in d["filename"]]
    for d in docs:
        if "Workers" in d["filename"]:
            d["facts"].pop("wc_payroll_by_state", None)
            d["facts"].pop("wc_class_codes", None)
    mf, flags = _merged(docs)
    assert not es._fv(mf, "state_of_operations")
    recs = _recs(mf, dict(flags, has_auto_coverage=True))
    assert not {f for f in recs if f.startswith(("ACORD_137_", "ACORD_138_"))}
    assert [c["code"] for c in _card(mf, recs | {"ACORD_127"})] == ["auto_state_unverified"]
    # the producer's answer gives the form back
    answered = dict(mf, state_of_operations=_person("CO"))
    assert "ACORD_137_CO" in _recs(answered, dict(flags, has_auto_coverage=True))


def test_orbin_and_the_policy_by_line_kit_keep_137_co():
    o24 = json.load(open(_FIX / "orbin_live_24sep.json"))
    assert "ACORD_137_CO" in _recs(o24["merged_facts"], o24["flags"])
    upload = json.load(open(_FIX / "policy_by_line_live_17sep.json"))["upload_1_package_and_project_certificate"]
    mf, flags = _merged(upload)
    assert fs._supported_state_forms(mf, flags) == ["CO"]


def test_the_ch125_kit_tennessee_insured_gets_no_ca_or_co_form():
    facts = {"mailing_address": "Nashville, TN 37204-1120",
             "locations": ["2850 Kellerman Industrial Pkwy, Nashville, TN 37211"],
             "state_of_operations": _ai("TN")}
    assert fs.coverage_states(facts, fs.COVERAGE_AUTO) == {"TN"}
    assert not {f for f in _recs(facts) if f.startswith(("ACORD_137_", "ACORD_138_"))}
    assert not _card(facts, {"ACORD_127"})


# ══ Item 6 - the AI's refused values: the audit record only ═══════════════════

@pytest.fixture(scope="module")
def live():
    d = json.load(open(_FIX / "needs_attention_live_30sep.json"))["b8d6"]
    return d["generated_forms"], d["facts"], d["flags"]


def test_no_user_list_carries_a_held_back_row(live):
    gf, facts, flags = live
    res = na.needs_attention_for_session(gf, facts, flags=flags, hard_blocks=True, findings=True)
    rows = [r for f in res["forms"] for r in f["rows"]]
    assert rows and not [r for r in rows if r["status"] == na.STATUS_HELD_BACK]
    assert res["counts"][na.STATUS_HELD_BACK] == 0
    assert all("refused" not in f for f in res["forms"])           # the user payload never ships them


def test_refused_questions_and_details_are_missing_and_the_rest_is_audit_only(live):
    gf, facts, flags = live
    refused: list = []
    rows = {r["field"]: r for r in na.needs_attention(gf["ACORD_125"], facts, "ACORD_125",
                                                      flags=flags, refused=refused)}
    by = {r["field"]: r for r in refused}
    # an unanswered Yes/No underwriting question: Missing, in the form's words
    q = rows["CommercialPolicy_Question_ABCCode_A"]
    assert q["status"] == na.STATUS_MISSING and q["reason"] == "An underwriting question your documents do not answer."
    # a detail with a fact behind it: Missing, the refused value never shown
    sic = rows["NamedInsured_SICCode_A"]
    assert sic["status"] == na.STATUS_MISSING and sic["found_value"] is None
    assert sic["fold_keys"] == ["sic_code"] and "GL class codes" not in sic["reason"]
    # a refused value with nothing behind it: not listed, kept for the record
    for f in ("NamedInsured_Primary_PhoneNumber_A", "BusinessInformation_ParentOrganizationName_A"):
        assert f not in rows and f in by
    assert "GL class codes" in by["NamedInsured_SICCode_A"]["reason"]   # the record keeps why


def test_a_refused_driver_date_is_a_missing_detail_with_its_table():
    schema = json.load(open(BACKEND / "forms_schemas" / "ACORD_127_schema.json"))
    fr = {"mapped": {"Driver_GivenName_B": "Alicia", "Driver_Surname_B": "Fontenot"},
          "confidence": {}, "schema": schema,
          "guard_blanks": [{"field": "Driver_BirthDate_B", "removed_value": "2012"}]}
    refused: list = []
    rows = {r["field"]: r for r in na.needs_attention(fr, {}, "ACORD_127", refused=refused)}
    r = rows["Driver_BirthDate_B"]
    assert r["status"] == na.STATUS_MISSING and "auto_drivers" in r["fold_keys"]
    assert r["found_value"] is None and "2012" not in r["reason"]
    assert [x["field"] for x in refused] == ["Driver_BirthDate_B"]


def test_the_audit_record_keeps_them_and_no_screen_lists_them(live):
    gf, facts, flags = live
    audit = na.attention_recommendation_rows(na.needs_attention_for_session(gf, facts, flags=flags, audit=True))
    held = [r for r in audit if r["rec_id"].endswith("_" + na.STATUS_HELD_BACK)]
    assert [r["rec_id"] for r in held] == ["fieldqa_attn_ACORD_125_ai_held_back"]
    assert held[0]["message"].startswith("ACORD 125 - AI held back (13): ")
    assert na.is_producer_todo_row(held[0]["rec_id"])               # the cover still leaves it out
    plain = na.attention_recommendation_rows(na.needs_attention_for_session(gf, facts, flags=flags))
    assert not [r for r in plain if r["rec_id"].endswith("_" + na.STATUS_HELD_BACK)]
    # the download review drops a stored record row, even for a form it could not read
    legacy = {"rec_id": "fieldqa_ACORD_125_guard_removed_value_grp",
              "message": "ACORD 125: 2 fields left blank on purpose - ..."}
    shown = na.download_review_rows([dict(held[0]), legacy], gf, [])
    assert shown == []


def test_one_item_is_never_listed_twice(live):
    import services.field_qa as fq
    gf, facts, flags = live
    qa = fq.run_field_qa(gf, merged_facts=facts, confirmations={}, flags=flags)
    att = na.needs_attention_for_session(gf, facts, flags=flags, audit=True)
    rows = fq.to_recommendation_rows(qa, attention=att)
    assert not [r for r in rows if "guard_removed_value" in str(r.get("rec_id"))]
    fields = [r["field"] for r in att["forms"][0]["rows"]]
    assert len(fields) == len(set(fields))
    assert not set(fields) & {r["field"] for r in att["forms"][0]["refused"]
                              if r["field"] not in fields}


def test_both_audit_record_sites_ask_for_the_refused_values():
    src = (BACKEND / "services" / "audit_service.py").read_text(encoding="utf-8")
    assert src.count("audit=True") >= 2


def test_the_side_panel_and_download_screen_have_no_held_back_section():
    util = (FRONTEND / "utils" / "needsAttention.js").read_text(encoding="utf-8")
    panel = (FRONTEND / "components" / "form" / "NeedsAttentionPanel.jsx").read_text(encoding="utf-8")
    assert 'export const ATTENTION_STATUS_ORDER = ["missing", "verify"];' in util
    assert "heldBack" not in util and "heldBack" not in panel and "ai_held_back:" not in util
    assert "AI_HELD_BACK_TIP" not in panel and "AI held back (" not in panel
    for text in (util, panel):
        assert "—" not in text
