"""b-umbrella-underlying (21 Oct 2026) - Brent's 20 Oct rule 2.

"Hard stop when umbrella / excess is selected and Primble cannot identify the
applicable underlying liability limits needed to support it. Do not require
both GL and Auto; look at the account's actual underlying coverage."

Until 21 Oct every reader counted only general liability and auto limits, so an
umbrella over Employers Liability only - or one whose limits sit only in its OWN
schedule of underlying insurance - was hard-stopped at 60, its pillar scored 0
and the ACORD 131 asked for a GL and an auto limit the account cannot have.

ONE door now (`sqs_service.umbrella_underlying`, reading
`coverage_evidence.umbrella_schedule_lines`), read by the package stops, the
per-form gate and its card, the Umbrella pillar, the evidence state, the ACORD
131 checklists and the cross-form umbrella checks:
  * identified = any underlying liability limit can be found (GL, auto CSL or
    split, EL, a row of the umbrella's own schedule, an amount its schedule
    text prints, the layer below on an upper layer's copy); none -> the one
    "no underlying" hard stop, as before (its sentence unchanged);
  * a line the umbrella's OWN schedule lists with no limit found anywhere ->
    a hard stop for that line (a warning to confirm when the schedule also
    prints amounts it does not tie to one line);
  * a line the package merely carries -> its existing warnings to confirm.

The adversarial cases come first: every way a NON-limit could clear the hard
stop, and every way a loose schedule reading could raise a false one.
"""
import ast
import copy
import inspect
import json
import textwrap
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from services import coverage_evidence as ce
from services import cross_form_validator as cfv
from services import sqs_service as sq
from services.issue_registry import (
    _LEGACY_MESSAGE_RULES, classify_legacy, resolution_for,
)

BACKEND = Path(__file__).resolve().parent.parent

NONE_STOP = "Umbrella detected but no underlying GL or Auto limits found"
GATE_HARD = "Umbrella present with no underlying GL or Auto limits"
EL_SOFT = "Umbrella attaches over WC but Employers Liability limits not provided."
SCHED_PREFIX = "Umbrella's own schedule of underlying insurance lists "


def _d(days):
    return (datetime.now() + timedelta(days=days)).strftime("%m/%d/%Y")


TERM = {"effective_date": _d(30), "expiration_date": _d(395)}
UMB = {"has_umbrella": True}
EL_TEXT = "$1,000,000 / $1,000,000 / $1,000,000"


def _f(**kw):
    out = {"umbrella_limit": "$5,000,000"}
    out.update(kw)
    return out


def _stops(facts, flags):
    return sq.evaluate_stops(dict(TERM, **facts), flags)


def _umb_hard(facts, flags):
    return [m for m in _stops(facts, flags)[0] if "mbrella" in m]


def _umb_soft(facts, flags):
    return [m for m in _stops(facts, flags)[1]
            if "mbrella" in m or "Employers Liability" in m]


def _row(line, limit=None, **kw):
    return dict({"line": line, "limit": limit, "carrier": "ACME", "policy_no": None}, **kw)


def _sched_sentence(fam):
    lbl = sq.UMB_UNDERLYING_LABELS[fam]
    return f"{SCHED_PREFIX}{lbl}, but no underlying {lbl} limit was found"


# =============================================================================
# 1. ADVERSARIAL - nothing that is not a limit may clear the hard stop
# =============================================================================
@pytest.mark.parametrize("non_answer", [
    "N/A", "n/a", "NA", "None", "none", "null", "", "   ", "Not covered", "Excluded",
    "Not Scheduled - -", "Not included", "To follow", "TBD", "Pending",
    "Not provided", "not applicable",
])
@pytest.mark.parametrize("key", ["employers_liability_limits", "gl_each_occurrence",
                                 "gl_limits", "auto_liability_limit"])
def test_a_non_limit_in_any_underlying_box_never_identifies_the_underlying(key, non_answer):
    facts = _f(**{key: non_answer})
    uu = sq.umbrella_underlying(facts, UMB)
    assert uu["identified"] is False and uu["numeric"] is False, (key, non_answer)
    assert NONE_STOP in _umb_hard(facts, UMB)


def test_the_pipelines_synthetic_schedule_sentence_identifies_nothing():
    """`extraction_pipeline` writes this when a document merely MENTIONS the
    schedule (H1-F class: a backfill that manufactures evidence)."""
    facts = _f(schedule_of_underlying_insurance={
        "value": "Schedule of Underlying Insurance referenced in submitted documents",
        "confidence": "filled", "source": "policy_doc_text"})
    assert sq.umbrella_underlying(facts, UMB)["identified"] is False
    assert NONE_STOP in _umb_hard(facts, UMB)


@pytest.mark.parametrize("text", [
    "SEE POLICIES IN ITEM 7",                                     # Choice Electric dec
    "The Schedule of Underlying Insurance is part of Policy No.",  # Choice Electric dec
    "Commercial General Liability; Commercial Auto Liability",     # line names, no limits
    "see the attached GL and Auto policies",
    "The schedule of underlying insurance was not supplied",
    "Policy No. CU7001A 11-15",
])
def test_schedule_prose_without_an_amount_identifies_nothing(text):
    facts = _f(schedule_of_underlying_insurance=text)
    uu = sq.umbrella_underlying(facts, UMB)
    assert uu["identified"] is False, text
    assert uu["missing_scheduled"] == [] and uu["scheduled_to_confirm"] == []
    assert _umb_hard(facts, UMB) == [NONE_STOP]


def test_the_umbrellas_own_limits_read_as_rows_are_not_underlying():
    """The Choice Electric umbrella dec: extraction put the umbrella's OWN limits
    into `underlying_policies` as "Umbrella Liability" rows."""
    rows = [_row("Umbrella Liability", "5,000 EACH OCCURRENCE"),
            _row("Umbrella Liability", "5,000 GENERAL AGGREGATE"),
            _row("Excess Liability", "$4,000,000")]
    facts = _f(underlying_policies=rows)
    assert sq.umbrella_underlying(facts, UMB)["identified"] is False
    assert NONE_STOP in _umb_hard(facts, UMB)


