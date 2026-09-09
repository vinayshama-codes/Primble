"""UI-04 (client, 2026-09-09): a "treated as equivalent" row must say WHY.

The Submission Integrity card asserted that two visibly different values were
the same fact and gave no reason. The reason existed all along -
`check_doc_consistency` tags every notice with the rule that produced it
(`code=effective_date_normalized`) - and TWO separate parsers stripped that
token before it reached the browser.

These tests pin the three things that fix depends on:

  1. Every `[info]` notice resolves a non-empty normalization category.
  2. The category is DERIVED from the same dispatch that decided the values
     were equal, so a new identity field gets a label without anyone adding a
     row to a table.
  3. Nothing that was working moved - the door still returns message strings,
     and every message is byte-identical to the old inline strip.

Plus the anti-rot guard: a NEW `[info]` emitter cannot land without coming
through the one parser. That is the standing lesson from the cap-gate
harvester (four unfixable blockers shipped green because the harvester walked
one emission path and the gates used another).
"""
from __future__ import annotations

import io
import os
import re

import pytest

from services.normalization import (
    equivalence_category,
    NAME_FIELDS, DATE_FIELDS, ENTITY_TYPE_FIELDS, ADDRESS_FIELDS,
    CARRIER_FIELDS, FEIN_FIELDS, VALUATION_METHOD_FIELDS,
)
from services.sqs_service import (
    check_doc_consistency,
    split_doc_consistency_issues,
    parse_normalization_notice,
    _INFO_VALUE_SEP,
)

HERE = os.path.dirname(os.path.abspath(__file__))
SQS_SRC = os.path.join(HERE, "..", "services", "sqs_service.py")
PIPELINE_SRC = os.path.join(HERE, "..", "services", "extraction_pipeline.py")
ACORD_MODAL = os.path.join(
    HERE, "..", "..", "frontend", "src", "components", "form", "AcordModal.jsx")


# ── The fixture: the client's own package, printed two ways ──────────────────
# Same values as backend/scripts/make_ui04_test_pdfs.py, so a failure here and
# a failure on the live kit are the same failure.

DEC_FACTS = {
    "applicant_name":    "ORBIN CONTRACTING LLC",
    "entity_type":       "LLC",
    "mailing_address":   "4600 DAHLIA ST STE D13, DENVER, CO 80216",
    "physical_address":  "4600 DAHLIA ST STE D13, DENVER, CO 80216",
    "fein":              "84-2210987",
    "effective_date":    "09/23/26",
    "expiration_date":   "09/23/27",
    "lines_of_business": ["Commercial General Liability", "Commercial Automobile"],
}
APP_FACTS = {
    "applicant_name":    "Orbin Contracting, LLC",
    "entity_type":       "Limited Liability Company",
    "mailing_address":   "4600 Dahlia Street, Suite D13, Denver, Colorado 80216",
    "physical_address":  "4600 Dahlia Street, Suite D13, Denver, Colorado 80216",
    "fein":              "84-2210987",
    "effective_date":    "9/23/2026",
    "expiration_date":   "9/23/2027",
    "lines_of_business": ["General Liability", "Automobile Liability"],
}


def _docs():
    return [
        {"doc_id": "1", "filename": "dec.pdf", "doc_type": "declarations_page",
         "facts": dict(DEC_FACTS), "text": ""},
        {"doc_id": "2", "filename": "app.pdf", "doc_type": "acord_form",
         "facts": dict(APP_FACTS), "text": ""},
    ]


def _info_issues():
    return [i for i in check_doc_consistency(_docs()) if i.startswith("[info]")]


# ── 1. The fixture actually produces the rows this file is about ─────────────

def test_the_fixture_is_not_silently_empty():
    """C25: an empty harvest makes every coverage test below pass vacuously."""
    assert len(_info_issues()) >= 6, (
        "the UI-04 fixture stopped producing equivalence notices - "
        "check_doc_consistency was probably refactored and these tests are "
        "now blind")


def test_the_fixture_raises_no_hard_stop_or_warning():
    """The block must be readable. A red blocker above it is a fixture bug."""
    hard, soft, _info, _c = split_doc_consistency_issues(
        check_doc_consistency(_docs()))
    assert hard == []
    assert soft == []


# ── 2. Every notice names its rule ───────────────────────────────────────────

