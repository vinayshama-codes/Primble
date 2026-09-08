"""ACORD 25: an unowned Workers Comp band, and an operations box owned by the
wrong resolver. Both found on the live SYS-09 acceptance run of 2026-09-06.

THE PACKAGE: Harborline Provisions LLC, a refrigerated food warehouse, GL +
Business Auto and nothing else. No workers comp anywhere in the documents.

WHAT PRINTED:
  * the applicant's operations sentence in the WORKERS COMPENSATION block's
    LIMITS column, on the PER STATUTE | OTH-ER row;
  * a bare "Y" in the workers-comp band;
  * DESCRIPTION OF OPERATIONS / LOCATIONS / VEHICLES - the box that sentence
    belongs in - EMPTY.

TWO ROOT CAUSES, and the first explains why the model reached for that box at
all: it had narrative to place and nowhere legitimate to put it.

1. `_line_absent_from_package`'s census floor was THREE granted coverage lines.
   Harborline grants TWO, so the whole WC family fell through to gap fill on the
   commonest small-commercial shape there is. The floor is now 2 when
   `_family_has_no_evidence` corroborates - see that function for why the
   obvious flag-based gate was rejected.

2. `_REMARK_TEXT_RE` is a NAME-SHAPE test with no second condition. It claims 28
   fields across 16 schemas; 27 are general-remarks boxes and one - ACORD 25's -
   is defined by ACORD's own tooltip as the opposite: "records information
   necessary to identify the operations, locations and vehicles for which the
   certificate was issued."
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline-test")

import services.pdf_service as ps                                # noqa: E402

OPS = "Refrigerated warehousing and cold storage of packaged food products."

WC_OTHER = "WorkersCompensationEmployersLiability_OtherCoverageDescription_A"
WC_YN = "WorkersCompensationEmployersLiability_AnyPersonsExcludedIndicator_A"
OPS_BOX = "CertificateOfLiabilityInsurance_ACORDForm_RemarkText_A"
WC_EL = ("WorkersCompensationEmployersLiability_EmployersLiability_"
         "EachAccidentLimitAmount_A")

_TWO_LINES = [
    {"line": "Commercial General Liability", "policy_number": "CWP-4471902",
     "premium": "8,400"},
    {"line": "Business Auto", "policy_number": "CWA-4471903",
     "premium": "3,150"},
]
# The shape `form_service` actually hands the stamper: `{**facts, **flags}`, so
# a real package arrives carrying the whole computed flag set, not one flag.
# Writing this fixture with a single `has_*` key made an earlier version of the
# suppression test pass over a rule that could not fire on live data (D22).
LIVE = {
    "_form_id": "ACORD_25",
    "applicant_name": "Harborline Provisions LLC",
    "operations_description": OPS,
    "coverage_lines": _TWO_LINES,
    "gl_each_occurrence": "1,000,000",
    "has_general_liability": True,
    "has_auto_coverage": True,
    "has_property_coverage": False,
    "has_umbrella": False,
    "has_workers_comp": False,
}


def _schema(form):
    path = os.path.join(os.path.dirname(__file__), "..", "forms_schemas",
                        f"{form}_schema.json")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _band_open(facts, field=WC_OTHER):
    """True when the field is still a question for the model."""
    return ps._resolve_declared_absent_line_row(field, facts) is ps._SCHED_SKIP


# ── 1. The live defect ───────────────────────────────────────────────────────

def test_the_live_certificate_comes_out_right():
    """All three symptoms, through the real stamper, with the gap fill answering
    exactly what it answered live."""
    gpt = {"filled_values": {WC_OTHER: OPS, WC_YN: "Y"},
           "raw_text_fields": {WC_OTHER}, "question_grounding": {}}
    res = ps.map_facts_to_form(dict(LIVE), _schema("ACORD_25"), "ACORD_25", OPS,
                               pre_filled_gpt=gpt)
    mapped = res[0] if isinstance(res, tuple) else res
    assert mapped.get(WC_OTHER) is None, "operations text in the WC limits column"
    assert mapped.get(WC_YN) is None, "a Y about coverage the package lacks"
    assert mapped.get(OPS_BOX) == OPS, "the box that sentence actually belongs in"


def test_a_two_line_package_with_no_wc_evidence_closes_the_band():
    assert not _band_open(LIVE)


# ── 2. Any evidence at all keeps the band OPEN ───────────────────────────────
#
# An adversarial pass killed the first version of this fix - which gated on the
# `has_workers_comp` flag - by showing it DELETED three correct, verbatim E.L.
# limits from a certificate that really did carry workers comp. Evidence, not
# truth, and from any source.

# PAYROLL IS DELIBERATELY NOT IN THIS LIST. The first version counted
# "total_payroll", "num_employees", "class_code" and a bare "wc_" prefix as
# evidence, and the live session of 2026-09-07 proved that makes the rule
# UNFIREABLE: a GL+Auto package with no workers comp anywhere, every genuine WC
# fact null and has_workers_comp False - yet carrying total_payroll =
# "$3,120,000" and wc_payroll_period = "annual", because EVERY commercial
# application states payroll. Evidence has to be something that could not exist
# WITHOUT the coverage.
@pytest.mark.parametrize("label,extra", [
    ("an affirmative flag", {"has_workers_comp": True}),
    ("a producer's typed fact", {"wc_carrier": {"value": "Granite Harbor",
                                                "source": "producer"}}),
    ("an E.L. limit read off the certificate",
     {"wc_el_each_accident": "1,000,000"}),
    ("a WC class-code schedule", {"wc_class_codes": [{"code": "8018"}]}),
    ("WC named in the inventory",
     {"coverage_lines": _TWO_LINES + [{"line": "Workers Compensation",
                                       "policy_number": "CWC-1",
                                       "premium": "5,000"}]}),
])
def test_any_workers_comp_evidence_keeps_the_band_open(label, extra):
    assert _band_open(dict(LIVE, **extra)), label


def test_a_real_EL_limit_still_stamps():
    """KILL 2, the one that blocked the first fix: three correct $1,000,000 E.L.
    limits deleted from a certificate that carried them."""
    facts = dict(LIVE, wc_el_each_accident="1,000,000")
    assert _band_open(facts, WC_EL)


# ── 3. A thin inventory is still never a census ──────────────────────────────

@pytest.mark.parametrize("label,facts", [
    ("no coverage_lines at all (legacy session)",
     {k: v for k, v in LIVE.items() if k != "coverage_lines"}),
    ("an empty inventory", dict(LIVE, coverage_lines=[])),
    ("ONE granted line", dict(LIVE, coverage_lines=_TWO_LINES[:1])),
    ("a non-list inventory", dict(LIVE, coverage_lines="Commercial GL")),
])
def test_a_thin_inventory_suppresses_nothing(label, facts):
    """The floor moved from 3 to 2, never to 1 and never to zero. A session with
    no inventory must behave byte-identically to before."""
    assert _band_open(facts), label


# ── 3b. Silence counts only where flags were computed ────────────────────────
#
# TWO WRONG VERSIONS OF THIS TEST SHIPPED BEFORE THE RIGHT ONE, and each was
# caught by something other than the file it lived in:
#
#   v1 - no precondition. Overrode an affirmative `has_workers_comp = True`
#        arriving through `line_presence.line_in_submission`, which keeps flags
#        in a SEPARATE argument. Caught by the existing SYS-04 suite.
#   v2 - required `has_workers_comp` to be present in facts. But that flag is
#        set only when a document EVIDENCES workers comp, so on a package
#        carrying none the key is simply absent - the suppression silently never
#        fired and a stray "Y" shipped to the 2026-09-07 live run. Caught by the
#        live form, not by any test.
#
# The right question is not "is this family's flag here?" but "were coverage
# flags computed at all?" - only then is the family's absence from them evidence.

_FLAGS = {"has_general_liability": True, "has_auto_coverage": True,
          "has_property_coverage": False, "has_umbrella": False}


def test_the_live_shape_closes_the_band_with_no_wc_flag_at_all():
    """THE 2026-09-07 LIVE SHAPE: flags were computed, and `has_workers_comp` is
    not among them because nothing in the documents evidenced workers comp."""
    facts = dict(_FLAGS, coverage_lines=_TWO_LINES,
                 applicant_name="Harborline Provisions LLC")
    for field in (WC_OTHER, WC_YN,
                  "Policy_WorkersCompensation_SubrogationWaivedCode_A"):
        assert not _band_open(facts, field), field


@pytest.mark.parametrize("label,facts", [
    ("no flags at all - the line_presence path",
     {"coverage_lines": _TWO_LINES}),
    ("a single lone flag - a hand-built fixture, not a computed package",
     {"coverage_lines": _TWO_LINES, "has_workers_comp": False}),
])
def test_a_dict_that_never_carried_flags_abstains(label, facts):
    assert _band_open(facts), label


@pytest.mark.parametrize("facts,expected", [
    ({}, False),
    ({"has_workers_comp": False}, False),
    ({"has_a": 1, "has_b": 2}, True),
    ({"has_workers_comp": False, "has_umbrella": True}, True),
    ({"hasnt_x": 1, "has": 2, "has_": 3, "has_9": 4}, False),
    (None, False), ([], False), ("x", False), (7, False),
])
def test_flags_were_computed_is_structural(facts, expected):
    """`has_<name>` is how every writer of a coverage flag names one. Two
    distinct ones, so a fixture carrying a single key is never mistaken for a
    computed package."""
    assert ps._flags_were_computed(facts) is expected


def test_a_family_with_no_evidence_profile_gets_no_opinion():
    """`_FAMILY_EVIDENCE_PREFIXES` is opt-in: a family added to
    `_DECLARED_ABSENT_LINE_FAMILIES` never silently gains the lowered floor."""
    assert ps._family_has_no_evidence({}, ("no", "such", "family")) is False


@pytest.mark.parametrize("value", [None, "", "   ", [], {}, (), set()])
def test_an_empty_value_is_not_evidence(value):
    assert ps._family_has_no_evidence(
        {"wc_carrier": value, "has_workers_comp": False, "has_umbrella": False},
        ("workers compensation", "employers liability")) is True


@pytest.mark.parametrize("value", [0, False, "0", "None"])
def test_a_falsey_but_stated_value_is_still_evidence_unless_a_bool(value):
    """An explicit False FLAG is not evidence for the coverage; a literal 0 or
    the string "None" is a stated answer and keeps the band open."""
    got = ps._family_has_no_evidence(
        {"wc_carrier": value, "has_workers_comp": False, "has_umbrella": False},
        ("workers compensation", "employers liability"))
    assert got is (value is False)


# ── 4. The operations box ────────────────────────────────────────────────────

def test_the_certificate_operations_box_is_not_a_remarks_box():
    """`_resolve_remark_text` must step aside; the name shape is not enough."""
    assert ps._resolve_remark_text(OPS_BOX, dict(LIVE)) is ps._SCHED_SKIP


def test_the_other_sixteen_forms_keep_their_remarks_owner():
    """Exactly one field of the 28 the regex claims changes hands."""
    for field in ("Policy_RemarkText_A", "ACORDForm_RemarkText_A",
                  "RemarkText_A"):
        assert ps._resolve_remark_text(field, dict(LIVE)) is not ps._SCHED_SKIP


def test_no_operations_fact_means_an_owned_blank_not_a_question():
    """This is the box the model reaches for when it wants somewhere to put
    narrative - so silence must close it, not open it."""
    facts = {k: v for k, v in LIVE.items() if k != "operations_description"}
    assert ps._resolve_certificate_operations_box(OPS_BOX, facts) is None
    assert ps._is_authoritative_blank_field(OPS_BOX, facts)


def test_it_claims_only_the_certificate_box():
    for field in ("Policy_RemarkText_A", "AdditionalRemark_RemarkText_A",
                  "CertificateOfLiabilityInsurance_ACORDForm_RemarkText",
                  "OtherPolicy_PolicyNumberIdentifier_A"):
        assert ps._resolve_certificate_operations_box(field, dict(LIVE)) \
            is ps._SCHED_SKIP


@pytest.mark.parametrize("value", [None, 7, True, [], {}, b"x", 3.5,
                                   {"value": OPS}])
def test_a_degenerate_operations_fact_never_reaches_the_form(value):
    got = ps._resolve_certificate_operations_box(
        OPS_BOX, dict(LIVE, operations_description=value))
    assert got is None or got == OPS


@pytest.mark.parametrize("facts", [None, [], "x", 7])
def test_degenerate_containers_do_not_crash(facts):
    ps._resolve_certificate_operations_box(OPS_BOX, facts)
    ps._resolve_declared_absent_line_row(WC_OTHER, facts)
    ps._family_has_no_evidence(facts, ("workers compensation",
                                       "employers liability"))


def test_payroll_is_not_workers_comp_evidence():
    """THE LIVE SESSION OF 2026-09-07, verbatim. Every genuine WC fact null,
    `has_workers_comp` False, 27 coverage flags computed - and `total_payroll`
    and `wc_payroll_period` populated, because every commercial application
    states payroll. Counting those as evidence made the rule unfireable."""
    facts = dict(LIVE, total_payroll={"value": "$3,120,000", "source": "ai"},
                 wc_payroll_period={"value": "annual", "source": "ai"})
    assert ps._family_has_no_evidence(
        facts, ("workers compensation", "employers liability")) is True
    assert not _band_open(facts)


def test_a_certificate_row_with_no_premium_still_evidences_its_policy():
    """The census read `_line_entry_grants_coverage`, which needs a premium or a
    limit - and "a certificate of insurance never prints premiums", as its own
    twin's docstring says. So on a certificate-led package NO line counted as
    granted and every absence inference built on the census was unreachable."""
    coi_row = {"line": "Commercial General Liability",
               "carrier": "Granite Harbor Insurance Company", "naic": "24198",
               "policy_number": "CWP-4471902", "premium": None,
               "effective_date": "10/07/2026", "expiration_date": "10/07/2027"}
    assert ps._line_entry_evidences_policy(coi_row) is True


@pytest.mark.parametrize("entry", [
    {"line": "Employers Liability", "carrier": "X", "limit": "1,000,000"},
    {"line": "Workers Compensation"},
    {"line": "Property", "premium": "No Coverage"},
    {"line": "GL", "policy_number": "CG 00 01 04 13"},
    {"line": "GL", "policy_number": "   "},
    None, [], "x", 7,
])
def test_a_requirement_shaped_row_still_evidences_nothing(entry):
    """The premium-or-number rule the predicate was written for is unchanged:
    the umbrella's schedule of REQUIRED underlying limits prints a carrier
    beside $1M/$1M/$1M and must never read as a granted policy."""
    assert ps._line_entry_evidences_policy(entry) is False
