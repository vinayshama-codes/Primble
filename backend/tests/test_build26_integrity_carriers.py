"""Submission Integrity's carrier advisory = two carriers on ONE line (24 Oct 2026).

Choice Electric: the EPL dec was read with no coverage line, so its carrier had
no line slot and was compared with every line - a false "Multiple carriers
referenced" advisory on a package where each carrier writes its own line. An
unplaced carrier is never a clash; two carriers on one line still are.
"""
from services.submission_integrity import assess_submission_integrity

_NAME = "Choice Electric LLC"
_ADDR = "100 Main St, Denver, CO 80216"


def _doc(doc_id, carrier, lines=None):
    facts = {
        "applicant_name": {"value": _NAME, "confidence": 0.9},
        "mailing_address": {"value": _ADDR, "confidence": 0.9},
        "carrier_name": {"value": carrier, "confidence": 0.9},
    }
    if lines is not None:
        facts["coverage_lines"] = {"value": [
            {"line": ln, "carrier": carrier} for ln in lines], "confidence": 0.9}
    return {"doc_id": doc_id, "filename": f"{doc_id}.pdf",
            "doc_type": "declarations_page", "facts": facts}


def _carrier_reason(docs):
    v = assess_submission_integrity(docs)
    return [r for r in v.get("reasons", []) if "carrier" in r.lower()]


def test_epl_dec_with_no_line_beside_carriers_on_their_own_lines_is_quiet():
    docs = [
        _doc("pkg", "Amerisure Insurance Company", ["General Liability", "Commercial Property"]),
        _doc("auto", "Travelers Property Casualty", ["Business Auto"]),
        _doc("wc", "Pinnacol Assurance", ["Workers Compensation"]),
        _doc("cyber", "ACE American Insurance Company", ["Cyber Liability"]),
        _doc("epl", "Federal Insurance Company"),           # no coverage line read
    ]
    assert _carrier_reason(docs) == []


def test_two_carriers_on_one_line_still_warn():
    docs = [
        _doc("gl1", "Amerisure Insurance Company", ["General Liability"]),
        _doc("gl2", "Travelers Property Casualty", ["General Liability"]),
    ]
    assert _carrier_reason(docs) == ["Multiple carriers referenced across documents"]


def test_unplaceable_carriers_with_no_signals_are_quiet():
    docs = [
        _doc("a", "Amerisure Insurance Company"),
        _doc("b", "Federal Insurance Company"),
    ]
    assert _carrier_reason(docs) == []


def _with_policy(doc, number):
    doc["facts"]["policy_number"] = {"value": number, "confidence": 0.9}
    return doc


def test_unplaced_carriers_on_one_policy_number_still_warn():
    """Review fix (24 Oct 2026): two documents printing the SAME policy number
    are one contract - two different carriers on it is a real clash even when
    neither document's coverage line was read."""
    docs = [
        _with_policy(_doc("dec", "Amerisure Insurance Company"), "CPP 2041187"),
        _with_policy(_doc("binder", "Federal Insurance Company"), "CPP-2041187"),
    ]
    assert _carrier_reason(docs) == ["Multiple carriers referenced across documents"]
    # Different policy numbers stay quiet (different contracts).
    docs[1]["facts"]["policy_number"]["value"] = "EPL 99-1"
    assert _carrier_reason(docs) == []
    # The same carrier on one policy number is no clash.
    docs[1]["facts"]["carrier_name"]["value"] = "Amerisure Insurance Company"
    docs[1]["facts"]["policy_number"]["value"] = "CPP 2041187"
    assert _carrier_reason(docs) == []
