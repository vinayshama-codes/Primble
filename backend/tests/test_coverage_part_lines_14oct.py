"""The coverage-part card asks for the line, and is not raised for a single-line dec's own parts (14 Oct 2026).

Owner, live package 91c865a5 (Choice Electric, 7 decs, pre-form): the review screen showed

    Coverage terminology not recognised - Coverage part not recognised: Non-Panel Response
    Provider, Digital Data Recovery, Network Extortion, Payment Card Loss, +2 more. The
    documents show it is carried, but Primble has no normalization rule ... / Primble can't
    tell which line this belongs to. Check the source document, then mark it resolved.

    "we should not tell user that we don't have anything for this, give user to enter the
     correct option, fix it now and if we have any other similar like this, fix them too"

ROOT CAUSE. The six names are the Cyber policy's own insuring agreements, printed as rows of
the Cyber dec's coverage grid. `lob_canon.unmapped_material_lines` judged each row on its
NAME alone, so a part of a known line read as unknown terminology. Now:
  1. a row a single-line declarations prints, that no rule places, is a part of that line
     (`lob_canon.attribute_parts_to_document_line`, per document in the merge) - marked, never
     renamed, read by the review alone, so no family is created and the recommender holds;
  2. when a part's line still cannot be told (a multi-line document), the card offers the
     standard lines plus "Part of another policy" - one producer fact,
     `lob_canon.PART_LINES_FACT`, through the ordinary field door, so "Open again" takes it
     back through the fix receipt;
  3. the other review-only cards that ended at "nothing to enter" got an input or a note
     naming what to do.

The route tests drive the REAL resolve / reopen routes and scorer through the in-memory
session of tests/test_reopen_takes_the_fix_back_9oct.py; the window's composer runs under node.
"""
from __future__ import annotations

import copy
import json
import shutil
import subprocess
from pathlib import Path

import pytest

import test_reopen_takes_the_fix_back_9oct as H                                   # noqa: E402
from test_reopen_takes_the_fix_back_9oct import _Session, _row                   # noqa: E402

import services.issue_fix_undo as undo                                          # noqa: E402
from services.extraction_service import (                                       # noqa: E402
    mark_parts_of_document_line, merge_facts, select_primary_truth,
)
from services.issue_registry import (                                           # noqa: E402
    RESOLUTION_MAP, _LEGACY_CODE_RESOLUTIONS, _CONFLICT_REVIEW_NOTE, build_grouped_view,
    grouped_with_package_caps, refresh_unmapped_line_issue, resolution_for,
    unmapped_line_issue, unmapped_line_message,
)
from services.lob_canon import (                                                # noqa: E402
    PART_LINES_FACT, PART_OF_ANOTHER_POLICY, PART_OF_KEY, attribute_parts_to_document_line,
    carried_lines_of_business, coverage_families_present, evidenced_line_families,
    format_part_lines, is_valid_part_lines, parse_part_lines, part_key, part_line_choices,
    unmapped_material_lines,
)

_FRONT = Path(__file__).resolve().parents[2] / "frontend" / "src"
_PART_LINES_JS = _FRONT / "utils" / "partLines.js"
_MODAL = _FRONT / "components" / "form" / "ResolutionModal.jsx"
_CODE = "unmapped_coverage_line"
_ACE = "ACE American Insurance Company"
_AMERISURE = "AMERISURE INSURANCE COMPANY"

# ══ The live shape: 91c865a5's per-document rows, as extraction stored them ══════
_CYBER_ROWS = [
    {"line": "Cyber Incident Response Team", "carrier": _ACE, "premium": "$1,000,000"},
    {"line": "Non-Panel Response Provider", "carrier": _ACE, "premium": "$500,000"},
    {"line": "Business Interruption Loss and Extra Expenses", "carrier": _ACE, "premium": "$1,000,000"},
    {"line": "Contingent Business Interruption Loss and Extra Expenses", "carrier": _ACE, "premium": "$1,000,000"},
    {"line": "Digital Data Recovery", "carrier": _ACE, "premium": "$1,000,000"},
    {"line": "Network Extortion", "carrier": _ACE, "premium": "$1,000,000"},
    {"line": "Cyber, Privacy and Network Security Liability", "carrier": _ACE, "premium": "$1,000,000"},
    {"line": "Payment Card Loss", "carrier": _ACE, "premium": "$1,000,000"},
    {"line": "Regulatory Proceeding", "carrier": _ACE, "premium": "$1,000,000"},
    {"line": "Electronic, Social And Printed Media Liability", "carrier": _ACE, "premium": "$1,000,000"},
]
_SIX = ["Non-Panel Response Provider", "Digital Data Recovery", "Network Extortion",
        "Payment Card Loss", "Regulatory Proceeding", "Electronic, Social And Printed Media Liability"]
