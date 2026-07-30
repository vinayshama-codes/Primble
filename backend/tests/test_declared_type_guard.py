"""C22 - type-aware rejection driven by ACORD's OWN declared field types.

Observed on a real ACORD 127 run, all four shipped to the PDF:

    Driver_TaxIdentifier_A = "4S4BRCGC9C3217772"   (a VIN in a tax-ID box)
    Driver_TaxIdentifier_I = "ERIN ROYAL"          (a person's name)
    Driver_GenderCode_A    = "ERIN ROYAL"
    Driver_LicensedYear_A  = "2012"                (the vehicle's model year)

None was caught by the existing guards: `_NUMERIC_DATE_FIELD_HINTS` lists
`YearBuilt`/`ModelYear` but not plain `Year`, and `_PROSE_FIELD_TOKENS` contains
"Name", so a name-ish field is classified as prose and anything passes.

ACORD states the expected type in each field's own tooltip - "Enter code:",
"Enter year:", "Enter identifier:", ... - for **3,888 of 5,852 fields (66%)**.
Only the 607 "Enter number:" ones were being used.

THE DESIGN RULE THESE TESTS EXIST TO PROTECT: a check may only reject what
CANNOT POSSIBLY be right for the declared type. This is not a format validator.
Insurance amount boxes legitimately hold "Statutory", "Included", "See schedule";
code boxes hold short words; identifier boxes hold alphanumeric soup. Blanking a
broker's real value is just as wrong as stamping a bad one - "blank beats wrong"
does not license "blank beats correct".
"""
import json
import os

import pytest

import services.pdf_service as ps


def _schema(form_id):
    path = os.path.join(ps.FORMS_SCHEMAS_DIR, f"{form_id}_schema.json")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def s127():
    return _schema("ACORD_127")


@pytest.fixture(scope="module")
def all_typed_fields():
    """Every (field, meta, declared_type) across all 17 schemas."""
    out = []
    for fn in sorted(os.listdir(ps.FORMS_SCHEMAS_DIR)):
        if not fn.endswith("_schema.json"):
            continue
        for f, m in _schema(fn[:-len("_schema.json")]).items():
            dt = ps._tooltip_declared_type(m)
            if dt:
                out.append((f, m, dt))
    return out


# ── The declared types really are there ──────────────────────────────────────

def test_two_thirds_of_all_fields_declare_their_own_type(all_typed_fields):
    """If this drops sharply, the schemas were regenerated with truncated
    tooltips again - which is exactly what caused the 2026-07-16 blank/N flood."""
    assert len(all_typed_fields) > 3500, (
        f"only {len(all_typed_fields)} fields declare a type; expected ~3,888. "
        f"Check that schema tooltips are not being truncated (_SCHEMA_TOOLTIP_MAX)."
    )


# ── The reported failures are caught ─────────────────────────────────────────

@pytest.mark.parametrize("field,value", [
    ("Driver_TaxIdentifier_A", "4S4BRCGC9C3217772"),   # a VIN
    ("Driver_TaxIdentifier_I", "ERIN ROYAL"),          # a person's name
    ("Driver_GenderCode_A", "ERIN ROYAL"),
])
def test_the_real_c22_failures_are_rejected(s127, field, value):
    assert ps._rejects_declared_type(field, s127.get(field), value), (
        f"{field} = {value!r} would still be stamped on the form"
    )


@pytest.mark.parametrize("field,value,why", [
    ("Driver_LicensedYear_A", "2012",
     "a valid year in a year field - it was the WRONG ENTITY's year (the "
     "vehicle's), which no type check can see. Documented, not fixed."),
    ("Driver_OtherGivenNameInitial_A", "Erin",
     "ACORD's own tooltip says 'middle name OR INITIAL', so a first name is a "
     "PERMITTED value. This was mis-reported as a defect; rejecting it would "
     "blank legitimate data."),
    ("Vehicle_RateClassCode_A", "7383",
     "a validly-shaped class code that happened to be borrowed from elsewhere - "
     "again invisible to a type check."),
])
def test_honest_limits_of_type_checking(s127, field, value, why):
    """Pins what this guard does NOT do, so nobody later claims C22 is closed."""
    assert not ps._rejects_declared_type(field, s127.get(field), value), why