@pytest.mark.parametrize("line", ["Commercial Property", "Inland Marine", "Crime"])
def test_a_first_party_line_on_the_schedule_is_not_an_underlying_limit(line):
    facts = _f(underlying_policies=[_row(line, "$1,000,000")])
    assert sq.umbrella_underlying(facts, UMB)["identified"] is False


def test_a_row_naming_no_line_with_no_amount_identifies_nothing():
    facts = _f(underlying_policies=[_row("", "Included"), _row(None, "See schedule")])
    assert sq.umbrella_underlying(facts, UMB)["identified"] is False


# =============================================================================
# 2. ADVERSARIAL - a loose schedule reading must not raise a false hard stop
# =============================================================================
def test_schedule_text_never_lists_a_line():
    """Only a structured row LISTS a line (the hard-stop evidence). Prose that
    names a line is never enough - even beside an identified GL limit."""
    facts = _f(gl_each_occurrence="$1,000,000",
               schedule_of_underlying_insurance="General Liability; Automobile Liability; "
                                                "Employers Liability")
    uu = sq.umbrella_underlying(facts, {**UMB, "has_general_liability": True})
    assert uu["identified"] is True
    assert uu["missing_scheduled"] == [] and uu["scheduled_to_confirm"] == []
    assert not any(m.startswith(SCHED_PREFIX) for m in _stops(facts, UMB)[0] + _stops(facts, UMB)[1])


def test_a_listed_line_is_only_a_warning_when_the_schedule_prints_amounts_it_cannot_place():
    """The panel's own shape: "EL $1M/$1M/$1M" - `canon_line("EL")` is None, so
    the amount cannot be tied to EL. A row listing EL with no limit is then a
    warning to confirm, never a hard stop."""
    facts = _f(gl_each_occurrence="$1,000,000",
               underlying_policies=[_row("Employers Liability", None)],
               schedule_of_underlying_insurance="GL $1M/$2M; Auto $1M CSL; EL $1M/$1M/$1M")
    uu = sq.umbrella_underlying(facts, UMB)
    assert uu["missing_scheduled"] == []
    assert uu["scheduled_to_confirm"] == ["workers_comp"]
    hard, soft = _stops(facts, UMB)
    assert not any(m.startswith(SCHED_PREFIX) for m in hard)
    conf = [m for m in soft if m.startswith(SCHED_PREFIX)]
    assert conf and "employers liability" in conf[0] and "confirm" in conf[0]


def test_an_unnamed_row_with_an_amount_also_softens_a_listed_line():
    facts = _f(gl_each_occurrence="$1,000,000",
               underlying_policies=[_row("Commercial Package Policy", "$1,000,000"),
                                    _row("Automobile Liability", "")])
    uu = sq.umbrella_underlying(facts, UMB)
    assert uu["missing_scheduled"] == [] and uu["scheduled_to_confirm"] == ["auto"]


@pytest.mark.parametrize("excluded_row", [
    _row("Employers Liability", "Not Scheduled"),
    _row("Employers Liability", "N/A"),
    _row("Employers Liability", "Excluded"),
    _row("Employers Liability - Not Scheduled", None),
    _row("Workers Compensation and Employers Liability", "not covered"),
])
def test_a_line_the_schedule_excludes_is_not_listed_and_asks_nothing(excluded_row):
    facts = _f(gl_each_occurrence="$1,000,000",
               underlying_policies=[_row("General Liability", "$1,000,000"), excluded_row])
    flags = {**UMB, "has_general_liability": True, "has_workers_comp": True}
    uu = sq.umbrella_underlying(facts, flags)
    el = uu["lines"]["workers_comp"]
    assert el["excluded"] is True and el["listed"] is False and el["applicable"] is False
    assert uu["missing_scheduled"] == [] and uu["missing_carried"] == []
    hard, soft = _stops(facts, flags)
    assert not any(m.startswith(SCHED_PREFIX) for m in hard)
    assert EL_SOFT not in soft                      # the umbrella does not sit over EL
    assert not any(i["fact"] == "employers_liability_limits"
                   for i in sq.umbrella_deduction_items(facts, flags))


def test_schedule_text_never_takes_a_line_out():
    """Review M1 (21 Oct): only a structured ROW excludes a line. Text that says
    "Employers Liability Not Scheduled" (the policy-by-line kit) leaves EL a
    carried line to confirm - the same rule that lets only rows LIST a line."""
    facts = _f(gl_each_occurrence="$1,000,000",
               schedule_of_underlying_insurance=(
                   "Commercial General Liability Quillon P&C Co. QPC5519 $1,000,000 occ / "
                   "$2,000,000 agg; Commercial Auto Liability Quillon Mutual Casualty Co. "
                   "4A82107 $1,000,000 CSL; Employers Liability Not Scheduled - -"))
    flags = {**UMB, "has_general_liability": True, "has_workers_comp": True}
    uu = sq.umbrella_underlying(facts, flags)
    assert uu["lines"]["workers_comp"]["excluded"] is False
    assert EL_SOFT in _stops(facts, flags)[1]


@pytest.mark.parametrize("text", [
    "GL $1M/$2M; hired autos excluded",
    "GL $1M/$2M; Products-Completed Operations excluded",
    "Schedule of underlying GL policy not included",
])
def test_a_coverage_part_or_a_missing_document_in_text_excludes_nothing(text):
    facts = _f(gl_each_occurrence="$1,000,000", schedule_of_underlying_insurance=text)
    flags = {**UMB, "has_general_liability": True, "has_auto_coverage": True}
    uu = sq.umbrella_underlying(facts, flags)
    assert not any(ln["excluded"] for ln in uu["lines"].values()), text
    assert uu["missing_carried"] == ["auto"]
    assert ce.limit_printing_state("Schedule of underlying GL policy not included") == ce.LIMIT_ABSENT


