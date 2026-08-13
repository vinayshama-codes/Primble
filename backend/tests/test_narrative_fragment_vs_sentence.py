"""A repeated truncated header must not out-vote a real sentence.

MEASURED ON THE CLIENT'S REAL 271-PAGE PACKAGE, 2026-08-12. Verbatim from the
run log:

    merge field='operations_description'
      chosen='COMMERCIAL GENERAL CONTRA'                      score=2.95 freq=4
      rejected=["Contractors' equipment coverage and installation floater
                 coverage for property used in contracting, installation,
                 erection, repair, moving, and installation or construction
                 projects."                                   score=1.85 freq=1,
                'Contractors - Executive Supervisors or Executive
                 Superintendents; subcontractors in connection with
                 construction, reconstruction, repair, or erection of
                 buildings - NOC.'                            score=1.85 freq=1]

`_score_value` is `tier x (authority + log1p(freq) + confidence)`. Four
repetitions of a column header cut off mid-word (log1p(4)=1.61) beat one
statement of the real thing (log1p(1)=0.69). The client's verdict on what got
stamped: *"COMMERCIAL GENERAL CONTRA is truncated carrier shorthand, not a
usable underwriting description."* It also drove the "GL class codes present but
operations description is insufficient" ACORD 101 warning on the same run.

The information the fix needs was already computed one line above the bug:
`_narrative` is set when ANY candidate for the fact is prose, and it already
switches source authority off for that reason. It just never acted on it.

SCOPE, and why this is safe:
  * fires only when a fact has BOTH a prose candidate and a non-prose one;
  * `_is_prose_value` requires >100 chars AND >12 words - a full mailing
    address is ~45 chars / 8 tokens, so no scalar/dec-page fact can reach it;
  * it REORDERS, never discards. The fragment stays one place lower.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline-test")

import services.extraction_service as es                 # noqa: E402

# The client's literal candidates and their logged frequencies.
_FRAGMENT = "COMMERCIAL GENERAL CONTRA"
_SENTENCE_A = (
    "Contractors' equipment coverage and installation floater coverage for "
    "property used in contracting, installation, erection, repair, moving, and "
    "installation or construction projects."
)
_SENTENCE_B = (
    "Contractors - Executive Supervisors or Executive Superintendents; "
    "subcontractors in connection with construction, reconstruction, repair, or "
    "erection of buildings - NOC."
)


def _merge(field, candidates):
    """Drive the REAL merge. A local reimplementation would only prove itself."""
    partials = []
    for value, freq in candidates:
        partials += [{"facts": {field: {"value": value,
                                        "confidence": "ai_high",
                                        "source": "ai"}}}
                     for _ in range(freq)]
    out = es._merge_list_fields(partials, [])["facts"][field]
    return out.get("value") if isinstance(out, dict) else out


def test_the_client_reported_case():
    """Replayed with the client's exact strings and exact frequencies."""
    got = _merge("operations_description",
                 [(_FRAGMENT, 4), (_SENTENCE_A, 1), (_SENTENCE_B, 1)])
    assert got != _FRAGMENT
    assert es._is_prose_value(got), f"a fragment still won: {got!r}"


def test_it_is_not_special_cased_to_one_fact():
    """The same defect on ACORD 130's operations narrative."""
    got = _merge("wc_description_of_operations", [(_FRAGMENT, 4), (_SENTENCE_A, 1)])
    assert es._is_prose_value(got)


def test_a_bigger_frequency_gap_does_not_rescue_the_fragment():
    """Frequency is evidence of a repeated HEADER, not of a better answer, so
    the fix must not be a threshold that a longer document defeats."""
    got = _merge("operations_description", [(_FRAGMENT, 40), (_SENTENCE_A, 1)])
    assert es._is_prose_value(got)


# ── Safety: nothing outside narrative facts may move ─────────────────────────

@pytest.mark.parametrize("field,candidates,expected_substr", [
    # Ordinary scalar facts: frequency still decides, exactly as before.
    ("carrier_name",
     [("EMPLOYERS MUTUAL CASUALTY COMPANY", 8), ("EMC Property & Casualty Company", 2)],
     "EMPLOYERS MUTUAL"),
    ("mailing_address",
     [("4800 DAHLIA ST # D13, DENVER, CO 80216-3121", 3),
      ("4800 DAHLIA STREET D13, DENVER CO. 80216-3121", 2)],
     "# D13"),
    ("state_of_operations", [("CO", 10), ("IA", 1)], "CO"),
])
def test_non_narrative_facts_are_untouched(field, candidates, expected_substr):
    assert expected_substr in _merge(field, candidates)


def test_c23_currency_tiebreak_still_holds():
    """LOAD-BEARING. C23 stops an umbrella's larger limit filling a General
    Liability field - wrong limits on a certificate is the failure mode with
    legal exposure. This must not be disturbed by a change to the same scorer."""
    assert "1,000,000" in _merge("gl_each_occurrence", [("$1,000,000", 2), ("$ 3,000,000", 1)])


def test_when_every_candidate_is_prose_frequency_still_decides():
    """The partition may only separate prose from FRAGMENT. Among genuine
    sentences it must change nothing at all."""
    long_a = ("The applicant operates a commercial general contracting business "
              "performing tenant finish and remodeling work across the Denver "
              "metropolitan area with no work above three stories.")
    long_b = ("The applicant performs residential roof replacement and repair "
              "work with no operations above three stories anywhere in the "
              "state of Colorado at the present time.")
    assert es._is_prose_value(long_a) and es._is_prose_value(long_b)
    assert _merge("operations_description", [(long_a, 1), (long_b, 3)]) == long_b


def test_a_lone_fragment_is_still_used_when_it_is_all_there_is():
    """NEVER LOSE A VALUE. With no prose candidate the fragment is the only
    answer available, and a blank operations description is worse than a short
    one."""
    assert _merge("operations_description", [(_FRAGMENT, 4)]) == _FRAGMENT


def test_the_prose_thresholds_are_pinned():
    """Lowering these would let ordinary dec-page values into the branch."""
    assert es._PROSE_VALUE_CHARS == 100
    assert es._PROSE_VALUE_WORDS == 12
