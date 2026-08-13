"""THE large-document root cause: the cross-chunk merge votes by FREQUENCY, so
the declarations page - which states each figure exactly ONCE - is structurally
outvoted by policy boilerplate that mentions a rival figure on many pages.

Measured against the real scoring function before this fix:

    RIGHT value, declarations page, 1 chunk,  ai_high :  1.543
    WRONG value, boilerplate,       2 chunks, ai_low  :  1.599   <- wins
    WRONG value, boilerplate,      16 chunks, ai_low  :  3.333   <- wins

i.e. a wrong value needs only TWO mentions to beat the right one stated once.
On a single-chunk document every candidate has freq==1, the frequency term is a
constant, and confidence decides correctly - which is exactly why small
documents come out right and large packages do not.

These tests drive the REAL `_merge_list_fields` / `_score_value`. A test that
reimplements the scoring only proves the copy is self-consistent (see C23 round
one, which failed the build for a comment reword).
"""

import pytest

from services import extraction_service as ex


# ── Document-shaped fixtures ────────────────────────────────────────────────
# Structural, not vocabulary: a declarations page is TABULAR (short lines, dense
# currency), a policy form is PROSE (long lines, almost no currency). Nothing
# here names a carrier, a client or a form.

_DECLARATIONS = """\
COMMON POLICY DECLARATIONS
Policy Number: 6E7-40-02---26
Effective Date: 07/15/2025    Expiration Date: 07/15/2026
Commercial General Liability Coverage Part        $ 3,954.00
Commercial Auto Coverage Part                     $ 2,991.00
Commercial Inland Marine Coverage Part            $   300.00
Commercial Umbrella Coverage Part                 $ 3,418.00
TOTAL POLICY PREMIUM                              $10,663.00
"""

_BOILERPLATE = """\
SECTION IV - COMMERCIAL GENERAL LIABILITY CONDITIONS
Bankruptcy or insolvency of the insured or of the insured's estate will not
relieve us of our obligations under this Coverage Part. No person or
organization has a right under this Coverage Part to sue us on this Coverage
Part unless all of its terms have been fully complied with. We will pay those
sums that the insured becomes legally obligated to pay as damages because of
bodily injury or property damage to which this insurance applies, and our
payment for loss of or damage to personal property of others will only be for
the account of the owner of the property as described in this Coverage Part.
"""


def _partial(idx, value, confidence, text, field="total_policy_premium"):
    """One chunk's extraction result, in the exact shape `_gather_chunks_async`
    builds and `_merge_list_fields` consumes."""
    return {
        "facts": {field: {"value": value, "confidence": confidence}},
        "flags": {},
        "_chunk_idx": idx,
        "_char_start": idx * 56_000,
        "_char_end": (idx + 1) * 56_000,
        "_authority": ex.declarations_authority(text),
    }


def _merge(partials, field="total_policy_premium"):
    """The winning VALUE. `_merge_list_fields` stores the annotated record
    (`merged_facts[field] = winner_c["record"]`), so unwrap it the way every
    production reader does."""
    v = ex._merge_list_fields(partials, [])["facts"].get(field)
    return v["value"] if isinstance(v, dict) and "value" in v else v


# ── The root cause ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("n_boilerplate", [2, 5, 16])
def test_declarations_value_beats_repeated_boilerplate(n_boilerplate):
    """The whole bug in one assertion: one authoritative statement must beat any
    number of boilerplate repetitions."""
    partials = [_partial(0, "$10,663", "ai_high", _DECLARATIONS)]
    partials += [
        _partial(i, "$2,991", "ai_low", _BOILERPLATE)
        for i in range(1, n_boilerplate + 1)
    ]
    assert _merge(partials) == "$10,663", (
        f"{n_boilerplate} boilerplate mentions outvoted the declarations page"
    )


