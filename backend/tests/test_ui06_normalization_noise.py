"""UI-06 (client, 2026-09-09): the equivalence block must not shout.

The client's report:

    *"The Submission Integrity section lists a very long 'Coverage terms'
    equivalence string and later repeats normalization conclusions that were
    already resolved above. This adds visual noise and can make users think
    there is still an unresolved coverage problem."*

Acceptance criteria, verbatim:

    *"Keep the concise normalization outcome and remove the verbose duplicate
    coverage-term dump. If detailed normalized values are needed for
    auditability, place them behind an expandable details control rather than
    in the primary review flow."*

The fix is display-only and lives entirely in `AcordModal.renderIntegrityStatus`
/ `NormalizationDiffRow`. Nothing about extraction, scoring, capping or the
`normalized_differences` payload moves, and these tests pin that as hard as they
pin the rendering.

WHY THE THRESHOLD IS ON LENGTH AND NOT ON THE COVERAGE FIELD
------------------------------------------------------------
The reported row is `lines_of_business`, but the defect is that the card prints
every raw printing of every fact inline, at any length. A package with four
documents and long addresses produces the same wall. So the component collapses
ANY row over `NORMALIZATION_INLINE_MAX_CHARS` and there is no field name in the
logic at all - `test_the_collapse_rule_names_no_field` fails the build if one
appears. That is the class, not the case.

WHY THESE TESTS READ THE JSX
----------------------------
There is no frontend test runner in this repo, and the standing lesson from
`fix-the-layer-the-screen-reads` is that a fix in the wrong layer passes every
backend test and changes nothing on screen. The backend half is driven for
real; the component is asserted from source.
"""
from __future__ import annotations

import io
import os
import re

import pytest

from services.sqs_service import (
    check_doc_consistency,
    split_doc_consistency_issues,
    parse_normalization_notice,
)

HERE = os.path.dirname(os.path.abspath(__file__))
ACORD_MODAL = os.path.join(
    HERE, "..", "..", "frontend", "src", "components", "form", "AcordModal.jsx")


def _jsx() -> str:
    return io.open(ACORD_MODAL, encoding="utf-8").read()


# ── The fixture: the live UI-06 kit, same values as the PDFs ─────────────────
# backend/scripts/make_ui06_test_pdfs.py writes these two documents. A failure
# here and a failure on the live run are the same failure.

_LINES_DEC = [
    "Commercial General Liability", "Commercial Property",
    "Commercial Automobile Liability", "Commercial Umbrella Liability",
    "Workers Compensation And Employers Liability", "Commercial Crime",
    "Commercial Inland Marine", "Cyber Liability",
    "Employment Practices Liability", "Equipment Breakdown", "Liquor Liability",
]
_LINES_COI = [
    "General Liability", "Property", "Automobile Liability",
    "Umbrella Liability", "Workers Compensation", "Crime", "Inland Marine",
    "Cyber", "EPLI", "Boiler And Machinery", "Liquor Legal Liability",
]

DEC_FACTS = {
    "applicant_name":    "Marisol Freight & Cold Storage, LLC",
    "entity_type":       "Limited Liability Company",
    "mailing_address":   "4820 Harborgate Way, Suite 260, Tacoma, WA 98421",
    "physical_address":  "1140 Terminal Court, Suite 3, Kent, WA 98032",
    "fein":              "47-6120933",
    "effective_date":    "10/09/2026",
    "expiration_date":   "10/09/2027",
    "lines_of_business": list(_LINES_DEC),
}
COI_FACTS = {
    "applicant_name":    "MARISOL FREIGHT AND COLD STORAGE, L.L.C.",
    "entity_type":       "LLC",
    "mailing_address":   "4820 Harborgate Way Ste 260, Tacoma, Washington 98421",
    "physical_address":  "1140 Terminal Ct Ste 3, Kent, Washington 98032",
    "fein":              "476120933",
    "effective_date":    "10/9/26",
    "expiration_date":   "10/9/27",
    "lines_of_business": list(_LINES_COI),
}


def _docs():
    return [
        {"doc_id": "1", "filename": "UI06_dec_page.pdf",
         "doc_type": "declarations_page", "facts": dict(DEC_FACTS), "text": ""},
        {"doc_id": "2", "filename": "UI06_certificate.pdf",
         "doc_type": "certificate", "facts": dict(COI_FACTS), "text": ""},
    ]


def _rows():
    return [parse_normalization_notice(i)
            for i in check_doc_consistency(_docs()) if i.startswith("[info]")]


# ── 1. The reported defect is real, and this fixture reproduces it ───────────