_PACKAGE_ROWS = [
    {"line": "Commercial Property", "carrier": _AMERISURE, "premium": "$ 6,275.00"},
    {"line": "Commercial General Liability", "carrier": _AMERISURE, "premium": "$ 16,818.00"},
    {"line": "Commercial Inland Marine", "carrier": _AMERISURE, "premium": "$ 2,431.00"},
    {"line": "Crime and Fidelity", "carrier": _AMERISURE, "premium": "$ 500.00"},
    {"line": "Employee Benefit Liability", "carrier": _AMERISURE, "premium": "$ 425.00"},
]


def _doc(name, rows, doc_type="dec_page", flags=None, **facts):
    return {"filename": name, "doc_type": doc_type, "text": f"{name} declarations",
            "facts": {"coverage_lines": copy.deepcopy(rows), "applicant_name": "Choice Electric LLC",
                      **facts},
            "flags": dict(flags or {})}


def _merged(*docs):
    docs = [copy.deepcopy(d) for d in docs]
    facts, _flags = merge_facts(docs, select_primary_truth(docs))
    rows = facts.get("coverage_lines")
    return facts, (rows.get("value") if isinstance(rows, dict) and "value" in rows else rows)


def _strip_marker(rows):
    return [{k: v for k, v in r.items() if k != PART_OF_KEY} for r in rows]


# ── 1. The six cyber parts on the Cyber dec raise no card ──────────────────────
def test_the_six_cyber_parts_are_the_cyber_decs_own():
    rows = copy.deepcopy(_CYBER_ROWS)
    assert unmapped_material_lines(rows) == _SIX          # the owner's card, before
    marked = attribute_parts_to_document_line(rows)
    assert marked == _SIX
    assert {r["line"]: r.get(PART_OF_KEY) for r in rows if r.get(PART_OF_KEY)} == dict.fromkeys(_SIX, "cyber")
    assert unmapped_material_lines(rows) == []
    # A known part keeps its own placement - never re-attributed.
    bi = next(r for r in rows if r["line"].startswith("Business Interruption"))
    assert PART_OF_KEY not in bi


def test_through_the_real_merge_the_card_is_gone_and_nothing_else_moves():
    cyber = _doc("25-26 Cyber Policy.pdf", _CYBER_ROWS, flags={"has_cyber": True})
    package = _doc("25-26 Package Policy.pdf", _PACKAGE_ROWS,
                   flags={"has_property_coverage": True, "has_general_liability": True})
    facts, rows = _merged(cyber, package)
    assert unmapped_material_lines(rows) == []
    assert unmapped_line_issue(facts) is None
    # The marker is read by the review alone: every line reader answers the same
    # with and without it, so no family appears and the recommender cannot move.
    bare = _strip_marker(rows)
    assert coverage_families_present(rows) == coverage_families_present(bare)
    stripped = dict(facts, coverage_lines=bare)
    assert carried_lines_of_business(facts) == carried_lines_of_business(stripped)
    assert evidenced_line_families(facts) == evidenced_line_families(stripped)
    from services.form_service import filter_available_forms, load_all_forms, match_forms
    forms = filter_available_forms(load_all_forms())
    assert ([r["form_id"] for r in match_forms(facts, {}, forms)]
            == [r["form_id"] for r in match_forms(stripped, {}, forms)])