def test_an_amount_beats_exclusion_words_in_a_row():
    """"$1,000,000 - pollution excluded" is a limit, not an excluded line."""
    facts = _f(underlying_policies=[_row("General Liability", "$1,000,000 - pollution excluded")])
    uu = sq.umbrella_underlying(facts, UMB)
    gl = uu["lines"]["general_liab"]
    assert gl["listed"] and gl["schedule_stated"] and gl["schedule_numeric"]
    assert not gl["excluded"] and uu["identified"]


def test_a_stated_row_outranks_an_exclusion_elsewhere():
    facts = _f(underlying_policies=[_row("Employers Liability", "$1,000,000")],
               schedule_of_underlying_insurance="Employers Liability excluded")
    el = sq.umbrella_underlying(facts, UMB)["lines"]["workers_comp"]
    assert el["listed"] and not el["excluded"] and el["schedule_numeric"]


# =============================================================================
# 3. The rule - Brent's own two ends and the account's actual coverage
# =============================================================================
def test_an_umbrella_over_employers_liability_only_is_not_hard_stopped():
    facts = _f(employers_liability_limits=EL_TEXT)
    flags = {**UMB, "has_workers_comp": True}
    uu = sq.umbrella_underlying(facts, flags)
    assert uu["identified"] and uu["numeric"]
    assert _umb_hard(facts, flags) == []
    assert sq._calculate_umbrella_adequacy(facts, flags) > 0
    assert sq._get_umbrella_state(facts, flags) != "unknown"


def test_an_umbrella_whose_limits_sit_only_in_its_own_schedule_is_not_hard_stopped():
    facts = _f(underlying_policies=[_row("General Liability", "$1,000,000 occ / $2,000,000 agg"),
                                    _row("Automobile Liability", "$1,000,000 CSL")])
    for flags in (UMB, {**UMB, "has_general_liability": True, "has_auto_coverage": True}):
        uu = sq.umbrella_underlying(facts, flags)
        assert uu["identified"] and uu["numeric"]
        assert _umb_hard(facts, flags) == []
        assert sq._calculate_umbrella_adequacy(facts, flags) > 0


def test_schedule_text_amounts_identify_the_underlying():
    facts = _f(schedule_of_underlying_insurance="GL $1M/$2M; Auto $1M CSL; EL $1M/$1M/$1M")
    uu = sq.umbrella_underlying(facts, UMB)
    assert uu["identified"] and uu["numeric"]
    assert _umb_hard(facts, UMB) == []


def test_a_policy_on_a_line_the_families_cannot_place_still_identifies():
    facts = _f(underlying_policies=[_row("Commercial Package Policy", "$1,000,000")])
    assert sq.umbrella_underlying(facts, UMB)["identified"] is True


@pytest.mark.parametrize("line", ["Liquor Liability", "Employee Benefits Liability",
                                  "Professional Liability"])
def test_any_liability_line_the_schedule_prices_identifies(line):
    facts = _f(underlying_policies=[_row(line, "$1,000,000")])
    uu = sq.umbrella_underlying(facts, UMB)
    assert uu["identified"] and uu["numeric"]
    assert uu["missing_scheduled"] == []          # only the three boxed lines are asked


def test_nothing_at_all_keeps_the_one_hard_stop_word_for_word():
    facts = _f()
    assert _umb_hard(facts, UMB) == [NONE_STOP]
    assert sq._calculate_umbrella_adequacy(facts, UMB) == 0
    assert sq._get_umbrella_state(facts, UMB) == "unknown"
    assert sq._resolve_cap([NONE_STOP], []) == (60, NONE_STOP)


@pytest.mark.parametrize("words", ["Included", "Statutory", "See schedule", "$0"])
@pytest.mark.parametrize("key", ["gl_each_occurrence", "auto_liability_limit"])
def test_a_limit_in_words_still_counts_as_stated(key, words):
    """The four conventions of 2026-09-08 (`_umbrella_underlying_stated`): stated
    for the hard stop, not a number for the pillar."""
    facts = _f(**{key: words})
    uu = sq.umbrella_underlying(facts, UMB)
    assert uu["identified"] is True
    if key != "auto_liability_limit":
        assert uu["numeric"] is False
    assert _umb_hard(facts, UMB) == []


@pytest.mark.parametrize("words", ["Statutory", "Included", "See schedule"])
@pytest.mark.parametrize("key", ["employers_liability_limits", "wc_el_each_accident"])
def test_employers_liability_in_words_is_not_an_el_limit(key, words):
    """Review M2: EL is a money limit - "Statutory" is the WC part's."""
    facts = _f(**{key: words})
    assert sq.umbrella_underlying(facts, UMB)["identified"] is False
    assert NONE_STOP in _umb_hard(facts, UMB)
    row = _f(underlying_policies=[_row("Workers Compensation and Employers Liability", words)])
    assert sq.umbrella_underlying(row, UMB)["identified"] is False


def test_auto_split_limits_and_a_csl_in_words_keep_their_reading():
    split = _f(auto_bi_per_person="$250,000", auto_bi_per_accident="$500,000",
               auto_pd_per_accident="$100,000")
    assert sq.umbrella_underlying(split, UMB)["numeric"] is True
    words = _f(auto_liability_limit="Included")
    assert sq.umbrella_underlying(words, UMB)["numeric"] is True     # as before 21 Oct
    zero = _f(auto_liability_limit="$0")
    uu = sq.umbrella_underlying(zero, UMB)
    assert uu["identified"] is True and uu["numeric"] is False


def test_an_amount_in_either_gl_box_is_read():
    """`gl_each_occurrence or gl_limits` read only the first non-blank string; a
    junk first box hid a real second one."""
    facts = _f(gl_each_occurrence="N/A", gl_limits="$1,000,000 / $2,000,000")
    uu = sq.umbrella_underlying(facts, UMB)
    assert uu["lines"]["general_liab"]["fact_numeric"] is True