def test_every_info_notice_resolves_a_category():
    missing = []
    for issue in _info_issues():
        row = parse_normalization_notice(issue)
        assert row is not None, issue
        if not row["category"]:
            missing.append(row["code"])
    assert not missing, (
        "these [info] codes reached the screen with no normalization category, "
        f"so the row says 'treated as equivalent' with no reason: {missing}")


@pytest.mark.parametrize("code,field,category", [
    ("name_normalized",            "applicant_name",    "Name format"),
    ("entity_type_normalized",     "entity_type",       "Accepted terminology"),
    ("mailing_address_normalized", "mailing_address",   "Address format"),
    ("effective_date_normalized",  "effective_date",    "Date format"),
    ("expiration_date_normalized", "expiration_date",   "Date format"),
    ("lob_normalized",             "lines_of_business", "Coverage name"),
])
def test_each_live_code_maps_to_its_fact_and_label(code, field, category):
    row = parse_normalization_notice("[info] code=%s Label: a | b" % code)
    assert row["field"] == field
    assert row["category"] == category


def test_no_category_merely_repeats_its_own_row_label():
    """The client's requirement, made executable.

    The ask was to say WHAT RULE made two visibly different values the same.
    A pill that only echoes the row's own label ("Entity type: LLC | Limited
    Liability Company [Entity type]") answers nothing - the reader already had
    that word. Caught auditing the first live run, not by a test, which is why
    there is now a test.
    """
    offenders = []
    for issue in _info_issues():
        row = parse_normalization_notice(issue)
        label_words = set(row["label"].lower().split())
        cat_words = set(row["category"].lower().split())
        if cat_words and cat_words <= label_words:
            offenders.append((row["label"], row["category"]))
    assert not offenders, (
        "these category pills only repeat their own row label, so the row still "
        f"does not say why the values are equivalent: {offenders}")


# ── 3. The category is derived, not listed ───────────────────────────────────

@pytest.mark.parametrize("field_set,expected", [
    (NAME_FIELDS,              "Name format"),
    (DATE_FIELDS,              "Date format"),
    (ENTITY_TYPE_FIELDS,       "Accepted terminology"),
    (ADDRESS_FIELDS,           "Address format"),
    (CARRIER_FIELDS,           "Carrier name"),
    (FEIN_FIELDS,              "ID number format"),
    (VALUATION_METHOD_FIELDS,  "Valuation term"),
])
def test_every_member_of_every_identity_set_is_labelled(field_set, expected):
    """Derived from normalize_value's own dispatch, so the whole set is covered
    the day a key is added to it."""
    for field in field_set:
        assert equivalence_category(field) == expected, field


@pytest.mark.parametrize("field,expected", [
    # Keys in NO explicit set - answered by _infer_field_category's shapes.
    ("retro_date",            "Date format"),
    ("completion_date",       "Date format"),
    ("garaging_address",      "Address format"),
    ("wc_prior_carrier",      "Carrier name"),
    ("certificate_holder",    "Name format"),
    ("subcontractor_name",    "Name format"),
])
def test_a_field_outside_every_set_still_gets_a_label(field, expected):
    assert equivalence_category(field) == expected


def test_an_unknown_field_gets_the_generic_label_never_a_blank():
    """A blank pill reads as a missing value; 'Wording' is the honest answer -
    normalize_general genuinely is what compared it."""
    for field in ("something_nobody_has_added_yet", "", None):
        assert equivalence_category(field) == "Wording"


# ── 4. Nothing that was working moved ────────────────────────────────────────

_LEGACY_TOKEN_RE = re.compile(r"^(?:field|code)=\S+\s*")


def test_message_is_byte_identical_to_the_old_inline_strip():
    """extraction_pipeline used to build the sentence with its own regex. The
    row's `message` must equal that exactly, or every consumer of the text
    silently changes."""
    for issue in _info_issues():
        legacy = _LEGACY_TOKEN_RE.sub("", issue[len("[info]"):].strip())
        assert parse_normalization_notice(issue)["message"] == legacy


def test_the_door_still_returns_message_strings():
    """`split_doc_consistency_issues`' contract is pinned by
    test_sqs_scoring_fixes_20260816 and read as text by doc_consistency_stops."""
    _h, _s, info, _c = split_doc_consistency_issues(check_doc_consistency(_docs()))
    assert info and all(isinstance(m, str) for m in info)
    for m in info:
        assert not m.startswith("code=")
        assert not m.startswith("field=")


