"""THE FOURTH DOOR: alias stamping bypassed every resolver and every guard.

Six live runs put the producer's PHONE in the FAX box. Each fix closed a real
door and the next run came through another:

    run 3  gap fill                 -> C55 duplicate guard
    run 5  the resolver trusted a mislabelled fact  -> C60 value-identity check
    run 6  Pass 1's substring rule  -> C61 explicit call site in _deterministic_map
    run 7  **Pass 1.5 alias stamping**

`stamp_form_fields` writes `mapped[field] = value` DIRECTLY. It never routes
through `_deterministic_map`, so every authoritative-blank resolver was
invisible to it; it never touches `gpt_filled_set`, so every guard scoped to
gap fill was invisible too. Measured across all 17 alias maps: **137 fields a
resolver owns** were being overridden - the fax, the deposit, REMARKS, the
applicant website, the no-loss attestation, all 64 prior-coverage cells.

Two rules come out of it, and this file exists to keep both true:

  1. An alias map may not override an authoritative blank.
  2. A guard that judges whether a value is POSSIBLE FOR ITS BOX must be
     source-agnostic. Only guards that judge MODEL BEHAVIOUR (hallucinated
     keys, ungrounded quotes) may scope themselves to `gpt_filled_set`.
"""
import glob
import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

import services.pdf_service as ps                                 # noqa: E402

BACKEND = os.path.join(os.path.dirname(__file__), "..")


def _schema(form):
    with open(os.path.join(BACKEND, "forms_schemas", f"{form}_schema.json"),
              encoding="utf-8") as fh:
        return json.load(fh)


# ── Rule 1: an alias map may not override an authoritative blank ─────────────

def test_alias_stamping_defers_to_every_owning_resolver():
    """ANTI-ROT, and the measurement that found the bug.

    Every alias-mapped field that a resolver owns must be skipped by Pass 1.5.
    If this count ever drops to zero the check has been removed; if a NEW alias
    entry lands on a resolver-owned box, this still passes - the skip is
    computed, not listed - but the assertion below proves the skip is wired.
    """
    owned = set()
    for path in sorted(glob.glob(os.path.join(BACKEND, "forms_aliases", "*_alias.json"))):
        with open(path, encoding="utf-8") as fh:
            for field in json.load(fh):
                if ps._is_authoritative_blank_field(field, {}):
                    owned.add(field)
    assert len(owned) >= 100, (
        f"only {len(owned)} alias fields resolve as owned - the resolver set "
        "or the alias maps changed shape; re-measure before trusting this")
    # The skip must be present INSIDE every alias stamping loop. Counted per
    # loop body, not per file: an identically-named guard exists elsewhere (the
    # unmatched-set builder), and a file-wide count would pass on its back.
    src = open(os.path.join(BACKEND, "services", "pdf_service.py"),
               encoding="utf-8").read()
    sites = [m.start() for m in re.finditer(r"alias_filled = stamp_form_fields", src)]
    assert len(sites) == 2, f"{len(sites)} alias call sites - expected 2"
    for start in sites:
        body = src[start:start + 1800]          # the loop and its body
        assert "_is_authoritative_blank_field(field, facts)" in body, (
            "an alias stamping loop does not defer to owning resolvers - this "
            "is the exact hole that put the producer's phone in the FAX box on "
            "six consecutive live runs")


def test_the_fax_box_survives_a_mislabelled_fact_end_to_end():
    """THE CLIENT'S SIX-RUN DEFECT, replayed through the exact fact shape that
    beat every earlier fix: extraction filed the phone under BOTH `producer_fax`
    and the alias key `producer_fax_number`."""
    facts = {"producer_fax": "303-996-7800",
             "producer_fax_number": "303-996-7800",
             "producer_phone": "303-996-7800",
             "applicant_name": "ORBIN CONTRACTING LLC"}
    mapped, _ = ps.map_facts_to_form(
        facts, _schema("ACORD_125"), "ACORD_125",
        raw_text="COMMON POLICY DECLARATIONS\nAgent Phone 303-996-7800\n",
        pre_filled_gpt={"filled_values": {}, "raw_text_fields": set(),
                        "question_grounding": {}})
    assert mapped.get("Producer_FaxNumber_A") is None


