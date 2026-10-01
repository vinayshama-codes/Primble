"""Orbin demo run of 1 Oct 2026 (session 69687a55) - three extraction defects.

1. GL limits came out as the COMMERCIAL UMBRELLA's $3,000,000 (ACORD 126 and the
   131's underlying GL row). Both figures were extracted every run; the merge
   elected by repetition, so the outcome flipped between runs (359b36b0 was
   right). A line-scoped limit is now settled by its OWN line's verified
   declarations entries.
2. The ACORD 125 CARRIER line joined two writing companies in first-seen row
   order, which flipped between runs; question 4 named the umbrella "Umbrella"
   on one run and "Commercial Umbrella" on the next.
3. `applicant_gl_class_code` held 7383 - the AUTO rating class.

Every value below is the live session's own shape (labels, sections, policy
numbers and amounts as the client's dec prints them); nothing else.
"""
from __future__ import annotations

import copy

import pytest

import services.extraction_service as es

UMB, GL, AUTO, IM = "6J7-40-02---26", "BBC7263 - 26", "6E7-40-02---26", "6C7-40-02---26"


def _e(label, value, section, pn, lob, owner="policy"):
    return {"label": label, "value": value, "section": section, "owner": owner,
            "policy_number": pn, "line_of_business": lob}


# The live verified entries that name these limits (69687a55, dec_page_entries).
UMB_DECL = [
    _e("Each Occurrence Limit (Liability Coverage)", "$ 3,000,000",
       "COMMERCIAL UMBRELLA DECLARATIONS", UMB, "Commercial Umbrella"),
    _e("Personal & Advertising Injury Limit (Any one person or organization)", "$ 3,000,000",
       "COMMERCIAL UMBRELLA DECLARATIONS", UMB, "Commercial Umbrella"),
    _e("Aggregate Limit (Liability Coverage)", "$ 3,000,000",
       "COMMERCIAL UMBRELLA DECLARATIONS", UMB, "Commercial Umbrella"),
]
UMB_SCHEDULE = [
    _e("Commercial General Liability Products-Completed Operations Aggregate", "$ 2,000,000",
       "COMMERCIAL UMBRELLA SCHEDULE", UMB, "Commercial Umbrella"),
    _e("General Aggregate", "$ 2,000,000", "COMMERCIAL UMBRELLA SCHEDULE", UMB, "Commercial Umbrella"),
    _e("Products-Completed Operations Aggregate", "$ 2,000,000",
       "COMMERCIAL UMBRELLA SCHEDULE", UMB, "Commercial Umbrella"),
    _e("Personal and Advertising Injury", "$ 1,000,000",
       "COMMERCIAL UMBRELLA SCHEDULE", UMB, "Commercial Umbrella"),
    _e("Each Occurrence", "$ 1,000,000", "COMMERCIAL UMBRELLA SCHEDULE", UMB, "Commercial Umbrella"),
]
GL_DECL = [
    _e("Each Occurrence Limit", "$1,000,000", "General Liability Declarations", GL, "General Liability"),
    _e("Damage To Premises Rented To You Limit", "$500,000(any one premises)",
       "General Liability Declarations", GL, "General Liability"),
    _e("Medical Expense Limit", "$10,000(any one person)", "General Liability Declarations", GL,
       "General Liability"),
    _e("Personal and Advertising Injury Limit", "$1,000,000(any one person or organization)",
       "General Liability Declarations", GL, "General Liability"),
    _e("General Aggregate Limit", "$2,000,000", "General Liability Declarations", GL, "General Liability"),
    _e("Products/Completed Operations Aggregate Limit", "$2,000,000",
       "General Liability Declarations", GL, "General Liability"),
]
AUTO_CLASS = _e("PRIV PASSENGER - COMM CLASS", "7383",
                "ITEM THREE - SCHEDULE OF COVERED AUTOS YOU OWN", AUTO, "Commercial Auto")
