"""The review's main button walks its pages (Choice Electric #2; owner, 9 Oct 2026).

Brent: "Make buttons reactive to section state ... move the user through to the
subsequent section. Making the form selection button the final in the sequence."
The owner added: keep form selection one click away on every other page. So,
before forms, the rail footer's main button reads "Continue to <next page>" and
opens it, with "Skip to form selection" beside it - sized and coloured like the
form-selection screen's "Back to review" (owner, 9 Oct: the same row, the same
solid pink); the last page (Recommendations) has the one button "Continue to
form selection". Once forms exist or are being generated nothing changes: one
button, "Continue where you left off", on every page.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_FRONT = Path(__file__).resolve().parents[2] / "frontend" / "src"
_PG = _FRONT / "utils" / "packageGeneration.js"
_RAIL = _FRONT / "components" / "form" / "review" / "ReviewRailLayout.jsx"
_CSS = _FRONT / "components" / "form" / "review" / "ReviewRailLayout.css"
_MODAL = _FRONT / "components" / "form" / "AcordModal.jsx"
_APP_CSS = _FRONT / "App.css"

_PAGES = ["overview", "documents", "integrity", "consistency", "hardstops", "warnings", "recommendations"]


def _rail_sections():
    """The rail's SECTIONS list as the component declares it: ids and labels, in order."""
    src = _RAIL.read_text(encoding="utf-8")
    block = src[src.index("const SECTIONS = ["):]
    block = block[:block.index("];")]
    return [{"id": i, "label": l} for i, l in re.findall(r'\{ id: "([^"]+)", label: "([^"]+)"', block)]


def _node(tmp_path, body):
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    script = tmp_path / "check.mjs"
    script.write_text(
        f"import * as P from {json.dumps(_PG.as_uri())};\n"
        f"const SECTIONS = {json.dumps(_rail_sections())};\n"
        f"{body}\n",
        encoding="utf-8",
    )
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


# ── The sequence ─────────────────────────────────────────────────────────────
def test_the_rail_walks_seven_pages_in_this_order():
    assert [s["id"] for s in _rail_sections()] == _PAGES


@pytest.mark.parametrize("state", ["none", "interrupted"])
def test_each_page_names_the_next_and_the_last_goes_to_form_selection(tmp_path, state):
    out = _node(tmp_path, f"""
const st = {json.dumps(state)};
console.log(JSON.stringify({{
  steps: SECTIONS.map((s) => P.nextReviewStep(SECTIONS, s.id, st)),
  last: P.continueLabel(st),
  skip: P.SKIP_TO_SELECTION,
}}));
""")
    assert out["steps"] == [
        {"id": "documents", "label": "Continue to Documents"},
        {"id": "integrity", "label": "Continue to Submission Integrity"},
        {"id": "consistency", "label": "Continue to Data Consistency"},
        {"id": "hardstops", "label": "Continue to Hard Stops"},
        {"id": "warnings", "label": "Continue to Warnings"},
        {"id": "recommendations", "label": "Continue to Recommendations"},
        None,                                   # the last page: the one continue button
    ]
    # A run that did not finish is generated again from form selection.
    assert out["last"] == "Continue to form selection"
    assert out["skip"] == "Skip to form selection"


@pytest.mark.parametrize("state", ["done", "running"])
def test_once_forms_exist_every_page_keeps_its_one_button(tmp_path, state):
    out = _node(tmp_path, f"""
const st = {json.dumps(state)};
console.log(JSON.stringify({{
  steps: SECTIONS.map((s) => P.nextReviewStep(SECTIONS, s.id, st)),
  label: P.continueLabel(st),
}}));
""")
    assert out["steps"] == [None] * 7
    assert out["label"] == "Continue where you left off"


def test_odd_input_falls_back_to_the_continue_button(tmp_path):
    out = _node(tmp_path, """
console.log(JSON.stringify([
  P.nextReviewStep(SECTIONS, "policies", "none"),          // a page the list does not hold
  P.nextReviewStep(SECTIONS, undefined, "none"),
  P.nextReviewStep([], "overview", "none"),
  P.nextReviewStep(null, "overview", "none"),
  P.nextReviewStep([{ id: "a", label: "A" }], "a", "none"),           // one page = the last page
  P.nextReviewStep([{ id: "a", label: "A" }, { id: "b" }], "a", "none"),  // no label to print
  P.nextReviewStep([null, { id: "a", label: "A" }, { id: "b", label: "B" }], "a", undefined),
]));
""")
    assert out == [None, None, None, None, None, None, {"id": "b", "label": "Continue to B"}]