# ── 2. Guards: only a single policy's own grid, only its own contract ─────────
def test_a_part_on_a_multi_line_document_is_left_for_the_producer():
    rows = copy.deepcopy(_PACKAGE_ROWS) + [{"line": "Kidnap and Ransom", "carrier": _AMERISURE,
                                            "premium": "$700"}]
    assert attribute_parts_to_document_line(rows) == []
    assert unmapped_material_lines(rows) == ["Kidnap and Ransom"]


@pytest.mark.parametrize("extra", [
    {"policy_number": "KR-7781-26"},                 # another contract on the same page
    {"carrier": "Lloyd's Syndicate 2001"},           # another company's policy
])
def test_another_policy_printed_on_a_single_line_dec_is_not_attributed(extra):
    rows = [{"line": "Cyber Liability", "carrier": _ACE, "premium": "$4,100",
             "policy_number": "D9512345"},
            {"line": "Kidnap and Ransom", "carrier": _ACE, "premium": "$700", **extra}]
    assert attribute_parts_to_document_line(rows) == []
    assert unmapped_material_lines(rows) == ["Kidnap and Ransom"]


def test_the_same_contract_number_is_attributed():
    rows = [{"line": "Cyber Liability", "carrier": _ACE, "premium": "$4,100", "policy_number": "D9512345"},
            {"line": "Network Extortion", "carrier": _ACE, "limit": "$1,000,000",
             "policy_number": "D95123-45"}]
    assert attribute_parts_to_document_line(rows) == ["Network Extortion"]


def test_a_certificate_is_never_one_policys_grid():
    cert = _doc("COI.pdf", [{"line": "Commercial General Liability", "premium": "$1,000"},
                            {"line": "Builders Risk Special Form", "limit": "$2,000,000"}],
                doc_type="certificate")
    assert mark_parts_of_document_line(cert) == []
    dec = _doc("GL dec.pdf", cert["facts"]["coverage_lines"])
    assert mark_parts_of_document_line(dec) == ["Builders Risk Special Form"]


def test_a_denied_line_is_not_the_documents_line_and_one_row_is_not_a_grid():
    denied = [{"line": "Cyber Liability", "premium": "No Coverage"},
              {"line": "Widget Protection", "premium": "$100"}]
    assert attribute_parts_to_document_line(denied) == []
    assert attribute_parts_to_document_line([{"line": "Widget Protection", "premium": "$100"}]) == []
    assert attribute_parts_to_document_line(None) == []


def test_a_document_named_only_by_its_unambiguous_parts_still_has_one_line():
    rows = [{"line": "Collision", "premium": "$688"}, {"line": "Towing", "premium": "$20"},
            {"line": "Widget Protection", "premium": "$100"}]
    assert attribute_parts_to_document_line(rows) == ["Widget Protection"]
    assert rows[2][PART_OF_KEY] == "auto"


def test_one_attributed_printing_places_every_printing_of_that_name():
    rows = [{"line": "Network Extortion", "premium": "$1,000,000", PART_OF_KEY: "cyber"},
            {"line": "Network  Extortion", "limit": "$1,000,000"}]
    assert unmapped_material_lines(rows) == []


# ── 3. The card offers an input - the parts and the standard lines ────────────
def _multi_line_facts(**extra):
    rows = copy.deepcopy(_PACKAGE_ROWS) + [
        {"line": "Kidnap and Ransom", "carrier": _AMERISURE, "premium": "$700"},
        {"line": "Widget Protection", "carrier": _AMERISURE, "limit": "$50,000"}]
    return {"coverage_lines": rows, **extra}


