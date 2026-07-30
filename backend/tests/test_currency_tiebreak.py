"""C23 - the currency tiebreak must not pull Umbrella limits into GL fields.

Measured on a real submission (ORBIN CONTRACTING LLC, 2026-07-29) containing a
General Liability part ($1M each occurrence / $2M aggregate) AND a Commercial
Liability Umbrella ($3M). The merge step logged:

    merge field='gl_each_occurrence' currency tiebreak: chose 'each occurrence
      limit (liability coverage) $ 3,000,000' over '$1,000,000' by magnitude

...while the composite `gl_limits` fact from the SAME run said `each occurrence
$1,000,000 ... general aggregate $2,000,000`. Two facts from one document
contradicting each other, and the wrong one is what stamps ACORD 125/126/25.
Wrong limits on a certificate of liability is the failure mode with legal
exposure.

Root cause was three defects in six lines - see the comment at the tiebreak.

THESE TESTS DRIVE THE REAL `_merge_list_fields`. They deliberately do NOT
reimplement the tiebreak in a local harness, which is what the first version of
this file did: a copy of production logic inside a test can only tell you the
copy is self-consistent, and it needed a string-matching "drift check" to notice
when it stopped describing reality - which then failed the build for a comment
reword rather than a behaviour change. Same defect class as C12 (two places
computing the fields-block size). One implementation, exercised directly.
"""
import logging

import pytest

import services.extraction_service as ex


def _merge(*facts_per_chunk):
    """Run the real cross-chunk merge. Each argument is a {field: value} dict
    representing one document chunk's extracted facts."""
    partials = [
        {
            "_chunk_idx": i,
            "facts": {k: {"value": v, "confidence": "ai_low"} for k, v in d.items()},
        }
        for i, d in enumerate(facts_per_chunk)
    ]
    out = ex._merge_list_fields(partials, [])
    return {
        k: (v.get("value") if isinstance(v, dict) else v)
        for k, v in out["facts"].items()
    }


_GL_COMPOSITE = ("each occurrence limit $1,000,000; general aggregate limit "
                 "$2,000,000; products/completed operations aggregate limit "
                 "$2,000,000")
_UMBRELLA = "each occurrence limit (liability coverage) $ 3,000,000"


# ── Defect 3: magnitude is meaningless on a composite ────────────────────────

def test_currency_magnitude_is_garbage_on_composite_strings():
    """Documented so nobody reintroduces a magnitude sort over these fields.
    `_currency_magnitude` strips non-digits and parses the remainder."""
    assert ex._currency_magnitude(_GL_COMPOSITE) > 1e18, (
        "expected the documented pathology; if this now returns something sane, "
        "_currency_magnitude was fixed and this test's premise should be revisited"
    )
    assert "gl_limits" in ex._CURRENCY_FIELDS, (
        "gl_limits is a composite field yet lives in _CURRENCY_FIELDS - that is "
        "what let 'most digits wins' decide it"
    )


def test_composite_is_not_beaten_by_a_bare_larger_number():
    """The composite used to score 1.0e+20 and win everything; the inverse must
    also hold - a bare $3,000,000 must not now beat the real composite."""
    got = _merge({"gl_limits": _GL_COMPOSITE}, {"gl_limits": "$3,000,000"})
    assert got["gl_limits"] == _GL_COMPOSITE


# ── Defect 1: the reported bug, in BOTH document orders ──────────────────────

@pytest.mark.parametrize("umbrella_first", [False, True])
def test_umbrella_limit_never_wins_a_gl_field(umbrella_first):
    """The outcome must not depend on which chunk mentioned the amount first.

    Killing the magnitude sort alone left this decided by document order - the GL
    figure won if it appeared first and the umbrella figure won if IT did, i.e. a
    coin flip on a number that prints on a certificate. The composite-consistency
    check settles it: only the candidate whose amount actually appears in the
    already-resolved `gl_limits` survives.
    """
    scalars = [_UMBRELLA, "$1,000,000"] if umbrella_first else ["$1,000,000", _UMBRELLA]
    got = _merge(
        {"gl_limits": _GL_COMPOSITE, "gl_each_occurrence": scalars[0]},
        {"gl_each_occurrence": scalars[1]},
    )
    assert got["gl_each_occurrence"] == "$1,000,000", (
        f"the $3,000,000 Umbrella figure won a General Liability field "
        f"(umbrella_first={umbrella_first}, got {got['gl_each_occurrence']!r}). "
        f"Umbrella/excess limits are by definition larger, so any rule preferring "
        f"the larger amount is inverted exactly where two coverage parts coexist - "
        f"which is most real packages."
    )


def test_aggregate_also_reconciles_against_the_composite():
    got = _merge(
        {"gl_limits": _GL_COMPOSITE, "gl_aggregate": "$ 3,000,000"},
        {"gl_aggregate": "$2,000,000"},
    )
    assert got["gl_aggregate"] == "$2,000,000"


