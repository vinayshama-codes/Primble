"""An unrecognised coverage part reaches the producer (client 1.7, C1-Q).

The client's rule has two halves:

    "If terminology is not covered by a known normalization rule, do not
     automatically assume equivalence. Leave it unmapped OR ROUTE IT FOR
     PRODUCER REVIEW WHEN MATERIAL."

Only the first half was built. `canon_line` returns None and every call site
skips it, so a coverage part Primble could not place was silently invisible -
never compared, never scored, never asked about, and nobody told.

MATERIAL is the load-bearing word and it is answered with positive evidence
only: a premium or a limit on the entry, the same test `denied_families` uses
to withdraw a denial (D26 - silence is not evidence). Without that gate every
ordinary certificate, whose rows carry no premium, would raise a review item.
"""
import pytest

from services.lob_canon import unmapped_material_lines, canon_line


def _row(line, **kw):
    return dict(line=line, **kw)


# ── 1. It fires on a real unrecognised, carried line ─────────────────────────

def test_a_carried_unrecognised_line_is_surfaced():
    rows = [_row("Kidnap and Ransom", limit="$500,000")]
    assert unmapped_material_lines(rows) == ["Kidnap and Ransom"]


def test_a_premium_counts_as_carried_too():
    rows = [_row("Widget Protection Coverage", premium="$1,200")]
    assert unmapped_material_lines(rows) == ["Widget Protection Coverage"]


def test_the_original_printing_is_returned_not_a_normalised_key():
    """The producer has to recognise the phrase their own document used."""
    rows = [_row("Kidnap & Ransom - Worldwide", limit="$500,000")]
    assert unmapped_material_lines(rows) == ["Kidnap & Ransom - Worldwide"]


def test_several_unrecognised_lines_all_surface_in_order():
    rows = [_row("Widget Protection", premium="$1,200"),
            _row("Gadget Protection", premium="$900")]
    assert unmapped_material_lines(rows) == ["Widget Protection", "Gadget Protection"]


# ── 2. It stays silent on everything else ────────────────────────────────────

def test_every_known_family_is_silent():
    """If this ever fires on a standard line, `canon_line` regressed."""
    known = ["Commercial General Liability", "Liability", "Commercial Auto",
             "Automobile", "Commercial Liability Umbrella", "Umbrella",
             "Workers Compensation", "Commercial Property",
             "Commercial Inland Marine", "Contractors Equipment",
             "Installation Floater", "Computer Coverage", "Crime and Fidelity",
             "Cyber Liability", "Professional Liability"]
    rows = [_row(n, premium="$1,000") for n in known]
    assert unmapped_material_lines(rows) == [], (
        "a standard line of business was reported as unrecognised")


def test_an_unrecognised_line_that_is_NOT_carried_stays_silent():
    """A certificate row, a placeholder, a section header. D26: silence is not
    evidence, and this is the gate that stops a review item on every COI."""
    assert unmapped_material_lines([_row("Widget Protection Coverage")]) == []
    assert unmapped_material_lines([_row("Widget Protection", premium="-")]) == []
    assert unmapped_material_lines([_row("Widget Protection", limit="")]) == []


def test_a_declined_unrecognised_line_stays_silent():
    """`NO COVERAGE` is positive evidence of ABSENCE - the opposite of material."""
    assert unmapped_material_lines(
        [_row("Widget Protection", premium="NO COVERAGE")]) == []


def test_a_blank_line_name_is_not_a_coverage_part():
    assert unmapped_material_lines([_row("", premium="$100")]) == []
    assert unmapped_material_lines([_row("   ", premium="$100")]) == []


# ── 3. Edge cases - it must never raise ──────────────────────────────────────

@pytest.mark.parametrize("bad", [None, "not a list", 42, {}, [None, 42, "x"]])
def test_unreadable_input_returns_empty_never_raises(bad):
    assert unmapped_material_lines(bad) == []


def test_non_dict_rows_are_skipped_and_the_real_one_still_found():
    rows = [None, 42, "text", _row("Kidnap and Ransom", limit="$500,000")]
    assert unmapped_material_lines(rows) == ["Kidnap and Ransom"]


def test_the_same_line_printed_twice_is_reported_once():
    """One coverage part listed twice must not look like two problems.
    '&' vs 'and' is the case that slipped the first cut."""
    rows = [_row("Kidnap & Ransom", limit="$500,000"),
            _row("kidnap and ransom", limit="$500,000")]
    assert unmapped_material_lines(rows) == ["Kidnap & Ransom"]


def test_two_genuinely_different_unknown_lines_are_not_folded():
    rows = [_row("Widget Protection", premium="$1"),
            _row("Gadget Protection", premium="$2")]
    assert len(unmapped_material_lines(rows)) == 2


# ── 4. The advisory never moves a score (Principle 7) ────────────────────────

def test_the_pipeline_emits_it_as_advisory_and_touches_no_stop_array():
    """We do not know what the line IS, so we cannot know what it should cost.
    'Give it no new scoring effect until a rule is explicitly defined.'

    Read out of the source rather than driven through the whole pipeline: the
    property under test is that the emission site appends to structured_issues
    ONLY. A test that ran the pipeline would prove today's wiring, not the rule.
    """
    import os
    src = open(os.path.join(os.path.dirname(__file__), "..", "services",
                            "extraction_pipeline.py"), encoding="utf-8").read()
    start = src.index("unmapped_coverage_line")
    block = src[max(0, start - 1500):start + 800]
    assert '"advisory"' in block, "the unmapped-line issue must be advisory"
    emit = src[src.index("from services.lob_canon import unmapped_material_lines"):
               start + 800]
    for forbidden in ("hard_stops = ", "soft_stops = "):
        assert forbidden not in emit, (
            f"the unmapped-line block writes {forbidden.strip()} - an advisory "
            "must not cap or deduct the score")


def test_canon_line_still_returns_none_for_the_unknown_case():
    """The other half of 1.7, pinned here so a future 'fix' cannot make this
    feature disappear by force-mapping unknown terminology instead."""
    assert canon_line("Widget Protection Coverage") is None
    assert canon_line("Kidnap and Ransom") is None