ENTRIES = UMB_DECL + UMB_SCHEDULE + GL_DECL + [AUTO_CLASS]


def _f(v):
    return {"value": v, "confidence": "ai_high", "source": "ai"}


def _wrong_run_facts():
    """69687a55 as stored: every GL limit (and the composite) is the umbrella's."""
    return {
        "gl_limits": _f("$ 3,000,000"),
        "gl_each_occurrence": _f("$ 3,000,000"),
        "gl_aggregate": _f("$ 3,000,000"),
        "gl_products_aggregate": _f("$2,000,000"),
        "gl_personal_advertising_injury": _f("$ 3,000,000"),
        "umbrella_limit": _f("$ 3,000,000"),
        "_merge_rejected": {"gl_limits": ["$1,000,000"], "gl_each_occurrence": ["$1,000,000"],
                            "gl_aggregate": ["$2,000,000"],
                            "gl_personal_advertising_injury": ["$1,000,000"]},
    }


GL_KEYS = ("gl_each_occurrence", "gl_aggregate", "gl_products_aggregate",
           "gl_personal_advertising_injury")
RIGHT = {"gl_each_occurrence": "$1,000,000", "gl_aggregate": "$2,000,000",
         "gl_products_aggregate": "$2,000,000", "gl_personal_advertising_injury": "$1,000,000"}


def _gl(facts):
    return {k: es._fv(facts, k) for k in GL_KEYS}


# ── The text the entries are verified against (each page prints its contract) ─
_PAGES = {
    UMB: ("COMMERCIAL UMBRELLA DECLARATIONS", UMB_DECL),
    "umb_schedule": ("COMMERCIAL UMBRELLA SCHEDULE", UMB_SCHEDULE),
    GL: ("General Liability Declarations", GL_DECL),
    AUTO: ("ITEM THREE - SCHEDULE OF COVERED AUTOS YOU OWN", [AUTO_CLASS]),
}


def _doc_text():
    out = []
    for n, (key, (heading, ents)) in enumerate(_PAGES.items(), start=1):
        pn = ents[0]["policy_number"]
        out.append(f"[Document page {n}]\n{heading}\nPolicy Number: {pn}")
        out += [f"{e['label']}: {e['value']}" for e in ents]
    return "\n".join(out) + "\n"


def _policy_number_entries():
    return [_e("Policy Number", pn, heading, pn, ents[0]["line_of_business"])
            for heading, ents in _PAGES.values() for pn in [ents[0]["policy_number"]]]


def _doc(facts, entries=None):
    f = copy.deepcopy(facts)
    f["dec_page_entries"] = copy.deepcopy(entries if entries is not None
                                          else ENTRIES + _policy_number_entries())
    return {"filename": "2526 Package Policy.pdf", "doc_type": "dec_page",
            "text": _doc_text(), "facts": f, "flags": {}}


# ════════════════════════════════════════════════════════════════════════════
# FIX 1 - a GL limit is what the GL's own declarations print
# ════════════════════════════════════════════════════════════════════════════

def test_the_live_wrong_run_prints_the_gl_limits_through_merge_facts():
    # End to end through the one merge door, as the pipeline calls it.
    doc = _doc(_wrong_run_facts())
    mf, _flags = es.merge_facts([doc], doc)
    assert _gl(mf) == RIGHT
    assert es._fv(mf, "gl_limits").startswith("$1,000,000")
    assert "3,000,000" not in es._fv(mf, "gl_limits")
    # The rebuilt composite names each amount, each-occurrence first (the
    # scorer reads its first figure as the each-occurrence limit).
    assert es._fv(mf, "gl_limits") == ("$1,000,000 each occurrence / $2,000,000 aggregate / "
                                       "$2,000,000 products aggregate / "
                                       "$1,000,000 personal advertising injury")
    from services.sqs_service import _to_int
    assert _to_int(es._fv(mf, "gl_limits")) == 1_000_000
    assert mf["gl_limits"]["source"] == "derived" and "verified_in_text" not in mf["gl_limits"]
    # ...and the document's own copy (the "Review extracted data" popup) agrees.
    assert _gl(doc["facts"]) == RIGHT
    # The corrected fact says where it came from and what it replaced.
    env = mf["gl_each_occurrence"]
    assert env["source"] == "dec_entry" and env["verified_in_text"] is True
    assert env["derivation"]["replaced"] == "$ 3,000,000"
    # The umbrella's own limit is untouched.
    assert es._fv(mf, "umbrella_limit") == "$ 3,000,000"