def test_parse_returns_none_for_anything_that_is_not_an_info_line():
    for other in ("[hard_stop] code=fein_conflict FEIN differs.",
                  "[warning] field=dba_name DBA differs.",
                  "totally unexpected string", "", None, 12, {}):
        assert parse_normalization_notice(other) is None


def test_a_malformed_info_line_still_yields_a_row():
    """Fails soft: a row with a generic label beats no row at all."""
    row = parse_normalization_notice("[info] no machine token here")
    assert row is not None
    assert row["message"] == "no machine token here"
    assert row["category"] == "Wording"


# ── 5. The values are readable, which is the other half of UI-04 ─────────────

def test_values_split_and_a_value_containing_a_comma_survives_whole():
    """The client's literal case. Comma-joined, 'Orbin Contracting, LLC,
    ORBIN CONTRACTING LLC' is three commas and two values with no way to tell
    where one ends."""
    row = next(r for r in (parse_normalization_notice(i) for i in _info_issues())
               if r["field"] == "applicant_name")
    assert row["values"] == ["ORBIN CONTRACTING LLC", "Orbin Contracting, LLC"]
    assert row["label"] == "Applicant name"


def test_the_legible_separator_is_confined_to_info_rows():
    """Hard stops and warnings are hashed into issue_ids and matched by
    classify_legacy, so their text must not move."""
    src = io.open(SQS_SRC, encoding="utf-8").read()
    start = src.index("def check_doc_consistency")
    end = src.index("\ndef ", start + 10)
    body = src[start:end]

    # Each `issues.append(` starts exactly one emitter, so slicing on it gives
    # one emitter per chunk without having to match parentheses.
    chunks = body.split("issues.append(")[1:]
    assert len(chunks) >= 8, "the emitter scan found almost nothing"
    for chunk in chunks:
        emitter = chunk.split("issues.append(")[0]
        if "_show_values(" in emitter:
            assert "[info]" in emitter, (
                "a [hard_stop]/[warning] emitter uses the legible join - its "
                "text is hashed into an issue_id and must not move:\n" + emitter)


# ── 6. Anti-rot: a new [info] emitter cannot bypass the one parser ───────────

def _info_emit_sites(body: str) -> int:
    body = re.sub(r'"""[\s\S]*?"""', "", body)
    body = "\n".join(ln for ln in body.splitlines()
                     if not ln.lstrip().startswith("#"))
    return len(re.findall(r'\[info\]', body))


# Five sites today: applicant name, the entity_type/mailing/physical address
# loop (one site, three codes), effective date, expiration date, lines of
# business.
_EXPECTED_INFO_SITES = 5


def test_the_number_of_info_emitters_has_not_changed_unnoticed():
    src = io.open(SQS_SRC, encoding="utf-8").read()
    start = src.index("def check_doc_consistency")
    end = src.index("\ndef ", start + 10)
    found = _info_emit_sites(src[start:end])
    assert found == _EXPECTED_INFO_SITES, (
        f"check_doc_consistency now has {found} [info] emitters, not "
        f"{_EXPECTED_INFO_SITES}. A new one is fine - add it to this file's "
        "fixture so its category is proven, then bump _EXPECTED_INFO_SITES. "
        "An emitter nobody drove is an equivalence claim with no reason "
        "behind it, which is the defect UI-04 reported.")


def test_extraction_pipeline_has_no_second_info_parser():
    """The category was computed and discarded because two parsers stripped the
    same token. There must be one."""
    src = io.open(PIPELINE_SRC, encoding="utf-8").read()
    i = src.index('issue.startswith("[info]")')
    branch = src[i:i + 1200]
    assert "parse_normalization_notice" in branch
    assert "re.sub" not in branch, (
        "extraction_pipeline is parsing the [info] token itself again - that "
        "duplication is what threw the category away in the first place")


def test_the_separator_constant_is_shared_not_retyped():
    """`_show_values` joins on it and `parse_normalization_notice` splits on
    it. Two literals would drift and the values would stop splitting."""
    src = io.open(SQS_SRC, encoding="utf-8").read()
    assert src.count('_INFO_VALUE_SEP = ') == 1
    assert _INFO_VALUE_SEP == " | "
    assert 'return " | ".join' not in src


