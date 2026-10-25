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

# Fix C (14 Oct 2026) - an AI value whose ONLY evidence is the wrong source:
# a person's answer to another question, the box's own tooltip example,
# another section's text. See the "Fix C" block above `_judge`.
REASON_ANOTHER_QUESTION = "AI_ANSWER_TO_ANOTHER_QUESTION"
REASON_OWN_PARTY_AS_INTEREST = "AI_INSUREDS_OWN_PARTY_AS_INTEREST"
REASON_TOOLTIP_EXAMPLE = "AI_TOOLTIP_EXAMPLE"
REASON_QUALIFIER_NOT_STATED = "AI_QUALIFIER_NOT_STATED"
REASON_INITIAL_FROM_NAME = "AI_INITIAL_FROM_THE_NAME"
REASON_ADDRESS_NOT_THIS_PERSONS = "AI_ADDRESS_NOT_THIS_PERSONS"
REASON_FACTOR_AS_IDENTIFIER = "AI_FACTOR_AS_IDENTIFIER"
REASON_ROW_REFERENCE = "AI_ROW_REFERENCE_AS_DESCRIPTION"
REASON_BLANK_FORM_LABEL = "AI_BLANK_FORM_LABEL"
REASON_SYMBOL_NOT_STATED = "AI_SYMBOL_NOT_STATED"
REASON_COVERAGE_ROW = "AI_COVERAGE_ROW_AS_EXPLANATION"
# Recorded by `pdf_service._blank_unnamed_other_rows` (an AI amount in an OTHER
# row whose naming box is empty); the sentence lives here with the others.
REASON_OTHER_ROW_UNNAMED = "AI_OTHER_ROW_UNNAMED"

# P15 (21 Oct 2026, 25sepChanges.md Z31-W). The first two are this module's
# rules; the last two are recorded by `pdf_service` (the ACORD 126 products row,
# the ACORD 127 garaging column) and their sentences live here with the others.
REASON_RATING_DATE_OTHER_TERM = "AI_RATING_DATE_NOT_THE_PROPOSED_TERM"
REASON_ITEM_LABEL = "AI_DOCUMENT_ITEM_LABEL"
REASON_PRODUCT_IS_OPERATIONS = "AI_PRODUCT_IS_THE_BUSINESS_DESCRIPTION"
REASON_GARAGING_WITHOUT_A_VEHICLE = "AI_GARAGING_WITHOUT_A_VEHICLE"
# Z41 (25 Oct 2026, live run f575160b) - see the Z41 section below `_judge`.
REASON_BOX_LABEL = "AI_BOX_LABEL_AS_VALUE"
REASON_SCHEDULE_PERSON = "AI_PERSON_FROM_ANOTHER_SCHEDULE"
REASON_STATE_NOT_THIS_FORMS = "AI_STATE_NOT_THIS_FORMS"
REASON_LICENCE_STATE_AS_ADDRESS = "AI_LICENCE_STATE_AS_ADDRESS"
REASON_OTHER_LINES_FORM = "AI_ANOTHER_LINES_FORM"
REASON_AMOUNT_NOT_FOR_THIS_COVERAGE = "AI_AMOUNT_NOT_STATED_FOR_THIS_COVERAGE"
REASON_ISSUE_DATE = "AI_ISSUE_DATE"
REASON_PERSON_ANSWER_ELSEWHERE = "AI_PERSON_ANSWER_FOR_ANOTHER_QUESTION"

REASON_CODES = frozenset({
    REASON_CROSS_REFERENCE, REASON_PARTY_NAME, REASON_ECHO, REASON_ONE_WORD_OPERATIONS,
    REASON_CLASSIFICATION, REASON_FORM_TITLE, REASON_OPTION_LIST, REASON_ROW_NAME_REFUSED,
    REASON_YEAR_FROM_A_DATE, REASON_POLICY_DATE_AS_START, REASON_COPE_WITHOUT_EVIDENCE,
    REASON_CARRIER_CODE_AS_INSURED_ID, REASON_COVERAGE_HAS_ITS_OWN_ROW, REASON_NOT_A_STREET_LINE,
    REASON_SELF_LABELLED, REASON_SUMMARY, REASON_BUREAU_NOT_STATED,
    REASON_ANOTHER_QUESTION, REASON_TOOLTIP_EXAMPLE, REASON_QUALIFIER_NOT_STATED,
    REASON_INITIAL_FROM_NAME, REASON_ADDRESS_NOT_THIS_PERSONS, REASON_FACTOR_AS_IDENTIFIER,
    REASON_ROW_REFERENCE, REASON_BLANK_FORM_LABEL, REASON_SYMBOL_NOT_STATED,
    REASON_OTHER_ROW_UNNAMED, REASON_COVERAGE_ROW,
    REASON_RATING_DATE_OTHER_TERM, REASON_ITEM_LABEL, REASON_PRODUCT_IS_OPERATIONS,
    REASON_GARAGING_WITHOUT_A_VEHICLE,
    REASON_BOX_LABEL, REASON_SCHEDULE_PERSON, REASON_STATE_NOT_THIS_FORMS,
    REASON_LICENCE_STATE_AS_ADDRESS, REASON_OTHER_LINES_FORM,
    REASON_AMOUNT_NOT_FOR_THIS_COVERAGE, REASON_ISSUE_DATE, REASON_PERSON_ANSWER_ELSEWHERE,
    REASON_OWN_PARTY_AS_INTEREST,
})

# What the producer reads in the needs-attention list. Plain words, no
# em-dashes, never the refused value (it belongs to nothing on this form).
_HELD_BACK: Dict[str, str] = {
    REASON_BOX_LABEL: "The AI copied the box's own label into it, so it was left blank.",
    REASON_SCHEDULE_PERSON: ("The AI listed a person your documents name only on another "
                             "schedule (for example the drivers), so it was left blank."),
    REASON_STATE_NOT_THIS_FORMS: ("The AI put another state on this state's form, so it was "
                                  "left blank."),
    REASON_LICENCE_STATE_AS_ADDRESS: ("The AI used a driver's licence state as a mailing "
                                      "address state, so it was left blank."),
    REASON_OTHER_LINES_FORM: ("The AI listed another policy's form or endorsement here, so it "
                              "was left blank."),
    REASON_AMOUNT_NOT_FOR_THIS_COVERAGE: ("Your documents do not print this amount for this "
                                          "coverage, so the AI's value was left blank."),
    REASON_ISSUE_DATE: ("The AI used a document's issue date here, so it was left blank."),
    REASON_PERSON_ANSWER_ELSEWHERE: ("The AI used an answer given for another question, so it "
                                     "was left blank."),
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
    REASON_OWN_PARTY_AS_INTEREST: ("The AI put the insured's own owner, contact or name here. An "
                                   "additional interest is a third party (a lender, loss payee or "
                                   "additional insured), so it was left blank."),
    REASON_ANOTHER_QUESTION: ("The AI copied an answer you gave to a different question here. "
                              "Nothing says it answers this one, so it was left blank."),
    REASON_TOOLTIP_EXAMPLE: ("The AI used the form's own example answer for this box, which your "
                             "documents do not state, so it was left blank."),
    REASON_QUALIFIER_NOT_STATED: ("Your documents do not state this value for what this box asks "
                                  "(such as subcontracted work or foreign sales), so the AI's answer "
                                  "was left blank."),
    REASON_INITIAL_FROM_NAME: ("The AI made this middle initial out of the person's own first or "
                               "last name, so it was left blank."),
    REASON_ADDRESS_NOT_THIS_PERSONS: ("Your documents do not print this address for this person. The "
                                      "AI used another address, so it was left blank."),
    REASON_FACTOR_AS_IDENTIFIER: ("The AI put a rating factor here. This box asks for an "
                                  "identifier, so it was left blank."),
    REASON_ROW_REFERENCE: ("The AI put a location or building number here, not a description, so "
                           "it was left blank."),
    REASON_BLANK_FORM_LABEL: ("The AI copied an unfilled label from a policy form here, not a value, "
                              "so it was left blank."),
    REASON_SYMBOL_NOT_STATED: ("Your documents do not state this covered auto symbol, so the AI's "
                               "answer was left blank."),
    REASON_OTHER_ROW_UNNAMED: ("The AI put an amount in an \"other\" row without naming what it is "
                               "for, so it was left blank."),
    REASON_COVERAGE_ROW: ("The AI copied a row of a policy's coverage table here, which explains "
                          "nothing about this question, so it was left blank."),
    REASON_RATING_DATE_OTHER_TERM: ("The AI put a date from another policy term here. A rating date "
                                    "belongs to the policy being applied for, so it was left blank."),
    REASON_ITEM_LABEL: ("The AI copied a numbered item from your documents here (such as \"Item 3A\"), "
                        "and what it holds does not answer this box, so it was left blank."),
    REASON_PRODUCT_IS_OPERATIONS: ("The AI put the description of the business here. This row asks for "
                                   "a product or service the business sells, so it was left blank."),
    REASON_GARAGING_WITHOUT_A_VEHICLE: ("No vehicle is listed on this row, so the AI's garaging address "
                                        "for it was left blank."),
}


def held_back_sentence(reason: Any) -> Optional[str]:
    """The needs-attention sentence for one of this module's reason codes
    ("AI_CROSS_REFERENCE" or "AI_CROSS_REFERENCE: detail"), else None."""
    code = str(reason or "").split(":", 1)[0].strip()
    return _HELD_BACK.get(code)


# Forms the owner froze on 14 Sep 2026 - no new guard acts on them. ACORD 141
# left the list on 25 Oct 2026 (Z41): its label is the template's own and the
# owner's run f575160b showed its AI values unguarded (cyber limits as crime
# limits, the drivers as employees, the carrier's office as the auditor).
_FROZEN_FORMS = frozenset({"ACORD_160"})


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


def tooltip_options(tooltip: str, minimum: int = _MIN_OPTIONS) -> List[str]:
    """ACORD's example answers in the tooltip's own order, folded; [] when the
    tooltip lists fewer than `minimum` (three: a LIST of options)."""
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
    return opts if len(opts) >= max(1, minimum) else []


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
_IMPROVEMENT_YEAR_RE = re.compile(r"^BuildingImprovement_(?P<k>\w+?)Year_(?P<r>[A-N])$")


def improvement_year_is_another_year(field: str, value: Any, mapped: Any) -> bool:
    """An AI improvement year (wiring / plumbing / heating / other) that is
    just the same building's ROOF year or YEAR BUILT already on the form (live
    85e51d02, 25 Oct: "other improvement year" 2018 = the typed roof year).
    A roof year is never judged against itself."""
    m = _IMPROVEMENT_YEAR_RE.match(field or "")
    if not m or m.group("k") == "Roofing" or not isinstance(mapped, dict):
        return False
    v = str(value or "").strip()
    if not re.fullmatch(r"(?:19|20)\d{2}", v):
        return False
    r = m.group("r")
    others = {str(mapped.get(f"BuildingImprovement_RoofingYear_{r}") or "").strip(),
              str(mapped.get(f"CommercialStructure_BuiltYear_{r}") or "").strip()}
    return v in others


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
    return _attribute_box_unstated(field, value, raw_text, tooltip, _COPE_ATTRIBUTE_BOXES)


def _attribute_box_unstated(field: str, value: Any, raw_text: str, tooltip: str,
                            table: Tuple[Tuple[re.Pattern, re.Pattern, int], ...]) -> bool:
    """The attribute rule's one body, for any (box, attribute, window) table:
    True when `field` is one of the table's boxes and `raw_text` (the evidence
    read) never states its attribute with this answer beside it."""
    text = str(value or "").strip()
    if not text or not raw_text:
        return False
    for box_re, attr_re, width in table:
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
_PARTY_ADDRESS_BOX_RE = re.compile(
    r"^(?:NamedInsured|Producer)_MailingAddress_(?:LineOne|LineTwo|CityName|StateOrProvinceCode|"
    r"PostalCode)_[A-N]$")


