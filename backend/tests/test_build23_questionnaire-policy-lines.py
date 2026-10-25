"""Build 23 (22 Oct 2026), lane POLICY - the questionnaire's policy number /
insurer / NAIC answers reach the policy they belong to (25sepChanges.md
Z32-POLICY; open since 17 Sep: "the questionnaire's policy number / carrier
answers still land on no per-line box").

A package holds one RECORD per policy (`services/policy_lines`, "Policies in
this submission"). Every section form's header prints ITS policy's record; the
125 prior-carrier grid reads the records. A questionnaire answer wrote only the
package-level fact (which no section header reads once records exist) and the
client's raw answer went into the header box of EVERY form carrying it.

What this file proves, adversarial cases first:
  1. the answer key: one fact, one policy, no routing word ever smuggled in by
     a carrier's name, never a package fact;
  2. one definition each: the form scan's rule, the header boxes, the line
     families - shared with the code they came from;
  3. the questions: several policies -> one question per policy lacking the
     value on its own section form (NAIC once per company); one policy -> the
     package question, only on the forms its answer reaches; no records ->
     byte-identical;
  4. the judge: non-answers skip, refused values hold (client) / refuse
     (producer), same values do nothing, contradicting values hold a client's
     answer and write a producer's;
  5. end to end on Brent's real package (session ca93ed8f, replayed offline):
     a client's answer lands on its own policy's boxes only, labelled the
     client's; a person-typed box stays; a contradiction is held; a question
     sent before this build no longer sprays every header;
  6. the producer's door ("Use the client's value") and the held list;
  7. the store's provenance; 8. anti-rot.
No database, network or LLM.
"""
import ast
import asyncio
import copy
import inspect
import json
import os
import pathlib
import re
import sys
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

from repositories.session_repository import resolve_facts_write          # noqa: E402
from services import arq_service as arq                                  # noqa: E402
from services import client_answer_review as car                         # noqa: E402
from services import extraction_service as es                            # noqa: E402
from services import pdf_service as ps                                   # noqa: E402
from services import policy_lines as pl                                  # noqa: E402
from services.form_instances import facts_for_form                       # noqa: E402
from services.question_classifier import classify_question               # noqa: E402

BACKEND = pathlib.Path(__file__).resolve().parent.parent
FIXTURE = BACKEND / "tests" / "fixtures" / "choice_electric_pol_6oct.json"
SCHEMAS = BACKEND / "forms_schemas"
CE_FORMS = ["ACORD_125", "ACORD_126", "ACORD_127", "ACORD_131", "ACORD_131__excess"]
AUTO_FORMS = ["ACORD_125", "ACORD_126", "ACORD_127"]
PN, CN, NAIC = "Policy_PolicyNumberIdentifier_A", "Insurer_FullName_A", "Insurer_NAICCode_A"
AMERISURE = "AMERISURE INSURANCE COMPANY"


# ══ Helpers ══════════════════════════════════════════════════════════════════

def _docs():
    return copy.deepcopy(json.loads(FIXTURE.read_text(encoding="utf-8"))["docs"])


def _merge(docs):
    return es.merge_facts(docs, es.select_primary_truth(docs))


def _schema(fid):
    return json.loads((SCHEMAS / f"{fid.split('__')[0]}_schema.json").read_text(encoding="utf-8"))


def _generate(form_ids, facts, flags, docs):
    """Generation's own engine, box by box (no LLM): a box the engine leaves
    blank is labelled low_confidence, as `map_facts_to_form` labels it."""
    text = "\n".join(str(d.get("text") or "") for d in docs)
    out = {}
    for fid in form_ids:
        base = fid.split("__")[0]
        schema = _schema(fid)
        ctx = {**facts_for_form(facts, fid), **flags, "_form_id": base,
               "_package_form_ids": list(form_ids)}
        state, conf = {}, {}
        hay = [None]
        with ps._schema_context(schema):
            for box in schema:
                if ps._is_nonfillable_field(box):
                    raw = ps.nonfillable_box_value(box, ctx, schema, text, hay)
                else:
                    raw = ps._deterministic_map(box, ctx)
                    if raw == "UNMATCHED" or raw is ps._SCHED_SKIP:
                        raw = None
                if raw in (None, ""):
                    conf[box] = "low_confidence"
                    continue
                state[box] = str(ps.display_value_for_box(base, box, raw, facts=ctx) or "").strip()
                conf[box] = "filled"
        out[fid] = {"schema": schema, "field_state": state, "mapped": dict(state),
                    "confidence": conf, "client_filled_fields": []}
    return out


class _FakeDB:
    """The session row: `upd_processing_session`'s merge rules, no database."""

    def __init__(self, session):
        self.row = copy.deepcopy(session)

    async def get(self, _sid):
        return copy.deepcopy(self.row)

    async def upd(self, _sid, updates, delete_facts=None):
        for k, v in updates.items():
            if k == "generated_forms":
                gen = self.row.setdefault("generated_forms", {})
                for fid, form in v.items():
                    if fid in gen:
                        gen[fid].update(copy.deepcopy(form))
                    else:
                        gen[fid] = copy.deepcopy(form)
            elif k == "facts" and isinstance(v, dict):
                self.row["facts"] = resolve_facts_write(self.row, copy.deepcopy(v))
            else:
                self.row[k] = copy.deepcopy(v)
        for fk in delete_facts or []:
            (self.row.get("facts") or {}).pop(fk, None)


def _session(facts, flags, docs, gen, **extra):
    return {"user_id": "u1", "docs": copy.deepcopy(docs), "facts": copy.deepcopy(facts),
            "flags": dict(flags), "generated_forms": copy.deepcopy(gen),
            "selected_form_ids": [f.split("__")[0] for f in gen], **extra}


def _patched(db):
    return (patch("repositories.session_repository.get_processing_session", db.get),
            patch("repositories.session_repository.upd_processing_session", db.upd))


def _client_apply(db, answers, questions):
    arq_row = {"id": "arq-1", "status": "submitted", "session_id": "s1",
               "answers": answers, "questions": questions}
    g, u = _patched(db)
    with patch.object(arq, "get_arq_by_id", AsyncMock(return_value=arq_row)), g, u:
        ok, updated = asyncio.run(arq.apply_arq_answers_to_session("arq-1", "s1"))
    assert ok
    return updated


def _producer_apply(db, field, value):
    g, u = _patched(db)
    with g, u:
        return asyncio.run(arq.apply_producer_answer_to_session("s1", field, value))


async def _no_humanizing(_names):
    return {}


def _questions(facts, flags, gen, docs):
    with patch.object(arq, "_humanize_fields_with_openai", _no_humanizing):
        return asyncio.run(arq.generate_arq_questions(facts, flags, gen, [], [],
                                                      session_docs=docs))


def _identity_questions(questions):
    return [q for q in questions if pl.is_answer_key(q["field_name"])
            or q["field_name"] in pl.HEADER_BOXES.values() or q["field_name"] in pl.ANSWER_FACTS]


def _synthetic(rows, **facts):
    out = {"coverage_lines": copy.deepcopy(rows), **facts}
    es._build_scoped_fact_store(out, None)
    return out


def _ctx(facts):
    return pl.answer_context({"facts": facts, "docs": [], "generated_forms": {"ACORD_125": {}}})


def _rows_by_line(facts):
    """{line: row} - an umbrella-family line by its LAYER key ("umbrella",
    "umbrella~excess") so two layers never collapse into one."""
    return {pl._scope(r): r for r in pl.question_rows(facts)}


def _box(gen, fid, box):
    form = gen[fid]
    return (form["field_state"].get(box) or ""), form["confidence"].get(box)


