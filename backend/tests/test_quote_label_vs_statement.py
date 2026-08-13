"""The evidence gate must tell a LABEL from a STATEMENT.

Regression cover for the 2026-08-12 defect in `_quote_restates_the_question`.

That check was added to stop two real failures - a checkbox ticked on the
"evidence" `"for non-payment of premium"`, another on `"additional insured"`.
Both are the field's own label read back. Correct target, wrong test: it asked
only "are all the quote's significant words already in the question?", and a
direct answer to a yes/no question is BY DEFINITION mostly the question's own
words. Worse, `"not"` is in `_ECHO_STOPWORDS`, so the single word carrying the
whole meaning was discarded before the comparison.

Measured against the real schemas: 39 of 218 genuine compliance questions across
9 forms (18%; ACORD 125 40%, ACORD 126 33%) had their canonical document
evidence rejected. A rejected "No" has NO fallback - `_evidence_supports`
failing on a negative blanks the field outright, where a "Yes" can still survive
on a paired explanation - so the loss landed squarely on the majority case.

The fix adds a STRUCTURAL second condition (`_quote_asserts_something`): overlap
is necessary but no longer sufficient. Both populations are pinned below.
"""
import os
import re
import sys
import glob
import json

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

import services.pdf_service as ps  # noqa: E402


# ── The two populations, as literal strings ─────────────────────────────────
# BARE LABELS: no subject, no finite verb - they assert nothing about anybody.
# The first two are the verbatim live failures this gate exists to stop.
BARE_LABELS = [
    "for non-payment of premium",
    "additional insured",
    "non-payment of premium",
    "parent company",
    "judgment or lien",
]

# REAL EVIDENCE: complete statements. Every one of these reuses its question's
# vocabulary wholesale - that is exactly why the token-overlap test destroyed
# them, and exactly why it must not.
REAL_STATEMENTS = [
    "The applicant does not have any subsidiaries.",
    "The applicant does not draw plans, designs or specifications for others.",
    "The applicant does not lease equipment to others with or without operators.",
    "The applicant does not install, service or demonstrate products.",
    "Subcontractors are not required to carry coverage.",
    "Subcontractors are required to carry coverage.",
    "The applicant does not handle hazardous material.",
    "The applicant has not had prior workers compensation coverage.",
    "The applicant does not own or rent any parking facilities.",
    "There are no swimming pools on the premises.",
]


@pytest.mark.parametrize("label", BARE_LABELS)
def test_a_bare_label_asserts_nothing(label):
    assert not ps._quote_asserts_something(label), (
        f"{label!r} has no subject and no finite verb - treating it as a "
        f"statement would let the original false checkbox tick back in"
    )


@pytest.mark.parametrize("stmt", REAL_STATEMENTS)
def test_real_evidence_is_a_statement(stmt):
    assert ps._quote_asserts_something(stmt), (
        f"{stmt!r} is a complete statement of fact about the applicant. "
        f"Rejecting it blanks a legitimate answer with no fallback."
    )


def test_the_question_itself_is_never_evidence():
    """A quote that IS the question - trailing '?' or an opening auxiliary -
    asserts nothing, however many words it has."""
    for q in (
        "Does the applicant own or rent any parking facilities?",
        "Are subcontractors required to carry coverage?",
        "Has the applicant had prior workers compensation coverage?",
        "Any area leased to others?",
    ):
        assert not ps._quote_asserts_something(q), q


def test_too_short_to_predicate():
    assert not ps._quote_asserts_something("premium")
    assert not ps._quote_asserts_something("")
    assert not ps._quote_asserts_something(None)


# ── The property, measured on the REAL schemas ──────────────────────────────
_SCHEMA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "forms_schemas")
_QRE = re.compile(
    r'response to the question,\s*["""“]?(.+?)["""”]?\s*[?."]*\s*$', re.I | re.S)


def _negate(q):
    """The canonical way a document denies an ACORD question."""
    s = re.sub(r"\s+", " ", q.strip().rstrip('?".').strip())
    m = re.match(r"^(?:does|do)\s+(?:the\s+)?applicant\s+(.*)$", s, re.I)
    if m:
        return f"The applicant does not {m.group(1)}."
    m = re.match(r"^(is|are)\s+(?:there\s+)?(.*)$", s, re.I)
    if m:
        return f"There {'is' if m.group(1).lower() == 'is' else 'are'} no {m.group(2)}."
    m = re.match(r"^(?:has|have)\s+(?:the\s+)?applicant\s+(.*)$", s, re.I)
    if m:
        return f"The applicant has not {m.group(1)}."
    return None