def test_the_live_right_run_is_left_exactly_as_it_was():
    facts = {k: _f(v) for k, v in RIGHT.items()}
    facts["gl_limits"] = {"value": "$1,000,000 / $2,000,000", "confidence": "ai_high",
                          "source": "ai", "evidence_state": "suggested"}
    before = copy.deepcopy(facts)
    assert es._settle_line_limits(facts, copy.deepcopy(ENTRIES)) == []
    assert facts == before


@pytest.mark.parametrize("umbrella_first", [True, False])
def test_the_outcome_does_not_depend_on_which_chunk_spoke_first(umbrella_first):
    # Two chunks, one quoting the umbrella's figures and one the GL's - a tie the
    # vote settles by chunk order. After settling, both orders print the GL's.
    umb = {"facts": {k: _f("$ 3,000,000") for k in GL_KEYS if k != "gl_products_aggregate"},
           "flags": {}}
    gl = {"facts": {k: _f(v) for k, v in RIGHT.items()}, "flags": {}}
    parts = [umb, gl] if umbrella_first else [gl, umb]
    for i, p in enumerate(parts):
        p["_chunk_idx"] = i
    merged = es._merge_list_fields(copy.deepcopy(parts), list_keys=[])["facts"]
    es._settle_line_limits(merged, copy.deepcopy(ENTRIES))
    assert _gl(merged) == RIGHT


def test_entry_order_never_changes_the_answer():
    for entries in (ENTRIES, list(reversed(ENTRIES))):
        facts = _wrong_run_facts()
        es._settle_line_limits(facts, copy.deepcopy(entries))
        assert _gl(facts) == RIGHT


def test_a_blank_gl_limit_is_filled_from_the_gl_declarations():
    facts = {"umbrella_limit": _f("$ 3,000,000")}
    es._settle_line_limits(facts, copy.deepcopy(ENTRIES))
    assert _gl(facts) == RIGHT
    assert facts["gl_each_occurrence"]["confidence"] == "ai_low"   # the backfill's own label
    assert "gl_limits" not in facts                                 # a composite is never invented


def test_several_own_amounts_keep_a_voted_one_and_blank_a_foreign_one():
    two_gl = GL_DECL + [_e("Each Occurrence Limit", "$500,000", "General Liability Declarations",
                           GL, "General Liability")]
    keep = {"gl_each_occurrence": _f("$500,000")}
    es._settle_line_limits(keep, copy.deepcopy(two_gl + UMB_DECL))
    assert es._fv(keep, "gl_each_occurrence") == "$500,000"
    drop = {"gl_each_occurrence": _f("$ 3,000,000")}
    es._settle_line_limits(drop, copy.deepcopy(two_gl + UMB_DECL))
    assert "gl_each_occurrence" not in drop
    assert "gl_each_occurrence" in drop["_rejected_facts"]


def test_without_gl_entries_a_contested_umbrella_figure_is_blank_not_guessed():
    # The GL's declarations were not indexed; the umbrella prints its own $3M AND
    # the underlying $1M for "each occurrence" - they cannot be separated.
    facts = _wrong_run_facts()
    es._settle_line_limits(facts, copy.deepcopy(UMB_DECL + UMB_SCHEDULE))
    for k in ("gl_each_occurrence", "gl_aggregate", "gl_personal_advertising_injury"):
        assert k not in facts, k
    assert "gl_limits" not in facts                   # its headline limit is unknown
    assert es._fv(facts, "gl_products_aggregate") == "$2,000,000"   # only ever the GL's