def test_the_same_bug_on_an_identity_fact():
    """Not premium-specific. A producer contact named once on the dec page is
    the same shape of candidate as a premium."""
    partials = [_partial(0, "Erin Royal", "ai_high", _DECLARATIONS,
                         field="producer_contact_name")]
    partials += [
        _partial(i, "Claim Reporting", "ai_low", _BOILERPLATE,
                 field="producer_contact_name")
        for i in range(1, 6)
    ]
    assert _merge(partials, "producer_contact_name") == "Erin Royal"


# ── Fail-open: nothing may change when authority cannot discriminate ────────

def test_flat_authority_reproduces_frequency_ranking_exactly():
    """When every chunk looks the same - a loss run, a narrative, one long form -
    authority carries no information and the old behaviour must survive intact,
    frequency included."""
    partials = [_partial(0, "$10,663", "ai_high", _BOILERPLATE)]
    partials += [_partial(i, "$2,991", "ai_low", _BOILERPLATE) for i in range(1, 6)]
    assert _merge(partials) == "$2,991", (
        "with no authority signal the merge must fall back to today's ranking"
    )


def test_single_chunk_document_is_untouched():
    """One partial short-circuits before scoring. Small documents cannot regress."""
    p = _partial(0, "$10,663", "ai_high", _DECLARATIONS)
    assert _merge([p]) == "$10,663"


def test_partials_without_an_authority_key_still_merge():
    """Every caller must survive the field being absent - old sessions, replayed
    fixtures, and the reconciliation path all build partials by hand."""
    partials = [
        {"facts": {"total_policy_premium": {"value": "$10,663", "confidence": "ai_high"}},
         "flags": {}, "_chunk_idx": 0},
        {"facts": {"total_policy_premium": {"value": "$2,991", "confidence": "ai_low"}},
         "flags": {}, "_chunk_idx": 1},
        {"facts": {"total_policy_premium": {"value": "$2,991", "confidence": "ai_low"}},
         "flags": {}, "_chunk_idx": 2},
    ]
    assert _merge(partials) == "$2,991", "missing authority must not crash or reorder"


# ── Narrative carve-out: the fix must not entrench the truncation defect ────

_TRUNCATED = "COMMERCIAL GENERAL CONTRA"
_FULL_NARRATIVE = (
    "Contractors - subcontracted work in connection with construction, "
    "reconstruction, repair or erection of buildings, including carpentry, "
    "roofing and interior finishing performed at the job site by subcontractors "
    "under written agreement."
)


def test_a_tabular_fragment_never_outranks_a_prose_narrative():
    """A dec page prints a truncated shorthand; the real description is out in
    the prose. Source authority says the dec page wins - which for a NARRATIVE
    is precisely backwards, and would have made this fix entrench the reported
    'COMMERCIAL GENERAL CONTRA' defect. Narrative facts opt out."""
    partials = [
        _partial(0, _TRUNCATED, "ai_high", _DECLARATIONS, field="operations_description"),
        _partial(1, _FULL_NARRATIVE, "ai_high", _BOILERPLATE, field="operations_description"),
        _partial(2, _FULL_NARRATIVE, "ai_high", _BOILERPLATE, field="operations_description"),
    ]
    assert _merge(partials, "operations_description") == _FULL_NARRATIVE


def test_prose_detection_does_not_catch_an_ordinary_atomic_value():
    """The carve-out must not swallow normal facts - a full mailing address is
    the longest atomic value a declarations page prints."""
    for atomic in (
        "4800 Dahlia St # D13, Denver, CO 80216-3121",
        "Employers Mutual Casualty Company",
        "$10,663.00",
        "6E7-40-02---26",
    ):
        assert not ex._is_prose_value(atomic), atomic
    assert ex._is_prose_value(_FULL_NARRATIVE)


