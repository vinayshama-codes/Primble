"""AI gap-fill answers that are NOT answers (round 5, 7 Oct 2026).

The owner's live run of 7 Oct (session b248c194, real AI fill) printed values
that LOOK like answers and say nothing. Every one passed the raw-text check -
the string is somewhere in the uploaded documents - and every one was missed
by the week's gates, which replayed with the AI switched off:

  * a POINTER to another page:   "SEE SCHEDULE" as the roof material, the
    burglar alarm, the front exposure and the BCEG grade (ACORD 140) - the
    dec printed "DEDUCTIBLE $500. Exceptions: SEE SCHEDULE";
  * a PARTY's name:              "CHOICE ELECTRIC LLC" as the description of
    operations (ACORD 125 and 130);
  * the QUESTION read back:      "service" explaining "Does applicant install,
    service or demonstrate products?" (ACORD 126); "service" alone as the
    description of operations (ACORD 131, both layers);
  * a RATING CLASS:              "State Act - Electrical Wiring-Within Buildings
    & Drivers." - the WC rating schedule's wording with its coverage label -
    as the description of operations (ACORD 131), which ACORD's own tooltip on
    that box says is "often not sufficient";
  * a FORM TITLE:                "DESIGNATED INSURED-PRIMARY NON-CONTRIB COV WHEN
    REQ BY INSURED CONTRACT OR CERT" (printed once, on the auto policy's forms
    schedule beside "CA 71 65 09 11") as underlying coverage information;
  * the box's OPTION LIST:       ACORD 140's blanket summary rows A-C =
    "Building" / "Contents" / "Combined Building and Contents" - the tooltip's
    "Examples include Building, Contents, or Combined Building and Contents.",
    in order.

ONE RULE PER CLASS, each structural and generic - the box's own tooltip, the
facts we already hold and the documents' own printing decide; no word list
tuned to one package. Each refusal returns a DISTINCT reason code (recorded on
the guard report) and the needs-attention list says why in its own sentence
(`held_back_sentence`).

SCOPE, and it is the whole safety argument: values THIS run's gap-fill model
wrote (`gpt_filled_set`). A deterministic rule's value, an alias stamp and a
person's answer never reach these rules. Yes/No boxes and checkboxes are the
evidence gate's; ACORD 141 / 160 are frozen (owner, 14 Sep 2026) like every
guard written since.

TWO DOORS INTO THE PIPELINE, one predicate behind both:
  * `refuse_non_answers` - one call in `map_facts_to_form`'s post-fill guard
    chain, for every AI text box;
  * `explanation_non_answer` - the evidence gate's `_present` asks it, so an
    EXPLANATION that is not an answer is not evidence: a Yes that stood on it
    alone stands on its own quote (which the gate then writes into the
    explanation, as it always has) or falls with it - the gate's semantics,
    unchanged. Without this the gate also PROMOTED an "Other" tick to Yes from
    a stranded "SEE SCHEDULE" (Pass B), which is how ACORD 140's guard /
    watchmen "Other" box came back ticked beside it.
"""
from __future__ import annotations

import bisect
import logging
import re
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# ── Reason codes (distinct per class; the guard report's `reason`) ───────────
REASON_CROSS_REFERENCE = "AI_CROSS_REFERENCE"
REASON_PARTY_NAME = "AI_PARTY_NAME_AS_DESCRIPTION"
REASON_ECHO = "AI_ECHOES_THE_QUESTION"
REASON_ONE_WORD_OPERATIONS = "AI_ONE_WORD_OPERATIONS"
REASON_CLASSIFICATION = "AI_CLASSIFICATION_AS_OPERATIONS"
REASON_FORM_TITLE = "AI_FORM_TITLE"
REASON_OPTION_LIST = "AI_OPTION_LIST_DUMP"
# Not a class of its own: the AI amount / tick of an OTHER row whose naming
# box one of the rules above refused ("dropping half a relationship must drop
# the other half" - an OTHER deductible amount with no deductible named).
REASON_ROW_NAME_REFUSED = "AI_OTHER_ROW_NAME_REFUSED"

REASON_YEAR_FROM_A_DATE = "AI_YEAR_NOT_A_BUILDING_YEAR"
REASON_POLICY_DATE_AS_START = "AI_POLICY_DATE_AS_BUSINESS_START"
REASON_COPE_WITHOUT_EVIDENCE = "AI_BUILDING_ATTRIBUTE_NOT_STATED"
REASON_CARRIER_CODE_AS_INSURED_ID = "AI_CARRIER_CODE_AS_INSURED_ID"
REASON_COVERAGE_HAS_ITS_OWN_ROW = "AI_OTHER_ROW_HAS_ITS_OWN_BOXES"
REASON_NOT_A_STREET_LINE = "AI_NOT_A_STREET_LINE"
REASON_SELF_LABELLED = "AI_LABEL_REPEATS_ITSELF"
REASON_SUMMARY = "AI_SUMMARY_NOT_DOCUMENT_TEXT"
REASON_BUREAU_NOT_STATED = "AI_BUREAU_ID_NOT_STATED"

REASON_CODES = frozenset({
    REASON_CROSS_REFERENCE, REASON_PARTY_NAME, REASON_ECHO, REASON_ONE_WORD_OPERATIONS,
    REASON_CLASSIFICATION, REASON_FORM_TITLE, REASON_OPTION_LIST, REASON_ROW_NAME_REFUSED,
    REASON_YEAR_FROM_A_DATE, REASON_POLICY_DATE_AS_START, REASON_COPE_WITHOUT_EVIDENCE,
    REASON_CARRIER_CODE_AS_INSURED_ID, REASON_COVERAGE_HAS_ITS_OWN_ROW, REASON_NOT_A_STREET_LINE,
    REASON_SELF_LABELLED, REASON_SUMMARY, REASON_BUREAU_NOT_STATED,
})

# What the producer reads in the needs-attention list. Plain words, no
# em-dashes, never the refused value (it belongs to nothing on this form).
_HELD_BACK: Dict[str, str] = {
    REASON_CROSS_REFERENCE: ("The AI put a pointer to another part of your documents here "
                             "(such as \"see schedule\"), not a value, so it was left blank."),
    REASON_PARTY_NAME: ("The AI put a company or person's name here, which does not describe "
                        "anything, so it was left blank."),
    REASON_ECHO: ("The AI repeated the words of this box's own question, not an answer, so it "
                  "was left blank."),
    REASON_ONE_WORD_OPERATIONS: ("The AI put a single word here, which does not describe the "
                                 "operations, so it was left blank."),
    REASON_CLASSIFICATION: ("The AI put a rating classification here. This box asks what the "
                            "business actually does, so it was left blank."),
    REASON_FORM_TITLE: ("The AI put the title of a policy form or endorsement here, not an answer "
                        "for this box, so it was left blank."),
    REASON_OPTION_LIST: ("The AI copied the form's own list of example answers here, not your "
                         "values, so it was left blank."),
    REASON_ROW_NAME_REFUSED: ("The AI's name for this \"other\" row was not an answer, so the "
                              "row's amount and tick were left blank too."),
    REASON_YEAR_FROM_A_DATE: ("Your documents do not state this building year. The AI took a "
                              "year from a policy date, so it was left blank."),
    REASON_POLICY_DATE_AS_START: ("The AI put a policy date (such as the issue date) here. It is "
                                  "not when the business started, so it was left blank."),
    REASON_COPE_WITHOUT_EVIDENCE: ("Your documents do not describe this part of the building, so "
                                   "the AI's answer was left blank."),
    REASON_CARRIER_CODE_AS_INSURED_ID: ("The AI put the insurance company's own code here. This box "
                                        "asks for the business's identifier, so it was left blank."),
    REASON_COVERAGE_HAS_ITS_OWN_ROW: ("The AI listed a coverage as \"other\" although this form has its "
                                      "own boxes for it, so the row was left blank."),
    REASON_NOT_A_STREET_LINE: ("The AI put a city or state in the street line, so it was left "
                               "blank. The city, state and ZIP have their own boxes."),
    REASON_SELF_LABELLED: ("The AI repeated one word as both a label and its value (such as "
                           "\"CO: CO\"), not an answer, so it was left blank."),
    REASON_SUMMARY: ("The AI wrote its own summary of your documents here, not something they "
                     "state, so it was left blank."),
    REASON_BUREAU_NOT_STATED: ("Your documents do not print this credit or rating bureau's number "
                               "or name, so the AI's answer was left blank."),
}


def held_back_sentence(reason: Any) -> Optional[str]:
    """The needs-attention sentence for one of this module's reason codes
    ("AI_CROSS_REFERENCE" or "AI_CROSS_REFERENCE: detail"), else None."""
    code = str(reason or "").split(":", 1)[0].strip()
    return _HELD_BACK.get(code)