def test_composite_is_resolved_before_its_scalar_children():
    """The consistency check can only work if `gl_limits` is already merged when
    `gl_each_occurrence` is decided. Field iteration order is what guarantees it,
    so assert it directly rather than relying on dict ordering luck."""
    order = sorted(
        ["gl_each_occurrence", "gl_limits", "gl_aggregate"],
        key=lambda f: (f not in ex._CURRENCY_COMPOSITES, f),
    )
    assert order[0] == "gl_limits"


# ── The one legitimate magnitude case ────────────────────────────────────────

@pytest.mark.parametrize("zero_first", [True, False])
def test_a_real_limit_still_beats_a_literal_zero(zero_first):
    """The ONE case the magnitude tiebreak legitimately existed for."""
    vals = ["$0", "$8,750,000"] if zero_first else ["$8,750,000", "$0"]
    got = _merge({"gl_aggregate": vals[0]}, {"gl_aggregate": vals[1]})
    assert got["gl_aggregate"] == "$8,750,000", (
        "a zero-valued candidate beat a real limit - the narrow non-zero rule "
        "was removed along with the broken magnitude sort"
    )


# ── Defect 2: the re-sort was global ─────────────────────────────────────────

def test_scoring_order_is_not_discarded_for_a_distant_candidate():
    """A low-scoring candidate with a huge number must never win. Frequency
    drives the score, so a thrice-seen $1,000,000 must beat a one-off
    $99,000,000 that the old global re-sort would have promoted from 4th place."""
    got = _merge(
        {"gl_each_occurrence": "$1,000,000"},
        {"gl_each_occurrence": "$1,000,000"},
        {"gl_each_occurrence": "$1,000,000"},
        {"gl_each_occurrence": "$99,000,000"},
    )
    assert got["gl_each_occurrence"] == "$1,000,000", (
        "a single-occurrence $99,000,000 beat a thrice-seen $1,000,000 - the "
        "global magnitude re-sort is back (C23 defect 2)"
    )


def test_global_magnitude_resort_is_not_reintroduced():
    """Source-level guard. Cheap, and the only way to catch someone 'restoring'
    the old behaviour in a shape the cases above happen not to cover."""
    import inspect
    src = inspect.getsource(ex._merge_list_fields)
    assert "key=lambda x: _currency_magnitude" not in src, (
        "the global magnitude re-sort has been reintroduced (C23 defect 2)"
    )


# ── Composite consistency must not overreach ─────────────────────────────────

def test_no_composite_means_no_action_and_no_crash():
    """With no `gl_limits` to check against, the rule must do nothing rather than
    guess. Order-dependence remains in this case, and that is honest - there is
    no better witness available."""
    got = _merge({"gl_each_occurrence": "$1,000,000"}, {"gl_each_occurrence": _UMBRELLA})
    assert got["gl_each_occurrence"] in ("$1,000,000", _UMBRELLA)


def test_does_not_act_when_both_candidates_appear_in_the_composite():
    """If the composite contains both amounts it cannot separate them, so the
    ordinary scoring must stand - inventing a preference here would be a guess."""
    composite = "each occurrence $1,000,000 or $2,000,000 per project"
    got = _merge(
        {"gl_limits": composite, "gl_each_occurrence": "$2,000,000"},
        {"gl_each_occurrence": "$1,000,000"},
    )
    assert got["gl_each_occurrence"] in ("$1,000,000", "$2,000,000")


def test_mismatch_between_scalar_and_composite_is_logged(caplog):
    """When NEITHER tied candidate appears in the composite, the two facts
    disagree and the operator must be told - silently stamping one is how C23
    stayed invisible for so long."""
    with caplog.at_level(logging.WARNING, logger="services.extraction_service"):
        _merge(
            {"gl_limits": _GL_COMPOSITE, "gl_each_occurrence": "$5,000,000"},
            {"gl_each_occurrence": "$7,000,000"},
        )
    assert any("composite MISMATCH" in r.message for r in caplog.records), (
        "a scalar limit disagreeing with its own composite was stamped silently"
    )


def test_money_amounts_requires_a_dollar_sign():
    """The containment test must not treat a year or a class code as money - a
    false member would let a wrong candidate look 'consistent'."""
    assert ex._money_amounts("effective 2025, class code 91560") == set()
    assert ex._money_amounts("limit $1,000,000 and $2,000,000") == {1000000.0, 2000000.0}
    assert ex._money_amounts("$1,000,000.50") == {1000000.50}


# ── The live ORBIN regression (2026-07-30) ───────────────────────────────────
# The first fix reconciled each scalar against the composite. It did nothing on
# this real package, because the COMPOSITE ITSELF was the umbrella one - so every
# scalar "agreed" with a wrong witness and all three came out $3,000,000 against a
# real GL part of $1M/$2M. Two separate defects had to be fixed:
#   * nothing was choosing between competing COMPOSITES
#   * the scalar check required exactly ONE consistent candidate, and
#     '$ 1,000,000' / '$1,000,000' are two candidates for the same amount
# Both are reproduced here with the verbatim strings from the run's merge log.