_STREET_SUFFIXES = {"rd": "road", "st": "street", "ave": "avenue", "av": "avenue", "dr": "drive",
                    "blvd": "boulevard", "ln": "lane", "hwy": "highway", "pkwy": "parkway",
                    "ct": "court", "pl": "place", "cir": "circle", "ste": "suite"}


def _street_spellings(value: Any) -> List[str]:
    v = str(value or "")
    out = [v]
    longer = re.sub(r"\b([A-Za-z]{2,4})\b\.?",
                    lambda m: _STREET_SUFFIXES.get(m.group(1).lower(), m.group(0)), v)
    shorter_map = {b: a for a, b in _STREET_SUFFIXES.items() if a not in ("av",)}
    shorter = re.sub(r"\b([A-Za-z]{4,9})\b",
                     lambda m: shorter_map.get(m.group(1).lower(), m.group(0)), v)
    for x in (longer, shorter):
        if x != v and x not in out:
            out.append(x)
    return out


def _office_address(value: Any, raw_text: str, own_names: Any = (), party_names: Any = ()) -> bool:
    try:
        from services.insured_scope import address_is_a_party_office
        # The model abbreviates a printed street ("26777 HALSTED ROAD" ->
        # "26777 Halsted Rd"): each spelling is tried, the first one printed
        # anywhere decides.
        for v in _street_spellings(value):
            if address_is_a_party_office(v, [raw_text], own_names=own_names,
                                         party_names=party_names):
                return True
        return False
    except Exception:                                      # noqa: BLE001
        return False


def _insured_own_names(facts: Any) -> list:
    try:
        from services.insured_scope import _own_names
        return _own_names(facts)
    except Exception:                                      # noqa: BLE001
        return []


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
    # The rating worksheet's OTHER row, written "<prefix>Other_CoverageDescription"
    # (ACORD 130's premium worksheet: "optional factors, charges or credits").
    m = _OTHER_FACTOR_DESC_RE.match(field or "") or _OTHER_FACTOR_ROW_RE.match(field or "")
    if m:
        desc = f"{m.group('p')}Other_CoverageDescription_{m.group('r')}"
        if desc in (schema or {}):
            return _rating_row_named(str((mapped or {}).get(desc) or ""), schema, m.group("p"))
    return False


# ── X2 (14 Oct 2026): the WORKSHEET's OTHER row is not a factor it prints ────
# ACORD 130's premium worksheet came back with OTHER rows "CO 9812: Employers
# Liab Incr Limits 1.1000 422.00", "CO 9664: Small Deductible 6.5000 -2,495.00"
# and "Experience Modification Factor: 0.92" - while the worksheet prints its
# own INCREASED LIMITS, DEDUCTIBLE and EXPERIENCE OR MERIT rows. A rating line
# carries a code, a rate and a premium around its name and abbreviates it, so
# the letters-in-a-box-name test above never matched. Here the OTHER row names
# a printed row when every word of that row's name ("IncreasedLimits" ->
# increased, limits) is a word of the value or abbreviated by one ("incr");
# "XOrY" rows ("ExperienceOrMerit") are named by either. Only this spelling of
# the OTHER row (the 130 worksheet; 160 is frozen) - the OTHER COVERAGE rows of
# 25 / 126 / 131 / 137 keep the rule above.
_OTHER_FACTOR_DESC_RE = re.compile(r"^(?P<p>\w+_)Other_CoverageDescription_(?P<r>[A-Z])$")
_OTHER_FACTOR_ROW_RE = re.compile(r"^(?P<p>\w+_)Other_(?!CoverageDescription_)\w+_(?P<r>[A-Z])$")
_ROW_NAME_ELEMENT_WORDS = frozenset({"amount", "indicator", "code", "description", "count", "identifier",
                                     "number", "percent", "date", "name", "type", "text", "and", "of",
                                     "the"})
_SPELLINGS = {"labour": "labor"}


def _word_matches(value_word: str, row_word: str) -> bool:
    v, r = _SPELLINGS.get(value_word, value_word), _SPELLINGS.get(row_word, row_word)
    if v == r:
        return True
    if len(v) >= 3 and r.startswith(v):           # "incr" for increased, "liab" for liability
        return True
    return len(r) >= 4 and v.startswith(r)          # "deductibles" for deductible


def _rating_row_named(text: str, schema: dict, prefix: str) -> bool:
    vwords = re.findall(r"[a-z]+", text.lower())
    if not vwords:
        return False
    for seg in {f[len(prefix):].split("_")[0] for f in schema or {} if f.startswith(prefix)}:
        if not seg or "Other" in seg:
            continue
        words = [w.lower() for w in re.findall(r"[A-Z][a-z]*|[a-z]+", seg)]
        groups: List[List[str]] = [[]]
        for w in words:
            if w == "or":
                groups.append([])
            elif w not in _ROW_NAME_ELEMENT_WORDS:
                groups[-1].append(w)
        for grp in groups:
            if grp and all(any(_word_matches(v, w) for v in vwords) for w in grp):
                return True
    return False


# ══ Z37 (24 Oct 2026): the worksheet's OTHER row named only by a label ═══════
# ACORD 130's premium block "Other" rows ("optional factors, charges or
# credits") came back holding "Workers Compensation", "Employers Liability",
# "Premium" - the section's own headings, naming no factor, charge or credit -
# with the line's premium beside them. A name made only of line names and the
# premium block's own words names nothing; the row's amount / factor go with it.
_PREMIUM_BLOCK_LABEL_WORDS = frozenset({
    "workers", "worker", "compensation", "comp", "wc", "employers", "employer", "liability", "liab",
    "el", "part", "one", "two", "three", "premium", "premiums", "total", "subtotal", "estimated",
    "annual", "other", "others", "coverage", "coverages", "policy", "state", "states", "rating",
    "rate", "rates", "factor", "factors", "charge", "charges", "credit", "credits", "optional",
    "required", "applicable", "modified", "modification", "amount", "description", "insurance",
    "general", "auto", "automobile", "umbrella", "property", "line", "lines", "section",
    "information", "and", "or", "of", "the", "for", "a", "an", "&",
})


def other_factor_row_is_a_label(field: str, schema: dict, mapped: dict) -> bool:
    """Is this box part of a worksheet OTHER row whose name is only a label
    (a line name or the premium block's own words)? Read off the row's naming
    box, so its amount and factor follow it."""
    m = _OTHER_FACTOR_DESC_RE.match(field or "") or _OTHER_FACTOR_ROW_RE.match(field or "")
    if not m:
        return False
    desc = f"{m.group('p')}Other_CoverageDescription_{m.group('r')}"
    if desc not in (schema or {}):
        return False
    text = re.sub(r"\$?\d[\d,.]*%?", " ", str((mapped or {}).get(desc) or "").lower())
    words = re.findall(r"[a-z]+", text)
    return bool(words) and all(w in _PREMIUM_BLOCK_LABEL_WORDS for w in words)


# ══ An explanation that is only a coverage schedule row (W10, 14 Oct 2026) ═══
# ACORD 131's "has any product, work, accident or location been excluded,
# uninsured or self-insured from any previous coverage?" came back Yes, explained
# by "EXCLUDED Employee Benefits Liability Each Employee Annual Aggregate" - the
# umbrella's OWN schedule-of-underlying row with its amounts gone: a status, a
# line's name and its limit labels. An explanation says why; a table row whose
# words are only a line, a coverage status and limit-basis labels explains no
# product, work or location. Questions about insurance may still be answered
# with a line ("tail bought on the General Liability" stays - it says something).
_COVERAGE_STATUS_RE = re.compile(r"\b(?:excluded|exclusion|included|not\s+covered|covered)\b", re.I)
_LIMIT_BASIS_WORDS = frozenset({"each", "employee", "employees", "annual", "aggregate", "occurrence",
                                "accident", "person", "claim", "claims", "policy", "limit", "limits",
                                "per", "any", "one", "disease", "injury", "bodily", "property", "damage"})
_LINE_TAIL_WORDS = frozenset({"liability", "liab", "coverage", "insurance"})


def is_coverage_schedule_row(value: Any) -> bool:
    s = str(value or "")
    words = re.findall(r"[a-z]+", _COVERAGE_STATUS_RE.sub(" ", s.lower()))
    if not words or not _COVERAGE_STATUS_RE.search(s):
        return False
    try:
        from services.lob_canon import canon_line
    except Exception:                                      # noqa: BLE001
        return False
    # The line's NAME opens the row: the shortest prefix the canon reads as a
    # line, at most four words, whose first word the canon needs (so "roofing
    # work from the prior GL policy" is prose that mentions a line, not a row).
    for k in range(1, min(len(words), 4) + 1):
        if canon_line(" ".join(words[:k])):
            if k > 1 and canon_line(" ".join(words[1:k])):
                return False
            rest = words[k:]
            return (bool(rest) and all(w in _LIMIT_BASIS_WORDS or w in _LINE_TAIL_WORDS for w in rest)
                    and any(w in _LIMIT_BASIS_WORDS for w in rest))
    return False


_TABLE_CELL_DATA_RE = re.compile(r"^\s*(?:\$?[\d,.]+%?|\d{1,2}/\d{1,2}/\d{2,4}|[A-Z]{2})\s*$")


def is_data_table_row(value: Any) -> bool:
    """A spreadsheet / schedule row ("Name | 05/04/1997 | CO | 02/03/2025 | 7"):
    three or more " | " cells, two or more of them bare data (a number, an
    amount, a date or a two-letter code). Prose that quotes one cell is not."""
    cells = [c.strip() for c in str(value or "").split("|")]
    if len(cells) < 3:
        return False
    return sum(1 for c in cells if c and _TABLE_CELL_DATA_RE.match(c)) >= 2


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


# ══ P15-1 (21 Oct 2026): a rating date belongs to the policy applied for ═════
# ACORD 130's RATING EFFECTIVE DATE ("the earliest date that a specific
# modification is applied to a policy") and NORMAL ANNIVERSARY RATING DATE ("the
# rates used are normally in effect on the effective date of the policy")
# describe the policy this application is FOR. No rule fills them - gap fill
# does - and on Choice Electric's renewal for 01/01/2026-27 (runs ba7c709d,
# b117f010) and Brent's 17 Oct run (proposed 01/01/2027) both printed 01/01/2025:
# the expiring WC term's start, the only rating date its dec prints.
#
# Structural, by the box's own name and declared type: a DATE box whose name
# says it holds a rating date - across the 17 schemas exactly those two ACORD
# 130 boxes (pinned by the build-22 test). An AI date there is refused when it
# falls outside the proposed term the same form prints (before its effective
# date, or on / after its expiration). With no proposed date printed, the
# proposed effective date fact decides; with none at all, the term the merge
# moved to prior_* does (a date before it ended belongs to it); with no term
# known, nothing is judged. A date inside the proposed term stands, and no date
# is ever written. ACCEPTED: NCCI's rule for a cancelled or short-term policy
# (enter the ORIGINAL effective date, which falls before the proposed one) is
# refused when the AI writes it; a person's date is never judged.
_RATING_DATE_BOX_RE = re.compile(r"(?:Rating\w*Date|Anniversary\w*Date)_[A-N]$")
_PROPOSED_TERM_BOXES = ("Policy_EffectiveDate_A", "Policy_ExpirationDate_A")
_DATE_IN_TEXT_RE = re.compile(
    r"\b\d{4}-\d{1,2}-\d{1,2}\b|\b\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}\b|"
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}\b",
    re.I)


def is_rating_date_box(field: str, schema: Any) -> bool:
    """A box that asks for a RATING date of the policy applied for."""
    return bool(_RATING_DATE_BOX_RE.search(field or "")) and \
        _tooltip(schema, field).strip().lower().startswith("enter date")


def _iso_date(value: Any) -> Optional[str]:
    try:
        from services.normalization import normalize_date
        return normalize_date(str(value or "").strip()) or None
    except Exception:                                      # noqa: BLE001
        return None


def _dates_in(value: Any) -> List[str]:
    """Every date `value` holds, ISO: the whole value, else each date in it
    ("01/01/2025 TO 01/01/2026" holds two)."""
    whole = _iso_date(value)
    if whole:
        return [whole]
    return [d for d in (_iso_date(m.group(0)) for m in _DATE_IN_TEXT_RE.finditer(str(value or ""))) if d]