# Forms the owner froze on 14 Sep 2026 - no new guard acts on them.
_FROZEN_FORMS = frozenset({"ACORD_141", "ACORD_160"})


def _base_form(form_id: Any) -> str:
    return str(form_id or "").split("__", 1)[0]


def _ps():
    from services import pdf_service as _p      # lazy: pdf_service imports us lazily too
    return _p


def _fv(facts: Any, key: str) -> Any:
    v = facts.get(key) if isinstance(facts, dict) else None
    if isinstance(v, dict) and "value" in v:
        v = v.get("value")
    return v


def _norm(text: Any) -> str:
    """Letters and digits only, lower case, single spaces."""
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


# ── The box: what kind of box is it, and what does its tooltip ask? ──────────
_ROW_RE = re.compile(r"^(?P<base>.+)_(?P<row>[A-N])(?P<sub>\d?)$")
# A narrative box's LEAF (its last name segment) ends in one of these. Ends, not
# contains: "...DescriptionCode" is a code box. "Desciption" is ACORD 127's own
# spelling of one box ("ElectronicDataMonitoringDevice_OtherDesciption").
_NARRATIVE_LEAF_ENDINGS = ("description", "desciption", "explanation", "narrative",
                           "remarktext", "remark", "remarks", "comment", "comments")


def _leaf(field: str) -> str:
    m = _ROW_RE.match(field or "")
    stem = m.group("base") if m else (field or "")
    return stem.rsplit("_", 1)[-1].lower()


def _is_narrative_box(field: str) -> bool:
    return _leaf(field).endswith(_NARRATIVE_LEAF_ENDINGS)


def _is_remarks_box(field: str) -> bool:
    return "remark" in _leaf(field) or _leaf(field).startswith("comment")


def _is_operations_box(field: str, tooltip: str) -> bool:
    """A box that asks what the business DOES (ACORD 125 / 130 / 131
    "...OperationsDescription"), read from its own name and tooltip."""
    if not _leaf(field).endswith("operationsdescription"):
        return False
    return bool(re.search(r"\boperations?\b|\bwhat business\b", tooltip or "", re.I))


def _tooltip(schema: Any, field: str) -> str:
    meta = schema.get(field) if isinstance(schema, dict) else None
    return str((meta or {}).get("tu") or "") if isinstance(meta, dict) else ""


def _field_type(schema: Any, field: str) -> str:
    meta = schema.get(field) if isinstance(schema, dict) else None
    return str((meta or {}).get("ft") or "") if isinstance(meta, dict) else ""


# ACORD's remarks boilerplate names the remarks FORM, not what the box asks.
_ACORD101_NOTE_RE = re.compile(
    r"ACORD\s*101,?\s*Additional\s+Remarks\s+Schedule,?\s+may\s+be\s+attached[^.]*\.?", re.I)


# Example material Guard 8's cut does not know: "An example might be ...",
# "Examples: Monthly, Quarterly", "Example valuation methods are: ...", and
# ACORD 28's spaced "(e. g., personal auto, truckers, ...)".
_MORE_EXAMPLE_CUT_RE = re.compile(r"\b(?:an\s+)?examples?\b|\be\.\s?g\b|\bsuch\s+as\b", re.I)


def _cut_examples(text: str) -> str:
    ps = _ps()
    body = text or ""
    for rx in (ps._TOOLTIP_EXAMPLE_CUT_RE, _MORE_EXAMPLE_CUT_RE):
        cut = rx.search(body)
        if cut:
            body = body[: cut.start()]
    return body


def _definition(tooltip: str) -> str:
    """The tooltip's DEFINITION half - its "Enter text:" prefix and its
    examples ("e.g.", "Examples include", "such as", "An example might be")
    cut off: Guard 8's cut (`_TOOLTIP_EXAMPLE_CUT_RE`) and any mention of an
    example. An example is a valid ANSWER on ACORD's authority, never the
    question."""
    body = _ps()._TOOLTIP_PREFIX_RE.sub("", tooltip or "")
    return _cut_examples(_ACORD101_NOTE_RE.sub("", body))


# ══ (a) A CROSS-REFERENCE IS NOT A VALUE ═════════════════════════════════════
# "SEE SCHEDULE", "SEE ITEM FOUR FOR HIRED OR BORROWED AUTOS", "Refer to the
# declarations", "As shown on the attached schedule": the source document
# telling ITS reader where to look. The ACORD form does not carry that
# schedule, so on the form the pointer points at nothing. Corpus, 690 stored
# sessions: 35 AI pointers standing in 15 different boxes (roof material, BCEG
# grade, a limit amount, a modification factor, traffic violations, remarks).
#
# A clause is a reference when it OPENS with a reference verb: "see ..." (a
# following word, so "See's Candies" is a name), "refer to ...", "as per ...",
# or a participle of showing ("shown / listed / stated ... in|on") followed by a
# DOCUMENT noun. "per" alone is a basis, not a pointer - "Per claim $2,500",
# "Per occurrence", "Per policy", "Per item" are real answers (corpus: 6 AI
# values) - so "per" counts only before a document noun that is never a basis.
# Every clause of the value must be a reference and no clause may carry money:
# "See schedule; deductible $1,000" says something.
_XREF_DOC_NOUNS = (
    r"(?:schedules?|sched\b|attach(?:ed|ments?)|enclosures?|enclosed|declarations?|decs?\b|"
    r"dec\s+pages?|endorsements?|forms?|items?|sections?|pages?|remarks?|acord\b|"
    r"applications?|supplements?|binders?|quotes?|quotations?|proposals?|statements?|"
    r"exhibits?|addend(?:um|a)|riders?|worksheets?|lists?|listing|summary|loss\s+runs?|"
    r"polic(?:y|ies)|documents?|file|below|above)")
# After "per": only the nouns no limit or deductible is ever "per".
_XREF_PER_NOUNS = (
    r"(?:schedules?|sched\b|attach(?:ed|ments?)|declarations?|decs?\b|dec\s+pages?|"
    r"endorsements?|remarks?|applications?|supplements?|binders?|quotes?|quotations?|"
    r"proposals?|statements?|exhibits?|addend(?:um|a)|worksheets?|loss\s+runs?|acord\b|"
    r"documents?|file)")
_XREF_DET = r"(?:(?:the|our|your|this|attached|enclosed|following|separate|policy|underlying)\s+)*"
_XREF_LEAD_RE = re.compile(
    r"^\W*(?:please\s+)?(?:"
    r"see\s+(?!'s\b)\w"                                             # see <anything>
    r"|refer(?:ence)?\s+(?:to\s+)?" + _XREF_DET + _XREF_DOC_NOUNS +   # refer to <doc>
    r"|as\s+per\s+" + _XREF_DET + _XREF_DOC_NOUNS +                 # as per <doc>
    r"|per\s+" + _XREF_DET + _XREF_PER_NOUNS +                      # per <doc, never a basis>
    r"|(?:as\s+)?(?:shown|stated|listed|described|indicated|detailed|scheduled|noted|"
    r"outlined|specified|reflected|contained|included|provided|found|set\s+forth)\s+"
    r"(?:in|on|under|within|per|at|by)\s+" + _XREF_DET + _XREF_DOC_NOUNS +
    r"|attached\s+" + _XREF_DET + _XREF_DOC_NOUNS +
    r")", re.I)
_XREF_CLAUSE_SPLIT_RE = re.compile(r"\s*(?:;|\n|\|| / |\.\s+(?=[A-Za-z]))\s*")
_MONEY_RE = re.compile(r"\$\s*\d|\b\d{1,3}(?:,\d{3})+\b|\b\d+(?:\.\d+)?\s*%")
_XREF_MAX_CLAUSE_WORDS = 20


def is_cross_reference(value: Any) -> bool:
    """True when every clause of `value` is a pointer to another document or
    part of one, and no clause carries an amount."""
    text = str(value or "").strip()
    if not text or len(text) > 400:
        return False
    clauses = [c.strip(" .,:-") for c in _XREF_CLAUSE_SPLIT_RE.split(text)]
    clauses = [c for c in clauses if c]
    if not clauses:
        return False
    for c in clauses:
        if not _XREF_LEAD_RE.match(c):
            return False
        if _MONEY_RE.search(c):
            return False
        if len(re.findall(r"[A-Za-z0-9]+", c)) > _XREF_MAX_CLAUSE_WORDS:
            return False
    return True


def _box_asks_for_a_reference(field: str, tooltip: str) -> bool:
    """A box whose subject IS an attachment or a reference (ACORD 125's "type
    of other attachment", ACORD 101's "form to which this section is
    attached"). Read from the box's own name and definition."""
    if re.search(r"Attachment|Reference", field or ""):
        return True
    return bool(re.search(
        r"\b(?:type\s+of\s+)?(?:other\s+)?(?:attachment|reference)\b(?!\s+schedule)"
        r"|\bto\s+which\s+this\s+section\s+is\s+attached\b", _definition(tooltip), re.I))