@pytest.mark.parametrize("voted", ["$ 3,000,000", "$1,000,000"])
def test_without_gl_entries_the_outcome_does_not_depend_on_which_figure_won(voted):
    # The same package, two runs: the vote picked the umbrella's $3M on one and
    # the GL's $1M on the other. The umbrella prints both for "each occurrence"
    # (its own limit and its schedule of the GL) and nothing ties either to the
    # GL's declarations - both runs leave it blank, never one right, one wrong.
    rejected = "$1,000,000" if voted.endswith("3,000,000") else "$ 3,000,000"
    facts = {"gl_each_occurrence": _f(voted),
             "_merge_rejected": {"gl_each_occurrence": [rejected]}}
    es._settle_line_limits(facts, copy.deepcopy(UMB_DECL + UMB_SCHEDULE))
    assert "gl_each_occurrence" not in facts


def test_a_rival_from_the_vote_counts_only_when_it_is_printed():
    facts = {"gl_each_occurrence": _f("$ 3,000,000"),
             "_merge_rejected": {"gl_each_occurrence": ["$7,777"]}}       # printed nowhere
    es._settle_line_limits(facts, copy.deepcopy(UMB_DECL))
    assert es._fv(facts, "gl_each_occurrence") == "$ 3,000,000"
    facts = {"gl_each_occurrence": _f("$ 3,000,000"),
             "_merge_rejected": {"gl_each_occurrence": ["$1,000,000"]}}
    es._settle_line_limits(facts, copy.deepcopy(UMB_DECL + [UMB_SCHEDULE[-1]]))
    assert "gl_each_occurrence" not in facts


def test_a_gl_limit_equal_to_an_uncontested_umbrella_is_kept():
    # A $1M umbrella over a $1M GL whose declarations were not indexed: nothing
    # proves the GL figure wrong, and a third line's sublimit is not a rival.
    umb_1m = [_e("Each Occurrence Limit (Liability Coverage)", "$ 1,000,000",
                 "COMMERCIAL UMBRELLA DECLARATIONS", UMB, "Commercial Umbrella"),
              _e("Each Occurrence", "$ 50,000", "COMMERCIAL INLAND MARINE DECLARATIONS",
                 IM, "Inland Marine")]
    facts = {"gl_each_occurrence": _f("$1,000,000")}
    assert es._settle_line_limits(facts, umb_1m) == []
    assert es._fv(facts, "gl_each_occurrence") == "$1,000,000"


def test_the_other_than_products_aggregate_is_the_general_aggregate():
    kinds = es._limit_kinds(tuple(es._CURRENCY_COMPOSITE_PARENT))
    assert es._entry_limit_key(
        "General Aggregate Limit (Other Than Products-Completed Operations)", kinds) == "gl_aggregate"
    assert es._entry_limit_key(
        "General Aggregate Limit Other Than Products-Completed Operations", kinds) == "gl_aggregate"
    assert es._entry_limit_key("Products/Completed Operations Aggregate Limit",
                               kinds) == "gl_products_aggregate"
    assert es._entry_limit_key("Each Occurrence Limit (Liability Coverage)",
                               kinds) == "gl_each_occurrence"
    assert es._entry_limit_key("Contractors Equipment Most We Pay in Any One Occurrence",
                               kinds) is None
    assert es._entry_limit_key("", kinds) is None and es._entry_limit_key(None, kinds) is None
    # Another GL limit's printed name outranks a coincidental "each occurrence"
    # (the registry's own dec_labels for the premises limit).
    assert es._entry_limit_key("Damage To Premises Rented To You Each Occurrence Limit",
                               kinds) == "gl_fire_damage_limit"
    assert es._entry_limit_key("Medical Expense Limit", kinds) == "gl_medical_expense"
    assert "gl_limits" not in kinds                    # a composite names no one limit
    assert es._limit_kinds(None) == {} == es._limit_kinds(["not_a_line_key"])


