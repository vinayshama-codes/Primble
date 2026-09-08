"""
The no-loss SENTENCE must never print as a claim on the form (live 2026-09-08).

WHAT WAS ON THE SCREEN
----------------------
ACORD 125, claim row A, on a package with no claims:

    TYPE / DESCRIPTION OF OCCURRENCE OR CLAIM
    "The applicant has had no known losses in the past five years."
    SUBROGATION Y/N  N        CLAIM OPEN Y/N  N

Those are real values in real row-A cells, so the missing-field highlighter then
marked the REST of the row required - the producer was asked for a date of
occurrence, a claim date, a paid amount and a reserve for a claim that does not
exist.

ROOT CAUSE - A GATE IN THE WRONG LAYER
--------------------------------------
The extraction model writing that sentence into the `loss_history` table was
found and gated on 2026-09-05 (`loss_history_state._row_states_a_claim`). The
gate went into the SCORING module, and the ACORD stamper binds
`LossHistory_OccurrenceDescription` straight to
`facts["loss_history"][i]["description"]` through `_SCHEDULE_REGISTRY` with no
filter at all. So the scorer discounted the row and the form printed it. Third
time on this project a fix has landed in a layer the screen does not read.

THE FIX
-------
`loss_history_state.claim_rows` is the public face of the existing gate, and
`pdf_service._countable_schedule_rows` is consulted by BOTH row doors:

    _resolve_schedule_row           what gets stamped into a row
    _resolve_phantom_schedule_row   which rows exist at all

They have to agree. Filtering only the first would leave the phantom resolver
believing row A is real, the emptied row would fall through to GAP FILL, and the
model would be invited to invent the claim we just removed - worse than the
defect. `test_the_two_row_doors_can_never_disagree` is that invariant.

Run from backend/:
    python -m pytest tests/test_loss_row_is_a_claim.py -v
"""

import os
import random
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.loss_history_state import attested_true, claim_rows  # noqa: E402
from services.pdf_service import (  # noqa: E402
    _ACORD125_LOSS_ROW_FIELDS,
    _SCHED_SKIP,
    _attests_no_loss,
    _countable_schedule_rows,
    _resolve_phantom_schedule_row,
    _resolve_schedule_row,
    apply_acord125_missing_field_highlights,
)

# The exact sentence the live run printed.
SENTENCE = "The applicant has had no known losses in the past five years."

DESC_A = "LossHistory_OccurrenceDescription_A"
DESC_B = "LossHistory_OccurrenceDescription_B"
DATE_A = "LossHistory_OccurrenceDate_A"
PAID_A = "LossHistory_PaidAmount_A"
SUBRO_A = "LossHistory_ClaimStatus_SubrogationCode_A"
OPEN_A = "LossHistory_ClaimStatus_OpenCode_A"

REAL_CLAIM = {"date": "03/14/2024", "description": "Slip and fall at job site",
              "paid": 12000, "reserved_amount": 0}

ALL_LOSS_ROW_FIELDS = {t.format(row=r) for t in _ACORD125_LOSS_ROW_FIELDS
                       for r in ("A", "B", "C")}


def _facts(rows):
    return {"loss_history": rows}


# ── 1. The reported case ─────────────────────────────────────────────────────

def test_the_no_loss_sentence_does_not_print_as_a_claim_description():
    assert _resolve_schedule_row(DESC_A, _facts([{"description": SENTENCE}])) is None


def test_the_sentence_row_takes_its_status_cells_with_it():
    """SUBRO N / CLAIM OPEN N came from the SAME phantom row and printed too."""
    facts = _facts([{"description": SENTENCE,
                     "subrogation_code": "N", "open_code": "N"}])
    for field in (DESC_A, SUBRO_A, OPEN_A):
        assert _resolve_schedule_row(field, facts) is None, field


def test_a_sentence_only_schedule_leaves_no_yellow_claim_cell():
    """End to end through the highlighter: the reported symptom is gone."""
    state = {f: "" for f in ALL_LOSS_ROW_FIELDS}
    state.update({"LossHistory_NoPriorLossesIndicator_A": "",
                  "LossHistory_InformationYearCount_A": "5",
                  "LossHistory_TotalAmount_A": "0"})
    conf = {k: "low_confidence" for k in state}
    out = apply_acord125_missing_field_highlights("ACORD_125", {}, dict(state), conf)
    assert not {k for k, v in out.items()
                if v == "missing_required"} & ALL_LOSS_ROW_FIELDS


