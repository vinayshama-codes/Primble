"""ONE DOOR for "does this text mention this term?" - `services/term_match.py`.

A bare `term in text` answers a DIFFERENT question: "do these letters appear
anywhere". Thirty-three sites asked it that way. Every case below was measured
live with a control input, not imagined:

    "bank"       inside  2255 SHOREBANK AVENUE      -> buy Crime coverage
    "tech"       inside  HVAC service TECHNICIANS   -> buy Cyber coverage
    "atm"        inside  wastewater TREATMENT plant -> buy Crime coverage
    "California" inside  1450 CALIFORNIA ST, DENVER -> the CALIFORNIA state form
    "building"   inside  OUTBUILDING VALUE: 45,000  -> form generation REFUSED

WHY A SHARED DOOR AND NOT ANOTHER LOCAL FIX. `sqs_service._lob_from_operations`
was given word boundaries, a single-bucket rule and an ownership test on
2026-09-05. Its twin `_ops_to_industry` sat 78 lines below it in the same file
with the same defect and was not touched, because it was a separate copy. Two
copies is the whole disease.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline-test")

from services import term_match as tm                             # noqa: E402


# ── 1. The live false positives ─────────────────────────────────────────────

@pytest.mark.parametrize("term,text,why", [
    ("bank", "2255 SHOREBANK AVENUE, CHICAGO IL 60617", "the client's own report"),
    ("bank", "Riverbank Drive", "another street"),
    ("bank", "Fairbanks AK", "a city"),
    ("atm", "municipal wastewater TREATMENT plants", "treATMent"),
    ("bar", "placement of REBAR and structural steel", "reBAR"),
    ("vault", "framing including VAULTED ceilings", "VAULTed"),
    ("tech", "HVAC service TECHNICIANS on rooftop units", "TECHnicians"),
    ("tech", "GEOTECHNICAL drilling and soil testing", "geoTECHnical"),
    ("farm", "FARMINGTON HILLS MI light trucks", "FARMington"),
    ("coi", "Coinsurance_Endorsement_2026.pdf", "COInsurance"),
    ("mill", "TOTAL INSURED VALUES: 4.5 million", "MILLion"),
    ("rcv", "RCVD 07/15/2025 underwriting dept", "RCVd"),
    ("no claims", "FRESNO CLAIMS SERVICE CENTER", "fresNO CLAIMS"),
    ("emod", "kitchen and bathroom REMODELING", "rEMODeling"),
    ("licensed", "no UNLICENSED drivers are permitted", "unLICENSED - a negation"),
])
def test_a_term_inside_a_longer_word_is_not_a_mention(term, text, why):
    assert tm.present(term, tm.fold(text)) is False, why


@pytest.mark.parametrize("term,text", [
    ("bank", "Operates a community BANK branch"),
    ("tech", "we are a tech company"),
    ("farm", "the farm is 40 acres"),
    ("workers compensation", "WORKERS' COMPENSATION coverage"),
    ("e commerce", "E-Commerce retailer"),
    ("motor carrier", "interstate MOTOR CARRIER operations"),
    ("8810", "class code 8810 clerical"),
])
def test_a_real_mention_is_still_found(term, text):
    assert tm.present(term, tm.fold(text)) is True


def test_a_number_inside_a_longer_number_is_not_a_mention():
    """The H1-F defect, one door over: a payroll of 540300 is not class 5403."""
    folded = tm.fold([{"code": "8810", "description": "Clerical", "payroll": "540300"}])
    assert tm.present("5403", folded) is False
    assert tm.present("8810", folded) is True


# ── 2. Looseness is opt-in, never inherited ─────────────────────────────────

def test_plurals_are_OFF_by_default():
    """Load-bearing. `_has_explicit_follow_form` breaks the moment "following
    form" matches "following forms" - that IS its bug."""
    assert tm.present("following form", tm.fold("the following forms are attached")) is False
    assert tm.present("following form", tm.fold("this policy is following form")) is True


def test_plurals_when_asked_for():
    assert tm.present("restaurant", tm.fold("we operate two restaurants"), plural=True)
    assert tm.present("bakery", tm.fold("two bakeries downtown"), plural=True) is False


def test_stems_are_OFF_by_default_and_keep_a_left_boundary():
    assert tm.present("agricultur", tm.fold("agricultural spraying")) is False
    assert tm.present("agricultur", tm.fold("agricultural spraying"), stem=True) is True
    assert tm.present("agricultur", tm.fold("theagricultural spraying"), stem=True) is False