def test_the_fixture_reproduces_the_clients_wall_of_text():
    """C25: an empty harvest would make every assertion below pass vacuously."""
    rows = _rows()
    assert len(rows) >= 6, (
        "the UI-06 fixture stopped producing equivalence notices - these tests "
        "are now blind")
    coverage = [r for r in rows if r["field"] == "lines_of_business"]
    assert coverage, "no coverage-terms row - the reported case is not covered"
    joined = "  ·  ".join(coverage[0]["values"])
    assert len(joined) > 400, (
        "the coverage-terms row is no longer long enough to reproduce the "
        f"client's screenshot ({len(joined)} chars)")


def test_the_fixture_raises_no_hard_stop_or_warning():
    """UI-06 is noise on a CLEAN package. A blocker here is a fixture bug."""
    hard, soft, _info, _c = split_doc_consistency_issues(
        check_doc_consistency(_docs()))
    assert hard == []
    assert soft == []


# ── 2. Every row can be matched to its fact, or the dedup silently never fires ─

def test_every_row_carries_the_fact_key_the_dedup_needs():
    """The card drops a row whose `field` is an open Data Consistency conflict.

    A row with no `field` can never match, so the dedup would look applied and
    do nothing - the exact shape of the `_harvest_dec_index` failure.
    """
    missing = [r["code"] for r in _rows() if not r.get("field")]
    assert not missing, (
        "these [info] codes reach the card with no fact key, so the card can "
        f"never tell they are already open in Data Consistency: {missing}")


def test_the_coverage_row_names_the_coverage_fact():
    """`lob_normalized` -> `lines_of_business`, via _INFO_CODE_FACT_ALIASES."""
    row = parse_normalization_notice("[info] code=lob_normalized Coverage terms: a | b")
    assert row["field"] == "lines_of_business"
    assert row["category"] == "Coverage name"


# ── 3. The component collapses on LENGTH, for every field alike ──────────────

def _component() -> str:
    """The whole component, bounded by the next top-level declaration.

    Deliberately NOT a fixed character window: the first version sliced 3000
    chars and silently started cutting the expanded branch off the end the
    moment the component grew, so a test asserting the row still renders its
    values began failing for a reason that had nothing to do with the row.
    """
    src = _jsx()
    i = src.index("function NormalizationDiffRow")
    m = re.search(r"^(?:function|const|class) ", src[i + 10:], re.M)
    assert m, "could not find the end of NormalizationDiffRow"
    return src[i:i + 10 + m.start()]


def test_the_component_exists_and_is_what_the_card_renders():
    src = _jsx()
    assert "function NormalizationDiffRow" in src
    i = src.rindex("Resolved formatting difference")
    assert "NormalizationDiffRow" in src[i:i + 1200], (
        "the equivalence block is not rendering rows through the component, "
        "so nothing collapses")


def test_the_collapse_is_decided_by_length():
    body = _component()
    assert "NORMALIZATION_INLINE_MAX_CHARS" in body, (
        "the row no longer measures its own length - it will print the wall "
        "again")
    assert re.search(r"joined\.length\s*>\s*NORMALIZATION_INLINE_MAX_CHARS", body), (
        "the length test is not the rendered length of the values")


def test_the_threshold_is_about_one_line_wide():
    src = _jsx()
    m = re.search(r"const NORMALIZATION_INLINE_MAX_CHARS\s*=\s*(\d+)", src)
    assert m, "the threshold constant is gone"
    n = int(m.group(1))
    # Below ~80 it would collapse an ordinary address pair, which reads fine on
    # one line and is genuinely useful inline. Above ~400 the client's own row
    # stops collapsing. Either end is a regression, not a preference.
    assert 80 <= n <= 400, f"threshold {n} is outside a defensible range"


def test_the_collapse_rule_names_no_field():
    """The class, not the case.

    A `lines_of_business` / `Coverage terms` check inside the component would
    fix the client's screenshot and leave every other long row broken - the
    allow-list-tuned-to-the-fixture failure the change quality bar forbids.
    """
    body = _component()
    for token in ("lines_of_business", "coverage_lines", "Coverage terms",
                  "Coverage name", "lob"):
        assert token not in body, (
            f"NormalizationDiffRow special-cases {token!r} - the collapse must "
            "be decided by length alone, or the next long row regresses")


def test_a_short_row_is_untouched():
    """*"Keep the concise normalization outcome."* A date pair already IS one.

    The component must still render the values and the existing wording on any
    row under the threshold, so nothing that reads well today changes.
    """
    body = _component()
    assert "{joined}" in body, "the short path stopped printing its values"
    assert "- treated as equivalent" in body, (
        "the short path lost the wording every row has always carried")


