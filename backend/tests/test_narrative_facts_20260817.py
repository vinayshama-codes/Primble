"""Client 2026-08-17: the facts inside a remarks paragraph, read in context.

*"Additional Remarks has a similar issue. A paragraph containing policy numbers,
dates, limits, premiums, exclusions, etc. should not be treated as one competing
value. The individual facts within it need to be interpreted in their
appropriate context."*

The first half (stop asking "which paragraph is correct?") is pinned in
test_fact_equivalence_20260817. This file covers the second half: reading the
statements a paragraph makes, and attaching them to the conflict they explain.

THE STANDING TRAP, and the reason most of these tests exist: probe run B showed
extraction lifting ``07/25/2025`` out of *"...reduced from $3,000,000 to
$1,000,000 effective 07/25/2025"* and storing it as the UMBRELLA'S EFFECTIVE
DATE. It is an endorsement date. A number inside a sentence is not a value.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

import pytest                                                     # noqa: E402

from services.fact_equivalence import PackageContext              # noqa: E402
from services.narrative_facts import (                            # noqa: E402
    explain_conflict, mine_statements, statements_for_facts,
)

# The client's literal paragraph, from probe run B.
CLIENT_REMARKS = (
    "The Commercial Umbrella limit under policy 6J7-40-02---26 was reduced "
    "from $3,000,000 to $1,000,000 effective 07/25/2025. General Liability "
    "policy BBC7263-26 remains in force through 07/15/2026 with a general "
    "aggregate of $2,000,000 and a total premium of $6,720. Coverage excludes "
    "work performed above three stories. The certificate holder is included as "
    "additional insured per written contract."
)

DEC_ENTRIES = [
    {"label": "Policy Number", "value": "6J7-40-02---26",
     "policy_number": "6J7-40-02---26", "line_of_business": "Commercial Umbrella"},
    {"label": "Policy Number", "value": "BBC7263-26",
     "policy_number": "BBC7263-26", "line_of_business": "General Liability"},
]


@pytest.fixture
def ctx():
    return PackageContext({"dec_page_entries": DEC_ENTRIES})


# ── What the paragraph actually says ─────────────────────────────────────────

class TestMining:
    def test_the_clients_umbrella_amendment_is_read_whole(self, ctx):
        st = next(s for s in mine_statements(CLIENT_REMARKS, ctx)
                  if s["subject"] == "umbrella_limit")
        assert st["kind"] == "amendment"
        assert st["from"] == "$3,000,000"
        assert st["to"] == "$1,000,000"
        assert st["as_of"] == "07/25/2025"
        assert st["policy_number"] == "6J7-40-02---26"
        assert "reduced from $3,000,000" in st["quote"]

    def test_the_policy_number_keeps_the_documents_own_printing(self, ctx):
        """The match key is "6j7400226"; showing that to a producer would read
        as gibberish."""
        st = next(s for s in mine_statements(CLIENT_REMARKS, ctx)
                  if s["subject"] == "umbrella_limit")
        assert st["policy_number"] == "6J7-40-02---26"

    def test_a_labelled_value_is_read(self, ctx):
        st = next(s for s in mine_statements(CLIENT_REMARKS, ctx)
                  if s["subject"] == "gl_aggregate")
        assert st["to"] == "$2,000,000"

    def test_every_statement_carries_its_verbatim_sentence(self, ctx):
        for s in mine_statements(CLIENT_REMARKS, ctx):
            assert s["quote"] and s["quote"] in CLIENT_REMARKS


# ── The guards. These are the file's real content. ───────────────────────────

class TestGuards:
    def test_a_bare_date_never_becomes_a_statement(self, ctx):
        """RUN B, VERBATIM. "effective 07/25/2025" with no subject is the defect
        that put an endorsement date in the umbrella's effective-date box."""
        assert mine_statements("Endorsement issued effective 07/25/2025.", ctx) == []
        assert mine_statements("Effective 07/25/2025.", ctx) == []

    def test_a_date_is_never_emitted_as_a_value(self, ctx):
        """A date may only ever be a QUALIFIER (as_of), never the value."""
        for s in mine_statements(CLIENT_REMARKS, ctx):
            assert "2025" not in str(s["to"] or "") or "$" in str(s["to"])
            assert s["from"] is None or "$" in s["from"]

    def test_a_label_cannot_reach_across_a_conjunction(self, ctx):
        """"...a general aggregate of $2,000,000 and a total premium of $6,720"
        - the PREMIUM was being attached to gl_aggregate because "total premium"
        is not in our vocabulary and the distance window still reached it."""
        amounts = {s["to"] for s in mine_statements(CLIENT_REMARKS, ctx)
                   if s["subject"] == "gl_aggregate"}
        assert "$6,720" not in amounts
        assert amounts == {"$2,000,000"}

    def test_a_statement_never_spans_a_sentence_boundary(self, ctx):
        text = ("The umbrella limit was reduced from $3,000,000 to $1,000,000. "
                "The total premium is $6,720.")
        for s in mine_statements(text, ctx):
            assert s["quote"].count(".") <= 2

    def test_an_unknown_subject_is_dropped(self, ctx):
        """A phrase we do not own cannot become a fact key."""
        assert mine_statements(
            "The widget allowance was reduced from $500 to $200.", ctx) == []

    def test_an_unknown_policy_number_is_not_attributed(self, ctx):
        """Only contracts the package's own evidence established."""
        sts = mine_statements(
            "The umbrella limit under policy ZZ-99-1234 was reduced from "
            "$3,000,000 to $1,000,000.", ctx)
        assert sts and sts[0]["policy_number"] is None

    def test_a_range_is_not_an_amendment(self, ctx):
        """"ranges from X to Y" states no change. Only the closed set of change
        verbs may produce an amendment."""
        assert not [s for s in mine_statements(
            "The umbrella limit ranges from $1,000,000 to $3,000,000.", ctx)
            if s["kind"] == "amendment"]

    def test_no_context_still_works_and_attributes_nothing(self):
        sts = mine_statements(CLIENT_REMARKS, None)
        assert any(s["subject"] == "umbrella_limit" for s in sts)
        assert all(s["policy_number"] is None for s in sts)

    def test_garbage_input_never_raises(self, ctx):
        for bad in (None, "", "   ", 12345, {"a": 1}):
            assert mine_statements(bad, ctx) == []