def test_every_registry_narrative_fact_is_recognised_from_a_realistic_value():
    """Anti-rot: the carve-out is derived from the VALUE, so it must hold for a
    realistic narrative on every fact the registry treats as free text. Fails
    the build if the thresholds drift away from real narrative lengths."""
    import re
    from services.fact_registry import FACT_REGISTRY
    pat = re.compile(r"(description|narrative|remarks|explanation|discussion)")
    narrative_keys = [k for k in FACT_REGISTRY if pat.search(k)]
    assert narrative_keys, "harvest found nothing - the check would pass vacuously"
    for key in narrative_keys:
        partials = [
            _partial(0, _TRUNCATED, "ai_high", _DECLARATIONS, field=key),
            _partial(1, _FULL_NARRATIVE, "ai_low", _BOILERPLATE, field=key),
            _partial(2, _FULL_NARRATIVE, "ai_low", _BOILERPLATE, field=key),
        ]
        assert _merge(partials, key) == _FULL_NARRATIVE, key


# ── The authority signal itself ─────────────────────────────────────────────

def test_a_declarations_block_scores_above_policy_prose():
    assert ex.declarations_authority(_DECLARATIONS) > ex.declarations_authority(_BOILERPLATE)


def test_authority_is_bounded():
    for text in (_DECLARATIONS, _BOILERPLATE, "", "   ", "x" * 5000):
        assert 0.0 <= ex.declarations_authority(text) <= 1.0


def test_authority_needs_no_insurance_vocabulary():
    """Structural, not keyword-driven: a tabular money block from an unrelated
    trade must still outrank prose, or the rule is a vocabulary list in disguise
    and will not hold across the 17 forms."""
    tabular = (
        "SCHEDULE OF EQUIPMENT\n"
        "Excavator 320D        $ 84,500.00\n"
        "Skid Steer S650       $ 41,200.00\n"
        "Compactor CS44        $ 22,750.00\n"
        "TOTAL                 $148,450.00\n"
    )
    assert ex.declarations_authority(tabular) > ex.declarations_authority(_BOILERPLATE)


# ── Coverage cannot fall ────────────────────────────────────────────────────

def _merge_all(partials):
    return ex._merge_list_fields(partials, [])["facts"]


def test_authority_only_reorders_it_never_drops_a_fact():
    """THE standing constraint on this project: a change may not reduce how many
    fields come out filled. Authority ranks candidates that already exist, so
    the merged KEY SET must be byte-identical with the term on and off. Proven
    over randomised partials, not one hand-picked case."""
    import random
    rng = random.Random(20260812)
    fields = ["total_policy_premium", "applicant_name", "effective_date",
              "carrier_name", "gl_each_occurrence", "producer_contact_name"]
    for trial in range(200):
        partials = []
        for idx in range(rng.randint(2, 8)):
            text = _DECLARATIONS if rng.random() < 0.4 else _BOILERPLATE
            facts = {
                f: {"value": rng.choice(["A-1", "B-2", "C-3"]),
                    "confidence": rng.choice(["ai_high", "ai_low"])}
                for f in fields if rng.random() < 0.7
            }
            p = _partial(idx, "x", "ai_low", text)
            p["facts"] = facts
            partials.append(p)

        with_authority = set(_merge_all(partials))
        for p in partials:
            p.pop("_authority", None)
        without_authority = set(_merge_all(partials))

        assert with_authority == without_authority, (
            f"trial {trial}: authority changed WHICH facts survive, not just their order\n"
            f"  lost: {without_authority - with_authority}\n"
            f"  gained: {with_authority - without_authority}"
        )


def test_within_one_tier_the_ranking_is_the_old_arithmetic_exactly():
    """The safety argument for the quantised tier, asserted rather than claimed:
    for two candidates of equal authority the score DIFFERENCE must equal the
    pre-change formula's difference, so ordering cannot drift."""
    import math
    rec_hi = {"value": "x", "confidence": "ai_high"}
    rec_lo = {"value": "y", "confidence": "ai_low"}
    for auth in (None, 0.0, 0.3, 0.9):
        for f_hi, f_lo in ((1, 5), (3, 3), (7, 2)):
            new = (ex._score_value("effective_date", rec_hi, f_hi, auth)
                   - ex._score_value("effective_date", rec_lo, f_lo, auth))
            tier = ex._TIER_WEIGHTS[ex._get_field_tier("effective_date")]
            old = tier * ((math.log1p(f_hi) + 0.85) - (math.log1p(f_lo) + 0.50))
            assert abs(new - old) < 1e-9, f"auth={auth} freqs=({f_hi},{f_lo})"