# ── 2. Everything that WAS working still works ───────────────────────────────

def test_a_real_claim_still_prints():
    facts = _facts([REAL_CLAIM])
    assert _resolve_schedule_row(DESC_A, facts) == "Slip and fall at job site"
    assert _resolve_schedule_row(DATE_A, facts) == "03/14/2024"


def test_a_real_claim_row_still_drives_the_required_highlight():
    state = {f: "" for f in ALL_LOSS_ROW_FIELDS}
    state[DATE_A] = "03/14/2024"
    conf = {k: "low_confidence" for k in state}
    out = apply_acord125_missing_field_highlights("ACORD_125", {}, dict(state), conf)
    required = {k for k, v in out.items() if v == "missing_required"}
    expected = {t.format(row="A") for t in _ACORD125_LOSS_ROW_FIELDS} - {DATE_A}
    assert expected <= required


def test_money_always_wins_over_no_loss_wording():
    """A row carrying a real amount is a claim whatever its description says -
    the rule `_row_states_a_claim` already owned, preserved through the stamper."""
    facts = _facts([{"description": "no known losses", "paid": 5000}])
    assert _resolve_schedule_row(DESC_A, facts) == "no known losses"


def test_a_real_claim_behind_a_sentence_row_moves_up_into_row_A():
    """Rows are DROPPED, not blanked - the form expects the first claim in row A."""
    facts = _facts([{"description": SENTENCE}, REAL_CLAIM])
    assert _resolve_schedule_row(DESC_A, facts) == "Slip and fall at job site"
    assert _resolve_schedule_row(DESC_B, facts) is None


def test_no_loss_history_fact_changes_nothing():
    """No schedule at all is NOT evidence of an empty schedule."""
    assert _resolve_phantom_schedule_row(DESC_A, {}) is _SCHED_SKIP
    assert _resolve_phantom_schedule_row(DESC_A, {"loss_history": []}) is _SCHED_SKIP


@pytest.mark.parametrize("list_key,rows", [
    ("auto_vin_schedule", [{"vin": "4S4BRCGC9C3217772", "year": "2012"}]),
    ("driver_schedule", [{"name": "A Driver", "dob": "01/01/1980"}]),
    ("property_locations", [{"line1": "1 Mill Road", "city": "Akron"}]),
])
def test_other_schedules_are_untouched(list_key, rows):
    assert _countable_schedule_rows(list_key, rows) is rows


# ── 3. THE INVARIANT - the two doors can never disagree ──────────────────────

def test_the_two_row_doors_can_never_disagree():
    """If a loss row is filtered away, the phantom door must call the cell an
    OWNED BLANK, never `_SCHED_SKIP`.

    `_SCHED_SKIP` there means "normal handling", and for an unmatched field
    normal handling is GAP FILL - so the model would be asked to supply the
    claim the filter just removed. That is worse than the bug being fixed."""
    shapes = [
        [{"description": SENTENCE}],
        [{"description": "No Known Losses"}],
        [{"description": "loss-free"}],
        [{"description": SENTENCE, "subrogation_code": "N", "open_code": "N"}],
        [{"description": SENTENCE}, {"description": "no prior losses or claims"}],
    ]
    for rows in shapes:
        facts = _facts(rows)
        assert claim_rows(rows) == [], rows
        for field in (DESC_A, DATE_A, PAID_A, SUBRO_A, OPEN_A):
            assert _resolve_schedule_row(field, facts) is None, (field, rows)
            assert _resolve_phantom_schedule_row(field, facts) is None, (field, rows)


def test_a_schedule_that_still_has_a_claim_keeps_normal_handling():
    facts = _facts([{"description": SENTENCE}, REAL_CLAIM])
    assert _resolve_phantom_schedule_row(DESC_A, facts) is _SCHED_SKIP
    assert _resolve_phantom_schedule_row(DESC_B, facts) is None    # beyond capacity


# ── 3b. THE REGRESSION THIS FIX CAUSED ONCE - a summary box is not a cell ────