def test_identified_is_never_narrower_than_numeric():
    shapes = [
        _f(), _f(gl_each_occurrence="$1,000,000"), _f(employers_liability_limits=EL_TEXT),
        _f(gl_each_occurrence="Included"), _f(auto_liability_limit="$0"),
        _f(underlying_policies=[_row("General Liability", "1,000 EACH OCCURRENCE")]),
        _f(schedule_of_underlying_insurance="$1M / $2M"),
    ]
    for facts in shapes:
        uu = sq.umbrella_underlying(facts, UMB)
        assert not (uu["numeric"] and not uu["identified"]), facts
        assert sq._umbrella_has_underlying(facts) == uu["numeric"]
        assert sq._umbrella_underlying_stated(facts) == uu["identified"]


# =============================================================================
# 4. Partial - a line the umbrella's own schedule lists, a line merely carried
# =============================================================================
def test_a_listed_line_with_no_limit_anywhere_is_a_hard_stop_of_its_own():
    facts = _f(gl_each_occurrence="$1,000,000",
               underlying_policies=[_row("General Liability", "$1,000,000"),
                                    _row("Automobile Liability", "")])
    assert _umb_hard(facts, UMB) == [_sched_sentence("auto")]
    code, _cluster, tier = classify_legacy(_sched_sentence("auto"), "hard_stop")
    assert code == "legacy_umbrella_scheduled_auto_limit_missing" and tier == "required"
    assert resolution_for(code) == {**resolution_for(code), "mode": "field",
                                    "facts": ["auto_liability_limit"]}
    assert sq._resolve_cap(_umb_hard(facts, UMB), []) == (60, _sched_sentence("auto"))


@pytest.mark.parametrize("found", [
    {"auto_liability_limit": "$1,000,000"},
    {"auto_bi_per_person": "$250,000"},
    {"auto_liability_limit": "Included"},
])
def test_a_listed_line_whose_limit_the_package_states_is_fine(found):
    facts = _f(gl_each_occurrence="$1,000,000", **found,
               underlying_policies=[_row("Automobile Liability", None)])
    assert sq.umbrella_underlying(facts, UMB)["missing_scheduled"] == []
    assert _umb_hard(facts, UMB) == []


def test_a_bare_typed_amount_is_an_amount():
    """A person's typed limit is stored "1000000" (14 Oct 2026) - an amount,
    as `_labelled_amounts` reads it, so it prices its schedule row too."""
    assert ce.limit_printing_state("1000000") == ce.LIMIT_AMOUNT
    assert ce.limit_is_positive_amount("1000000") is True
    assert ce.limit_printing_state("2015") == ce.LIMIT_WORDS          # a year is not
    facts = _f(underlying_policies=[_row("General Liability", "1000000")])
    gl = sq.umbrella_underlying(facts, UMB)["lines"]["general_liab"]
    assert gl["schedule_numeric"] is True


@pytest.mark.parametrize("limit", ["$1,000,000", "1M", "1000000",
                                   "Statutory / $1,000,000 / $1,000,000 / $1,000,000"])
def test_a_listed_line_whose_own_row_prints_a_limit_is_fine(limit):
    facts = _f(gl_each_occurrence="$1,000,000",
               underlying_policies=[_row("Workers Compensation and Employers Liability", limit)])
    assert sq.umbrella_underlying(facts, UMB)["missing_scheduled"] == []


def test_one_row_with_a_limit_and_a_duplicate_without_is_stated():
    facts = _f(underlying_policies=[_row("General Liability", None),
                                    _row("General Liability", "$1,000,000")])
    uu = sq.umbrella_underlying(facts, UMB)
    assert uu["lines"]["general_liab"]["stated"] and uu["missing_scheduled"] == []


def test_every_line_listed_and_missing_is_one_stop_each_in_order():
    facts = _f(underlying_policies=[_row("Employers Liability", ""), _row("Auto Liability", ""),
                                    _row("General Liability", ""),
                                    _row("Liquor Liability", "$1,000,000")])
    uu = sq.umbrella_underlying(facts, UMB)
    assert uu["identified"] is True                    # the liquor row prices one line
    assert uu["missing_scheduled"] == ["general_liab", "auto", "workers_comp"]
    hard = _umb_hard(facts, UMB)
    assert hard == [_sched_sentence("general_liab"), _sched_sentence("auto"),
                    _sched_sentence("workers_comp")]
    boxes = [resolution_for(classify_legacy(m, "hard_stop")[0])["facts"] for m in hard]
    assert boxes == [["gl_each_occurrence", "gl_limits"], ["auto_liability_limit"],
                     ["employers_liability_limits"]]


def test_with_nothing_identified_the_listed_lines_do_not_stop_twice():
    facts = _f(underlying_policies=[_row("General Liability", ""), _row("Auto Liability", "")])
    uu = sq.umbrella_underlying(facts, UMB)
    assert uu["identified"] is False and uu["missing_scheduled"] == []
    assert _umb_hard(facts, UMB) == [NONE_STOP]


def test_a_carried_line_is_a_warning_to_confirm_never_a_hard_stop():
    """GL found, the package carries auto (its policy is in the package), the
    umbrella's documents do not list auto, no auto limit: the cross-form
    "limit could not be determined" warning, as before - not a hard stop."""
    facts = _f(gl_each_occurrence="$1,000,000")
    flags = {**UMB, "has_general_liability": True, "has_auto_coverage": True}
    uu = sq.umbrella_underlying(facts, flags)
    assert uu["missing_carried"] == ["auto"] and uu["missing_scheduled"] == []
    assert _umb_hard(facts, flags) == []
    codes = {i["code"] for i in cfv.run_cross_form_validation(
        dict(TERM, **facts), flags, {"ACORD_125", "ACORD_126", "ACORD_127", "ACORD_131"})}
    assert "umbrella_auto_limits_not_found" in codes


def test_the_employers_liability_warning_is_the_carried_lines_warning():
    facts = _f(gl_each_occurrence="$1,000,000")
    flags = {**UMB, "has_general_liability": True, "has_workers_comp": True}
    assert EL_SOFT in _stops(facts, flags)[1]
    # ...beside the one "no underlying" stop too, as it always was.
    assert EL_SOFT in _stops(_f(), {**UMB, "has_workers_comp": True})[1]