def test_the_card_asks_for_a_line_per_part_in_plain_words():
    card = unmapped_line_issue(_multi_line_facts())
    assert card["code"] == _CODE and card["severity"] == "advisory" and card["score_neutral"] is True
    msg = card["message"]
    assert msg == unmapped_line_message(["Kidnap and Ransom", "Widget Protection"])
    for banned in ("Primble", "not recognised", "normalization", "can't", "cannot", "—"):
        assert banned not in msg, banned
    res = card["resolution"]
    assert res["mode"] == "field" and res["facts"] == [PART_LINES_FACT]
    ctl = res["controls"][PART_LINES_FACT]
    assert ctl["control"] == "part_lines"
    assert [p["label"] for p in ctl["parts"]] == ["Kidnap and Ransom", "Widget Protection"]
    assert [p["key"] for p in ctl["parts"]] == [part_key("Kidnap and Ransom"), part_key("Widget Protection")]
    values = [o["value"] for o in ctl["options"]]
    labels = [o["label"] for o in ctl["options"]]
    assert values[-1] == PART_OF_ANOTHER_POLICY
    assert labels[-1] == "Part of another policy - not a separate line"
    # The lines this package carries come first.
    assert set(values[:5]) == {"general_liab", "property", "inland_marine", "crime", "employee_benefits"}
    assert len(values) == 15 and len(set(values)) == 15
    assert "Primble" not in res["note"] and "—" not in res["note"]
    assert "Primble" not in (resolution_for(_CODE) or {}).get("note", "")


def test_the_one_door_routes_the_answer_as_a_field_and_the_write_door_takes_it():
    from services.answer_routing import answer_mode, can_write_scalar
    from services.arq_service import _canonical_key
    assert _canonical_key(PART_LINES_FACT) == PART_LINES_FACT
    assert answer_mode(PART_LINES_FACT, {})["mode"] == "field"
    assert can_write_scalar(PART_LINES_FACT, {PART_LINES_FACT: {"value": "x"}})


@pytest.mark.parametrize("name", ["Kidnap and Ransom", "No Fault Coverage", "Unknown Hazards",
                                  "N/A Endorsement", "Later Discovery Extension", "Skip Tracing",
                                  "None Of The Above Coverage"])
def test_every_choice_the_window_offers_is_accepted_whatever_the_part_is_called(name):
    """A person's answer is never refused: the stored text carries a hashed key, never the
    printed words, so no answer reader can read a part's NAME as "not known" or "none"."""
    from routes.audit_routes import _validate_producer_answer
    from services.answer_semantics import VALUE, interpret_answer
    key = part_key(name)
    for opt in part_line_choices():
        text = format_part_lines({key: opt["value"]})
        assert _validate_producer_answer(PART_LINES_FACT, text) == (True, ""), (name, opt)
        interp = interpret_answer(PART_LINES_FACT, text)
        assert interp.intent == VALUE and interp.value == text, (name, opt, interp)


def test_the_stored_text_round_trips_and_garbage_is_not_an_answer():
    k1, k2 = part_key("Kidnap & Ransom"), part_key("Widget Protection")
    assert k1 == part_key("Kidnap and Ransom")                 # one part, two printings
    text = format_part_lines({k2: "crime", k1: PART_OF_ANOTHER_POLICY})
    assert text == f"{min(k1, k2)}={'crime' if min(k1, k2) == k2 else PART_OF_ANOTHER_POLICY}; " \
                   f"{max(k1, k2)}={'crime' if max(k1, k2) == k2 else PART_OF_ANOTHER_POLICY}"
    assert parse_part_lines({"value": text, "source": "producer"}) == {k1: PART_OF_ANOTHER_POLICY, k2: "crime"}
    assert is_valid_part_lines(text)
    for bad in ("", "cyber", f"{k1}=marine stuff", "abc=cyber", f"{k1}=cyber; junk"):
        assert not is_valid_part_lines(bad), bad


def test_an_answer_places_its_part_and_a_partial_answer_keeps_the_same_card():
    facts = _multi_line_facts()
    first = unmapped_line_issue(facts)
    k = part_key("Kidnap and Ransom")
    facts[PART_LINES_FACT] = {"value": format_part_lines({k: "crime"}), "source": "producer"}
    assert unmapped_material_lines(facts["coverage_lines"], facts[PART_LINES_FACT]) == ["Widget Protection"]
    partial = unmapped_line_issue(facts)
    assert partial["message"] == first["message"]             # same card, same id
    parts = partial["resolution"]["controls"][PART_LINES_FACT]["parts"]
    assert {p["label"]: p["value"] for p in parts} == {"Kidnap and Ransom": "crime", "Widget Protection": ""}
    facts[PART_LINES_FACT] = {"value": format_part_lines({k: "crime", part_key("Widget Protection"):
                                                          PART_OF_ANOTHER_POLICY}), "source": "producer"}
    assert unmapped_line_issue(facts) is None


