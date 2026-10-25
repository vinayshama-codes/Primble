"""Build of 22 Oct 2026, lane FACTS, key facts-hygiene (25sepChanges.md Z32-FACTS).

Three defects of one family - a value that is not what it claims to be was read
as data:

  1. GAP 1 (CLAUDE.md "Answer Interpretation"): extraction kept a literal
     non-answer ("TBD", "Not provided", "N/A.", "--") as DATA. The merge wrote
     `facts[key]` straight from the model, `fact_answered` called it answered,
     Structural credited it, and the Data Consistency picker set it against the
     real value as a rival (a false "documents disagree" warning, 85 while open).
     One door: `answer_semantics.extracted_non_answer`, read per document and on
     the merged result (`extraction_service.drop_extracted_non_answers`), by the
     chunk vote (`_merge_list_fields`) and by the picker's candidates.
  2. A placeholder is not a party (Orbin "Not done"): "FIO" passed the party
     test because an initialism reads exactly like "3M". One vocabulary,
     `normalization.is_party_placeholder`, read by the insured-name door
     `is_not_a_party_name` and the third-party test `names_a_party`.
  3. A policy number printed without its carrier prefix ("7263-26" for
     "BBC7263-26") raised a false "two policies on the same coverage line" GL
     card. One rule, `fact_equivalence._number_without_its_prefix`, inside the
     one contract door; the grouping closure never lets a bare number join two
     different prefixes.

Adversarial cases come FIRST in every section: each rule must not over-reach.
"""
import ast
import copy
import inspect
import itertools
import logging
import os
import pathlib
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

from services import answer_semantics as AS                          # noqa: E402
from services import extraction_service as ES                         # noqa: E402
from services import fact_comparison as FC                            # noqa: E402
from services import fact_equivalence as FE                           # noqa: E402
from services import normalization as NZ                              # noqa: E402
from services import underwriting_consistency as UC                   # noqa: E402
from services.fact_registry import FACT_REGISTRY                      # noqa: E402
from services.field_mapping_integrity import names_a_party            # noqa: E402

BACKEND = pathlib.Path(__file__).resolve().parent.parent
logging.getLogger().setLevel(logging.CRITICAL)


def _env(value, source="ai", conf="ai_high", **extra):
    """A fact as extraction stores it on a document."""
    out = {"value": value, "confidence": conf, "source": source}
    out.update(extra)
    return out


def _v(raw):
    return raw.get("value") if isinstance(raw, dict) and "value" in raw else raw


def _door_off(monkeypatch):
    """The change switched OFF - proves a test depends on the door."""
    monkeypatch.setattr(AS, "extracted_non_answer", lambda _k, _v: None)


# =============================================================================
# 1. GAP 1 - THE DOOR: answer_semantics.extracted_non_answer
# =============================================================================

# ── 1a. ADVERSARIAL FIRST: a value is never a non-answer ─────────────────────
_REAL_VALUES = [
    # descriptions that merely CONTAIN a non-answer word - whole values only
    "Roofing contractor; hazardous materials not applicable",
    "Snow removal, scheduled later in the season",
    "Unknown Mortals LLC", "TBD Construction Inc", "N/A Holdings",
    "Skip's Plumbing", "Waiting Room Productions LLC",
    "None of the buildings are sprinklered", "No losses in the last five years",
    # conventions a box legitimately holds (CLAUDE.md C22)
    "Statutory", "Included", "See schedule", "see attached", "pending",
    "not required", "Not covered", "Not covered at this time", "Excluded",
    # short data
    "0", "$0", "0.00", "N", "No", "Y", "Yes", "1", "OR", "US", "-5", "#1",
    "84-2210987", "07/15/2026", "2250 NW Vaughn St",
]


@pytest.mark.parametrize("value", _REAL_VALUES)
@pytest.mark.parametrize("fact_key", ["operations_description", "prior_carrier",
                                      "total_revenue", "applicant_name"])
def test_a_real_value_is_never_a_non_answer(fact_key, value):
    assert AS.extracted_non_answer(fact_key, value) is None
    assert AS.extracted_non_answer(fact_key, _env(value)) is None


@pytest.mark.parametrize("raw", [None, "", "   ", 0, 0.0, 12, True, False, [],
                                 ["N/A"], {"line": "GL", "policy_number": "TBD"},
                                 {"confidence": "ai_high"}, {"value": None},
                                 {"value": 0}, {"value": ["TBD"]}])
def test_anything_that_is_not_text_is_never_judged(raw):
    assert AS.extracted_non_answer("total_revenue", raw) is None


