"""One policy printed two ways is ONE policy (Sep 1 SYS-06 audit, 13 Oct 2026).

The dec prints `BBC7263 - 26`, the certificate prints `BBC7263`. SYS-07b made
`same_policy_contract` treat those as one policy, but five pdf_service resolvers
still counted policies by EXACT normalised text - so the two printings read as
"2 different policy numbers attached to this line" and the ACORD 126 / 127 / 131
header shipped blank. The dec index masks it on first generation; it bit on every
re-stamp after `PURGE_DEC_INDEX_AFTER_GENERATION` and on a form added later.

`pdf_service._policy_contracts` is now the one count. The adversarial cases come
first: two REAL policies, two terms of one number and digits that run together
must stay apart, because folding them would print a wrong policy number on a
signed application. Blank stays blank there.
"""
import ast
import itertools
import logging
import pathlib
import sys

import pytest

from services import extraction_service as es
from services import pdf_service as ps

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from test_sys06_line_specific_identity_20260904 import (  # noqa: E402
    COI_ROWS, DEC_ROWS, RIVAL_GL, _doc,
)

BACKEND = pathlib.Path(__file__).resolve().parents[1]
GL_PHRASES = ps._SECTION_FORM_LINE_PHRASES["ACORD_126"]


# ════════════════════════════════════════════════════════════════════════════
# 1. ADVERSARIAL FIRST - what the count must never fold
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("pair", [
    ("BBC7263-26", "GL-4471102-26"),     # two carriers' GL policies (D-1)
    ("POL123", "POL12345"),              # digits run together: two policies
    ("BBC7263", "BBC7264"),
])
def test_two_real_policies_stay_two(pair):
    for order in (pair, pair[::-1]):
        assert len(ps._policy_contracts(order)) == 2


def test_two_terms_of_one_number_never_fold_whatever_the_order():
    """A bare `BBC7263` matches both `- 25` and `- 26`. It must not bridge them
    into one policy - that would print one term's number as the other's."""
    for order in itertools.permutations(["BBC7263", "BBC7263 - 25", "BBC7263 - 26"]):
        assert len(ps._policy_contracts(order)) >= 2, order


def test_a_line_with_two_real_policies_still_ships_blank():
    docs = [_doc("dec.pdf", "dec_page", RIVAL_GL)]
    facts, _ = es.merge_facts(docs, docs[0])
    gl = dict(facts)
    gl["_form_id"] = "ACORD_126"
    assert ps._deterministic_map("Policy_PolicyNumberIdentifier_A", gl) in (None, "")


# ════════════════════════════════════════════════════════════════════════════
# 2. The count itself - every edge
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("printings", [[], None, ["", "  ", None]])
def test_nothing_counts_as_no_policy(printings):
    assert ps._policy_contracts(printings) == []


def test_one_printing_is_one_policy():
    assert ps._policy_contracts(["BBC7263"]) == ["BBC7263"]


@pytest.mark.parametrize("order", [("BBC7263 - 26", "BBC7263"), ("BBC7263", "BBC7263 - 26")])
def test_two_printings_of_one_policy_are_one_in_its_fullest_printing(order):
    assert ps._policy_contracts(order) == ["BBC7263 - 26"]


def test_three_printings_of_one_policy_are_one():
    for order in itertools.permutations(["6E74002", "6E7-40-02---26", "6E7 40 02 26"]):
        assert len(ps._policy_contracts(order)) == 1, order


@pytest.mark.parametrize("order", [("BBC 7263", "BBC7263"), ("BBC7263", "BBC 7263")])
def test_exact_text_twins_keep_the_first_printing_as_before(order):
    """Unchanged behaviour: a value that printed before prints byte-identically."""
    assert ps._policy_contracts(order) == [order[0]]


def test_a_non_number_is_refused_before_it_is_counted():
    refused = "COMMERCIAL AUTO CA DS 70 01 09 06"
    assert ps._not_a_contract_number(refused)
    assert ps._policy_contracts([refused, "6E7-40-02---26"]) == ["6E7-40-02---26"]


def test_the_order_is_deterministic():
    """Callers only count, but a log line must not change between runs."""
    printings = ["6E74002", "BBC7263", "6E7-40-02---26"]
    assert ps._policy_contracts(printings) == ["BBC7263", "6E7-40-02---26"]
    assert ps._policy_contracts(printings) == ps._policy_contracts(list(printings))


# ════════════════════════════════════════════════════════════════════════════
# 3. The reported defect, through the REAL merge and stamper
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("reverse", [False, True])
def test_the_section_headers_print_their_own_policy_after_the_index_is_gone(reverse):
    """Dec + certificate, no dec index (the post-purge shape). Before the fix
    all three headers were blank; each now prints its OWN line's number."""
    docs = [_doc("dec.pdf", "dec_page", DEC_ROWS), _doc("coi.pdf", "certificate", COI_ROWS)]
    if reverse:
        docs.reverse()
    facts, _ = es.merge_facts(docs, docs[0])
    assert not facts.get("dec_page_entries")
    want = {"ACORD_126": "BBC7263 - 26", "ACORD_127": "6E7-40-02---26",
            "ACORD_131": "6J7-40-02---26"}
    for form_id, number in want.items():
        f = dict(facts)
        f["_form_id"] = form_id
        assert ps._deterministic_map("Policy_PolicyNumberIdentifier_A", f) == number, form_id


