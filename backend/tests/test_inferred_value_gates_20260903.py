"""A document may not be read as stating something it does not say.

Two fixes, one root cause, both found by the SYS-05 live run (2026-09-03) rather
than by review. Neither touches an LLM prompt: a prompt is a request, and on a
signed application the guarantee has to be deterministic. That is the standing
lesson from H1-K, which built `_gate_inferred_payroll_period` after v16's prompt
already forbade the same thing "in terms" and was ignored anyway.

RUN 1 - the declarations page alone - correctly reported the building value as
MISSING and raised no valuation advisory. RUN 2 added a certificate whose
property row reads "Property - Special Form  $4,200,000", and the package came
back with:

    property_building_value = 4,200,000      <- a LIMIT read as a VALUE
    valuation_method        = ACV            <- named in neither document

"Special Form" is a CAUSE OF LOSS form (Basic / Broad / Special). It says
nothing about valuation, and a certificate says nothing about what the building
is worth - it evidences what the policy pays.

Both are Principle 3's forbidden move ("Missing Does Not Mean No") and CLAUDE.md's
documented GAP 1: `answer_semantics` guards what a HUMAN types, and until now
nothing guarded what the model extracts.
"""
import pytest

from services.coverage_evidence import valuation_method_corroborated
from services.extraction_service import _gate_inferred_valuation_method as gate
from services.fact_comparison import document_witnesses


# ── 1. The live defect ──────────────────────────────────────────────────────

_COI_TEXT = ("CERTIFICATE OF LIABILITY INSURANCE\n"
             "Property - Special Form  KM-CP-771655-26  $4,200,000\n")


def test_the_live_defect_a_cause_of_loss_form_is_not_a_valuation_method():
    """Must never fail. This is the run-2 package, verbatim in shape."""
    mf = {"valuation_method": {"value": "ACV", "source": "ai",
                               "confidence": "medium"}}
    gate(mf, [{"text": _COI_TEXT}])
    assert mf["valuation_method"] is None


@pytest.mark.parametrize("method,text", [
    ("ACV", "Buildings are valued at Actual Cash Value"),
    ("ACV", "Coverage is written on an ACV basis"),
    ("acv", "ACTUAL CASH VALUE"),
    ("RCV", "Replacement Cost valuation applies to all buildings"),
    ("RCV", "Building 1 ... RCV ... Building 2"),
    ("Agreed Amount", "Agreed Value endorsement attached"),
    ("Market Value", "Loss settlement: Market Value"),
])
def test_a_method_the_document_names_is_kept(method, text):
    mf = {"valuation_method": {"value": method, "source": "ai"}}
    gate(mf, [{"text": text}])
    assert mf["valuation_method"] is not None


# ── 2. Provenance decides (Principle 6) ─────────────────────────────────────

@pytest.mark.parametrize("source", ["producer", "client_arq", "client",
                                    "derived", "human"])
def test_a_human_or_derived_answer_is_never_gated(source):
    """A producer or client answer IS the named evidence; a derived value was
    computed from a corroborating label to begin with. Only the model's own
    inference is stripped."""
    mf = {"valuation_method": {"value": "ACV", "source": source}}
    gate(mf, [{"text": "no method appears anywhere in this document"}])
    assert mf["valuation_method"]["value"] == "ACV"


def test_a_bare_string_fact_is_gated_too():
    """Not every fact is wrapped in an envelope; the gate must read both."""
    mf = {"valuation_method": "ACV"}
    gate(mf, [{"text": "nothing names a valuation method"}])
    assert mf["valuation_method"] is None


# ── 3. Corroboration sources and the matching mechanism ────────────────────

def test_a_verified_dec_entry_corroborates_as_well_as_raw_text():
    mf = {"valuation_method": {"value": "RCV", "source": "ai"},
          "dec_page_entries": [{"label": "Valuation", "value": "Replacement Cost"}]}
    gate(mf, [{"text": ""}])
    assert mf["valuation_method"] is not None


def test_any_uploaded_document_may_carry_the_evidence():
    """The certificate is silent; the dec page names it. One package."""
    mf = {"valuation_method": {"value": "ACV", "source": "ai"}}
    gate(mf, [{"text": _COI_TEXT}, {"text": "Valuation: Actual Cash Value"}])
    assert mf["valuation_method"] is not None


@pytest.mark.parametrize("text", [
    "the vacvuum cleaner was damaged",     # 'acv' inside a word
    "preplacement costs were incurred",    # 'rcv' is not here at all
    "MACVILLE PROPERTIES LLC",             # 'acv' inside a proper noun
    "Special Form",                        # the live false positive
])
def test_abbreviations_match_whole_tokens_never_substrings(text):
    """Three-letter abbreviations are the D9 danger in miniature - "the danger
    was never the equivalence, it was the matching mechanism"."""
    assert valuation_method_corroborated("ACV", None, text) is False


def test_an_uninterpretable_method_gets_no_opinion():
    """The gate strips an INVENTED method; it does not police free text the
    scoring rules already ignore."""
    assert valuation_method_corroborated("", None, "x") is True
    assert valuation_method_corroborated(None, None, "x") is True
    assert valuation_method_corroborated("Functional Replacement", None, "x") is True


# ── 4. Never raises, never blocks the pipeline ─────────────────────────────

@pytest.mark.parametrize("mf", [
    {}, {"valuation_method": None}, {"valuation_method": ""},
    {"valuation_method": {"value": None}}, {"valuation_method": {}},
])
def test_absent_or_empty_is_untouched_and_safe(mf):
    before = dict(mf)
    gate(mf, None)
    assert mf == before or mf.get("valuation_method") in (None, "", {})