# ── 1b. A whole-value non-answer, for every fact ─────────────────────────────
_NON_ANSWERS = [
    "N/A", "n/a", "N.A.", "NA", "n / a", "N/A.", "[N/A]", "(n/a)",
    "Unknown", "UNKNOWN", "unknown at this time", "Currently unknown",
    "TBD", "T.B.D.", "TBA", "t.b.a.", "TBC", "To be determined", "To be announced",
    "Not provided", "NOT PROVIDED", "Not available", "Not available at present",
    "Not yet known", "Not yet provided", "None provided", "None given",
    "Not supplied", "Unavailable", "Unspecified", "Not on file", "Not stated",
    "Information not available", "No data", "null",
    "-", "--", "---", "—", "...", "()", "- -",
]


@pytest.mark.parametrize("value", _NON_ANSWERS)
@pytest.mark.parametrize("fact_key", ["applicant_name", "prior_carrier", "total_revenue",
                                      "operations_description", "effective_date",
                                      "fein", "naics_code", "years_in_business"])
def test_a_non_answer_is_dropped_whatever_the_fact(fact_key, value):
    assert AS.extracted_non_answer(fact_key, value) == "non_answer"
    assert AS.extracted_non_answer(fact_key, _env(value)) == "non_answer"


# ── 1c. An absence is kept exactly where the fact takes one as an answer ─────
_ABSENCES = ["None reported", "Nil", "Nothing to report", "None known", "none at all",
             "(None)", "None at this time", "None known at this time"]


@pytest.mark.parametrize("value", _ABSENCES)
def test_an_absence_is_refused_only_on_a_fact_that_cannot_be_absent(value):
    """Oracle independent of the door: FACT_REGISTRY's own `required` flag (the
    same declaration `interpret_answer`'s rule 2b reads). Every fact, both ways."""
    for key, entry in FACT_REGISTRY.items():
        got = AS.extracted_non_answer(key, value)
        if entry.get("required"):
            assert got == "absence_refused", (key, value, got)
        else:
            assert got is None, (key, value, got)


def test_an_absence_is_the_answer_on_a_negative_polarity_fact():
    """"None reported" FILLS `loss_history_no_prior_losses_indicator`."""
    assert AS.extracted_non_answer("loss_history_no_prior_losses_indicator",
                                   "None reported") is None


# ── 1d. A person's value is never judged ─────────────────────────────────────
@pytest.mark.parametrize("value", ["N/A", "TBD", "None", "--", "Unknown"])
@pytest.mark.parametrize("envelope", [
    {"source": "producer", "confidence": "filled"},
    {"source": "client_arq", "confidence": "client_arq"},
    {"source": "user_confirmed", "confidence": "filled"},
    {"source": "ai", "confidence": "ai_high", "evidence_state": "user_confirmed"},
    {"source": "account", "confidence": "deterministic",
     "evidence_state": "user_confirmed", "evidence_actor": "producer"},
])
def test_a_persons_value_is_never_judged(envelope, value):
    assert AS.extracted_non_answer("applicant_name", dict(envelope, value=value)) is None
    assert AS.extracted_non_answer("total_revenue", dict(envelope, value=value)) is None


def test_the_account_envelope_writer_is_a_persons():
    env = ES._account_producer_envelope("TBD")
    assert AS.extracted_non_answer("producer_name", env) is None


# ── 1e. One vocabulary: the widened form-box door, still adversarial-safe ────
_MUST_SURVIVE_BOXES = [
    "0", "zero", "$0", "0.00", "N", "No", "n", "OR", "US", "1", "A", "S",
    "Statutory", "Included", "See schedule", "see attached", "pending",
    "not required", "None of the buildings are sprinklered",
    "No losses in the last five years", "2250 NW Vaughn St",
    "Meridian Ironworks & Mechanical, LLC", "93-2841760", "-5", "$", "%", "#1",
    "Not covered at this time", "Pending at this time", "Currently insured",
    "Not yet re-inspected", "Unknown Mortals LLC",
]


@pytest.mark.parametrize("value", _MUST_SURVIVE_BOXES)
def test_the_widened_placeholder_door_spares_every_real_value(value):
    assert AS.is_placeholder_text(value) is False


@pytest.mark.parametrize("value", ["TBA", "T.B.A.", "tbc", "None provided",
                                   "Unknown at this time", "Not yet known",
                                   "currently unknown", "Not available at present",
                                   "Unavailable", "Not on file", "Not supplied",
                                   "unknown currently", "N/A for now"])
def test_the_new_spellings_carry_no_information(value):
    assert AS.is_placeholder_text(value) is True


def _code_strings(fn) -> set:
    """Every string literal in a function's CODE (its docstring excluded)."""
    node = ast.parse(inspect.cleandoc("\n" + inspect.getsource(fn))).body[0]
    doc = ast.get_docstring(node)
    return {n.value.strip().lower() for n in ast.walk(node)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and n.value != doc}