# ── The footer ───────────────────────────────────────────────────────────────
def test_the_footer_offers_skip_beside_every_step_and_one_button_otherwise():
    rail = _RAIL.read_text(encoding="utf-8")
    assert "const step = nextReviewStep(SECTIONS, section, genState);" in rail
    foot = rail[rail.index('<div className="rr-footer"'):]
    skip = foot.index("{step && (")
    main = foot.index('className="btn btn-modal-primary btn-large step-footer-primary rr-footer__next"')
    # The skip slot comes first (left), so the main button keeps its place and focus.
    assert skip < main
    # The skip goes to form selection, and only inside the {step && (...)} slot.
    assert re.search(r'className="btn btn-modal-primary step-footer-back rr-footer__skip"\s+'
                     r'onClick=\{\(e\) => \{ if \(e\.detail > 1\) return; onContinue\(\); \}\}>\s*'
                     r'\{SKIP_TO_SELECTION\}', foot[skip:main])
    # The main button opens the next page, or continues on the last one - one page
    # per press: the second click of a double-click (detail 2) is ignored, so it can
    # never land on the next page's button (from Warnings: leave the review).
    assert ("onClick={(e) => { if (e.detail > 1) return; if (step) onSectionChange(step.id); "
            "else onContinue(); }}>") in foot
    assert "{step ? <>{step.label}<ArrowIcon /></> : continueLabel(genState)}" in foot
    # The note above the buttons is unchanged: open items never block either button.
    assert "your input. You can continue and come back." in foot
    assert "disabled" not in foot[skip:]


def test_the_skip_is_the_form_selection_back_buttons_twin():
    # Owner, 9 Oct: the same length and colour as "Back to review" on the form
    # selection screen - so the same row and the same button classes, and the
    # rail's own CSS sets neither size nor colour for it.
    modal = _MODAL.read_text(encoding="utf-8")
    back = modal[modal.index('<div className="step-footer-buttons">'):]
    back = back[:back.index("Back to review")]
    assert 'className="btn btn-modal-primary step-footer-back"' in back
    assert 'className="btn btn-modal-primary btn-large step-footer-primary"' in modal
    rail = _RAIL.read_text(encoding="utf-8")
    assert '<div className="step-footer-buttons rr-footer__buttons">' in rail
    assert 'className="btn btn-modal-primary step-footer-back rr-footer__skip"' in rail
    app = _APP_CSS.read_text(encoding="utf-8")
    # Owner, 9 Oct: exactly the same width on both screens - one fixed width for the
    # row's smaller button, wide enough for "Skip to form selection" (the longer label).
    # Its words never spill out (text-only zoom, a minimum font size, a page
    # translation): it grows to fit them, and stays 212px at normal size.
    assert (".step-footer-buttons .step-footer-back { flex: 0 0 auto; white-space: nowrap; width: 212px; "
            "min-width: max-content; padding-left: 16px; padding-right: 16px; }") in app
    assert ".step-footer-buttons .step-footer-primary { flex: 1 1 auto; min-width: 0; }" in app
    # The review page's own CSS never sizes or colours the skip outside its narrow
    # (stacked) mode, under ANY selector - so the two cannot drift apart.
    css = _CSS.read_text(encoding="utf-8")
    narrow = css.index("@container (max-width: 600px) {\n  .rr-footer__buttons")
    outside = css[:narrow] + css[css.index("\n}\n", narrow) + 3:]
    for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", outside):
        # (A :hover rule is a state, not the resting size or colour - the touch-screen
        # rule only puts the resting look back.)
        if ":hover" in selector:
            continue
        if re.search(r"step-footer-back|rr-footer__skip|rr-footer__buttons\s+(?:button|\.btn)(?![-\w])", selector):
            assert not re.search(r"(?:^|;)\s*(?:width|min-width|max-width|flex|padding|font-size|background|"
                                 r"border|color)\s*:", body), selector.strip()


def test_the_footer_row_stacks_as_soon_as_both_no_longer_fit():
    css = _CSS.read_text(encoding="utf-8")
    inner = css[css.index(".rr-footer__inner {"):]
    assert "container-type: inline-size;" in inner[:inner.index("}")]
    # The main labels are longer than "Generate N Forms Now": the row stacks (the
    # main button on top, as the form-selection screen does on a phone) whenever
    # the footer itself is under 600px, and the stacked skip is full width again.
    assert ("@container (max-width: 600px) {\n  .rr-footer__buttons { flex-direction: column-reverse; }\n"
            "  .rr-footer__buttons.step-footer-buttons .step-footer-back { width: auto; }\n}") in css


def test_the_form_selection_row_stacks_before_generate_wraps():
    # With "Back to review" at 212px, "Generate 12 Forms Now" wraps just above
    # 480px (measured: 225px wraps, 234px fits), so the row stacks from 520px,
    # full width again, Generate on top.
    app = _APP_CSS.read_text(encoding="utf-8")
    block = app[app.index("@media (max-width: 520px) {"):]
    block = block[:block.index("\n}\n")]
    assert "flex-direction: column-reverse;" in block
    assert ".step-footer-buttons .step-footer-back { flex: 1 1 auto; width: auto; }" in block
    for at in re.finditer(r"@media \(max-width: 480px\) \{", app):
        block480 = app[at.start():app.index("\n}\n", at.start())]
        assert "step-footer-buttons" not in block480        # the stacking moved to 520px


def test_no_em_dashes_in_the_new_wording():
    for path in (_PG, _RAIL):
        assert "—" not in path.read_text(encoding="utf-8")
