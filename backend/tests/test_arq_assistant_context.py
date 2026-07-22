"""Figure 19: the Form Assistant must be context-aware and stay in its lane.

Before this, the assistant received only a flat list of question texts - so it
could not resolve "where do I find this?" to a field, did not know what shape of
answer a field accepted, and had no guardrail against giving coverage advice.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from routes.arq_routes import (  # noqa: E402
    _ARQ_ASSISTANT_RULES,
    _ASSISTANT_MAX_LISTED_QUESTIONS,
    _assistant_field_block,
    _assistant_package_context,
    _assistant_question_list,
)


# --------------------------------------------------------------------------
# The focused field is described in full
# --------------------------------------------------------------------------

def test_field_block_carries_id_hint_and_answer_type():
    block = _assistant_field_block({
        "question":    "Do you know your business's NAICS code?",
        "field_name":  "naics_code",
        "field_type":  "code",
        "code_digits": 6,
        "hint":        "This is a 6-digit industry code - leave blank if unsure.",
        "forms":       "ACORD 125",
    })
    assert "naics_code" in block                    # question id reaches the model
    assert "6-digit industry code" in block         # on-screen guidance is reused
    assert "exactly 6 digits" in block              # length rule is explicit
    assert "ACORD 125" in block


def test_field_block_lists_select_options_verbatim():
    """A select field must never get a suggestion that is not on the list."""
    block = _assistant_field_block({
        "question":   "How urgent is this submission?",
        "field_name": "submission_urgency",
        "field_type": "select",
        "options":    ["Standard", "Rush", "Other"],
    })
    assert "ONLY THESE ANSWERS ARE ACCEPTED" in block
    for opt in ("Standard", "Rush", "Other"):
        assert opt in block


def test_field_block_survives_a_bare_question():
    """Questions carry optional keys; a minimal one must not raise."""
    block = _assistant_field_block({"question": "Q?", "field_name": "f"})
    assert "ANSWER TYPE: free text" in block


# --------------------------------------------------------------------------
# The roster flags the focused question
# --------------------------------------------------------------------------

def test_question_list_marks_only_the_focused_question():
    qs = [
        {"question": "What is your business name?", "field_name": "applicant_name"},
        {"question": "Do you know your NAICS code?", "field_name": "naics_code"},
    ]
    listed = _assistant_question_list(qs, active_q=qs[1])
    lines  = listed.splitlines()
    assert "CLIENT IS LOOKING AT THIS ONE" not in lines[0]
    assert "CLIENT IS LOOKING AT THIS ONE" in lines[1]
    # The stable id travels with every question, not just the focused one.
    assert "[id: applicant_name]" in listed


def test_question_list_without_focus_marks_nothing():
    qs = [{"question": "What is your business name?", "field_name": "applicant_name"}]
    assert "CLIENT IS LOOKING AT" not in _assistant_question_list(qs, None)


def test_question_list_is_bounded_and_says_so():
    """A runaway roster is what makes these prompts expensive."""
    qs = [{"question": f"Q{i}", "field_name": f"f{i}"} for i in range(_ASSISTANT_MAX_LISTED_QUESTIONS + 25)]
    listed = _assistant_question_list(qs, None)
    assert listed.splitlines()[-1] == "...and 25 more questions."


def test_question_list_carries_options_for_unfocused_selects():
    """The model must never invent an option for a field it is not focused on."""
    qs = [{"question": "How urgent?", "field_name": "urgency",
           "field_type": "select", "options": ["Standard", "Rush"]}]
    listed = _assistant_question_list(qs, None)
    assert "Standard" in listed and "Rush" in listed


def test_question_list_omits_runaway_option_lists():
    qs = [{"question": "Pick one", "field_name": "f", "field_type": "select",
           "options": [f"opt{i}" for i in range(30)]}]
    assert "opt29" not in _assistant_question_list(qs, None)


def test_question_list_clips_long_question_text():
    qs = [{"question": "x" * 400, "field_name": "f"}]
    assert "..." in _assistant_question_list(qs, None)
    assert len(_assistant_question_list(qs, None)) < 250


# --------------------------------------------------------------------------
# Package context is best-effort and must never break chat
# --------------------------------------------------------------------------

def test_package_context_lists_forms_without_touching_the_database():
    arq = {"questions": [
        {"field_name": "a", "forms": "ACORD 125, ACORD 126"},
        {"field_name": "b", "forms": "ACORD 126"},
    ]}
    ctx = asyncio.run(_assistant_package_context(arq))
    assert "ACORD 125" in ctx and "ACORD 126" in ctx
    assert ctx.count("ACORD 126") == 1          # deduplicated


def test_package_context_swallows_a_missing_session():
    """A dead session_id must degrade to less context, never to a failed chat."""
    arq = {"questions": [], "session_id": "does-not-exist"}
    ctx = asyncio.run(_assistant_package_context(arq))
    assert isinstance(ctx, str)


# --------------------------------------------------------------------------
# Guardrails
# --------------------------------------------------------------------------

def test_rules_ban_coverage_advice():
    rules = _ARQ_ASSISTANT_RULES.lower()
    for banned in ("never recommend coverage", "limits", "deductibles", "carriers"):
        assert banned in rules


def test_rules_ban_inventing_values_and_claiming_to_act():
    rules = _ARQ_ASSISTANT_RULES.lower()
    assert "never state a specific code" in rules
    assert "never claim to fill in" in rules


def test_rules_resolve_unqualified_questions_to_the_current_field():
    """The exact screenshot case: "where do I find this?" must not be refused."""
    rules = _ARQ_ASSISTANT_RULES.lower()
    assert "where do i find this?" in rules
    assert "do not ask them which question they mean" in rules


def test_rules_forbid_markdown():
    """The chat bubble renders plain text - Markdown reaches the client as
    literal asterisks."""
    rules = _ARQ_ASSISTANT_RULES.lower()
    assert "plain text only" in rules
    assert "markdown" in rules


def test_rules_permit_leaving_a_question_blank():
    assert "blank" in _ARQ_ASSISTANT_RULES.lower()