# ── 7. The screen actually renders it ────────────────────────────────────────
#
# A fix in the wrong layer passes every backend test and changes nothing on
# screen. This file has caused that three times in one week, so the component
# is asserted too.

def test_the_card_renders_the_category_and_one_info_icon():
    """Every UI-04 guarantee, followed to where UI-06 moved the row.

    UI-06 extracted the row body into `NormalizationDiffRow` so a verbose row
    can hold local open/closed state. The guarantees are unchanged; only their
    address is. This test asserts BOTH halves so neither can quietly lose the
    category, the icon, or the normalization call.
    """
    src = io.open(ACORD_MODAL, encoding="utf-8").read()
    # rindex, not index: the phrase also names the severity chip far above.
    i = src.rindex("Resolved formatting difference")
    block = src[i:i + 1200]
    assert "InfoTip" in block, "the heading lost its explanation icon"
    # One icon on the heading, not one per row (owner ruling 2026-08-27).
    assert block.count("<InfoTip") == 1
    assert "NormalizationDiffRow" in block, (
        "the equivalence rows are no longer rendered through their component")

    j = src.index("function NormalizationDiffRow")
    row_fn = src[j:j + 3000]
    assert "treated as equivalent" in row_fn, "the row lost its outcome wording"
    assert "row.category" in row_fn, "the row no longer prints its category"
    assert "<InfoTip" not in row_fn, "an icon per row is the 2026-08-27 clutter"

    # The rows still go through the normalizer before they are rendered.
    k = src.index("const normalizedRows")
    assert "normalizationRow" in src[k:k + 400], (
        "the rows are not being normalized before render")


def test_the_card_still_accepts_a_legacy_string_payload():
    """A session open across a deploy must keep its block, not lose it."""
    src = io.open(ACORD_MODAL, encoding="utf-8").read()
    i = src.index("function normalizationRow")
    fn = src[i:i + 1200]
    assert 'typeof entry === "object"' in fn
    assert "String(entry" in fn


# ── 8. The same rows survive a browser refresh ───────────────────────────────
#
# `/extraction-result` restores a session after F5 and its docstring promises
# "the same shape as the synchronous upload response". `normalized_differences`
# was only ever built on the UPLOAD path, so a refresh emptied the block and
# dropped its chip. These pin the recompute against the upload path it mirrors.

from services.sqs_service import doc_consistency_normalizations   # noqa: E402

FORM_ROUTES_SRC = os.path.join(HERE, "..", "routes", "form_routes.py")


def _session(docs=None, confirmations=None):
    return {
        "docs": _docs() if docs is None else docs,
        "underwriting_confirmations": confirmations or {},
    }


def _upload_path_rows(docs, confirmed=None):
    """What extraction_pipeline's [info] branch builds, expressed directly."""
    return [r for r in (parse_normalization_notice(i)
                        for i in check_doc_consistency(docs, confirmed or set()))
            if r is not None]


def test_a_refresh_returns_exactly_what_the_upload_returned():
    """The whole point of the fix. Not 'something' - the same rows."""
    assert doc_consistency_normalizations(_session()) == _upload_path_rows(_docs())


def test_the_refresh_rows_are_every_row_the_card_draws():
    """Seven here, six on the live kit: this fixture also states a separate
    physical_address, so the address loop's third code is covered. The kit's
    PDFs print only a mailing address, which is the ordinary shape."""
    rows = doc_consistency_normalizations(_session())
    assert [r["field"] for r in rows] == [
        "applicant_name", "entity_type", "mailing_address", "physical_address",
        "effective_date", "expiration_date", "lines_of_business",
    ]
    assert all(r["category"] for r in rows)


def test_one_document_cannot_disagree_with_itself():
    assert doc_consistency_normalizations(_session(docs=_docs()[:1])) == []
    assert doc_consistency_normalizations(_session(docs=[])) == []


def test_an_excluded_document_is_dropped_exactly_as_the_upload_path_drops_it():
    docs = _docs()
    docs[1]["excluded"] = True
    assert doc_consistency_normalizations(_session(docs=docs)) == []