def _proposed_term(mapped: Any, facts: Any) -> Tuple[Optional[str], Optional[str]]:
    """(effective, expiration) of the proposed term, ISO: the form's own header
    first, then the facts. A backwards pair bounds nothing after its start."""
    m = mapped if isinstance(mapped, dict) else {}
    eff, exp = _iso_date(m.get(_PROPOSED_TERM_BOXES[0])), _iso_date(m.get(_PROPOSED_TERM_BOXES[1]))
    if not eff:
        eff, exp = _iso_date(_fv(facts, "effective_date")), _iso_date(_fv(facts, "expiration_date"))
    elif not exp:
        exp = _iso_date(_fv(facts, "expiration_date"))
    if eff and exp and exp <= eff:
        exp = None
    return eff, exp


def rating_date_outside_the_term(field: str, value: Any, schema: Any, mapped: Any,
                                 facts: Any) -> bool:
    """True when `value`, in a rating-date box, holds a date of another term."""
    if not is_rating_date_box(field, schema):
        return False
    dates = _dates_in(value)
    if not dates:
        return False                       # no date read: another rule's, or nobody's
    eff, exp = _proposed_term(mapped, facts)
    if eff:
        return any(d < eff or (exp is not None and d >= exp) for d in dates)
    ended = _iso_date(_fv(facts, "prior_expiration_date"))
    return bool(ended) and any(d < ended for d in dates)


# ══ P15-4 (21 Oct 2026): a document's item label is not part of the value ════
# Run b117f010's ACORD 130 printed "Item 3A State: CO" - the WC information
# page's ITEM reference ("Item 3. A. Worker's Compensation Insurance: ... the
# states listed here: CO") and a field label, kept with the value. A value that
# OPENS with a document item / section / part reference ("Item 3A", "Item 3.A.",
# "Item 4:", "Section 2 -", "Part One:", "Section II") followed by a field label
# and a colon is the model copying a labelled line out of a document.
#
# Strip or refuse, decided by the box: what follows the label prints when the
# label names what the box asks (a word of the box's own tooltip definition or
# of its name's last segment) and the value fits the box's declared type
# (`pdf_service._rejects_declared_type`) and says something
# (`answer_semantics.is_placeholder_text`); otherwise the box is left blank.
#
# Narrow on purpose: the reference word stands alone ("Part-time", "Partners",
# "Itemized", "Items" are words, not references); its designator is short - one
# or two digits with an optional letter, a roman numeral, a number word or one
# letter ("Section 179", "Part 135" are statute and regulation numbers) - and is
# set off from the label; and BOTH the label and its colon must follow
# ("Section 8 housing", "Item 1 of 3", "Item 3A: CO" are untouched). AI text
# boxes only; Yes/No boxes and checkboxes are the evidence gate's; ACORD 141 /
# 160 are frozen.
_ITEM_NUMBER_WORDS = r"(?:one|two|three|four|five|six|seven|eight|nine|ten)"
_DOC_ITEM_LABEL_RE = re.compile(
    r"^\s*(?P<ref>item|section|part)(?![a-z])\s*(?:no\.?\s*|#\s*)?"
    r"(?P<des>\d{1,2}(?!\d)(?:\s*\.?\s*\(?[a-z]\)?(?![a-z]))?"
    r"|[ivx]{1,4}(?![a-z])|" + _ITEM_NUMBER_WORDS + r"(?![a-z])|[a-z](?![a-z]))"
    r"(?:\s*[.):\-–—]+\s*|\s+)"
    r"(?P<label>[a-z][a-z'’&/\- ]{0,48}?)\s*:\s*(?P<value>.*?)\s*$",
    re.I | re.S)
_LABEL_FILLER = frozenset({
    "the", "of", "and", "or", "a", "an", "for", "to", "in", "on", "by", "per", "with", "at",
    "from", "is", "are", "as", "its", "this", "that", "any", "all", "each", "if", "be"})
# A label may OPEN with these and still be a label ("Each Accident", "Per
# Claim" - the limit labels of every dec); any other filler word first is prose
# ("Item 7 of the Declarations to include: ...").
_LABEL_QUANTIFIERS = frozenset({"each", "per"})
_CAMEL_WORD_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+")


def _label_stem(w: str) -> str:
    """One spelling per word, the same for a label and a box: plurals, -ed and
    -ing off, then a final e ("Named" = "Name", "Rating" = "Rate", "States" =
    "State" = "Stated"). Consistency, not linguistics - both sides go through it."""
    if len(w) > 4 and w.endswith("ies"):
        w = w[:-3] + "y"
    elif len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        w = w[:-1]
    if len(w) > 4 and w.endswith("ed"):
        w = w[:-2]
    elif len(w) > 5 and w.endswith("ing"):
        w = w[:-3]
    if len(w) > 3 and w.endswith("e"):
        w = w[:-1]
    return w


def _word_stems(text: Any) -> Set[str]:
    out: Set[str] = set()
    t = str(text or "").lower().replace("’", "'").replace("'s", "")
    for w in re.findall(r"[a-z]+", t):
        if len(w) < 2 or w in _LABEL_FILLER:
            continue
        out.add(_label_stem(w))
    return out


# The words of a data element's name that say only its TYPE ("FullName",
# "LimitAmount", "StateOrProvinceCode", "EffectiveDate") - what is left names it.
# "limit" is ACORD's own type declaration ("Enter limit:"), like "amount".
_DATA_TYPE_WORDS = frozenset({
    "code", "amount", "identifier", "indicator", "description", "text", "number", "count",
    "name", "full", "date", "type", "value", "total", "limit"})
_DATA_TYPE_STEMS = frozenset(_label_stem(w) for w in _DATA_TYPE_WORDS)


def _label_names_the_box(label: str, field: str, schema: Any) -> bool:
    """The label names what the box asks, three ways at once:
      * every word of it is a word of the box - its data element, its tooltip
        definition or, for an explanation, the question it explains;
      * one of them is the data element's own;
      * on a data box, it names the element: every word one of the element's
        alternatives keeps beyond its type ("StateOrProvinceCode" = state |
        province; "CityName" = city; "FullName" = anything that names it).
    Measured over the 17 schemas with labelled probes: with one shared word
    alone, "Item 1 Name of Insured: ..." stripped into the producer's, the
    insurer's and the CITY box, and "Item 2 Policy Period: <date>" into the
    audit FREQUENCY and EXPIRATION boxes; all of the label must fit.
    The data element is the name's last segment and, when the name has three
    or more, the one before it ("GeneralLiability_EachOccurrence_LimitAmount"
    is an each occurrence limit); a two-segment name's first segment is its
    OWNER ("Policy_", "NamedInsured_"), never the element."""
    words = _word_stems(label)
    if not words:
        return False
    segments = _element_segments(field)
    own: Set[str] = set()
    for seg in segments:
        own |= _word_stems(" ".join(_CAMEL_WORD_RE.findall(seg)))
    box = own | _word_stems(_definition(_tooltip(schema, field))) | \
        _word_stems(" ".join(_question_words(schema, field)))
    if not (words <= box and words & own):
        return False
    if _is_narrative_box(field):
        return True                        # an explanation is named by its question
    return any(_word_stems(" ".join(_CAMEL_WORD_RE.findall(alt))) - _DATA_TYPE_STEMS <= words
               for seg in segments for alt in re.split(r"Or(?=[A-Z])", seg))


def _element_segments(field: str) -> Tuple[str, ...]:
    """The segments of a box's name that are its data element: the last one,
    and the one before it when the name has three or more (row letter off)."""
    m = _ROW_RE.match(field or "")
    parts = (m.group("base") if m else (field or "")).split("_")
    return tuple(parts[-2:]) if len(parts) >= 3 else (parts[-1],)


# ── The label must pick out THIS box (review of P15-4, 21 Oct) ───────────────
# A generic label ("State", "Limits", "Each Accident") names an element several
# parties / sections of one form print: on ACORD 130 "Item 3A State: CO" names
# the producer's, the insured's mailing, every location's, Part 1's, Part 3's
# and the individuals' state. Stripped into the insured's mailing state it
# prints a clean "CO" that passes the raw-text check - the label was the only
# sign the value belonged to WC Item 3A. So the stripped value prints only when
# the label, read against EVERY data box of the form, comes down to this box's
# element (its rows are one element):
#   1. the label names one element on the form; or
#   2. the document reference itself is in the element's name ("Part One -
#      State: CO" -> WorkersCompensation_PartOne_...; tooltips are not read,
#      Part 3's says "states not listed in Part 1"); or
#   3. the label spells the box's WHOLE name - every word of every segment
#      beyond its type, and nothing the name does not say ("Name of Insured" ->
#      NamedInsured_FullName, not the insured's inspection contact). The
#      element alone is not enough: "Each Occurrence" spells the element of
#      ACORD 131's underlying GL box (GeneralLiability_EachOccurrence_
#      LimitAmount) and not the umbrella's (ExcessUmbrella_Umbrella_
#      EachOccurrenceAmount) only by how ACORD named them - an umbrella's
#      $5,000,000 would have stripped into the GL box (C23's shape).
# Otherwise it is refused: blank over a value whose meaning nothing states.
# An explanation box is not judged this way - its words carry their own
# meaning and the evidence guards judge them.
_NUMBER_WORD_DIGITS = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
                       "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10"}
_ROMAN_DIGITS = {"i": "1", "ii": "2", "iii": "3", "iv": "4", "v": "5", "vi": "6", "vii": "7",
                 "viii": "8", "ix": "9", "x": "10"}
_REFERENCE_WORDS = ("item", "section", "part")


def _reference_key(ref: Any, des: Any) -> str:
    """"Part" + "One" / "1" / "I" -> "part1"; "Item" + "3.A." -> "item3a"."""
    d = re.sub(r"[^a-z0-9]", "", str(des or "").lower())
    return str(ref or "").lower() + _NUMBER_WORD_DIGITS.get(d, _ROMAN_DIGITS.get(d, d))


def _box_reference_keys(field: str) -> Set[str]:
    """The document references a box's NAME spells ("PartOne" -> part1)."""
    m = _ROW_RE.match(field or "")
    words = [w.lower() for w in _CAMEL_WORD_RE.findall(m.group("base") if m else (field or ""))]
    return {_reference_key(a, b) for a, b in zip(words, words[1:])
            if a in _REFERENCE_WORDS and (b in _NUMBER_WORD_DIGITS or b in _ROMAN_DIGITS)}


def _spells_the_name(words: Set[str], field: str) -> bool:
    """Every word of every segment of the box's name (beyond its type; one
    alternative of a "StateOrProvince" segment) is in the label, and every
    word of the label is in the name."""
    m = _ROW_RE.match(field or "")
    segments = (m.group("base") if m else (field or "")).split("_")
    name_words: Set[str] = set()
    for seg in segments:
        name_words |= _word_stems(" ".join(_CAMEL_WORD_RE.findall(seg)))
    if not words <= name_words:
        return False
    return all(any(_word_stems(" ".join(_CAMEL_WORD_RE.findall(alt))) - _DATA_TYPE_STEMS <= words
                   for alt in re.split(r"Or(?=[A-Z])", seg))
               for seg in segments)


_LABEL_BOXES_CACHE: List[Tuple[Any, str, Dict[str, List[str]]]] = []


def _boxes_the_label_names(label: str, schema: dict) -> Dict[str, List[str]]:
    """{element (name minus row letter): its boxes} for every data box of the
    form the label names. Cached per schema object and label."""
    key = " ".join(sorted(_word_stems(label)))
    for ref, k, out in _LABEL_BOXES_CACHE:
        if ref is schema and k == key:
            return out
    out: Dict[str, List[str]] = {}
    for f in schema:
        if _is_narrative_box(f) or _skip_box(f, schema) or not _label_names_the_box(label, f, schema):
            continue
        m = _ROW_RE.match(f)
        out.setdefault(m.group("base") if m else f, []).append(f)
    _LABEL_BOXES_CACHE.append((schema, key, out))
    del _LABEL_BOXES_CACHE[:-8]
    return out