def test_the_extraction_vocabulary_lives_only_in_answer_semantics():
    """ANTI-ROT. The merge and the picker call the door; neither grows its own
    copy of the vocabulary in code."""
    for fn in (ES.drop_extracted_non_answers, ES._extracted_non_answer,
               UC.assess_underwriting_consistency):
        literals = _code_strings(fn)
        # ("unknown" is left out: the picker's doc-type default is that word.)
        for token in ("tbd", "not provided", "n/a", "none provided", "tba",
                      "to be determined", "not available"):
            assert token not in literals, (fn.__name__, token)


# =============================================================================
# 2. GAP 1 - THE MERGE: extraction_service
# =============================================================================

def test_the_per_document_drop_removes_only_non_answers():
    facts = {
        "total_revenue": _env("Not provided"),
        "num_employees": _env("TBD"),
        "fein": "--",                                    # a bare value, no envelope
        "operations_description": _env("Roofing; hazmat not applicable"),
        "prior_carrier": _env("None reported"),          # an absence it takes
        "applicant_name": _env("None reported"),         # an absence it cannot take
        "contact_name": _env("N/A", source="producer"),  # a person's - never judged
        "lines_of_business": _env(["General Liability", "N/A", "TBD"]),
        "locations": ["TBD"],
        "coverage_lines": [{"line": "GL", "policy_number": "TBD"}],   # rows keep cells
        "_merge_rejected": {"x": ["N/A"]},               # bookkeeping, never judged
        "is_renewal": True,
    }
    removed = ES.drop_extracted_non_answers(facts)
    assert set(facts) == {"operations_description", "prior_carrier", "contact_name",
                          "lines_of_business", "coverage_lines", "_merge_rejected",
                          "is_renewal"}
    assert _v(facts["lines_of_business"]) == ["General Liability"]
    assert _v(facts["prior_carrier"]) == "None reported"
    assert _v(facts["contact_name"]) == "N/A"
    assert facts["coverage_lines"] == [{"line": "GL", "policy_number": "TBD"}]
    assert len(removed) == 6, removed
    assert ES.drop_extracted_non_answers(facts) == []    # idempotent


def test_a_persons_list_is_never_judged():
    facts = {"lines_of_business": _env(["N/A"], source="producer")}
    assert ES.drop_extracted_non_answers(facts) == []
    assert _v(facts["lines_of_business"]) == ["N/A"]


@pytest.mark.parametrize("junk", [None, [], "x", 5])
def test_the_per_document_drop_never_raises(junk):
    assert ES.drop_extracted_non_answers(junk) == []


def _doc(name, doc_type, facts, text=""):
    return {"doc_id": name, "filename": f"{name}.pdf", "doc_type": doc_type,
            "text": text or f"{doc_type.upper()} ORBIN CONTRACTING LLC",
            "facts": facts, "flags": {"has_general_liability": True}}


def _merge(docs):
    docs = copy.deepcopy(docs)
    mf, mg = ES.merge_facts(docs, ES.select_primary_truth(docs))
    return mf, mg, docs


def test_a_documents_non_answer_never_beats_another_documents_value():
    """The application is the AUTHORITATIVE source for the employee count
    (`_FIELD_CONFIDENCE_SOURCES`), so before the fix its "TBD" replaced the
    dec's 14 and the count normaliser then blanked it - the real value was
    destroyed, not just outranked (measured, see the test below)."""
    docs = [_doc("dec", "dec_page", {"applicant_name": _env("ORBIN CONTRACTING LLC"),
                                     "total_revenue": _env("$2,500,000"),
                                     "num_employees": _env("14")}),
            _doc("app", "application", {"applicant_name": _env("ORBIN CONTRACTING LLC"),
                                        "total_revenue": _env("Not provided"),
                                        "num_employees": _env("TBD")})]
    for order in (docs, list(reversed(docs))):
        mf, _mg, merged_docs = _merge(order)
        assert _v(mf["total_revenue"]) == "$2,500,000"
        assert _v(mf["num_employees"]) == "14"
        app = next(d for d in merged_docs if d["doc_id"] == "app")
        assert "total_revenue" not in app["facts"]       # the persisted copy agrees
        assert "num_employees" not in app["facts"]


def test_the_merge_bites_without_the_door(monkeypatch):
    docs = [_doc("dec", "dec_page", {"num_employees": _env("14")}),
            _doc("app", "application", {"num_employees": _env("TBD")})]
    mf, _mg, _d = _merge(docs)
    assert _v(mf["num_employees"]) == "14"
    _door_off(monkeypatch)
    mf, _mg, _d = _merge(docs)
    assert mf.get("num_employees") is None           # the defect: the real 14 lost


def test_a_lone_non_answer_leaves_the_fact_missing():
    docs = [_doc("dec", "dec_page", {"applicant_name": _env("ORBIN CONTRACTING LLC"),
                                     "operations_description": _env("Unknown at this time"),
                                     "years_in_business": _env("N/A."),
                                     "naics_code": _env("TBD")})]
    mf, _mg, _d = _merge(docs)
    for key in ("operations_description", "years_in_business", "naics_code"):
        assert key not in mf, key
    assert _v(mf["applicant_name"]) == "ORBIN CONTRACTING LLC"