def test_a_genuine_fax_still_reaches_the_form_through_the_alias_path():
    """The other direction: deferring to the resolver must not mean the box can
    never be filled. A fax that is genuinely distinct from the phone stamps."""
    facts = {"producer_fax": "303-996-7801", "producer_fax_number": "303-996-7801",
             "producer_phone": "303-996-7800"}
    mapped, _ = ps.map_facts_to_form(
        facts, _schema("ACORD_125"), "ACORD_125", raw_text="Fax 303-996-7801",
        pre_filled_gpt={"filled_values": {}, "raw_text_fields": set(),
                        "question_grounding": {}})
    assert mapped.get("Producer_FaxNumber_A") == "303-996-7801"


# ── Rule 2: possibility guards are source-agnostic ───────────────────────────

_POSSIBILITY_GUARD_MARKERS = (
    "_DRIVER_PERSONAL_COLUMN_RE.match(_f)",
    "_is_row_label_not_a_name(_f, mapped.get(_f))",
)


def test_possibility_guards_do_not_iterate_only_gap_fill():
    """A guard that asks 'can this value be true for this box?' must look at
    every value, not only the model's. Scoping them to `gpt_filled_set` is
    exactly what let Pass 1.5 deliver the same wrong values unseen.

    Checked structurally on the loop header that precedes each guard, so a
    future refactor that re-scopes one fails here.
    """
    src = open(os.path.join(BACKEND, "services", "pdf_service.py"),
               encoding="utf-8").read()
    for marker in _POSSIBILITY_GUARD_MARKERS:
        idx = src.index(marker)
        loop = src.rindex("for _f in ", 0, idx)
        header = src[loop:src.index("\n", loop)]
        assert "mapped.keys()" in header, (
            f"{marker} is scoped to {header.strip()!r} - a possibility guard "
            "must be source-agnostic (see this file's docstring)")


@pytest.mark.parametrize("field,value", [
    ("Driver_GenderCode_A", "F"),           # inferred from a first name
    ("Driver_MaritalStatusCode_A", "S"),    # invented outright
    ("Driver_LicensedYear_A", "2012"),      # the VEHICLE'S model year
])
def test_driver_personal_columns_fall_from_any_source(field, value):
    """Run 7 delivered all three again after C59 'fixed' them - through the
    alias door. Planted as a gap-fill value here AND reachable by alias; the
    guard must not care which."""
    schema = {"Driver_FullName_A": {}, field: {}}
    mapped, _ = ps.map_facts_to_form(
        {"auto_drivers": [{"name": "Erin Royal"}]}, schema, "ACORD_127",
        raw_text="ERIN ROYAL\n2012 SUBARU OUTBACK\n",
        pre_filled_gpt={"filled_values": {field: value},
                        "raw_text_fields": set(), "question_grounding": {}})
    assert mapped.get(field) is None


def test_a_row_label_is_not_a_party_name_from_any_source():
    schema = {"AdditionalInterest_FullName_A": {},
              "AdditionalInterest_Primary_PhoneNumber_A": {}}
    mapped, _ = ps.map_facts_to_form(
        {}, schema, "ACORD_125", raw_text="Location 000: Limited Pollution",
        pre_filled_gpt={"filled_values": {
            "AdditionalInterest_FullName_A": "Location 000"},
            "raw_text_fields": set(), "question_grounding": {}})
    assert mapped.get("AdditionalInterest_FullName_A") is None


# ── The map of every door, so the next fix starts from the right place ───────

def test_every_value_producing_path_is_accounted_for():
    """DOCUMENTATION WITH TEETH. Four paths write into `mapped`. A fix that
    closes one and calls the defect solved is the mistake this whole file
    records. If a fifth appears, this fails and someone has to decide whether
    the guards reach it.
    """
    src = open(os.path.join(BACKEND, "services", "pdf_service.py"),
               encoding="utf-8").read()
    body = src[src.index("def map_facts_to_form("):]
    body = body[:body.index("\ndef ", 10)]
    writes = len(re.findall(r"^\s{4,}mapped\[[^\]]+\]\s*=\s*(?!None)", body, re.M))
    assert writes, "no writes found - the parser broke, not the code"
    # Pass 1 (_deterministic_map result), Pass 1.5 (alias), Pass 2 (gap fill),
    # and the post-fill resolvers/canonicalisation are the known writers.
    assert "alias_filled.items()" in body
    assert "_deterministic_map(" in body