def test_another_gl_limit_printed_per_occurrence_is_not_the_each_occurrence_limit():
    premises = _e("Damage To Premises Rented To You Each Occurrence Limit", "$100,000",
                  "General Liability Declarations", GL, "General Liability")
    facts = {"gl_each_occurrence": _f("$ 3,000,000")}
    es._settle_line_limits(facts, copy.deepcopy(GL_DECL + [premises] + UMB_DECL))
    assert es._fv(facts, "gl_each_occurrence") == "$1,000,000"


def test_a_gl_tag_on_the_umbrellas_own_contract_is_not_gl_evidence():
    # The section was dropped as unverified and the model tagged the umbrella's
    # $3M "General Liability" - its contract's own pages are the umbrella's.
    mistag = _e("Each Occurrence Limit", "$ 3,000,000", None, UMB, "General Liability")
    home = es._entry_home_lines(UMB_DECL + GL_DECL + [mistag])
    assert es._limit_entry_line(mistag, home) is None
    facts = {"gl_each_occurrence": _f("$ 3,000,000")}
    es._settle_line_limits(facts, copy.deepcopy(UMB_DECL + GL_DECL + [mistag]))
    assert es._fv(facts, "gl_each_occurrence") == "$1,000,000"


def test_the_umbrella_schedule_of_underlying_insurance_is_not_the_gls_declarations():
    home = es._entry_home_lines(ENTRIES)
    by_label = {e["label"]: es._limit_entry_line(e, home) for e in UMB_SCHEDULE}
    assert by_label["Products-Completed Operations Aggregate"] is None       # names GL on umbrella pages
    assert by_label["Each Occurrence"] == "umbrella"
    assert all(es._limit_entry_line(e, home) == "general_liab" for e in GL_DECL)


def test_a_person_s_answer_is_never_re_read():
    facts = {"gl_each_occurrence": {"value": "$ 3,000,000", "source": "producer"}}
    es._settle_line_limits(facts, copy.deepcopy(ENTRIES))
    assert es._fv(facts, "gl_each_occurrence") == "$ 3,000,000"


def test_a_prior_term_contract_speaks_only_when_nothing_current_does():
    prior_gl = [dict(e, policy_number="GL 7784120 25", value=e["value"].replace("1,000,000", "500,000"))
                for e in GL_DECL]
    facts = {"gl_each_occurrence": _f("$ 3,000,000"),
             "prior_coverage_by_line": [{"line": "General Liability", "policy_no": "GL 7784120 25"}]}
    es._settle_line_limits(facts, copy.deepcopy(prior_gl + GL_DECL + UMB_DECL))
    assert es._fv(facts, "gl_each_occurrence") == "$1,000,000"
    facts = {"gl_each_occurrence": _f("$ 3,000,000"),
             "prior_coverage_by_line": [{"line": "General Liability", "policy_no": "GL 7784120 25"}]}
    es._settle_line_limits(facts, copy.deepcopy(prior_gl + UMB_DECL))
    assert es._fv(facts, "gl_each_occurrence") == "$500,000"


@pytest.mark.parametrize("facts,entries", [
    (None, ENTRIES), ({}, None), ({}, []), ({}, "junk"),
    ({"gl_each_occurrence": _f("$1")}, [None, 3, "x", {"label": None, "value": None}]),
    ({"gl_each_occurrence": _f("$ 3,000,000")}, [dict(e, owner="producer") for e in GL_DECL]),
])
def test_junk_or_no_usable_entry_changes_nothing(facts, entries):
    before = copy.deepcopy(facts)
    assert es._settle_line_limits(facts, copy.deepcopy(entries)) == []
    assert facts == before