def test_the_detail_is_expandable_and_never_dropped():
    """*"place them behind an expandable details control"* - behind, not gone."""
    body = _component()
    assert "useState" in body, "the control cannot open - it has no state"
    assert "aria-expanded" in body, (
        "there is no expandable control, so the values are simply hidden")
    assert "open &&" in body, "nothing renders when the row is expanded"
    assert "row.values.map" in body, (
        "expanding no longer prints every printing the server sent")
    # The component must never build a shortened string. Collapsed and
    # recoverable is the ask; truncated is not.
    assert "slice(0" not in body and "substring(" not in body, (
        "the row is truncating values - UI-06 asks for them to be collapsed "
        "and recoverable, never shortened")


def test_the_disclosure_matches_the_apps_own_chevron():
    """Owner, 2026-09-09: a dropdown, not a text link.

    CollapsibleSection is the established control on this screen. Reusing its
    glyph and rotation means a broker who has opened "Documents Processed"
    already knows what this row does; a second invention would not.
    """
    src = _jsx()
    body = _component()
    assert "▶" in body, "the row lost the app's disclosure chevron"
    assert 'rotate(90deg)' in body, "the chevron does not turn when open"
    # Same glyph the shared section header uses - not a lookalike.
    i = src.index("function CollapsibleSection")
    assert "▶" in src[i:i + 1500]
    assert "View details" not in body and "Hide details" not in body, (
        "the text link is back alongside the chevron - two controls for one "
        "action")


def test_a_short_row_offers_no_control_at_all():
    """Nothing is hidden on a short row, so nothing may suggest it is."""
    body = _component()
    i = body.index("if (!verbose)")
    short = body[i:i + 700]
    assert "aria-expanded" not in short and "▶" not in short, (
        "a row with nothing to reveal is drawing a disclosure control")


def test_the_toggle_is_a_button_that_cannot_submit():
    body = _component()
    assert 'type="button"' in body, (
        "the details toggle is not type=button, so it can submit an enclosing "
        "form on Enter")


# ── 4. The dedup: nothing is declared resolved AND asked about ───────────────

def test_the_card_drops_a_row_data_consistency_still_owns():
    src = _jsx()
    i = src.index("const normalizedRows")
    block = src[i:i + 600]
    assert "openConsistencyFields" in block, (
        "equivalence rows are not deduped against open Data Consistency "
        "conflicts - the card can say 'treated as equivalent' while the "
        "picker below asks for the same value")
    assert "r.field" in block, "the dedup has nothing to match on"


def test_the_chip_follows_the_rows_that_actually_render():
    """A 'Resolved formatting difference' chip over an empty block is the
    confusion this ticket is about."""
    src = _jsx()
    i = src.index('severity = st === "low"')
    block = src[i:i + 300]
    assert "normalizedRows.length" in block, (
        "the severity chip still counts the raw payload, so it can label a "
        "section that was entirely deduped away")
    assert "normalizedDiffs.length" not in block


def test_the_block_renders_off_the_deduped_list():
    src = _jsx()
    assert "{normalizedRows.length > 0 && (" in src, (
        "the block visibility still reads the raw payload")


# ── 5. Nothing that was working moved ────────────────────────────────────────

def test_a_legacy_string_payload_still_renders():
    """A session open across a deploy keeps its block.

    The legacy shape has no fact key, so it must opt OUT of the dedup rather
    than be dropped by it.
    """
    src = _jsx()
    i = src.index("function normalizationRow")
    fn = src[i:i + 1400]
    assert 'typeof entry === "object"' in fn
    assert "String(entry" in fn
    assert 'field: ""' in fn, (
        "a legacy row has no fact key; without an explicit empty field it "
        "could match a conflict by accident and vanish")


def test_the_backend_payload_is_untouched():
    """Display-only. The row the server sends is the row it always sent."""
    row = parse_normalization_notice(
        "[info] code=effective_date_normalized Effective date: 10/9/26 | 10/09/2026")
    assert row["message"] == "Effective date: 10/9/26 | 10/09/2026"
    assert row["values"] == ["10/9/26", "10/09/2026"]
    assert set(row) == {"code", "field", "label", "values", "category", "message"}


def test_no_scoring_path_reads_the_render_threshold():
    """The threshold is a rendering constant. If any Python ever grows one, the
    display fix has leaked into the score."""
    backend = os.path.join(HERE, "..")
    for root, dirs, files in os.walk(backend):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", "tests", "tmp")]
        for fn in files:
            if not fn.endswith(".py"):
                continue
            text = io.open(os.path.join(root, fn), encoding="utf-8",
                           errors="ignore").read()
            assert "NORMALIZATION_INLINE_MAX_CHARS" not in text, (
                f"{fn} reads a frontend rendering threshold")


@pytest.mark.parametrize("field,expected_len", [
    ("effective_date", 2),
    ("lines_of_business", 2),
])
def test_the_server_still_sends_every_printing(field, expected_len):
    """Collapsing is a browser decision. The server must keep sending them all
    or 'View details' has nothing to show."""
    row = next(r for r in _rows() if r["field"] == field)
    assert len(row["values"]) == expected_len