def _with_store_edit(facts, edit_key, fields, source=None, docs=None):
    """`facts` with a stored edit APPLIED - as the table's door leaves them."""
    out = copy.deepcopy(facts)
    out[pl.STORE_KEY] = pl.store_with_edit(pl.read_store(out), edit_key, fields,
                                           pl.anchor_for(out, edit_key), "u1", source=source)
    pl.apply_producer_policy_lines(out, None, docs, force=True)
    return out


# ══ Fixtures (the client's own package, replayed) ════════════════════════════

@pytest.fixture(scope="module")
def ce():
    docs = _docs()
    mf, flags = _merge(docs)
    return mf, flags, docs


@pytest.fixture(scope="module")
def ce_gen(ce):
    mf, flags, docs = ce
    return _generate(CE_FORMS, mf, flags, docs)


@pytest.fixture(scope="module")
def ce_questions(ce, ce_gen):
    mf, flags, docs = ce
    return _questions(mf, flags, copy.deepcopy(ce_gen), docs)


@pytest.fixture(scope="module")
def auto1():
    docs = [d for d in _docs() if "Business Auto" in d["filename"]]
    mf, flags = _merge(docs)
    return mf, flags, docs


@pytest.fixture(scope="module")
def auto1_gen(auto1):
    mf, flags, docs = auto1
    return _generate(AUTO_FORMS, mf, flags, docs)


# ══ 1. The answer key ════════════════════════════════════════════════════════

_ROW = {"edit_key": "auto#unnumbered", "line": "auto", "layer": None}


@pytest.mark.parametrize("fact", pl.ANSWER_FACTS)
def test_a_key_names_one_fact_one_policy_and_round_trips(fact):
    key = pl.answer_key(fact, _ROW)
    assert pl.parse_answer_key(key) == (fact, "auto", pl._digest("auto#unnumbered"))
    assert pl.is_answer_key(key) and pl.answer_fact(key) == fact
    other = pl.answer_key(fact, {**_ROW, "edit_key": "auto#BA1"})
    assert other != key                                       # another policy, another key
    exc = pl.answer_key(fact, {"edit_key": "umbrella~excess#unnumbered", "line": "umbrella",
                               "layer": "excess"})
    assert pl.parse_answer_key(exc)[1] == "umbrella~excess"


@pytest.mark.parametrize("key", [
    None, "", "policy_number", "Policy_PolicyNumberIdentifier_A",
    "insurer_policy::premium::auto::0123456789",              # not one of the three facts
    "insurer_policy::policy_number::auto::012345678",         # digest too short
    "insurer_policy::policy_number::auto::0123456789a",       # too long
    "insurer_policy::policy_number::auto::0123456789::x",     # an extra segment
    "insurer_policy::policy_number::AUTO::0123456789",        # not a line scope
    "insurer_policy::policy_number::auto#unnumbered::0123456789",
    "INSURER_POLICY::policy_number::auto::0123456789",
    "schedule::auto_vin_schedule", "premises_interest@loc2",
])
def test_anything_else_is_not_a_policy_answer(key):
    assert pl.parse_answer_key(key) is None and not pl.is_answer_key(key)
    assert pl.answer_fact(key) is None


@pytest.mark.parametrize("edit_key", [
    "auto#unnumbered@FAXONINSURANCE", "general_liab#unnumbered@PRODUCERSNATIONALCORP",
    "property#AGENCYPOL1", "workers_comp#unnumbered@SICCODEMUTUAL", "cyber#TEL123",
])
def test_a_carrier_name_never_reaches_the_field_name(edit_key):
    """The record's id can carry a company's name ("@FAXON..."); the key carries
    only its digest, so no routing word ("fax", "producer", "agency", "sic",
    "tel") can ride in on it."""
    line = edit_key.split("#")[0]
    for fact in pl.ANSWER_FACTS:
        key = pl.answer_key(fact, {"edit_key": edit_key, "line": line})
        assert re.fullmatch(r"[a-z_:~0-9]+", key), key
        tail = key.split("::")[-1]
        assert re.fullmatch(r"[0-9a-f]{10}", tail)
        assert "fax" not in key and "producer" not in key and "agency" not in key


_SCOPES = [{"edit_key": f"{fam}#unnumbered", "line": fam}
           for fam in ("general_liab", "auto", "umbrella", "workers_comp", "property",
                       "inland_marine", "crime", "cyber", "professional", "epli",
                       "pollution", "directors_officers", "employee_benefits", "liquor")] + \
          [{"edit_key": "umbrella~excess#unnumbered", "line": "umbrella", "layer": "excess"}]


@pytest.mark.parametrize("fact", pl.ANSWER_FACTS)
def test_a_policy_question_is_routed_like_the_box_it_replaces(fact):
    """Same audience, priority and bucket as the header box's own question: a
    per-policy question never becomes a default client question."""
    box = classify_question(pl.HEADER_BOXES[fact], ["ACORD_126"],
                            canonical_key=fact, is_curated_client=True)
    for row in _SCOPES:
        mine = classify_question(pl.answer_key(fact, row), ["ACORD_126"],
                                 canonical_key=None, is_curated_client=False)
        for k in ("audience", "priority", "bucket", "suppressed"):
            assert mine[k] == box[k], (fact, row, k, mine[k], box[k])


def test_a_policy_key_never_resolves_to_a_package_fact():
    for fact in pl.ANSWER_FACTS:
        for row in _SCOPES:
            key = pl.answer_key(fact, row)
            assert arq._canonical_key(key) is None
            assert not (arq._canonical_keys_for(key) & set(pl.ANSWER_FACTS))


def test_the_answer_cleaner_reads_a_policy_key_as_its_fact():
    key = pl.answer_key("policy_number", _ROW)
    assert arq._clean_answer_ex("Policy number: BA-7731042", key) == ("BA-7731042", "")
    assert arq._clean_answer_ex("None", key) == ("None", "")         # an absence, kept
    assert arq._clean_answer_ex("not sure", key) == (None, "")       # never an answer
    assert arq._clean_answer_ex("", key) == (None, "")
    naic = pl.answer_key("carrier_naic", _ROW)
    assert arq._clean_answer_ex("23396", naic) == ("23396", "")
    assert not arq._blocks_submit("text", key)                       # never a 422 trap


# ══ 2. One definition each ═══════════════════════════════════════════════════

def _old_scan_rule(form_id, conf_val, raw_val):
    """The inline rule `generate_arq_questions` carried until 22 Oct, frozen."""
    is_empty = arq._is_empty_arq_value(raw_val)
    if form_id == "ACORD_125":
        return not (conf_val != "missing_required" or not is_empty)
    if conf_val == "missing_required":
        return True
    if conf_val == "low_confidence" and is_empty:
        return True
    if conf_val == "low_confidence" and not is_empty:
        return False
    if conf_val == "filled" and is_empty:
        return True
    return False


@pytest.mark.parametrize("form_id", ["ACORD_125", "ACORD_126", "ACORD_131__excess", ""])
def test_the_scan_rule_is_the_old_inline_rule(form_id):
    for conf_val in ("missing_required", "low_confidence", "filled", "ai_verified",
                     "producer", "client_arq", None, "", "not_applicable"):
        for raw in (None, "", "  ", "null", "None", "x", "0", 0, False):
            assert arq._scan_asks_box(form_id, conf_val, raw) == _old_scan_rule(form_id, conf_val, raw)