# ══ (b) A PARTY'S NAME IS NOT A DESCRIPTION ══════════════════════════════════
# The applicant's name as its own description of operations, a lender's name as
# the "type of other interest", the certificate holder's as the item of
# interest, a contact's name as the contact TYPE. A name says WHO; these boxes
# ask WHAT. Identity is the one door (`same_entity_name`: spelling, case, OCR
# glue), plus the same name without its legal form ("Cascade Metal Works" for
# "Cascade Metal Works LLC") - a name missing its suffix is still a name.
#
# A box whose tooltip asks for a NAME is exempt - ACORD 125's
# Insurer_ProductDescription "may also be used to name the subsidiary company",
# ACORD 126's "explanation of any named insured WHO sells..." - and a value that
# merely STARTS with a party's name is a sentence about that party ("Ironclad
# Fabrication & Welding LLC is a metal fabrication contractor", 27 such AI
# values in the corpus, every one kept).
_PARTY_SCALAR_KEYS = (
    "applicant_name", "dba_name", "producer_name", "carrier_name", "prior_carrier",
    "wc_prior_carrier", "submission_carrier_name", "certificate_holder", "mortgagee_name",
    "loss_payee_name", "additional_insured", "landlord_name", "expiring_producer_name",
    "builders_risk_owner_name", "builders_risk_contractor_name", "contact_name",
    "producer_contact_name", "expiring_producer_contact_name",
)
_PARTY_LIST_KEYS = ("additional_named_insureds", "named_insured_details", "additional_interests",
                    "auto_named_individuals", "auto_drivers")
_PARTY_ROW_CARRIER_KEYS = ("coverage_lines", "prior_coverage_lines", "other_insurance_policies")
_NAME_ROW_KEYS = ("name", "full_name", "legal_name", "named_insured", "insured_name")
# "list" is deliberately absent: "For a vehicle, list the make, model and VIN"
# asks for details, not for a party.
_ASKS_FOR_A_NAME_RE = re.compile(r"\bnames?\b|\bidentify\b|\bwho\b", re.I)


def _party_names(facts: Any) -> List[str]:
    out: List[str] = []

    def _add(v: Any) -> None:
        if isinstance(v, str) and v.strip() and len(v.strip()) <= 160:
            out.append(v.strip())
        elif isinstance(v, dict):
            for k in _NAME_ROW_KEYS:
                if isinstance(v.get(k), str):
                    _add(v.get(k))
    for k in _PARTY_SCALAR_KEYS:
        v = _fv(facts, k)
        for x in (v if isinstance(v, list) else [v]):
            _add(x)
    for k in _PARTY_LIST_KEYS:
        v = _fv(facts, k)
        for x in v if isinstance(v, list) else []:
            _add(x)
    for k in _PARTY_ROW_CARRIER_KEYS:
        v = _fv(facts, k)
        for row in v if isinstance(v, list) else []:
            if isinstance(row, dict):
                _add(row.get("carrier"))
    # One printing per party is enough.
    seen: Set[str] = set()
    uniq: List[str] = []
    for n in out:
        k = _norm(n)
        if k and k not in seen:
            seen.add(k)
            uniq.append(n)
    return uniq


def _legal_form_tokens() -> frozenset:
    try:
        from services.normalization import _ENTITY_SUFFIXES
        toks = {t for suf in _ENTITY_SUFFIXES for t in _norm(suf).split()}
    except Exception:                                      # noqa: BLE001
        toks = set()
    return frozenset(toks | {"llc", "inc", "corp", "co", "company", "ltd", "lp", "llp",
                             "pllc", "pc", "na", "incorporated", "corporation", "limited"})


_LEGAL_FORMS: List[frozenset] = []


def _name_core(value: Any) -> str:
    """The name without trailing legal-form words ("cascade metal works")."""
    if not _LEGAL_FORMS:
        _LEGAL_FORMS.append(_legal_form_tokens())
    toks = _norm(value).replace(" and ", " ").split()
    while toks and toks[-1] in _LEGAL_FORMS[0]:
        toks.pop()
    return " ".join(toks)


def _is_party_name(value: Any, parties: Iterable[str]) -> Optional[str]:
    try:
        from services.normalization import same_entity_name
    except Exception:                                      # noqa: BLE001
        same_entity_name = None
    v = str(value or "").strip().strip(" .,;:")
    if not v or len(v) > 160:
        return None
    v_core = _name_core(v)
    for p in parties:
        if same_entity_name is not None and same_entity_name(v, p):
            return p
        p_core = _name_core(p)
        if v_core and v_core == p_core and len(v_core.split()) >= 2:
            return p
    return None


# ══ (c) THE QUESTION READ BACK, A ONE-WORD "DESCRIPTION", A RATING CLASS ═════
# Guard 8 (`_is_tooltip_echo`) catches a value that restates its box at 30+
# characters, or 2+ words lifted from the definition. It deliberately leaves
# ONE word alone - "Building" can be an answer - and so "service" explaining
# "install, service or demonstrate products?" shipped. What makes "service"
# safe to refuse is not its length but WHERE its words come from: every
# content word is the box's own definition (examples cut off - "Accounting"
# and "Claims" are ACORD's own example answers for the contact type, never an
# echo) or, for an explanation, its paired QUESTION's words. Digits count as
# content ("Location 2 - Building 1" is an answer), "no" counts as content (a
# negation the gate's own rules handle), the ACORD answer letters do not.
_ANSWER_TOKENS = frozenset({"y", "yes", "n"})


def _content_tokens(text: str) -> List[str]:
    ps = _ps()
    return [t for t in ps._echo_tokens(text)
            if t not in ps._ECHO_STOPWORDS and t not in _ANSWER_TOKENS]


def _question_words(schema: Any, field: str) -> Tuple[str, ...]:
    """The words of the Yes/No QUESTION this explanation box belongs to, when
    it belongs to one (the ACORD question-code pairing), else ()."""
    ps = _ps()
    try:
        pairs = _pairs_for(schema)
    except Exception:                                      # noqa: BLE001
        return ()
    q = pairs.get(field)
    if not q:
        return ()
    # The question's own examples ("such as medical equipment") are answers too.
    return tuple(ps._echo_tokens(_cut_examples(ps._compliance_question_text(_tooltip(schema, q)))))


_PAIRS_CACHE: List[Tuple[Any, Dict[str, str]]] = []


def _pairs_for(schema: Any) -> Dict[str, str]:
    """{explanation box: its Question-code box} - the evidence gate's pairing,
    Question codes only (an "Other" checkbox's tooltip is not a question)."""
    for ref, pairs in _PAIRS_CACHE:
        if ref is schema:
            return pairs
    ps = _ps()
    pairs = {exp: q for q, exp in ps._question_explanation_pairs(schema).items()
             if ps._QUESTION_CODE_RE.search(q)}
    _PAIRS_CACHE.insert(0, (schema, pairs))
    del _PAIRS_CACHE[4:]
    return pairs


def echoes_its_question(field: str, value: Any, schema: Any) -> bool:
    """Every content word of `value` is a word of the box's own definition or
    of its paired question. Narrative boxes only."""
    if not _is_narrative_box(field):
        return False
    tokens = _content_tokens(str(value or ""))
    if not tokens:
        return False
    ps = _ps()
    hay = tuple(ps._echo_tokens(_definition(_tooltip(schema, field)))) + _question_words(schema, field)
    if not hay:
        return False
    return all(any(ps._echo_near(t, h) for h in hay) for t in tokens)


def is_one_word_operations(field: str, value: Any, schema: Any) -> bool:
    """"service" as the description of a business's operations. ACORD's own
    words for these boxes: "completed in enough detail to enable the
    underwriter to understand and classify each operation"."""
    if not _is_operations_box(field, _tooltip(schema, field)):
        return False
    text = str(value or "").strip()
    return bool(text) and not re.search(r"\d", text) and len(re.findall(r"[A-Za-z]+", text)) == 1


# A rating classification as the description of operations. ACORD's tooltip on
# the 131 / 160 box: "A restatement of the products classification wording is
# often not sufficient (e.g., "Metal Goods Manufacturing NOC" could include
# anything from paper clips to bridge girders)"; on the 125 premises box: "Do
# not use the classification wording from the Commercial Lines Manual or
# Workers Compensation Manual." Corpus: 35 AI operations descriptions were a
# GL or WC class description and every one was already refused by an existing
# guard; the two that shipped (Choice Electric's 131, both layers) wore the WC
# schedule's coverage label "State Act - " in front, which defeated equality.
# Compared with a leading code and a leading short label ("State Act - ",
# "Contractors - ") folded away on BOTH sides.
_CLASS_LABEL_PREFIX_RE = re.compile(r"^\s*[A-Za-z][A-Za-z.&/' ]{0,30}?\s+[-–:]\s+(?=\S)")
_CLASS_CODE_PREFIX_RE = re.compile(r"^\s*\d{3,6}[A-Za-z]?\s*[-–:]?\s*")
_CLASS_DESC_KEYS = ("description", "classification", "class_description", "desc")


