"""ACORD 126 / 127 per-form Exposure read their facts through the one readers
(14 Oct 2026, live run f83757cf: 126 Exposure 60 and 127 Exposure 80 on a package
whose GL limits, GL code and auto radius were all known). Per-form only - the
package score never reads these blocks (D29)."""
import json
import os

from services.sqs_service import calculate_sqs

HERE = os.path.dirname(os.path.abspath(__file__))


def _schema(fid):
    with open(os.path.join(HERE, "..", "forms_schemas", f"{fid}_schema.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _exposure(fid, facts, flags):
    r = calculate_sqs(facts, flags, {}, _schema(fid), [fid], [], [], 100, form_id=fid, _simulate=True)
    return r["breakdown"]["exposure_consistency"]


BASE_GL = {"operations_description": "Commercial electrical contracting", "total_payroll": "$2,626,500",
           "gl_each_occurrence": "$1,000,000", "gl_aggregate": "$2,000,000"}


def test_126_counts_a_typed_code_a_schedule_and_split_limits():
    flags = {"has_general_liability": True}
    typed = {**BASE_GL, "gl_class_codes_by_location": {"value": "92478", "source": "producer"}}
    sched = {**BASE_GL, "gl_class_code_schedule": [{"location": "1", "class_code": "92478", "classification": "Electrical",
                                                     "premium_basis": "Payroll", "exposure_amount": "$500,000"}]}
    listed = {**BASE_GL, "gl_class_codes_by_location": [{"location": "1", "codes": ["92478"]}]}
    assert _exposure("ACORD_126", typed, flags) == _exposure("ACORD_126", sched, flags) == _exposure("ACORD_126", listed, flags) == 100


def test_126_still_deducts_when_no_code_exists():
    assert _exposure("ACORD_126", dict(BASE_GL), {"has_general_liability": True}) < 100


def test_127_reads_the_radius_through_the_one_reader():
    from services.coverage_evidence import auto_radius_known
    facts = {"auto_liability_limit": "$1,000,000", "auto_liability_structure": "combined single limit",
             "auto_covered_symbols": [{"coverage": "liability", "symbols": [1]}],
             "auto_vin_schedule": [{"vin": "1FTFW1E50MFA00001", "year": "2021", "make": "Ford"}],
             "auto_radius_of_operation": "50 miles"}
    assert auto_radius_known(facts)
    assert _exposure("ACORD_127", facts, {"has_auto_coverage": True}) == 100