# ── 3. Ownership, and the single-bucket rule ────────────────────────────────

_BUCKETS = (("restaurant", ("restaurant", "cafe")),
            ("contractor", ("roofing", "contractor")))


def test_one_bucket_wins_and_two_buckets_abstain():
    assert tm.sole_bucket(_BUCKETS, "Full service restaurant") == "restaurant"
    assert tm.sole_bucket(_BUCKETS, "Restaurant construction contractor") is None


def test_somebody_elses_trade_is_not_the_subjects():
    """The client's own example. One bucket, whole words, and still wrong."""
    ops = "Janitorial services for grocery, restaurant and retail accounts"
    assert tm.sole_bucket(_BUCKETS, ops) == "restaurant"          # boundaries alone
    assert tm.sole_bucket(_BUCKETS, ops, require_subject=True) is None


def test_naming_a_customer_does_not_erase_the_subjects_own_trade():
    assert tm.sole_bucket(_BUCKETS, "Roofing contractor serving restaurant chains",
                          require_subject=True) == "contractor"


def test_ownership_reads_raw_text_so_sentence_boundaries_survive():
    """It runs on the unfolded text on purpose: folding turns every full stop
    into a space, and the customer cues are bounded by `[^.]`, so a cue would
    leak across two sentences."""
    two = "We run a restaurant. Deliveries are made to grocery accounts."
    assert tm.describes_the_subject("restaurant", two) is True


# ── 4. Any data at all. These are called inside score computations ──────────

@pytest.mark.parametrize("value", [
    None, 0, 1, False, True, 3.14, b"bytes", bytearray(b"x"), "", "   ",
    ["a", ["b", {"c": "bank"}]], {"value": "bank"}, {"a": {"b": "bank"}},
    {1: 2}, {"x": None}, set(["bank"]), (), 10 ** 50, "\ud800bad",
    # An explicit id: pytest puts the parameter into PYTEST_CURRENT_TEST, and a
    # 100k-character value exceeds the 32,767-char limit on an environment
    # variable, which fails the RUN rather than the code.
    pytest.param("x" * 100000, id="a-very-long-document"),
])
def test_no_haystack_can_raise(value):
    folded = tm.fold(value)
    assert isinstance(folded, str)
    tm.present("bank", folded)
    tm.matched(["bank", "tech"], folded)
    tm.find("bank", folded)
    list(tm.mentions("bank", folded))
    tm.sole_bucket(_BUCKETS, value)
    tm.describes_the_subject("bank", value)


@pytest.mark.parametrize("term", [
    None, "", "   ", "---", 0, 7, ["bank"], {"value": "bank"}, {"a": 1},
    set(["bank"]), b"bank", object(),
])
def test_no_term_can_raise(term):
    """A term arriving as a list or dict is unhashable, and `lru_cache` raises
    on those BEFORE the function body runs - found by fuzzing, not by reading."""
    folded = tm.fold("a bank branch here")
    assert isinstance(tm.present(term, folded), bool)
    tm.find(term, folded)
    tm.matched(term, folded)
    tm.describes_the_subject(term, "a bank branch here")


def test_an_envelope_is_unwrapped_and_a_container_uses_its_leaves():
    """Never the repr: the punctuation in `[{'code': ...}]` is how a payroll
    became a class code in the first place."""
    assert tm.present("bank", tm.fold({"value": "community bank"})) is True
    assert tm.present("clerical", tm.fold([{"code": "8810", "desc": "clerical"}])) is True


def test_a_boolean_is_not_text():
    assert tm.fold(True).strip() == ""


def test_fold_is_idempotent_and_padded():
    once = tm.fold("A-B  c.")
    assert tm.fold(once) == once
    assert once.startswith(" ") and once.endswith(" ")


# ── 5. The consumers, end to end ────────────────────────────────────────────

def test_the_clients_bank_warning_is_gone_and_a_real_bank_still_warns():
    from services.cross_form_validator import _check_crime_silent_exposure as crime
    street = {"certificate_description_of_operations":
              "RE: Job #4412 - tuckpointing at 2255 SHOREBANK AVENUE, CHICAGO IL 60617"}
    assert crime(street, {}, set()) == []
    real = {"operations_description": "Operates a community bank branch with teller windows"}
    assert crime(real, {}, set()), "a genuine cash exposure must still warn"