_ORBIN_UMBRELLA = (
    "each occurrence limit (liability coverage) $ 3,000,000; personal & advertising "
    "injury limit $ 3,000,000; aggregate limit (liability coverage) $ 3,000,000")
_ORBIN_GL_SHORT = (
    "general aggregate $ 2,000,000; products-completed operations aggregate "
    "$ 2,000,000; personal and advertising injury $ 1,000,000; each occurrence "
    "$ 1,000,000")
_ORBIN_GL_FULL = (
    "each occurrence limit $1,000,000; damage to premises rented to you limit "
    "$500,000(any one premises); medical expense limit $10,000(any one person); "
    "personal and advertising injury limit $1,000,000(any one person or "
    "organization); general aggregate limit $2,000,000; products/completed "
    "operations aggregate limit $2,000,000")


def _orbin(composite_order):
    partials = []
    for i, comp in enumerate(composite_order):
        partials.append({"_chunk_idx": i,
                         "facts": {"gl_limits": {"value": comp, "confidence": "ai_low"}}})
    scalars = [
        ("gl_each_occurrence", ["$ 3,000,000", "$ 1,000,000", "$1,000,000"]),
        ("gl_aggregate", ["$ 3,000,000", "$ 2,000,000", "$2,000,000"]),
        ("gl_personal_advertising_injury", ["$ 3,000,000", "$ 1,000,000", "$1,000,000"]),
        ("gl_products_aggregate", ["$ 2,000,000", "$2,000,000"]),
    ]
    for name, vals in scalars:
        for v in vals:
            partials.append({"_chunk_idx": len(partials),
                             "facts": {name: {"value": v, "confidence": "ai_low"}}})
    out = ex._merge_list_fields(partials, [])["facts"]
    return {k: (v.get("value") if isinstance(v, dict) else v) for k, v in out.items()}


@pytest.mark.parametrize("order", [
    [_ORBIN_UMBRELLA, _ORBIN_GL_SHORT, _ORBIN_GL_FULL],
    [_ORBIN_UMBRELLA, _ORBIN_GL_FULL, _ORBIN_GL_SHORT],
    [_ORBIN_GL_SHORT, _ORBIN_UMBRELLA, _ORBIN_GL_FULL],
    [_ORBIN_GL_SHORT, _ORBIN_GL_FULL, _ORBIN_UMBRELLA],
    [_ORBIN_GL_FULL, _ORBIN_UMBRELLA, _ORBIN_GL_SHORT],
    [_ORBIN_GL_FULL, _ORBIN_GL_SHORT, _ORBIN_UMBRELLA],
])
def test_orbin_umbrella_never_fills_gl_limits_in_any_document_order(order):
    """The real policy is $1,000,000 each occurrence / $2,000,000 aggregate. The
    $3,000,000 is a Commercial Liability Umbrella. No ordering of the three
    composite candidates may put $3,000,000 on a GL field."""
    got = _orbin(order)
    for field, expect in (("gl_each_occurrence", 1000000.0),
                          ("gl_aggregate", 2000000.0),
                          ("gl_personal_advertising_injury", 1000000.0)):
        amts = ex._money_amounts(got[field])
        assert amts == {expect}, (
            f"{field} = {got[field]!r} (expected ${expect:,.0f}). The umbrella "
            f"figure is back on a General Liability field - C23 has regressed."
        )


def test_the_richest_gl_breakdown_wins_the_composite():
    """`_score_composite_candidate` must prefer the composite that explains the
    scalar family AND enumerates the most distinct limits. An umbrella block
    repeats one number; a real GL block lists several."""
    got = _orbin([_ORBIN_UMBRELLA, _ORBIN_GL_SHORT, _ORBIN_GL_FULL])
    assert got["gl_limits"] == _ORBIN_GL_FULL


def test_composite_scoring_prefers_explained_over_raw_amount_count():
    """`explained` is ordered first on purpose: a long endorsement paragraph that
    happens to list many dollar figures must not outrank a composite that actually
    accounts for the scalar limits."""
    kids = {"gl_each_occurrence": {"$1,000,000": 1}, "gl_aggregate": {"$2,000,000": 1}}
    real = ex._score_composite_candidate("each occurrence $1,000,000; aggregate $2,000,000", kids)
    noise = ex._score_composite_candidate(
        "fees of $10, $20, $30, $40, $50, $60, $70 may apply", kids)
    assert real > noise, f"noise {noise} outranked the real composite {real}"


def test_composite_scoring_ignores_a_candidate_with_no_money():
    assert ex._score_composite_candidate("see schedule", {"gl_aggregate": {"$1": 1}}) == (0, 0)
