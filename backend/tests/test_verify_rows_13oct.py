"""The editor's Please verify rows (owner, 13 Oct 2026, run `ba7c709d`).

1. "after generating form, i clicked on please verify's one item and every item starts showing
   confirming". The side panel kept ONE busy flag for the whole list, so a single Confirm put
   "Confirming..." on every row and on "Confirm all". Now the rows being saved are tracked by
   key: only they say "Confirming..."; the others wait (one save of a form at a time) but keep
   their own label, and "Confirm all" says "Confirming..." only when it is the save in flight.
2. "Page 1 ... should have 1 in the same line ... and Show on form in a single line, like a little
   button (not pill design), one above another". The footer's "Page N" and "Show on form" wrapped
   to "Page / 1" and "Show on / form"; they are now two small square-cornered labels, one line
   each, stacked at the row's right.
"""
from __future__ import annotations

from pathlib import Path

_PANEL = Path(__file__).resolve().parents[2] / "frontend" / "src" / "components" / "form" / "NeedsAttentionPanel.jsx"


def _panel() -> str:
    return _PANEL.read_text(encoding="utf-8")


def test_only_the_row_being_saved_says_confirming():
    src = _panel()
    assert "busy={confirming}" not in src                                  # the one shared flag is gone
    assert "const [confirmingKeys, setConfirmingKeys] = useState(() => new Set());" in src
    assert "busy={saving.has(rowKey(r))} locked={locked}" in src
    # the other rows wait but keep their own label
    assert "disabled={busy || locked}" in src
    assert '{busy ? "Confirming..." : "Confirm"}' in src
    # "Confirm all" says so only when it is the save in flight
    assert '{allSaving ? "Confirming..." : `Confirm all ${mine.length}`}' in src
    # still one save at a time
    assert "if (!picked.length || confirmingKeys.size > 0) return;" in src


def test_page_and_show_on_form_are_small_stacked_labels_on_one_line_each():
    src = _panel()
    chip = src[src.index("const rowChip = (pink) => ({"):src.index("});", src.index("const rowChip"))]
    assert 'whiteSpace: "nowrap"' in chip                                   # never "Page / 1"
    assert "borderRadius: 4" in chip                                        # a small button, not a pill
    assert '<span style={{ display: "flex", flexDirection: "column", alignItems: "stretch", gap: 3, flexShrink: 0 }}>' in src
    assert "<span style={rowChip(false)}>Page {row.page}</span>" in src
    assert "{clickable ? <span style={rowChip(true)}>Show on form</span> : null}" in src
    assert "—" not in src                                              # no em-dashes in UI text