def test_a_composite_with_no_amounts_is_left_and_never_invented():
    facts = {"gl_limits": _f("See schedule")}
    es._settle_line_limits(facts, copy.deepcopy(ENTRIES))
    assert es._fv(facts, "gl_limits") == "See schedule"
    assert _gl(facts) == RIGHT                         # the children are the GL's own


def test_entries_without_a_document_text_change_nothing():
    doc = _doc(_wrong_run_facts())
    doc["text"] = ""
    assert es._settle_document_line_facts(doc) == []
    assert es._fv(doc["facts"], "gl_each_occurrence") == "$ 3,000,000"


def test_an_unprinted_gl_entry_is_never_evidence():
    # The model recorded a GL entry the document does not print - verification
    # drops it, so it cannot rewrite the limit.
    fake = [_e("Each Occurrence Limit", "$9,000,000", "General Liability Declarations", GL,
               "General Liability")]
    doc = _doc({"gl_each_occurrence": _f("$1,000,000")}, entries=fake + _policy_number_entries())
    es._settle_document_line_facts(doc)
    assert es._fv(doc["facts"], "gl_each_occurrence") == "$1,000,000"


# ════════════════════════════════════════════════════════════════════════════
# FIX 2 - carrier order and line names are fixed, not first-seen
# ════════════════════════════════════════════════════════════════════════════

_EMCPC, _EMCC = "EMC Property & Casualty Company", "Employers Mutual Casualty Company"
# Row orders of the two live runs (69687a55 / 359b36b0 coverage_lines).
RUN_A = [{"line": "Inland Marine", "carrier": _EMCC.upper(), "policy_number": IM, "premium": "$300.00"},
         {"line": "General Liability", "carrier": _EMCPC, "policy_number": GL, "premium": "$3,954.00"},
         {"line": "Umbrella", "carrier": _EMCC.upper(), "policy_number": UMB, "premium": "$3,418.00"},
         {"line": "Commercial Inland Marine", "carrier": _EMCC, "policy_number": IM, "premium": None}]
RUN_B = [{"line": "Property", "carrier": _EMCC.upper(), "policy_number": None, "premium": None},
         {"line": "Liability", "carrier": _EMCPC, "policy_number": GL, "premium": "$3,954.00"},
         {"line": "Inland Marine", "carrier": _EMCC.upper(), "policy_number": IM, "premium": "$300.00"},
         {"line": "Commercial Inland Marine", "carrier": _EMCC, "policy_number": IM, "premium": None}]


def test_the_125_carrier_line_is_the_same_whichever_row_came_first():
    want = [_EMCPC, _EMCC]
    assert es.current_policy_writer_names(RUN_A) == want
    assert es.current_policy_writer_names(RUN_B) == want
    assert es.current_policy_writer_names(list(reversed(RUN_A))) == want
    assert es._current_policy_writers(RUN_A) == es._current_policy_writers(list(reversed(RUN_A)))


def test_the_printing_is_chosen_by_its_characters():
    rows = [{"carrier": "Employers Mutual Casualty Co.", "policy_number": "A-1"},
            {"carrier": _EMCC.upper(), "policy_number": "A-1"},
            {"carrier": _EMCC, "policy_number": "A-2"}]
    for order in (rows, list(reversed(rows))):
        assert es.current_policy_writer_names(order) == [_EMCC]      # ordinary case, fuller name
    assert es.current_policy_writer_names([{"carrier": "ACME CASUALTY CO", "policy_number": "Z"}]) \
        == ["ACME CASUALTY CO"]
    assert es.current_policy_writer_names(None) == [] == es.current_policy_writer_names("junk")