def _class_cores(text: str) -> Set[str]:
    """The comparable forms of one class wording: as printed, without a leading
    code, without a leading short label."""
    s = str(text or "").strip()
    out = {_norm(s)}
    no_code = _CLASS_CODE_PREFIX_RE.sub("", s, count=1)
    out.add(_norm(no_code))
    m = _CLASS_LABEL_PREFIX_RE.match(no_code)
    if m and len(re.findall(r"[A-Za-z]+", m.group(0))) <= 3:
        out.add(_norm(no_code[m.end():]))
    return {c for c in out if len(c.split()) >= 2}


def _classification_wordings(facts: Any) -> Set[str]:
    cores: Set[str] = set()
    for key in (facts or {}) if isinstance(facts, dict) else ():
        if not isinstance(key, str) or key.startswith("_") or "class" not in key:
            continue
        rows = _fv(facts, key)
        if isinstance(rows, dict):
            rows = [r for v in rows.values() for r in (v if isinstance(v, list) else [v])]
        for r in rows if isinstance(rows, list) else []:
            if not isinstance(r, dict):
                continue
            for k in _CLASS_DESC_KEYS:
                if isinstance(r.get(k), str) and r.get(k).strip():
                    cores |= _class_cores(r[k])
    return cores


def is_classification_wording(field: str, value: Any, schema: Any, wordings: Set[str]) -> bool:
    if not wordings or not _is_operations_box(field, _tooltip(schema, field)):
        return False
    parts = [p for p in re.split(r"\s*;\s*", str(value or "").strip()) if p.strip()]
    if not parts:
        return False
    return all(_class_cores(p) & wordings for p in parts)


# ══ (d) A FORM OR ENDORSEMENT TITLE IS NOT AN ANSWER ═════════════════════════
# A value the documents print ONLY as a title - a line led (or closed) by its
# form number, or the form's own heading line - names a document. In a box that
# asks for forms (ACORD 140 "form numbers and special conditions", ACORD 127's
# remarks "Enter any endorsements that apply", a certificate's "special
# conditions") that is the answer; anywhere else it is a line lifted off a
# forms schedule. A value the documents ALSO print as anything else - a priced
# line ("Limited Pollution Coverage - Work Sites $150"), running text - is left
# alone: that is a coverage, and other guards judge coverages.
#
# The form number is read STRUCTURALLY, never from a list: two or three
# letters, an optional series designator ("DS"), number groups, and an EDITION
# (month 01-12, year) at the end - or ISO's edition letter ("WC 00 00 00 C").
# The edition is what separates a form number from "NY 10001" or "CO 80221".
_DESIGNATOR_NORM_RE = re.compile(
    r"^(?:(?:form|forms|endorsement|endt|end|no|number|ed|edition)\s+)*(?:"
    r"[a-z]{2,3}(?:\s[a-z][a-z0-9]?)?(?:\s?\d{1,5}[a-z]{0,2}){1,3}"
    r"\s(?:ed\s)?(?:0[1-9]|1[0-2])\s(?:\d{2}|\d{4})"
    r"|[a-z]{2,3}(?:\s\d{2}){2,3}\s[a-z])$")
# A box that takes a TITLE: one that asks for forms / endorsements / conditions,
# or one that names a line, a policy or a coverage - an "other line of
# business", an "other coverage", a "policy type" is legitimately a coverage
# part's printed name ("Excess (Following Form) Liability").
_TAKES_A_TITLE_RE = re.compile(
    r"\b(?:forms?|endorsements?|special\s+conditions?|lines?\s+of\s+business|"
    r"policy\s+type|type\s+of\s+(?:policy|coverage|insurance)|other\s+(?:policy|polic(?:y|ies)|"
    r"coverages?|insurance))\b", re.I)
_TITLE_NAME_WORDS = (("Form",), ("Forms",), ("Endorsement",), ("Line", "Of", "Business"),
                     ("Policy", "Type"), ("Coverage", "Description"), ("Other", "Policy"))
_TITLE_MIN_WORDS = 3


class _TextIndex:
    """The documents' lines, folded once, for "where and how is this printed?"."""

    def __init__(self, raw_text: str):
        lines = str(raw_text or "").splitlines()
        self.lines = [" " + _norm(ln) + " " for ln in lines]
        self.starts: List[int] = []
        pos = 0
        for ln in self.lines:
            self.starts.append(pos)
            pos += len(ln) + 1
        self.text = "\n".join(self.lines)

    def printings(self, value: Any, limit: int = 400) -> List[Tuple[str, str]]:
        """(before, after): what else the line holds, for every printing."""
        needle = " " + _norm(value) + " "
        if len(needle.strip()) < 3:
            return []
        out: List[Tuple[str, str]] = []
        pos = self.text.find(needle)
        while pos != -1 and len(out) < limit:
            i = bisect.bisect_right(self.starts, pos) - 1
            local = pos - self.starts[i]
            line = self.lines[i]
            out.append((line[:local].strip(), line[local + len(needle):].strip()))
            pos = self.text.find(needle, pos + len(needle) - 1)
        return out


_INDEX_CACHE: List[Tuple[str, _TextIndex]] = []


def _text_index(raw_text: str) -> _TextIndex:
    for ref, idx in _INDEX_CACHE:
        if ref is raw_text:
            return idx
    idx = _TextIndex(raw_text)
    _INDEX_CACHE.insert(0, (raw_text, idx))
    del _INDEX_CACHE[3:]
    return idx


def printed_only_as_form_title(value: Any, raw_text: str) -> bool:
    """Every printing of `value` is a title printing - its line holds nothing
    else but a form number (before or after it), or nothing at all (the form's
    own heading) - and at least one carries the form number."""
    if len(re.findall(r"[A-Za-z]{2,}", str(value or ""))) < _TITLE_MIN_WORDS or not raw_text:
        return False
    prints = _text_index(raw_text).printings(value)
    if not prints:
        return False
    designated = False
    for before, after in prints:
        rest = [p for p in (before, after) if p]
        if not rest:
            continue                                       # a heading line
        if len(rest) == 2 or not _DESIGNATOR_NORM_RE.match(rest[0]):
            return False
        designated = True
    return designated


def _box_takes_a_title(field: str, tooltip: str) -> bool:
    if _TAKES_A_TITLE_RE.search(_definition(tooltip)):
        return True
    m = _ROW_RE.match(field or "")
    words = re.findall(r"[A-Z][a-z]*|[a-z]+|\d+", m.group("base") if m else (field or ""))
    for seq in _TITLE_NAME_WORDS:
        n = len(seq)
        if any(tuple(words[i:i + n]) == seq for i in range(len(words) - n + 1)):
            return True
    return False


# ══ (e) THE TOOLTIP'S OPTION LIST, COPIED IN ORDER ═══════════════════════════
# ACORD 140's blanket summary came back "Building" / "Contents" / "Combined
# Building and Contents" in rows A-C on SEVEN stored packages: the tooltip's
# "Examples include Building, Contents, or Combined Building and Contents.",
# one example per row, in order. Each example is a valid answer on its own
# (22 packages carry "Building" alone in row A - kept); reproducing the LIST is
# the model filling rows from the question. Same shape on the burglar-alarm
# and fire-protection rows ("safe" / "premises", "sprinklers" / "standpipes")
# and in one box ("safe, premises, perimeter, or ultrasonic").
#
# Fires on: a run of 3+ consecutive AI rows equal to consecutive options; a
# run of 2 when it fills EVERY row the box has and the list is longer than the
# box (a 2-row box can hold no more of a 4-option list); one box holding 3+
# options in order. A list of two options ("Ford, Chevy") is never used - a
# real two-vehicle fleet looks exactly like it.
_EXAMPLE_CUE_RE = re.compile(
    r"\b(?:examples?\s+(?:include|are|of)\b|e\.?\s?g\b\.?|such\s+as\b|for\s+example\b)", re.I)
_OPTION_STOP_RE = re.compile(
    r"[()]|\.\s|\.$|\s(?:may|are|is|can|should|will|could)\s|\setc\b", re.I)
_MIN_OPTIONS = 3