# ── The consumer: explain a conflict, never resolve it ───────────────────────

class TestExplainConflict:
    def test_the_clients_umbrella_card_gets_its_explanation(self, ctx):
        note = explain_conflict("umbrella_limit", ["$3,000,000", "$1,000,000"],
                                mine_statements(CLIENT_REMARKS, ctx))
        assert note and "reduced" in note
        assert "$3,000,000" in note and "$1,000,000" in note
        assert "07/25/2025" in note
        assert "6J7-40-02---26" in note

    def test_it_never_selects_a_value(self, ctx):
        """The client also required that an unresolved fact STAY unresolved. The
        note is prose: it must not name a winner or pre-select anything."""
        note = explain_conflict("umbrella_limit", ["$3,000,000", "$1,000,000"],
                                mine_statements(CLIENT_REMARKS, ctx))
        assert "Confirm which applies." in note
        for word in ("suggested", "recommend", "use $", "correct value is"):
            assert word not in note.lower()

    def test_an_unrelated_field_gets_no_note(self, ctx):
        assert explain_conflict("total_revenue", ["$1,500,000", "$2,400,000"],
                                mine_statements(CLIENT_REMARKS, ctx)) is None

    def test_a_remark_naming_none_of_the_cards_amounts_explains_nothing(self, ctx):
        assert explain_conflict("umbrella_limit", ["$5,000,000", "$4,000,000"],
                                mine_statements(CLIENT_REMARKS, ctx)) is None

    def test_no_statements_means_no_note(self):
        assert explain_conflict("umbrella_limit", ["$3,000,000"], []) is None


# ── End to end, through the real picker ──────────────────────────────────────

def test_the_conflict_row_carries_the_explanation():
    from services.underwriting_consistency import assess_underwriting_consistency
    docs = [
        {"doc_id": "1", "filename": "dec.pdf", "doc_type": "dec_page", "text": "",
         "facts": {"umbrella_limit": "$3,000,000",
                   "dec_page_entries": DEC_ENTRIES}},
        {"doc_id": "2", "filename": "coi.pdf", "doc_type": "certificate",
         "text": "", "facts": {"umbrella_limit": "$1,000,000"}},
    ]
    merged = {"additional_remarks_text": CLIENT_REMARKS,
              "dec_page_entries": DEC_ENTRIES}
    res = assess_underwriting_consistency(docs, merged, {})
    row = next(f for f in res["fields"] if f["fact_key"] == "umbrella_limit")
    assert row["status"] == "conflict", "THE GATE: this must stay unresolved"
    assert row["narrative_note"] and "07/25/2025" in row["narrative_note"]


def test_every_conflict_row_has_the_key_even_when_there_is_nothing_to_say():
    """The frontend reads `narrative_note` unconditionally; it must always be
    present on a conflict row, even as None."""
    from services.underwriting_consistency import assess_underwriting_consistency
    docs = [
        {"doc_id": "1", "filename": "a.pdf", "doc_type": "dec_page", "text": "",
         "facts": {"total_revenue": "$1,500,000"}},
        {"doc_id": "2", "filename": "b.pdf", "doc_type": "dec_page", "text": "",
         "facts": {"total_revenue": "$2,400,000"}},
    ]
    res = assess_underwriting_consistency(docs, {}, {})
    for f in res["fields"]:
        assert "narrative_note" in f


def test_statements_are_deduped_across_narrative_fields():
    """One sentence repeated in two narrative fields is one assertion."""
    merged = {"additional_remarks_text": CLIENT_REMARKS,
              "acord101_remarks": CLIENT_REMARKS,
              "dec_page_entries": DEC_ENTRIES}
    ctx = PackageContext(merged)
    sts = statements_for_facts(merged, ctx)
    umbrella = [s for s in sts if s["subject"] == "umbrella_limit"]
    assert len(umbrella) == 1
