"""Two live-run defects: a field answered with its own description, and an
exclusion clause read as proof an exposure exists.

FOUND ON A REAL RUN 2026-08-09 (third generation of the client's document).

1. `AdditionalInterest_FullName_B` - tooltip "The additional interest's full
   name. As used here, this is the name of the trust." - came back stamped
   "The Additional Interest's Full Name. As Used Here, This Is The Name Of The
   Trust." Our own prompt text, title-cased, sitting on the form as though a
   real trust had been named.

2. ACORD 125 Question 3 ("any exposure to flammables, explosives, chemicals?")
   came back "Y" grounded on "This insurance does not apply to: Asbestos" - a
   policy EXCLUSION. The policy saying it will not cover a thing is not the
   applicant saying they do it. Same conflation that ticked the Cyber box and
   answered Question 6 from an exclusion TITLE; this is the CLAUSE form.

THE 30-CHARACTER THRESHOLD IS THE SAFETY ARGUMENT for the echo check, and an
earlier attempt at this feature was abandoned for being unsafe. A 103,464-pair
sweep (realistic values x every free-text field on all 17 forms) measured false
positives at each length: 86 at 16, 16 at 20, 14 at 25, ZERO at 30. Below 30 it
blanks real answers like "Business Personal Property" that happen to appear in
their own tooltip. Do not lower it.
"""
import glob
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline-test")

import services.pdf_service as ps                        # noqa: E402

_SCHEMA_DIR = os.path.join(os.path.dirname(__file__), "..", "forms_schemas")


def _acord125():
    with open(os.path.join(_SCHEMA_DIR, "ACORD_125_schema.json"), encoding="utf-8") as fh:
        return json.load(fh)


# ── Tooltip echo ─────────────────────────────────────────────────────────────

def test_the_live_run_trust_echo_is_blanked():
    schema = _acord125()
    mapped = {
        "AdditionalInterest_FullName_B":
            "The Additional Interest's Full Name. As Used Here, This Is The "
            "Name Of The Trust.",
    }
    ps._enforce_post_fill_guards(mapped, schema, {})
    assert mapped["AdditionalInterest_FullName_B"] is None


@pytest.mark.parametrize("field,value", [
    ("AdditionalInterest_FullName_A", "Wells Fargo Equipment Finance"),
    ("NamedInsured_FullName_A", "Orbin Contracting LLC"),
    ("CommercialPolicy_OperationsDescription_A",
     "Commercial general contractor performing tenant finish work"),
    ("NamedInsured_MailingAddress_LineOne_A", "4800 Dahlia St # D13"),
])
def test_real_answers_are_never_mistaken_for_their_own_tooltip(field, value):
    schema = _acord125()
    mapped = {field: value}
    ps._enforce_post_fill_guards(mapped, schema, {})
    assert mapped[field] == value


def test_short_values_are_never_checked():
    """Below the threshold a legitimate short answer routinely appears inside
    its own tooltip - "Building" in a building-area box, "Occurrence" in an
    occurrence-date box."""
    schema = _acord125()
    for value in ("Building", "Occurrence", "Tenant", "Frame", "CO"):
        assert not ps._is_tooltip_echo(value, schema.get(
            "CommercialPolicy_OperationsDescription_A"))


def test_the_threshold_is_pinned():
    """STANDING GUARD. Lowering this re-introduces the false positives that got
    an earlier version of this feature abandoned."""
    assert ps._TOOLTIP_ECHO_MIN_CHARS == 30


def test_zero_false_positives_across_every_form():
    """The measurement, as an executable assertion."""
    values = [
        "Orbin Contracting LLC", "Commercial General Contractor", "Roofing",
        "Business Personal Property", "Contractors equipment",
        "Replacement Cost", "Joisted Masonry", "Direct Bill",
        "General contractor performing commercial remodeling and tenant finish work",
        "No prior losses in the last five years", "Employee Dishonesty $50,000",
    ]
    offenders = []
    for path in glob.glob(os.path.join(_SCHEMA_DIR, "*_schema.json")):
        with open(path, encoding="utf-8") as fh:
            schema = json.load(fh)
        for field, meta in schema.items():
            if (meta or {}).get("ft") != "/Tx":
                continue
            for value in values:
                if ps._is_tooltip_echo(value, meta):
                    offenders.append(f"{field} <- {value!r}")
    assert not offenders, f"{len(offenders)} legitimate values flagged: {offenders[:5]}"


# ── Exclusion clause cannot ground a "Yes" ───────────────────────────────────

@pytest.mark.parametrize("quote", [
    "This insurance does not apply to: Asbestos",
    "This insurance does not apply to bodily injury arising out of pollution",
    "Coverage shall not apply to any claim arising from abuse",
    "We will not pay for loss caused by wear and tear",
])
def test_an_exclusion_clause_cannot_ground_a_yes(quote):
    assert ps._EXCLUSION_CLAUSE_RE.search(quote) is not None


@pytest.mark.parametrize("quote", [
    "Scrap and used cutting fluid are stored on site and removed by a licensed hauler",
    "The applicant stores acetylene and oxygen cylinders in a locked cage",
    "Applicant performs roofing work above three stories",
    "A discrimination suit was settled in 2022",
    "Hazardous materials are stored on site and disposed of by a licensed contractor",
    "Prior negligent hiring claim paid $45,000",
])
def test_genuine_affirmative_evidence_still_grounds_a_yes(quote):
    """THE LOAD-BEARING TEST. This may only remove Yes answers whose own
    evidence contradicts them."""
    assert ps._EXCLUSION_CLAUSE_RE.search(quote) is None


def test_the_clause_pattern_is_not_shared_with_the_declared_absent_scan():
    """Y-GATE ONLY, on purpose. "this insurance does not apply to flood" sitting
    near the word Property would wrongly downgrade the whole property line, and
    the declared-absent scan already refuses "excluded" for that reason."""
    from services.extraction_service import _lines_declared_absent
    assert _lines_declared_absent(
        "Commercial Property - this insurance does not apply to flood") == set()