def test_a_contractor_is_not_told_to_buy_cyber():
    from services.cross_form_validator import _check_cyber_silent_exposure as cyber
    assert cyber({"operations_description":
                  "HVAC service technicians perform preventive maintenance"}, {}, set()) == []
    assert cyber({"operations_description":
                  "We operate a SaaS platform for online payments"}, {}, set())


@pytest.mark.parametrize("ops", [
    "Apartment building owner; 62 units with long-term tenants residing on site.",
    "Overhauling of industrial pumps",
    "Insurance agency serving contractors and building trades.",
])
def test_the_twin_no_longer_invents_an_industry(ops):
    """`_ops_to_industry` fed a -15 ops/class-code mismatch twice over."""
    from services.sqs_service import _ops_to_industry
    assert _ops_to_industry(ops.lower(), "") is None


@pytest.mark.parametrize("ops,expected", [
    ("Commercial roofing contractor", "construction"),
    ("Long haul trucking company", "transportation"),
])
def test_the_twin_still_classifies_what_it_should(ops, expected):
    from services.sqs_service import _ops_to_industry
    assert _ops_to_industry(ops.lower(), "") == expected


@pytest.mark.parametrize("address,expected", [
    ("1450 California Street, Suite 900, Denver, CO 80202", "CO"),
    ("120 Nevada Ave, Colorado Springs, CO 80903", "CO"),
    ("9 Indiana Avenue, Kansas City, MO 64127", "MO"),
    ("4800 Dahlia St, Denver, CO 80216", "CO"),
    ("1200 Main St, Sacramento, CA 95814", "CA"),
    ("Denver, Colorado", "CO"),
    ("CA", "CA"),
])
def test_a_street_named_after_a_state_no_longer_picks_the_form(address, expected):
    """THE WORST ONE IN THE SWEEP: this shipped a California form to a Colorado
    risk. The patterns were all already \\b-anchored - the ORDER was the bug."""
    from services.form_service import _extract_state_code
    assert _extract_state_code(address) == expected


def test_an_outbuilding_no_longer_blocks_form_generation():
    """`property_building_value` is the only generation-blocking reconcilable
    key, so a false conflict here refuses to produce forms at all."""
    from services.underwriting_consistency import _text_scan_values
    text = "PROPERTY SCHEDULE\nBuilding Value: 1,250,000\nOutbuilding Value: 45,000\n"
    assert _text_scan_values(text, "property_building_value") == ["1,250,000"]


def test_two_genuine_building_figures_still_both_scan():
    from services.underwriting_consistency import _text_scan_values
    text = "Building Value: 1,250,000\nBuilding Limit: 900,000\n"
    assert len(_text_scan_values(text, "property_building_value")) == 2


# ── 6. Anti-rot ─────────────────────────────────────────────────────────────

def test_the_door_imports_nothing_from_the_app():
    """Stdlib-only is load-bearing, not tidiness. `lob_canon` is the deepest
    leaf in the service layer and a consumer; `sqs_service` and
    `cross_form_validator` already import each other lazily. One `services`
    import here and this module cannot sit below all three."""
    import re as _re
    src = open(os.path.join(os.path.dirname(__file__), "..", "services",
                            "term_match.py"), encoding="utf-8").read()
    bad = _re.findall(r"^\s*(?:from|import)\s+(services|utils|config|routes)\b",
                      src, _re.M)
    assert not bad, f"term_match must stay a leaf; found imports of {set(bad)}"


def test_the_customer_regexes_have_exactly_one_definition():
    """They were written in `cross_form_validator`, then needed unchanged by
    `sqs_service`. Two copies would drift; the re-export keeps one."""
    from services import cross_form_validator as cfv
    assert cfv._CUSTOMER_BEFORE_RE is tm._CUSTOMER_BEFORE_RE
    assert cfv._CUSTOMER_AFTER_RE is tm._CUSTOMER_AFTER_RE


def test_the_two_industry_classifiers_both_go_through_the_door():
    """The defect this door exists for was one classifier fixed and its twin,
    78 lines away, not. If either stops asking, they can drift again."""
    import inspect
    from services import sqs_service as sq
    for fn in (sq._ops_to_industry, sq._lob_from_operations):
        assert "term_match" in inspect.getsource(fn), fn.__name__