def test_a_non_answer_no_longer_blocks_a_derivation():
    """`_derive_years_in_business` never overwrites a stated value - "Unknown"
    was stated, so the start date on the same dec went unused."""
    docs = [_doc("dec", "dec_page", {"applicant_name": _env("ORBIN CONTRACTING LLC"),
                                     "years_in_business": _env("Unknown"),
                                     "business_start_date": _env("06/15/2014")})]
    mf, _mg, _d = _merge(docs)
    assert _v(mf.get("years_in_business")) not in (None, "", "Unknown")
    assert mf["years_in_business"].get("evidence_state") == "derived"


def test_a_chunks_non_answer_never_out_votes_a_real_value():
    """The chunk vote (`_merge_list_fields`, frequency + confidence): two chunks
    printing "TBD" against one printing the date."""
    partials = [{"facts": {"effective_date": _env("TBD")}, "flags": {}, "_chunk_idx": 0},
                {"facts": {"effective_date": _env("TBD")}, "flags": {}, "_chunk_idx": 1},
                {"facts": {"effective_date": _env("07/15/2026")}, "flags": {}, "_chunk_idx": 2}]
    out = ES._merge_list_fields(partials, list_keys=[])
    assert _v(out["facts"]["effective_date"]) == "07/15/2026"


def test_the_chunk_vote_bites_without_the_door(monkeypatch):
    _door_off(monkeypatch)
    partials = [{"facts": {"effective_date": _env("TBD")}, "flags": {}, "_chunk_idx": i}
                for i in range(2)] + [
               {"facts": {"effective_date": _env("07/15/2026")}, "flags": {}, "_chunk_idx": 2}]
    out = ES._merge_list_fields(partials, list_keys=[])
    assert _v(out["facts"]["effective_date"]) == "TBD"


def test_the_merged_floor_drops_a_non_answer_and_keeps_a_persons():
    mf = {"contact_name": _env("TBD"), "total_revenue": _env("TBD", source="producer"),
          "wc_xmod": dict(ES._account_producer_envelope("Not provided")),
          "applicant_name": _env("ORBIN CONTRACTING LLC")}
    ES._strip_non_value_facts(mf)
    assert "contact_name" not in mf
    assert _v(mf["total_revenue"]) == "TBD"          # a person's: never judged here
    assert _v(mf["wc_xmod"]) == "Not provided"
    assert _v(mf["applicant_name"]) == "ORBIN CONTRACTING LLC"


def test_every_merge_point_asks_the_one_door():
    """ANTI-ROT: the chunk vote, the per-document head of the merge and the
    merged floor all reach `answer_semantics.extracted_non_answer`."""
    assert "_extracted_non_answer(" in inspect.getsource(ES._merge_list_fields)
    assert "drop_extracted_non_answers(" in inspect.getsource(ES.merge_facts)
    assert "drop_extracted_non_answers(" in inspect.getsource(ES._strip_non_value_facts)
    assert "_extracted_non_answer(" in inspect.getsource(ES.detect_source_conflicts)
    assert "from services.answer_semantics import extracted_non_answer" in \
        inspect.getsource(ES._extracted_non_answer)


def test_the_structural_tier_two_no_longer_credits_a_non_answer(monkeypatch):
    """D6 shape, through the real merge and the scorer's own Tier 2 reader."""
    from services.sqs_service import _tier2_items
    docs = [_doc("dec", "dec_page", {"applicant_name": _env("ORBIN CONTRACTING LLC"),
                                     "fein": _env("84-2210987"),
                                     "operations_description": _env("Carpentry contractor"),
                                     "total_revenue": _env("Not provided"),
                                     "num_employees": _env("14"),
                                     "years_in_business": _env("12"),
                                     "naics_code": _env("Unknown at this time")})]
    mf, _mg, _d = _merge(docs)
    _applicable, missing = _tier2_items(mf)
    assert "Annual revenue" in missing
    assert any("NAICS" in m for m in missing), missing
    _door_off(monkeypatch)
    mf_off, _mg, _d = _merge(docs)
    _applicable, missing_off = _tier2_items(mf_off)
    assert "Annual revenue" not in missing_off       # the defect: credited as answered
    assert not any("NAICS" in m for m in missing_off), missing_off


# =============================================================================
# 3. GAP 1 - DATA CONSISTENCY NEVER COMPARES A NON-ANSWER
# =============================================================================