def test_header_boxes_are_the_resolvers_identity_boxes():
    for fact, box in pl.HEADER_BOXES.items():
        assert ps._SECTION_IDENTITY_RE.match(box), box
        assert arq._canonical_key(box) == fact
    for fid in ps._SECTION_FORM_LINE_PHRASES:
        schema = _schema(fid)
        assert any(b in schema for b in pl.HEADER_BOXES.values()) or fid == "ACORD_133", fid


def test_section_families_are_the_header_resolvers():
    from services.lob_canon import canon_line
    for fid, phrases in ps._SECTION_FORM_LINE_PHRASES.items():
        want = {canon_line(p) for p in phrases} - {None}
        assert pl.section_families(fid) == want, fid
        assert pl.is_section_form(fid) == bool(want)
    for fid in ("ACORD_125", "ACORD_101", "ACORD_25", "", None, "ACORD_999"):
        assert pl.section_families(fid) == frozenset() and not pl.is_section_form(fid)
    assert pl.section_families("ACORD_131__excess") == pl.section_families("ACORD_131")


# ══ 3. The questions ═════════════════════════════════════════════════════════

def test_no_policy_records_change_nothing():
    """A package with no records (a legacy session, a package with no lines):
    the very same questions come back."""
    qs = [{"field_name": PN, "_canonical_key": "policy_number", "form_ids": ["ACORD_126"],
           "forms": "126"},
          {"field_name": "applicant_name", "_canonical_key": "applicant_name",
           "form_ids": ["ACORD_125"], "forms": "125"}]
    gen = {"ACORD_126": {"schema": {PN: {}}, "field_state": {}, "confidence": {PN: "low_confidence"}}}
    for facts in ({}, {"applicant_name": "X"}, {"coverage_lines": []}):
        before = copy.deepcopy(qs)
        assert pl.questions_by_policy(qs, facts, gen) == before
        assert qs == before


def test_a_package_without_records_gets_todays_questionnaire(auto1, auto1_gen):
    """The real generator, the pass on and off, on a package with no policy
    records: the same questions, in the same order, worded the same."""
    mf, flags, docs = auto1
    facts = {k: v for k, v in mf.items() if k not in ("coverage_lines", "_line_records")}
    assert pl.question_rows(facts) == []
    on = _questions(facts, flags, copy.deepcopy(auto1_gen), docs)
    with patch.object(pl, "questions_by_policy", lambda q, _f, _g: q):
        off = _questions(facts, flags, copy.deepcopy(auto1_gen), docs)
    assert on == off


def test_odd_shapes_never_break_the_pass():
    """A form that is not a dict, no forms at all, a question with no form ids
    or no canonical key: never a crash, and a question about anything else is
    never touched."""
    facts = _synthetic([
        {"line": "General Liability", "carrier": "Acme Mutual Insurance Company", "premium": "$100"},
        {"line": "Business Auto", "carrier": "Zenith Casualty Company", "premium": "$200"}])
    other = {"field_name": "applicant_name", "_canonical_key": "applicant_name",
             "form_ids": ["ACORD_126"]}
    pkg = {"field_name": PN, "_canonical_key": "policy_number", "form_ids": ["ACORD_125"]}
    sec = {"field_name": PN, "_canonical_key": "policy_number", "form_ids": ["ACORD_126"]}
    bare = {"field_name": CN, "_canonical_key": "carrier_name"}
    for gen in ({"ACORD_126": "not a form"}, None, {}, {"ACORD_126": {}}):
        out = pl.questions_by_policy([other, pkg, sec, bare, "junk"], facts, gen)
        assert out[:2] == [other, pkg] and out[0] is other and out[1] is pkg   # untouched
        assert bare in out and "junk" in out
        # a section header with no policy gap is not asked as a package question
        assert sec not in out
    assert pl.questions_by_policy([], facts, {"ACORD_126": {}}) == []


def test_several_policies_are_asked_one_question_each(ce, ce_questions):
    mf, _flags, _docs = ce
    ident = _identity_questions(ce_questions)
    # The package questions that would have sprayed every header are gone.
    assert not [q for q in ident if not pl.is_answer_key(q["field_name"])]
    by_fact = {}
    for q in ident:
        by_fact.setdefault(pl.answer_fact(q["field_name"]), []).append(q)
    ctx = _ctx(mf)
    pn_lines = {pl.answer_row(ctx, q["field_name"])["edit_key"] for q in by_fact["policy_number"]}
    # every policy with a section form in this package and no number of its own
    assert pn_lines == {"general_liab#unnumbered", "auto#unnumbered", "umbrella#unnumbered",
                        "umbrella~excess#unnumbered"}
    for q in ident:
        assert q["audience"] == "producer" and q["bucket"] == "agency"
        assert not q.get("default_selected")
        assert "—" not in q["question"] and "—" not in q["hint"]
    auto = next(q for q in by_fact["policy_number"] if "::auto::" in q["field_name"])
    assert auto["question"] == f"Policy number for Commercial Auto ({AMERISURE})"
    assert auto["form_ids"] == ["ACORD_125", "ACORD_127"]     # its header and the prior grid


def test_each_policy_question_names_the_policy_its_answer_writes(ce, ce_questions):
    mf, _flags, _docs = ce
    ctx = _ctx(mf)
    for q in _identity_questions(ce_questions):
        row = pl.answer_row(ctx, q["field_name"])
        assert row is not None, q["field_name"]
        if pl.answer_fact(q["field_name"]) != "carrier_name":
            assert row["carrier_name"] in q["question"], (q["question"], row["carrier_name"])
    texts = [q["question"] for q in _identity_questions(ce_questions)]
    assert len(texts) == len(set(texts))                      # no two read the same


def test_naic_is_asked_once_per_company(ce, ce_questions):
    mf, _flags, _docs = ce
    naic = [q for q in _identity_questions(ce_questions)
            if pl.answer_fact(q["field_name"]) == "carrier_naic"]
    companies = [pl.answer_row(_ctx(mf), q["field_name"])["carrier_name"] for q in naic]
    assert sorted(companies) == sorted({AMERISURE, "AMERISURE MUTUAL INSURANCE COMPANY",
                                        "TRAVELERS PROPERTY CASUALTY COMPANY OF AMERICA"})
    amerisure = next(q for q in naic if q["question"].startswith(f"NAIC code for {AMERISURE} ("))
    assert "Commercial Auto" in amerisure["question"] and "General Liability" in amerisure["question"]
    assert {"ACORD_126", "ACORD_127"} <= set(amerisure["form_ids"])


def test_the_excess_layer_is_asked_about_its_own_policy(ce, ce_questions):
    mf, _flags, _docs = ce
    exc = [q for q in _identity_questions(ce_questions) if "::umbrella~excess::" in q["field_name"]]
    assert {pl.answer_fact(q["field_name"]) for q in exc} == {"policy_number", "carrier_naic"}
    row = pl.answer_row(_ctx(mf), exc[0]["field_name"])
    assert row["layer"] == "excess"
    assert row["carrier_name"] == "TRAVELERS PROPERTY CASUALTY COMPANY OF AMERICA"
    for q in exc:                                              # listed under its form
        assert q["form_ids"] == ["ACORD_131"]


def test_a_policy_that_states_the_value_is_not_asked(ce, ce_gen):
    mf, flags, docs = ce
    facts = _with_store_edit(mf, "auto#unnumbered", {"policy_number": "BA-7731042"}, docs=docs)
    gen = _generate(["ACORD_125", "ACORD_127"], facts, flags, docs)
    assert gen["ACORD_127"]["field_state"][PN] == "BA-7731042"
    rows = pl.question_rows(facts)
    gaps = pl.identity_gaps(facts, gen, rows)
    assert ("policy_number", "auto#unnumbered") not in gaps
    assert ("carrier_naic", "auto#unnumbered") in gaps
    # ...and the form scan's own answer agrees: a filled box is not a question.
    assert not arq._scan_asks_box("ACORD_127", "filled", "BA-7731042")