def _real_compliance_negations():
    """Harvested from the shipped schemas, never hand-listed."""
    out = []
    for path in sorted(glob.glob(os.path.join(_SCHEMA_DIR, "*.json"))):
        try:
            sch = json.load(open(path, encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(sch, dict):
            continue
        form = os.path.basename(path).replace("_schema.json", "")
        seen = set()
        for field, meta in sch.items():
            if not isinstance(meta, dict):
                continue
            tu = meta.get("tu") or ""
            if "response to the question" not in tu.lower():
                continue
            m = _QRE.search(tu)
            if not m:
                continue
            q = m.group(1).strip()
            if len(q) < 15 or q in seen:
                continue
            seen.add(q)
            neg = _negate(q)
            if neg:
                out.append((form, field, tu, neg))
    return out


def _gate_rejects(quote, tooltip):
    """Mirrors the closure in map_facts_to_form: overlap AND not-a-statement."""
    text = str(quote or "").strip().strip('"“”‘’ ')
    q = ps._echo_tokens(text)
    d = ps._echo_definition_tokens(tooltip)
    if not (q and d):
        return False
    if not ps._echo_all_tokens_present(q, d):
        return False
    return not ps._quote_asserts_something(text)


def test_the_harvest_is_not_empty():
    """An empty or thin harvest would make the coverage test below pass
    vacuously - the exact trap improving-ll.md C25 documents. 121 questions
    across 9 forms at the time of writing; the floor guards against the
    harvester silently breaking, not against ACORD adding questions."""
    rows = _real_compliance_negations()
    assert len(rows) > 100, f"only harvested {len(rows)} questions - harvester broken"
    assert len({f for f, _, _, _ in rows}) >= 8, "harvest lost whole forms"


def test_no_real_compliance_answer_is_rejected_as_a_restatement():
    """THE regression. Every genuine compliance question on every shipped form,
    answered the way a document actually answers it, must survive the gate."""
    rejected = [
        (form, field, neg)
        for form, field, tu, neg in _real_compliance_negations()
        if _gate_rejects(neg, tu)
    ]
    assert not rejected, (
        f"{len(rejected)} legitimate 'No' answers rejected as restatements "
        f"(each blanks its field with no fallback). First 5: {rejected[:5]}"
    )


def test_the_gate_still_kills_the_live_culprits():
    """The fix must not simply disable the check."""
    for quote, tooltip in (
        ("for non-payment of premium",
         "Check the box (if applicable): Indicates the policy is being "
         "cancelled due to NON-PAYMENT OF PREMIUM."),
        ("additional insured",
         "Check the box (if applicable): Indicates the additional interest "
         "type is an ADDITIONAL INSURED."),
    ):
        assert _gate_rejects(quote, tooltip), (
            f"{quote!r} is a bare label echoed from the question - it must "
            f"still be rejected, or the original false tick returns"
        )


def test_predication_check_carries_no_insurance_vocabulary():
    """Same standing rule as `_window_authority`: the signal is structural, so
    it holds for a carrier whose wording we have never seen. A domain keyword
    here would be a per-carrier lookup in disguise."""
    import inspect
    # The EXECUTABLE logic only. The docstring legitimately quotes the live
    # culprit ("additional insured") as the example it exists to catch, and
    # documenting a defect is not the same as matching on its vocabulary.
    src = inspect.getsource(ps._quote_asserts_something)
    src = re.sub(r'""".*?"""', "", src, flags=re.S)
    for pattern in (ps._QUOTE_INTERROGATIVE_RE.pattern,
                    ps._QUOTE_PREDICATE_RE.pattern):
        src += pattern
    banned = (
        "insur", "premium", "policy", "coverage", "liability", "applicant",
        "subcontractor", "vehicle", "claim", "deductible", "endorse",
    )
    hits = [w for w in banned if w in src.lower()]
    assert not hits, f"insurance vocabulary leaked into a structural check: {hits}"