def _dc_docs():
    dec = _doc("dec", "dec_page", {
        "applicant_name": _env("ORBIN CONTRACTING LLC"), "total_revenue": _env("$2,500,000"),
        "num_employees": _env("14"),
        "coverage_lines": [{"line": "General Liability", "carrier": "EMC Property & Casualty Company",
                            "policy_number": "BBC7263-26", "premium": "$3,954"}]})
    app = _doc("app", "application", {
        "applicant_name": _env("ORBIN CONTRACTING LLC"), "total_revenue": _env("Not provided"),
        "num_employees": _env("TBD"),
        "coverage_lines": [{"line": "General Liability", "carrier": "N/A",
                            "policy_number": "BBC7263-26"}]})
    merged = {"applicant_name": _env("ORBIN CONTRACTING LLC"), "total_revenue": _env("$2,500,000"),
              "num_employees": _env("14"), "coverage_lines": copy.deepcopy(dec["facts"]["coverage_lines"])}
    return [dec, app], merged


def _fields(uw, keys):
    return {f["fact_key"]: f for f in uw.get("fields") or [] if f["fact_key"] in keys}


def test_a_stored_documents_non_answer_is_no_rival():
    """A session stored before the rule: the picker re-assesses its documents
    WITHOUT a re-merge (the editor's confirm, the policies table)."""
    docs, merged = _dc_docs()
    got = _fields(UC.assess_underwriting_consistency(docs, merged, {}),
                  {"total_revenue", "num_employees", "carrier_name"})
    for key, row in got.items():
        assert not row.get("review_required"), (key, row.get("conflict_reason"))
        shown = [v.get("display") for v in row.get("values") or []]
        assert not any(s in ("Not provided", "TBD", "N/A") for s in shown), (key, shown)


def test_the_picker_bites_without_the_door(monkeypatch):
    _door_off(monkeypatch)
    docs, merged = _dc_docs()
    got = _fields(UC.assess_underwriting_consistency(docs, merged, {}), {"total_revenue"})
    assert got["total_revenue"].get("review_required") is True


def test_a_real_disagreement_still_raises_its_card():
    """ADVERSARIAL: only non-answers leave - two real amounts still conflict."""
    docs, merged = _dc_docs()
    docs[1]["facts"]["total_revenue"] = _env("$3,850,000")
    got = _fields(UC.assess_underwriting_consistency(docs, merged, {}), {"total_revenue"})
    assert got["total_revenue"].get("review_required") is True


def test_the_picker_asks_the_one_door():
    src = inspect.getsource(UC.assess_underwriting_consistency)
    assert "from services.answer_semantics import extracted_non_answer" in src


def _source_docs(app_values):
    return [_doc("dec", "dec_page", {"num_locations": _env("3"),
                                     "building_construction_year": _env("1998")}),
            _doc("app", "application", {k: _env(v) for k, v in app_values.items()})]


def test_a_stored_non_answer_raises_no_source_conflict():
    """`detect_source_conflicts` (the source stops) reads the stored per-document
    copies too - an old session's "TBD" is no rival there either."""
    docs = _source_docs({"num_locations": "TBD", "building_construction_year": "Not provided"})
    assert ES.detect_source_conflicts(docs, return_fields=True) == []


def test_the_source_conflict_bites_without_the_door(monkeypatch):
    _door_off(monkeypatch)
    docs = _source_docs({"num_locations": "TBD", "building_construction_year": "Not provided"})
    got = {f for f, _m, _c in ES.detect_source_conflicts(docs, return_fields=True)}
    assert got == {"num_locations", "building_construction_year"}


def test_a_real_source_disagreement_still_conflicts():
    """ADVERSARIAL: two real years still disagree."""
    docs = _source_docs({"num_locations": "3", "building_construction_year": "2004"})
    got = {f for f, _m, _c in ES.detect_source_conflicts(docs, return_fields=True)}
    assert got == {"building_construction_year"}


# =============================================================================
# 4. A PLACEHOLDER IS NOT A PARTY (normalization.is_party_placeholder)
# =============================================================================

# ── 4a. ADVERSARIAL FIRST: real names stay names ─────────────────────────────
_REAL_NAMES = [
    "Various Builders LLC", "Sample Electric Inc", "Void Studios LLC",
    "Insured Logistics Co", "FIO Holdings LLC", "TBA Electric", "Specimen Labs Inc",
    "Information Only Systems Inc", "Blank Rome LLP", "Unknown Mortals LLC",
    "Sample Company", "3M", "IBM", "EMC", "CRS", "AT&T", "U.S. Steel",
    "ORBIN CONTRACTING LLC", "Kestrel Terminal Authority", "Choice Electric LLC",
]


@pytest.mark.parametrize("name", _REAL_NAMES)
def test_a_real_name_is_never_a_placeholder(name):
    assert NZ.is_party_placeholder(name) is False
    assert NZ.is_not_a_party_name(name) is False


@pytest.mark.parametrize("name", [n for n in _REAL_NAMES if n not in ("3M",)])
def test_a_real_third_party_still_names_a_party(name):
    assert names_a_party(name, third_party=True) is True