_SUMMARY_BOXES = ("LossHistory_InformationYearCount_A",    # "FOR THE LAST n YEARS"
                  "LossHistory_TotalAmount_A",             # "TOTAL LOSSES"
                  "LossHistory_NoPriorLossesIndicator_A")  # "Check if none"


@pytest.mark.parametrize("field", _SUMMARY_BOXES)
def test_a_claimless_table_does_not_blank_the_section_summary_boxes(field):
    """LIVE REGRESSION, 2026-09-08, caught on the very next run.

    `_resolve_phantom_schedule_row` identifies a field by its ROOT WORD, and the
    LossHistory root also carries three SECTION SUMMARY boxes. The first cut of
    the empty-table rule blanked them too, so a stated 5-year loss period and
    the total vanished off the form - real extracted data destroyed. It is the
    SAME row-versus-summary confusion as BUG-04 itself, reintroduced by BUG-04's
    own fix one resolver over. The registry now decides: only a field that binds
    to a schedule COLUMN is a cell of the table."""
    facts = _facts([{"description": SENTENCE}])
    assert _resolve_phantom_schedule_row(field, facts) is _SCHED_SKIP


def test_the_cell_or_summary_split_is_read_off_the_registry():
    """Derived, not listed: every LossHistory field on the REAL ACORD 125 schema
    is judged by whether it binds to a `_SCHEDULE_REGISTRY` column, so a field
    added to either side cannot quietly change class."""
    from services.pdf_service import _all_form_schemas, _schedule_def_for_base
    schema = _all_form_schemas().get("ACORD_125") or {}
    assert schema, "ACORD_125 schema did not load"
    facts = _facts([{"description": SENTENCE}])
    for name in schema:
        if not name.startswith("LossHistory_") or name[-2] != "_":
            continue
        binds = _schedule_def_for_base(name[:-2]) is not None
        got = _resolve_phantom_schedule_row(name, facts)
        if binds:
            assert got is None, f"{name} is a table cell and must be an owned blank"
        else:
            assert got is _SCHED_SKIP, f"{name} is a summary box and must be left alone"


# ── 4. The two attestation parsers now agree, and must keep agreeing ─────────

_ATTESTATION_VOCABULARY = [
    "Yes", "yes", "Y", "true", "1", "on", "No", "no", "false", "0", "Off", "",
    "None", "none", "N/A", "Zero claims", "loss free", "loss-free",
    "clean loss history", "no known losses", "No known losses",
    "no prior losses or claims in the last five years",
    "No - no claims or losses in the past 5 years",
    "Yes - we have had claims or losses",
    True, False, None, 0, 1,
]


@pytest.mark.parametrize("value", _ATTESTATION_VOCABULARY)
def test_the_box_and_the_score_read_the_same_parser(value):
    """`_attests_no_loss` delegates to `attested_true`; its old local copy said
    it "mirrors" it and did not - "None" / "loss free" / "Zero claims" scored 60
    while the box printed UNTICKED, i.e. the form asserted the opposite of the
    score on a human's own answer."""
    assert _attests_no_loss(value) == attested_true(value), value


# ── 5. Fuzz - a real loss table can hold anything ────────────────────────────

_CELL_VALUES = [
    None, "", "   ", "0", "$0", "12,500", "$1,200.00", 5000, 0, 12.5, True, False,
    "03/14/2024", "Slip and fall at job site", SENTENCE, "No Known Losses",
    "loss-free", "no injuries reported on this claim", "N", "Y", "Open", "Closed",
    "éàü", "a" * 300, "<script>", "'; DROP TABLE", "unknown", "TBD",
]
_COLUMNS = ["date", "claim_date", "description", "amount", "paid",
            "reserved_amount", "line_of_business", "open_code",
            "subrogation_code", "claim_number"]


def test_fuzz_the_stamper_never_prints_a_row_the_gate_rejects():
    rng = random.Random(20260908)
    for _ in range(6000):
        rows = []
        for _r in range(rng.randint(1, 3)):
            rows.append({c: rng.choice(_CELL_VALUES)
                         for c in rng.sample(_COLUMNS, rng.randint(0, len(_COLUMNS)))})
        facts = _facts(rows)
        kept = claim_rows(rows)
        value = _resolve_schedule_row(DESC_A, facts)
        if not kept:
            assert value is None, rows
            assert _resolve_phantom_schedule_row(DESC_A, facts) is None, rows
        elif isinstance(kept[0].get("description"), str) and kept[0]["description"].strip():
            assert value == kept[0]["description"], rows