# ── It must not blank legitimate values ──────────────────────────────────────

_LEGIT_BY_TYPE = {
    "amount":     ["$1,000,000", "1,000,000", "$0", "0", "$58,900", "Statutory",
                   "Included", "Excluded", "Waived", "See schedule", "See attached",
                   "Not covered", "No coverage", "Per policy", "Blanket coverage",
                   "Refer to schedule", "Various", "$1,000,000/$2,000,000",
                   "1000000.00"],
    "limit":      ["$1,000,000", "Statutory", "Included", "Excluded", "See schedule",
                   "$1,000,000/$2,000,000", "Various", "Per occurrence"],
    "deductible": ["$1,000", "$0", "None", "Waived", "See schedule", "1% of TIV", "5%"],
    "percentage": ["100%", "80", "2.5", "0.75", "100"],
    "rate":       ["2.45", "0.075", ".85", "1.2500", "Included"],
    "number":     ["1", "2", "B-1", "#12", "0", "12345", "3"],
    "year":       ["2012", "1998", "98", "2024-2025", "2024/2025", "2026"],
    "date":       ["07/25/2025", "2025-07-25", "July 25, 2025", "25-Jul-25",
                   "7/1/25", "01/01/2026", "Jan 1, 2026"],
    "code":       ["M", "F", "X", "Y", "N", "A", "CA", "CO", "238160", "5812",
                   "91560", "B-1", "R", "ACV", "RCV", "Corporation", "LLC",
                   "Partnership", "Individual", "Trust", "Other", "SC", "CGL", "WC"],
    "identifier": ["123-45-6789", "84-2210987", "D1234567", "GL-4471",
                   "POL-2026-004471", "0012345", "ABC123456", "12-3456789"],
    "text":       ["Ridgeline Sheet Metal LLC", "Erin Royal", "Mary-Jane O'Neill",
                   "Denver", "CO 80202", "Roofing - residential and commercial",
                   "Statutory", "See schedule", "1200 Industrial Way"],
    "time":       ["12:01 AM", "12:01", "00:01"],
}


def test_no_legitimate_value_is_ever_blanked(all_typed_fields):
    """The sweep that matters: every type-appropriate legitimate value against
    EVERY field of that declared type in all 17 schemas. ~49,000 pairs.

    A failure here is real data loss on a real submission, so this is deliberately
    exhaustive rather than a handful of spot checks. It is also how the
    "See schedule" false positive was found - two alphabetic words with no digits
    matched the person-name shape, and it is a perfectly good value in a limit box.
    """
    bad = []
    for field, meta, dtype in all_typed_fields:
        for v in _LEGIT_BY_TYPE.get(dtype, []):
            reason = ps._rejects_declared_type(field, meta, v)
            if reason:
                bad.append((dtype, v, field, reason))
    assert not bad, (
        f"{len(bad)} legitimate value(s) would be BLANKED. First few:\n"
        + "\n".join(f"  type={d} value={v!r} field={f}: {r}" for d, v, f, r in bad[:6])
    )


def test_a_vin_is_allowed_in_a_vin_field(s127):
    """The VIN check must never fire where a VIN belongs."""
    assert not ps._rejects_declared_type(
        "Vehicle_VINIdentifier_A", s127.get("Vehicle_VINIdentifier_A"),
        "4S4BRCGC9C3217772")
    assert ps._is_vin_field("Vehicle_VINIdentifier_A")
    assert not ps._is_vin_field("Driver_TaxIdentifier_A")


def test_untyped_fields_are_left_completely_alone():
    """No declared type means no rule. A missing check costs nothing; a wrong one
    blanks real data."""
    assert ps._tooltip_declared_type({"tu": "The edition identifier of the form."}) is None
    assert ps._rejects_declared_type(
        "Form_EditionIdentifier_A", {"tu": "The edition identifier of the form."},
        "ERIN ROYAL") is None