# ── 4b. The placeholders, whole values, every spelling ───────────────────────
_PLACEHOLDERS = [
    "FIO", "fio", "F.I.O.", "F I O", "FIPO", "F.I.P.O.",
    "For Informational Purposes Only", "FOR INFORMATIONAL PURPOSES ONLY",
    "For Information Only", "For Informational Purposes", "Information Only",
    "TBD", "TBA", "TBC", "To be determined", "To Be Announced", "To be named",
    "N/A", "Sample", "SPECIMEN", "Void", "VOIDED", "Sample Only",
    "Various", "Insured", "Named Insured", "Certificate Holder",
    "Unknown", "None", "Not provided", "--",
]


@pytest.mark.parametrize("name", _PLACEHOLDERS)
def test_a_placeholder_fails_the_insured_name_door(name):
    assert NZ.is_not_a_party_name(name) is True


@pytest.mark.parametrize("name", _PLACEHOLDERS)
def test_a_placeholder_fails_the_third_party_test(name):
    assert names_a_party(name, third_party=True) is False


@pytest.mark.parametrize("junk", [None, "", "  ", 5, ["FIO"], {"value": "FIO"}])
def test_the_placeholder_test_never_raises(junk):
    assert NZ.is_party_placeholder(junk) is False


def test_the_insured_door_reads_the_placeholder_test():
    assert "is_party_placeholder(" in inspect.getsource(NZ.is_not_a_party_name)
    from services import field_mapping_integrity as FMI
    assert "is_party_placeholder" in inspect.getsource(FMI.names_a_party)


def test_the_orbin_certificate_holder_placeholder_leaves_the_document():
    """The Orbin COI's holder, read per document (`drop_non_party_names`)."""
    facts = {"certificate_holder": _env("FIO"),
             "certificate_description_of_operations": _env("FIO"),
             "applicant_name": _env("ORBIN CONTRACTING LLC")}
    cleared = ES.drop_non_party_names(facts)
    assert "certificate_holder" not in facts
    assert "certificate_description_of_operations" not in facts    # the same text
    assert _v(facts["applicant_name"]) == "ORBIN CONTRACTING LLC"
    assert any(c.startswith("certificate_holder=") for c in cleared)


def test_a_real_holder_stays():
    facts = {"certificate_holder": _env("Kestrel Terminal Authority")}
    assert ES.drop_non_party_names(facts) == []
    assert _v(facts["certificate_holder"]) == "Kestrel Terminal Authority"


def test_a_specimen_insured_never_wins_the_merge():
    docs = [_doc("specimen", "application", {"applicant_name": _env("SPECIMEN")}),
            _doc("dec", "dec_page", {"applicant_name": _env("ORBIN CONTRACTING LLC")})]
    for order in (docs, list(reversed(docs))):
        mf, _mg, _d = _merge(order)
        assert _v(mf["applicant_name"]) == "ORBIN CONTRACTING LLC"


def test_a_person_typing_fio_as_the_holder_is_asked_for_a_name():
    """The human door's third-party check reads the same party test (6c)."""
    assert AS.interpret_answer("certificate_holder", "FIO").intent == AS.UNKNOWN
    assert AS.interpret_answer("certificate_holder",
                               "Kestrel Terminal Authority").intent == AS.VALUE


# =============================================================================
# 5. A POLICY NUMBER WITHOUT ITS PREFIX IS THE SAME NUMBER
# =============================================================================

# ── 5a. ADVERSARIAL FIRST: different numbers never merge ─────────────────────
_DIFFERENT = [
    ("7263-26", "BBC7263-27"),          # another term / another policy
    ("263-26", "BBC7263-26"),           # a suffix is not the number
    ("26", "BBC7263-26"),               # proves nothing
    ("ABC7263-26", "BBC7263-26"),       # two prefixes = two policies
    ("CA0123456", "CPP0123456"),        # one account core, two lines
    ("7263", "BBC7263"),                # a core needs five characters
    ("ABCDE7263-26", "7263-26"),        # five letters is not a short prefix
    ("72630", "BBC72630 - 26"),         # no prefix AND no term: not composed
    ("0123456X", "CPP0123456"),
    ("BBC7263-26", "GL-4471102-26"),    # D-1: two carriers' GL policies
    ("POL123", "POL12345"),
    ("6C7-40-02---26", "6J7-40-02---26"),
    (None, "BBC7263"), ("", ""), (42, "BBC7263"), ("BBC7263", {}),
]


@pytest.mark.parametrize("a,b", _DIFFERENT)
def test_different_numbers_are_never_the_same(a, b):
    assert FC.same_policy_contract(a, b) is False
    assert FC.same_policy_contract(b, a) is False
    assert FE._number_without_its_prefix(a, b) is None


# ── 5b. The same number, printed with and without its prefix ─────────────────
_SAME = [
    ("7263-26", "BBC7263-26"), ("7263 - 26", "BBC 7263-26"), ("7263-26", "BBC-7263-26"),
    ("Policy No. 7263-26", "BBC7263-26"), ("0123456", "CPP0123456"),
    ("9930221 26", "WC 9930221 26"), ("7263-26", "bbc7263-26"),
]


