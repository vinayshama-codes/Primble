"""One cross-document disagreement renders ONCE (V1 C1-Q, 2026-08-23).

LIVE RUN B, 2026-08-23: the "Document identity & date conflicts" cluster showed

    DBA / trade name differs across documents: Orbin Roofing, Orbin Electrical
      Services. Verify or add an ACORD 101 explanation. (Source: ...)
    DBA / Trade Name: documents disagree (Orbin Roofing, Orbin Electrical
      Services). Fix: Confirm the correct value to apply it across forms.

- two rows, one disagreement, from the two engines that both compare the same
eight identity fields. Mailing Address did the same, and the legacy copy listed
all THREE address spellings including the two the picker had correctly folded,
so the older row read exactly like the bug the folding fixed.

The picker's row wins: folded groups, per-document attribution, a reason, a
suggestion and a working control. These tests pin that, both directions, plus
the two properties that make the suppression safe.
"""
import os
import re

import pytest

from services.issue_registry import (
    build_grouped_view, doc_conflict_fact_key, picker_fact_key,
    _DOC_CONFLICT_CODE_TO_FACT,
)

HERE = os.path.dirname(__file__)

# The client's literal Run B strings.
LEGACY_DBA = ("DBA / trade name differs across documents: Orbin Roofing, "
              "Orbin Electrical Services. Verify or add an ACORD 101 explanation.")
PICKER_DBA = ("DBA / Trade Name: documents disagree (Orbin Roofing, Orbin "
              "Electrical Services). Fix: Confirm the correct value to apply "
              "it across forms.")
LEGACY_ADDR = ("Mailing address differs across documents: 4800 Dahlia St # D13, "
               "Denver, CO 80216-3121, 4800 Dahlia Street D13, Denver, CO 80216, "
               "2255 S Wadsworth Blvd Ste 410, Lakewood, CO 80227")
PICKER_ADDR = ("Mailing Address: documents disagree (4800 Dahlia St # D13, "
               "Denver, CO 80216-3121, 2255 S Wadsworth Blvd Ste 410, "
               "Lakewood, CO 80227). Fix: Confirm the correct value to apply "
               "it across forms.")
LEGACY_LOB = ("Lines of business differ across documents: Commercial General "
              "Liability, Commercial Property")


def _issue(code, severity, message):
    return {"code": code, "severity": severity, "message": message}


def _messages(view):
    """Every message the view actually renders, from ALL sections.

    `warnings` is a dict of TIERS, not a list - an earlier version of this
    helper iterated it like a list, got the tier names as strings, skipped them
    all, and so only ever read `important` and `hard_stops`. That is the C25
    shape: a check that looks thorough and reads half the structure.
    """
    out = []

    def _eat(clusters):
        for cluster in (clusters or []):
            if not isinstance(cluster, dict):
                continue
            for item in (cluster.get("items") or [cluster]):
                msg = item.get("message") if isinstance(item, dict) else None
                if msg:
                    out.append(msg)

    _eat(view.get("hard_stops"))
    _eat(view.get("important"))
    warnings = view.get("warnings")
    if isinstance(warnings, dict):
        for tier_clusters in warnings.values():
            _eat(tier_clusters)
    else:
        _eat(warnings)
    return out


def test_the_message_walker_reads_the_warnings_tiers():
    """Self-check for the helper above - if it silently stops seeing the
    warnings dict again, every assertion in this file weakens without failing."""
    view = build_grouped_view(
        [_issue("doc_conflict_warn_lines_of_business", "soft_warning", LEGACY_LOB)],
        [], [LEGACY_LOB])
    assert isinstance(view.get("warnings"), dict), "shape changed - update _messages"
    assert LEGACY_LOB in _messages(view)


def _view(issues, hard, soft):
    return build_grouped_view(issues, list(hard), list(soft))


# ── 1. The reported case, both fields ───────────────────────────────────────

def test_the_legacy_twin_is_hidden_when_the_picker_row_is_present():
    """Run B's literal shape: one row survives per disagreement, the picker's."""
    issues = [
        _issue("doc_conflict_warn_dba_name", "soft_warning", LEGACY_DBA),
        _issue("underwriting_reconciliation_dba_name", "soft_warning", PICKER_DBA),
        _issue("doc_conflict_warn_mailing_address", "soft_warning", LEGACY_ADDR),
        _issue("underwriting_reconciliation_mailing_address", "soft_warning", PICKER_ADDR),
    ]
    msgs = _messages(_view(issues, [], [LEGACY_DBA, PICKER_DBA, LEGACY_ADDR, PICKER_ADDR]))
    assert PICKER_DBA in msgs
    assert PICKER_ADDR in msgs
    assert LEGACY_DBA not in msgs
    assert LEGACY_ADDR not in msgs