def tooltip_options(tooltip: str) -> List[str]:
    """ACORD's example answers in the tooltip's own order, folded; [] when the
    tooltip lists fewer than three."""
    tu = str(tooltip or "")
    m = _EXAMPLE_CUE_RE.search(tu)
    if not m:
        return []
    tail = tu[m.end():].lstrip(" \t.:,")
    if re.match(r"\s*\n?\s*[*\-•]", tail):                  # a bulleted list
        items = []
        for ln in tail.splitlines():
            b = re.match(r"\s*[*\-•]\s*(.+)$", ln)
            if b:
                items.append(re.sub(r"\(.*?\)", "", b.group(1)))
            elif items and ln.strip():
                break
    else:
        stop = _OPTION_STOP_RE.search(tail)
        body = tail[: stop.start()] if stop else tail
        # A comma separates options only before a space - "$100,000" is one.
        items = [i for i in re.split(r"\s*;\s*|\s*,\s+|,$", body) if i.strip()]
        if not items:
            return []
        last = items[-1].strip()
        lead = re.match(r"^(?:or|and)\s+(.+)$", last, re.I)
        if lead:                                            # Oxford comma: ", or X and Y"
            items[-1] = lead.group(1)
        elif len(items) >= 2:                               # "B and C" closing the list
            items[-1:] = re.split(r"\s+(?:or|and)\s+", last, maxsplit=1)
        else:                                               # "A or B or C"
            items = re.split(r"\s+or\s+", last)
    opts = [_norm(i) for i in items]
    opts = [o for o in opts if o and o not in ("etc", "and", "or")]
    return opts if len(opts) >= _MIN_OPTIONS else []


def _split_options_in_value(value: Any) -> List[str]:
    parts = re.split(r"\s*[,;/]\s*|\s+(?:or|and)\s+", str(value or "").strip())
    return [_norm(p) for p in parts if _norm(p)]


def _is_in_order(values: List[str], opts: List[str]) -> bool:
    if not values or len(values) > len(opts):
        return False
    for j in range(len(opts) - len(values) + 1):
        if opts[j:j + len(values)] == values:
            return True
    return False


def option_list_dumps(mapped: dict, schema: dict, ai_fields: Set[str]) -> Set[str]:
    """Boxes whose AI values reproduce their tooltip's example list in order."""
    groups: Dict[str, Dict[str, str]] = {}
    for f in schema or {}:
        m = _ROW_RE.match(f)
        if m and not m.group("sub"):
            groups.setdefault(m.group("base"), {})[m.group("row")] = f
    out: Set[str] = set()
    for base, rows in groups.items():
        letters = sorted(rows)
        first = rows[letters[0]]
        if _field_type(schema, first) == "/Btn":
            continue
        opts = tooltip_options(_tooltip(schema, first))
        if not opts:
            continue
        # one box, the whole list (or 3+ of it, in order)
        for f in rows.values():
            if f in ai_fields and str(mapped.get(f) or "").strip():
                parts = _split_options_in_value(mapped.get(f))
                if len(parts) >= _MIN_OPTIONS and _is_in_order(parts, opts):
                    out.add(f)
        # consecutive rows, one option each, in order
        run: List[str] = []

        def _flush(run_: List[str]) -> None:
            if len(run_) < 2:
                return
            vals = [_norm(mapped.get(f)) for f in run_]
            if not _is_in_order(vals, opts):
                return
            if len(run_) >= _MIN_OPTIONS or (len(run_) == len(letters) and len(opts) > len(run_)):
                out.update(run_)
        prev = None
        for L in letters:
            f = rows[L]
            v = _norm(mapped.get(f))
            ok = f in ai_fields and v and v in opts
            adjacent = prev is not None and ord(L) - ord(prev) == 1
            if ok and run and adjacent:
                run.append(f)
            elif ok:
                _flush(run)
                run = [f]
            else:
                _flush(run)
                run = []
            prev = L
        _flush(run)
    return out


# ══ A building year must be printed as a building's year (8 Oct 2026) ════════
# ACORD 140's year-built and improvement-year boxes kept coming back with a
# year the documents print only INSIDE A DATE - five "2025" improvement years
# off "01/01/2025" policy periods (505bf394, twice), and round 6's "1999" off
# "Copyright, Insurance Services Office, Inc., 1999". The labels said
# `ai_verified` because the string occurs somewhere. Structural, no topic list
# for the refusal itself: every printing of the year is part of a full date or
# a copyright / edition line, or the year is not printed at all. A date that
# sits beside a building word ("roof replaced 06/15/2018") is still evidence.
_BUILDING_YEAR_BOX_RE = re.compile(
    r"^(?:CommercialStructure|BuildingImprovement|Construction)_\w*Year_[A-N]\d?$")
_DATE_BEFORE_YEAR_RE = re.compile(
    r"(?:\d{1,2}\s*[/\-.]\s*\d{1,2}\s*[/\-.]\s*|"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2},?\s*)$", re.I)
_DATE_AFTER_YEAR_RE = re.compile(r"^\s*[/\-.]\s*\d{1,2}\s*[/\-.]\s*\d{1,2}")
_COPYRIGHT_RE = re.compile(r"copyright|©|\(c\)|insurance services office|all rights reserved",
                           re.I)
# Words that only describe work ON A BUILDING. Deliberately narrow: "electric"
# is in insureds' names (CHOICE ELECTRIC LLC 01/01/2025 kept a 2025 in the first
# cut), "replacement" is a valuation, "improvements" a coverage, "installment"
# a billing term.
_BUILDING_WORD_RE = re.compile(
    r"\b(?:roof(?:s|ing)?|wir(?:e|ed|ing)|heating|hvac|plumbing|built|"
    r"renovat\w*|remodel\w*|upgrad\w*)\b", re.I)


def year_not_printed_as_a_building_year(year: Any, raw_text: str) -> bool:
    """True when `year` (4 digits) is printed only inside dates / copyright
    lines - or not at all - and never beside a building word."""
    y = str(year or "").strip()
    if not re.fullmatch(r"(?:18|19|20)\d{2}", y) or not raw_text:
        return False
    for m in re.finditer(rf"(?<!\d){y}(?!\d)", raw_text):
        before = raw_text[max(0, m.start() - 24):m.start()]
        after = raw_text[m.end():m.end() + 8]
        near = raw_text[max(0, m.start() - 40):m.end() + 40]
        in_date = bool(_DATE_BEFORE_YEAR_RE.search(before) or _DATE_AFTER_YEAR_RE.match(after))
        in_copyright = bool(_COPYRIGHT_RE.search(raw_text[max(0, m.start() - 80):m.start()]))
        # Glued to a word ("2001CHEVROLET", "1999GMC"): a vehicle description
        # or an identifier, never a statement of a building's year.
        glued = (raw_text[m.end():m.end() + 1].isalpha()
                 or raw_text[max(0, m.start() - 1):m.start()].isalpha())
        if (in_date or in_copyright or glued) and not _BUILDING_WORD_RE.search(near):
            continue
        return False                      # printed as a year in its own right
    return True


# ══ A building attribute must be stated as that attribute (8 Oct 2026) ═══════
# The same 140 sections on every Choice Electric run: roof "Composition" (one of
# ACORD's own options - the documents never mention a roof material), protection
# class 4, "sprinklers", "Cyber Incident Response Team" as a burglar alarm,
# "REPLACEMENT COST" as fire protection, the vehicle garaging address as the
# building's front exposure. Each value is printed somewhere (or is an option
# the tooltip lists), so every presence test passed. The bar: the documents
# must mention the ATTRIBUTE, with the answer (or the words of the ACORD option
# it names) within 80 characters of that mention.
_COPE_ATTRIBUTE_BOXES: Tuple[Tuple[re.Pattern, re.Pattern, int], ...] = (
    (re.compile(r"Roof(?:Material|Type|Covering)", re.I), re.compile(r"\broof", re.I), 80),
    (re.compile(r"ProtectionClass", re.I),
     re.compile(r"protection\s+class|\bp\.?c\.?\s*(?:#|no\.?|code)?\s*\d", re.I), 80),
    (re.compile(r"Sprinkler", re.I), re.compile(r"sprinkl", re.I), 80),
    # BCEG (8 Oct 2026, run 15f43bba): ACORD 140 printed a building code
    # effectiveness grade "0" on a package that never says BCEG anywhere.
    (re.compile(r"BuildingCodeEffectiveness", re.I),
     re.compile(r"\bbceg\b|code\s+effectiveness", re.I), 80),
    (re.compile(r"Alarm|Burglar|FireProtection", re.I),
     re.compile(r"alarm|central\s+station|sprinkl|fire\s+(?:department|protection)", re.I), 80),
    (re.compile(r"BuildingExposure_\w*Description", re.I),
     re.compile(r"exposure|adjacent|adjoin\w*|\bfeet\b|\bft\b|distance|vacant", re.I), 80),
    # ...and its DISTANCE (14 Oct 2026, run `b117f010`): ACORD 140 printed all
    # four exposure distances as "500" - the producer's hydrant answer - on a
    # package whose documents state no exposure. Only exposure wording counts:
    # a "500 FT" printed for a hydrant is not a distance to an exposure.
    (re.compile(r"BuildingExposure_\w*Distance", re.I),
     re.compile(r"exposure|adjacent|adjoin\w*|clearance|separation", re.I), 80),
    # An AUTO COVERAGE's own amount (8 Oct 2026): ACORD 137 printed UM / UIM
    # limits of $1,000,000 three times - the liability limit - on a dec whose
    # Uninsured Motorists line reads "$SEE SCHEDULE" and whose schedule states
    # no UM limit. Wider window: a coverage grid prints its column far from
    # the amount.
    (re.compile(r"(?:Un|Under)insuredMotorist", re.I),
     re.compile(r"uninsured|underinsured|\bu\.?m\.?\b|\bu\.?i\.?m\.?\b", re.I), 200),
    (re.compile(r"MedicalPayments", re.I),
     re.compile(r"medical\s+payments|med\.?\s*pay", re.I), 200),
    (re.compile(r"PersonalInjuryProtection", re.I),
     re.compile(r"personal\s+injury\s+protection|\bp\.?i\.?p\.?\b", re.I), 200),
    # Towing (14 Oct 2026, run `b117f010`): ACORD 137 printed a towing and
    # labour limit of $1,000,000 - the liability limit - with no towing line.
    (re.compile(r"TowingAndLabou?r", re.I), re.compile(r"towing", re.I), 200),
)
_SIG_WORD_RE = re.compile(r"[a-z]{4,}")
_YES_NO_TOKEN_RE = re.compile(r"(?:y|n|yes|no|true|false|x|on|off|1|0)", re.I)


