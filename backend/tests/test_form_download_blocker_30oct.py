"""Owner, 30 Oct 2026: "forms score is 100 but there are stops". A form whose own
download blocker is open (a required-gate box empty, or a placeholder value) is held
at 60 like any hard stop, and says why."""
from services.sqs_service import _form_download_blocker


def test_empty_gate_box_blocks_and_names_itself():
    r = _form_download_blocker("ACORD_140", {"Construction_ConstructionCode_A": ""},
                               {"Construction_ConstructionCode_A": "missing_required_gate"})
    assert r and "required before download" in r and r.startswith("ACORD 140")


def test_filled_gate_box_does_not_block():
    assert _form_download_blocker("ACORD_140", {"Construction_ConstructionCode_A": "Joisted Masonry"},
                                  {"Construction_ConstructionCode_A": "missing_required_gate"}) is None


def test_no_gate_no_block_and_bad_input_never_raises():
    assert _form_download_blocker("ACORD_125", {"X_A": "value"}, {"X_A": "ai_verified"}) is None
    assert _form_download_blocker("ACORD_125", None, None) is None
    assert _form_download_blocker(None, "junk", 5) is None


# ── What holds a form at 85 (owner, 30 Oct 2026) ─────────────────────────────
from services.sqs_service import _form_open_warning


def test_a_cross_form_check_naming_the_form_holds_it():
    cross = [{"type": "soft_warning", "message": "GL limits differ", "forms": ["ACORD_125", "ACORD_131"]}]
    assert _form_open_warning("ACORD_125", {}, {}, {}, {}, {}, cross) == "GL limits differ"
    # another form's check, an advisory note, or a check naming no form never holds it
    assert _form_open_warning("ACORD_126", {}, {}, {}, {}, {}, cross) is None
    adv = [{"type": "advisory", "message": "note", "forms": ["ACORD_125"]}]
    assert _form_open_warning("ACORD_125", {}, {}, {}, {}, {}, adv) is None
    assert _form_open_warning("ACORD_125", {}, {}, {}, {}, {}, [{"type": "hard_stop", "message": "x"}]) is None


def test_a_second_copy_of_a_form_is_held_by_its_base_forms_check():
    cross = [{"type": "soft_warning", "message": "umbrella", "forms": ["ACORD_131"]}]
    assert _form_open_warning("ACORD_131__excess", {}, {}, {}, {}, {}, cross) == "umbrella"


def test_bad_input_never_raises():
    assert _form_open_warning(None, None, None, None, None, None, None) is None
    assert _form_open_warning("ACORD_125", "junk", 5, [], None, None, [None, 3]) is None


def test_acord101_scores_the_form_it_continues_not_a_phantom_fact():
    """Live c5675766: every ACORD 101 stopped at 87 - its checks read
    `form_reference`, which nothing writes. Now the forms its boxes print."""
    from services import sqs_service as S
    long = "The insured operates a mechanical contracting business. " * 6
    facts = {"applicant_name": "Ridgeline", "effective_date": "12/01/2026",
             "additional_remarks_text": {"value": long, "source": "producer"},
             "operations_description": "HVAC contractor"}
    assert S._acord101_names_its_form({"form_reference": "ACORD 125"})
    import services.pdf_service as P
    orig = P.acord101_attached_forms
    try:
        P.acord101_attached_forms = lambda f: ["ACORD_125"]
        assert S._acord101_names_its_form(facts)
        P.acord101_attached_forms = lambda f: []
        assert not S._acord101_names_its_form(facts)
    finally:
        P.acord101_attached_forms = orig