def test_a_person_typed_header_is_not_asked(ce, ce_gen):
    mf, _flags, _docs = ce
    gen = copy.deepcopy(ce_gen)
    gen["ACORD_127"]["client_filled_fields"] = [PN]
    gaps = pl.identity_gaps(mf, gen, pl.question_rows(mf))
    assert ("policy_number", "auto#unnumbered") not in gaps


def test_one_policy_keeps_one_package_question_on_its_own_forms(auto1, auto1_gen):
    mf, flags, docs = auto1
    assert [r["edit_key"] for r in pl.question_rows(mf)] == ["auto#unnumbered"]
    ident = _identity_questions(_questions(mf, flags, copy.deepcopy(auto1_gen), docs))
    assert not [q for q in ident if pl.is_answer_key(q["field_name"])]
    by = {q["field_name"]: q for q in ident}
    # The auto header asks; ACORD 126 (no GL policy: its header is blank by the
    # header resolver's own rule) is no longer offered as a place it prints.
    assert by[PN]["form_ids"] == ["ACORD_127"]
    assert by[NAIC]["form_ids"] == ["ACORD_127"]
    assert CN not in by                                       # only the 126's carrier was blank


def test_two_policies_with_one_name_read_apart():
    """Two GL policies of one company lacking numbers (two the producer added):
    the term tells them apart, an ordinal when even the term is the same."""
    def _r(key, eff, exp):
        return {"edit_key": key, "line": "general_liab", "line_label": "General Liability",
                "carrier_name": "Acme Mutual Insurance Company", "policy_number": "",
                "effective_date": eff, "expiration_date": exp}
    rows = [_r("added:a1", "01/01/2026", "01/01/2027"), _r("added:b2", "01/01/2026", "01/01/2027"),
            _r("added:c3", "02/01/2026", "02/01/2027")]
    gaps = {("policy_number", r["edit_key"]): {"row": r, "forms": {"ACORD_126"}} for r in rows}
    texts = [q["question"] for q in pl._policy_questions(gaps, rows, {"ACORD_126": {}})]
    assert len(set(texts)) == 3, texts
    assert texts[2].endswith(", 02/01/2026 to 02/01/2027")
    assert texts[0].endswith(", policy 1") and texts[1].endswith(", policy 2")
    # one company, several policies: ONE NAIC question naming its policies
    gaps = {("carrier_naic", r["edit_key"]): {"row": r, "forms": {"ACORD_126"}} for r in rows}
    qs = pl._policy_questions(gaps, rows, {"ACORD_126": {}})
    assert len(qs) == 1
    assert qs[0]["question"] == "NAIC code for Acme Mutual Insurance Company (General Liability)"


def test_a_policy_naming_no_company_keeps_its_own_naic_question():
    rows = [{"edit_key": "general_liab#GL1", "line": "general_liab", "line_label": "General Liability",
             "carrier_name": "", "policy_number": "GL1"},
            {"edit_key": "auto#BA1", "line": "auto", "line_label": "Commercial Auto",
             "carrier_name": "", "policy_number": "BA1"}]
    gaps = {("carrier_naic", r["edit_key"]): {"row": r, "forms": {"ACORD_126"}} for r in rows}
    assert len(pl._policy_questions(gaps, rows, {})) == 2


# ══ 4. The judge ═════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def two_lines():
    return _synthetic([
        {"line": "Commercial General Liability", "carrier": "Acme Mutual Insurance Company",
         "naic": "11111", "premium": "$1,000"},
        {"line": "Business Auto", "carrier": "Acme Mutual Insurance Company",
         "policy_number": "BA-200", "premium": "$2,000"},
        {"line": "Commercial Umbrella", "carrier": "Zenith Casualty Company", "premium": "$900"},
    ])


def _key(facts, line, fact):
    return pl.answer_key(fact, _rows_by_line(facts)[line])


@pytest.mark.parametrize("value", ["", "   ", "None", "N/A", "don't know", "not sure", "TBD"])
@pytest.mark.parametrize("person", [pl.CLIENT_SOURCE, pl.PRODUCER_SOURCE])
def test_a_non_answer_never_writes_or_clears(two_lines, value, person):
    v = pl.judge(_ctx(two_lines), _key(two_lines, "general_liab", "policy_number"), value, person=person)
    assert v["action"] == pl.SKIP
    v = pl.judge(_ctx(two_lines), _key(two_lines, "auto", "policy_number"), value, person=person)
    assert v["action"] == pl.SKIP                             # BA-200 is never cleared


@pytest.mark.parametrize("fact,value", [
    ("policy_number", "ABC"),                 # no digit
    ("policy_number", "CG 00 01 04 13"),      # an ISO form number
    ("carrier_naic", "1234"),
    ("carrier_naic", "NAIC 12"),
    ("carrier_name", "ISO"),                  # a rating bureau
])
def test_a_value_the_table_refuses_is_held_for_a_client_refused_for_a_producer(two_lines, fact, value):
    line = "umbrella"
    key = _key(two_lines, line, fact)
    held = pl.judge(_ctx(two_lines), key, value, person=pl.CLIENT_SOURCE)
    assert held["action"] == pl.HOLD and held["reason"]
    assert held["label"].startswith(pl._ANSWER_LABEL[fact] + " - ")
    assert pl.judge(_ctx(two_lines), key, value, person=pl.PRODUCER_SOURCE)["action"] == pl.REFUSE


@pytest.mark.parametrize("line,fact,value", [
    ("auto", "policy_number", "BA-200"), ("auto", "policy_number", "ba-200"),
    ("general_liab", "carrier_naic", "11111"), ("general_liab", "carrier_naic", "NAIC #11111"),
    ("general_liab", "carrier_name", "ACME MUTUAL INSURANCE COMPANY"),
])
def test_the_same_value_does_nothing(two_lines, line, fact, value):
    for person in (pl.CLIENT_SOURCE, pl.PRODUCER_SOURCE):
        assert pl.judge(_ctx(two_lines), _key(two_lines, line, fact), value,
                        person=person)["action"] == pl.SAME


@pytest.mark.parametrize("line,fact,value,stated", [
    ("auto", "policy_number", "BA-999", "BA-200"),
    ("general_liab", "carrier_naic", "22222", "11111"),
    ("general_liab", "carrier_name", "Zenith Casualty Company", "Acme Mutual Insurance Company"),
])
def test_a_contradicting_value_holds_a_clients_answer_and_writes_a_producers(two_lines, line, fact,
                                                                           value, stated):
    key = _key(two_lines, line, fact)
    held = pl.judge(_ctx(two_lines), key, value, person=pl.CLIENT_SOURCE)
    assert held["action"] == pl.HOLD and held["source_value"] == stated
    assert pl.judge(_ctx(two_lines), key, value, person=pl.PRODUCER_SOURCE)["action"] == pl.WRITE


def test_another_policys_number_is_held(two_lines):
    """A number two policies share may be one package policy's - the producer
    confirms it; a producer's own answer is their decision."""
    key = _key(two_lines, "general_liab", "policy_number")
    v = pl.judge(_ctx(two_lines), key, "BA-200", person=pl.CLIENT_SOURCE)
    assert v["action"] == pl.HOLD and "BA-200" in v["source_value"]
    assert "Business Auto" in v["reason"] and "package policy" in v["reason"]
    assert pl.judge(_ctx(two_lines), key, "BA-200", person=pl.PRODUCER_SOURCE)["action"] == pl.WRITE
    assert pl.judge(_ctx(two_lines), key, "GL-55", person=pl.CLIENT_SOURCE)["action"] == pl.WRITE