def test_fuzz_never_raises_on_a_malformed_schedule():
    rng = random.Random(3)
    junk = [None, [], {}, "", "a string", 5, [None], [[]], [{"description": None}],
            [1, 2, 3], {"description": SENTENCE}, [{"description": SENTENCE}, None]]
    for rows in junk:
        for _ in range(3):
            facts = {"loss_history": rows}
            try:
                _resolve_schedule_row(DESC_A, facts)
                _resolve_phantom_schedule_row(DESC_A, facts)
                _countable_schedule_rows("loss_history", rows)
            except Exception as exc:                            # noqa: BLE001
                pytest.fail(f"raised on {rows!r}: {exc}")
        rng.random()


# ── 6. The pipeline's no-loss flag derivation is two-way ─────────────────────

def test_the_pipeline_flag_derivation_sets_no_prior_losses_in_both_directions():
    """`extraction_pipeline` used to RAISE `no_prior_losses` and never lower it,
    while both `arq_service` writers have always been two-way. Unreachable today
    (`mflags` is rebuilt per run and the flags column is replaced wholesale), so
    this is an intent pin rather than a bug test - driven by AST because the
    derivation is inline in an async pipeline function.

    The `else` must be CONDITIONAL: an ABSENT fact leaves the flag alone.
    Inventing a False from silence is what Principle 3 forbids, and D-BO is the
    same rule one layer down."""
    import ast
    import pathlib

    src = pathlib.Path(__file__).resolve().parents[1] / "services" / "extraction_pipeline.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))

    def _writes_flag(stmts, value):
        for node in stmts:
            for sub in ast.walk(node):
                if not isinstance(sub, ast.Assign):
                    continue
                for target in sub.targets:
                    if (isinstance(target, ast.Subscript)
                            and isinstance(target.value, ast.Name)
                            and target.value.id == "mflags"
                            and isinstance(target.slice, ast.Constant)
                            and target.slice.value == "no_prior_losses"
                            and isinstance(sub.value, ast.Constant)
                            and sub.value.value is value):
                        return True
        return False

    raising = [n for n in ast.walk(tree)
               if isinstance(n, ast.If) and _writes_flag(n.body, True)]
    assert raising, "nothing raises no_prior_losses"

    lowered_conditionally = False
    for node in raising:
        # The lowering must live in an `elif` - a bare `else` would invent a
        # False from an ABSENT fact, which is exactly what Principle 3 forbids.
        for alt in node.orelse:
            if isinstance(alt, ast.If) and _writes_flag(alt.body, False):
                lowered_conditionally = True
    assert lowered_conditionally, (
        "no_prior_losses is raise-only, or is lowered by an unconditional else - "
        "it must drop only when the fact is PRESENT and says no"
    )


# ── 7. Found by adversarial review, 2026-09-08 - three defects the fixes caused ──

@pytest.mark.parametrize("text", [
    "No losses over the past five years",
    "No known losses over the last 5 years",
    "no losses over the prior policy term",
    "no claims above the previous three years",
])
def test_a_time_phrase_is_not_a_money_threshold(text):
    """`_NO_LOSS_QUALIFIERS` lists "over" to catch "no losses over $10,000", and
    nothing checked that a FIGURE followed - so the far commoner time phrasing
    was discarded. It only became visible when `_attests_no_loss` began
    delegating here: the ACORD 125 "Check if none" box went from ticked to
    printing an explicit **No**, a signed form asserting the opposite of what
    the producer typed."""
    from services.normalization import detect_no_loss_assertion
    assert detect_no_loss_assertion(text.lower()) is True, text
    assert _attests_no_loss(text) is True, text


@pytest.mark.parametrize("text", [
    "no losses over $10,000",
    "no losses exceed $10,000",
    "no losses above $25,000",
    "no claims in excess of $50,000",
    "no losses greater than $1,000",
])
def test_a_real_money_threshold_is_still_refused(text):
    """The guard this fix narrowed must keep doing its job: a threshold means
    losses EXIST and are capped, which is the opposite of a no-loss assertion."""
    from services.normalization import detect_no_loss_assertion
    assert detect_no_loss_assertion(text.lower()) is False, text


