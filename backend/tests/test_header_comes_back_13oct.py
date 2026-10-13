"""The navbar never came back (owner, 13 Oct 2026: "i refreshed and opened the same session and then
i m scrolling up and down but i cant see the navbar" - a blank band where the header was).

Two measuring defects in the header's auto-hide: an element's FIRST scroll was measured from 0 (a
refreshed page restores its position, so the first move - even upward - read as a huge downward
scroll and hid the header), and the header came back only on ONE upward step of more than 40px,
which a trackpad's many small steps never reach. `utils/headerAutoHide.js` is the pure rule.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

_FRONT = Path(__file__).resolve().parents[2] / "frontend" / "src"


def _run(tmp_path, body):
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    script = tmp_path / "check.mjs"
    script.write_text(f"import * as H from {json.dumps((_FRONT / 'utils' / 'headerAutoHide.js').as_uri())};\n"
                      + body + "\n", encoding="utf-8")
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


# Feed a sequence of scroll positions for one element; return the hidden flag after each.
_DRIVE = """
function drive(ys, start = false) {
  const a = H.createHeaderAutoHide(); const el = {}; let hidden = start; const out = [];
  for (const y of ys) { const n = a.step(el, y, hidden); if (n !== null) hidden = n; out.push(hidden); }
  return out;
}
"""


def test_a_refreshed_page_does_not_hide_the_header_on_its_first_scroll(tmp_path):
    out = _run(tmp_path, _DRIVE + "console.log(JSON.stringify(drive([600, 592, 584, 576])));")
    assert out == [False, False, False, False]


def test_small_upward_steps_add_up_and_bring_it_back(tmp_path):
    # down past 80 (hides), then a trackpad's 8px steps upward - never one 40px jump
    ys = [0, 50, 120, 200] + [200 - 8 * i for i in range(1, 9)]
    out = _run(tmp_path, _DRIVE + f"console.log(JSON.stringify(drive({ys})));")
    assert out[3] is True                      # hidden after scrolling down
    assert out[-1] is False                    # back after 48px of small steps
    assert out[4:8] == [True, True, True, True]  # not on jitter


def test_the_top_of_the_page_always_shows_it(tmp_path):
    out = _run(tmp_path, _DRIVE + "console.log(JSON.stringify(drive([300, 310, 75], true)));")
    assert out[-1] is False


def test_a_downward_scroll_still_hides_and_jitter_does_not(tmp_path):
    out = _run(tmp_path, _DRIVE + "console.log(JSON.stringify([drive([0, 100, 200]), drive([200, 202, 199, 201])]));")
    assert out[0][-1] is True
    assert out[1] == [False, False, False, False]


def test_the_header_uses_the_rule_and_the_top_is_never_locked():
    src = (_FRONT / "components" / "layout" / "Header.jsx").read_text(encoding="utf-8")
    assert 'import { createHeaderAutoHide, HIDE_AFTER } from "../../utils/headerAutoHide";' in src
    assert "const shouldHide = autoHide.step(el, el.scrollTop, hiddenLocal);" in src
    assert "!(shouldHide === false && el.scrollTop <= HIDE_AFTER)" in src
    assert "autoHide.reset(el, el.scrollTop)" in src
    # the old per-step measure is gone
    assert "delta < -40" not in src and "?? 0" not in src[src.index("const handleScroll"):src.index("const handleReset")]


def test_no_box_breakdown_before_generation():
    """Owner, 13 Oct 2026: first "why is there numbering" (the counts read as a list), then
    "remove it" - nothing in it can be acted on before generation. The counts stay in the payload."""
    src = (_FRONT / "components" / "form" / "review" / "BeforeYouGenerate.jsx").read_text(encoding="utf-8")
    assert '"Why"} other boxes are not listed' not in src     # the button is gone
    assert "showWhy" not in src and "reasonText" not in src
    # the actionable red note about boxes blocking a clean download stays
    assert "Also needed for a clean download" in src


def test_a_window_or_dialog_never_moves_the_navbar():
    """Owner, 13 Oct 2026 (screenshot): a white band under the review footer. Scrolling inside the fix
    window (its own scroll box) hid AND collapsed the header; the window closed and nothing released it,
    so the page sat a header's height short of the screen's bottom."""
    src = (_FRONT / "components" / "layout" / "Header.jsx").read_text(encoding="utf-8")
    assert "[role=\"dialog\"], [aria-modal=\"true\"], .modal-overlay" in src
    assert "|| insideFixedLayer(t))) return;" in src
    assert 'window.getComputedStyle(n).position === "fixed"' in src
    fix = (_FRONT / "components" / "form" / "ResolutionModal.jsx").read_text(encoding="utf-8")
    assert 'role="dialog" aria-modal="true" data-header-autohide="off"' in fix