def test_a_held_naic_names_its_company_and_a_refused_value_states_nothing(two_lines):
    v = pl.judge(_ctx(two_lines), _key(two_lines, "umbrella", "carrier_naic"), "1234",
                 person=pl.CLIENT_SOURCE)
    assert v["label"] == "NAIC code - Zenith Casualty Company"
    entry = pl.hold_entry(v, "1234", "k", "arq-9")
    assert entry["source_value"] == "(not stated)" and entry["reason"] == "A NAIC code is 5 digits."
    assert entry["client_value"] == "1234" and entry["arq_id"] == "arq-9" and entry["held_at"]
    assert not [k for k in entry if k == "source"]          # never a fact envelope


def _bare_session(facts):
    """A session after forms with no form boxes: the door's store, records and
    holds, without a re-stamp to wait for."""
    return {"user_id": "u1", "docs": [], "facts": copy.deepcopy(facts), "flags": {},
            "generated_forms": {"ACORD_125": {"schema": {}, "field_state": {}, "confidence": {}}}}


def test_the_door_writes_a_policy_the_producer_added():
    facts = _synthetic([{"line": "Commercial General Liability", "carrier": "Acme Mutual Insurance Company",
                         "policy_number": "GL-100", "premium": "$1,000"}])
    sess = {"facts": facts, "docs": []}
    store, _ = pl.plan_change(sess, "add", line_key="epli",
                              fields={"carrier_name": "Federal Insurance Company"}, user="u1")
    facts[pl.STORE_KEY] = store
    pl.apply_producer_policy_lines(facts, {}, [], force=True)
    added = next(r for r in pl.question_rows(facts) if r["producer_added"])
    db = _FakeDB(_bare_session(facts))
    g, u = _patched(db)
    with g, u:
        rep = asyncio.run(pl.apply_policy_answers(
            "s1", [(pl.answer_key("policy_number", added), "EPL-55123")], person=pl.CLIENT_SOURCE))
    assert rep["written"] and not rep["held"]
    row = next(r for r in pl.question_rows(db.row["facts"]) if r["producer_added"])
    assert row["policy_number"] == "EPL-55123"


def test_the_door_rejudges_and_holds_a_value_that_arrived_meanwhile(two_lines):
    """The loop judged the policy empty; by the time the door runs, the producer
    typed a number in the table. The client's answer is held, never written."""
    gl = _rows_by_line(two_lines)["general_liab"]
    key = pl.answer_key("policy_number", gl)
    facts = _with_store_edit(two_lines, gl["edit_key"], {"policy_number": "GL-TYPED-1"})
    db = _FakeDB(_bare_session(facts))
    g, u = _patched(db)
    with g, u:
        rep = asyncio.run(pl.apply_policy_answers("s1", [(key, "GL-999")], person=pl.CLIENT_SOURCE,
                                                  arq_id="arq-2"))
    assert not rep["written"] and key in rep["held"]
    assert db.row["client_answer_conflicts"][key]["source_value"] == "GL-TYPED-1"
    assert db.row["facts"]["_client_answer_conflicts"][key]["arq_id"] == "arq-2"
    assert _rows_by_line(db.row["facts"])["general_liab"]["policy_number"] == "GL-TYPED-1"


_TRAVELERS = "Travelers Indemnity Company"
_TRAVELERS_AM = "Travelers Indemnity Company of America"


@pytest.fixture()
def sister_companies():
    """Two companies the comparison door reads as one printing, with two NAICs
    (review, 22 Oct 2026): the NAIC question is asked once per company KEY."""
    from services.fact_comparison import values_agree
    assert values_agree("carrier_name", _TRAVELERS, _TRAVELERS_AM)
    assert pl._carrier_group_key(_TRAVELERS) != pl._carrier_group_key(_TRAVELERS_AM)
    facts = _synthetic([
        {"line": "Commercial General Liability", "carrier": _TRAVELERS, "policy_number": "GL-1",
         "premium": "$1,000"},
        {"line": "Business Auto", "carrier": _TRAVELERS_AM, "policy_number": "BA-1",
         "premium": "$2,000"},
    ])
    rows = _rows_by_line(facts)
    return facts, pl.answer_key("carrier_naic", rows["general_liab"]), \
        pl.answer_key("carrier_naic", rows["auto"])


def _naics(facts):
    rows = _rows_by_line(facts)
    return rows["general_liab"]["carrier_naic"], rows["auto"]["carrier_naic"]


def test_sister_companies_get_two_naic_questions(sister_companies):
    facts, _gl, _auto = sister_companies
    rows = pl.question_rows(facts)
    gaps = {("carrier_naic", r["edit_key"]): {"row": r, "forms": {"ACORD_126"}} for r in rows}
    assert len(pl._policy_questions(gaps, rows, {})) == 2
    assert [r["edit_key"] for r in pl.company_rows(rows, rows[0])] == [rows[0]["edit_key"]]


def test_sister_companies_answered_together_keep_their_own_naic(sister_companies):
    facts, gl, auto = sister_companies
    db = _FakeDB(_bare_session(facts))
    g, u = _patched(db)
    with g, u:
        rep = asyncio.run(pl.apply_policy_answers("s1", [(gl, "25658"), (auto, "25666")],
                                                  person=pl.CLIENT_SOURCE))
    assert sorted(rep["written"]) == sorted([gl, auto]) and not rep["held"]
    assert _naics(db.row["facts"]) == ("25658", "25666")


def test_sister_companies_answered_separately_keep_their_own_naic(sister_companies):
    facts, gl, auto = sister_companies
    db = _FakeDB(_bare_session(facts))
    g, u = _patched(db)
    with g, u:
        first = asyncio.run(pl.apply_policy_answers("s1", [(gl, "25658")], person=pl.CLIENT_SOURCE))
        second = asyncio.run(pl.apply_policy_answers("s1", [(auto, "25666")], person=pl.CLIENT_SOURCE))
    assert first["written"] == [gl] and second["written"] == [auto]
    assert not first["held"] and not second["held"]
    assert _naics(db.row["facts"]) == ("25658", "25666")


def test_two_answers_about_one_policy_write_one_edit(two_lines):
    gl = _rows_by_line(two_lines)["general_liab"]
    db = _FakeDB(_bare_session(two_lines))
    g, u = _patched(db)
    with g, u:
        rep = asyncio.run(pl.apply_policy_answers(
            "s1", [(pl.answer_key("policy_number", gl), "GL-55"),
                   (pl.answer_key("carrier_name", gl), "Acme Mutual Insurance Company")],
            person=pl.CLIENT_SOURCE))
    assert rep["written"] == [pl.answer_key("policy_number", gl)]
    assert rep["unchanged"] == [pl.answer_key("carrier_name", gl)]
    edits = pl.read_store(db.row["facts"])["edits"]
    assert list(edits) == [gl["edit_key"]]
    assert edits[gl["edit_key"]]["fields"] == {"policy_number": "GL-55"}


def test_a_prior_terms_number_is_held():
    facts = _synthetic([{"line": "Commercial General Liability", "carrier": "Acme Mutual Insurance Company",
                         "premium": "$1,000"},
                        {"line": "Business Auto", "carrier": "Zenith Casualty Company", "premium": "$900"}],
                       prior_coverage_by_line=[{"line": "General Liability", "policy_no": "GL-OLD 1"}])
    v = pl.judge(_ctx(facts), _key(facts, "general_liab", "policy_number"), "GL-OLD-1",
                 person=pl.CLIENT_SOURCE)
    assert v["action"] == pl.HOLD and "prior term" in v["source_value"]