def test_a_policy_record_prints_the_same_carrier_whichever_row_came_first():
    # The same contract printed twice, in capitals and in ordinary case, at the
    # same length: the record took whichever row came first.
    rows = [{"line": "Commercial Umbrella", "carrier": _EMCC.upper(), "policy_number": UMB,
             "premium": "$3,418.00"},
            {"line": "Commercial Umbrella", "carrier": _EMCC, "policy_number": UMB, "premium": None}]
    got = set()
    for order in (rows, list(reversed(rows))):
        recs = es._build_line_records({"coverage_lines": copy.deepcopy(order)})
        got.add(tuple((r["line"], r["carrier_name"], r["policy_number"]) for r in recs))
    assert got == {(("umbrella", _EMCC, UMB),)}


def _row(line, pn, premium=None, carrier=_EMCC):
    return {"line": line, "carrier": carrier, "policy_number": pn, "premium": premium}


# The umbrella's summary rows the two live runs emitted, and the headings both
# runs' verified entries carry for the contracts.
ROWS_A = [_row("Commercial Liability Umbrella", UMB, "$ 3,418.00"), _row("Umbrella", UMB, "$3,418.00"),
          _row("Automobile", AUTO, "$2,991.00"), _row("COVERED AUTOS LIABILITY", AUTO, "$ 1,496.00"),
          _row("General Liability", GL, "$3,954.00", _EMCPC),
          _row("Commercial General Liability", GL, None, _EMCPC)]
ROWS_B = [_row("Umbrella", UMB, "$3,418.00"), _row("Commercial Umbrella", UMB, "$ 3,418.00"),
          _row("Automobile", AUTO, "$2,991.00"), _row("COVERED AUTOS LIABILITY", AUTO, "$ 1,496.00"),
          _row("Liability", GL, "$3,954.00", _EMCPC),
          _row("Commercial General Liability", GL, "$3,954.00", _EMCPC)]
HEADINGS = [
    _e("Each Occurrence Limit (Liability Coverage)", "$ 3,000,000", "COMMERCIAL UMBRELLA DECLARATIONS",
       UMB, "Commercial Umbrella"),
    _e("COVERED AUTOS LIABILITY LIMIT", "$ 1,000,000", "COMMERCIAL AUTO DECLARATIONS - BUSINESS AUTO",
       AUTO, "Commercial Auto"),
    _e("Each Occurrence Limit", "$1,000,000", "General Liability Declarations", GL, "General Liability"),
    # The umbrella's schedule of the GL policy names no line for the GL contract.
    _e("General Aggregate", "$ 2,000,000", "COMMERCIAL UMBRELLA SCHEDULE", GL, "General Liability"),
]


def _names(rows, entries):
    mf = {"coverage_lines": copy.deepcopy(rows), "dec_page_entries": copy.deepcopy(entries)}
    return {r["line"]: r["line_printed"] for r in es._build_line_records(mf)}


def test_question_4_names_each_policy_the_same_on_every_run():
    a, b = _names(ROWS_A, HEADINGS), _names(ROWS_B, HEADINGS)
    assert a == b == {"umbrella": "Commercial Umbrella", "auto": "Commercial Auto",
                      "general_liab": "Commercial General Liability"}
    assert _names(list(reversed(ROWS_A)), list(reversed(HEADINGS))) == a


def test_without_declarations_headings_the_names_are_as_before():
    names = _names(ROWS_A, [])
    assert names["umbrella"] == "Umbrella" and names["auto"] == "Automobile"


def test_a_heading_naming_another_line_gives_nothing():
    heads = es._declarations_heading_names(HEADINGS + [
        _e("x", "1", "DISCLOSURE PURSUANT TO TERRORISM RISK INSURANCE ACT", UMB, "Commercial Umbrella"),
        _e("x", "1", "ITEM TWO: SCHEDULE OF COVERAGES AND COVERED AUTOS", AUTO, "Commercial Auto"),
        None, "junk", _e("x", "1", "", UMB, None)])
    assert sorted(heads) == sorted([("umbrella", UMB, "Commercial Umbrella"),
                                    ("auto", AUTO, "Commercial Auto"),
                                    ("general_liab", GL, "General Liability")])
    assert es._declarations_heading_names(None) == [] == es._declarations_heading_names("x")