def test_a_listed_el_with_no_limit_is_the_hard_stop_not_also_the_warning():
    facts = _f(gl_each_occurrence="$1,000,000",
               underlying_policies=[_row("Employers Liability", None)])
    flags = {**UMB, "has_general_liability": True, "has_workers_comp": True}
    hard, soft = _stops(facts, flags)
    assert _sched_sentence("workers_comp") in hard
    assert EL_SOFT not in soft
    codes = {i["code"] for i in cfv.run_cross_form_validation(
        dict(TERM, **facts), flags, {"ACORD_125", "ACORD_126", "ACORD_130", "ACORD_131"})}
    assert "umbrella_missing_employers_liability" not in codes


def test_a_limit_the_umbrellas_schedule_states_answers_the_carried_line():
    facts = _f(underlying_policies=[_row("General Liability", "$1,000,000"),
                                    _row("Employers Liability", "$1,000,000")])
    flags = {**UMB, "has_general_liability": True, "has_workers_comp": True}
    uu = sq.umbrella_underlying(facts, flags)
    assert uu["missing_carried"] == [] and uu["missing_scheduled"] == []
    hard, soft = _stops(facts, flags)
    assert _umb_hard(facts, flags) == [] and EL_SOFT not in soft
    codes = {i["code"] for i in cfv.run_cross_form_validation(
        dict(TERM, **facts), flags, {"ACORD_126", "ACORD_130", "ACORD_131"})}
    assert "umbrella_gl_limits_not_found" not in codes
    assert "umbrella_missing_employers_liability" not in codes


def test_the_existing_below_minimum_warnings_stay():
    facts = _f(gl_each_occurrence="$500,000", auto_liability_limit="$500,000",
               employers_liability_limits="$100,000")
    flags = {**UMB, "has_general_liability": True, "has_auto_coverage": True,
             "has_workers_comp": True}
    soft = _stops(facts, flags)[1]
    assert "Underlying limits may not meet umbrella requirements." in soft
    assert any(m.startswith("Employers Liability limit (100,000) is below") for m in soft)
    codes = {i["code"] for i in cfv.run_cross_form_validation(
        dict(TERM, **facts), flags, {"ACORD_126", "ACORD_127", "ACORD_130", "ACORD_131"})}
    assert {"umbrella_gl_attachment_failure", "umbrella_auto_attachment_failure",
            "umbrella_el_below_minimum"} <= codes


# =============================================================================
# 5. The pillar, the cards and the evidence state read the same door
# =============================================================================
def test_the_no_underlying_row_asks_for_a_box_that_lifts_the_pillar():
    cases = [
        ({**UMB, "has_workers_comp": True}, "employers_liability_limits", EL_TEXT),
        ({**UMB, "has_general_liability": True}, "gl_each_occurrence", "$1,000,000"),
        ({**UMB, "has_auto_coverage": True}, "auto_liability_limit", "$1,000,000"),
        (dict(UMB), "gl_each_occurrence", "$1,000,000"),
    ]
    for flags, box, answer in cases:
        rows = sq.umbrella_gap_items(_f(), flags)
        assert [(r["fact"], r["points"]) for r in rows] == [(box, 100)], flags
        assert "employers liability" in rows[0]["label"]
        assert sq._calculate_umbrella_adequacy(_f(**{box: answer}), flags) > 0
        assert NONE_STOP not in _umb_hard(_f(**{box: answer}), flags)


def test_a_limit_the_schedule_states_is_not_charged_as_absent():
    facts = _f(underlying_policies=[_row("General Liability", "$1,000,000"),
                                    _row("Automobile Liability", "$1,000,000 CSL")])
    flags = {**UMB, "has_general_liability": True, "has_auto_coverage": True}
    charged = {i["fact"] for i in sq.umbrella_deduction_items(facts, flags)}
    assert "gl_each_occurrence" not in charged and "auto_liability_limit" not in charged
    assert sq._get_umbrella_state(facts, flags) == "umbrella_coverage_present"


def test_a_schedule_amount_is_never_compared_against_the_minimum():
    """A schedule printed in thousands ("1,000 EACH OCCURRENCE") must not become a
    $1,000 GL limit below the $1M minimum - the comparison reads the policy's
    own limit facts only."""
    facts = _f(underlying_policies=[_row("General Liability", "1,000 EACH OCCURRENCE")])
    flags = {**UMB, "has_general_liability": True}
    items = sq.umbrella_deduction_items(facts, flags)
    assert not any("below" in i["label"] and i["fact"] == "gl_each_occurrence" for i in items)
    assert not any(w.startswith("Underlying GL limits may not meet")
                   for w in sq._build_umbrella_warnings(facts, flags, 50))


def test_a_listed_line_not_carried_is_still_required_by_the_pillar():
    """The umbrella sits over it (its own schedule says so) - the pillar asks
    for it like a carried line, beside the hard stop."""
    facts = _f(gl_each_occurrence="$1,000,000",
               underlying_policies=[_row("Automobile Liability", None)])
    charged = {i["fact"] for i in sq.umbrella_deduction_items(facts, UMB)}
    assert "auto_liability_limit" in charged


def test_the_el_tiers_follow_the_umbrella_not_only_the_wc_flag():
    listed = _f(gl_each_occurrence="$1,000,000", employers_liability_limits="$500,000",
                underlying_policies=[_row("Employers Liability", "$500,000")])
    items = sq.umbrella_deduction_items(listed, UMB)                 # WC not flagged
    assert ("employers_liability_limits", 10) in {(i["fact"], i["points"]) for i in items}
    # Not carried, not listed - nothing to charge (as before).
    assert not any(i["fact"] == "employers_liability_limits"
                   for i in sq.umbrella_deduction_items(_f(gl_each_occurrence="$1,000,000"), UMB))