@pytest.mark.parametrize("row", [
    {"claim_number": "88213", "claim_date": "03/14/2024", "open_code": "Y"},
    {"claim_number": "C-99"},
    {"claim_date": "01/02/2025"},
])
def test_a_row_named_by_claim_number_or_date_is_printed(row):
    """`_row_states_a_claim` reads money and date/description/line_of_business
    only. Extraction also emits rows keyed on claim_number / claim_date, and
    those were being DELETED off the printed form - real extracted claims lost.
    "Blank over wrong" does not cover deleting a real value."""
    assert claim_rows([row]) == [row]
    assert _resolve_schedule_row("LossHistory_ClaimNumber_A", _facts([row])) == (
        row.get("claim_number") if row.get("claim_number") else None)


@pytest.mark.parametrize("row", [
    {"description": SENTENCE, "subrogation_code": "N", "open_code": "N"},
    {"open_code": "N"},
    {"subrogation_code": "N"},
    {"open": "Closed"},
])
def test_a_status_column_is_not_claim_identity(row):
    """The live phantom row carries open_code "N" beside its no-loss sentence.
    Admitting status columns as identity would make that sentence a claim again
    and undo both the 2026-09-05 conflict fix and this one. Only a claim NUMBER
    or claim DATE - identifiers a narrative sentence never produces - count."""
    assert claim_rows([row]) == []


def test_the_scorers_definition_of_a_claim_was_not_widened():
    """The identity rule lives on the PRINTING side. If it leaked into
    `_row_states_a_claim`, the scorer would start counting the phantom row as a
    claim and the false loss conflict would return."""
    from services.loss_history_state import _row_states_a_claim
    assert _row_states_a_claim(
        {"claim_number": "88213", "claim_date": "03/14/2024"}) is False
    assert _row_states_a_claim(
        {"description": SENTENCE, "open_code": "N"}) is False