def _option_words(value: str, tooltip: str) -> Set[str]:
    """The words of the ACORD option `value` names, read off its tooltip."""
    out: Set[str] = set()
    tu = tooltip or ""
    i = tu.lower().find(value.lower())
    if i >= 0:
        out |= set(_SIG_WORD_RE.findall(re.split(r"[;*\n]", tu[i:i + 120])[0].lower()))
    return out


def cope_answer_without_evidence(field: str, value: Any, raw_text: str, tooltip: str = "") -> bool:
    """True when `field` is a building-attribute box and the documents never
    state that attribute with this answer."""
    text = str(value or "").strip()
    if not text or not raw_text:
        return False
    for box_re, attr_re, width in _COPE_ATTRIBUTE_BOXES:
        if not box_re.search(field or ""):
            continue
        amount = bool(re.fullmatch(r"[\d\s.,%$]+", text))
        words = set() if amount else (set(_SIG_WORD_RE.findall(text.lower())) | _option_words(text, tooltip))
        digits = re.sub(r"\D", "", text.split(".")[0]) if amount else ""
        if not words and not digits:
            # A short code with no word of four letters ("GRP I", "TPO") is
            # read as itself (run 15f43bba: ACORD 140's protection class
            # printed "GRP I", the property schedule's Group I RATE line). A
            # yes / no tick says nothing to look for and is left alone.
            if _YES_NO_TOKEN_RE.fullmatch(text):
                return False
            words = {re.sub(r"\s+", " ", text.lower())}
        # A coverage's AMOUNT follows its heading (a column's values sit under
        # it, a row's limit after its name), so an amount is read mostly
        # forward: the figures BEFORE "UNINSURED MOTORISTS" on the Choice
        # Electric schedule are the previous column's liability limits.
        back = 0 if amount else width
        for m in attr_re.finditer(raw_text):
            window = raw_text[max(0, m.start() - back):m.end() + width].lower()
            if any(w in window for w in words):
                return False
            if digits and re.search(rf"(?<!\d){digits}(?!\d)", window.replace(",", "")):
                return False
        return True
    return False


# ══ A carrier's code is not the insured's identifier (8 Oct 2026) ════════════
# ACORD 130 NCCI RISK ID printed 11525 on every Choice Electric run - the WC
# dec's header "AMERISURE INSURANCE COMPANY NCCI Code No.11525", the CARRIER's
# NCCI code. The merge already refuses a number printed under another code's
# label as a NAIC (extraction_service._OTHER_CODE_LABEL_RE); this is the same
# reading for the insured's own identifier boxes.
_INSURED_ID_BOX_RE = re.compile(r"NCCIRiskIdentifier|RiskIdentifier|TaxIdentifier|FEIN", re.I)
_CARRIER_CODE_LABEL_RE = re.compile(
    r"\bncci\s+(?:carrier\s+)?code\b|\bnaic\b|\ba\.?\s?m\.?\s?best\b|"
    r"\b(?:company|carrier|insurer)\s+(?:code|no\.?|number)\b", re.I)


def carrier_code_as_insured_id(value: Any, raw_text: str) -> bool:
    """True when every printing of `value`'s digits sits after a carrier-code
    label on its own line, and none says "risk"."""
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) < 4 or not raw_text:
        return False
    hits = list(re.finditer(rf"(?<!\d){digits}(?!\d)", raw_text))
    if not hits:
        return False
    for h in hits:
        before = raw_text[raw_text.rfind("\n", 0, h.start()) + 1:h.start()]
        if not _CARRIER_CODE_LABEL_RE.search(before) or re.search(r"\brisk\b", before, re.I):
            return False
    return True


# ══ An OTHER coverage row is not a coverage the form prints itself (8 Oct) ═══
# ACORD 137 came back with four OTHER rows "Medical Payments $1,000,000" while
# the form has its own Medical Payments boxes (`Vehicle_MedicalPayments_*`) and
# the dec prints Med Pay "SEE SCHEDULE". An OTHER row names a coverage the form
# has no row for; one naming a coverage the form DOES print is a misfile, and
# its limit and symbol go with it.
_OTHER_COVERAGE_DESC_RE = re.compile(r"^(?P<p>\w+_)OtherCoverage(?:_)?Description_(?P<r>[A-Z])$")
_OTHER_COVERAGE_ROW_RE = re.compile(r"^(?P<p>\w+_)OtherCoverage_\w+_(?P<r>[A-Z])$")


def _own_boxes_name(text: str, schema: dict, prefix: str) -> bool:
    key = re.sub(r"[^a-z]", "", str(text or "").lower())
    if len(key) < 6:
        return False
    for f in schema or {}:
        if not f.startswith(prefix) or "Other" in f:
            continue
        if key in re.sub(r"[^a-z]", "", f.lower()):
            return True
    return False


def other_row_names_a_coverage_with_its_own_boxes(field: str, schema: dict, mapped: dict) -> bool:
    m = _OTHER_COVERAGE_DESC_RE.match(field or "")
    if m:
        return _own_boxes_name((mapped or {}).get(field), schema, m.group("p"))
    m = _OTHER_COVERAGE_ROW_RE.match(field or "")
    if m:
        desc = f"{m.group('p')}OtherCoverageDescription_{m.group('r')}"
        return _own_boxes_name((mapped or {}).get(desc), schema, m.group("p"))
    return False


# ══ A street line holds a street (8 Oct 2026) ════════════════════════════════
# ACORD 127 GARAGING street line came back "CO" - the state, with the city and
# ZIP already in their own boxes. A street line is a number, a street word or a
# post-office box; a bare state code, or words with no number and no street
# word (a city), is not one.
_LINE_ONE_BOX_RE = re.compile(r"(?:Address|PhysicalAddress|MailingAddress)_LineOne_[A-Z]$")
_STREET_WORD_RE = re.compile(
    r"\b(?:st|street|ave|avenue|rd|road|blvd|boulevard|dr|drive|ln|lane|way|hwy|highway|"
    r"pkwy|parkway|ct|court|pl|place|cir|circle|ter|terrace|trl|trail|loop|sq|square|plaza|"
    r"route|rte|box|suite|ste|unit|floor|bldg|building)\b", re.I)


def not_a_street_line(value: Any) -> bool:
    s = str(value or "").strip()
    if not s:
        return False
    if re.fullmatch(r"[A-Za-z]{2}", s):
        return True
    if re.match(r"^\s*\d", s) or _STREET_WORD_RE.search(s):
        return False
    return not re.search(r"\d", s) or bool(re.search(r",\s*[A-Za-z]{2}\s+\d{5}", s))


# ══ A person's answer is evidence (8 Oct 2026) ═══════════════════════════════
# The rules above ask whether the DOCUMENTS state a value. On Brent's own
# package the producer answered year built 2001 and protection class 3 for the
# premises, and gap fill carried them to building 2 - the first cut of these
# rules refused them because no document prints them. A value equal to one a
# person supplied (producer, client) is grounded by that person.
_PERSON_SOURCES = frozenset({"producer", "client_arq", "client", "human"})


def _norm_answer(v: Any) -> str:
    s = str(v or "").strip().lower()
    digits = re.sub(r"[^\d]", "", s.split(".")[0])
    return digits if digits and re.fullmatch(r"[\d\s.,%$]+", s) else re.sub(r"\s+", " ", s)


def person_value_facts(facts: Any) -> Dict[str, Set[str]]:
    """{normalised value: the facts a PERSON gave that value for}."""
    out: Dict[str, Set[str]] = {}
    for k, v in (facts or {}).items() if isinstance(facts, dict) else ():
        if isinstance(v, dict) and str(v.get("source") or "").lower() in _PERSON_SOURCES:
            n = _norm_answer(v.get("value"))
            if n:
                out.setdefault(n, set()).add(str(k))
    return out