def test_all_excluded_falls_back_to_every_document():
    """`active_docs`' own rule: `[not excluded] or processed_docs`. Mirroring
    the upload path means mirroring this too, odd as it looks."""
    docs = _docs()
    for d in docs:
        d["excluded"] = True
    assert len(doc_consistency_normalizations(_session(docs=docs))) == 7


def test_a_document_with_no_facts_is_dropped_instead_of_crashing():
    docs = _docs() + [{"doc_id": "3", "filename": "junk.pdf"},
                      {"doc_id": "4", "filename": "junk2.pdf", "facts": None}]
    assert doc_consistency_normalizations(_session(docs=docs)) == _upload_path_rows(_docs())


@pytest.mark.parametrize("session", [
    None, {}, {"docs": None}, {"docs": "not a list"},
    {"docs": ["not a dict", 7, None]},
    {"docs": [{"facts": {}}, {"facts": {}}]},
    {"docs": None, "underwriting_confirmations": "nonsense"},
])
def test_a_malformed_session_returns_an_empty_list_never_an_exception(session):
    """Fails open to [] - which is what this endpoint returned before the fix,
    so the worst case of the change is the behaviour it replaces."""
    assert doc_consistency_normalizations(session) == []


def test_a_confirmed_fact_does_not_reappear_after_a_refresh():
    """The producer settled it in Data Consistency; a refresh must not show it
    again as an unresolved-looking equivalence."""
    rows = doc_consistency_normalizations(
        _session(confirmations={"entity_type": "LLC"}))
    assert "entity_type" not in [r["field"] for r in rows]
    assert len(rows) == 6          # the seven, less the confirmed one


def test_a_line_scoped_confirmation_still_counts():
    """SYS-06 stores a line-scoped resolution as `effective_date@auto`.
    doc_consistency_stops compares RAW keys and would miss it; this path
    reduces with parse_confirmation_key, like the upload path does."""
    rows = doc_consistency_normalizations(
        _session(confirmations={"effective_date@auto": "9/23/2026"}))
    assert "effective_date" not in [r["field"] for r in rows]


def test_the_reload_endpoint_actually_returns_the_key():
    """A fix in the wrong layer changes nothing on screen. The endpoint is the
    layer the refreshed page reads."""
    src = io.open(FORM_ROUTES_SRC, encoding="utf-8").read()
    i = src.index('@router.get("/api/session/{session_id}/extraction-result")')
    body = src[i:src.index("\n@router.", i + 10)]
    assert '"normalized_differences"' in body, (
        "/extraction-result stopped returning normalized_differences - a "
        "browser refresh empties the Submission Integrity block again")
    assert "doc_consistency_normalizations(" in body


def test_nothing_is_persisted_by_the_recompute():
    """Read-only by construction: the session dict handed in must come back
    untouched, or a refresh could rewrite stored state."""
    import copy
    session = _session()
    before = copy.deepcopy(session)
    doc_consistency_normalizations(session)
    assert session == before


def test_the_reload_endpoint_really_returns_the_rows():
    """Through the ENTRY POINT, not the helper.

    The source grep above proves the line exists; this proves the response the
    refreshed page actually receives carries the rows. A fix asserted only at
    the primitive has passed while the screen stayed broken three times in this
    codebase - hence both.
    """
    import asyncio
    import json
    import routes.form_routes as FR

    session = {
        "session_id": "s1", "user_id": "42",
        "docs": _docs(), "primary_doc": "dec.pdf",
        "underwriting_confirmations": {},
        "facts": dict(DEC_FACTS), "flags": {},
        "hard_stops": [], "soft_stops": [],
        "integrity": {"status": "high"}, "recommendations": [],
    }

    async def _fake_get(_sid):
        return session

    real = FR.get_processing_session
    FR.get_processing_session = _fake_get
    try:
        resp = asyncio.run(
            FR.get_extraction_result("s1", current_user={"id": 42}))
        body = json.loads(resp.body)
    finally:
        FR.get_processing_session = real

    rows = body.get("normalized_differences")
    assert rows, "a refreshed page receives no equivalence rows"
    assert [r["field"] for r in rows] == [
        "applicant_name", "entity_type", "mailing_address", "physical_address",
        "effective_date", "expiration_date", "lines_of_business",
    ]
    assert all(r["category"] and r["message"] for r in rows)