def test_the_overflow_remark_counts_the_same_rows_the_grid_prints():
    """The THIRD door. `_resolve_loss_overflow_remark` names the claims that did
    not fit the grid; reading the RAW list made it announce an overflow claim the
    grid no longer carries."""
    import ast
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "services" / "pdf_service.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef)
              and n.name == "_resolve_loss_overflow_remark")
    called = {n.func.id for n in ast.walk(fn)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "_countable_schedule_rows" in called, (
        "_resolve_loss_overflow_remark reads the loss list without the filter - "
        "it will name a claim the grid does not print"
    )


# ── 8. The open question: free text can say anything ────────────────────────
#
# "clean loss history apart from a $40,000 fire in 2023" attested - the phrase
# scan read three words and stopped. The answer is NOT a longer list of
# exception words ("apart from", "except", "other than", ...) - that set is open
# and you are always one phrasing behind. Two structural changes instead:
#
#   1. CLOSED INPUT - ALREADY SHIPPED, and NOT extended here. `answer_options`
#      gives this fact two options and no "Other", so `control_for` renders a
#      SELECT in both the questionnaire and the Resolve card: a producer cannot
#      type at it. Hard-refusing off-list text at the storage layer was built,
#      then REVERTED - `test_none_fills_a_negative_polarity_fact` encodes a
#      deliberate decision that "None" / "loss free" are the affirmative answer
#      on a negative-polarity fact, and overturning a product decision is not a
#      cleanup. The contradiction rule below closes the reported defect without
#      touching it.
#   2. SELF-CONTRADICTION. A no-loss claim carrying a non-zero loss AMOUNT in its
#      own clause contradicts itself, whatever words join the two halves.
#
# Neither claims to read arbitrary prose correctly. The guarantee is the failure
# direction: what is not read confidently ends blank and asked, never a false
# "yes" on a signed form.

_CLOSED_FACT = "loss_history_no_prior_losses_indicator"


@pytest.mark.parametrize("text", [
    "clean loss history apart from a $40,000 fire in 2023",
    "Loss-free except for one auto claim of $12,500 last year",
    "No claims other than a $3,200 water damage loss",
    "no known losses, aside from the $18,000 theft in March",
])
def test_a_no_loss_claim_carrying_a_loss_amount_contradicts_itself(text):
    from services.normalization import detect_no_loss_assertion
    assert detect_no_loss_assertion(text.lower()) is False, text


@pytest.mark.parametrize("text", [
    "no known losses",
    "clean loss history",
    "No claims or accidents in the past 5 years",   # peril words must NOT refuse
    "No losses over the past five years",
    "loss-free since 2019",
    "no losses, total incurred $0",                 # a stated zero is not a loss
    "No known losses. Building value $1,200,000.",  # amount in ANOTHER sentence
])
def test_a_genuine_no_loss_statement_still_attests(text):
    from services.normalization import detect_no_loss_assertion
    assert detect_no_loss_assertion(text.lower()) is True, text


def test_the_document_path_can_never_tick_the_box():
    """A sentence in an uploaded document is a HINT, not an attestation. It can
    reach the narrative tier and nothing more - only a human pressing a button
    reaches 60 and prints on the form."""
    from services.sqs_service import calculate_p4_loss_history
    from services.pdf_service import no_loss_attestation_verdict
    flags = {"narrative_states_no_losses": True}
    assert no_loss_attestation_verdict({**flags}) is None
    assert calculate_p4_loss_history({}, dict(flags))[0] == 40


def test_the_fire_sentence_end_to_end():
    """The reported string, all the way through: no tick, no attested score."""
    from services.sqs_service import calculate_p4_loss_history
    from services.pdf_service import no_loss_attestation_verdict
    facts = {_CLOSED_FACT: {
        "value": "clean loss history apart from a $40,000 fire in 2023",
        "source": "producer"}}
    assert no_loss_attestation_verdict(dict(facts)) == "No"
    assert calculate_p4_loss_history(dict(facts), {})[0] == 25


@pytest.mark.parametrize("text,kw,counts", [
    ("loss runs were never provided", "loss runs", False),
    ("we never received loss runs", "loss runs", False),
    ("loss runs were provided", "loss runs", True),
])
def test_never_denies_on_both_sides_of_the_phrase(text, kw, counts):
    """"never" was a negation before the phrase and not after it - one rule
    disagreeing with itself, not a missing vocabulary entry."""
    from services.extraction_service import _phrase_counts
    assert _phrase_counts(text, kw) is counts, text


# ── 9. The gap the money rule cannot see: an exception with no figure ────────
#
# "clean loss history apart from one fire" carries no amount, so nothing
# contradicts the phrase. It was first written off as unfixable on the grounds
# that exception wording is infinite. THAT WAS WRONG, and the correction is the
# whole point: what is infinite is the LOSS ("a fire", "the forklift thing") -
# which is why no list of perils can work and why the money rule names none. The
# words that JOIN "everything clean" to "this one thing" are a CLOSED
# grammatical class - exceptive prepositions and conjunctions, roughly fifteen
# of them, and English coins no more.

@pytest.mark.parametrize("text", [
    "clean loss history apart from one fire",
    "loss-free except for a minor auto incident",
    "no known losses other than the 2023 water event",
    "no claims besides the forklift thing",
    "clean loss record with the exception of one slip and fall",
    "no losses barring a small theft",
    "loss free save for one windscreen claim",
    "no claims excluding the roof repair",
])
def test_an_exception_with_no_figure_is_still_caught(text):
    from services.normalization import detect_no_loss_assertion
    assert detect_no_loss_assertion(text.lower()) is False, text


@pytest.mark.parametrize("text", [
    "No claims or accidents in the past 5 years",   # THE CONTROL - a coordination
    "no losses reported for the policy period",     # inside the negation's scope
    "No known losses in the past five years, per the insured",
    "no known losses",
    "clean loss history",
])
def test_a_coordination_or_qualifier_is_not_an_exception(text):
    """"no claims OR ACCIDENTS" is the negation listing what it covers, not
    carving something out of it. This case is what killed the peril-word
    approach and it is the control for the exceptive one."""
    from services.normalization import detect_no_loss_assertion
    assert detect_no_loss_assertion(text.lower()) is True, text


def test_the_two_rules_are_independent():
    """Money catches an exception that names a figure whatever joins it;
    grammar catches one that names none. Neither is load-bearing alone."""
    from services.normalization import detect_no_loss_assertion as d
    assert d("no losses, however there was a claim of $9,500") is False   # money only
    assert d("clean loss history apart from one fire") is False           # grammar only