def test_authority_gain_dominates_the_widest_possible_base_spread():
    """The tier separation must survive a pathological chunk count, or a heavily
    repeated boilerplate value could climb back over a declarations value."""
    import math
    widest_base = math.log1p(200) + 1.0          # 200 chunks, max confidence
    assert ex._AUTHORITY_GAIN > widest_base, (
        f"gain {ex._AUTHORITY_GAIN} does not dominate a base spread of {widest_base:.2f}"
    )


# ── Realistic scale: the signal must survive a real 56,000-char chunk ───────

def _pad(s, n):
    return (s * (n // len(s) + 1))[:n]


_CHUNK = 56_000          # what _effective_chunk_size() actually returns


@pytest.mark.parametrize("dec_chars", [28_000, 14_000, 8_000, 4_000])
def test_a_dec_page_diluted_inside_a_real_chunk_still_outranks_boilerplate(dec_chars):
    """The failure mode that nearly shipped. Scoring the chunk MEAN, a genuine
    declarations page at 14% of its 56,000-char chunk scored 0.174 against pure
    prose at 0.061 - both tier 0, signal gone, fix inert on exactly the
    documents it exists for. The windowed max has to hold at every dilution."""
    dec_chunk = _pad(_DECLARATIONS, dec_chars) + _pad(_BOILERPLATE, _CHUNK - dec_chars)
    prose_chunk = _pad(_BOILERPLATE, _CHUNK)
    assert ex._authority_tier(ex.declarations_authority(dec_chunk)) > \
           ex._authority_tier(ex.declarations_authority(prose_chunk))


def test_end_to_end_on_a_seventeen_chunk_package():
    """The reported shape: one declarations chunk, sixteen chunks of forms. The
    right figure is stated once and must survive being outnumbered 16 to 1."""
    partials = [
        _partial(0, "$10,663", "ai_high",
                 _pad(_DECLARATIONS, 8_000) + _pad(_BOILERPLATE, _CHUNK - 8_000)),
    ]
    partials += [
        _partial(i, "$2,991", "ai_low", _pad(_BOILERPLATE, _CHUNK))
        for i in range(1, 17)
    ]
    assert _merge(partials) == "$10,663"


def test_authority_is_cheap_enough_to_run_on_every_chunk():
    """It runs 17+ times per document on the extraction hot path. If this ever
    becomes expensive the windowing is wrong."""
    import time
    text = _pad(_BOILERPLATE, _CHUNK)
    t0 = time.perf_counter()
    for _ in range(17):
        ex.declarations_authority(text)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert elapsed_ms < 1000, f"{elapsed_ms:.0f} ms for one document is too slow"


def test_no_module_level_regex_name_is_defined_twice():
    """Found the hard way. A new `_MONEY_TOKEN_RE` here silently shadowed the
    CAPTURING one `_money_amounts` parses with float(); findall() began
    returning whole matches and all 12 C23 currency tiebreak tests went red.
    A counting pattern and a parsing pattern must never share a name."""
    import ast
    import inspect
    from collections import Counter

    tree = ast.parse(inspect.getsource(ex))
    names = []
    for node in tree.body:                       # module level only
        if not isinstance(node, ast.Assign):
            continue
        val = node.value
        if not (isinstance(val, ast.Call) and isinstance(val.func, ast.Attribute)
                and val.func.attr == "compile"):
            continue
        names += [t.id for t in node.targets if isinstance(t, ast.Name)]

    assert names, "harvest found no compiled patterns - the check would pass vacuously"
    dupes = {n: c for n, c in Counter(names).items() if c > 1}
    assert not dupes, f"module-level regex names defined more than once: {dupes}"


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