def test_the_per_form_gate_and_card():
    def _form(facts, flags):
        return sq.calculate_sqs(facts, flags, {}, {}, ["ACORD_131"], [], [], 0,
                                form_id="ACORD_131")

    el_only = _form(_f(employers_liability_limits=EL_TEXT), {**UMB, "has_workers_comp": True})
    assert el_only["breakdown"]["umbrella_limit_adequacy"] > 0
    assert GATE_HARD not in (el_only.get("cap_hard_stops") or [])
    assert el_only.get("cap_applied") != sq.HARD_STOP_CAP

    bare = _form(_f(), {**UMB, "has_workers_comp": True})
    assert bare["breakdown"]["umbrella_limit_adequacy"] == 0
    assert bare["cap_applied"] == sq.HARD_STOP_CAP and bare["cap_reason"] == GATE_HARD
    rec = next(r for r in bare["recommendations"] if r.get("rec_id") == "rec_underlying_limits")
    assert rec["field"] == "employers_liability_limits"        # the box this account has
    gl_rec = next(r for r in _form(_f(), {**UMB, "has_general_liability": True})["recommendations"]
                  if r.get("rec_id") == "rec_underlying_limits")
    assert gl_rec["field"] == "gl_limits"                       # unchanged for GL


def test_every_no_underlying_window_offers_the_employers_liability_box():
    for message in (NONE_STOP, GATE_HARD):
        code = classify_legacy(message, "hard_stop")[0]
        assert "employers_liability_limits" in resolution_for(code)["facts"], message
    assert "employers_liability_limits" in resolution_for("umbrella_no_underlying_coverage")["facts"]


# =============================================================================
# 6. The ACORD 131 checklists - "do not require both GL and Auto"
# =============================================================================
def _struct_and_exposure(facts, flags):
    res = sq.calculate_sqs(facts, flags, {}, {}, ["ACORD_131"], [], [], 0, form_id="ACORD_131")
    return res["breakdown"]["structural_completeness"], res["breakdown"]["exposure_consistency"]


def test_the_checklists_ask_only_for_the_lines_the_umbrella_sits_over():
    base = dict(umbrella_limit="$5,000,000", umbrella_sir="$10,000")
    el_only = sq._umbrella_underlying_checks(
        dict(base, employers_liability_limits=EL_TEXT), {**UMB, "has_workers_comp": True},
        split_counts=False)
    assert el_only == [True]                                   # no GL / auto item
    gl_only = sq._umbrella_underlying_checks(
        dict(base, gl_each_occurrence="$1,000,000"), {**UMB, "has_general_liability": True},
        split_counts=False)
    assert gl_only == [True]
    # Nothing known at all - the two items the checklist always had stay.
    assert sq._umbrella_underlying_checks(dict(base), UMB, split_counts=False) == [False, False]
    # A carried line with no limit is still a gap.
    assert sq._umbrella_underlying_checks(
        dict(base, gl_each_occurrence="$1,000,000"),
        {**UMB, "has_general_liability": True, "has_auto_coverage": True},
        split_counts=False) == [True, False]
    # The Exposure checklist never had an EL item - an EL-only umbrella leaves it nothing.
    assert sq._umbrella_underlying_checks(
        dict(base, employers_liability_limits=EL_TEXT), {**UMB, "has_workers_comp": True},
        split_counts=True, families=("general_liab", "auto")) == []
    # Split limits count where the checklist reads them (Exposure), not the CSL box.
    split = dict(base, gl_each_occurrence="$1,000,000", auto_bi_per_person="$250,000")
    flags = {**UMB, "has_general_liability": True, "has_auto_coverage": True}
    assert sq._umbrella_underlying_checks(split, flags, split_counts=True) == [True, True]
    assert sq._umbrella_underlying_checks(split, flags, split_counts=False) == [True, False]


@pytest.mark.parametrize("junk", ["N/A", "none", "Excluded", "Not covered"])
def test_a_non_limit_never_meets_a_checklist_item(junk):
    """An EL box reading "N/A" counted as a stated limit, so the 131's
    Structural read 100 on a package hard-stopped for having no underlying."""
    facts = dict(umbrella_limit="$5,000,000", umbrella_sir="$10,000",
                 employers_liability_limits=junk)
    flags = {**UMB, "has_workers_comp": True}
    assert sq._umbrella_underlying_checks(facts, flags, split_counts=False) == [False]
    struct, _exp = _struct_and_exposure(facts, flags)
    assert struct < 100


def test_the_per_form_131_score_rises_for_an_el_only_umbrella_and_holds_for_a_full_one():
    el_only = _f(umbrella_sir="$10,000", employers_liability_limits=EL_TEXT)
    s, e = _struct_and_exposure(el_only, {**UMB, "has_workers_comp": True})
    assert s == 100 and e == 100
    full = _f(umbrella_sir="$10,000", gl_each_occurrence="$1,000,000",
              auto_liability_limit="$1,000,000", employers_liability_limits=EL_TEXT)
    flags = {**UMB, "has_general_liability": True, "has_auto_coverage": True,
             "has_workers_comp": True}
    assert _struct_and_exposure(full, flags) == (100, 100)
    missing_auto = dict(full, auto_liability_limit=None)
    s2, e2 = _struct_and_exposure(missing_auto, flags)
    assert s2 == 80 and e2 == 75                     # a carried line's gap still counts


# =============================================================================
# 7. The excess layer's copy follows the same door
# =============================================================================
_CE_FIXTURE = BACKEND / "tests" / "fixtures" / "choice_electric_pol_6oct.json"
EXCESS = "ACORD_131__excess"


@pytest.fixture(scope="module")
def tower():
    from services import extraction_service as es
    docs = copy.deepcopy(json.load(open(_CE_FIXTURE))["docs"])
    mf, flags = es.merge_facts(docs, es.select_primary_truth(docs))
    return mf, flags


def test_the_choice_electric_tower_is_identified_on_both_copies(tower):
    from services import form_instances as fi
    mf, flags = tower
    for fid in ("ACORD_131", EXCESS):
        view = fi.facts_for_form(mf, fid)
        uu = sq.umbrella_underlying(view, flags)
        assert uu["identified"] and uu["numeric"], fid
        assert uu["missing_scheduled"] == [], fid