def person_values(facts: Any) -> Set[str]:
    return set(person_value_facts(facts))


def box_question_facts(field: str, facts: Any, form_id: str = "") -> Set[str]:
    """The facts a box's own question is about: what the stamper reads for it
    (`pdf_service.source_fact_for_field`), its schedule column, the business fact
    a one-premises box twins, the auto grid's own fact for a coverage box
    (`state_auto_grid.box_facts`), and the one documented fallback hop."""
    keys: Set[str] = set()
    try:
        ps = _ps()
        src = ps.source_fact_for_field(field, facts if isinstance(facts, dict) else {}, form_id)
        if src:
            keys.add(str(src))
        m = ps._SCHED_ROW_RE.match(field or "")
        d = ps._schedule_def_for_base(m.group(1)) if m else None
        if d is not None and d.sub_key:
            keys.add(str(d.sub_key))
        twin = ps.premises_twin_key(field)
        if twin:
            keys.add(str(twin))
        # An auto coverage box the 137 / 138 grid reads a fact for (the UM,
        # medical payments, liability and owned-deductible boxes).
        from services.state_auto_grid import box_facts as _auto_box_facts
        keys |= set(_auto_box_facts(field))
        for k in list(keys):
            alt = (getattr(ps, "_FACT_FALLBACKS", {}) or {}).get(k)
            if alt:
                keys.add(str(alt))
    except Exception:                                      # noqa: BLE001
        pass
    return keys


# ══ A business start date is not a policy date (8 Oct 2026) ══════════════════
# ACORD 125 printed BUSINESS START DATE 01/16/2025 after the Business Auto
# Policy was added - the date the common declarations print immediately above
# "Issue Date:", which the equality guard (`pdf_service._policy_metadata_dates`,
# fed by the effective / expiration FACTS) could not know. A 2025 start reads
# as a new venture. Refused when every printing of that date sits beside a
# policy-administration label.
_START_DATE_BOX_RE = re.compile(r"BusinessStart(?:ed)?Date|DateBusinessStarted", re.I)
_POLICY_DATE_LABEL_RE = re.compile(
    r"\b(?:issue[ds]?|issuance|countersign\w*|transaction|printed|processed|"
    r"effective|expiration|expiry|policy\s+period|endorsement|cancel\w*|renewal)\b", re.I)


def _date_printings(value: str, raw_text: str) -> List[re.Match]:
    m = re.fullmatch(r"\s*(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})\s*", value or "")
    if not m:
        return []
    mo, d, y = int(m.group(1)), int(m.group(2)), m.group(3)
    pat = rf"(?<!\d)0?{mo}\s*[/\-.]\s*0?{d}\s*[/\-.]\s*{y}(?!\d)"
    return list(re.finditer(pat, raw_text or ""))


def policy_date_as_business_start(value: Any, raw_text: str) -> bool:
    hits = _date_printings(str(value or ""), raw_text)
    if not hits:
        return False
    return all(_POLICY_DATE_LABEL_RE.search(raw_text[max(0, h.start() - 40):h.end() + 40])
               for h in hits)


# ══ The doors ═════════════════════════════════════════════════════════════════
class _Context:
    """What the rules read about the package, built once per call."""

    def __init__(self, schema: dict, facts: dict, raw_text: str, form_id: str):
        self.schema = schema if isinstance(schema, dict) else {}
        self.facts = facts if isinstance(facts, dict) else {}
        self.raw_text = raw_text or ""
        self.form_id = _base_form(form_id or (self.facts.get("_form_id") if self.facts else ""))
        self._parties: Optional[List[str]] = None
        self._classes: Optional[Set[str]] = None
        self._person_value_facts: Optional[Dict[str, Set[str]]] = None

    @property
    def person_value_facts(self) -> Dict[str, Set[str]]:
        if self._person_value_facts is None:
            self._person_value_facts = person_value_facts(self.facts)
        return self._person_value_facts

    @property
    def parties(self) -> List[str]:
        if self._parties is None:
            self._parties = _party_names(self.facts)
        return self._parties

    @property
    def classes(self) -> Set[str]:
        if self._classes is None:
            self._classes = _classification_wordings(self.facts)
        return self._classes


# ══ Not an answer: a label repeating itself, a summary about the documents ═══
# 8 Oct 2026, run 15f43bba. ACORD 130's company-information box printed
# "CO: CO". And seven stored ACORD 131s (this run's too) printed "Umbrella follows
# form over the underlying coverages (per submitted documents)" - our OWN
# derived `umbrella_follow_form` sentence, which the gap fill copied into the
# underlying-restrictions, other-coverage and tail-coverage boxes. A sentence
# ABOUT "the submitted documents" is a summary, never something a document
# prints; and on the Choice Electric umbrella it was not even true of that
# policy (the Excess policy is the "following form" one).
_SELF_LABELLED_RE = re.compile(r"^\s*([^:]{1,40}?)\s*:\s*([^:]{1,40}?)\s*$")
_SUMMARY_PHRASE_RE = re.compile(
    r"\b(?:submitted|provided|uploaded|attached|supplied|reviewed)\s+"
    r"(?:documents?|documentation|materials|paperwork)\b|"
    r"\b(?:documents?|documentation|paperwork)\s+(?:provided|submitted|uploaded|supplied|reviewed)\b",
    re.I)


# ══ A bureau's number or name is printed as that bureau's (8 Oct 2026) ═══════
# Run 2076fe35: ACORD 130's credit-bureau and rating-bureau boxes printed "3" -
# the Package Policy's "ACCOUNT NUMBER: 3" - with the credit bureau named "Dun
# And Bradstreet Number", which no document mentions. Every stored value ever
# written into these boxes was junk (a tooltip echo, a carrier, an unnamed
# bureau). A number must follow a bureau / D-U-N-S / risk-ID label on its own
# line; a bureau name needs some bureau named in the documents at all.
_BUREAU_BOX_RE = re.compile(r"(?:Credit|Rating)Bureau", re.I)
_BUREAU_LABEL_RE = re.compile(
    r"\bbureau\b|\bd\W?u\W?n\W?s\b|dun\s*(?:&|and)\s*bradstreet|\bd\s*&\s*b\b|"
    r"experian|equifax|transunion|\brisk\s*(?:id|identifier|number|no)\b", re.I)


def bureau_value_without_its_label(field: str, value: Any, raw_text: str) -> bool:
    if not _BUREAU_BOX_RE.search(field or ""):
        return False
    text = str(value or "").strip()
    if not text or not raw_text:
        return False
    labels = list(_BUREAU_LABEL_RE.finditer(raw_text))
    if "Name" in (field or ""):
        return not labels
    digits = re.sub(r"\D", "", text)
    for m in labels:
        tail = raw_text[m.end():m.end() + 40].split("\n", 1)[0]
        if digits:
            if re.search(rf"(?<!\d){digits}(?!\d)", re.sub(r"[\s./-]", "", tail)):
                return False
        elif text.lower() in tail.lower():
            return False
    return True


def is_self_labelled(text: Any) -> bool:
    m = _SELF_LABELLED_RE.match(str(text or ""))
    if not m:
        return False
    a, b = (re.sub(r"[^a-z0-9]", "", g.lower()) for g in m.groups())
    return bool(a) and a == b