# ════════════════════════════════════════════════════════════════════════════
# 4. The other four resolvers that shared the count
# ════════════════════════════════════════════════════════════════════════════

def test_the_underlying_schedule_names_one_policy_in_two_printings():
    facts = {"underlying_policies": [
        {"line": "General Liability", "policy_no": "BBC7263"},
        {"line": "Commercial General Liability", "policy_no": "BBC7263 - 26"},
    ]}
    assert ps._underlying_policy_number(facts, GL_PHRASES) == "BBC7263 - 26"
    facts["underlying_policies"].append(
        {"line": "General Liability", "policy_no": "GL-4471102-26"})
    assert ps._underlying_policy_number(facts, GL_PHRASES) is None


def test_the_prior_grid_rescue_names_one_policy_in_two_printings():
    term = {"effective_date": "07/15/2025", "expiration_date": "07/15/2026"}
    grid = [{"line": "General Liability", "policy_no": p,
             "effective": "07/15/2025", "expiration": "07/15/2026"}
            for p in ("BBC7263", "BBC7263 - 26")]
    facts = {"prior_coverage_by_line": grid}
    assert ps._current_number_from_prior_grid(facts, GL_PHRASES, [term]) == "BBC7263 - 26"
    grid.append({"line": "General Liability", "policy_no": "GL-4471102-26",
                 "effective": "07/15/2025", "expiration": "07/15/2026"})
    assert ps._current_number_from_prior_grid(facts, GL_PHRASES, [term]) is None


def _package(rows):
    return {"_form_id": "ACORD_125", "coverage_lines": rows}


def test_the_package_header_counts_policies_the_way_its_own_precheck_does():
    """`_distinct_package_policies` already folded the two printings; the
    second count in the same resolver did not, and blanked the box anyway."""
    one = _package([
        {"line": "Commercial General Liability", "carrier": "EMC Property & Casualty Company",
         "policy_number": "BBC7263 - 26", "premium": "$4,000"},
        {"line": "Commercial Property", "carrier": "EMC Property & Casualty Company",
         "policy_number": "BBC7263", "premium": "$3,000"},
    ])
    assert len(ps._distinct_package_policies(one)) == 1
    assert ps._resolve_package_header_identity("Policy_PolicyNumberIdentifier_A", one) == "BBC7263 - 26"

    two = _package([dict(r) for r in one["coverage_lines"]])
    two["coverage_lines"][1]["policy_number"] = "CPP-9921-26"
    assert ps._resolve_package_header_identity("Policy_PolicyNumberIdentifier_A", two) is None


def test_a_number_another_line_claims_in_another_printing_is_still_claimed(caplog):
    """The package-wide fallback. GL states no number; the package's only
    policy is printed `6E7-40-02---26` on an unplaceable row and `6E74002` on
    the AUTO row. Now that the two printings count as one policy, the claim
    must be read the same way - text equality would miss it and stamp the auto
    policy on the General Liability form."""
    rows = [
        {"line": "Commercial General Liability", "carrier": "EMC Property & Casualty Company",
         "premium": "$4,000"},
        {"line": "Commercial Auto", "carrier": "Employers Mutual Casualty Company",
         "policy_number": "6E74002", "premium": "$2,991"},
        {"line": "Package", "carrier": "Employers Mutual Casualty Company",
         "policy_number": "6E7-40-02---26"},
    ]
    facts = {"coverage_lines": rows, "_form_id": "ACORD_126"}
    with caplog.at_level(logging.INFO, logger="services.pdf_service"):
        got = ps._resolve_section_policy_identity("Policy_PolicyNumberIdentifier_A", facts)
    assert got is None
    assert "printed against a different coverage line" in caplog.text


# ════════════════════════════════════════════════════════════════════════════
# 5. Anti-rot - the count has one owner
# ════════════════════════════════════════════════════════════════════════════

def test_no_resolver_counts_policies_by_exact_text_again():
    """`<dict>.setdefault(_norm_policy_no(...), ...)` is the shape that counted
    printings instead of policies. Only `_policy_contracts` may use it, as its
    first-printing dedupe before the contract fold."""
    tree = ast.parse((BACKEND / "services" / "pdf_service.py").read_text())
    offenders = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if fn.name == "_policy_contracts":
            continue
        for node in ast.walk(fn):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "setdefault" and node.args
                    and isinstance(node.args[0], ast.Call)
                    and getattr(node.args[0].func, "id", "") == "_norm_policy_no"):
                offenders.append(f"{fn.name}:{node.lineno}")
    assert not offenders, offenders


def test_the_guard_can_see_the_shape_it_forbids():
    """C25 trap: a guard that matches nothing passes vacuously."""
    src = ("def f(xs):\n    d = {}\n    for x in xs:\n"
           "        d.setdefault(_norm_policy_no(x), x)\n    return d\n")
    hits = [n for n in ast.walk(ast.parse(src))
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "setdefault"
            and getattr(n.args[0].func, "id", "") == "_norm_policy_no"]
    assert len(hits) == 1