def test_the_excess_copy_reads_the_layer_it_sits_on(tower):
    """Strip every underlying limit from the package: the umbrella layer has
    none (its copy and the package are hard-stopped), but the excess copy sits
    on the umbrella layer, whose $5,000,000 limit is known."""
    from services import form_instances as fi
    from services import umbrella_layers as ul
    mf, flags = tower
    bare = {k: v for k, v in mf.items() if k not in (
        "gl_each_occurrence", "gl_limits", "gl_aggregate", "auto_liability_limit",
        "auto_bi_per_person", "auto_bi_per_accident", "auto_pd_per_accident",
        "employers_liability_limits", "wc_el_each_accident", "wc_el_disease_each_employee",
        "wc_el_disease_policy_limit", "underlying_policies", "schedule_of_underlying_insurance")}
    bare.pop(ul.DOCS_KEY, None)
    plain = fi.facts_for_form(bare, "ACORD_131")
    excess = fi.facts_for_form(bare, EXCESS)
    assert (excess.get(ul.MARKER_KEY) or {}).get("index") == 1
    assert (excess[ul.MARKER_KEY].get("below") or {}).get("limit")
    assert sq.umbrella_underlying(plain, flags)["identified"] is False
    assert sq.umbrella_underlying(excess, flags)["identified"] is True
    assert NONE_STOP in sq.evaluate_stops(dict(TERM, **bare), {**flags, "has_umbrella": True})[0]
    uflags = {**flags, "has_umbrella": True}
    # The pillar may still reach 0 by accumulation (the excess's own limit and
    # every detail are stripped too) - that is the "supporting detail" warning,
    # never the broken-tower 60, on the copy whose underlying is known.
    res = sq.calculate_sqs(bare, uflags, {}, {}, ["ACORD_131", EXCESS], [], [], 0, form_id=EXCESS)
    assert GATE_HARD not in (res.get("cap_hard_stops") or [])
    assert res.get("cap_reason") != GATE_HARD
    base = sq.calculate_sqs(bare, uflags, {}, {}, ["ACORD_131", EXCESS], [], [], 0,
                            form_id="ACORD_131")
    assert base["cap_reason"] == GATE_HARD and base["cap_applied"] == sq.HARD_STOP_CAP


def test_a_view_with_no_layer_below_reads_nothing_from_it():
    for marker in ({"index": 0, "below": {"limit": "$5,000,000"}}, {"index": 1, "below": None},
                   {"index": None}, "x"):
        facts = _f(_umbrella_layer=marker)
        assert sq.umbrella_underlying(facts, UMB)["identified"] is False, marker


# =============================================================================
# 8. Wiring - the rule tables, the harvest and the other doors
# =============================================================================
def test_every_sentence_the_door_raises_opens_its_own_lines_box():
    for fam, _label in sq.UMB_UNDERLYING_LINES:
        box = resolution_for(classify_legacy(_sched_sentence(fam), "hard_stop")[0])
        assert box["mode"] == "field" and box["facts"][0] == (
            "gl_each_occurrence" if fam == "general_liab" else sq.UMB_UNDERLYING_FACT[fam])
    prefix_code = classify_legacy(SCHED_PREFIX, "hard_stop")[0]
    assert prefix_code == "legacy_umbrella_scheduled_limit_missing"
    for phrase, _cluster, _tier, code, _res in _LEGACY_MESSAGE_RULES:
        assert classify_legacy(phrase, "soft_warning")[0] == code, phrase


def test_every_box_these_windows_offer_is_one_a_person_can_answer():
    from services.answer_routing import answer_mode
    codes = ["legacy_umbrella_scheduled_gl_limit_missing",
             "legacy_umbrella_scheduled_auto_limit_missing",
             "legacy_umbrella_scheduled_el_limit_missing",
             "legacy_umbrella_scheduled_limit_missing", "legacy_umbrella_no_underlying",
             "legacy_umbrella_gate_no_underlying", "umbrella_no_underlying_coverage"]
    for code in codes:
        for fact in resolution_for(code)["facts"]:
            assert answer_mode(fact)["mode"] == "field", (code, fact)


def test_the_hard_stop_stays_hard_on_a_package_with_no_property():
    hard = [_sched_sentence("auto"), NONE_STOP]
    _can_warn, remaining, downgraded = sq.classify_stops(hard, {"has_umbrella": True})
    assert remaining == hard and downgraded == []


def test_the_new_hard_stop_site_is_harvested_and_has_a_fixture():
    """`test_legacy_rules.test_every_hard_stop_offers_a_real_fix` pins one
    fixture per `hard.append` site (Brent keeps the list short). The new site is
    the umbrella kind, line by line; its fixture must trip exactly it."""
    import tests.test_legacy_rules as tlr
    sites = tlr._hard_append_sites()
    fixtures = tlr._hard_stop_fixtures()
    assert len(sites) == len(fixtures)
    assert any(s[2] == SCHED_PREFIX for s in sites)
    facts, flags, opening = fixtures["a line the umbrella's own schedule lists with no limit"]
    hard, _soft = sq.evaluate_stops(facts, flags)
    assert len(hard) == 1 and hard[0].startswith(opening)
    assert SCHED_PREFIX in tlr._harvest_static_messages()


def test_no_reader_counts_gl_and_auto_alone_any_more():
    """The shape of the defect: a reader deciding "is there underlying?" from
    the GL and auto facts by itself. Every reader asks the door."""
    for fn in (sq._umbrella_has_underlying, sq._umbrella_underlying_stated,
               sq._get_umbrella_state, sq.umbrella_gap_items):
        assert "umbrella_underlying" in inspect.getsource(fn) or \
            "_umbrella_has_underlying" in inspect.getsource(fn), fn.__name__
    src = textwrap.dedent(inspect.getsource(sq.evaluate_stops))
    assert "umbrella_underlying(facts, flags)" in src
    assert "not _umbrella_underlying_stated(facts):\n        hard.append" not in src
    gate = textwrap.dedent(inspect.getsource(cfv._check_gl_missing_when_umbrella))
    assert "_umb_underlying(facts, flags)" in gate