def _judge(field: str, value: Any, ctx: _Context) -> Optional[str]:
    """"CODE: detail" when `value` is not an answer for `field`, else None.
    The order is the most specific first."""
    text = str(value or "").strip()
    if not text:
        return None
    tu = _tooltip(ctx.schema, field)
    if is_cross_reference(text) and not _box_asks_for_a_reference(field, tu):
        return f"{REASON_CROSS_REFERENCE}: {text[:40]!r} points at another page"
    if is_self_labelled(text):
        return f"{REASON_SELF_LABELLED}: {text[:40]!r} repeats its own label"
    if _SUMMARY_PHRASE_RE.search(text) and not (
            ctx.raw_text and re.sub(r"\s+", " ", text.lower()) in re.sub(r"\s+", " ", ctx.raw_text.lower())):
        return f"{REASON_SUMMARY}: {text[:40]!r} is a summary of the documents"
    if (ctx.raw_text and not _box_takes_a_title(field, tu)
            and printed_only_as_form_title(text, ctx.raw_text)):
        return f"{REASON_FORM_TITLE}: {text[:40]!r} is printed only as a form title"
    narrative = _is_narrative_box(field)
    if narrative and not _ASKS_FOR_A_NAME_RE.search(_definition(tu)):
        hit = _is_party_name(text, ctx.parties)
        if hit:
            return f"{REASON_PARTY_NAME}: {text[:40]!r} is the name of a party"
    if is_classification_wording(field, text, ctx.schema, ctx.classes):
        return f"{REASON_CLASSIFICATION}: {text[:40]!r} is a rating classification"
    # Nor is it an EXPLANATION (8 Oct 2026): ACORD 130's "do employees travel
    # out of state?" came back Yes, explained by the rating row "CO 001 8742
    # State Act - Salespersons or Collectors-Outside".
    if ("Explanation" in (field or "") or "BusinessType_OtherDescription" in (field or "")) \
            and ctx.classes:
        # A rating ROW leads with its state, location and class code ("CO 001
        # 8742 State Act - ...") - stripped so the wording itself is compared.
        _parts = [re.sub(r"^\s*(?:[A-Z]{2}\s+)?(?:\d{1,4}\s+)?\d{4}\b\s*[-:]?\s*", "", p)
                  for p in re.split(r"\s*;\s*", text) if p.strip()]
        if _parts and all(_class_cores(p) & ctx.classes for p in _parts if p.strip()):
            return f"{REASON_CLASSIFICATION}: {text[:40]!r} is a rating classification, not an explanation"
    if is_one_word_operations(field, text, ctx.schema):
        return f"{REASON_ONE_WORD_OPERATIONS}: {text[:40]!r} is one word"
    if narrative and echoes_its_question(field, text, ctx.schema):
        return f"{REASON_ECHO}: {text[:40]!r} is the box's own question"
    # A PERSON's value is evidence for the question they answered, never for
    # every box that happens to hold the same text (14 Oct 2026, live run
    # `b117f010`): the producer's hydrant distance "500" let the AI's "500"
    # stand as the 140's miles to the fire station and all four exposure
    # distances, and the typed auto liability limit let "1,000,000" stand as
    # the 137's uninsured motorist limits. Round 9's own case still holds: a
    # year built / protection class a person gave prints on building 2's boxes,
    # which ask that same question.
    _said_for = ctx.person_value_facts.get(_norm_answer(text))
    if _said_for and _said_for & box_question_facts(field, ctx.facts, ctx.form_id):
        return None                       # a person stated this value for this question
    if _BUILDING_YEAR_BOX_RE.match(field or "") and year_not_printed_as_a_building_year(text, ctx.raw_text):
        return f"{REASON_YEAR_FROM_A_DATE}: {text[:10]!r} is printed only inside dates"
    if _START_DATE_BOX_RE.search(field or "") and policy_date_as_business_start(text, ctx.raw_text):
        return f"{REASON_POLICY_DATE_AS_START}: {text[:12]!r} is a policy date"
    if cope_answer_without_evidence(field, text, ctx.raw_text, tu):
        return f"{REASON_COPE_WITHOUT_EVIDENCE}: {text[:40]!r} is not stated for this building"
    if _INSURED_ID_BOX_RE.search(field or "") and carrier_code_as_insured_id(text, ctx.raw_text):
        return f"{REASON_CARRIER_CODE_AS_INSURED_ID}: {text[:14]!r} is printed as the carrier's code"
    if other_row_names_a_coverage_with_its_own_boxes(field, ctx.schema, getattr(ctx, "mapped", None)):
        return f"{REASON_COVERAGE_HAS_ITS_OWN_ROW}: the OTHER row names a coverage this form prints itself"
    if _LINE_ONE_BOX_RE.search(field or "") and not_a_street_line(text):
        return f"{REASON_NOT_A_STREET_LINE}: {text[:30]!r} is not a street"
    if bureau_value_without_its_label(field, text, ctx.raw_text):
        return f"{REASON_BUREAU_NOT_STATED}: {text[:30]!r} is not printed as a bureau's"
    return None


def _skip_box(field: str, schema: dict) -> bool:
    """The evidence gate's boxes (Yes/No answers, checkboxes) are not ours."""
    if _field_type(schema, field) == "/Btn":
        return True
    try:
        return bool(_ps()._is_yes_no_field(field, schema))
    except Exception:                                      # noqa: BLE001
        return False


_OTHER_NAMING_BOX_RE = re.compile(
    r"^(?P<prefix>.*Other)(?P<mid>[A-Za-z]*?)(?:Description|Desciption)_(?P<row>[A-N])$")


def _other_row_companions(field: str, schema: dict) -> List[str]:
    """The amount / tick boxes an OTHER row's naming box names, read off the
    form: "GeneralLiability_OtherDeductibleDescription_A" ->
    "...OtherDeductibleAmount_A", "...OtherDeductibleIndicator_A"."""
    m = _OTHER_NAMING_BOX_RE.match(field or "")
    if not m:
        return []
    pat = re.compile(r"^" + re.escape(m.group("prefix") + m.group("mid"))
                     + r"(?:Limit|Premium)?(?:Amount|Indicator)_" + m.group("row") + r"$")
    return [f for f in schema if pat.match(f)]


def refuse_non_answers(mapped: dict, schema: dict, facts: dict, raw_text: str,
                       gpt_filled_set: Optional[set], form_id: str = "") -> Dict[str, str]:
    """Blank every AI value that is not an answer for its box (the classes
    above). Returns {field: "CODE: detail"}; mutates `mapped`. Never raises.

    A paired explanation under a Yes that a RULE stamped (not the AI) is left
    alone: blanking it would make the final coherence sweep remove a
    deterministic answer, and that is not this module's to remove."""
    out: Dict[str, str] = {}
    try:
        if not gpt_filled_set or not isinstance(mapped, dict) or not isinstance(schema, dict):
            return out
        ctx = _Context(schema, facts, raw_text, form_id)
        ctx.mapped = mapped
        ctx.person_values = person_values(facts)
        if ctx.form_id in _FROZEN_FORMS:
            return out
        ai = {f for f in gpt_filled_set
              if f in schema and isinstance(mapped.get(f), str) and mapped.get(f).strip()
              and not _skip_box(f, schema)}
        if not ai:
            return out
        ps = _ps()
        # Every pairing the final coherence sweep enforces (Question codes AND
        # "Other" checkboxes): a box whose question a RULE answered Yes is not
        # ours to empty - the sweep would then remove the rule's own Yes.
        owner = {exp: q for q, exp in ps._question_explanation_pairs(schema).items()}

        def _rule_said_yes(f: str) -> bool:
            q = owner.get(f)
            return bool(q) and q not in gpt_filled_set and \
                str(mapped.get(q) or "").strip().lower() in ps._AFFIRMATIVE_VALUES
        # An OTHER deductible that only names a printed row IS that row: the
        # existing door (`_misfiled_other_deductibles`) moves its amount to the
        # row or clears the whole OTHER row. Refusing its name here first would
        # strand the amount (live run 7's pin), so that door keeps its case.
        try:
            claimed = {d for d, _t, _a in ps._misfiled_other_deductibles(mapped, schema, ai)}
        except Exception:                                  # noqa: BLE001
            claimed = set()
        for f in sorted(option_list_dumps(mapped, schema, ai)):
            if not _rule_said_yes(f):
                out[f] = (f"{REASON_OPTION_LIST}: {str(mapped.get(f))[:40]!r} is one of the box's "
                          f"own examples, copied in order")
        for f in sorted(ai - set(out) - claimed):
            why = _judge(f, mapped.get(f), ctx)
            if why and not _rule_said_yes(f):
                out[f] = why
        for f in sorted(out):
            for c in _other_row_companions(f, schema):
                cv = str(mapped.get(c) or "").strip()
                if c.endswith(tuple(f"Indicator_{r}" for r in "ABCDEFGHIJKLMN")) \
                        and cv.lower() not in ps._AFFIRMATIVE_VALUES:
                    continue                               # an unticked box says nothing
                if c in gpt_filled_set and c not in out and cv:
                    out[c] = f"{REASON_ROW_NAME_REFUSED}: its row's name {f} was refused"
        for f, why in out.items():
            mapped[f] = None
            logger.info("gpt_fill DROP_%s: field=%s - %s", why.split(":", 1)[0], f,
                        why.split(":", 1)[1].strip() if ":" in why else why)
    except Exception as exc:                               # noqa: BLE001
        logger.warning("ai_answer_guards skipped (form=%s): %s", form_id, exc)
    return out


def explanation_non_answer(field: Optional[str], value: Any, schema: dict, facts: dict,
                           raw_text: str = "", form_id: str = "") -> Optional[str]:
    """The evidence gate's door: the reason code when an AI explanation /
    description `value` in box `field` is not an answer, else None. Used by
    `_present`, so a non-answer is never evidence for a Yes and never promotes
    one. Never raises."""
    try:
        if not field or not isinstance(schema, dict) or field not in schema:
            return None
        if _base_form(form_id or (facts or {}).get("_form_id")) in _FROZEN_FORMS:
            return None
        if _skip_box(field, schema):
            return None
        why = _judge(field, value, _Context(schema, facts, raw_text, form_id))
        return why.split(":", 1)[0] if why else None
    except Exception:                                      # noqa: BLE001
        return None