@pytest.mark.parametrize("a,b", _SAME)
def test_a_number_without_its_prefix_is_the_same_number(a, b):
    assert FC.same_policy_contract(a, b) is True
    assert FC.same_policy_contract(b, a) is True
    assert FE.same_fact("policy_number", a, b) == FE.SAME


def test_the_existing_printings_are_untouched():
    for a, b in (("BBC7263 - 26", "BBC7263"), ("6E7-40-02---26", "6E74002"),
                 ("6J7-40-02---26", "6J74002"), ("bbc7263 - 26", "BBC7263")):
        assert FC.same_policy_contract(a, b) is True
    assert FC.same_policy_contract("BBC7263", "BBC726399") is False
    assert FC.policy_contract_groups(["BBC7263 - 26", "BBC7263", "6E7-40-02---26"]) == [[0, 1], [2]]


# ── 5c. The grouping closure never bridges two prefixes ──────────────────────
def _as_values(groups, vals):
    return sorted(tuple(sorted(vals[i] for i in g)) for g in groups)


@pytest.mark.parametrize("perm", list(itertools.permutations(
    ["CPP0123456", "CA0123456", "0123456"])))
def test_a_bare_number_matching_two_prefixes_stays_apart(perm):
    groups = FC.policy_contract_groups(list(perm))
    assert len(groups) == 3, groups


@pytest.mark.parametrize("perm", list(itertools.permutations(
    ["CPP1234567", "1234567", "1234567-26", "ABC1234567-26"])))
def test_a_chain_of_bare_printings_never_bridges_two_prefixes(perm):
    vals = list(perm)
    got = _as_values(FC.policy_contract_groups(vals), vals)
    assert ("CPP1234567",) in got and ("ABC1234567-26",) in got, got


@pytest.mark.parametrize("perm", list(itertools.permutations(
    ["BBC7263-26", "7263-26", "6E7-40-02---26", "BBC7263"])))
def test_an_unambiguous_bare_number_joins_its_contract_in_any_order(perm):
    vals = list(perm)
    got = _as_values(FC.policy_contract_groups(vals), vals)
    assert got == sorted([("6E7-40-02---26",),
                          tuple(sorted(("BBC7263-26", "7263-26", "BBC7263")))]), got


def test_the_picker_merge_keeps_an_ambiguous_bare_number_apart():
    assert FC.compare("policy_number", ["CPP0123456", "CA0123456", "0123456"]).distinct == 3
    assert FC.compare("policy_number", ["BBC7263-26", "7263-26"]).verdict == "equivalent"


def test_one_implementation_of_the_prefix_rule():
    """ANTI-ROT: the door delegates; the closure reads the same two halves."""
    assert "_fe._same_policy_contract" in inspect.getsource(FC.same_policy_contract)
    src = inspect.getsource(FC.policy_contract_groups)
    assert "_fe._number_without_its_prefix" in src
    assert "_fe._same_policy_contract_as_printed" in src
    tree = ast.parse((BACKEND / "services" / "fact_comparison.py").read_text())
    assert not any(isinstance(n, ast.FunctionDef) and n.name == "_number_without_its_prefix"
                   for n in ast.walk(tree)), "a second copy of the prefix rule"


# ── 5d. The live shape: the GL card, the line records, the policies table ────
_DEC_TEXT = ("COMMON POLICY DECLARATIONS\nNamed Insured: ORBIN CONTRACTING LLC\n"
             "Policy Number: BBC7263-26\nEMC Property & Casualty Company\n")


def _gl_docs(cert_number, cert_carrier="EMC Property & Casualty Company"):
    row = {"line": "General Liability", "carrier": "EMC Property & Casualty Company",
           "policy_number": "BBC7263-26", "effective_date": "07/15/2025",
           "expiration_date": "07/15/2026", "premium": "$3,954"}
    dec = _doc("dec", "dec_page", {"applicant_name": _env("ORBIN CONTRACTING LLC"),
                                   "policy_number": _env("BBC7263-26"),
                                   "carrier_name": _env("EMC Property & Casualty Company"),
                                   "coverage_lines": [row]}, text=_DEC_TEXT)
    cert = _doc("coi", "certificate", {"applicant_name": _env("ORBIN CONTRACTING LLC"),
                                       "policy_number": _env(cert_number),
                                       "carrier_name": _env(cert_carrier),
                                       "coverage_lines": [dict(row, policy_number=cert_number,
                                                               carrier=cert_carrier,
                                                               premium=None)]},
                text=f"CERTIFICATE OF LIABILITY INSURANCE {cert_number}")
    return [dec, cert]


def _policy_card(docs):
    mf, mg, merged_docs = _merge(docs)
    uw = UC.assess_underwriting_consistency(merged_docs, mf, {}, flags=mg)
    row = _fields(uw, {"policy_number"}).get("policy_number") or {}
    return row, mf, merged_docs