def test_the_door_never_raises_on_malformed_input():
    for facts in (None, {}, {"underlying_policies": "x"}, {"underlying_policies": [None, 3, "a"]},
                  {"underlying_policies": {"value": [{"line": None, "limit": None}]}},
                  {"schedule_of_underlying_insurance": ["GL $1M", {"x": 1}, None]},
                  {"schedule_of_underlying_insurance": {"a": "GL $1M"}},
                  {"employers_liability_limits": {"value": ["$1M"]}},
                  {"_umbrella_layer": {"index": 2, "below": {"limit": ["x"]}}}):
        uu = sq.umbrella_underlying(facts, None)
        assert set(uu) >= {"identified", "numeric", "lines", "missing_scheduled",
                           "scheduled_to_confirm", "missing_carried"}
    assert ce.umbrella_schedule_lines(None)["stated"] is False


# =============================================================================
# 9. Review fixes (21 Oct) - H1 / M1-M4 / L2
# =============================================================================
@pytest.mark.parametrize("key", ["wc_el_each_accident", "wc_el_disease_each_employee",
                                 "wc_el_disease_policy_limit"])
def test_the_el_parts_extraction_writes_are_the_el_limit(key):
    """H1: extraction writes `wc_el_*` (the policies table's PRIMARY EL facts,
    `policy_lines.limit_facts`); `employers_liability_limits` is often the
    umbrella's REQUIRED figure. A listed WC row with a blank cell is no stop."""
    listed = _f(**{key: "$1,000,000"}, underlying_policies=[
        _row("Workers Compensation and Employers Liability", "")])
    flags = {**UMB, "has_workers_comp": True}
    uu = sq.umbrella_underlying(listed, flags)
    assert uu["identified"] and uu["missing_scheduled"] == [] and uu["missing_carried"] == []
    assert _umb_hard(listed, flags) == []
    assert EL_SOFT not in _stops(listed, flags)[1]
    alone = _f(**{key: "$1,000,000"})
    assert _umb_hard(alone, flags) == []
    assert not any(i["fact"] == "employers_liability_limits"
                   for i in sq.umbrella_deduction_items(alone, flags))
    codes = {i["code"] for i in cfv.run_cross_form_validation(
        dict(TERM, **alone), flags, {"ACORD_130", "ACORD_131"})}
    assert "umbrella_missing_employers_liability" not in codes
    assert "umbrella_no_underlying_coverage" not in codes


def test_the_per_line_keys_come_from_the_one_limit_table():
    from services.policy_lines import limit_facts
    for fam in ("general_liab", "workers_comp"):
        assert set(limit_facts()[fam]) <= set(sq._umb_line_fact_keys(fam))
    assert sq._umb_line_fact_keys("auto") == ("auto_liability_limit",)   # split read beside


def test_a_listed_gl_whose_limit_is_only_its_aggregate_is_no_stop():
    """M4: the GL limit stated only as gl_aggregate."""
    facts = _f(gl_aggregate="$2,000,000", underlying_policies=[_row("General Liability", "")])
    uu = sq.umbrella_underlying(facts, UMB)
    assert uu["identified"] and uu["missing_scheduled"] == []


def test_a_listed_gl_whose_limit_is_on_its_coverage_line_row_is_no_stop():
    """M4: the limit printed only on the line's own coverage_lines row."""
    facts = _f(coverage_lines=[{"line": "Commercial General Liability", "limit": "$1,000,000",
                                "carrier": "EMC", "policy_number": "BBC7263"}],
               underlying_policies=[_row("General Liability", "")])
    uu = sq.umbrella_underlying(facts, UMB)
    assert uu["identified"] and uu["missing_scheduled"] == []
    denied = _f(coverage_lines=[{"line": "General Liability", "limit": "$1,000,000",
                                 "premium": "No Coverage"}])
    assert sq.umbrella_underlying(denied, UMB)["lines"]["general_liab"]["fact_stated"] is False


@pytest.mark.parametrize("rows", [
    [{"line": "", "limit": "Each Occurrence $5,000,000"}],
    [{"line": None, "limit": "Aggregate $5,000,000"}],
    [{"line": "", "limit": "$5,000,000", "carrier": "ACME"}],      # the umbrella's own figure
])
def test_a_nameless_row_with_the_umbrellas_own_limit_is_not_underlying(rows):
    """M3: never identifies, and never softens a listed line's hard stop."""
    facts = _f(underlying_policies=rows)
    assert sq.umbrella_underlying(facts, UMB)["identified"] is False
    listed = _f(gl_each_occurrence="$1,000,000",
                underlying_policies=rows + [_row("Automobile Liability", "")])
    uu = sq.umbrella_underlying(listed, UMB)
    assert uu["missing_scheduled"] == ["auto"] and uu["scheduled_to_confirm"] == []


@pytest.mark.parametrize("text", ["Each Occurrence $5,000,000; Aggregate $5,000,000",
                                  "SIR $10,000", "$5,000,000"])
def test_a_nameless_text_segment_with_the_umbrellas_own_limit_is_not_underlying(text):
    facts = _f(umbrella_sir="$10,000", schedule_of_underlying_insurance=text)
    assert sq.umbrella_underlying(facts, UMB)["identified"] is False


def test_a_nameless_row_naming_a_policy_still_counts():
    facts = _f(underlying_policies=[{"line": "", "limit": "$1,000,000", "policy_no": "P-1"}])
    assert sq.umbrella_underlying(facts, UMB)["identified"] is True


@pytest.mark.parametrize("row", [
    _row("Auto Physical Damage", "$1,000 deductible"),
    _row("Automobile Liability", "Comprehensive $1,000 deductible"),
])
def test_a_physical_damage_row_is_not_an_auto_limit(row):
    """L2: a deductible is not an underlying liability limit."""
    facts = _f(underlying_policies=[row])
    uu = sq.umbrella_underlying(facts, UMB)
    assert uu["identified"] is False and uu["lines"]["auto"]["stated"] is False