# ════════════════════════════════════════════════════════════════════════════
# FIX 3 - a code another line rates is not the applicant's GL code
# ════════════════════════════════════════════════════════════════════════════

_VIN = [{"year": "2012", "make": "SUBARU", "vin": "4S4BRCGC9C3217772", "class_code": "7383",
         "territory": "111"}]
_GL_SCHED = [{"location": "Location 001", "class_code": "91580", "premium_basis": "Payroll"},
             {"location": "Location 001", "class_code": "91585", "premium_basis": "Total Cost"}]


def test_the_auto_class_is_not_stored_as_the_applicants_gl_code_through_merge_facts():
    facts = {"applicant_gl_class_code": _f("7383"), "auto_vin_schedule": copy.deepcopy(_VIN),
             "gl_class_code_schedule": copy.deepcopy(_GL_SCHED)}
    doc = _doc(facts)
    mf, _flags = es.merge_facts([doc], doc)
    assert "applicant_gl_class_code" not in mf
    assert "applicant_gl_class_code" not in doc["facts"]
    assert "Commercial Auto" in mf["_rejected_facts"]["applicant_gl_class_code"]
    # the auto's own rating schedule keeps its class
    assert mf["auto_vin_schedule"][0]["class_code"] == "7383"
    assert [r["class_code"] for r in mf["gl_class_code_schedule"]] == ["91580", "91585"]


def test_the_entry_alone_is_witness_enough():
    facts = {"applicant_gl_class_code": _f("7383")}
    assert es._drop_codes_another_line_owns(facts, [AUTO_CLASS])
    assert "applicant_gl_class_code" not in facts


@pytest.mark.parametrize("code", ["91580", "1234", "73"])
def test_a_gl_code_or_an_unattributed_code_is_kept(code):
    facts = {"applicant_gl_class_code": _f(code), "auto_vin_schedule": copy.deepcopy(_VIN),
             "gl_class_code_schedule": copy.deepcopy(_GL_SCHED)}
    assert es._drop_codes_another_line_owns(facts, [AUTO_CLASS]) == []
    assert es._fv(facts, "applicant_gl_class_code") == code


def test_a_code_both_lines_rate_is_kept():
    facts = {"applicant_gl_class_code": _f("7383"), "auto_vin_schedule": copy.deepcopy(_VIN),
             "gl_class_code_schedule": [{"class_code": "7383"}]}
    assert es._drop_codes_another_line_owns(facts) == []


def test_another_named_insureds_gl_code_column_is_checked_too():
    facts = {"named_insured_details": [{"name": "Second LLC", "gl_class_code": "7383", "sic": "1542"},
                                       {"name": "Third LLC", "gl_class_code": "91580"}],
             "auto_vin_schedule": copy.deepcopy(_VIN), "gl_class_code_schedule": copy.deepcopy(_GL_SCHED)}
    assert es._drop_codes_another_line_owns(facts)
    rows = facts["named_insured_details"]
    assert rows[0] == {"name": "Second LLC", "gl_class_code": None, "sic": "1542"}
    assert rows[1]["gl_class_code"] == "91580"


def test_a_person_typed_code_and_junk_are_left_alone():
    facts = {"applicant_gl_class_code": {"value": "7383", "source": "producer"},
             "auto_vin_schedule": copy.deepcopy(_VIN)}
    assert es._drop_codes_another_line_owns(facts) == []
    for junk in (None, {}, {"applicant_gl_class_code": None}, {"applicant_gl_class_code": True},
                 {"applicant_gl_class_code": _f(["7383"])}):
        es._drop_codes_another_line_owns(junk)
