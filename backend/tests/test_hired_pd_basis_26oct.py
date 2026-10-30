"""26 Oct 2026 (P15 X1): ACORD 137's hired physical damage PRIMARY / EXCESS tick
is ticked by the AI only when a document puts that word beside "hired"."""
import json
from pathlib import Path

from services.ai_answer_guards import refuse_non_answers

_SCHEMA = json.loads(Path(__file__).resolve().parents[1].joinpath(
    "forms_schemas", "ACORD_137_CO_schema.json").read_text(encoding="utf-8"))
BOX = "Vehicle_HiredPhysicalDamage_PrimaryIndicator_A"
DEC = "HIRED AUTO PHYSICAL DAMAGE  ACV LESS DEDUCTIBLE  COMP $1,000  COLL $1,000"


def _run(text):
    mapped = {BOX: "Yes"}
    out = refuse_non_answers(mapped, _SCHEMA, {}, text, {BOX}, "ACORD_137_CO")
    return out, mapped


def test_a_primary_tick_no_document_states_is_refused():
    out, mapped = _run(DEC)
    assert BOX in out and mapped[BOX] is None


def test_a_primary_tick_the_dec_states_stands():
    out, mapped = _run(DEC + "\nHired physical damage coverage is primary.")
    assert BOX not in out and mapped[BOX] == "Yes"


def test_no_documents_means_no_judgement():
    out, mapped = _run("")
    assert out == {} and mapped[BOX] == "Yes"


def test_primary_said_of_hired_liability_is_not_evidence():
    # live 6c420291: the dec's hired LIABILITY row says "primary"; physical damage says nothing
    text = ("CO OTHER THAN PUBLIC TRANSPORTATION - HIRED AUTOS - LIABILITY - INSURED PROVIDING PRIMARY INSURANCE 1,000,000 93\n"
            "CO WITH DRIVERS - COMPREHENSIVE - HIRED AUTOS - PHYSICAL DAMAGE  ACV  $1,000")
    out, mapped = _run(text)
    assert BOX in out and mapped[BOX] is None
    out2, _ = _run(text + "\nHIRED AUTOS PHYSICAL DAMAGE - COLLISION - PRIMARY")
    assert BOX not in out2