def _label_picks_out_the_box(label: str, ref_key: str, field: str, schema: Any) -> bool:
    """Rules 1-3 above, in order, each narrowing what the one before left."""
    if _is_narrative_box(field) or not isinstance(schema, dict):
        return True
    m = _ROW_RE.match(field or "")
    mine = m.group("base") if m else field
    named = dict(_boxes_the_label_names(label, schema))
    named.setdefault(mine, [field])
    pool = set(named)
    words = _word_stems(label)
    for narrow in (lambda b: ref_key in _box_reference_keys(named[b][0]),
                   lambda b: _spells_the_name(words, named[b][0])):
        if len(pool) == 1:
            break
        hit = {b for b in pool if narrow(b)}
        if hit:
            pool = hit
    return pool == {mine}


def strip_document_item_label(field: str, value: Any,
                              schema: Any) -> Optional[Tuple[Optional[str], Optional[str]]]:
    """None when `value` carries no document item label; otherwise
    (the value to print, None) or (None, "AI_DOCUMENT_ITEM_LABEL: detail")."""
    m = _DOC_ITEM_LABEL_RE.match(str(value or ""))
    if not m:
        return None
    label, rest = m.group("label").strip(), m.group("value").strip()
    first = label.split()[0].lower()
    if first in _LABEL_FILLER and first not in _LABEL_QUANTIFIERS:
        return None                        # "Item 7 of the Declarations ...:" is prose

    why = f"{REASON_ITEM_LABEL}: {str(value)[:40]!r} is a line copied with its document item label"
    if not rest or not _label_names_the_box(label, field, schema):
        return None, why
    if not _label_picks_out_the_box(label, _reference_key(m.group("ref"), m.group("des")),
                                    field, schema):
        return None, f"{why}; {label!r} names more than one box on this form"
    try:
        from services.answer_semantics import is_placeholder_text
        if is_placeholder_text(rest):
            return None, why
    except Exception:                                      # noqa: BLE001
        pass
    try:
        meta = schema.get(field) if isinstance(schema, dict) else None
        if _ps()._rejects_declared_type(field, meta, rest, schema):
            return None, why
    except Exception:                                      # noqa: BLE001
        pass
    return rest, None


def document_item_label_values(mapped: dict, schema: dict, facts: Any,
                               gpt_filled_set: Optional[set]) -> Dict[str, Tuple[Optional[str], Optional[str]]]:
    """{field: (value to print or None, refusal reason or None)} for every AI
    text box whose value carries a document item label. Mutates nothing; never
    raises. `pdf_service._enforce_post_fill_guards` applies it FIRST, so every
    later guard judges the value, not the label."""
    out: Dict[str, Tuple[Optional[str], Optional[str]]] = {}
    try:
        if not gpt_filled_set or not isinstance(mapped, dict) or not isinstance(schema, dict):
            return out
        form_id = facts.get("_form_id") if isinstance(facts, dict) else ""
        if _base_form(form_id) in _FROZEN_FORMS:
            return out
        for f in sorted(gpt_filled_set):
            v = mapped.get(f)
            if f not in schema or not isinstance(v, str) or not v.strip() or _skip_box(f, schema):
                continue
            res = strip_document_item_label(f, v, schema)
            if res is not None:
                out[f] = res
    except Exception as exc:                               # noqa: BLE001
        logger.warning("document item label check skipped: %s", exc)
    return out


# ══ Fix C (14 Oct 2026): an AI value whose ONLY evidence is the wrong source ══
# The owner's parked class, read off the live Choice Electric runs (`ba7c709d`,
# `18f6914f`, `b117f010`, `f83757cf`) with their STORED AI answers fed back
# through the current stamper. Every value below passed the raw-text check (or
# was "low confidence" and printed anyway) because its words ARE somewhere -
# just not as an answer to THIS box:
#
#   * a PERSON's answer to a different question - the producer-typed contact
#     "Dana Whitfield" as a vehicle's other owner (127) and as the accounting /
#     claims / inspection contact (130); the typed mailing address as the 127
#     garage description; the typed total revenue as FOREIGN gross sales (131);
#   * the box's own TOOLTIP EXAMPLE - contact type "Accounting" ("e.g.
#     accounting, claims"), fire protection "sprinklers" ("sprinklers,
#     standpipes, chemical systems");
#   * a value with no word of what the box QUALIFIES it as - the WC payroll as
#     "paid to subcontractors" (126, W4), the narrative's scope sentence as the
#     "type of work subcontracted" (W6), the audit frequency as the retro plan;
#   * another SECTION's text - each driver's first initial as the middle
#     initial (W8), the vehicles' garaging ZIP as the driver's mailing address
#     (W9), the experience mod 1.0800 as the NCCI risk id, "Prem #: 001 Bldg #:
#     001" as a building's description (X7), a form's unfilled label line
#     ("... is part of Policy No.") as underlying coverage information, covered
#     auto symbols "1".."7" down the 137's OTHER boxes on a package with no auto
#     policy.
#
# Each rule is one generic STRUCTURAL test with a second condition (CLAUDE.md
# H1-F): the value must match the wrong source AND have no right one. A value
# the documents print in the box's own sense, or a person gave for this very
# question, is never refused. Measured over the stored corpus (660 packages,
# their stored AI answers replayed) before shipping: see 25sepChanges.md.

# (1) A person's answer to ANOTHER question. Z13 made a person's value evidence
# only for the question they answered (`box_question_facts`); this is the active
# half. Narrow on purpose: IDENTITY values only (a name, phone, e-mail, address,
# identifier the person typed) - an amount equal to a typed amount can be the
# same quantity in a grid row the box map cannot name (a typed business income
# limit printed in the 140's business income row), and is left to the meaning
# rules. Short values (under four letters / digits) collide by chance.
_IDENTITY_FACT_RE = re.compile(r"name|phone|fax|e_?mail|address|website|fein|licen[cs]e|contact")
_MIN_COPY_CHARS = 4


def _printed(text: Any, folded_raw: str) -> bool:
    """`text` is printed in the (already folded) documents - the stamper's own
    presence test, plus a whole-token test for values under four characters."""
    ps = _ps()
    if not folded_raw:
        return False
    needle = ps._normalize_for_search(str(text or ""))
    if not needle:
        return False
    if re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", folded_raw):
        return True
    return bool(ps._value_in_raw_text(str(text or ""), folded_raw))


def _held_by_a_document_fact(text: Any, facts: Any) -> bool:
    """Some fact a document gave (any source but a person) holds this value."""
    n = _norm_answer(text)
    for k, v in (facts or {}).items() if isinstance(facts, dict) else ():
        if not isinstance(k, str) or k.startswith("_"):
            continue
        if isinstance(v, dict) and str(v.get("source") or "").lower() in _PERSON_SOURCES:
            continue
        val = v.get("value") if isinstance(v, dict) and "value" in v else v
        if isinstance(val, bool) or not isinstance(val, (str, int, float)):
            continue
        if n and _norm_answer(val) == n:
            return True
    return False


_KEY_FILLER_WORDS = frozenset({"the", "of", "and", "num", "number", "code", "value", "text"})


def _stem(word: str) -> str:
    """A plural folded to its singular ("claims" / "claim", "companies" /
    "company"); "address" keeps its double s."""
    w = word.lower()
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def _fact_reads_as_this_box(fact_key: str, field: str, tooltip: str) -> bool:
    """Every word of the fact's own key is a word of the box (its name or
    ACORD's description of it): "contact_type" reads as the contact-type box,
    "contact_name" does not read as a vehicle's other owner. The box map
    (`box_question_facts`) does not know every fact a person can answer; a
    fact whose words the box itself carries is never called another
    question's."""
    words = [w for w in re.findall(r"[a-z]+", str(fact_key or "").lower())
             if len(w) >= 3 and w not in _KEY_FILLER_WORDS]
    if not words:
        return True
    box = {_stem(w) for w in re.findall(r"[a-z]+", re.sub(
        r"(?<=[a-z0-9])(?=[A-Z])", " ", str(field or "")).lower() + " " + str(tooltip or "").lower())
        if len(w) >= 3}
    return all(_stem(w) in box for w in words)


def answers_another_question(text: Any, said_for: Iterable[str], folded_raw: str,
                             facts: Any, field: str = "", tooltip: str = "") -> bool:
    """True when an AI `text` equal to what a PERSON gave for `said_for` (none of
    them this box's question by the box map - the caller checked) has no other
    evidence: an identity value, of a fact whose words the box does not carry,
    printed in no document, held by no document's fact."""
    keys = [k for k in (said_for or ()) if isinstance(k, str)]
    if not folded_raw or not keys or not any(_IDENTITY_FACT_RE.search(k) for k in keys):
        return False                       # no documents to read: not judged
    if any(_fact_reads_as_this_box(k, field, tooltip) for k in keys):
        return False                       # the box's own words name that fact
    if len(re.sub(r"[^A-Za-z0-9]", "", str(text or ""))) < _MIN_COPY_CHARS:
        return False
    return not _printed(text, folded_raw) and not _held_by_a_document_fact(text, facts)


def person_statements(facts: Any) -> str:
    """Every scalar a PERSON supplied, one "fact words: value" line each - the
    evidence a person gave, with the question they answered beside it."""
    lines: List[str] = []
    for k, v in (facts or {}).items() if isinstance(facts, dict) else ():
        if isinstance(v, dict) and str(v.get("source") or "").lower() in _PERSON_SOURCES:
            val = v.get("value")
            if isinstance(val, (str, int, float)) and not isinstance(val, bool) and str(val).strip():
                lines.append(f"{str(k).replace('_', ' ')}: {val}")
    return "\n".join(lines)


# (2) The box's own TOOLTIP EXAMPLE as the answer. ACORD's examples are valid
# answers on its authority (Guard 8's cut keeps them out of the echo test) -
# but only when something STATES them: an example copied into a free-text box
# that no document prints and no person gave is the model reaching for the
# illustration. "Enter text:" boxes only - a CODE box's examples are its option
# set, and choosing one ("dollars" for a "$5,000" deductible) is a reading.
_FREE_TEXT_TOOLTIP_RE = re.compile(r"^\s*enter\s+text\s*:", re.I)


# The words naming what a box is ABOUT (its party / subject), read off its name:
# "NamedInsured_Contact_ContactDescription_A" -> {"contact"}. Z41 (25 Oct 2026,
# run f575160b): ACORD 125's contact type printed "Claims" - the tooltip's own
# example ("e.g. accounting, claims") - because "claims" is printed all over a
# package; it counts as stated only on a line that also names the box's subject.
_SUBJECT_STOP = frozenset({"named", "insured", "description", "type", "code", "other", "name",
                           "indicator", "text", "full", "applicant", "information"})