def test_a_naic_the_documents_print_for_the_company_elsewhere_is_held():
    facts = _synthetic([{"line": "Commercial General Liability", "carrier": "Acme Mutual Insurance Company",
                         "naic": "11111", "premium": "$1,000"},
                        {"line": "Business Auto", "carrier": "Acme Mutual Insurance Company",
                         "premium": "$900"},
                        {"line": "Commercial Umbrella", "carrier": "Zenith Casualty Company",
                         "premium": "$500"}])
    key = _key(facts, "auto", "carrier_naic")
    assert pl.judge(_ctx(facts), key, "33333", person=pl.CLIENT_SOURCE)["action"] == pl.HOLD
    assert pl.judge(_ctx(facts), key, "11111", person=pl.CLIENT_SOURCE)["action"] == pl.WRITE


def test_a_judge_that_fails_keeps_a_clients_answer(two_lines, monkeypatch):
    def _boom(*_a, **_k):
        raise RuntimeError("boom")
    monkeypatch.setattr(pl, "_judge", _boom)
    key = _key(two_lines, "general_liab", "policy_number")
    assert pl.judge(_ctx(two_lines), key, "GL-1", person=pl.CLIENT_SOURCE)["action"] == pl.HOLD
    assert pl.judge(_ctx(two_lines), key, "GL-1", person=pl.PRODUCER_SOURCE)["action"] == pl.REFUSE


def test_a_policy_that_changed_or_left_is_never_guessed(two_lines):
    gone = "insurer_policy::policy_number::general_liab::0000000000"
    assert pl.judge(_ctx(two_lines), gone, "GL-1", person=pl.CLIENT_SOURCE)["action"] == pl.HOLD
    assert pl.judge(_ctx(two_lines), gone, "GL-1", person=pl.PRODUCER_SOURCE)["action"] == pl.REFUSE
    assert pl.judge(None, _key(two_lines, "general_liab", "policy_number"), "GL-1",
                    person=pl.CLIENT_SOURCE)["action"] == pl.HOLD
    # The digest matches but the line does not: still never this policy.
    key = _key(two_lines, "general_liab", "policy_number").replace("::general_liab::", "::auto::")
    assert pl.answer_row(_ctx(two_lines), key) is None


def test_a_package_answer_names_a_policy_only_when_one_is_meant(two_lines, auto1):
    ctx = _ctx(two_lines)
    assert pl.package_target(ctx, "policy_number") is None            # three policies
    assert pl.package_target(ctx, "policy_number", ["ACORD_125", "ACORD_25"]) is None
    assert pl.package_target(ctx, "policy_number", ["ACORD_126"]) == \
        _key(two_lines, "general_liab", "policy_number")              # the 126 names one
    assert pl.package_target(ctx, "policy_number", ["ACORD_126", "ACORD_127"]) is None
    assert pl.package_target(ctx, "applicant_name", ["ACORD_126"]) is None
    assert pl.package_target(None, "policy_number") is None
    mf, _f, _d = auto1
    assert pl.package_target(_ctx(mf), "policy_number") == \
        pl.answer_key("policy_number", pl.question_rows(mf)[0])


# ══ 5. End to end on the client's package ════════════════════════════════════

@pytest.fixture(scope="module")
def answered(ce, ce_gen, ce_questions):
    """The client answers the auto policy's number and Amerisure's NAIC."""
    mf, flags, docs = ce
    gen = copy.deepcopy(ce_gen)
    gen["ACORD_131"]["field_state"][PN] = "TYPED-131"
    gen["ACORD_131"]["confidence"][PN] = "producer"
    db = _FakeDB(_session(mf, flags, docs, gen))
    q_pn = next(q for q in ce_questions if "policy_number::auto::" in q["field_name"])
    q_naic = next(q for q in ce_questions if q["field_name"].startswith("insurer_policy::carrier_naic")
                  and AMERISURE + " (" in q["question"])
    q_typed = next(q for q in ce_questions if "policy_number::umbrella::" in q["field_name"])
    answers = {q_pn["field_name"]: "BA-7731042", q_naic["field_name"]: "NAIC 23396",
               q_typed["field_name"]: "UMB-5550001"}
    updated = _client_apply(db, answers, [q_pn, q_naic, q_typed])
    return db, gen, updated, answers


def test_a_clients_answer_lands_on_its_own_policys_boxes(answered):
    db, before, updated, _answers = answered
    after = db.row["generated_forms"]
    assert _box(after, "ACORD_127", PN) == ("BA-7731042", "client_arq")
    assert PN in after["ACORD_127"]["client_filled_fields"]
    assert after["ACORD_125"]["field_state"]["PriorCoverage_Automobile_PolicyNumberIdentifier_A"] \
        == "BA-7731042"
    assert {"ACORD_125", "ACORD_127"} <= set(updated)
    # NO other policy's header shows the auto number.
    for fid in ("ACORD_125", "ACORD_126", "ACORD_131__excess"):
        assert _box(after, fid, PN)[0] != "BA-7731042", fid


def test_a_naic_answer_reaches_every_policy_of_that_company_and_no_other(answered):
    db, _before, _updated, _answers = answered
    after = db.row["generated_forms"]
    for fid in ("ACORD_126", "ACORD_127"):                     # Amerisure Insurance Company
        assert _box(after, fid, NAIC) == ("23396", "client_arq"), fid
    for fid in ("ACORD_131", "ACORD_131__excess"):             # Amerisure Mutual, Travelers
        assert not _box(after, fid, NAIC)[0], fid
    rows = _rows_by_line(db.row["facts"])
    assert rows["general_liab"]["carrier_naic"] == rows["auto"]["carrier_naic"] == "23396"
    assert rows["workers_comp"]["carrier_naic"] == "23396"
    assert not rows["umbrella"]["carrier_naic"]


def test_the_records_carry_the_clients_values_and_the_package_fact_is_untouched(ce, answered):
    mf, _flags, _docs = ce
    db, _before, _updated, _answers = answered
    facts = db.row["facts"]
    assert facts.get("policy_number") == mf.get("policy_number")
    assert facts.get("carrier_naic") == mf.get("carrier_naic")
    auto = _rows_by_line(facts)["auto"]
    assert auto["policy_number"] == "BA-7731042"
    assert auto["client_fields"] == ["carrier_naic", "policy_number"]
    assert auto["edited_fields"] == []                        # never "Corrected by you"
    store = pl.read_store(facts)
    assert store["edits"]["auto#unnumbered"]["sources"] == {"policy_number": "client_arq",
                                                            "carrier_naic": "client_arq"}
    assert not db.row.get("client_answer_conflicts")


def test_a_person_typed_header_stays(answered):
    db, _before, _updated, _answers = answered
    after = db.row["generated_forms"]
    # The umbrella's answer reached its record, never the box the producer typed.
    assert _box(after, "ACORD_131", PN) == ("TYPED-131", "producer")
    assert _rows_by_line(db.row["facts"])["umbrella"]["policy_number"] == "UMB-5550001"