def test_the_review_door_redraws_the_card_from_the_facts():
    old = {"code": _CODE, "severity": "advisory", "message": "Coverage part not recognised: X. "
           "Primble has no normalization rule ...", "forms": []}
    other = {"code": "legacy_fein_format", "severity": "soft_warning", "message": "FEIN format", "forms": []}
    facts = _multi_line_facts()
    out = refresh_unmapped_line_issue([old, other], facts)
    assert [i["code"] for i in out] == ["legacy_fein_format", _CODE]
    assert out[1]["message"].startswith("Choose the line for these coverage parts")
    # Every part answered: the stored copy goes.
    facts[PART_LINES_FACT] = format_part_lines({part_key("Kidnap and Ransom"): "crime",
                                                part_key("Widget Protection"): "property"})
    assert [i["code"] for i in refresh_unmapped_line_issue([old, other], facts)] == ["legacy_fein_format"]
    # A view that cannot see the rows does not judge them.
    assert refresh_unmapped_line_issue([old], {"applicant_name": "x"}) == [old]
    assert refresh_unmapped_line_issue([old], None) == [old]
    # Through the door the Review screen uses: no card text from before, and the input.
    view = grouped_with_package_caps([old, other], [], ["FEIN format"], {}, facts=_multi_line_facts())
    items = [it for tier in view["warnings"].values() for c in tier for it in c["items"]]
    card = next(it for it in items if it["code"] == _CODE)
    assert card["resolution"]["controls"][PART_LINES_FACT]["control"] == "part_lines"
    assert all("Primble" not in it["message"] for it in items)


# ── 4. Saved through the real route, honoured, and "Open again" takes it back ──
def _session_with_part():
    row = _row(generated_forms={}, selected_form_ids=[])
    row["facts"]["coverage_lines"] = _multi_line_facts()["coverage_lines"]
    row["structured_issues"] = [unmapped_line_issue(row["facts"])]
    s = _Session(row)
    s.recalc()
    return s


def _review_items(body):
    gi = body.get("grouped_issues") or {}
    out = []
    for c in (gi.get("hard_stops") or []):
        out += c.get("items") or []
    for tier in (gi.get("warnings") or {}).values():
        for c in tier or []:
            out += c.get("items") or []
    return out


def test_the_choice_is_saved_honoured_and_open_again_restores_it():
    s = _session_with_part()
    card = s.store["structured_issues"][0]
    issue_id = build_grouped_view([card], [], [])["warnings"]["binder_followup"][0]["items"][0]["issue_id"]
    before_score = s.score()
    value = format_part_lines({part_key("Kidnap and Ransom"): "crime",
                               part_key("Widget Protection"): PART_OF_ANOTHER_POLICY})
    out = s.fix(issue_id, mode="field", field=PART_LINES_FACT, value=value, code=_CODE)
    assert out["success"] is True, out
    saved = s.store["facts"][PART_LINES_FACT]
    assert saved["value"] == value and saved["source"] == "producer"
    assert unmapped_material_lines(s.store["facts"]["coverage_lines"], saved) == []
    assert not [it for it in _review_items(out) if it["code"] == _CODE]   # the card is gone
    assert s.score() == before_score                                       # advice only
    assert PART_LINES_FACT in undo.load_receipts(s.store)[issue_id]["facts"]

    back = s.reopen(issue_id, code=_CODE)
    assert back["cleared"] is True
    assert PART_LINES_FACT not in s.store["facts"]
    again = [it for it in _review_items(back) if it["code"] == _CODE]
    assert len(again) == 1 and again[0]["issue_id"] == issue_id           # the same card, back
    assert again[0]["resolution"]["mode"] == "field"
    assert s.score() == before_score


def test_the_card_never_enters_a_stop_list_so_no_score_moves():
    s = _session_with_part()
    messages = [i["message"] for i in s.store["structured_issues"] if i.get("code") == _CODE]
    for m in messages:
        assert m not in (s.store.get("hard_stops") or []) and m not in (s.store.get("soft_stops") or [])