@pytest.mark.parametrize("docs", [None, [], [{}], [{"text": None}], "not a list"])
def test_unreadable_documents_never_raise(docs):
    mf = {"valuation_method": {"value": "ACV", "source": "ai"}}
    gate(mf, docs)                                   # must not raise


# ── 5. A certificate states LIMITS, never VALUES ───────────────────────────

@pytest.mark.parametrize("fact", [
    "property_building_value", "property_bpp_value", "valuation_method",
    "year_built", "construction_type", "occupancy_type", "sprinkler_system",
    "total_revenue", "total_payroll", "num_employees", "coinsurance_percentage",
])
def test_a_certificate_does_not_witness_the_risk_itself(fact):
    assert document_witnesses("certificate", fact) is False


@pytest.mark.parametrize("fact", [
    "policy_number", "carrier_name", "carrier_naic", "effective_date",
    "expiration_date", "coverage_lines", "lines_of_business", "applicant_name",
    "mailing_address", "gl_each_occurrence",
])
def test_a_certificate_still_witnesses_what_it_is_FOR(fact):
    """Blinding identity, policy numbers, carriers, dates or coverage lines
    would break the multi-carrier ACORD 25 roster (H5). Those are the whole
    point of the document."""
    assert document_witnesses("certificate", fact) is True


def test_the_loss_run_role_is_unchanged():
    for fact in ("policy_number", "carrier_name", "coverage_lines",
                 "effective_date"):
        assert document_witnesses("loss_run", fact) is False
    assert document_witnesses("loss_run", "num_claims") is True


@pytest.mark.parametrize("role", ["dec_page", "application", "policy", "quote",
                                  "unknown", "", None, "brand_new_type"])
def test_every_other_role_still_witnesses_everything(role):
    """Fail-open by construction: this can only ever REMOVE a value."""
    assert document_witnesses(role, "property_building_value") is True
    assert document_witnesses(role, "valuation_method") is True


# ── 6. THE SEAM. An offline probe proves the function, never the wiring ────
# Standing lesson from the declarations-index arc: "every offline probe passed
# while the pipeline was broken, because each called the function directly and
# read its return value."

def _doc(name, doc_type, facts):
    return {"filename": name, "doc_type": doc_type, "facts": facts,
            "flags": {}, "text": ""}


def test_the_merge_ACTUALLY_drops_a_role_blind_SCALAR():
    """The gate read `k not in _LIST_FIELDS or witnesses(...)`, so a role-blind
    SCALAR sailed through and the table only half meant what it said. This is
    the assertion that would have caught the live defect."""
    from services.extraction_service import merge_facts
    primary = _doc("dec.pdf", "dec_page", {"applicant_name": "Marisol Freight"})
    cert = _doc("coi.pdf", "certificate", {
        "property_building_value": "4200000",     # a LIMIT, not a value
        "valuation_method": "ACV",
        "carrier_name": "Kestrel Mutual Insurance Company",   # legitimately its own
    })
    facts, _flags = merge_facts([primary, cert], primary)

    def val(k):
        v = facts.get(k)
        return v.get("value") if isinstance(v, dict) else v

    assert not val("property_building_value"), (
        "a certificate's limit reached property_building_value - the run-2 defect")
    assert not val("valuation_method")
    assert val("carrier_name"), "a certificate IS a witness to the carrier"


def test_a_dec_page_may_still_state_the_building_value():
    """The gate is keyed on ROLE. A declarations page or application says what
    the building is worth, and must be unaffected."""
    from services.extraction_service import merge_facts
    primary = _doc("app.pdf", "application", {"applicant_name": "Marisol Freight"})
    dec = _doc("dec.pdf", "dec_page", {"property_building_value": "4200000"})
    facts, _ = merge_facts([primary, dec], primary)
    v = facts.get("property_building_value")
    assert (v.get("value") if isinstance(v, dict) else v)


@pytest.mark.parametrize("docs", [
    "not a list", 7, {"text": "x"}, [None], ["a string row"], [[], {}],
])
def test_a_malformed_docs_argument_never_silently_skips_the_gate(docs):
    """Found by this suite, not by review, and it mattered more than it looks.

    Both gates read `" ".join(str(d.get("text") or "") for d in (docs or []))`.
    A str survives `or []`, is iterable, and yields characters - so it raised
    AttributeError. The callers wrap each gate in try/except, so the failure was
    not a crash; the gate was SKIPPED and the invented value survived silently,
    which is the one outcome these functions exist to prevent.

    Fixed for the payroll gate at the same time - it had the identical hole.
    """
    mf = {"valuation_method": {"value": "ACV", "source": "ai"}}
    gate(mf, docs)
    assert mf["valuation_method"] is None, (
        "no readable document text means nothing corroborates the method")


def test_the_payroll_gate_got_the_same_hardening():
    from services.extraction_service import _gate_inferred_payroll_period
    mf = {"wc_payroll_period": {"value": "annual", "source": "ai"}}
    _gate_inferred_payroll_period(mf, "not a list")     # must not raise
    assert mf["wc_payroll_period"] is None


def test_a_row_that_is_not_a_dict_is_skipped_not_fatal():
    from services.extraction_service import _all_document_text
    assert _all_document_text([{"text": "a"}, None, "b", {"text": "c"}]) == "a c"
    assert _all_document_text(None) == ""
    assert _all_document_text("xyz") == ""