def test_the_live_shape_raises_no_card_and_lists_one_gl_policy():
    row, mf, docs = _policy_card(_gl_docs("7263-26"))
    assert not row.get("review_required"), row.get("conflict_reason")
    records = {(r.get("scope") or {}).get("record") for r in
               (mf.get("_scoped") or {}).get("policy_number") or []}
    assert len(records) == 1, records
    from services import policy_lines
    gl = [r for r in policy_lines.table_rows(mf, docs) if r.get("policy_number")]
    assert [r.get("policy_number") for r in gl] == ["BBC7263-26"], gl


@pytest.mark.parametrize("other", ["BBC7263-27", "ABC7263-26", "263-26"])
def test_a_genuinely_different_number_still_raises_its_card(other):
    """ADVERSARIAL: the card the rule must never silence."""
    row, _mf, _d = _policy_card(_gl_docs(other))
    assert row.get("review_required") is True, other


def test_the_card_rule_bites_without_the_prefix_rule(monkeypatch):
    monkeypatch.setattr(FE, "_number_without_its_prefix", lambda _a, _b: None)
    row, _mf, _d = _policy_card(_gl_docs("7263-26"))
    assert row.get("review_required") is True


# ── 5e. Review fix: the first-match consumers group through the one door ─────
# Compared against a group's FIRST member, a bare "0123456" seen first absorbed
# both "CA0123456" and "CPP0123456": the ACORD 125 header stopped blanking and
# printed one policy's number as the package's, and question 4 listed 1 of 3.
from services import pdf_service as PS                                # noqa: E402

_THREE = [{"line": "Commercial General Liability", "policy_number": "0123456"},
          {"line": "Business Auto", "policy_number": "CA0123456"},
          {"line": "Commercial Property", "policy_number": "CPP0123456"}]


@pytest.mark.parametrize("perm", list(itertools.permutations(range(3))))
def test_the_package_policy_count_is_order_independent(perm):
    rows = [dict(_THREE[i]) for i in perm]
    facts = {"_form_id": "ACORD_125", "coverage_lines": rows}
    assert len(PS._distinct_package_policies(facts)) == 3
    assert PS._resolve_package_header_identity("Policy_PolicyNumberIdentifier_A", facts) is None


@pytest.mark.parametrize("perm", list(itertools.permutations(range(3))))
def test_question_four_keeps_every_policy_in_any_order(perm):
    rows = [dict(_THREE[i]) for i in perm]
    kept = PS._dedupe_rows_by_policy_contract(rows)
    assert sorted(r["policy_number"] for r in kept) == ["0123456", "CA0123456", "CPP0123456"]


@pytest.mark.parametrize("order", ["forward", "reversed"])
def test_an_unambiguous_bare_number_folds_and_prints_what_it_printed(order):
    """Only the GROUPING moved: the count returns each policy as first printed,
    and the question 4 row prints its own number (the 17 Aug pin: "6E74002"
    stays "6E74002")."""
    rows = [{"line": "General Liability", "policy_number": "7263-26"},
            {"line": "Commercial General Liability", "policy_number": "BBC7263-26"},
            {"line": "Business Auto", "policy_number": "6E7-40-02---26"}]
    if order == "reversed":
        rows = rows[::-1]
    facts = {"_form_id": "ACORD_125", "coverage_lines": rows}
    got = PS._distinct_package_policies(facts)
    gl_first = next(r["policy_number"] for r in rows if "7263" in r["policy_number"])
    assert sorted(got) == sorted([gl_first, "6E7-40-02---26"])
    kept = PS._dedupe_rows_by_policy_contract([dict(r) for r in rows])
    assert len(kept) == 2
    for r in kept:                                    # each row prints its OWN number
        assert any(r == dict(orig) for orig in rows), r


@pytest.mark.parametrize("order", ["forward", "reversed"])
def test_the_header_binder_never_chains_two_prefixes(order):
    rows = [dict(r) for r in (_THREE if order == "forward" else _THREE[::-1])]
    groups = ES._contract_printings({"coverage_lines": rows})
    assert sorted(map(tuple, groups)) == [("0123456",), ("CA0123456",), ("CPP0123456",)]
    one = ES._contract_printings({"coverage_lines": [
        {"line": "GL", "policy_number": p} for p in
        (("7263-26", "BBC7263-26") if order == "forward" else ("BBC7263-26", "7263-26"))]})
    assert len(one) == 1 and sorted(one[0]) == ["7263-26", "BBC7263-26"]


def test_the_three_consumers_ask_the_grouping_door():
    for fn in (PS._distinct_package_policies, PS._dedupe_rows_by_policy_contract,
               ES._contract_printings):
        assert "policy_contract_groups" in inspect.getsource(fn), fn.__name__