# ── 5. The window composes the answer (under node) ────────────────────────────
@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_window_composes_one_answer_and_keeps_earlier_ones(tmp_path):
    k1, k2, k3 = part_key("Kidnap and Ransom"), part_key("Widget Protection"), part_key("Gone Part")
    ctl = {"control": "part_lines", "parts": [{"key": k1, "label": "Kidnap and Ransom", "value": "crime"},
                                              {"key": k2, "label": "Widget Protection", "value": ""}],
           "keep": {k3: "cyber"}}
    script = tmp_path / "check.mjs"
    script.write_text(
        f"import * as P from {json.dumps(_PART_LINES_JS.as_uri())};\n"
        f"const ctl = {json.dumps(ctl)};\n"
        "const saved = P.partPicks(ctl, undefined);\n"
        "const picked = { ...saved, [ctl.parts[1].key]: 'property' };\n"
        "const text = P.composePartLines(ctl, picked);\n"
        "const cleared = P.composePartLines(ctl, { ...picked, [ctl.parts[0].key]: '' });\n"
        "console.log(JSON.stringify({ saved, text, cleared, back: P.partPicks(ctl, text),\n"
        "  left: P.partsLeft(ctl, saved), leftAfter: P.partsLeft(ctl, picked) }));\n",
        encoding="utf-8")
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    o = json.loads(run.stdout)
    assert o["saved"] == {k1: "crime", k2: ""}
    assert o["text"] == format_part_lines({k1: "crime", k2: "property", k3: "cyber"})
    assert o["cleared"] == format_part_lines({k2: "property", k3: "cyber"})
    assert is_valid_part_lines(o["text"])
    assert o["back"] == {k1: "crime", k2: "property"}
    assert (o["left"], o["leftAfter"]) == (1, 0)


def test_the_window_renders_the_part_lines_control():
    src = _MODAL.read_text(encoding="utf-8")
    assert "ctl.control === 'part_lines'" in src and "composePartLines" in src
    assert "—" not in src.split("ctl.control === 'part_lines'")[1].split("const opts")[0]


# ── 6. The sweep: no review-only card ends at "we have nothing" ───────────────
_DEAD_END = ("Primble can't", "can't tell", "No value can be typed", "can't be applied",
             "could not be matched", "no normalization rule", "Check the source document")


def test_no_review_note_claims_we_have_nothing():
    notes = {code: (res or {}).get("note") or ""
             for src in (RESOLUTION_MAP, _LEGACY_CODE_RESOLUTIONS) for code, res in src.items()}
    notes["source_conflict (nested)"] = _CONFLICT_REVIEW_NOTE
    bad = {c: n for c, n in notes.items() if any(p.lower() in n.lower() for p in _DEAD_END)}
    assert not bad, bad
    assert "—" not in "".join(notes.values())
    modal = _MODAL.read_text(encoding="utf-8")
    assert "can't be fixed by entering a single value" not in modal


def test_the_acv_advisory_offers_the_valuation_choice():
    res = resolution_for("acv_high_value_building")
    assert res["mode"] == "field" and res["facts"] == ["valuation_method"]
    assert "Replacement Cost" in res["controls"]["valuation_method"]["options"]


@pytest.mark.parametrize("code,line", [("crime_silent_exposure", "Crime"),
                                       ("cyber_silent_exposure", "Cyber")])
def test_a_coverage_gap_card_names_the_document_that_clears_it(code, line):
    note = resolution_for(code)["note"]
    assert f"already carries {line} coverage" in note and "declarations page" in note
    assert "Add documents" in note


def test_every_none_card_still_says_something():
    for src in (RESOLUTION_MAP, _LEGACY_CODE_RESOLUTIONS):
        for code, res in src.items():
            if (res or {}).get("mode") == "none" and not (res or {}).get("add_forms"):
                assert (res or {}).get("note") or code in {
                    "contractor_missing_acord186", "acord127_missing_state_137",
                    "certificate_requested_but_acord25_missing",
                    "property_evidence_requested_but_acord28_missing", "acord125_missing",
                }, code
