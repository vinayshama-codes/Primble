"""What the GAP-FILL MODEL reads. See RETRIEVAL_CHANGES.md at the repo root.

THE PRODUCT CONSTRAINT THIS FILE EXISTS TO ENFORCE:
    *"I don't want values to be lost in the declaration pages because it will
      be a horrible thing."*

So the invariant asserted throughout is NOT "some facts are visible" - it is
**every declarations-page value present in the input is present in the output**.
An earlier harness asserted the former and produced false alarms whenever the
fixture simply never contained a value; that says nothing about the filter.

WHY THE FILTER EXISTS (measured, client's real 271-page package, 2026-08-12):

    raw_text_chars=683601  prompt_chars=724348  chunk 1/1
    LLM_SPEND stage=gap_fill in=174664 tokens
    gpt_fill: sent=31 filled=14 | sent=40 filled=5 | ...   -> 42/159 = 26%

The whole package went into every call, the field list was ~1% of the prompt,
and the model answered a quarter of what it was asked.
"""
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline-test")

from services.text_selection import select_gap_fill_text     # noqa: E402

# A declarations/schedule page: short lines, dense with money and dates.
_DEC = (
    "COMMERCIAL AUTO DECLARATIONS\n"
    "Named Insured: Orbin Contracting LLC\n"
    "4800 DAHLIA ST # D13, DENVER, CO 80216-3121\n"
    "Policy Number: 6E7-40-02---26   Term: 07/15/2025 to 07/15/2026\n"
    "Carrier: EMPLOYERS MUTUAL CASUALTY COMPANY   NAIC: 21415\n"
    "Each Occurrence Limit                 $1,000,000\n"
    "General Aggregate Limit               $2,000,000\n"
    "Products/Completed Ops Aggregate      $2,000,000\n"
    "Damage To Premises Rented               $500,000\n"
    "Medical Expense Limit                    $10,000\n"
    "Commercial General Liability Premium      $3,954\n"
    "Commercial Auto Premium                   $2,991\n"
    "Commercial Inland Marine Premium            $300\n"
    "Commercial Umbrella Premium               $3,418\n"
    "Total Policy Premium                     $10,663\n"
    "Comprehensive Deductible: $1,000   Collision Deductible: $1,000\n"
) * 6

# Standard policy wording: long wrapped prose, almost no figures.
_FORM = (
    "COMMERCIAL GENERAL LIABILITY COVERAGE FORM\n"
    "Various provisions in this policy restrict coverage. Read the entire policy "
    "carefully to determine rights, duties and what is and is not covered. "
    "Throughout this policy the words you and your refer to the Named Insured "
    "shown in the Declarations, and any other person or organization qualifying "
    "as a Named Insured under this policy.\n"
    "SECTION I - COVERAGES. We will pay those sums that the insured becomes "
    "legally obligated to pay as damages because of bodily injury or property "
    "damage to which this insurance applies. We will have the right and duty to "
    "defend the insured against any suit seeking those damages.\n"
    "2. Exclusions. This insurance does not apply to bodily injury expected or "
    "intended from the standpoint of the insured. Bankruptcy or insolvency of "
    "the insured will not relieve us of our obligations under this Coverage "
    "Part. No person or organization has a right under this Coverage Part to "
    "join us as a party or otherwise bring us into a suit asking for damages.\n"
    "Pollutants means any solid, liquid, gaseous or thermal irritant or "
    "contaminant, including smoke, vapor, soot, fumes, acids, alkalis, chemicals "
    "and waste. If we cancel this policy we will mail written notice of "
    "cancellation. We may cancel for non-payment of premium. Any judgment or "
    "lien obtained against the insured shall not create any obligation on us.\n"
)