def test_the_folded_address_spellings_stop_being_reprinted():
    """The legacy copy is the ONLY row that listed all three spellings. Hiding
    it is what stops the screen re-showing what the picker just folded."""
    issues = [
        _issue("doc_conflict_warn_mailing_address", "soft_warning", LEGACY_ADDR),
        _issue("underwriting_reconciliation_mailing_address", "soft_warning", PICKER_ADDR),
    ]
    joined = " ".join(_messages(_view(issues, [], [LEGACY_ADDR, PICKER_ADDR])))
    assert "4800 Dahlia Street D13" not in joined, (
        "the equivalent second spelling is being shown as a rival value again")
    assert "2255 S Wadsworth Blvd" in joined, "the REAL rival must still show"


# ── 2. Nothing is ever lost ─────────────────────────────────────────────────

def test_the_legacy_row_survives_when_the_picker_did_not_fire():
    """Suppression is gated on the superseding row being PRESENT. A field the
    picker never assessed keeps today's behaviour exactly."""
    issues = [_issue("doc_conflict_warn_dba_name", "soft_warning", LEGACY_DBA)]
    msgs = _messages(_view(issues, [], [LEGACY_DBA]))
    assert LEGACY_DBA in msgs


def test_lines_of_business_is_never_suppressed():
    """`lines_of_business` has no picker row by design (it is not a
    reconcilable field), so the coverage contradiction Run B planted must
    always survive."""
    issues = [
        _issue("doc_conflict_warn_lines_of_business", "soft_warning", LEGACY_LOB),
        _issue("underwriting_reconciliation_dba_name", "soft_warning", PICKER_DBA),
    ]
    msgs = _messages(_view(issues, [], [LEGACY_LOB, PICKER_DBA]))
    assert LEGACY_LOB in msgs


def test_a_hard_stop_is_never_hidden_behind_a_warning():
    """THE SAFETY PROPERTY. A 60 cap with nothing on screen explaining it is
    worse than a duplicate row. Today the two engines agree on which four
    fields block; this guard means a future drift degrades to a duplicate
    instead of an invisible blocker."""
    legacy_fein = "FEIN differs across uploaded documents. Score is capped at 60."
    picker_fein = "FEIN: documents disagree (84-2210987, 99-9999999)."
    issues = [
        _issue("doc_conflict_hard_fein_conflict", "hard_stop", legacy_fein),
        _issue("underwriting_reconciliation_fein", "soft_warning", picker_fein),
    ]
    msgs = _messages(_view(issues, [legacy_fein], [picker_fein]))
    assert legacy_fein in msgs, "a hard stop was hidden behind a warning"


def test_a_hard_stop_IS_superseded_by_an_equally_hard_picker_row():
    """The normal case for the four blocking fields - the surviving row is
    just as blocking, so the producer still sees why the score is capped."""
    legacy_fein = "FEIN differs across uploaded documents. Score is capped at 60."
    picker_fein = "FEIN: documents disagree (84-2210987, 99-9999999)."
    issues = [
        _issue("doc_conflict_hard_fein_conflict", "hard_stop", legacy_fein),
        _issue("underwriting_reconciliation_fein", "hard_stop", picker_fein),
    ]
    msgs = _messages(_view(issues, [legacy_fein, picker_fein], []))
    assert picker_fein in msgs
    assert legacy_fein not in msgs


def test_the_callers_stop_arrays_are_not_mutated():
    """SQS caps, dismiss credit and issue_id hashing all key off these arrays.
    Suppression is display-only; the block above this one carries the same
    contract and the same test."""
    hard = ["FEIN differs across uploaded documents."]
    soft = [LEGACY_DBA, PICKER_DBA]
    before_hard, before_soft = list(hard), list(soft)
    build_grouped_view(
        [_issue("doc_conflict_warn_dba_name", "soft_warning", LEGACY_DBA),
         _issue("underwriting_reconciliation_dba_name", "soft_warning", PICKER_DBA)],
        hard, soft)
    assert hard == before_hard
    assert soft == before_soft