# ── The two narrow shape tests ───────────────────────────────────────────────

@pytest.mark.parametrize("s,expected", [
    ("ERIN ROYAL", True), ("Erin Royal", True), ("Mary-Jane O'Neill", True),
    ("See schedule", False),      # the false positive a self-test caught
    ("Not covered", False), ("No coverage", False), ("Per policy", False),
    ("Blanket coverage", False), ("Refer to schedule", False),
    ("Included", False),          # single word - shape needs 2+
    ("$1,000,000", False), ("123-45-6789", False), ("M", False),
])
def test_person_name_shape(s, expected):
    assert ps._looks_like_person_name(s) is expected, s


@pytest.mark.parametrize("s,expected", [
    ("4S4BRCGC9C3217772", True), ("1FTFW1ET5DFC10312", True),
    ("4S4BRCGC9C321777", False),          # 16 chars
    ("4S4BRCGC9C32177721", False),        # 18 chars
    ("IOQ4BRCGC9C3217772", False),        # I/O/Q are excluded from the VIN alphabet
    ("12345678901234567", False),         # all digits - no letters
    ("ABCDEFGHJKLMNPRSTU"[:17], False),   # all letters - no digits
])
def test_vin_shape(s, expected):
    assert ps._looks_like_vin(s) is expected, s


def test_guard_is_wired_into_post_fill():
    """A perfect predicate nobody calls fixes nothing."""
    import inspect
    src = inspect.getsource(ps._enforce_post_fill_guards)
    assert "_rejects_declared_type" in src, (
        "Guard 3b is not invoked from _enforce_post_fill_guards - the declared-type "
        "check is dead code and C22 is open again"
    )


# ── Found by an adversarial pass; do not delete ──────────────────────────────

@pytest.mark.parametrize("name", [
    "JOSÉ GARCÍA", "José García", "Renée Dubois", "Søren Kierkegaard",
    "Zoë O'Brien", "Björn Müller", "François Lefèvre",
])
def test_accented_names_are_detected_too(s127, name):
    """An ASCII-only `[A-Za-z]` name class shipped first and an adversarial pass
    caught it: no word in "JOSÉ GARCÍA" is ASCII-only, so the value bypassed the
    check entirely and would still land in a gender-code box.

    US commercial-lines submissions are full of accented names, so an ASCII-only
    name detector fails precisely the people it most needs to protect. This is not
    a nicety - it is the difference between the guard working and the guard looking
    like it works.
    """
    assert ps._looks_like_person_name(name), name
    assert ps._rejects_declared_type(
        "Driver_GenderCode_A", s127.get("Driver_GenderCode_A"), name), (
        f"{name!r} would still be stamped into a gender-code field")


@pytest.mark.parametrize("bad", [None, "notadict", 123, [], {"tu": None}])
def test_never_raises_on_malformed_metadata(bad):
    """This runs inside `_enforce_post_fill_guards` over every field of every
    generated form. An exception here fails a whole download."""
    assert ps._rejects_declared_type("Any_Field_A", bad, "some value") is None


@pytest.mark.parametrize("value", [None, "", "   ", "\t\n"])
def test_empty_values_are_left_alone(s127, value):
    assert ps._rejects_declared_type(
        "Driver_GenderCode_A", s127.get("Driver_GenderCode_A"), value) is None


@pytest.mark.parametrize("vin", [
    "4S4BRCGC9C3217772",        # plain
    "4s4brcgc9c3217772",        # lowercase
    "4S4BRCGC9C 3217772",       # OCR inserted a space
    "4S4BRCGC9C-3217772",       # hyphenated
])
def test_vin_variants_all_caught_in_a_tax_id_field(s127, vin):
    """OCR does not hand over clean strings. A VIN check that only matches the
    canonical form is a check that misses the real input."""
    assert ps._rejects_declared_type(
        "Driver_TaxIdentifier_A", s127.get("Driver_TaxIdentifier_A"), vin), vin