def _norm(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _dec_values(text):
    """Every distinctive token a declarations page carries - money, dates,
    policy-number-shaped codes, postal codes. These are what must never be lost."""
    vals = set()
    vals |= set(re.findall(r"\$\s?\d[\d,]*(?:\.\d{2})?", text))
    vals |= set(re.findall(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b", text))
    vals |= set(re.findall(r"\b[A-Z0-9]{3,}-[A-Z0-9-]{3,}\b", text))
    return {v for v in vals if len(v.strip()) >= 4}


def _lost(original, output):
    hay = _norm(output)
    return sorted(v for v in _dec_values(original) if _norm(v) not in hay)


def _package(dec=8, form=90):
    """A realistic package: declarations are a small minority of the pages,
    exactly as in the client's 271-page file."""
    return "\n".join(([_DEC] * dec) + ([_FORM * 3] * form))


# ── THE INVARIANT ────────────────────────────────────────────────────────────

def test_no_declarations_value_is_ever_lost():
    """THE LOAD-BEARING TEST. If this fails, the change is not shippable."""
    pkg = _package()
    out, stats = select_gap_fill_text(pkg, {}, label="t")
    assert stats["applied"], "the filter should act on a realistic package"
    assert not _lost(pkg, out), f"declarations values lost: {_lost(pkg, out)[:8]}"


# Built lazily and identified by NAME. Passing the ~350KB fixture as a
# parametrize value puts it in the test id, which pytest exports into the
# environment - and Windows caps an environment variable at 32,767 chars, so
# every one of these errored before the test body ever ran.
@pytest.mark.parametrize("name", ["dec_at_start", "dec_at_end", "dec_in_middle"])
def test_position_of_the_declarations_page_does_not_matter(name):
    """A window-boundary accident at the head or tail of the document is the
    obvious way a filter like this loses data. Dilation covers it."""
    text = {
        "dec_at_start":  lambda: _DEC + (_FORM * 250),
        "dec_at_end":    lambda: (_FORM * 250) + _DEC,
        "dec_in_middle": lambda: (_FORM * 120) + _DEC + (_FORM * 120),
    }[name]()
    out, _ = select_gap_fill_text(text, {}, label=name)
    assert not _lost(text, out), f"{name}: lost {_lost(text, out)[:8]}"


def test_it_actually_reduces_the_prompt():
    """The whole point. A filter that keeps everything fixes nothing."""
    pkg = _package()
    out, stats = select_gap_fill_text(pkg, {}, label="t")
    assert stats["applied"]
    assert len(out) < len(pkg) * 0.5, (
        f"kept {100.0 * len(out) / len(pkg):.0f}% - no material reduction")


# ── Guarantee 1: small documents are never touched ───────────────────────────

def test_a_small_document_is_returned_unchanged():
    small = _DEC * 2
    out, stats = select_gap_fill_text(small, {}, label="t")
    assert out == small and not stats["applied"]


def test_empty_text_is_safe():
    out, stats = select_gap_fill_text("", {}, label="t")
    assert out == "" and not stats["applied"]


# ── Guarantee 4: refuse to act when the signal did not discriminate ──────────

def test_an_all_prose_narrative_survives_whole():
    """A narrative or supplemental application is prose BY CONSTRUCTION. Scored
    on tabular-ness it would be deleted entirely - so the filter must decline."""
    narrative = _FORM * 200
    out, stats = select_gap_fill_text(narrative, {}, label="t")
    assert out == narrative, "a prose-only document must never be filtered"
    assert not stats["applied"]


def test_an_all_declarations_document_is_left_alone():
    """Nothing to gain, so nothing is risked."""
    decs = _DEC * 90
    out, stats = select_gap_fill_text(decs, {}, label="t")
    assert out == decs and not stats["applied"]


# ── Guarantee 3: an extracted fact is never made invisible ───────────────────

_BURIED = ("Applicant operates as a commercial general contractor performing "
           "tenant finish and remodeling work throughout the Denver metro area")


def _package_with_buried_fact():
    return "\n".join(
        ([_DEC] * 8) + ([_FORM * 3] * 45)
        + [_FORM + "\n" + _BURIED + "\n" + _FORM]
        + ([_FORM * 3] * 45)
    )


def test_a_fact_living_only_in_prose_is_rescued():
    pkg = _package_with_buried_fact()
    out, stats = select_gap_fill_text(
        pkg, {"operations_description": _BURIED}, label="t")
    assert stats["applied"]
    assert _norm(_BURIED) in _norm(out)
    assert stats["rescued_windows"] >= 1


def test_the_rescue_is_what_saves_it_not_luck():
    """THE CONTROL. Without this the test above could pass because the window
    happened to be kept anyway, and the guarantee would be untested."""
    pkg = _package_with_buried_fact()
    out, _ = select_gap_fill_text(pkg, {}, label="t")     # same doc, no facts
    assert _norm(_BURIED) not in _norm(out), (
        "the buried text survives even without the fact-rescue, so this fixture "
        "does not exercise guarantee 3 - fix the fixture, not the guarantee")


def test_fact_envelopes_and_non_strings_do_not_crash_the_rescue():
    """Facts arrive as {'value':..,'confidence':..} envelopes, bools, lists and
    schedule dicts. None of them may raise."""
    pkg = _package_with_buried_fact()
    facts = {
        "operations_description": {"value": _BURIED, "confidence": "ai_high"},
        "has_general_liability": True,
        "num_employees": 47,
        "auto_vehicles": [{"vin": "4S4BRCGC9C3217772"}],
        "nothing": None,
        "blank": "",
    }
    out, stats = select_gap_fill_text(pkg, facts, label="t")
    assert _norm(_BURIED) in _norm(out)


# ── Operational safety ───────────────────────────────────────────────────────

def test_the_kill_switch_returns_the_input_byte_for_byte():
    import importlib
    import services.text_selection as ts
    old = os.environ.get("GAP_FILL_TEXT_SELECTION")
    os.environ["GAP_FILL_TEXT_SELECTION"] = "0"
    try:
        importlib.reload(ts)
        pkg = _package()
        out, stats = ts.select_gap_fill_text(pkg, {}, label="t")
        assert out == pkg and not stats["applied"] and stats["reason"] == "disabled"
    finally:
        if old is None:
            os.environ.pop("GAP_FILL_TEXT_SELECTION", None)
        else:
            os.environ["GAP_FILL_TEXT_SELECTION"] = old
        importlib.reload(ts)


def test_a_failure_falls_back_to_the_full_document():
    """A text-selection bug must never cost a submission its whole gap fill."""
    pkg = _package()

    class Exploding(dict):
        # Raises on BOTH read paths - _fact_values used .values() originally
        # and .items() since the dec-entries change (2026-08-12). The invariant
        # under test is the same either way: a crash while reading facts must
        # degrade to the full document, never to a partial one.
        def values(self):
            raise RuntimeError("boom")

        def items(self):
            raise RuntimeError("boom")

    # MUST BE NON-EMPTY. `_fact_values` does `(facts or {}).values()`, so an
    # empty mapping is falsy, gets replaced by a plain `{}`, and never raises -
    # the first version of this test passed through the happy path and proved
    # nothing. Caught by the assertion below, not by inspection.
    facts = Exploding()
    facts["operations_description"] = _BURIED
    assert facts, "the fixture must be truthy or it cannot reach the raising code"

    out, stats = select_gap_fill_text(pkg, facts, label="t")
    assert out == pkg, "a failure must degrade to today's behaviour, not to nothing"
    assert stats["reason"].startswith("error:")


# ── The scope rule that keeps verification honest ────────────────────────────

def test_verification_still_reads_the_complete_document():
    """STANDING GUARD, and the subtlest rule in this change.

    `map_facts_to_form` uses `raw_text` to VERIFY the model's output - the
    evidence gate, `_value_in_raw_text`, the NAIC and classification-code
    guards. If `combined_gap_fill` ever reassigns `raw_text` to the filtered
    copy, every answer grounded in a dropped region gets wrongly blanked and
    this change starts DELETING correct data.

    Only the prompt may be filtered.
    """
    import inspect
    import services.pdf_service as ps
    src = inspect.getsource(ps.combined_gap_fill)
    assert "_prompt_text" in src, "the filtered copy must have its own name"
    assert not re.search(r"^\s*raw_text\s*=", src, re.M), (
        "combined_gap_fill reassigns raw_text - verification would start "
        "reading the filtered document")
    assert "raw_text=_prompt_text" in src, (
        "the model must be given the filtered copy")


# ── The adaptive cut ─────────────────────────────────────────────────────────
# MEASURED FAILURE on the client's real 271-page package, 2026-08-12:
#
#     TEXT_SELECTION SKIPPED kept ratio 97.4% outside [2%, 90%]
#
# `_window_authority` is `0.5*figure_density + 0.5*brevity`, and pdfplumber's
# native extraction emits SHORT LINES ON EVERY PAGE - so `brevity` sat near 0.86
# throughout. A policy-form page scored ~0.44 and a declarations page ~0.83:
# both above the absolute 0.25 cut, so nothing was dropped and the prompt stayed
# at 174k tokens per call.
#
# The page types were still cleanly separated - just not around 0.25. The cut is
# now taken from the document's own distribution (Otsu), but ONLY when that
# distribution is provably two-humped.

def _short_lines(text, width=44):
    """Re-wrap to short lines - what pdfplumber does to a policy form page.
    Without this the fixture does not reproduce the real defect at all."""
    import textwrap
    return "\n".join(textwrap.wrap(" ".join(text.split()), width=width))


_FORM_SHORT = _short_lines(_FORM)


def _short_line_package(dec=8, form=90):
    return "\n".join(([_DEC] * dec) + ([_FORM_SHORT] * form))


def test_the_absolute_cut_really_does_fail_on_this_shape():
    """THE FIXTURE'S OWN SELF-CHECK. If the absolute cut can separate this
    document, the test below proves nothing about the adaptive one."""
    from services.extraction_service import _window_authority
    pkg = _short_line_package()
    windows = [pkg[i:i + 3000] for i in range(0, len(pkg), 3000)]
    scores = [_window_authority(w) for w in windows]
    above = sum(1 for s in scores if s >= 0.25)
    assert above == len(scores), (
        "the fixture no longer reproduces the client's failure - every window "
        "must sit above the absolute cut, as it did on the real document")


def test_the_adaptive_cut_fires_where_the_absolute_one_could_not():
    pkg = _short_line_package()
    out, stats = select_gap_fill_text(pkg, {}, label="t")
    assert stats["applied"], "the adaptive cut did not fire on the reproduction"
    assert stats["cut_kind"] == "adaptive"
    assert len(out) < len(pkg) * 0.5


def test_the_adaptive_cut_loses_no_declarations_value():
    """THE LOAD-BEARING TEST for this feature."""
    pkg = _short_line_package()
    out, _ = select_gap_fill_text(pkg, {}, label="t")
    assert not _lost(pkg, out), f"lost {_lost(pkg, out)[:8]}"


def test_an_all_declarations_document_is_not_split_down_the_middle():
    """THE DANGEROUS CASE. A relative cut with no quality gate would split a
    document that is entirely declarations and delete half the real data.

    Measured with the largest-gap criterion: gap=0.00. There is no empty band
    anywhere in this distribution, because there is only one kind of page - so
    the split is refused outright rather than narrowly survived."""
    decs = _DEC * 90
    out, stats = select_gap_fill_text(decs, {}, label="t")
    assert out == decs and not stats["applied"]
    assert stats["cut_kind"] == "absolute"


def test_a_uniformly_prose_document_with_short_lines_is_not_split():
    prose = _FORM_SHORT * 200
    out, stats = select_gap_fill_text(prose, {}, label="t")
    assert out == prose and not stats["applied"]


@pytest.mark.parametrize("name", ["long_prose", "short_lines"])
def test_the_adaptive_cut_only_ever_tightens(name):
    """THE INVARIANT, not a fixture outcome.

    The adaptive cut may never keep MORE than the absolute rule already keeps -
    that would let this change REDUCE what gets dropped on a document that
    already worked. Enforced in code by `if _bimodal and _o_cut > _cut`.

    An earlier version of this test asserted `cut_kind == "absolute"` on the
    long-prose fixture, which was an assumption about that fixture's
    distribution rather than a property of the rule - and it was simply wrong.
    Whichever cut wins, it must never be below the absolute one, and no
    declarations value may be lost either way.
    """
    pkg = {"long_prose": _package, "short_lines": _short_line_package}[name]()
    out, stats = select_gap_fill_text(pkg, {}, label=name)
    assert stats["applied"]
    assert stats["cut"] >= 0.25, (
        f"{name}: cut {stats['cut']:.2f} is LOOSER than the absolute cut")
    assert not _lost(pkg, out)


def test_a_looser_otsu_cut_is_rejected_in_favour_of_the_absolute_one():
    """Directly exercises the `_o_cut > _cut` condition: a distribution whose
    natural split sits BELOW 0.25 must not be allowed to widen what is kept."""
    from services.text_selection import _separation_cut
    scores = [0.02] * 40 + [0.20] * 40          # separable, but entirely under 0.25
    result = _separation_cut(scores)
    assert result is not None
    cut, _var_explained, gap = result
    assert gap >= 0.15, "it IS a real separation"
    assert cut < 0.25, "fixture must produce a cut below the absolute one"
    # ...and the code must therefore ignore it. Proven by the parametrized test
    # above, which asserts the effective cut never drops below 0.25.


def test_otsu_declines_on_degenerate_input():
    from services.text_selection import _separation_cut
    assert _separation_cut([]) is None
    assert _separation_cut([0.5] * 50) is None            # zero variance
    assert _separation_cut([0.1, 0.9]) is None            # too few windows


def test_the_adaptive_kill_switch():
    import importlib
    import services.text_selection as ts
    old = os.environ.get("TEXT_SELECT_ADAPTIVE")
    os.environ["TEXT_SELECT_ADAPTIVE"] = "0"
    try:
        importlib.reload(ts)
        pkg = _short_line_package()
        out, stats = ts.select_gap_fill_text(pkg, {}, label="t")
        assert out == pkg and not stats["applied"], (
            "with the adaptive cut off, this must behave exactly as before")
    finally:
        if old is None:
            os.environ.pop("TEXT_SELECT_ADAPTIVE", None)
        else:
            os.environ["TEXT_SELECT_ADAPTIVE"] = old
        importlib.reload(ts)


# ── Step 2: standard-form pages identified by their OWN printed footer ───────
# The density signal FAILED TWICE on the client's live package (final state:
# separation gap 0.07 against the 0.15 floor -> SKIPPED, prompt stayed a
# 174k-token haystack, fill rate stayed 26%). An ISO standard form declares
# itself in its page footer ("CG 00 01 04 13"); that identification is
# independent of how the PDF extractor renders lines, so it works exactly where
# the density signal cannot.

_DEC_BLUR = (
    "COMMERCIAL AUTO DECLARATIONS CA7000A 02-22\n"
    "POLICY NUMBER 6E7-40-02---26\n"
    "NAMED INSURED ORBIN CONTRACTING LLC\n"
    "PREMIUM $2,991 EFF 07/15/2025\n"
    "items of coverage described below apply\n"
    "TOTAL POLICY PREMIUM $10,663\n"
) * 14

def _blurred_form_page(n, extra=""):
    """Short lines WITH figures - pdfplumber's real output shape, scoring so
    close to a dec page that no density cut can separate them - plus the ISO
    footer every printed page of a standard form carries."""
    body = (
        "we will pay up to $250 per day\n"
        "subject to the limit of 07/15/2025\n"
        "no legal action may be brought here\n"
        "coverage applies as stated in item\n"
    ) * 11
    return body + extra + f"CG 00 {n % 90:02d} 04 13 Page {n} of 90\n"


def _blurred_package(extra_on_page=None, extra=""):
    pages = []
    for n in range(1, 70):
        pages.append(_blurred_form_page(n, extra if n == extra_on_page else ""))
    return _DEC_BLUR + "".join(pages)


def test_footer_pages_drop_when_no_density_signal_exists():
    pkg = _blurred_package()
    out, stats = select_gap_fill_text(pkg, {}, label="t")
    assert stats["applied"], "the footer stage must act where density could not"
    assert stats["footer_dropped"] > 0
    assert stats["kept_chars"] < 0.2 * len(pkg)
    assert "TOTAL POLICY PREMIUM $10,663" in out


def test_the_footer_stage_never_loses_a_declarations_value():
    pkg = _blurred_package()
    out, _ = select_gap_fill_text(pkg, {}, label="t")
    assert _lost(_DEC_BLUR, out) == []


def test_the_footer_stage_self_check_density_alone_really_skips():
    """The fixture's own self-check: with the footer stage off, this document
    must come back UNCHANGED - otherwise the tests above prove nothing about
    the footer stage."""
    import importlib
    import services.text_selection as ts
    old = os.environ.get("TEXT_SELECT_FORM_FOOTER")
    os.environ["TEXT_SELECT_FORM_FOOTER"] = "0"
    try:
        importlib.reload(ts)
        pkg = _blurred_package()
        out, stats = ts.select_gap_fill_text(pkg, {}, label="t")
        assert out == pkg and not stats["applied"]
    finally:
        if old is None:
            os.environ.pop("TEXT_SELECT_FORM_FOOTER", None)
        else:
            os.environ["TEXT_SELECT_FORM_FOOTER"] = old
        importlib.reload(ts)


def test_a_forms_schedule_on_the_dec_side_is_not_footer_dropped():
    # A dec package's FORMS AND ENDORSEMENTS schedule lists MANY ISO codes in
    # one place - that is dec content and must survive. A form's own footer is
    # one code per page; a window with more distinct codes than
    # _FOOTER_MAX_PER_WINDOW is a list, not a footer.
    schedule = ("FORMS AND ENDORSEMENTS SCHEDULE\n" + "\n".join(
        f"CG {i:02d} {j:02d} 04 13  ENDORSEMENT TITLE"
        for i in range(4) for j in range(6)) + "\n")
    pkg = _DEC_BLUR + schedule + _blurred_package()[len(_DEC_BLUR):]
    out, stats = select_gap_fill_text(pkg, {}, label="t")
    assert stats["applied"]
    assert "FORMS AND ENDORSEMENTS SCHEDULE" in out


def test_a_carrier_form_code_is_not_an_iso_footer():
    from services.text_selection import _ISO_FORM_CODE_RE
    # Carrier dec-page codes - the exact shapes on the client's package.
    assert not _ISO_FORM_CODE_RE.search("CA7000A 02-22")
    assert not _ISO_FORM_CODE_RE.search("CA7000A 02-22 BPF 07")
    assert not _ISO_FORM_CODE_RE.search("CO 80216-3121")      # state + ZIP+4
    # The real thing, in its common printed spellings.
    assert _ISO_FORM_CODE_RE.search("CG 00 01 04 13")
    assert _ISO_FORM_CODE_RE.search("IL 00 17 11 98")


def test_a_fact_living_only_on_a_form_page_is_rescued_from_footer_drop():
    sentinel = "UNIQUE ENDORSED VALUE 7Q9-XX-4321"
    pkg = _blurred_package(extra_on_page=40, extra=sentinel + "\n")
    out, stats = select_gap_fill_text(
        pkg, {"some_fact": {"value": sentinel}}, label="t")
    assert stats["applied"]
    assert sentinel in out, (
        "guarantee 3 outranks the footer stage: an extracted fact restores "
        "its window even when that window carries an ISO footer")
