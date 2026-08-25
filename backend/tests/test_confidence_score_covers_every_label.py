"""ANTI-ROT: every per-field confidence label the fill layer emits has a weight.

Found 2026-08-24 (v1-20AUG.md C1-S). `sqs_service.confidence_fill_rate` reads
``CONFIDENCE_SCORE.get(label, 0.0)``, so a label that is assigned in
``pdf_service`` but absent from the table silently scores ZERO. The
"ai_verified" label - an AI value CONFIRMED present in the uploaded document,
painted pink "AI-OK" on the form - had been missing from the table since the
day raw-text verification shipped. A form of ten document-verified AI fields
reported a **0%** fill rate; ten unverified guesses reported 50%. Verification
made the score worse, on every submission, for weeks.

Same device as `test_legacy_rules` (harvest what the code can actually emit,
fail the build on anything unmapped) and `test_no_check_reads_a_fact_nothing_
writes`. The harvest is a regex over the SOURCE of the two modules that assign
per-field labels, so a new label cannot ship without a weight, and the
harvester has a self-check so an empty harvest cannot pass vacuously (C25).
"""
import pathlib
import re

import pytest

from services.sqs_service import CONFIDENCE_SCORE, confidence_fill_rate

ROOT = pathlib.Path(__file__).resolve().parents[1]

# Every module that assigns a per-field confidence label into the dict the
# fill-rate reads. Add a module here if a new one starts writing
# ``confidence[<field>] = "<label>"``.
_LABEL_WRITERS = (
    ROOT / "services" / "pdf_service.py",
    ROOT / "routes" / "form_routes.py",
)

# ``confidence[field] = "label"`` and the ternary form
# ``confidence[field] = "a" if cond else "b"``.
_ASSIGN_RE = re.compile(r'confidence\[[^\]]+\]\s*=\s*"([a-z_]+)"(?:\s+if\b[^\n]*?\belse\s+"([a-z_]+)")?')


def _harvest_labels() -> set:
    found = set()
    for path in _LABEL_WRITERS:
        src = path.read_text(encoding="utf-8")
        for m in _ASSIGN_RE.finditer(src):
            found.add(m.group(1))
            if m.group(2):
                found.add(m.group(2))
    return found


def test_the_harvester_actually_finds_labels():
    """C25 self-check: an empty harvest would make the coverage test pass
    vacuously. The two labels the fill layer has emitted since day one must be
    visible to the regex."""
    labels = _harvest_labels()
    assert {"filled", "low_confidence"} <= labels, labels


def test_the_harvester_sees_the_ternary_form():
    src = 'confidence[f] = "filled" if has(f) else "low_confidence"\n'
    m = _ASSIGN_RE.search(src)
    assert m and m.group(1) == "filled" and m.group(2) == "low_confidence"


def test_every_emitted_label_has_a_weight():
    """A label with no weight scores 0.0 silently. That is the ai_verified bug.

    C3 3.8 (2026-08-25) added a SECOND legitimate destination for a label:
    `FILL_RATE_EXCLUDED_LABELS`, whose members are dropped from the fill rate
    entirely rather than weighted. `not_applicable` lives there because
    *"Not Applicable fields must not reduce fill rate"* - a 0.00 weight would
    still sit in the denominator and drag the average down, which is the defect
    rather than the fix.

    The invariant is unchanged and still bites: a label must be DELIBERATELY
    placed in one of the two, and a new one in neither still fails the build.
    """
    from services.sqs_service import FILL_RATE_EXCLUDED_LABELS
    accounted = set(CONFIDENCE_SCORE) | set(FILL_RATE_EXCLUDED_LABELS)
    missing = sorted(_harvest_labels() - accounted)
    assert missing == [], (
        f"per-field confidence label(s) assigned in the fill layer but absent "
        f"from BOTH sqs_service.CONFIDENCE_SCORE and FILL_RATE_EXCLUDED_LABELS "
        f"- they score ZERO: {missing}")
    assert not (set(CONFIDENCE_SCORE) & set(FILL_RATE_EXCLUDED_LABELS)), (
        "a label is either weighted or excluded, never both - being in the "
        "weight table would invite someone to 'simplify' the exclusion away"
    )


def test_c3_38_fill_rate_rules():
    """The four C3 3.8 rules, each pinned to its measured before-value."""
    from services.sqs_service import confidence_fill_rate as _f

    # 1. Not Applicable must not reduce the fill rate. Measured before: 75.
    assert _f({"a": "Acme", "b": "N/A"},
              {"a": "filled", "b": "not_applicable"}) == 100
    # 2. A conflicting field does not get full completed-field credit.
    assert _f({"a": "Acme"}, {"a": "conflicted"}) < _f({"a": "Acme"}, {"a": "filled"})
    # 3. Suggested / unverified never equals Source Verified or User Confirmed.
    assert CONFIDENCE_SCORE["ai_verified"] < CONFIDENCE_SCORE["filled"]
    assert CONFIDENCE_SCORE["low_confidence"] < CONFIDENCE_SCORE["client_arq"]
    # 4. An Explicit No is a valid completed response. Measured before: 0.
    assert _f({"a": "None"}, {"a": "explicit_no"}) == 100
    # ...but ONLY via the label. A stringified Python None is still not credit -
    # that is why the emptiness test excludes the string in the first place.
    assert _f({"a": "None"}, {"a": "filled"}) == 0


def test_a_document_verified_ai_value_outscores_an_unverified_guess():
    """The ladder the fill layer promises: verified > unverified > missing."""
    assert CONFIDENCE_SCORE["ai_verified"] > CONFIDENCE_SCORE["low_confidence"]
    assert CONFIDENCE_SCORE["low_confidence"] > CONFIDENCE_SCORE["missing_required"]
    assert CONFIDENCE_SCORE["filled"] >= CONFIDENCE_SCORE["ai_verified"]


def test_verified_ai_values_never_read_as_an_empty_form():
    """The measured shape of the defect: ten verified fields reported 0%."""
    mapped = {f"F{i}": "value" for i in range(10)}
    verified = {f: "ai_verified" for f in mapped}
    guesses = {f: "low_confidence" for f in mapped}
    assert confidence_fill_rate(mapped, verified) > confidence_fill_rate(mapped, guesses)
    assert confidence_fill_rate(mapped, verified) >= 85


def test_the_gate_label_is_an_explicit_zero_not_a_default():
    """missing_required_gate was also unlisted; 0.00 by accident is still an
    accident. It must be a decision recorded in the table."""
    assert "missing_required_gate" in CONFIDENCE_SCORE
    assert CONFIDENCE_SCORE["missing_required_gate"] == 0.0


@pytest.mark.parametrize("label", ["filled", "client_arq"])
def test_human_and_deterministic_fills_are_full_weight(label):
    assert CONFIDENCE_SCORE[label] == 1.0
