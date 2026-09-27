"""The ACORD 125 baseline warnings must survive a recompute (2026-09-23).

REPORTED LIVE. A producer uploaded one declarations page and saw three warnings
under a banner reading "Caps your Submission Quality Score (SQS) at 85":

    ACORD 125 minimum field missing: Proposed effective date
    ACORD 125 minimum field missing: Contact information
    Driver schedule not provided - ...

They resolved the effective date. BOTH ACORD 125 rows disappeared. Their session
afterwards:

    effective_date : 07/15/2027      <- the fix landed
    contact_name   : None
    contact_phone  : None            <- never filled
    contact_email  : None
    check_tier1    : still missing ['Contact information']

Three defects in one, all from the rule living in `routes/form_routes.py` on the
UPLOAD RESPONSE instead of in an engine:

  1. It appended to a LOCAL `soft_stops` that was returned and never persisted,
     so the sentences were absent from the array `_resolve_cap` reads. The
     stored session showed `soft_stops` length 1 (the driver warning alone)
     while the screen showed three items claiming to cap the score.
  2. `evaluate_stops` never emitted them, and EVERY recompute path rebuilds the
     stop lists from `evaluate_stops` + doc-consistency + cross-form. So the
     first Resolve / Dismiss / answer / field edit dropped all of them - the
     fixed one and the unfixed one identically.
  3. Nothing re-raised them afterwards, so a real Tier 1 gap went silent while
     still costing 20 points of the Tier 1 component inside Structural.

The rule now lives in `sqs_service.evaluate_stops`, the engine every recompute
runs, so it persists, re-derives from the facts, and disappears only when the
field is actually answered.
"""
import pytest

from services.sqs_service import evaluate_stops, check_tier1, TIER1_CONTACT
from services.issue_registry import classify_legacy, _legacy_message_resolution

_PREFIX = "ACORD 125 minimum field missing:"


def _F(v):
    return {"value": v, "confidence": "filled", "source": "producer"}


# Everything Tier 1 asks for EXCEPT contact information - the live shape.
_ALL_BUT_CONTACT = {
    "producer_name": _F("Midwest Agency"),
    "applicant_name": _F("ACME LLC"),
    "mailing_address": _F("123 Main St, Detroit, MI 48226"),
    "effective_date": _F("07/15/2027"),
    "lines_of_business": _F(["General Liability"]),
    "entity_type": _F("LLC"),
}


def _tier1_msgs(facts, flags=None):
    _hard, soft = evaluate_stops(facts, flags or {})
    return [m for m in soft if m.startswith(_PREFIX)]


def test_the_engine_emits_them_so_every_recompute_keeps_them():
    """THE DEFECT. The sentences must come from evaluate_stops, because that is
    what every recompute path re-runs."""
    msgs = _tier1_msgs(_ALL_BUT_CONTACT)
    assert any("Contact information" in m for m in msgs), (
        "the Tier 1 gap is not emitted by the stop engine - it will vanish on "
        "the first recompute exactly as it did live"
    )


def test_resolving_one_item_does_not_silence_another():
    """The live sequence: the effective date was fixed, contact was not."""
    no_date = {k: v for k, v in _ALL_BUT_CONTACT.items() if k != "effective_date"}
    before = _tier1_msgs(no_date)
    assert any("Proposed effective date" in m for m in before)
    assert any("Contact information" in m for m in before)

    after = _tier1_msgs(_ALL_BUT_CONTACT)          # date now supplied
    assert not any("Proposed effective date" in m for m in after), \
        "the item that WAS fixed must clear"
    assert any("Contact information" in m for m in after), \
        "the item that was NOT fixed must survive - this is the reported bug"


@pytest.mark.parametrize("key", TIER1_CONTACT)
def test_any_one_contact_method_clears_it(key):
    """Client 9.1: any one contact method satisfies Tier 1. Whichever the
    producer fills must actually clear the warning - a rule that cannot be
    satisfied by its own declared fix is the class of defect this work closed."""
    facts = dict(_ALL_BUT_CONTACT)
    facts[key] = _F({"contact_name": "Jordan Reyes",
                     "contact_phone": "2485551212",
                     "contact_email": "jordan@acme.example"}[key])
    assert not _tier1_msgs(facts), f"filling {key} did not clear the Tier 1 gap"
    assert check_tier1(facts, {})[0] is True


def test_a_complete_baseline_emits_nothing():
    facts = dict(_ALL_BUT_CONTACT, contact_email=_F("jordan@acme.example"))
    assert _tier1_msgs(facts) == []


def test_each_row_carries_its_own_fix():
    """Every sentence must arrive with the fact(s) that clear it, whichever door
    it reaches the display through. The safety-net (message) route is the one
    that had no answer for a dynamically-coded rule."""
    for label, expected in (
        ("Proposed effective date", ["effective_date"]),
        ("Contact information", list(TIER1_CONTACT)),
        ("Business entity type", ["entity_type"]),
    ):
        msg = (f"{_PREFIX} {label} (Fix: Provide this value manually, or "
               "upload a document that states it.)")
        code, cluster, _tier = classify_legacy(msg, "soft_warning")
        assert code == f"tier1_missing_{label}"
        assert cluster == "Missing baseline ACORD 125 fields"
        res = _legacy_message_resolution(msg)
        assert res and res["mode"] == "field"
        assert res["facts"] == expected


def test_there_is_exactly_one_emitter():
    """ANTI-ROT. The bug was a second copy in a ROUTE, invisible to every test
    that drove the engine. A route emitting this sentence again must fail."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent
    offenders = []
    for path in sorted((root / "routes").glob("*.py")) + \
            sorted((root / "services").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#") or _PREFIX not in line:
                continue
            # sqs_service emits it; issue_registry parses it. Anything else is
            # a second copy.
            if path.name not in ("sqs_service.py", "issue_registry.py"):
                offenders.append(f"{path.name}:{i}")
    assert not offenders, (
        f"a second emitter of the Tier 1 baseline warning is back: {offenders} - "
        "it belongs in sqs_service.evaluate_stops so every recompute keeps it"
    )