def test_a_contradicting_answer_is_held_and_nothing_moves(ce, ce_gen, ce_questions):
    mf, flags, docs = ce
    facts = _with_store_edit(mf, "auto#unnumbered", {"policy_number": "BA-1000001"}, docs=docs)
    gen = _generate(["ACORD_125", "ACORD_127"], facts, flags, docs)
    db = _FakeDB(_session(facts, flags, docs, gen))
    q = next(q for q in ce_questions if "policy_number::auto::" in q["field_name"])
    _client_apply(db, {q["field_name"]: "BA-7731042"}, [q])
    held = db.row["client_answer_conflicts"][q["field_name"]]
    assert held["client_value"] == "BA-7731042" and held["source_value"] == "BA-1000001"
    assert held["label"] == f"Policy number - Commercial Auto ({AMERISURE})"
    assert db.row["facts"]["_client_answer_conflicts"][q["field_name"]] == held
    assert db.row["generated_forms"]["ACORD_127"]["field_state"][PN] == "BA-1000001"
    assert pl.read_store(db.row["facts"]) == pl.read_store(facts)
    row = car.build_review_rows(db.row)[0]
    assert row["label"] == held["label"] and row["reason"] == pl._HELD_MISMATCH
    assert row["fact_key"] == q["field_name"]


def test_a_question_sent_before_this_build_no_longer_sprays_every_header(ce, ce_gen):
    """The old package question: `Policy_PolicyNumberIdentifier_A` on 126, 127
    and 131 at once. Its answer is the package's - no section header prints it."""
    mf, flags, docs = ce
    db = _FakeDB(_session(mf, flags, docs, ce_gen))
    q = {"field_name": PN, "form_ids": ["ACORD_126", "ACORD_127", "ACORD_131"]}
    _client_apply(db, {PN: "PKG-123456"}, [q])
    after = db.row["generated_forms"]
    for fid in ("ACORD_126", "ACORD_127", "ACORD_131", "ACORD_131__excess"):
        assert _box(after, fid, PN)[0] != "PKG-123456", fid
    assert db.row["facts"]["policy_number"]["value"] == "PKG-123456"   # the package's fact
    assert not pl.read_store(db.row["facts"])["edits"]


def test_a_question_sent_before_this_build_on_one_policys_form_reaches_it(ce, ce_gen):
    mf, flags, docs = ce
    db = _FakeDB(_session(mf, flags, docs, ce_gen))
    _client_apply(db, {PN: "BA-7731042"}, [{"field_name": PN, "form_ids": ["ACORD_127"]}])
    assert _box(db.row["generated_forms"], "ACORD_127", PN) == ("BA-7731042", "client_arq")
    assert _box(db.row["generated_forms"], "ACORD_126", PN)[0] != "BA-7731042"
    assert _rows_by_line(db.row["facts"])["auto"]["policy_number"] == "BA-7731042"


def test_an_old_question_naming_one_policy_is_held_as_that_policys_answer(ce, ce_questions):
    """Review, 22 Oct: on a package of several policies the hold is keyed by the
    policy's own answer key, never the package fact - "Use the client's value"
    then writes that policy, and two such holds cannot overwrite each other."""
    mf, flags, docs = ce
    facts = _with_store_edit(mf, "auto#unnumbered", {"policy_number": "BA-1000001"}, docs=docs)
    gen = _generate(["ACORD_125", "ACORD_127"], facts, flags, docs)
    db = _FakeDB(_session(facts, flags, docs, gen))
    _client_apply(db, {PN: "BA-7731042"}, [{"field_name": PN, "form_ids": ["ACORD_127"]}])
    key = pl.answer_key("policy_number", _rows_by_line(facts)["auto"])
    held = db.row["client_answer_conflicts"]
    assert list(held) == [key] and "policy_number" not in held
    assert held[key]["field_name"] == PN and held[key]["source_value"] == "BA-1000001"
    assert not db.row["facts"].get("policy_number")                   # nothing written
    g, u = _patched(db)
    with g, u, patch("services.audit_service.log_underwriting_confirmation", AsyncMock()), \
            patch.object(arq, "recalculate_session_scores", AsyncMock(return_value={"ok": True})):
        out = asyncio.run(car.resolve_client_answer("s1", key, car.CHOICE_USE_CLIENT, "u1"))
    assert out["ok"]
    assert _rows_by_line(db.row["facts"])["auto"]["policy_number"] == "BA-7731042"
    assert _box(db.row["generated_forms"], "ACORD_127", PN) == ("BA-7731042", "producer")


# ══ 6. One policy ════════════════════════════════════════════════════════════

def test_one_policys_package_answer_is_that_policys(auto1, auto1_gen):
    mf, flags, docs = auto1
    db = _FakeDB(_session(mf, flags, docs, auto1_gen))
    _client_apply(db, {PN: "BA-7731042"}, [{"field_name": PN, "form_ids": ["ACORD_127"]}])
    facts = db.row["facts"]
    assert facts["policy_number"]["value"] == "BA-7731042"             # the package fact, as before
    assert pl.question_rows(facts)[0]["policy_number"] == "BA-7731042"  # ...and its policy
    gen = db.row["generated_forms"]
    assert _box(gen, "ACORD_127", PN) == ("BA-7731042", "client_arq")
    assert not _box(gen, "ACORD_126", PN)[0]                          # no GL policy


def test_one_policys_package_answer_contradicting_it_is_held(auto1, auto1_gen):
    mf, flags, docs = auto1
    facts = _with_store_edit(mf, "auto#unnumbered", {"policy_number": "BA-1000001"}, docs=docs)
    db = _FakeDB(_session(facts, flags, docs, auto1_gen))
    _client_apply(db, {PN: "BA-7731042"}, [{"field_name": PN, "form_ids": ["ACORD_127"]}])
    held = db.row["client_answer_conflicts"]["policy_number"]
    assert held["client_value"] == "BA-7731042" and held["source_value"] == "BA-1000001"
    assert held["field_name"] == PN
    assert not db.row["facts"].get("policy_number")                   # nothing written


def test_an_absence_answer_writes_no_policy(auto1, auto1_gen):
    mf, flags, docs = auto1
    db = _FakeDB(_session(mf, flags, docs, auto1_gen))
    _client_apply(db, {PN: "None"}, [{"field_name": PN, "form_ids": ["ACORD_127"]}])
    assert not pl.read_store(db.row["facts"])["edits"]
    assert not pl.question_rows(db.row["facts"])[0]["policy_number"]


# ══ 7. The producer's door and the held list ═════════════════════════════════

def test_use_the_clients_value_writes_that_policy(ce, ce_gen, ce_questions):
    mf, flags, docs = ce
    facts = _with_store_edit(mf, "auto#unnumbered", {"policy_number": "BA-1000001"}, docs=docs)
    gen = _generate(["ACORD_125", "ACORD_127"], facts, flags, docs)
    db = _FakeDB(_session(facts, flags, docs, gen))
    q = next(q for q in ce_questions if "policy_number::auto::" in q["field_name"])
    _client_apply(db, {q["field_name"]: "BA-7731042"}, [q])
    assert q["field_name"] in db.row["client_answer_conflicts"]
    g, u = _patched(db)
    with g, u, patch("services.audit_service.log_underwriting_confirmation", AsyncMock()), \
            patch.object(arq, "recalculate_session_scores", AsyncMock(return_value={"ok": True})):
        out = asyncio.run(car.resolve_client_answer("s1", q["field_name"], car.CHOICE_USE_CLIENT, "u1"))
    assert out["ok"] and "ACORD_127" in out["forms_updated"]
    assert _box(db.row["generated_forms"], "ACORD_127", PN) == ("BA-7731042", "producer")
    auto = _rows_by_line(db.row["facts"])["auto"]
    assert auto["policy_number"] == "BA-7731042" and auto["edited_fields"] == ["policy_number"]
    assert not db.row.get("client_answer_conflicts")


