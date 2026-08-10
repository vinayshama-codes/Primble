"""A coverage flag describes coverage the policy GRANTS - not an exposure, and
not a coverage the document names in order to exclude it.

Client report (ACORD 125, Orbin Contracting) #5:
  "Cyber-related terms in the policy do not establish a standalone Cyber policy.
   In fact, the GL forms include a Cyber Incident and Data Privacy exclusion
   notice."

`has_crime` and `has_cyber` were pure keyword-presence definitions ("true if
document MENTIONS cyber liability, data breach ... PCI, PHI"). Six sibling flags
had already been hardened with an explicit "Do NOT set true..." guard; these two
were never given one.

RULE 6's own preamble made it worse. It taught the model that
"we hold customer health and card data" implies cyber - which is an EXPOSURE, and
exposure-implies-coverage is the exact conflation that ticked the box.
"""
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline-test")

import services.extraction_service as es                 # noqa: E402
import services.pdf_service as ps                        # noqa: E402

PROMPT = es._EXTRACT_PROMPT_PREFIX


def _flag_definitions():
    return dict(re.findall(r"^\s{2}(has_\w+|is_\w+):\s*(.*)$", PROMPT, re.M))


def _lob_driving_flags():
    """Flags that decide whether a line-of-business checkbox is ticked."""
    return {
        fact for sub, (fact, _mv) in ps._INDICATOR_RULES.items()
        if sub.startswith("Policy_LineOfBusiness_")
    }


@pytest.mark.parametrize("flag", ["has_crime", "has_cyber"])
def test_the_two_client_reported_flags_now_carry_a_guard(flag):
    definition = _flag_definitions()[flag]
    assert "do not set true" in definition.lower(), (
        f"{flag} is still a pure keyword-presence definition"
    )


@pytest.mark.parametrize("flag,must_mention", [
    ("has_cyber", ["exclusion", "electronic data processing", "exposure"]),
    ("has_crime", ["exclusion", "not covered"]),
])
def test_the_guards_name_the_situations_that_caused_the_defect(flag, must_mention):
    definition = _flag_definitions()[flag].lower()
    for phrase in must_mention:
        assert phrase in definition, f"{flag} guard does not cover {phrase!r}"


@pytest.mark.parametrize("flag", ["has_crime", "has_cyber"])
def test_the_guards_require_positive_evidence(flag):
    """A distinct coverage part with a stated limit or premium - the same bar the
    already-hardened has_inland_marine and has_umbrella definitions use."""
    definition = _flag_definitions()[flag].lower()
    assert "distinct" in definition
    assert "limit" in definition and "premium" in definition


def test_rule_six_no_longer_teaches_that_an_exposure_implies_coverage():
    """The preamble example "we hold customer health and card data implies cyber"
    was teaching the exact conflation this fix removes. Judging by MEANING stays
    - that was added deliberately and is valuable - but the meaning that matters
    is what the policy covers."""
    preamble = PROMPT.split("Criteria:")[0]
    assert "implies cyber even without the word" not in preamble
    assert "exposure" in preamble.lower()
    # The valuable half must survive.
    assert "meaning" in preamble.lower()
    assert "equivalents and paraphrases" in preamble.lower()


def test_a_genuine_coverage_paraphrase_is_still_recognised():
    """Hardening must not turn the flag into a literal keyword match - a real
    cyber coverage part named differently still counts."""
    preamble = PROMPT.split("Criteria:")[0].lower()
    assert "network security and privacy liability" in preamble


def test_most_lob_driving_flags_are_guarded():
    """Six of the eight flags behind a line-of-business checkbox carry a guard."""
    defs = _flag_definitions()
    guarded = {
        f for f in _lob_driving_flags()
        if f in defs and "do not set true" in defs[f].lower()
    }
    assert {"has_crime", "has_cyber", "has_inland_marine", "has_umbrella",
            "has_property_coverage", "has_auto_coverage"} <= guarded


def test_general_liability_and_workers_comp_are_deliberately_left_alone():
    """DELIBERATE, not an oversight - re-read before "fixing" this.

    Both are still pure-mention definitions and both drive an LOB checkbox, so
    they look like the same defect. They are not worth the same treatment:

      * General Liability is present on the overwhelming majority of commercial
        packages. A false POSITIVE is rare and cheap; a false NEGATIVE unticks
        the GL box on a real GL policy and disturbs ACORD 126 recommendation.
        The asymmetry runs the wrong way.
      * Workers Comp: the client's actual reported case ("Workers Compensation -
        No Coverage") is already handled deterministically by
        `apply_declared_absent_downgrades`, which reads the denial off the dec
        page. Adding a prompt guard on top buys nothing reported and risks
        dropping ACORD 130 for a genuine WC submission.

    Neither was reported. Both fail toward MORE coverage, which is the standing
    product preference. If a client ever reports a false GL or WC tick, harden
    them then - with that report as the evidence."""
    defs = _flag_definitions()
    for flag in ("has_general_liability", "has_workers_comp"):
        assert flag in defs, f"{flag} lost its definition"
        assert "do not set true" not in defs[flag].lower(), (
            f"{flag} was hardened - if that was intentional, update this test and "
            "explain the evidence; see the docstring for why it was left"
        )


def test_workers_comp_denial_is_still_caught_deterministically():
    """The reason has_workers_comp needs no prompt guard."""
    flags = {"has_workers_comp": True}
    changed = es.apply_declared_absent_downgrades(
        flags, {}, "Workers Compensation - No Coverage")
    assert changed == ["has_workers_comp"]
    assert flags["has_workers_comp"] is False
