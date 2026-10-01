"""Fuzz the 1 Oct 2026 fix round on messy data (owner: "it should work on all
the fuzzy data properly").

Seeded, so every failure reproduces: row order shuffled, the same value printed
with and without spaces, in capitals and in ordinary case, glued by OCR,
duplicated across chunks; typed amounts in every shape a producer types; Yes/No
answers in every spelling. Each test states a PROPERTY that must hold for every
variant, not an expected output for one fixture.
"""
import copy
import importlib.util
import json
import random
import re
from pathlib import Path

import pytest

import services.extraction_service as es
import services.needs_attention as na
import services.signature_boxes as sb
from routes.form_routes import printed_typed_amounts
from services import loss_history_state as lhs
from services import pdf_service as ps

BACKEND = Path(__file__).resolve().parents[1]
SEEDS = range(40)


def _load(name):
    spec = importlib.util.spec_from_file_location(name, BACKEND / "tests" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


G1A = _load("test_fix_g1a_1oct")


def _schema(form_id):
    return json.loads((BACKEND / "forms_schemas" / f"{form_id}_schema.json").read_text())


def _respace(rng, value):
    """The same printed amount the way different pages / chunks print it."""
    digits = re.sub(r"[^\d]", "", value)
    n = int(digits)
    return rng.choice([f"${n:,}", f"$ {n:,}", f"${n:,}.00", f"{n:,}", f"$ {n:,} "])


def _jumble(rng, entries):
    out = []
    for e in entries:
        e = dict(e)
        if rng.random() < 0.5:
            e["value"] = _respace(rng, e["value"]) if re.search(r"\d{3},\d{3}", e["value"]) else e["value"]
        if rng.random() < 0.3:
            e["label"] = e["label"].upper()
        out.append(e)
        if rng.random() < 0.25:                       # the same line read by two chunks
            out.append(dict(e))
    rng.shuffle(out)
    return out


def _amounts(facts):
    return {k: es._amount_key(es._fv(facts, k)) for k in G1A.GL_KEYS}


RIGHT_AMOUNTS = {k: es._amount_key(v) for k, v in G1A.RIGHT.items()}


# ══ GL limits: the line's own declarations decide, in any order or spelling ══

@pytest.mark.parametrize("seed", SEEDS)
def test_the_umbrella_never_becomes_the_gl_limit(seed):
    rng = random.Random(seed)
    facts = G1A._wrong_run_facts()
    es._settle_line_limits(facts, _jumble(rng, G1A.ENTRIES))
    assert _amounts(facts) == RIGHT_AMOUNTS
    assert "3,000,000" not in str(es._fv(facts, "gl_limits"))
    assert es._amount_key(es._fv(facts, "umbrella_limit")) == 3_000_000


@pytest.mark.parametrize("seed", SEEDS)
def test_a_right_run_is_never_touched(seed):
    rng = random.Random(seed)
    facts = {k: G1A._f(v) for k, v in G1A.RIGHT.items()}
    before = copy.deepcopy(facts)
    es._settle_line_limits(facts, _jumble(rng, G1A.ENTRIES))
    assert _amounts(facts) == _amounts(before)


@pytest.mark.parametrize("seed", range(10))
def test_settling_is_the_same_whatever_order_the_rows_came_in(seed):
    rng = random.Random(1000 + seed)
    base = _jumble(rng, G1A.ENTRIES)
    results = set()
    for _ in range(4):
        order = list(base)
        rng.shuffle(order)
        facts = G1A._wrong_run_facts()
        es._settle_line_limits(facts, order)
        results.add(tuple(sorted((k, es._fv(facts, k)) for k in G1A.GL_KEYS + ("gl_limits",))))
    assert len(results) == 1, results


# ══ The 125 carrier line: one order, one printing, whatever the rows say ═════

_WRITERS = [("EMC Property & Casualty Company", "BBC7263 - 26"),
            ("Employers Mutual Casualty Company", "6E7-40-02---26"),
            ("Employers Mutual Casualty Company", "6J7-40-02---26"),
            ("EMPLOYERS MUTUAL CASUALTY COMPANY", "6C7-40-02---26")]


@pytest.mark.parametrize("seed", SEEDS)
def test_the_carrier_line_never_flips(seed):
    rng = random.Random(seed)
    rows = [{"carrier": c, "policy_number": p, "premium": "$1,000"} for c, p in _WRITERS]
    rows += [{"carrier": "Prior Carrier Inc", "policy_number": "", "premium": ""},   # writes nothing
             {"carrier": "", "policy_number": "X-1", "premium": "$5"}]
    for r in rows:
        if rng.random() < 0.3 and r["carrier"]:
            r["carrier"] = "  " + r["carrier"] + " "
    rng.shuffle(rows)
    assert es.current_policy_writer_names(rows) == [
        "EMC Property & Casualty Company", "Employers Mutual Casualty Company"]


@pytest.mark.parametrize("rows", [None, [], "x", [None, 3, "row"], [{"carrier": None}]])
def test_carrier_names_never_raise(rows):
    assert es.current_policy_writer_names(rows) == []


# ══ An insurer is never a vehicle owner or an interest; a lender always can be ═

_INSURER_SPELLINGS = ["Emcasco Insurance Company", "EMCASCO INSURANCE COMPANY",
                      "EMCASCOInsuranceCompany", "Emcasco  Insurance   Co.",
                      "emcasco insurance company"]
_LENDERS = ["Wells Fargo Bank, N.A.", "Toyota Motor Credit Corporation", "Ally Financial Inc",
            "First Insurance Funding Corp", "Imperial PFS Premium Finance Company",
            "Acme Equipment Leasing LLC", "Commercial Risk Solutions Insurance Agency"]


def _facts_naming(carrier="Emcasco Insurance Company"):
    return {"coverage_lines": {"value": [{"carrier": carrier, "policy_number": "6E7", "line": "Auto"}]}}


@pytest.mark.parametrize("seed", SEEDS)
def test_an_insurer_in_any_spelling_is_refused_and_a_lender_never(seed):
    rng = random.Random(seed)
    boxes = [f"AdditionalInterest_FullName_{r}" for r in "ABCD"]
    rng.shuffle(boxes)
    insurer = rng.choice(_INSURER_SPELLINGS)
    lender = rng.choice(_LENDERS)
    mapped = {boxes[0]: insurer, boxes[1]: lender, boxes[2]: "Erin Royal",
              "NamedInsured_FullName_A": insurer}
    ai = set(mapped) | {boxes[3]}                    # one AI box left empty
    out = ps._insurer_in_a_party_box(mapped, _facts_naming(), ai)
    assert set(out) == {boxes[0]}, out
    # what a person typed is theirs, whatever it says
    typed = {**_facts_naming(), "landlord_name": {"value": insurer, "source": "producer"}}
    assert ps._insurer_in_a_party_box(mapped, typed, ai) == {}
    # a box the AI did not write is never judged here
    assert ps._insurer_in_a_party_box(mapped, _facts_naming(), {boxes[1], boxes[2]}) == {}


# ══ Typed amounts print like the stamper's; anything else prints as typed ════

_S125 = _schema("ACORD_125")
_MONEY = "CommercialVehicleLineOfBusiness_PremiumAmount_A"


@pytest.mark.parametrize("seed", SEEDS)
def test_a_typed_amount_is_grouped_and_anything_else_is_left(seed):
    rng = random.Random(seed)
    n = rng.choice([7, 85, 3418, 10663, 125000, 1000000, 2500000])
    cents = rng.choice(["", ".00", ".50"])
    typed = rng.choice(["", "$", "$ "]) + rng.choice([str(n), f"{n:,}"]) + cents
    out = printed_typed_amounts("ACORD_125", {_MONEY: typed}, _S125)
    printed = out.get(_MONEY, typed)
    assert float(re.sub(r"[^\d.]", "", printed)) == float(re.sub(r"[^\d.]", "", typed))  # same amount
    if n >= 1000:
        assert f"{n:,}" in printed                                  # grouped
    for text in ("Included", "See schedule", "5%", "1M", "TBD", "", " "):
        assert _MONEY not in printed_typed_amounts("ACORD_125", {_MONEY: text}, _S125)
    # a name box holding digits is not a money box
    assert printed_typed_amounts("ACORD_125", {"NamedInsured_FullName_A": typed}, _S125) == {}


# ══ A person's casing: kept when chosen, formatted when not ══════════════════

_WORDS = ["acme", "builders", "llc", "cbre", "group", "inc", "jll", "ii", "partners", "denver"]


@pytest.mark.parametrize("seed", SEEDS)
def test_casing_is_kept_only_when_the_person_chose_it(seed):
    rng = random.Random(seed)
    words = [rng.choice(_WORDS) for _ in range(rng.randint(1, 4))]
    if rng.random() < 0.6:
        words = [w.upper() if rng.random() < 0.4 else w for w in words]
    typed = ("  " if rng.random() < 0.3 else "") + "  ".join(words)
    box = "AdditionalInterest_FullName_A"
    printed = ps.display_value_for_box("ACORD_125", box, typed, provenance="producer")
    as_document = ps.display_value_for_box("ACORD_125", box, typed, provenance="filled")
    if any(ch.isupper() for ch in typed):
        assert printed == re.sub(r"\s+", " ", typed).strip()
    else:
        assert printed == as_document


# ══ A refused Yes/No is never repeated, in any spelling, on any question ═════

_YN = ["Y", "N", "Yes", "No", "y", "n", "YES", "no ", " Yes", "true", "false"]


@pytest.mark.parametrize("form_id", ["ACORD_125", "ACORD_126", "ACORD_127", "ACORD_131", "ACORD_186"])
def test_no_refused_answer_is_quoted(form_id):
    schema = _schema(form_id)
    questions = [f for f in schema if na.is_question_box(schema, f)]
    assert questions
    rng = random.Random(form_id)
    for field in rng.sample(questions, min(25, len(questions))):
        answer = rng.choice(_YN)
        reason, quotable = na.held_back(schema, field, answer, {})
        assert quotable is False and answer.strip() not in re.findall(r'"([^"]*)"', reason), (field, reason)


# ══ "Check if none" unticked is never "we have had claims" ═══════════════════

@pytest.mark.parametrize("seed", SEEDS)
def test_an_untick_in_any_spelling_is_not_a_claims_answer(seed):
    rng = random.Random(seed)
    word = rng.choice(["No", "N", "false", "0", "Off", "no", "NO", "n"])
    value = rng.choice(["", " ", "  "]) + word + rng.choice(["", " "])
    held = rng.choice([value, {"value": value, "source": "producer"}])
    assert lhs.had_claims_answer({"loss_history_no_prior_losses_indicator": held}) is False


# ══ Whose box is it: the tooltip and the name must agree ═════════════════════

_TIPS = {
    "producer": "Sign here: Accommodates the signature of the authorized representative "
                "(e.g., producer, agent, broker, etc.) of the company(ies) listed.",
    "applicant": "Sign here: Accommodates the signature of the applicant or named insured.",
    None: "Sign here: Accommodates a signature.",
}
_NAMES = {"producer": "Producer_AuthorizedRepresentative_Signature_{r}",
          "applicant": "NamedInsured_Signature_{r}",
          None: "Signature_{r}"}


@pytest.mark.parametrize("seed", SEEDS)
def test_a_signature_box_belongs_to_whoever_both_say(seed):
    rng = random.Random(seed)
    by_tip, by_name = rng.choice(list(_TIPS)), rng.choice(list(_NAMES))
    field = _NAMES[by_name].format(r=rng.choice("ABC"))
    kind, signer = sb.signature_box(field, _TIPS[by_tip], rng.choice(["/Tx", "/Sig", ""]))
    assert kind == sb.KIND_SIGNATURE
    if by_tip and by_name and by_tip != by_name:
        assert signer is None                         # disagreement: nobody
    else:
        assert signer == (by_tip or by_name)
    assert sb.is_producer_signature(field, _TIPS[by_tip]) == (signer == "producer")