# ── 3. ANTI-ROT - a fifth code token cannot appear unmapped ─────────────────

def _emitted_doc_consistency_tokens():
    """Every `field=`/`code=` token `check_doc_consistency` can actually emit.

    Harvested from its source, not from a list someone maintains alongside it -
    the same device as `test_legacy_rules.py`. Its branches are mutually
    exclusive, so driving the function would silently under-cover.
    """
    src = open(os.path.join(HERE, "..", "services", "sqs_service.py"),
               encoding="utf-8").read()
    start = src.index("def check_doc_consistency")
    end = src.index("\ndef ", start + 10)
    body = src[start:end]
    # Drop every docstring in the range - they show the wire format
    # ("[hard_stop] code=x <msg>") and those examples are not tokens anything
    # emits. The range spans the function's own nested helpers, so there is
    # more than one.
    body = re.sub(r'"""[\s\S]*?"""', "", body)
    # ... and comment-only lines, for the same reason. A comment cannot emit an
    # issue, and one of them documents the wire format verbatim.
    body = "\n".join(ln for ln in body.splitlines()
                     if not ln.lstrip().startswith("#"))
    # LITERAL tokens only. An f-string interpolation (`field={key}`) is a loop
    # over fact keys by construction, never a rule name, so it needs no mapping
    # decision - which is exactly what this harvest exists to force.
    return set(re.findall(r'(?:field|code)=(?!\{)([a-z0-9_]+)', body))


def test_the_harvester_actually_finds_something():
    """C25: an empty harvest makes the coverage test below pass vacuously."""
    assert len(_emitted_doc_consistency_tokens()) >= 6, (
        "the harvester found almost nothing - check_doc_consistency was probably "
        "refactored and this guard is now blind")


def test_every_emitted_token_resolves_to_a_fact_key():
    """A token that is neither a real fact key nor mapped here would silently
    never match its picker twin, and the duplicate would come back."""
    from services.underwriting_consistency import RECONCILABLE_FIELDS
    unresolved = []
    for token in _emitted_doc_consistency_tokens():
        if token.endswith("_normalized"):
            continue                      # [info] rows never become an issue
        fact = doc_conflict_fact_key(f"doc_conflict_warn_{token}")
        if fact in _DOC_CONFLICT_CODE_TO_FACT.values():
            continue                      # explicitly mapped
        if fact in RECONCILABLE_FIELDS:
            continue                      # `field=<fact_key>`, needs no remap
        if fact == "lines_of_business":
            continue                      # deliberately has no picker row
        unresolved.append(token)
    assert not unresolved, (
        "check_doc_consistency emits token(s) with no canonical fact, so their "
        f"picker twin can never supersede them: {sorted(unresolved)}. Add the "
        "mapping to issue_registry._DOC_CONFLICT_CODE_TO_FACT.")


def test_every_mapped_token_is_still_emitted():
    """The mirror image, and the mistake the umbrella entry made: a mapping
    keyed on a token nothing emits is a silent no-op."""
    emitted = _emitted_doc_consistency_tokens()
    dead = [t for t in _DOC_CONFLICT_CODE_TO_FACT if t not in emitted]
    assert not dead, f"mapping keyed on token(s) nothing emits: {dead}"


def test_every_mapped_fact_is_a_real_reconcilable_field():
    """The remap only helps if the picker actually owns that fact."""
    from services.underwriting_consistency import RECONCILABLE_FIELDS
    for token, fact in _DOC_CONFLICT_CODE_TO_FACT.items():
        assert fact in RECONCILABLE_FIELDS, (
            f"{token} maps to {fact}, which the picker does not assess - "
            "suppression would hide the only row about it")


@pytest.mark.parametrize("code,expected", [
    ("doc_conflict_hard_name_conflict", "applicant_name"),
    ("doc_conflict_warn_dba_name", "dba_name"),
    ("doc_conflict_hard_date_conflict", "effective_date"),
    ("underwriting_reconciliation_fein", None),
    ("some_other_code", None),
])
def test_doc_conflict_fact_key_cases(code, expected):
    assert doc_conflict_fact_key(code) == expected


def test_picker_fact_key_cases():
    assert picker_fact_key("underwriting_reconciliation_mailing_address") == "mailing_address"
    assert picker_fact_key("doc_conflict_warn_dba_name") is None
    assert picker_fact_key(None) is None