def test_a_producer_answer_the_table_refuses_is_refused(ce, ce_gen):
    mf, flags, docs = ce
    db = _FakeDB(_session(mf, flags, docs, ce_gen))
    key = pl.answer_key("policy_number", _rows_by_line(mf)["auto"])
    assert _producer_apply(db, key, "CG 00 01 04 13") == (False, [])
    assert _producer_apply(db, key, "") == (False, [])
    assert not pl.read_store(db.row["facts"])["edits"]


def test_no_answer_about_a_policy_is_written_before_forms(ce):
    mf, flags, docs = ce
    db = _FakeDB({"user_id": "u1", "docs": docs, "facts": copy.deepcopy(mf), "flags": dict(flags),
                  "generated_forms": {}})
    key = pl.answer_key("policy_number", _rows_by_line(mf)["auto"])
    g, u = _patched(db)
    with g, u:
        rep = asyncio.run(pl.apply_policy_answers("s1", [(key, "BA-1")], person=pl.CLIENT_SOURCE))
        rep2 = asyncio.run(pl.apply_policy_answers("s1", [(key, "BA-1")], person=pl.PRODUCER_SOURCE))
    assert not rep["written"] and key in rep["held"]
    assert not rep2["written"] and key in rep2["refused"]
    assert not pl.read_store(db.row["facts"])["edits"]


def test_the_held_list_keeps_its_old_rows_as_they_were():
    held = {"num_employees": {"client_value": "60", "source_value": "45", "field_name": "x"}}
    row = car.build_review_rows({"client_answer_conflicts": held})[0]
    assert row["label"] == car._label_for("num_employees")
    assert "does not match" in row["reason"]


# ══ 8. The store's provenance ════════════════════════════════════════════════

def test_client_sources_survive_a_read_and_a_producer_edit_takes_the_field_back():
    store = pl.store_with_edit(pl.empty_store(), "auto#x", {"policy_number": "BA-1", "carrier_naic": "12345"},
                               {}, "client_arq", source=pl.CLIENT_SOURCE)
    facts = {pl.STORE_KEY: store}
    assert pl.read_store(facts)["edits"]["auto#x"]["sources"] == {"policy_number": "client_arq",
                                                                  "carrier_naic": "client_arq"}
    store2 = pl.store_with_edit(pl.read_store(facts), "auto#x", {"policy_number": "BA-2"}, {}, "u1")
    assert store2["edits"]["auto#x"]["sources"] == {"carrier_naic": "client_arq"}
    store3 = pl.store_with_edit(store2, "auto#x", {"carrier_naic": "54321"}, {}, "u1")
    assert "sources" not in store3["edits"]["auto#x"]
    # junk in the stored sources is dropped on read; no source = the producer's (old stores)
    junk = {pl.STORE_KEY: {"edits": {"auto#x": {"fields": {"policy_number": "BA-1"},
                                                "sources": {"policy_number": "ai", "premium": "client_arq",
                                                            "carrier_name": "client_arq"}}}}}
    assert "sources" not in pl.read_store(junk)["edits"]["auto#x"]
    assert "sources" not in pl.store_with_edit(pl.empty_store(), "k", {"premium": "$1"}, {}, "u1")["edits"]["k"]


def test_a_clients_value_is_not_the_producers(two_lines):
    gl = _rows_by_line(two_lines)["general_liab"]["edit_key"]
    facts = _with_store_edit(two_lines, gl, {"policy_number": "GL-777"}, source=pl.CLIENT_SOURCE)
    row = _rows_by_line(facts)["general_liab"]
    assert row["client_fields"] == ["policy_number"] and row["edited_fields"] == []
    assert not (pl._value_keys("GL-777") & pl.producer_values(facts))
    mine = _with_store_edit(two_lines, gl, {"policy_number": "GL-777"})
    assert pl._value_keys("GL-777") <= pl.producer_values(mine)
    assert _rows_by_line(mine)["general_liab"]["edited_fields"] == ["policy_number"]


def test_the_box_labels_follow_who_supplied_the_value():
    gen = {"ACORD_126": {"field_state": {PN: "GL-777", "Other_A": "x"},
                         "confidence": {PN: "filled", "Other_A": "filled"},
                         "client_filled_fields": ["Other_A"]}}
    before = {"ACORD_126": {PN: ""}}
    assert pl.label_producer_boxes(gen, before, {}, label=pl.CLIENT_SOURCE,
                                   values=pl._value_keys("GL-777")) == ["ACORD_126"]
    assert gen["ACORD_126"]["confidence"][PN] == "client_arq"
    assert set(gen["ACORD_126"]["client_filled_fields"]) == {"Other_A", PN}
    gen2 = {"ACORD_126": {"field_state": {PN: "GL-777"}, "confidence": {PN: "filled"},
                          "client_filled_fields": [PN]}}
    pl.label_producer_boxes(gen2, before, {}, values=pl._value_keys("GL-777"))
    assert gen2["ACORD_126"]["confidence"][PN] == "producer"
    assert gen2["ACORD_126"]["client_filled_fields"] == []


def test_the_clients_values_survive_a_pipeline_rerun(answered, ce):
    db, _b, _u, _a = answered
    _mf, flags, docs = ce
    fresh, fresh_flags = _merge(copy.deepcopy(docs))
    pl.carry_and_apply(fresh, fresh_flags, docs, db.row["facts"])
    auto = _rows_by_line(fresh)["auto"]
    assert auto["policy_number"] == "BA-7731042"
    assert auto["client_fields"] == ["carrier_naic", "policy_number"]


# ══ 9. Anti-rot ══════════════════════════════════════════════════════════════

def _calls(fn, name):
    tree = ast.parse(inspect.getsource(fn).lstrip())
    return [n for n in ast.walk(tree) if isinstance(n, ast.Call)
            and getattr(n.func, "id", getattr(n.func, "attr", "")) == name]


@pytest.mark.parametrize("door", [arq.apply_arq_answers_to_session, arq.apply_producer_answer_to_session])
def test_a_package_answer_never_restamps_a_section_header(door):
    """Every re-stamp of the ANSWERED fact skips the section forms when the
    package has policy records (`skip_forms=`); the derived-fact re-stamps
    (`_dk`) are other facts."""
    own = [c for c in _calls(door, "_restamp_canonical_into_forms")
           if len(c.args) >= 2 and getattr(c.args[1], "id", "") == "canon"]
    assert own, door.__name__
    for c in own:
        assert any(k.arg == "skip_forms" for k in c.keywords), door.__name__


def test_the_client_write_loop_skips_section_forms():
    src = inspect.getsource(arq.apply_arq_answers_to_session)
    loop = src[src.index("for fid, form_data in generated.items():"):]
    # The box write is `_box_val` since the Z33-PERCENT review (22 Oct 2026):
    # an amount-or-percent box prints the door's value for the answer.
    assert loop.index("if _pl_identity and fid in _pl_sections:") < loop.index("field_state[field_name] = _box_val")


def test_the_policy_pass_runs_before_decoration():
    src = inspect.getsource(arq.generate_arq_questions)
    assert src.index("_questions_by_policy(questions, facts, generated_forms)") < \
        src.index("decorate_questions(")
    assert "_scan_asks_box(form_id, conf_val, raw_val)" in src


def test_one_lock_for_the_table_and_the_questionnaire():
    from routes import policy_line_routes as plr
    assert plr._lock_for("s-lock") is pl.session_lock("s-lock")


def test_the_question_wording_has_no_em_dash():
    for text, hint in pl._ANSWER_QUESTION.values():
        assert "—" not in text and "—" not in hint
    for v in (pl._HELD_MISMATCH, pl._HELD_GONE, *pl._ANSWER_LABEL.values()):
        assert "—" not in v