def _box_subject_words(field: str) -> Set[str]:
    base = re.sub(r"_[A-N]$", "", str(field or ""))
    words = set(re.findall(r"[a-z]+", re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", base).lower()))
    return {w for w in words if len(w) >= 4 and w not in _SUBJECT_STOP}


def _example_stated_for_subject(text: Any, field: str, raw_text: str) -> bool:
    subject = _box_subject_words(field)
    word = _norm(text)
    if not subject or not word or not raw_text:
        return True                        # nothing to scope by: not judged here
    rx = re.compile(rf"(?<![a-z]){re.escape(word)}", re.I)
    for line in str(raw_text).splitlines():
        low = line.lower()
        if rx.search(low) and any(w in low for w in subject):
            return True
    return False


def unstated_tooltip_example(text: Any, tooltip: str, folded_raw: str,
                             field: str = "", raw_text: str = "") -> bool:
    if not folded_raw or not _FREE_TEXT_TOOLTIP_RE.match(tooltip or ""):
        return False                       # no documents to read: not judged
    examples = tooltip_options(tooltip, minimum=1)
    if not examples or _norm(text) not in examples:
        return False
    # A LINE OF BUSINESS is a reading of a closed vocabulary ("CGL" in a loss
    # run is "General Liability" on the form), judged by the line rules - never
    # the box's illustration.
    try:
        from services.lob_canon import canon_line
        if canon_line(str(text or "")):
            return False
    except Exception:                                      # noqa: BLE001
        return False
    if not _printed(text, folded_raw):
        return True
    # Printed somewhere - stated for THIS box's subject only on a line naming it.
    # Z42 review B: only a DESCRIPTION box whose example is one common word
    # ("Claims" as a contact type); "Ford" for a vehicle's make or "Property" for
    # a loss's line of business is printed as itself, on rows naming no subject.
    if not re.search(r"Description_[A-N]$", field or "") or len(_norm(text).split()) != 1:
        return False
    return bool(field and raw_text) and not _example_stated_for_subject(text, field, raw_text)


_OWN_PARTY_FACTS = ("contact_name", "applicant_name", "dba_name", "producer_name",
                    "inspection_contact_name", "accounting_contact_name")


_INTEREST_ROLE_RE = re.compile(
    r"\b(?:other\s+owner|co-?owner|lien\s*holder|loss\s+payee|mortgagee|lessor|lender|"
    r"additional\s+(?:insured|interest)|leased\s+from|registered\s+owner)\b", re.I)


def _named_in_an_interest_role(value: Any, raw_text: str) -> bool:
    """A document prints ``value`` on a line naming an interest role ("Other
    owner: Dana Whitfield", "Loss payee - First Bank"): it may be one."""
    v = re.sub(r"\s+", " ", str(value or "")).strip().lower()
    if not v:
        return False
    for ln in str(raw_text or "").splitlines():
        low = re.sub(r"\s+", " ", ln).lower()
        if v in low and _INTEREST_ROLE_RE.search(low):
            return True
    return False


_INTEREST_FACTS = ("loss_payee_name", "mortgagee_name", "lienholder_name", "landlord_name",
                   "additional_interests", "additional_insureds")


def _a_documents_interest_fact(value: Any, facts: Any) -> bool:
    """A fact that names an interest party holds ``value`` - it may be one."""
    v = _norm(value)
    f = facts if isinstance(facts, dict) else {}
    for k in _INTEREST_FACTS:
        x = f.get(k)
        x = x.get("value") if isinstance(x, dict) and "value" in x else x
        items = x if isinstance(x, list) else [x]
        for it in items:
            n = (it.get("name") or it.get("full_name")) if isinstance(it, dict) else it
            if isinstance(n, str) and _norm(n) == v:
                return True
    return False


def _is_the_insureds_own_party(value: Any, facts: Any) -> bool:
    """``value`` names the applicant, its DBA, its contact / owner, or the
    producer - never an additional interest. Never raises."""
    try:
        from services.normalization import same_entity_name
        v = _norm(value)
        if not v or len(v) < 5:
            return False                   # "Al": too short to be anybody's name for sure
        f = facts if isinstance(facts, dict) else {}
        names = []
        for k in _OWN_PARTY_FACTS:
            x = f.get(k)
            x = x.get("value") if isinstance(x, dict) and "value" in x else x
            if isinstance(x, str) and x.strip():
                names.append(x)
        contacts = f.get("applicant_contacts")
        contacts = contacts.get("value") if isinstance(contacts, dict) and "value" in contacts else contacts
        for c in contacts if isinstance(contacts, list) else []:
            n = c.get("name") if isinstance(c, dict) else c
            if isinstance(n, str) and n.strip():
                names.append(n)
        return any(_norm(n) == v or same_entity_name(n, str(value)) for n in names)
    except Exception:                                      # noqa: BLE001
        return False


_FIELD_LABEL_WORDS = frozenset({
    "full", "first", "last", "middle", "given", "sur", "surname", "name", "names", "date", "of",
    "birth", "dob", "address", "street", "city", "state", "zip", "postal", "code", "phone", "fax",
    "email", "e", "mail", "number", "no", "id", "type", "title", "description", "years", "year",
    "experience", "hired", "licence", "license", "licensed", "in", "n", "a"})
_TYPE_OF_TOOLTIP_RE = re.compile(r"^\s*enter\s+text\s*:\s*the\s+type\s+of\b", re.I)


def unstated_type_word(text: Any, tooltip: str, folded_raw: str) -> bool:
    """A short value (1-3 words) in an "Enter text: The type of ..." box that
    no document prints: the model's guess at a category, not a reading. A line
    of business is judged by the line rules, never here."""
    if not folded_raw or not _TYPE_OF_TOOLTIP_RE.match(tooltip or ""):
        return False
    words = _norm(text).split()
    if not words or len(words) > 3:
        return False
    # A field LABEL is no type (live bcfd175b, 25 Oct: the contact type read
    # "Full Name" - the driver Excel's column heading).
    if all(w in _FIELD_LABEL_WORDS for w in words):
        return True
    try:
        from services.lob_canon import canon_line
        if canon_line(str(text or "")):
            return False
    except Exception:                                      # noqa: BLE001
        return False
    return not _printed(text, folded_raw)


# (3) A QUALIFIED box needs its qualifier. A box that narrows a general quantity
# - the payroll PAID TO SUBCONTRACTORS, FOREIGN gross sales, the RETROSPECTIVE
# rating plan - is answered only by a statement that carries the qualifier
# beside the value; the general figure (total payroll, total revenue) or a
# neighbouring section's word ("Annual" from the audit terms) is another
# question's answer. The COPE rule's body (`_attribute_box_unstated`), read over
# the documents AND what a person stated (labelled with the question they
# answered), so a person's "subcontract cost: 350000" still supports $350,000.
# The subcontracting words include the ISO class's own abbreviation ("91585
# Contrctrs-sub work" on Orbin's GL schedule - its $350,000 is the cost of
# subcontracted work and stays).
_QUALIFIED_BOXES: Tuple[Tuple[re.Pattern, re.Pattern, int], ...] = (
    (re.compile(r"Subcontract", re.I),
     re.compile(r"\bsub[\s-]?(?:contr\w*|work\w*)|\bsubs\b", re.I), 200),
    (re.compile(r"Foreign\w*(?:Sales|Receipts|Revenue)", re.I),
     re.compile(r"\bforeign\b|\bexport\w*|\binternational\b|\boverseas\b|"
                r"\boutside\s+(?:of\s+)?(?:the\s+)?(?:u\.?\s?s\.?|united\s+states|country)", re.I), 200),
    (re.compile(r"Retrospective", re.I), re.compile(r"\bretro(?:spective)?\b", re.I), 160),
    # An inflation guard percentage (live 85e51d02, 25 Oct: the 140 printed the
    # 80% COINSURANCE there; the dec's "Inflation Guard (%)" line is empty).
    (re.compile(r"InflationGuard", re.I), re.compile(r"\binflation\b", re.I), 60),
    # A GL property damage / bodily injury deductible (live 85e51d02, 25 Oct:
    # the 126 printed the PROPERTY coverage's $5,000 building deductible; no
    # document says "property damage").
    (re.compile(r"^GeneralLiability_(?:PropertyDamage|BodilyInjury)_Deductible", re.I),
     re.compile(r"\bproperty\s+damage\b|\bbodily\s+injury\b|\bP\.?D\.?\s+deductible|\bB\.?I\.?\s+deductible", re.I), 160),
)


def is_qualified_box(field: str) -> bool:
    return any(box_re.search(field or "") for box_re, _attr, _w in _QUALIFIED_BOXES)


def qualifier_not_stated(field: str, value: Any, evidence: str, tooltip: str = "") -> bool:
    """True when `field` is a qualified box and `evidence` (documents + person
    statements) never states its qualifier with this answer."""
    return _attribute_box_unstated(field, value, evidence, tooltip, _QUALIFIED_BOXES)


# (4) A middle initial made out of the row's own name (W8: "Marcus Delgado" ->
# middle initial "M", all eight drivers; "Erin Royal" -> middle name "Royal").
# Refused when the AI's initial / middle name IS the row's first letter of the
# given name, the given name or the surname, unless a document prints the name
# with it ("Mary M. Smith", "SMITH, MARY M").
_MIDDLE_NAME_BOX_RE = re.compile(
    r"^(?P<p>.+)_(?:OtherGivenNameInitial|OtherGivenName|MiddleInitial|MiddleName)_(?P<r>[A-N])$")


def initial_from_the_name(field: str, value: Any, mapped: Any, raw_text: str) -> bool:
    m = _MIDDLE_NAME_BOX_RE.match(field or "")
    if not m or not isinstance(mapped, dict) or not raw_text:
        return False                       # no documents to read: not judged
    p, r = m.group("p"), m.group("r")
    given = str(mapped.get(f"{p}_GivenName_{r}") or "").strip()
    surname = str(mapped.get(f"{p}_Surname_{r}") or "").strip(" ,")
    core = str(value or "").strip().rstrip(".").strip()
    if not core or not given:
        return False
    if len(core) == 1:
        from_name = core.lower() == given[0].lower()
    else:
        from_name = _norm(core) in {_norm(given), _norm(surname)} - {""}
    if not from_name:
        return False
    g, c = re.escape(given), re.escape(core)
    # An initial stands for a middle NAME too ("Mary Margaret Smith" -> "M").
    c = c + r"[a-z]*" if len(core) == 1 else c
    pats = [rf"\b{g}\s+{c}\.?(?![A-Za-z])"]
    if surname:
        s = re.escape(surname)
        pats = [rf"\b{g}\s+{c}\.?\s+{s}\b", rf"\b{s}\s*,\s*{g}\s+{c}\.?(?![A-Za-z])"]
    return not any(re.search(p_, raw_text or "", re.I) for p_ in pats)


# (5) A PERSON row's address is that person's (W9: driver 1's mailing city / ZIP
# = the vehicles' garaging line "DENVER, CO 80221"; 21 stored packages put the
# insured's mailing address, a business location or an auto's garaging address
# on the 127's driver rows - no document in the corpus prints a driver's own
# address). Kept only where a document prints the value in the block that names
# that person: on the line naming them or within the three lines after it. A
# state alone says nothing; it goes with its row's refused city / ZIP.
_ROW_ADDRESS_BOX_RE = re.compile(
    r"^(?P<p>[A-Za-z]+)_MailingAddress_(?P<part>[A-Za-z]+)_(?P<r>[A-N])$")
_ADDRESS_PARTS = ("LineOne", "CityName", "PostalCode")


_NORM_LINES_CACHE: List[Tuple[str, List[str]]] = []


def _norm_lines(raw_text: str) -> List[str]:
    """The documents' lines folded once (" " + words + " ")."""
    for ref, lines in _NORM_LINES_CACHE:
        if ref is raw_text:
            return lines
    lines = [f" {_norm(ln)} " for ln in str(raw_text or "").splitlines()]
    _NORM_LINES_CACHE.insert(0, (raw_text, lines))
    del _NORM_LINES_CACHE[3:]
    return lines


def _address_part_unstated(value: Any, names: List[str], raw_text: str) -> bool:
    v = _norm(value)
    if not v or not raw_text:
        return False
    lines = _norm_lines(raw_text)
    name_res = [re.compile(rf"(?<![a-z0-9]){re.escape(_norm(n))}(?![a-z0-9])") for n in names]
    needle = f" {v} "
    for i, ln in enumerate(lines):
        if needle not in ln:
            continue
        block = " ".join(lines[max(0, i - 3):i + 1])
        if any(rx.search(block) for rx in name_res):
            return False
    return True


def address_not_this_persons(field: str, value: Any, mapped: Any, schema: Any, raw_text: str,
                             ai_fields: Optional[Set[str]] = None) -> bool:
    m = _ROW_ADDRESS_BOX_RE.match(field or "")
    if not m or not isinstance(mapped, dict) or not isinstance(schema, dict):
        return False
    p, part, r = m.group("p"), m.group("part"), m.group("r")
    if f"{p}_GivenName_{r}" not in schema and f"{p}_Surname_{r}" not in schema:
        return False                                     # not a PERSON row
    names = [str(mapped.get(f"{p}_{k}_{r}") or "").strip(" ,.") for k in ("Surname", "GivenName")]
    names = [n for n in names if len(re.sub(r"[^A-Za-z]", "", n)) >= 3]
    if not names:
        return False                                     # nobody on the row: not judged
    if part == "StateOrProvinceCode":
        for q in _ADDRESS_PARTS:
            box = f"{p}_MailingAddress_{q}_{r}"
            held = mapped.get(box)
            if str(held or "").strip() and (ai_fields is None or box in ai_fields) \
                    and _address_part_unstated(held, names, raw_text):
                return True
        return False
    if part not in _ADDRESS_PARTS:
        return False
    return _address_part_unstated(value, names, raw_text)


# (6) A rating FACTOR is not an identifier (18f6914f: ACORD 130's NCCI risk id
# printed "1.0800" - the WC dec's "Experience Mod 1.0800"). A decimal of one or
# two whole digits and two to four decimals identifies nothing; refused in an
# identifier box unless a document prints it under a non-factor label.
_FACTOR_VALUE_RE = re.compile(r"^\s*\d{1,2}\.\d{2,4}\s*$")
_FACTOR_LABEL_RE = re.compile(
    r"\b(?:mod(?:ification)?|factor|rate|credit|debit|multiplier|surcharge|discount)\b", re.I)


def factor_as_identifier(field: str, value: Any, tooltip: str, raw_text: str) -> bool:
    if not (_INSURED_ID_BOX_RE.search(field or "")
            or re.match(r"^\s*enter\s+identifier\s*:", tooltip or "", re.I)):
        return False
    s = str(value or "").strip()
    if not _FACTOR_VALUE_RE.match(s):
        return False
    hits = list(re.finditer(rf"(?<![\d.]){re.escape(s)}(?![\d])", raw_text or ""))
    return all(_FACTOR_LABEL_RE.search((raw_text or "")[max(0, h.start() - 60):h.start()])
               for h in hits)


# (7) A row REFERENCE is not a description (X7: "Prem #: 001 Bldg #: 001" as
# ACORD 140's building description, on nine stored packages). A description box
# holding nothing but identifier headings - a word, a number mark, a number -
# names a row and describes nothing ("Location 2 - Building 1", with no number
# mark, is still read as an answer).
_ROW_REFERENCE_RE = re.compile(
    r"^(?:\s*[A-Za-z]{2,}\.?\s*(?:#|no\.|number)\s*:?\s*[A-Za-z]?\d[\w-]*[\s,;/-]*)+$", re.I)


def is_row_reference(value: Any) -> bool:
    return bool(_ROW_REFERENCE_RE.match(str(value or "").strip()))


# (8) A form's UNFILLED label line is not a value ("The Schedule of Underlying
# Insurance is part of Policy No." - the umbrella dec's own heading, its number
# left blank - as ACORD 131's underlying coverage information and as an
# explanation, three stored boxes). The value ends in a label marker ("No.",
# "Number", "#", ":") and every printing of it is the end of its line.
_DANGLING_LABEL_RE = re.compile(r"(?:\bno\.|\bnumber|#|:)\s*$", re.I)


def is_blank_form_label(value: Any, raw_text: str) -> bool:
    s = str(value or "").strip()
    if len(re.findall(r"[A-Za-z]{2,}", s)) < 4 or not _DANGLING_LABEL_RE.search(s) or not raw_text:
        return False
    prints = _text_index(raw_text).printings(s)
    return bool(prints) and all(not after for _before, after in prints)


# (9) A covered auto symbol is stated (b117f010: ACORD 137's "other symbol"
# boxes A-H printed 1, 2, 3, 4, 5, 6, 7 on a package with no auto policy). An
# AI symbol stands when a document prints it after the word "symbol", or the
# extracted covered-auto symbols (`auto_covered_symbols`) carry it.
_OTHER_SYMBOL_BOX_RE = re.compile(r"Symbol_OtherSymbolCode_[A-N]$")
_SYMBOL_WORD_RE = re.compile(r"\bsymbols?\b", re.I)


def symbol_not_stated(field: str, value: Any, facts: Any, raw_text: str) -> bool:
    if not _OTHER_SYMBOL_BOX_RE.search(field or ""):
        return False
    v = str(value or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9]{1,3}", v):
        return False
    core = v.lstrip("0") or "0"
    try:
        from services.auto_symbols import parse_symbols
        stated = parse_symbols(_fv(facts, "auto_covered_symbols"))
        if core.isdigit() and any(int(core) in nums for nums in stated.values()):
            return False
    except Exception:                                      # noqa: BLE001
        pass
    text = raw_text or ""
    if not text:
        return False                       # no documents to read: not judged
    tok = re.compile(rf"(?<![\w.])0*{re.escape(core)}(?![\w.])", re.I)
    return not any(tok.search(text[m.end():m.end() + 80]) for m in _SYMBOL_WORD_RE.finditer(text))


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
        self._folded: Optional[str] = None
        self._person_text: Optional[str] = None
        self._evidence: Optional[str] = None
        # Set by `refuse_non_answers` (the form's boxes and the AI's own set);
        # the evidence gate's door judges one box and leaves them None.
        self.mapped: Optional[dict] = None
        self.ai_fields: Optional[Set[str]] = None

    @property
    def folded(self) -> str:
        """The documents folded once for presence tests."""
        if self._folded is None:
            self._folded = _ps()._normalize_for_search(self.raw_text) if self.raw_text else ""
        return self._folded

    @property
    def person_text(self) -> str:
        if self._person_text is None:
            self._person_text = person_statements(self.facts)
        return self._person_text

    @property
    def evidence(self) -> str:
        """The documents and what a person stated, read together (built once)."""
        if self._evidence is None:
            self._evidence = self.raw_text + "\n" + self.person_text
        return self._evidence

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
    if _is_operations_box(field, tu) and ctx.raw_text:
        from services.normalization import describes_insurance_not_business
        if describes_insurance_not_business(text, ctx.raw_text):
            return f"{REASON_SUMMARY}: {text[:40]!r} describes the insurance, not the business"
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
    # Fix C (7), (8), W10 - after the person check, so a person's own words
    # for this question stand: a row reference as a description, a form's own
    # unfilled label line as a value, a coverage table row as an explanation.
    why = _z41_judge(field, text, tu, _said_for, ctx)
    if why:
        return why
    if narrative and is_row_reference(text):
        return f"{REASON_ROW_REFERENCE}: {text[:40]!r} names a row, it describes nothing"
    if ctx.raw_text and is_blank_form_label(text, ctx.raw_text):
        return f"{REASON_BLANK_FORM_LABEL}: {text[:40]!r} is a form's unfilled label"
    if "Explanation" in (field or "") and is_coverage_schedule_row(text):
        return f"{REASON_COVERAGE_ROW}: {text[:40]!r} is a coverage table row"
    # The TYPE OF WORK subcontracted is work, not the insurance the subs must
    # carry (live 85e51d02, 25 Oct: the 126 printed "subcontractors must carry
    # their own insurance and name us as additional insured").
    if re.search(r"TypeOfWorkSubcontracted", field or "") and re.search(
            r"\b(?:insurance|insured|certificates?|coverage|limits?|policy|policies)\b", str(text or ""), re.I):
        return f"{REASON_ANOTHER_QUESTION}: {text[:40]!r} is about the subcontractors' insurance, not their work"
    # Any DATA row is no explanation either (live 85e51d02, 25 Oct: the 130's
    # "employees under 16 or over 60?" answered Yes with a driver schedule row,
    # "Hannah Price | 05/04/1997 | CO | 02/03/2025 | 7", as its explanation).
    if "Explanation" in (field or "") and is_data_table_row(text):
        return f"{REASON_COVERAGE_ROW}: {text[:40]!r} is a table row"
    # Fix C (1): ...and it is no evidence for ANOTHER question either - an
    # identity value a person typed for one question, in a box asking another,
    # with nothing else stating it (the typed contact as a vehicle's owner).
    if _said_for and ctx.raw_text and answers_another_question(text, _said_for, ctx.folded, ctx.facts,
                                                                field, tu):
        return (f"{REASON_ANOTHER_QUESTION}: {text[:30]!r} is the answer a person gave for "
                f"{sorted(_said_for)[0]}")
    # An ADDITIONAL INTEREST is a third party - a lender, loss payee or
    # additional insured - never the insured's own owner, contact or producer
    # (live e66d68d7, 25 Oct: "Eric Berger", the owner the handwritten note
    # names, printed as additional interest #2 on the 28, 126, 127 and 140).
    if (re.match(r"^AdditionalInterest_FullName_[A-N]$", field or "") and ctx.raw_text
            and _is_the_insureds_own_party(text, ctx.facts)
            and not _named_in_an_interest_role(text, ctx.raw_text)
            and not _a_documents_interest_fact(text, ctx.facts)):
        return f"{REASON_OWN_PARTY_AS_INTEREST}: {text[:40]!r} is the insured's own party, not an additional interest"
    # Fix C (2): the box's own tooltip example, stated by nothing.
    if not _said_for and ctx.raw_text and unstated_tooltip_example(text, tu, ctx.folded,
                                                                      field, ctx.raw_text):
        return f"{REASON_TOOLTIP_EXAMPLE}: {text[:30]!r} is the box's own example"
    # ...and a TYPE word nothing states (live 85e51d02, 25 Oct: ACORD 125's
    # contact type printed "Inspection" beside the owner - no document says it).
    if not _said_for and ctx.raw_text and unstated_type_word(text, tu, ctx.folded):
        return f"{REASON_TOOLTIP_EXAMPLE}: {text[:30]!r} is a type no document states"
    if ctx.mapped is not None and improvement_year_is_another_year(field, text, ctx.mapped):
        return f"{REASON_YEAR_FROM_A_DATE}: {text[:6]!r} is this building's roof year / year built"
    if _BUILDING_YEAR_BOX_RE.match(field or "") and year_not_printed_as_a_building_year(text, ctx.raw_text):
        return f"{REASON_YEAR_FROM_A_DATE}: {text[:10]!r} is printed only inside dates"
    if _START_DATE_BOX_RE.search(field or "") and policy_date_as_business_start(text, ctx.raw_text):
        return f"{REASON_POLICY_DATE_AS_START}: {text[:12]!r} is a policy date"
    if rating_date_outside_the_term(field, text, ctx.schema, ctx.mapped, ctx.facts):
        return f"{REASON_RATING_DATE_OTHER_TERM}: {text[:24]!r} is outside the proposed term"
    if cope_answer_without_evidence(field, text, ctx.raw_text, tu):
        return f"{REASON_COPE_WITHOUT_EVIDENCE}: {text[:40]!r} is not stated for this building"
    # Fix C (3): a qualified box (subcontracted, foreign, retrospective) needs
    # its qualifier beside the value - in a document or what a person stated.
    if ctx.raw_text and is_qualified_box(field) and qualifier_not_stated(field, text, ctx.evidence, tu):
        return f"{REASON_QUALIFIER_NOT_STATED}: {text[:40]!r} is not stated as what this box asks"
    # Fix C (4) and (5): a row's own name as its middle initial; another
    # party's address on a person's row. Both read the form's other boxes.
    if ctx.mapped is not None:
        if initial_from_the_name(field, text, ctx.mapped, ctx.raw_text):
            return f"{REASON_INITIAL_FROM_NAME}: {text[:12]!r} is made from the row's own name"
        if address_not_this_persons(field, text, ctx.mapped, ctx.schema, ctx.raw_text, ctx.ai_fields):
            return f"{REASON_ADDRESS_NOT_THIS_PERSONS}: {text[:30]!r} is not printed for this person"
    # Z37: an insurer's / office's address is not the insured's or the agency's
    # (Travelers' "OFFICE: PHOENIX AZ" printed as the applicant's mailing state).
    if (ctx.raw_text and (_PARTY_ADDRESS_BOX_RE.match(field or "")
                          or _OTHER_PARTY_ADDRESS_BOX_RE.match(field or ""))
            and not _row_party_is_an_outside_insurer(field, ctx.mapped, ctx.facts)
            and _office_address(text, ctx.raw_text,
                                own_names=(_insured_own_names(ctx.facts)
                                           if (field or "").startswith("NamedInsured_")
                                           or _OTHER_PARTY_ADDRESS_BOX_RE.match(field or "") else ()),
                                party_names=(_package_carrier_names(ctx.facts)
                                             if _OTHER_PARTY_ADDRESS_BOX_RE.match(field or "")
                                             else ()))):
        return f"{REASON_ADDRESS_NOT_THIS_PERSONS}: {text[:30]!r} is printed only as an office's address"
    if _INSURED_ID_BOX_RE.search(field or "") and carrier_code_as_insured_id(text, ctx.raw_text):
        return f"{REASON_CARRIER_CODE_AS_INSURED_ID}: {text[:14]!r} is printed as the carrier's code"
    # Fix C (6) and (9): a rating factor as an identifier; a covered auto
    # symbol nothing states.
    if factor_as_identifier(field, text, tu, ctx.raw_text):
        return f"{REASON_FACTOR_AS_IDENTIFIER}: {text[:14]!r} is a rating factor"
    if symbol_not_stated(field, text, ctx.facts, ctx.raw_text):
        return f"{REASON_SYMBOL_NOT_STATED}: {text[:6]!r} is stated as no symbol"
    if other_factor_row_is_a_label(field, ctx.schema, getattr(ctx, "mapped", None)):
        return f"{REASON_ROW_NAME_REFUSED}: the OTHER row is named only by a section label"
    if other_row_names_a_coverage_with_its_own_boxes(field, ctx.schema, getattr(ctx, "mapped", None)):
        return f"{REASON_COVERAGE_HAS_ITS_OWN_ROW}: the OTHER row names a coverage this form prints itself"
    if _LINE_ONE_BOX_RE.search(field or "") and not_a_street_line(text):
        return f"{REASON_NOT_A_STREET_LINE}: {text[:30]!r} is not a street"
    if bureau_value_without_its_label(field, text, ctx.raw_text):
        return f"{REASON_BUREAU_NOT_STATED}: {text[:30]!r} is not printed as a bureau's"
    # Z41: last, so every more specific reason names the box first.
    if box_label_as_value(text, tu):
        return f"{REASON_BOX_LABEL}: {text[:40]!r} is the box's own label"
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


# ══ Z41 (25 Oct 2026, live run f575160b) - AI values borrowed across roles ═══
# ACORD 141 / 127 / 137_CO / 140 / 28 on the owner's Choice Electric package
# printed: the box's own tooltip as its value; the carrier's head office as
# the auditor's address; the twelve drivers as the crime form's employees; the
# drivers' licence states as their mailing states and as the Colorado form's
# hired / non-owned states; the producer's ROOF year as the WIRING year and the
# typed period of restoration as an Actual Loss Sustained month count; an AUTO
# endorsement (CA 71 65 09 11) on the property evidence; a $5,000 deductible
# under named windstorm and ordinance or law (neither printed); the dec's ISSUE
# date as a prior evidence date. One rule each, every form, AI values only - a
# person's own answer for the box's question is returned before any of these.

def _plain(text: Any) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", str(text or "").lower())).strip()


def box_label_as_value(text: Any, tooltip: Any) -> bool:
    """The value is the box's own tooltip text (four words or more of it)."""
    v = _plain(text)
    if len(re.findall(r"[a-z]{3,}", v)) < 4:
        return False
    # Z42 review B: ACORD's own example answers are answers, not the label
    # ("e.g., combined building and contents" on the 140 blanket type) - an
    # unstated one is `unstated_tooltip_example`'s question.
    try:
        if any(v == _plain(o) or v in _plain(o) for o in tooltip_options(str(tooltip or ""), minimum=1)):
            return False
    except Exception:                                      # noqa: BLE001
        pass
    return v in _plain(tooltip)


# Address boxes of a party other than the insured / producer (those keep the
# older rule with their own names): an auditor, an interest, a premises owner.
# An insurer's own address boxes are never judged.
_OTHER_PARTY_ADDRESS_BOX_RE = re.compile(
    r"^(?!NamedInsured_|Producer_|Insurer|Carrier|Company)[A-Za-z]+(?:_[A-Za-z]+)*?_"
    r"(?:MailingAddress|PhysicalAddress)_(?:LineOne|LineTwo|CityName|PostalCode)_[A-N]$")
_ADDRESS_PART_RE = re.compile(
    r"^(?P<p>.+)_(?P<k>MailingAddress|PhysicalAddress)_(?:LineOne|LineTwo|CityName|"
    r"StateOrProvinceCode|PostalCode|CountyName|CountryCode)_(?P<r>[A-N])$")


def _row_party_is_an_outside_insurer(field: str, mapped: Any, facts: Any) -> bool:
    """Z42 review B: the row's own party is an insurance company that writes
    nothing in this package - a mortgagee / lender such as "Northwestern Mutual
    Life Insurance Company" on an interest row. Its address printed under its
    own (insurer-shaped) name is its address, not a carrier's office."""
    m = _ADDRESS_PART_RE.match(field or "")
    if not m or not isinstance(mapped, dict) or m.group("p").startswith(("NamedInsured", "Producer")):
        return False
    name = str(mapped.get(f"{m.group('p')}_FullName_{m.group('r')}") or "").strip()
    if not name:
        return False
    try:
        from services.fact_comparison import looks_like_an_insurer
        from services.normalization import same_entity_name
        if not looks_like_an_insurer(name):
            return False
        return not any(same_entity_name(name, c) for c in _package_carrier_names(facts))
    except Exception:                                      # noqa: BLE001
        return False


def _package_carrier_names(facts: Any) -> List[str]:
    """Every carrier the package names (its scalar and each coverage row)."""
    names: List[str] = []
    try:
        v = _fv(facts, "carrier_name")
        if isinstance(v, str) and v.strip():
            names.append(v.strip())
        rows = _fv(facts, "coverage_lines")
        for r in rows if isinstance(rows, list) else []:
            c = r.get("carrier") if isinstance(r, dict) else None
            if isinstance(c, str) and c.strip() and c.strip() not in names:
                names.append(c.strip())
    except Exception:                                      # noqa: BLE001
        pass
    return names


# A person list kept for ONE role, and the facts that name people in other roles.
_SCHEDULE_PERSON_LISTS = ("auto_drivers",)
_ROLE_PERSON_KEY_RE = re.compile(
    r"officer|named_individual|contact|interest|owner|partner|member|employee|trustee|"
    r"principal|auditor|manager|applicant|insured|dba|individual|proprietor|signer|signature", re.I)
# Words of a name box that say only its type, never its role.
_NAME_TYPE_WORDS = frozenset({"full", "name", "given", "surname", "other", "initial", "middle"})
# A printed role of a person in the business ("OFFICERS: Daniel Mercer,
# President") states the person beside any such box, whatever its own words.
_PERSON_ROLE_WORDS = ("officer", "president", "owner", "partner", "member", "manager",
                      "secretary", "treasurer", "director", "principal", "proprietor",
                      "executive")
_NAME_BOX_RE = re.compile(r"(?:FullName|GivenName|Surname)_[A-N]$")


def _list_names(rows: Any) -> List[str]:
    out = []
    for r in rows if isinstance(rows, list) else []:
        if isinstance(r, dict):
            n = r.get("name") or " ".join(str(r.get(k) or "") for k in ("first_name", "last_name"))
        else:
            n = r
        if isinstance(n, str) and len(n.split()) >= 2:
            out.append(n.strip())
    return out


def person_from_another_schedule(field: str, text: str, facts: Any, raw_text: str) -> bool:
    """A name box outside the drivers' rows holding a name only the driver
    schedule gives, with no fact naming that person in another role and no
    printed line naming them beside the box's own role word."""
    if not _NAME_BOX_RE.search(field or "") or (field or "").startswith("Driver_"):
        return False
    who = _plain(text)
    if len(who.split()) < 2:
        return False
    listed = {_plain(n) for k in _SCHEDULE_PERSON_LISTS for n in _list_names(_fv(facts, k))}
    if who not in listed:
        return False
    for k, v in (facts or {}).items() if isinstance(facts, dict) else ():
        if isinstance(k, str) and not k.startswith("_") and k not in _SCHEDULE_PERSON_LISTS \
                and _ROLE_PERSON_KEY_RE.search(k) and who in _plain(json_safe(v)):
            return False
    # Every segment of the box's name but the name type: "NamedInsured_Contact_
    # FullName" is a contact ("Contact: Erin Royal" states it), "WorkersCompensation_
    # Individual_FullName" an individual (Z42 review B - the first segment alone
    # read "named insured" / "workers compensation").
    role = [w for seg in re.sub(r"_[A-N]$", "", field).split("_")
            for w in re.findall(r"[a-z]{4,}", _field_words_lower(seg))
            if w not in _NAME_TYPE_WORDS] + list(_PERSON_ROLE_WORDS)
    for line in str(raw_text or "").splitlines():
        pl = _plain(line)
        if who in pl and any(_stem(w) in {_stem(x) for x in pl.split()} for w in role):
            return False
    return True


def json_safe(v: Any) -> str:
    try:
        import json as _json
        return _json.dumps(v, default=str)
    except Exception:                                      # noqa: BLE001
        return str(v)


def _field_words_lower(segment: str) -> str:
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(segment or "")).lower()


_STATE_FORM_RE = re.compile(r"_([A-Z]{2})$")
_STATE_BOX_RE = re.compile(r"StateOrProvinceCode_[A-N]$")
_NOT_A_COVERAGE_STATE_RE = re.compile(r"MailingAddress|PhysicalAddress|Licensed|Garag|Address")


def state_not_this_forms(field: str, text: str, form_id: str) -> bool:
    """A state-specific form (ACORD 137_CO) is about that state: a coverage
    row's state box holding another state is not this form's."""
    m = _STATE_FORM_RE.search(_base_form(form_id))
    if not m or not _STATE_BOX_RE.search(field or "") or _NOT_A_COVERAGE_STATE_RE.search(field):
        return False
    v = str(text or "").strip().upper()
    return bool(re.fullmatch(r"[A-Z]{2}", v)) and v != m.group(1)


def licence_state_as_mailing_state(field: str, text: str, mapped: Any) -> bool:
    """A row's mailing state equal to its LICENCE state, with no street and no
    city on the row - the licence state copied, not an address."""
    m = re.match(r"^(?P<p>.+)_MailingAddress_StateOrProvinceCode_(?P<r>[A-N])$", field or "")
    if not m or not isinstance(mapped, dict):
        return False
    p, r = m.group("p"), m.group("r")
    lic = str(mapped.get(f"{p}_LicensedStateOrProvinceCode_{r}") or "").strip().upper()
    if not lic or lic != str(text or "").strip().upper():
        return False
    return not any(str(mapped.get(f"{p}_MailingAddress_{k}_{r}") or "").strip()
                   for k in ("LineOne", "CityName", "PostalCode"))


# ISO / AAIS form-number prefixes and the line each belongs to (IL = common
# policy conditions, every line's - never judged).
_FORM_PREFIX_LINE = {
    "CA": "auto", "CG": "general_liab", "CP": "property", "CU": "umbrella",
    "WC": "workers_comp", "CM": "inland_marine", "IM": "inland_marine", "CR": "crime",
    "EP": "epli",
}


def form_from_another_line(field: str, mapped: Any, form_id: str) -> bool:
    """A FormEndorsement row naming another line's form (an AUTO "CA ..." on
    the property evidence)."""
    m = re.match(r"^FormEndorsement_\w+_([A-N])$", field or "")
    if not m or not isinstance(mapped, dict):
        return False
    try:
        from services.scoped_evidence import form_line
        line = form_line(form_id)
    except Exception:                                      # noqa: BLE001
        return False
    if not line:
        return False
    r = m.group(1)
    code = str(mapped.get(f"FormEndorsement_CopyrightOwnerCode_{r}") or "").strip().upper()
    number = str(mapped.get(f"FormEndorsement_FormIdentifier_{r}")
                 or mapped.get(f"FormEndorsement_FormNumberIdentifier_{r}") or "").strip().upper()
    prefix = code if re.fullmatch(r"[A-Z]{2}", code) else (
        re.match(r"^([A-Z]{2})[\s-]?\d", number).group(1) if re.match(r"^([A-Z]{2})[\s-]?\d", number)
        else "")
    owner = _FORM_PREFIX_LINE.get(prefix)
    return bool(owner) and owner not in _COMPATIBLE_FORM_LINES.get(line, {line})


# A property evidence / section may print an inland marine form (contractors'
# equipment, builders' risk - first-party property the lender is evidenced on).
_COMPATIBLE_FORM_LINES = {"property": {"property", "inland_marine"},
                          "inland_marine": {"inland_marine", "property"}}


# A peril / coverage named in an amount box's own name, and the words a
# document prints for it.
_COVERAGE_AMOUNT_WORDS = (
    ("namedwindstorm", ("windstorm", "namedstorm", "hurricane", "wind")),
    ("windstorm", ("windstorm", "wind")),
    ("windhail", ("wind", "hail")),
    ("ordinanceorlaw", ("ordinance",)),
    ("earthquake", ("earthquake", "earthmovement")),
    ("flood", ("flood",)),
    ("sinkhole", ("sinkhole",)),
    ("terrorism", ("terror",)),
    ("spoilage", ("spoilage",)),
    ("equipmentbreakdown", ("breakdown", "boiler")),
)
_AMOUNT_BOX_RE = re.compile(r"(?:Amount|Limit|Deductible|Percent)\w*_[A-N]$")


def percent_deductible_as_limit(field: str, text: str, raw_text: str) -> bool:
    """A LIMIT box holding a bare percentage the documents print only as a
    deductible ("WINDSTORM OR HAIL DEDUCTIBLE: 2%" -> the 28's wind / hail and
    named windstorm LIMITS read "2%" - live 85e51d02, 25 Oct). A limit is an
    amount; an inflation-guard / coinsurance percentage is printed with its own
    words and is not a deductible line, so it stands."""
    if not raw_text or not re.search(r"Limit\w*_[A-N]$", field or ""):
        return False
    m = re.fullmatch(r"\s*(\d{1,3}(?:\.\d+)?)\s*%\s*", str(text or ""))
    if not m:
        return False
    rx = re.compile(rf"(?<![\d.]){re.escape(m.group(1))}\s*%")
    lines = [ln for ln in str(raw_text).splitlines() if rx.search(ln)]
    return bool(lines) and all("deductible" in ln.lower() for ln in lines)


def amount_not_for_this_coverage(field: str, text: str, raw_text: str) -> bool:
    """An amount in a box about one named peril / coverage that no document
    prints on (or right under) a line naming that coverage."""
    if not raw_text or not _AMOUNT_BOX_RE.search(field or ""):
        return False
    # A coverage SECTION's amounts are judged here too (live bcfd175b, 25 Oct:
    # the 28's equipment breakdown deductible took the policy-wide "$500";
    # the schedule prints $5,000 under it). Whether the section is carried at
    # all stays scoped_evidence rule (b)'s question.
    key = re.sub(r"[^a-z]", "", (field or "").lower())
    words = next((w for k, w in _COVERAGE_AMOUNT_WORDS if k in key), None)
    if not words:
        return False
    try:
        from services.scoped_evidence import coverage_section
        if coverage_section(field) and not any(
                w in re.sub(r"[^a-z]", "", str(raw_text).lower()) for w in words):
            return False                  # no document names it: rule (b)'s refusal
    except Exception:                                      # noqa: BLE001
        pass
    digits = re.sub(r"\D", "", str(text or "").split(".")[0])
    if not digits or not re.fullmatch(r"[\s$,.\d%]+", str(text or "")):
        return False
    # The label an amount belongs to: its own line when that line names a
    # coverage or a deductible / limit ("THEFT CAUSE OF LOSS DEDUCTIBLE:
    # $5,000"), else the nearest line above (up to three) naming a coverage or
    # peril ("COVERAGE: BUILDING-EQUIPMENT BREAKDOWN" over "LIMIT DEDUCTIBLE" /
    # "INCLUDED $5,000"); a column header of bare limit / deductible words is
    # passed over.
    lines = str(raw_text).splitlines()
    rx = re.compile(rf"(?<!\d){digits}(?!\d)")
    every = {w for _k, ws in _COVERAGE_AMOUNT_WORDS for w in ws} | {"theft", "coverage", "causeofloss"}
    for i, line in enumerate(lines):
        if not rx.search(line.replace(",", "")):
            continue
        own = re.sub(r"[^a-z]", "", line.lower())
        if any(w in own for w in every) or re.search(r"deductible|limit", own) and len(own) > 15:
            if any(w in own for w in words):
                return False
            continue
        for j in range(i - 1, max(-1, i - 4), -1):
            up = re.sub(r"[^a-z]", "", lines[j].lower())
            if any(w in up for w in every):
                if any(w in up for w in words):
                    return False
                break
    return True


def issue_date_as_value(field: str, text: str, tooltip: str, raw_text: str) -> bool:
    """A date box (not an issue-date box) holding a date the documents print
    only as an issue / countersign / transaction date."""
    tl = str(tooltip or "").lower()
    # A box that asks for a POLICY's / declarations' own issue date takes it;
    # ACORD 28's "date the prior Evidence of Property was issued" does not.
    if not raw_text or "issue" in (field or "").lower() or (
            "issue" in tl and re.search(r"\b(?:polic(?:y|ies)|declarations?|binder|certificate)\b", tl)):
        return False
    if not re.search(r"Date_[A-N]$", field or ""):
        return False
    try:
        from services.extraction_service import issue_only_dates
        from services.normalization import normalize_date
        iso = normalize_date(text)
        return bool(iso) and iso in issue_only_dates(raw_text)
    except Exception:                                      # noqa: BLE001
        return False


_BOX_ELEMENT_WORDS = frozenset({
    "year", "count", "code", "amount", "number", "identifier", "indicator", "date", "month",
    "months", "percent", "description", "name", "limit", "value", "other", "type", "each",
    "total", "commercial", "property", "coverage", "information", "building", "improvement",
    "policy", "class",
})
_FACT_SYNONYMS = {"revenue": ("sale", "receipt", "revenue"), "employee": ("employee", "staff")}


def _box_words(field: str) -> List[str]:
    segs = re.sub(r"_[A-N]$", "", field or "").split("_")
    for seg in reversed(segs):
        words = [w for w in re.findall(r"[a-z]+", _field_words_lower(seg))
                 if len(w) >= 4 and w not in _BOX_ELEMENT_WORDS]
        if words:
            return words
    return []


def person_answer_for_another_question(field: str, text: str, said_for: Set[str],
                                       tooltip: str, raw_text: str) -> bool:
    """A short number (a year, a count, a code) equal to what a PERSON gave for
    another question, in a box whose own words name none of those facts, and
    printed in no document beside the box's own words."""
    if not said_for or not re.fullmatch(r"[\d\s.,]+", str(text or "")):
        return False
    digits = re.sub(r"\D", "", str(text).split(".")[0])
    if not digits or len(digits) > 4:
        return False
    box = {_stem(w) for w in re.findall(r"[a-z]+", _field_words_lower(field) + " "
                                       + str(tooltip or "").lower()) if len(w) >= 3}
    for k in said_for:
        kw = [_stem(w) for w in re.findall(r"[a-z]+", str(k).lower())
              if len(w) >= 3 and w not in _KEY_FILLER_WORDS]
        syn = {s for w in kw for s in _FACT_SYNONYMS.get(w, (w,))}
        if _fact_reads_as_this_box(k, field, tooltip) or (syn and syn & box and len(kw) == 1):
            return False
    words = [w[:4] for w in _box_words(field)]
    rx = re.compile(rf"(?<!\d){digits}(?!\d)")
    lines = str(raw_text or "").splitlines()
    for i, line in enumerate(lines):
        if rx.search(line.replace(",", "")):
            if not words:
                return False
            # Z42 review B: words by their stem ("roofing" box, "Roof replaced
            # 2018"); a column table prints the box's words in its header row,
            # so up to three lines above count when they carry ALL of them.
            if any(w in line.lower() for w in words):
                return False
            near = " ".join(lines[max(0, i - 3):i + 1]).lower()
            if all(w in near for w in words):
                return False
    return True


def _z41_judge(field: str, text: str, tu: str, said_for: Any, ctx: "_Context") -> Optional[str]:
    if ctx.raw_text and person_from_another_schedule(field, text, ctx.facts, ctx.raw_text):
        return f"{REASON_SCHEDULE_PERSON}: {text[:30]!r} is listed only on another schedule"
    if state_not_this_forms(field, text, ctx.form_id):
        return f"{REASON_STATE_NOT_THIS_FORMS}: {text[:4]!r} is not this form's state"
    if ctx.mapped is not None:
        if licence_state_as_mailing_state(field, text, ctx.mapped):
            return f"{REASON_LICENCE_STATE_AS_ADDRESS}: {text[:4]!r} is the row's licence state"
        if form_from_another_line(field, ctx.mapped, ctx.form_id):
            return f"{REASON_OTHER_LINES_FORM}: the row names another line's form"
    if percent_deductible_as_limit(field, text, ctx.raw_text):
        return f"{REASON_AMOUNT_NOT_FOR_THIS_COVERAGE}: {text[:20]!r} is printed only as a deductible"
    if amount_not_for_this_coverage(field, text, ctx.raw_text):
        return f"{REASON_AMOUNT_NOT_FOR_THIS_COVERAGE}: {text[:14]!r} is not printed for this coverage"
    if issue_date_as_value(field, text, tu, ctx.raw_text):
        return f"{REASON_ISSUE_DATE}: {text[:12]!r} is printed only as an issue date"
    if ctx.raw_text and person_answer_for_another_question(field, text, set(said_for or ()),
                                                           tu, ctx.raw_text):
        return (f"{REASON_PERSON_ANSWER_ELSEWHERE}: {text[:12]!r} was given for "
                f"{sorted(said_for)[0]}")
    return None


def _office_address_companions(out: Dict[str, str], mapped: dict, ai: Set[str]) -> None:
    """An address refused as an office's takes its row's other AI parts with
    it (the state "MI" of the carrier's head office prints everywhere)."""
    for f, why in list(out.items()):
        if not why.startswith(REASON_ADDRESS_NOT_THIS_PERSONS) or "office" not in why:
            continue
        m = _ADDRESS_PART_RE.match(f)
        if not m:
            continue
        head = f"{m.group('p')}_{m.group('k')}_"
        for c in ai:
            cm = _ADDRESS_PART_RE.match(c)
            if c not in out and cm and c.startswith(head) and cm.group("r") == m.group("r") \
                    and str(mapped.get(c) or "").strip():
                out[c] = f"{REASON_ADDRESS_NOT_THIS_PERSONS}: part of an office's address ({f})"


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
        ctx.ai_fields = set(ai)
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
        _office_address_companions(out, mapped, ai)
        # A refused additional-interest NAME takes its row's other AI boxes
        # (rank, interest type, address) with it - a row about nobody.
        for f in sorted(out):
            m_ = re.match(r"^AdditionalInterest_FullName_(?P<r>[A-N])$", f)
            if m_:
                for k in list(gpt_filled_set):
                    if (k.startswith("AdditionalInterest_") and k.endswith("_" + m_.group("r"))
                            and k not in out and str(mapped.get(k) or "").strip()):
                        out[k] = f"{REASON_ROW_NAME_REFUSED}: its row's name {f} was refused"
        # A refused deductible AMOUNT takes its own AI "deductible applies" tick
        # with it (live 85e51d02: the 126's GL property damage tick stayed Yes).
        for f in sorted(out):
            m_ = re.match(r"^(?P<b>.+)_DeductibleAmount_(?P<r>[A-N])$", f)
            if m_:
                tick = f"{m_.group('b')}_DeductibleIndicator_{m_.group('r')}"
                if tick in gpt_filled_set and tick not in out and str(mapped.get(tick) or "").strip():
                    out[tick] = f"{REASON_ROW_NAME_REFUSED}: its amount {f} was refused"
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
