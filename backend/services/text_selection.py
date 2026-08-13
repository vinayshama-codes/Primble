"""Choose which part of an uploaded package the GAP-FILL MODEL reads.

READ `RETRIEVAL_CHANGES.md` AT THE REPO ROOT BEFORE CHANGING ANYTHING HERE.
It records every decision below and why the alternatives were rejected.

WHY THIS EXISTS
---------------
Measured on the client's real 271-page package (2026-08-12):

    raw_text_chars=683601   prompt_chars=724348   chunk 1/1
    LLM_SPEND stage=gap_fill in=174664 tokens
    gpt_fill: sent=31 filled=14 | sent=40 filled=5 | ...   -> 42/159 = 26%

The whole package goes into every call, the field list is ~1% of the prompt,
and the model answers a quarter of what it is asked. It is not failing to read;
it is being asked 40 unrelated questions inside a 174k-token haystack that is
mostly standard policy wording - and that wording contains a plausible wrong
answer to almost every ACORD 125 General Information question. The client named
it themselves: *"Primble is treating policy language describing who COULD be
covered as evidence that the entity or condition EXISTS."*

WHAT IT DOES
------------
Keeps the declarations/schedule regions, drops the standard policy wording, and
hands the model ONE filtered document that is identical across every call in the
run - so OpenAI's prefix cache (measured at 98-99% here) keeps working and the
call count does not change. Cost falls in proportion to the document.

WHAT IT MUST NEVER DO
---------------------
Lose a value that is on the declarations page. Four guarantees enforce that; see
`select_gap_fill_text`. The last one is the important one: when the signal
cannot discriminate, this returns the input UNCHANGED rather than guessing.

SCOPE - and this is the subtle part
-----------------------------------
Only the gap-fill PROMPT is filtered. `map_facts_to_form` keeps the COMPLETE
document, because that is what the evidence gate, `_value_in_raw_text`, the NAIC
guard and the classification-code guard use to VERIFY what the model produced.
Point verification at the filtered text and any answer grounded in a dropped
region gets wrongly blanked - the change would start deleting correct data.
The two must never be unified.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Reused from the extraction scorer - NOT re-derived here. `_window_authority`
# scores a span 0.0 (wrapped policy prose) .. 1.0 (dense tabular schedule) using
# only line length and figure/date density, and
# `test_authority_needs_no_insurance_vocabulary` fails the build if it ever
# acquires domain keywords. Writing a second classifier is how two thresholds
# drift apart (improving-ll.md C3).
from services.extraction_service import (           # noqa: E402
    _AUTHORITY_TIER_CUTS,
    _AUTHORITY_WINDOW_CHARS,
    _window_authority,
)

# ── Configuration ───────────────────────────────────────────────────────────
# Every one of these exists to be turned OFF or loosened, never to be tuned to a
# particular client's paperwork.

# DEFAULT OFF - OWNER DECISION 2026-08-12, after a live run where coverage
# DROPPED with filtering on: the entry-anchored mode keeps only windows that
# carry an already-known value, and a dec window whose values extraction never
# captured (audit basis, billing block, underwriter line) has no anchor - so
# exactly the fields only call 2 could fill lost their source text. The owner's
# standing order is that LLM call 2 reads the COMPLETE document. Set
# GAP_FILL_TEXT_SELECTION=1 to re-enable filtering (tests do, via conftest.py);
# every stage inside keeps its own kill switch for when it is on.
_ENABLED = os.getenv("GAP_FILL_TEXT_SELECTION", "0").strip().lower() not in (
    "0", "false", "no")

# Below this the document is left alone. A short submission is already cheap,
# its signal-to-noise is already fine, and every part of it may matter. The
# 271-page package that motivated this is 683,601 chars; a dec page alone is
# ~9,000. Anything under this threshold is not the problem being solved.
_MIN_CHARS = int(os.getenv("TEXT_SELECT_MIN_CHARS", "60000"))

# One window ~ one printed page. Same constant the extraction scorer uses, so
# "a page" means the same thing in both places.
_WINDOW = max(500, _AUTHORITY_WINDOW_CHARS)

# The prose/mixed boundary from the extraction scorer's own tier cuts. Using a
# bespoke number here would mean two different definitions of "this is prose".
_KEEP_CUT = float(os.getenv("TEXT_SELECT_KEEP_CUT", str(_AUTHORITY_TIER_CUTS[0])))

# Kept windows are dilated by this many neighbours on each side, so a schedule
# straddling a window boundary cannot be half-dropped. 1 is deliberate: it costs
# ~2 pages per kept region and removes the entire class of boundary accidents.
_DILATE = int(os.getenv("TEXT_SELECT_DILATE", "1"))

# If the filter would keep less than this share, the signal failed to
# discriminate (a uniformly-prose document - a narrative, a supplemental
# application). Returning the input unchanged is the only safe answer; deleting
# 97% of a document on a signal that did not fire is not.
_MIN_KEEP_RATIO = float(os.getenv("TEXT_SELECT_MIN_KEEP", "0.02"))

# If it would keep more than this share there is nothing to gain, and rewriting
# the text for a 3% saving only risks a boundary artefact.
_MAX_KEEP_RATIO = float(os.getenv("TEXT_SELECT_MAX_KEEP", "0.90"))

# Fact values shorter than this are not searched for: too short to locate
# unambiguously, and their windows would be restored on a coincidence.
_FACT_MIN_CHARS = 4

# ── Adaptive cut ────────────────────────────────────────────────────────────
# MEASURED FAILURE, client's real 271-page package, 2026-08-12:
#
#     TEXT_SELECTION SKIPPED kept ratio 97.4% outside [2%, 90%]
#
# The absolute cut did not discriminate. `_window_authority` is
# `0.5*figure_density + 0.5*brevity`, and pdfplumber's native extraction emits
# SHORT LINES EVERYWHERE - so `brevity` sat near 0.86 on every page of that
# document. A policy-form page scored ~0.44 and a declarations page ~0.83:
# both far above 0.25, so nothing was dropped and the prompt stayed at 174k
# tokens per call.
#
# The two page types were still cleanly separated - just not around the number
# 0.25. So the cut is now taken FROM THE DOCUMENT'S OWN DISTRIBUTION (Otsu's
# method: the threshold maximising between-class variance) instead of from a
# constant that cannot know how a particular PDF extractor renders lines.
#
# THE DANGER THIS CREATES: on a document that is ALL declarations, a purely
# relative threshold still finds "a" split somewhere inside the noise and would
# delete half the real data. So the split must first be shown to be REAL.
#
# The measure is the WIDTH OF THE GAP it sits in. A document with two kinds of
# page has a visible empty band between them; a document with one kind has no
# wide gap anywhere, whatever its absolute scores. Measured:
#
#     realistic package   gap=0.19 -> separable, 26% kept, 14/14 values preserved
#     all declarations    gap=0.00 -> refused
#     all policy wording  gap=0.01 -> refused
#
# Fail the gate and the ABSOLUTE cut is used, i.e. exactly today's behaviour.
_ADAPTIVE = os.getenv("TEXT_SELECT_ADAPTIVE", "1").strip().lower() not in (
    "0", "false", "no")
# THE ONLY GATE. A gap this wide in the sorted window scores is a real
# boundary between two kinds of page; anything narrower is one kind of page
# with noise. Deliberately NOT a variance-explained gate - see _separation_cut.
_MIN_SEPARATION_GAP = float(os.getenv("TEXT_SELECT_MIN_SEPARATION_GAP", "0.15"))
# Below this many windows there is not enough of a distribution to call
# anything bimodal, and the document is small enough not to matter.
_MIN_WINDOWS_FOR_SPLIT = int(os.getenv("TEXT_SELECT_MIN_WINDOWS", "10"))

# ── Step 2: standard-form pages identified by their OWN printed footer ───────
# The density signal FAILED on the client's live package twice: pdfplumber
# emits short lines on every page, so the separation gap came out 0.07 against
# the 0.15 floor and the filter skipped - the prompt stayed a 174k-token
# haystack and the fill rate stayed at 26%. This is the complementary signal
# RETRIEVAL_CHANGES.md planned as Step 2: an ISO standard form declares ITSELF
# in its page footer ("CG 00 01 04 13" - two letters, then form number and
# edition as four 2-digit groups). That is a positive identification of
# boilerplate, independent of how any PDF extractor renders lines.
#
# Two shapes it deliberately does NOT match:
#   * carrier dec-page form codes ("CA7000A 02-22") - different shape, and dec
#     pages are exactly what must never be dropped;
#   * the FORMS AND ENDORSEMENTS schedule on a dec page, which lists MANY such
#     codes in one place. A form's own footer appears once per printed page
#     (~one per window); a schedule crams 10-40 into one window. Hence
#     `_FOOTER_MAX_PER_WINDOW`: more distinct codes than that means a LIST of
#     forms - dec content - and the window is kept.
#
# Guarantees 2-4 (dilation, fact rescue, the ratio gates) apply to the combined
# result, and the fact rescue runs AFTER footer-dropping, so an extracted fact
# living on a form page always restores its window. `TEXT_SELECT_FORM_FOOTER=0`
# disables this stage alone; the density stage is untouched either way.
# ── Entry-anchored keep (2026-08-12, same day as the footer stage) ──────────
# When call 1 produced enough VERIFIED dec-page entries, the windows those
# values live in ARE the declarations content - a carrier-agnostic fingerprint
# that needs no density statistic and no footer convention. Engages only above
# the entry floor; below it the density+footer path runs exactly as before.
_ENTRY_ANCHOR = os.getenv(
    "TEXT_SELECT_ENTRY_ANCHOR", "1").strip().lower() not in ("0", "false", "no")
# Below this many verified entries the fingerprint is too thin to trust as the
# ONLY selector - a doc type the extraction barely touched must keep today's
# behaviour rather than being cut down to two windows.
_ENTRY_ANCHOR_MIN = int(os.getenv("TEXT_SELECT_ENTRY_MIN", "20"))

_FOOTER_ENABLED = os.getenv(
    "TEXT_SELECT_FORM_FOOTER", "1").strip().lower() not in ("0", "false", "no")
_ISO_FORM_CODE_RE = re.compile(r"\b[A-Z]{2}[ -]?\d{2}[ -]\d{2}[ -]\d{2}[ -]\d{2}\b")
_FOOTER_MAX_PER_WINDOW = int(os.getenv("TEXT_SELECT_FOOTER_MAX_PER_WINDOW", "2"))
# Below this many footer-marked windows the pattern is noise, not a policy-form
# section - a real commercial package has dozens of standard-form pages.
_FOOTER_MIN_WINDOWS = int(os.getenv("TEXT_SELECT_FOOTER_MIN_WINDOWS", "3"))


def _separation_cut(scores: List[float]) -> Optional[Tuple[float, float, float]]:
    """Where the declarations pages separate from the bulk of the document.

    Returns ``(cut, variance_explained, gap)`` or None.

    **NOT Otsu, despite the name kept for continuity.** Otsu was tried first and
    MEASURED WRONG on the client's real package (2026-08-12):

        windows=228 min=0.00 median=0.39 max=0.70
        otsu_cut=0.34 var_explained=0.61 mean_gap=0.19 bimodal=True
        -> kept 96.1%, still skipped

    Otsu maximises between-class variance `w0*w1*(mu0-mu1)^2`, and that term is
    dominated by the BALANCE of the two classes. On a 271-page policy the
    declarations pages are ~5% of the document, so the most "balanced" split is
    not the one that matters: Otsu separated the ~4% of near-empty windows
    (min=0.00) from the other 96% and left the real boundary - between the
    ~0.39 bulk and the ~0.70 declarations tail - untouched.

    What is actually wanted is the boundary between the BULK and a MINORITY TOP
    GROUP, which is the LARGEST GAP in the sorted scores above the median. That
    is parameter-free, it is not fooled by class imbalance (a 5% tail is exactly
    what it is built to find), and the gap width is itself the quality measure -
    a tight unimodal cloud has no large gap anywhere, so it declines.

    Searching only ABOVE THE MEDIAN is deliberate: it is what makes this look
    for a minority top group rather than any break at all, and it bounds the
    kept share at 50% so a bad call cannot keep almost everything.
    """
    n = len(scores)
    if n < _MIN_WINDOWS_FOR_SPLIT:
        return None
    ordered = sorted(scores)
    mean = sum(ordered) / n
    var_total = sum((s - mean) ** 2 for s in ordered) / n
    if var_total <= 0:
        return None                       # every window identical - no split
    # Search only splits whose KEPT (upper) group is at most half the document.
    # Splitting between index i and i+1 keeps n-(i+1) windows, so that bound is
    # i >= ceil(n/2) - 1. Using a plain `n // 2` excluded the boundary of an
    # exactly-50/50 document - a real off-by-one, caught by a unit test whose
    # fixture happened to split precisely at the median.
    lo = max(0, (n + 1) // 2 - 1)
    best_gap, best_cut = 0.0, None
    for i in range(lo, n - 1):
        gap = ordered[i + 1] - ordered[i]
        if gap > best_gap:
            best_gap = gap
            best_cut = (ordered[i] + ordered[i + 1]) / 2.0
    if best_cut is None:
        return None
    # Variance explained by THIS split, reported for the log and the gate.
    below = [s for s in ordered if s < best_cut]
    above = [s for s in ordered if s >= best_cut]
    if not below or not above:
        return None
    w0, w1 = len(below) / n, len(above) / n
    mu0, mu1 = sum(below) / len(below), sum(above) / len(above)
    var_explained = (w0 * w1 * (mu0 - mu1) ** 2) / var_total
    return best_cut, var_explained, best_gap


def _norm(text: str) -> str:
    """Punctuation/case-insensitive form, for presence checks only.

    Mirrors `pdf_service._normalize_for_search` deliberately: "$6,150,000" and
    "6 150 000" must compare equal, or the fact-rescue guarantee would fire on
    formatting rather than on real absence.
    """
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _fact_values(facts: Optional[dict]) -> List[str]:
    """Every scalar fact value worth protecting, unwrapped from its envelope.

    Extraction has ALREADY proved these strings are real content in this
    document. They are the ground truth for guarantee 3: whatever else this
    filter drops, it may not drop the text these came from.
    """
    out: List[str] = []
    for key, value in (facts or {}).items():
        # Verified dec-page entries (2026-08-12): each entry's VALUE is a
        # literally-verified dec-page string, so it is exactly the class of
        # content guarantee 3 protects. Including them here means a window
        # carrying a dec value the 173-key extraction never captured as a fact
        # is STILL rescued - the one data-loss shape the filter had left open.
        # Only ever ADDS kept text; the ratio gates still judge the result.
        if key == "dec_page_entries" and isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    v = str(item.get("value") or "").strip()
                    if len(v) >= _FACT_MIN_CHARS:
                        out.append(v)
            continue
        if isinstance(value, dict) and "value" in value:
            value = value.get("value")
        if isinstance(value, bool) or value is None:
            continue
        if isinstance(value, (int, float)):
            value = str(value)
        if not isinstance(value, str):
            continue                      # lists/dicts (schedules) are not searched
        value = value.strip()
        if len(value) >= _FACT_MIN_CHARS:
            out.append(value)
    return out


def select_gap_fill_text(
    raw_text: str,
    facts: Optional[dict] = None,
    label: str = "",
) -> Tuple[str, Dict[str, Any]]:
    """Return (text_for_the_model, stats). NEVER raises.

    FOUR GUARANTEES, in the order they are enforced:

      1. A document below `_MIN_CHARS` is returned unchanged.
      2. Kept windows are dilated by `_DILATE`, so a region cut by a window
         boundary keeps its neighbours.
      3. Every scalar fact value still present in the ORIGINAL is checked
         against the KEPT text; a missing one has its window restored. The facts
         are what extraction already proved is real data in this document.
      4. If the kept share falls outside [`_MIN_KEEP_RATIO`, `_MAX_KEEP_RATIO`]
         the signal did not discriminate, and the ORIGINAL is returned unchanged.

    Guarantee 4 is the one that makes this safe on a document shape nobody
    anticipated. It mirrors `_partition_by_shape`, which returns its input
    unchanged when every candidate fails.
    """
    stats: Dict[str, Any] = {
        "applied": False, "reason": "", "original_chars": len(raw_text or ""),
        "kept_chars": len(raw_text or ""), "windows": 0, "kept_windows": 0,
        "rescued_windows": 0, "cut": _KEEP_CUT, "cut_kind": "absolute",
    }
    try:
        if not _ENABLED:
            stats["reason"] = "disabled"
            return raw_text, stats
        if not raw_text or len(raw_text) < _MIN_CHARS:
            stats["reason"] = f"document under {_MIN_CHARS} chars - left alone"
            logger.info("TEXT_SELECTION SKIPPED label=%s %s", label, stats["reason"])
            return raw_text, stats

        # ── Score every window ───────────────────────────────────────────────
        # Non-overlapping here, unlike `declarations_authority`'s 50%-overlap
        # MAX scan: that function asks "does this span contain a dec page
        # anywhere", which is the right question for scoring a whole chunk and
        # the WRONG one for deciding what to delete - with overlap every window
        # inherits its neighbour's score and nothing is ever dropped. Dilation
        # below restores the boundary safety that overlap would have given.
        windows = [raw_text[i:i + _WINDOW] for i in range(0, len(raw_text), _WINDOW)]
        scores = [_window_authority(w) for w in windows]
        stats["windows"] = len(windows)

        # ── Entry-anchored keep: the verified entries ARE the dec fingerprint ─
        # Measured live 2026-08-12 (the client's 271-page EMC package): the
        # density signal declined (gap 0.07) and the ISO-footer stage caught
        # only 82 of 228 windows, because EMC's boilerplate is CARRIER-
        # PROPRIETARY form pages ("FORM CU7000A ED. 01-07") that no ISO shape
        # can identify - 66.4% kept, calls still ~120k tokens, fill rate 31%.
        #
        # The same run produced 161 VERIFIED dec-page entries - values proven
        # literally present, extracted from the dec pages themselves. Windows
        # containing those values ARE the declarations content, whoever the
        # carrier is and however their PDF renders. So when enough entries
        # exist, keep the windows the anchors live in and skip trying to
        # identify boilerplate at all. Anchors = every protected value
        # (_fact_values: scalar facts + verified entry values), so guarantee 3
        # is satisfied BY CONSTRUCTION - the rescue pass below then has nothing
        # to restore, and the ratio gates still judge the result.
        #
        # Falls back to the density+footer path when entries are scarce (an
        # old session, a doc type extraction barely touched) - never on a
        # guess. TEXT_SELECT_ENTRY_ANCHOR=0 disables this stage alone.
        _anchored = False
        _anchor_values = _fact_values(facts) if _ENTRY_ANCHOR else []
        _entry_count = sum(
            1 for item in ((facts or {}).get("dec_page_entries") or [])
            if isinstance(item, dict))
        if _ENTRY_ANCHOR and _entry_count >= _ENTRY_ANCHOR_MIN and _anchor_values:
            _needles = [n for n in (_norm(v) for v in _anchor_values) if n]
            _win_norms = [_norm(w) for w in windows]
            keep = {
                i for i, wn in enumerate(_win_norms)
                if any(n in wn for n in _needles)
            }
            if keep:
                _anchored = True
                stats["cut_kind"] = "entry-anchor"
                logger.info(
                    "TEXT_SELECTION ENTRY_ANCHOR label=%s entries=%d anchors=%d "
                    "windows_kept=%d/%d - keeping the windows the verified "
                    "dec-page values live in, instead of guessing at boilerplate",
                    label, _entry_count, len(_needles), len(keep), len(windows),
                )

        # ── Choose the cut from THIS document, not from a constant ───────────
        # The absolute cut assumes one scale. pdfplumber's short-line output
        # moves every window up it, which is how a 271-page package came back
        # 97.4% kept. Otsu takes the cut from the document's own distribution -
        # but only when that distribution is convincingly two-humped, because on
        # an all-declarations document a relative cut would happily delete half
        # the real data. See the constants block for the two gates.
        _cut, _cut_kind = _KEEP_CUT, "absolute"
        _sep = _separation_cut(scores) if (_ADAPTIVE and not _anchored) else None
        if _sep:
            _sep_cut, _var_explained, _gap = _sep
            # THE GATE IS THE GAP WIDTH, and variance-explained is deliberately
            # NOT a gate any more. It was one while this used Otsu, and it is
            # actively wrong for a largest-gap search: `w0*w1*(mu0-mu1)^2` is
            # dominated by class BALANCE, so a genuine 5%-of-the-document
            # declarations tail scores LOW on it by construction - the gate
            # would reject exactly the split it exists to find. The gap itself
            # is the honest measure: a tight unimodal cloud (all declarations,
            # or all policy wording) has no wide gap anywhere, so it declines.
            # var_explained is still computed and logged, purely as a diagnostic.
            _separable = _gap >= _MIN_SEPARATION_GAP
            # ONLY EVER USED TO TIGHTEN. A looser Otsu cut would keep more than
            # the absolute rule already keeps, which cannot help and would make
            # this change able to *reduce* what is dropped on a document that
            # already worked.
            if _separable and _sep_cut > _cut:
                _cut, _cut_kind = _sep_cut, "adaptive"
            _ordered = sorted(scores)
            def _pct(q):
                return _ordered[min(len(_ordered) - 1, int(q * len(_ordered)))]
            logger.info(
                "TEXT_SELECTION DISTRIBUTION label=%s windows=%d "
                "p0=%.2f p25=%.2f p50=%.2f p75=%.2f p90=%.2f p95=%.2f p100=%.2f | "
                "gap_cut=%.2f gap=%.2f var_explained=%.2f (diagnostic only) "
                "separable=%s -> using %s cut %.2f",
                label, len(scores), _ordered[0], _pct(.25), _pct(.50), _pct(.75),
                _pct(.90), _pct(.95), _ordered[-1],
                _sep_cut, _gap, _var_explained, _separable, _cut_kind, _cut,
            )
        if not _anchored:
            stats["cut"] = _cut
            stats["cut_kind"] = _cut_kind
            keep = {i for i, s in enumerate(scores) if s >= _cut}
        if keep and _DILATE > 0:                       # guarantee 2
            for i in list(keep):
                for d in range(1, _DILATE + 1):
                    if i - d >= 0:
                        keep.add(i - d)
                    if i + d < len(windows):
                        keep.add(i + d)

        # ── Step 2: drop pages that DECLARE themselves standard-form wording ─
        # Runs after dilation (its positive identification outranks a
        # neighbour-of-a-dec-page guess) and before the fact rescue (which can
        # re-add any window here, keeping guarantee 3 absolute). When the
        # density stage failed to discriminate - kept ratio near 100%, the
        # measured state on the client's package - this is the stage that still
        # produces a usable cut, and the ratio gates below judge the COMBINED
        # result exactly as they judged the density result before.
        footer_dropped = 0
        # In entry-anchored mode there is no boilerplate to identify - only the
        # anchored windows were kept in the first place, so subtracting footer
        # pages could only remove a window a VERIFIED dec value lives in.
        if _FOOTER_ENABLED and not _anchored:
            code_counts = [len(set(_ISO_FORM_CODE_RE.findall(w))) for w in windows]
            # More codes than a footer can explain = a FORMS AND ENDORSEMENTS
            # schedule (dec content). Its window is kept - and so is any window
            # NEXT to one, because a schedule cut by a window boundary leaves
            # 1-2 spilled codes in its neighbour, which would otherwise look
            # exactly like a form page's footer. Caught by the fixture in
            # test_a_forms_schedule_on_the_dec_side_is_not_footer_dropped.
            schedule_like = {
                i for i, n in enumerate(code_counts) if n > _FOOTER_MAX_PER_WINDOW
            }
            marked = {
                i for i, n in enumerate(code_counts)
                if 1 <= n <= _FOOTER_MAX_PER_WINDOW
                and (i - 1) not in schedule_like
                and (i + 1) not in schedule_like
            }
            if len(marked) >= _FOOTER_MIN_WINDOWS:
                before = len(keep)
                keep -= marked
                footer_dropped = before - len(keep)
                logger.info(
                    "TEXT_SELECTION FORM_FOOTER label=%s windows_marked=%d "
                    "dropped_from_keep=%d - pages carrying an ISO form-number "
                    "footer are standard policy wording by their own statement",
                    label, len(marked), footer_dropped,
                )
        stats["footer_dropped"] = footer_dropped

        # ── Guarantee 3: no already-extracted fact may become invisible ───────
        # Cheap because it only runs over facts NOT already present in the kept
        # text, and only those actually findable in the original.
        rescued = 0
        if keep:
            kept_norm = _norm("".join(windows[i] for i in sorted(keep)))
            win_norms: Optional[List[str]] = None
            for value in _fact_values(facts):
                needle = _norm(value)
                if not needle or needle in kept_norm:
                    continue
                if win_norms is None:                  # built once, only if needed
                    win_norms = [_norm(w) for w in windows]
                for i, wn in enumerate(win_norms):
                    if i in keep or needle not in wn:
                        continue
                    keep.add(i)
                    for d in range(1, _DILATE + 1):    # a rescued window gets
                        if i - d >= 0:                 # the same neighbours
                            keep.add(i - d)
                        if i + d < len(windows):
                            keep.add(i + d)
                    rescued += 1
                    logger.info(
                        "TEXT_SELECTION FACT_RESCUE label=%s window=%d value=%r "
                        "- an extracted fact lived only in a window the density "
                        "signal would have dropped; restoring it",
                        label, i, value[:60],
                    )
                    break                              # first window is enough
                kept_norm = _norm("".join(windows[j] for j in sorted(keep)))
        stats["rescued_windows"] = rescued

        kept_chars = sum(len(windows[i]) for i in sorted(keep))
        ratio = kept_chars / len(raw_text) if raw_text else 1.0

        # ── Guarantee 4: refuse to act on a signal that did not discriminate ──
        if ratio < _MIN_KEEP_RATIO or ratio > _MAX_KEEP_RATIO:
            stats["reason"] = (
                f"kept ratio {ratio:.1%} outside [{_MIN_KEEP_RATIO:.0%}, "
                f"{_MAX_KEEP_RATIO:.0%}] - the density signal did not "
                f"discriminate on this document, so nothing is dropped"
            )
            logger.warning("TEXT_SELECTION SKIPPED label=%s %s", label, stats["reason"])
            return raw_text, stats

        # Windows are re-joined IN ORDER with a gap marker, so the model is told
        # plainly that material was omitted rather than being handed two
        # unrelated passages glued into one false sentence.
        out: List[str] = []
        prev = -2
        for i in sorted(keep):
            if i != prev + 1 and out:
                out.append("\n[... omitted: standard policy wording ...]\n")
            out.append(windows[i])
            prev = i
        selected = "".join(out)

        stats.update({
            "applied": True, "kept_chars": len(selected),
            "kept_windows": len(keep),
            "reason": ("density+footer-filtered" if footer_dropped
                       else "density-filtered"),
        })
        logger.info(
            "TEXT_SELECTION label=%s APPLIED %d -> %d chars (%.1f%% kept) "
            "windows=%d/%d rescued=%d footer_dropped=%d cut=%.2f (%s)",
            label, len(raw_text), len(selected), 100.0 * len(selected) / len(raw_text),
            len(keep), len(windows), rescued, footer_dropped, _cut, _cut_kind,
        )
        return selected, stats

    except Exception as exc:                           # noqa: BLE001
        # A text-selection failure must NEVER cost a whole submission its gap
        # fill. Falling back to the complete document is always correct - it is
        # exactly today's behaviour.
        logger.warning(
            "TEXT_SELECTION label=%s failed (%s) - using the full document", label, exc)
        stats["reason"] = f"error: {exc}"
        return raw_text, stats
