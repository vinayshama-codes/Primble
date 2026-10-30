"""normalization.py

Value Normalization Layer for Conflict Detection (Beta Report §5 / Workstream 2).

Cross-document conflict detection was generating FALSE hard stops and warnings
because equivalent values appearing in different formats were compared as raw
strings. Examples from Beta Test 2 (Orbin Contracting):

    ORBIN CONTRACTING LLC   vs  Orbin Contracting, LLC      (name formatting)
    07/15/25                vs  7/15/2025                   (date formatting)
    LLC                     vs  Limited Liability Company   (entity synonym)
    4800 DAHLIA ST #D13     vs  4800 Dahlia Street D13       (address formatting)
    CSL                     vs  Combined Single Limit       (insurance synonym)
    Employers Mutual ...    vs  EMC Property & Casualty ...  (carrier alias)

This module provides the normalization primitives + a single dispatcher so the
cross-document conflict detectors compare NORMALIZED values, while the callers
keep the RAW values for display. A conflict is generated only when the
normalized values *materially* differ.

Design notes
------------
* PURE module — no DB, no I/O, no network. Easy to unit-test. Mirrors
  ``submission_integrity.py`` and ``underwriting_consistency.py``.
* Normalization is COMPARISON-ONLY. It never mutates stored facts. Raw values
  remain the source of truth for display (Beta Report §5.1: "Preserve raw
  values for user display").
* CARRIER aliases are handled as a *seed map + review* (per product decision):
  a small curated carrier-family map collapses known aliases (EMC ↔ Employers
  Mutual Casualty); any UNMATCHED carrier difference is surfaced for REVIEW
  rather than as a definitive hard conflict (Beta Report §5.2 carrier handling).
"""

import functools
import re
from datetime import datetime
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple

NORMALIZATION_MODEL_VERSION = "1.0.0"


# ── Field categorization (which normalizer applies to which fact key) ─────────

NAME_FIELDS = frozenset({
    "applicant_name", "dba_name", "named_insured", "insured_name",
    "business_name", "loss_run_insured_name",
})
DATE_FIELDS = frozenset({
    "effective_date", "expiration_date",
    "policy_effective_date", "policy_expiration_date",
})
ENTITY_TYPE_FIELDS = frozenset({
    "entity_type", "legal_entity_type", "business_type", "organization_type",
})
ADDRESS_FIELDS = frozenset({
    "mailing_address", "physical_address", "premises_address",
    "location_address", "insured_address",
})
CARRIER_FIELDS = frozenset({
    "carrier_name", "prior_carrier", "carrier", "current_carrier", "insurer_name",
    "wc_prior_carrier",
})
FEIN_FIELDS = frozenset({"fein", "fein_ssn", "tax_id"})
# `valuation_method` is normalized to "RCV"/"ACV" (the industry 3-letter term)
# at extraction time, but the real ACORD 140/141 ValuationCode field's own
# tooltip documents a SINGLE-LETTER code (A/R/V/M) - pdf_service now
# translates to that code when it stamps the field deterministically. Without
# a dedicated normalizer here, field_qa's value-vs-source check compared the
# stamped "R" against the untranslated fact "RCV" and flagged a false
# mismatch (confirmed live 2026-07-17) - a SEPARATE bug from the "RCV" vs "R"
# display inconsistency that prompted the stamping fix in the first place.
# Deliberately its OWN explicit field set rather than added to the generic
# _GENERAL_SYNONYMS table: "R"/"A" are single letters that would collide with
# unrelated fields' legitimate values (a grade, a class code, an initial) if
# expanded as a context-free global synonym.
VALUATION_METHOD_FIELDS = frozenset({"valuation_method"})

# Curated name-like keys that hold an organization name but do NOT end in
# "_name" (holder / payee style). Extend here if new such keys appear.
_NAME_LIKE_KEYS = frozenset({"certificate_holder"})


# ── Yes / No: ONE vocabulary and ONE type door (SYS-07, 2026-09-04) ───────────
#
# The client's item: *"The same affirmative answer can arrive as 'Yes,' boolean
# true, X, or a checked box depending on the source document and extraction
# path. These representation differences should not create false conflicts...
# Route this through the same pre-comparison canonicalization layer used for
# other equivalent values."* This module IS that layer, so the vocabulary lives
# here and every other module asks it.
#
# WHY IT LIVES HERE AND NOT IN THE COMPARATOR. Before this, EIGHT modules each
# carried a private "what counts as affirmative" list and no two agreed:
# `fact_equivalence._YES` knew "x", `pdf_service._resolve_bool_indicator` did
# not (so an affirmative X on a certificate ticked the *No* box on a generated
# ACORD form), `answer_semantics._AFFIRM_TOKENS` knew neither "x" nor "1", and
# NONE of them knew a checkmark glyph. Same one-rule-many-copies shape as C1's
# five comparison sites and H1-C's phantom keys. `normalization` is the leaf
# every one of those modules can already import, so it is the only place the
# rule can sit without a new dependency edge.
#
# WHAT IT REFUSES TO DECIDE, deliberately:
#   * "N/A" / "not applicable" - a NON-ANSWER, not a No. `answer_semantics`
#     owns that distinction (C2-G) and core principle 3 forbids turning an
#     absence into a negative.
#   * a bare ballot-X glyph with no box around it (U+2717 / U+2718) - it means
#     "checked" in a column and "wrong/no" standing alone. No opinion.
#   * anything that is not the WHOLE value. "Yes - see attached schedule" is
#     not a bare token, so it falls through to ordinary text comparison rather
#     than being read as a bald Yes.
# In every one of those cases the answer is None ("cannot say"), which callers
# must treat as "compare it as text", never as a No.

_YES_TOKENS = frozenset({
    "y", "yes", "true", "t", "1", "on", "checked",
    "x",                  # the mark a broker puts in an ACORD checkbox
    "✓", "✔",     # ✓ ✔  check marks
    "☑", "☒",     # ☑ ☒  ballot box CHECKED (either mark inside the box)
    "included", "include",
    # A DECLARATIONS PAGE DOES NOT SAY "Yes". It says the coverage is there.
    # Live-shape vocabulary, whole-value only: a grid cell reading "Covered" is
    # the same affirmative as the certificate's "X" for the same coverage.
    # "applicable" is deliberately ABSENT - "Not Applicable" must stay a
    # NON-answer (core principle 3), and the negation rule below would turn it
    # into a No the moment "applicable" became an affirmative.
    "covered", "elected", "purchased", "applies", "provided", "afforded",
    "carried", "granted",
})
_NO_TOKENS = frozenset({
    "n", "no", "false", "f", "0", "off", "unchecked",
    "☐",               # ☐  ballot box EMPTY
    "excluded", "exclude",
    "declined", "decline", "rejected", "waived",
})
# Read AFTER a negation only: "no coverage" is a No, a box reading "coverage"
# on its own asserts nothing.
_YN_NEGATABLE_NOUNS = frozenset({"coverage", "cover", "coverages"})
# NEGATION IS STRUCTURAL, NOT ENUMERATED. "not covered" / "not purchased" /
# "no coverage" are one rule, not three table rows - so an affirmative added
# above is negatable the day it is added and cannot be half-covered.
_YN_NEGATION_RE = re.compile(r"^(?:not|no|non)[\s-]+(?P<rest>.+)$")
# OCR letter-spacing on a scanned form: "Y e s", "N o". Only when the WHOLE
# value is single letters - "A B C" joins to "abc" and is still not a token.
_YN_SPACED_LETTERS_RE = re.compile(r"^(?:[A-Za-z][ ]){1,5}[A-Za-z]$")
# NOT in either table, on purpose: "none", "null", "blank", "n/a". Those are
# the machine's own spellings of "no value found" and a human's non-answer -
# `_fv`, `underwriting_consistency._normalize` and `answer_semantics` already
# own them, and reading one as a No would turn an absence into a negative
# (core principle 3). "check" is out too: on its own it is as likely a payment
# method as a tick.
# The subset that is unambiguous ENGLISH rather than a mark. Only these license
# the value-shaped fallback in `fact_equivalence.same_fact`: a bare "1" against
# a bare "0" on an untyped field must stay two numbers, not become Yes vs No.
_YES_NO_STRONG_WORDS = frozenset({
    "yes", "no", "true", "false", "checked", "unchecked",
})
# One layer of brackets/parens a checkbox is often transcribed inside: "[X]",
# "(x)", "{X}". An EMPTY pair strips to nothing and yields no opinion - an
# empty bracket is far more often OCR noise than an asserted negative.
_YN_BRACKET_RE = re.compile(r"^[\[\(\{<]\s*(.*?)\s*[\]\)\}>]$")
# Brackets are trimmed as well as matched by `_YN_BRACKET_RE`: OCR routinely
# drops one half of a checkbox pair, leaving "X]" or "[X".
_YN_TRIM_CHARS = " \t\r\n.,;:!*_'\"`[]()<>{}"


def yes_no_token(value: Any) -> Optional[str]:
    """``"Y"`` / ``"N"`` / ``None`` for one value. THE affirmative reader.

    ``None`` means "this is not a Yes/No answer" - never "No". A real ``bool``
    is answered directly: the previous implementation did ``str(value or "")``,
    so ``False`` collapsed to the empty string and a stored boolean *False*
    was silently unreadable.
    """
    if isinstance(value, bool):
        return "Y" if value else "N"
    if value is None:
        return None
    s = str(value).strip().lower()
    if not s:
        return None
    # PDF checkbox export values print as /Yes, /On, /1.
    s = s.lstrip("/").strip()
    m = _YN_BRACKET_RE.match(s)
    if m:
        s = m.group(1).strip()
    s = s.strip(_YN_TRIM_CHARS)
    if not s:
        return None
    if _YN_SPACED_LETTERS_RE.match(s):
        s = s.replace(" ", "")
    if s in _YES_TOKENS:
        return "Y"
    if s in _NO_TOKENS:
        return "N"
    neg = _YN_NEGATION_RE.match(s)
    if neg:
        rest = neg.group("rest").strip(_YN_TRIM_CHARS)
        if rest in _YES_TOKENS or rest in _YN_NEGATABLE_NOUNS:
            return "N"
    return None


# A value that arrives carrying its OWN question: "Hired and Non-Owned Auto
# Coverage: X". Live run 1 (2026-09-04): the extractor returned the whole
# printed line for the certificate and a bare "X" for the same layout in
# another package, so one document's answer conflicted with the other's purely
# because of where the model chose to stop reading. That is SYS-07's own class -
# the client's wording is "depending on the source document AND EXTRACTION PATH".
#
# A LABEL IS NOT A QUALIFIER, and that distinction is the whole safety argument:
#   "Hired and Non-Owned Auto Coverage: X"  -> the label restates the question,
#                                              the answer is X
#   "Yes - see the attached schedule"       -> the tail QUALIFIES the answer and
#                                              must never be flattened
# The tail therefore has to be a WHOLE bare token, which the second shape fails.
# SEPARATORS: EVERY way a printed form divides a question from its answer.
#
# The first cut accepted ":" and "=" only, because that is what the live run
# happened to print - which is fitting the fixture, the exact thing the change
# quality bar forbids. A dec page, a broker worksheet and a scanned grid divide
# the two with a dash, a column gap, a dot leader or a table pipe just as often:
#
#     Hired and Non-Owned Auto Coverage: X          colon
#     Hired and Non-Owned Auto Coverage = X         equals
#     Hired and Non-Owned Auto Coverage - X         hyphen / en / em dash
#     Hired and Non-Owned Auto Coverage .......  X  dot leader
#     Hired and Non-Owned Auto Coverage    X        a COLUMN GAP, which is what
#                                                   a two-column layout becomes
#                                                   once it is flattened to text
#     Hired and Non-Owned Auto Coverage | X         a table cell boundary
#
# WIDENING THE SEPARATORS IS SAFE BECAUSE THE TAIL TEST DOES THE WORK, not the
# separator. A qualifier is never a bare Yes/No token:
#     "Yes - see the attached schedule"   tail = "see the attached schedule"  no
#     "Yes, but only for scheduled autos" tail is not reached (no separator)   no
#     "Yes - only scheduled autos"        tail = "only scheduled autos"        no
# The dash was originally excluded for fear of the first of those. That fear was
# unfounded - it fails on the tail, not on the separator - and excluding the
# dash cost real coverage.
_YN_LABEL_SPLIT_RE = re.compile(
    r"^(?P<head>.*\S)"                      # greedy: find the LAST separator
    r"[ \t]*(?::|=|\||\t|—|–|-|\.{2,}|[ ]{1,})[ \t]*"
    r"(?P<tail>\S{1,24})$"
)
# Every character the separator alternation can consume, so a head can never
# retain one. Kept beside the pattern it mirrors.
_YN_SEP_CHARS = " 	:=|.—–-"
_YN_LABEL_MAX_WORDS = 12          # a question label, never a paragraph
_YN_LABEL_MAX_CHARS = 140
# A LABEL IS MADE OF WORDS. The structural guard that stops a numeric pair from
# being read as an answer: "3 - 0" has no label, so its "0" is a score and not a
# No. Requires one real alphabetic word, which every genuine question label has
# and no ratio, score, time or measurement does.
_YN_LABEL_WORD_RE = re.compile(r"[A-Za-z]{3,}")
# A label that is ITSELF a non-answer cannot license reading the mark beside
# it: "N/A: X" says the question does not apply, whatever the X is. The same
# spellings `_fv` and `underwriting_consistency._normalize` already drop.
_YN_LABEL_NON_ANSWERS = frozenset({
    "n/a", "na", "n a", "not applicable", "none", "null", "unknown", "tbd",
})


def yes_no_answer(value: Any) -> Optional[str]:
    """``"Y"`` / ``"N"`` / ``None``, reading a LABELLED answer as well as a bare
    one. Use this wherever the FIELD is already known to hold a Yes/No.

    ``yes_no_token`` stays strict on purpose: it is what licenses the
    value-shaped fallback in ``fact_equivalence``, which runs on facts nothing
    declares, and a labelled value there would be read on no evidence at all.
    """
    tok = yes_no_token(value)
    if tok:
        return tok
    if value is None or isinstance(value, bool):
        return None
    # A LINE BREAK IS A COLUMN BOUNDARY. Joining with a single space made
    # a two-line table cell - one of the commonest flattened shapes there
    # is - indistinguishable from prose. Two spaces keep it a separator.
    s = "  ".join(str(value).split("\n")).strip()
    if not s or len(s) > _YN_LABEL_MAX_CHARS:
        return None
    m = _YN_LABEL_SPLIT_RE.match(s)
    if not m:
        return None
    head, tail = m.group("head").strip(), m.group("tail").strip()
    # THE HEAD MUST NOT KEEP A SEPARATOR. Once a single space counts as a
    # divider the greedy head absorbs the real separator - "Not Applicable - X"
    # splits to head "Not Applicable -", which is not the string the non-answer
    # table holds, so the label escaped every check below and the X was read as
    # a Yes on a question that does not apply. Strip them and the checks see the
    # actual label.
    head = head.rstrip(_YN_SEP_CHARS).strip()
    if not head:
        return None
    # THE TAIL CARRIES THE ANSWER, and it has to be a WHOLE bare token. This is
    # the condition that keeps every qualifier out, whatever divides it.
    tail_tok = yes_no_token(tail)
    if not tail_tok:
        return None
    # A BARE DIGIT AFTER A LABEL IS A NUMBER, NOT AN ANSWER. "0"/"1" alone on a
    # Yes/No field can only be the answer - there is nothing else the box holds.
    # Behind a label they are exactly the shape of a labelled COUNT or amount,
    # and "Total Losses - 0" is not a No. Found by the fuzz sweep, not by
    # reasoning: the first cut read it as one.
    if tail.strip(_YN_TRIM_CHARS).isdigit():
        return None
    # The head must read as a LABEL: short, made of words, not a paragraph, and
    # not itself a non-answer.
    if len(head.split()) > _YN_LABEL_MAX_WORDS or ". " in head:
        return None
    if not _YN_LABEL_WORD_RE.search(head):
        return None
    if head.strip(_YN_TRIM_CHARS).lower() in _YN_LABEL_NON_ANSWERS:
        return None
    # A NEGATION IMMEDIATELY BEFORE THE TAIL BELONGS TO THE TAIL. Widening the
    # separator to a single space put "Hired Auto Not Covered" within reach of
    # the splitter, where the head would end "Not" and the tail read as a Yes -
    # the exact inversion this whole item exists to prevent. Refuse; ordinary
    # text comparison then applies and nobody guesses.
    if head.split()[-1].strip(_YN_TRIM_CHARS).lower() in ("not", "no", "non", "never"):
        return None
    # If the label is ITSELF a Yes/No answer, the two must agree. A value that
    # says both things says neither.
    head_tok = yes_no_token(head)
    if head_tok and head_tok != tail_tok:
        return None
    return tail_tok


def canonical_yes_no(value: Any) -> Optional[str]:
    """The ONE canonical printing of an affirmative / negative, or None.

    This is the "one canonical true value / one canonical false value" the
    acceptance criteria asks for. Callers that need ACORD's single-letter form
    take ``yes_no_answer`` / ``yes_no_token`` instead - same vocabulary,
    different printing.
    """
    tok = yes_no_answer(value)
    return {"Y": "Yes", "N": "No"}.get(tok) if tok else None



# ── A POLICY NUMBER FIELD, AND A VALUE CARRYING ITS OWN LABEL ───────────────
# Both derived, both owned here, for the same reason the Yes/No vocabulary is:
# `fact_comparison`, `fact_equivalence` and `pdf_service` all need the same
# answer and a second copy is how the auto-symbol and Umbrella-SIR bugs each
# survived their first fix.
# ── A FORM NUMBER IS NOT A POLICY NUMBER - the one shape door (24 Sep 2026) ──
# A form number names coverage WORDING; a policy number names a contract.
# Until today the test existed twice (extraction and stamping) and read ONE
# shape - ISO/AAIS "IM 7100 06 04". The client's own package prints its
# carrier's forms in three more, and every one passed as a POLICY number at the
# merge, the row scrub, producer confirmation and the box guard:
#   series + series letter + edition   CU7001A 11-15 / CU7001A(11/15) /
#                                      CA7000A 02-22 / IL 71 31A 04 01 /
#                                      CG 70 01A 10 12 / CG7001A Ed. 10-12
#   series + bracketed edition         IM7100(06/04) / CA7450(09-24)
#   series + edition LETTER            CA7450 M / WC 00 00 00 C
# Structural, not a list of known forms: two or three letters, a four-digit
# series (ISO prints it as two pairs), then an edition - a real MONTH (01-12)
# and a year, or a single edition letter. A form series never runs five digits
# together, so a policy number that does (BOP 7654321 01 26, SRC-4410982) is
# never read as one, and one that leads with a digit (6E7-40-02---26) or ends
# on a bare term suffix (BBC7263-26, BBC7263 - 26) has no edition to match.
_ISO_FORM_NUMBER_RE = re.compile(r"^[A-Z]{2}[ -]?\d{2,4}(?:[ -]\d{2}){2,3}$", re.I)
_CARRIER_FORM_NUMBER_RE = re.compile(
    r"^(?!.*\d{5})[A-Z]{2,3}\s?\d{2}\s?\d{2}[A-Z]{0,2}\s*[(\[]?\s*"
    r"(?:ed(?:ition)?\.?\s*)?(?:0[1-9]|1[0-2])\s*[-/.\s]\s*(?:\d{2}|\d{4})\s*[)\]]?$",
    re.I)
_EDITION_LETTER_FORM_NUMBER_RE = re.compile(r"^[A-Z]{2,3}(?:\s?\d{2}){2,3}\s[A-Z]$")
# ...and a SERIES DESIGNATOR between the line prefix and the number (6 Oct 2026,
# Choice Electric). ISO's declarations forms and carriers' own forms put a
# second, short letter group there: "IL DS 71 05 02 08", "CP DS 70 00 09 06",
# "CU DS 71 02 04 14" (DS = declarations schedule), "CG T0 96 04 17",
# "IL T8 01 01 01", "CG D0 31 10 91", "IL N 020 09 03". Every one passed as a
# POLICY number and "IL DS 71 05 02 08" printed on ACORD 125 question 4. The
# shape still ends on a real edition (month 01-12, two-digit year), the two
# letter groups are separated by a space, and the number groups are spaced
# pairs - a policy number of the "LL dddddddd" / "LLL-dddddd-dd" families can
# never take it.
_DESIGNATOR_FORM_NUMBER_RE = re.compile(
    r"^[A-Z]{2}\s[A-Z][A-Z0-9]?\s\d{2,3}(?:\s\d{2}){0,2}\s(?:0[1-9]|1[0-2])\s\d{2}$")
# ...and a carrier form whose BRACKETED edition writes the month with one digit,
# or whose series carries a dotted sub-number (7 Oct 2026, round 5 corpus):
# "CA8214(5-12)", "CA8214.1(5-12)", "CA8282(8-18)", "CA8112.2(11-15)" - EMC page
# footers the model tagged as the policy number of their declarations entries.
# The brackets are what make the one-digit month safe: a policy number never
# closes on a parenthesised month-year, and the series still never runs five
# digits together.
_BRACKETED_EDITION_FORM_NUMBER_RE = re.compile(
    r"^(?!.*\d{5})[A-Z]{2,3}\s?\d{2}\s?\d{2}(?:\.\d{1,2})?[A-Z]{0,2}\s*[(\[]\s*"
    r"(?:0?[1-9]|1[0-2])\s*[-/.]\s*(?:\d{2}|\d{4})\s*[)\]]$", re.I)


def looks_like_a_form_number(value: Any) -> bool:
    """True when ``value`` is shaped like an insurance FORM number (ISO, AAIS or
    a carrier's own edition-dated form), never a contract's policy number.

    Shape only. A caller holding the declarations' own "POLICY NUMBER" printings
    passes them through `is_contract_identifier` first - a printed contract
    number is a policy number whatever it looks like."""
    s = str(value or "").strip()
    if not s or len(s) > 40:
        return False
    return bool(_ISO_FORM_NUMBER_RE.match(s)
                or _CARRIER_FORM_NUMBER_RE.match(s)
                or _EDITION_LETTER_FORM_NUMBER_RE.match(s)
                or _DESIGNATOR_FORM_NUMBER_RE.match(s)
                or _BRACKETED_EDITION_FORM_NUMBER_RE.match(s))


# A page's own FOOTER: the page counter, the copy marking, the copyright line.
# A form number prints there; the line that carries it is page furniture.
_PAGE_FOOTER_MARK_RE = re.compile(
    r"\bpage\s*\d+\s*of\s*\d+\b|\binsured'?s?\s+copy\b|\bcopyright\b|©", re.I)


def printed_as_page_footer(value: Any, text: Any) -> bool:
    """True when ``text`` prints ``value`` on a line that is the page's own
    footer (a "Page 1 of 2" counter, "INSURED COPY", a copyright mark).

    Choice Electric (6 Oct 2026): three declarations print "POLICYNUMBER: IL DS
    71 05 02 08" - the contract number was redacted and the page's form number
    sits beside the label - and the same three pages close with "IL DS 71 05 02
    08 INSURED COPY Page 1of2". The label alone made it a contract. The footer
    is the document saying, in its own layout, what the token is."""
    s = str(value or "").strip()
    t = str(text or "")
    if not s or not t:
        return False
    tokens = [re.escape(tok) for tok in s.split() if tok]
    if not tokens:
        return False
    pattern = re.compile(r"(?<![A-Za-z0-9])" + r"\s*".join(tokens) + r"(?![A-Za-z0-9])", re.I)
    for m in pattern.finditer(t):
        ls = t.rfind("\n", 0, m.start()) + 1
        le = t.find("\n", m.end())
        line = t[ls:le if le != -1 else len(t)]
        if _PAGE_FOOTER_MARK_RE.search(line[:m.start() - ls] + " " + line[m.end() - ls:]):
            return True
    return False


_ACCOUNT_LABEL_RE = re.compile(r"\b(?:account|acct)\b", re.I)
_POLICY_NO_LABEL_RE = re.compile(
    r"\bpol(?:icy|\.)?\s*(?:number|num|no\.?|nbr|#)", re.I)


def _identifier_key(value: Any) -> str:
    return re.sub(r"[^0-9A-Za-z]", "", str(value or "")).upper()


def labelled_identifiers(entries: Any) -> Tuple[Set[str], Set[str]]:
    """(contract numbers, account numbers) the declarations index PRINTS under
    their own label - "POLICY NUMBER: 6E7-40-02---26", "Account Number:
    0482854". Keyed on the alphanumerics only. Positive evidence both ways:
    an entry whose label names neither contributes nothing."""
    contracts: Set[str] = set()
    accounts: Set[str] = set()
    for e in entries if isinstance(entries, list) else []:
        if not isinstance(e, dict):
            continue
        label = str(e.get("label") or "")
        raw_value = str(e.get("value") or "")
        key = _identifier_key(raw_value)
        if len(key) < 4:
            continue
        if _ACCOUNT_LABEL_RE.search(label) and not _POLICY_NO_LABEL_RE.search(label):
            accounts.add(key)
        elif _POLICY_NO_LABEL_RE.search(label):
            # A contract identifier carries a digit and is not a DATE. A
            # redacted "POLICY NUMBER" cell reads its neighbour instead -
            # "EFFECTIVE DATE 01/01/2025", "X If Supplemental Declarations Is
            # Attached" (6 Oct 2026) - and neither is a contract.
            if not re.search(r"\d", key) or _LABELLED_DATE_RE.search(raw_value):
                continue
            contracts.add(key)
    return contracts, accounts


_LABELLED_DATE_RE = re.compile(r"\b\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}\b")


def is_not_a_policy_number(value: Any, entries: Any = None, text: Any = None) -> bool:
    """True for a value that cannot be THIS package's policy number.

    * NO DIGIT (Brent, 6 Oct 2026): *"Policy number will always have an actual
      number somewhere in the string, even if it starts with letters."* The
      Business Auto declarations print "POLICYNUMBER: COMMERCIAL AUTO" - a
      redaction label - and it was the auto policy number on ACORD 125 and 131.
      No label rescues a digit-free value.
    * A FORM number (`looks_like_a_form_number`), unless the declarations print
      it under a POLICY NUMBER label - and that label does not rescue a form
      number the same document prints as its own page footer (``text``; see
      `printed_as_page_footer`).
    * The value the declarations print under an ACCOUNT label (Orbin's "Account
      Number: 0482854" was listed on the card as a fifth policy).
    * NO IDENTIFIER LEFT (7 Oct 2026, round 5): words plus a form number
      ("COMMERCIAL AUTO CA DS 70 01 09 06"), a date, an amount, a lone digit, a
      street address, a value naming itself another identifier ("ACCOUNT
      4471100") or a number cut at its separator ("CGL-2024-") - see
      `policy_number_refusal`. No label rescues these either.
    """
    return bool(policy_number_refusal(value, entries, text))


# ── AN IDENTIFIER MUST BE LEFT (7 Oct 2026, round 5) ─────────────────────────
# Brent's digit rule reads the WHOLE value, and "COMMERCIAL AUTO CA DS 70 01 09
# 06" carries digits - every one of them the declarations' own FORM number. The
# model joined the redacted "POLICYNUMBER: COMMERCIAL AUTO" with the form number
# printed on the next line, the merge kept it (printed, in order) and it printed
# on ACORD 125 question 4, 127, 137 and the 131 underlying auto row. The replay
# corpus (690 sessions) holds the same hole in other shapes: a date
# ("09/01/2026", "07/15/2025 - 07/15/2026"), an amount ("$4,600,000"), a lone
# digit ("9", "Primble Beta Testing Round 1"), a street address ("1500 Market
# Street"), a page header's "ACCOUNT 4471100" and a number cut at its dash
# ("CGL-2024-") - each in a policy-number box or a line's policy number.
#
# So: take away what a value's digits can belong to that is not a contract - a
# form number (every shape `looks_like_a_form_number` knows, wherever it sits
# among the words), a date or a policy-year span, an amount, a percentage - and
# the words; what is left must still carry a number - at least four letters and
# digits, or a short code with a letter in it ("X-1"), never a bare count like
# "9". TOKEN by token, never by substring: "6E7-40-02-26" is a policy
# number, not the date "40-02-26" inside it. A value that keeps an identifier is
# never rewritten here - "Commercial Auto: BA-456789" is not refused, and is not
# cut down to its number either (measured 7 Oct: no stored value has that shape,
# and "CPP 4Q 887214 26" / "GL 7784120 25" show a line word can BE the number's
# own prefix).
_ID_TOKEN_EDGE = "()[]{}<>,;:\"'"
_ID_TOKEN_SEPARATORS = frozenset({"-", "–", "/", "&", "#", "|", "."})
# Words that say the value is ANOTHER identifier. Whole tokens only, so a
# carrier prefix glued to its number ("EIN-12345") is never read as a label.
_OTHER_IDENTIFIER_LABEL_WORDS = frozenset({
    "account", "acct", "fein", "ein", "naic", "phone", "telephone", "fax",
    "license", "licence", "ssn",
})
_MONTH_NAME_RE = re.compile(
    r"^(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|"
    r"aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?$", re.I)
_YEAR_SPAN_TOKEN_RE = re.compile(r"^((?:19|20)\d{2})\s*[-–/]\s*((?:19|20)\d{2})$")
_YEAR_TOKEN_RE = re.compile(r"^(?:19|20)\d{2}$")
_MONEY_TOKEN_RE = re.compile(
    r"^\$\s*\d[\d,]*(?:\.\d{1,2})?$|^\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?$|^\d+\.\d{2}$")
_PERCENT_TOKEN_RE = re.compile(r"^\d+(?:\.\d+)?%$")
_HOUSE_NUMBER_RE = re.compile(r"^\d{1,6}[A-Za-z]?$")


def _id_token(tok: str) -> str:
    return tok.strip(_ID_TOKEN_EDGE)


def _id_alnum(tok: str) -> int:
    return len(re.sub(r"[^0-9A-Za-z]", "", tok))


def _is_month_name_date(window: str) -> bool:
    """"January 1, 2025" / "Jan. 1, 2025" / "15 Mar 2026" - a month NAME in the
    first two words and the whole window one date (`normalize_date`)."""
    ws = window.split()
    if not any(_MONTH_NAME_RE.match(w.strip(_ID_TOKEN_EDGE)) for w in ws[:2]):
        return False
    return bool(normalize_date(re.sub(r"(?<=[A-Za-z])\.", "", window)))


def _mark_runs(toks: List[str], test, width: int) -> List[Tuple[int, int]]:
    """Left-to-right, longest-first runs of whole tokens `test` accepts - as
    printed ("CA8214(5-12)" keeps its brackets) or without edge punctuation."""
    runs: List[Tuple[int, int]] = []
    i = 0
    while i < len(toks):
        for j in range(min(len(toks), i + width), i, -1):
            window = " ".join(toks[i:j])
            if test(window) or test(window.strip(_ID_TOKEN_EDGE)):
                runs.append((i, j))
                i = j
                break
        else:
            i += 1
    return runs


@functools.lru_cache(maxsize=65536)
def _no_identifier_reason(s: str) -> Optional[str]:
    """Why ``s`` holds no contract identifier, or None when one is left. ``s``
    carries a digit and is not itself form-shaped (the caller's earlier rules).
    A colon separates like a space ("DATE:01/23/2025" is a label and a date)."""
    toks = s.replace(":", " ").split()
    if not toks:
        return None
    if not _POLICY_NO_LABEL_RE.search(s):
        if any(_id_token(t).lower().rstrip(".#") in _OTHER_IDENTIFIER_LABEL_WORDS
               for t in toks) or re.search(r"(?<![A-Za-z])tax\s*(?:id|identification)\b", s, re.I):
            return "OTHER_IDENTIFIER_LABEL"
    # A house number, a street word, then its suffix: an address, not a number.
    if len(toks) >= 3 and _HOUSE_NUMBER_RE.match(_id_token(toks[0])):
        words = [_id_token(t).lower().rstrip(".") for t in toks[1:]]
        for k, w in enumerate(words):
            if k >= 1 and w in _STREET_SUFFIXES and any(
                    re.fullmatch(r"[a-z]{3,}", x) and x not in _STREET_SUFFIXES
                    for x in words[:k]):
                return "STREET_ADDRESS"
    # A number cut at its separator ("CGL-2024-") identifies nothing.
    if s.rstrip()[-1:] in ("-", "–", "/"):
        return "TRUNCATED_IDENTIFIER"
    taken = [""] * len(toks)
    for i, j in _mark_runs(toks, looks_like_a_form_number, 8):
        for k in range(i, j):
            taken[k] = "form"
    for i, j in _mark_runs(toks, _is_month_name_date, 4):
        if any(taken[k] for k in range(i, j)):
            continue
        for k in range(i, j):
            taken[k] = "date"
    for k, raw in enumerate(toks):
        if taken[k]:
            continue
        t = _id_token(raw)
        if (_YEAR_SPAN_TOKEN_RE.match(t) or normalize_date(t)
                or (_YEAR_TOKEN_RE.match(t) and (
                    (k + 2 < len(toks) and toks[k + 1] in _ID_TOKEN_SEPARATORS
                     and _YEAR_TOKEN_RE.match(_id_token(toks[k + 2])))
                    or (k >= 2 and taken[k - 2] == "date" and toks[k - 1] in _ID_TOKEN_SEPARATORS)))):
            taken[k] = "date"
        elif (_MONEY_TOKEN_RE.match(t) or _PERCENT_TOKEN_RE.match(t)
              or (k >= 1 and toks[k - 1] == "$" and re.fullmatch(r"\d[\d,]*(?:\.\d+)?", t))
              or (k + 1 < len(toks) and toks[k + 1] == "%" and re.fullmatch(r"\d+(?:\.\d+)?", t))):
            taken[k] = "amount"
    kept = [t for k, t in enumerate(toks) if not taken[k] and re.search(r"\d", t)]
    left = sum(_id_alnum(t) for t in kept)
    if left >= 4:
        return None
    if left == 0:
        for kind, reason in (("form", "LABEL_AND_FORM_NUMBER"), ("date", "DATE_NOT_AN_IDENTIFIER"),
                             ("amount", "AMOUNT_NOT_AN_IDENTIFIER")):
            if kind in taken:
                return reason
    # A bare one-to-three digit number ("9", "41", "Round 1") is a count, an
    # ordinal or a row number. A short code that mixes letters in ("X-1", the
    # SYS-06 pin of 4 Sep) has never been refused for its length and is not now.
    if not any(re.search(r"[A-Za-z]", t) for t in kept):
        return "TOO_SHORT_FOR_AN_IDENTIFIER"
    return None


# Reasons the door gives that the rules before 7 Oct 2026 did not - a guard
# that records which rule took a box names these.
NEW_POLICY_NUMBER_REFUSALS = frozenset({
    "OTHER_IDENTIFIER_LABEL", "STREET_ADDRESS", "TRUNCATED_IDENTIFIER",
    "LABEL_AND_FORM_NUMBER", "DATE_NOT_AN_IDENTIFIER", "AMOUNT_NOT_AN_IDENTIFIER",
    "TOO_SHORT_FOR_AN_IDENTIFIER",
})


def policy_number_refusal(value: Any, entries: Any = None, text: Any = None) -> Optional[str]:
    """Why ``value`` cannot be THIS package's policy number - a reason code - or
    None when it can. `is_not_a_policy_number` is this, as a bool.

    Reasons: NO_DIGIT, FORM_NUMBER, FORM_NUMBER_FOOTER, ACCOUNT_NUMBER (the
    rules of 24 Sep / 6 Oct, unchanged) and the seven `NEW_POLICY_NUMBER_
    REFUSALS` of `_no_identifier_reason`. A value the declarations print under
    a POLICY NUMBER label still rescues a FORM-shaped value (the label decides
    that edge, as before); it never rescues one with no identifier left."""
    s = str(value or "").strip()
    if not s:
        return None
    if not re.search(r"\d", s):
        return "NO_DIGIT"
    form_shaped = looks_like_a_form_number(s)
    if not form_shaped:
        reason = _no_identifier_reason(s)
        if reason:
            return reason
    contracts, accounts = labelled_identifiers(entries) if entries else (set(), set())
    key = _identifier_key(s)
    if key in contracts:
        if form_shaped and text and printed_as_page_footer(s, text):
            return "FORM_NUMBER_FOOTER"
        return None
    if key in accounts:
        return "ACCOUNT_NUMBER"
    return "FORM_NUMBER" if form_shaped else None


_POLICY_NUM_WORDS = ("number", "num", "no", "nbr", "id")


def is_policy_number_field(fact_key: Any) -> bool:
    """True when this fact names a POLICY CONTRACT number.

    Derived from the key's own tokens, never a list: `policy_number`,
    `prior_policy_number`, `umbrella_policy_number` and the per-coverage-line
    form `policy_number@auto` all answer True the day they are added.
    A `certificate_number` does NOT - a certificate is not the contract.
    """
    k = str(fact_key or "").split("@", 1)[0].lower()
    toks = [t for t in re.split(r"[^a-z0-9]+", k) if t]
    return "policy" in toks and any(w in toks for w in _POLICY_NUM_WORDS)


# A value that arrives carrying its own printed label - the SYS-07 shape, one
# fact over. Live run 1 showed the extractor returning the whole printed line
# for one document and the bare value for the same layout in another, so one
# document's answer conflicted with the other's purely by where the model
# stopped reading. The label must END in a separator or a number-word, so a
# value that merely BEGINS with one of these words is untouched.
_LEADING_LABEL_RE = re.compile(
    r"^(?:policy|certificate|cert|binder|contract|pol)\s*"
    r"(?:no\.?|number|num|nbr|#)?\s*[:#\-]?\s+(?P<rest>\S.*)$",
    re.IGNORECASE)


def strip_leading_label(value: Any) -> str:
    """``"Policy No. BBC7263"`` -> ``"BBC7263"``. Unchanged when there is no
    label, so it is always safe to call."""
    s = str(value or "").strip()
    m = _LEADING_LABEL_RE.match(s)
    return m.group("rest").strip() if m else s


def is_strong_yes_no_word(value: Any) -> bool:
    """True when the value is an unambiguous English boolean word.

    The STRUCTURAL second condition (H1-F's standing lesson: a test that is
    necessary but not sufficient needs one). "X" is a Yes only when something
    unambiguous sits opposite it.
    """
    if isinstance(value, bool):
        return True
    s = str(value or "").strip().lower().lstrip("/").strip()
    m = _YN_BRACKET_RE.match(s)
    if m:
        s = m.group(1).strip()
    return s.strip(_YN_TRIM_CHARS) in _YES_NO_STRONG_WORDS


# ── Which FIELDS hold a Yes/No ───────────────────────────────────────────────
# Curated overrides only. Everything else is DERIVED from declarations that
# already exist, so a Yes/No fact added tomorrow is classified correctly the
# day it is added and nobody has to remember this list.
YES_NO_FIELDS: FrozenSet[str] = frozenset()

_YES_NO_SHAPE_TOKENS = frozenset({"indicator", "required", "confirmed"})
_YES_NO_SHAPE_PREFIXES = ("is_", "has_")
_YES_NO_SHAPE_SUFFIXES = ("_yn", "_y_n")
# A key that NAMES another type is not a Yes/No however it starts. `has_` and
# `is_` are a guess, and a guess must never outrank a key that says outright it
# holds an amount, a count or a date - `has_umbrella` is a boolean,
# `has_umbrella_limit` would not be. Declared Yes/No facts are unaffected: this
# only ever gates `yes_no_field_shape`, which is the weakest of the sources.
_YES_NO_SHAPE_BLOCKERS = frozenset({
    "amount", "limit", "limits", "value", "values", "premium", "cost", "costs",
    "payroll", "revenue", "sales", "deductible", "deductibles", "sir",
    "count", "number", "num", "employees", "vehicles", "locations", "years",
    "year", "date", "dates", "code", "codes", "rate", "rates", "percent",
    "pct", "phone", "email", "address", "name", "naic", "fein", "id",
})

# Probes for the FACT_REGISTRY validator. A field is Yes/No when its own
# declared validator accepts both booleans and rejects every other shape a
# fact can hold - a BEHAVIOURAL test, so it needs no source parsing and cannot
# drift from what the validator actually does.
_YN_PROBE_ACCEPT = ("Yes", "No")
_YN_PROBE_REJECT = ("$1,000,000", "Acme Contracting LLC", "12/31/2026",
                    "84-2210987", "4800 Dahlia St Denver CO 80216", "238160")

_YES_NO_FIELD_CACHE: Dict[str, bool] = {}
_BOOLEAN_SCHEMA_KEYS: Optional[FrozenSet[str]] = None


def _boolean_schema_keys() -> FrozenSet[str]:
    """Fact keys LLM call 1's own schema declares as ``boolean``.

    Lazy + cached + fail-open: ``extraction_service`` imports this module, so
    the edge only ever exists at call time. Same pattern ``fact_equivalence``
    already uses to read ``FACT_REGISTRY``.
    """
    global _BOOLEAN_SCHEMA_KEYS
    if _BOOLEAN_SCHEMA_KEYS is None:
        try:
            from services.extraction_service import BOOLEAN_FACT_KEYS
            _BOOLEAN_SCHEMA_KEYS = frozenset(BOOLEAN_FACT_KEYS)
        except Exception:                                    # pragma: no cover
            return frozenset()
    return _BOOLEAN_SCHEMA_KEYS


def _registry_declares_yes_no(field: str) -> bool:
    try:
        from services.fact_registry import FACT_REGISTRY
        entry = FACT_REGISTRY.get(field) or {}
    except Exception:                                        # pragma: no cover
        return False
    hint = str(entry.get("format_hint") or "").strip().lower()
    if hint.startswith("yes or no") or hint in ("yes/no", "y/n"):
        return True
    validate = entry.get("validate")
    if not callable(validate):
        return False
    try:
        if not all(bool(validate(p)) for p in _YN_PROBE_ACCEPT):
            return False
        if any(bool(validate(p)) for p in _YN_PROBE_REJECT):
            return False
    except Exception:
        return False
    return True


def declares_yes_no(field: str) -> bool:
    """AUTHORITATIVE: this fact is declared Yes/No somewhere it already was."""
    f = (field or "").strip()
    if not f:
        return False
    return (f in YES_NO_FIELDS
            or f in _boolean_schema_keys()
            or _registry_declares_yes_no(f))


def yes_no_field_shape(field: str) -> bool:
    """A GUESS from the key's own shape - weaker than ``declares_yes_no``."""
    f = (field or "").strip().lower()
    if not f:
        return False
    toks = set(re.split(r"[^a-z0-9]+", f))
    if toks & _YES_NO_SHAPE_BLOCKERS:
        return False
    if toks & _YES_NO_SHAPE_TOKENS:
        return True
    return f.startswith(_YES_NO_SHAPE_PREFIXES) or f.endswith(_YES_NO_SHAPE_SUFFIXES)


def is_yes_no_field(field: str) -> bool:
    """True when this fact holds a Yes/No answer. Declared first, shape second.

    Cached: called inside grouping loops by both the merge and the comparator.
    """
    f = (field or "").strip()
    if not f:
        return False
    hit = _YES_NO_FIELD_CACHE.get(f)
    if hit is None:
        hit = declares_yes_no(f) or yes_no_field_shape(f)
        _YES_NO_FIELD_CACHE[f] = hit
    return hit


# ── A RATING BUREAU IS NEVER THE CARRIER (2026-09-05) ────────────────────────
# The client's own SYS-07 screenshot offers three carriers to choose between:
# EMPLOYERS MUTUAL CASUALTY COMPANY / **AAIS** / EMC Property & Casualty
# Company. AAIS is the American Association of Insurance Services - an advisory
# and rating BUREAU. Its name is printed on the policy because it wrote the
# coverage FORMS ("AAIS Form CL-100"), never because it wrote the policy.
#
# Measured before the fix: `compare("carrier_name", [EMC..., "AAIS"])` returned
# a conflict, `normalize_carrier("AAIS")` returned a carrier family token, and a
# grep of the whole backend found AAIS mentioned ONLY inside the ISO/AAIS
# FORM-NUMBER convention. Nothing anywhere said a bureau is not an insurer. A
# producer who picked it would have stamped "AAIS" as the carrier on a signed
# ACORD form.
#
# This is a DECLARATION, not a heuristic - the same kind of curated table as
# `_STRICT_TOKEN_CANON` - because there is no derivable signal that separates
# "American Association of Insurance Services" from a real insurer's name.
# It is deliberately tiny and holds only bodies that publish forms, rates or
# standards and write no insurance at all.
_INSURANCE_BUREAUS: FrozenSet[str] = frozenset({
    "aais",                                  # American Association of Ins. Services
    "american association of insurance services",
    "iso", "insurance services office", "iso properties", "verisk",
    "ncci", "national council on compensation insurance",
    "naic", "national association of insurance commissioners",
    "acord",                                 # publishes the forms themselves
    "aaisonline",
    "wcirb", "wcribma", "ncrb", "ncci holdings",
    "surplus lines association", "aaisdirect",
})


# ── A ROLE LABEL IS NOT A NAME (2026-09-05) ──────────────────────────────────
# Live 5 Sep 2026: all three generated forms carried an ADDITIONAL INTEREST
# whose NAME was the words "Certificate Holder". The certificate's remarks say
# *"Certificate holder is an additional insured with respect to general
# liability where required by written contract"* - a sentence about the ROLE,
# naming nobody - and the extractor returned the label as the value.
#
# The orphan-row rule already suppresses an UNNAMED interest row. This row had
# a name, so it survived; the name was just not a name. These are ACORD's own
# party-role words, and no company is called one of them.
_PARTY_ROLE_LABELS: FrozenSet[str] = frozenset({
    "certificate holder", "certificate holders", "cert holder",
    "additional insured", "additional insureds", "additional interest",
    "named insured", "first named insured", "other named insured",
    "loss payee", "lender", "lenders loss payable", "lienholder",
    "mortgagee", "mortgage holder", "trustee", "registrant", "owner",
    "employee as lessor", "breach of warranty", "co owner", "co-owner",
    "insured", "applicant", "producer", "agency", "carrier", "insurer",
    "as their interests may appear", "atima", "various", "as required",
    "as per written contract", "where required by written contract",
    "to whom it may concern", "n a", "same as above", "see attached",
    # The lease-side roles a certificate prints in place of a name (14 Sep 2026).
    "landlord", "lessor", "lessee", "tenant", "building owner", "property owner",
})


# A HEADING IS NOT A NAME (8 Oct 2026, Choice Electric b38a4367). A redacted
# Travelers dec prints "INSURED'S NAME:" with nothing after it; the next thing on
# the page is the billing table's column headings ("ACCT. EFF. PREMIUM" /
# "S.B. MO. DATE"), and the model returned "S.B. MO." as the insured. That one
# reading raised a "Possible multiple submissions" hard stop over six documents
# of one insured AND won the merge as the package's applicant name.
# Structural, no word list: a name made ENTIRELY of dotted abbreviations
# ("S.B.", "MO.", "ACCT.") is a table heading or a key, never a party - a real
# insured has a word of its own ("J. Smith", "U.S. Steel", "St. Louis Electric").
# A legal-form designator ("A.B. Co.", "U.S. Inc.") keeps it a name.
_ABBREVIATION_TOKEN_RE = re.compile(r"^(?:[A-Za-z]{1,5}\.)+$")
_HEADING_LEGAL_FORMS = frozenset({
    "co", "inc", "llc", "lc", "pllc", "llp", "lp", "ltd", "corp", "pc", "pa", "plc", "na",
})
# The fact keys that name THE INSURED - the ones the integrity check, the
# merge's applicant vote and `insured_scope` read.
INSURED_NAME_KEYS = ("applicant_name", "named_insured", "insured_name", "loss_run_insured_name")


def is_abbreviation_heading(value: Any) -> bool:
    """True when every word of `value` is a dotted abbreviation and none is a
    legal-form designator: "S.B. MO.", "ACCT. EFF." - never "J. Smith"."""
    toks = [t.strip(",;:") for t in str(value or "").split()]
    toks = [t for t in toks if t]
    if not toks:
        return False
    if any(t.replace(".", "").lower() in _HEADING_LEGAL_FORMS for t in toks):
        return False
    return all(_ABBREVIATION_TOKEN_RE.match(t) for t in toks)


# ── A PERSON IN A ROLE IS NOT THE INSURED (21 Oct 2026) ──────────────────────
# Brent's Choice Electric test of 17 Oct (session ecab28dd, 25sepChanges.md Z29
# item 4): a handwritten narrative reads "I met with Eric / Berger owner of
# Choice Electric", and extraction took "Berger Owner of Choice Electric" as the
# narrative's applicant name. `same_entity_name` rightly says that is not CHOICE
# ELECTRIC LLC, so a Data Consistency name conflict - "documents name different
# companies", a hard stop (60) - came out of a sentence naming a PERSON and the
# job he holds AT the insured. Same family as a role label ("Certificate
# Holder") and a column heading ("S.B. MO."): a value in an insured-name fact
# that is not the insured.
#
# STRUCTURAL - the WHOLE value must read
#     [title] <person, 1-4 words> <job title> of | at | for <organisation>
# * the job title holds a ROLE word, singular ("owner", "managing member",
#   "chief executive officer"); a plural names a GROUP ("Partners of Michigan
#   Inc", "The Members of X Association");
# * at least one PERSON word stands in front of it - no article or function
#   word, no business or legal-form word (this module's own company vocabulary,
#   `_glue_words`), no other role word: "Owner Operator Trucking LLC",
#   "President Homes LLC", "Principal Financial Group" and "Director Supply Co"
#   carry none (and no "of / at / for" after the role either), and a job title
#   with nobody in front ("Property Manager of Detroit LLC") stays a name;
# * a fiduciary capacity is NOT a role here: "John Smith, Trustee of the Smith
#   Family Trust" and "Jane Doe, Executor of the Estate of John Doe" are how a
#   trust or an estate IS named on a policy; nor is a profession ("Attorney at
#   Law").
# Never a reading of prose: a sentence fails the person part at its first
# non-name word ("Choice Electric LLC is owned by ...", "I met with ...").
_PERSON_ROLE_WORDS: FrozenSet[str] = frozenset({
    "owner", "coowner", "proprietor", "president", "vp", "ceo", "cfo", "coo", "cto",
    "cio", "founder", "cofounder", "manager", "member", "partner", "principal",
    "director", "officer", "agent", "employee", "operator", "chairman", "chairwoman",
    "chairperson", "secretary", "treasurer", "superintendent", "foreman", "supervisor",
    "executive", "representative", "controller", "comptroller", "shareholder",
    "stockholder", "estimator", "bookkeeper",
})
# Words that qualify a role inside a job title - "VICE president", "MANAGING
# member", "CHIEF financial officer", "OFFICE manager", "CO-owner".
_PERSON_ROLE_MODIFIERS: FrozenSet[str] = frozenset({
    "co", "vice", "managing", "general", "assistant", "associate", "senior", "junior",
    "chief", "deputy", "acting", "interim", "regional", "district", "area", "branch",
    "store", "office", "project", "property", "operations", "operating", "sales",
    "account", "plant", "safety", "risk", "finance", "financial", "technology",
    "information", "marketing", "human", "resources", "sole", "majority", "minority",
    "founding", "lead", "business", "home", "corporate",
})
_PERSON_ROLE_CONNECTORS = frozenset({"and", "&"})
_PERSON_ROLE_PREPOSITIONS = frozenset({"of", "at", "for"})
_PERSON_TITLES = frozenset({"mr", "mrs", "ms", "miss", "mx", "dr", "sir"})
# Words no person's name is made of: articles, pronouns, connectors, the verbs a
# note puts in front of a name, and the party / role nouns of a policy.
_NOT_A_PERSON_WORDS = frozenset({
    "the", "a", "an", "and", "or", "of", "at", "for", "to", "by", "with", "from", "in",
    "on", "as", "per", "via", "is", "was", "are", "were", "be", "been", "i", "we", "you",
    "he", "she", "they", "it", "me", "us", "him", "her", "them", "my", "our", "your",
    "his", "their", "its", "this", "that", "these", "those", "met", "spoke", "talked",
    "contact", "attn", "attention", "named", "insured", "applicant", "producer",
    "carrier", "insurer", "certificate", "holder", "additional", "interest", "landlord",
    "lessor", "lessee", "tenant", "mortgagee", "owned", "operated", "aka", "fka", "nka",
})
_PERSON_ROLE_SPLIT_RE = re.compile(r"[\s,;:()\[\]{}/\\|\"\u2013\u2014-]+")
_PERSON_WORD_RE = re.compile(r"[a-z][a-z']*[a-z]")
_PERSON_ROLE_MAX_TOKENS = 16


# The organisation a person serves can END in a legal-form or body designator.
# Then the value may just as well be a company NAMED that way ("Lord Agent of
# Change LLC", "Hope Agent of Mercy Foundation") - review of 21 Oct 2026 - so it
# reads as a person only when punctuation sets the person apart from the title
# ("Eric Berger, Managing Member of Choice Electric LLC").
_ORG_DESIGNATORS = frozenset({
    "llc", "inc", "co", "corp", "corporation", "company", "companies", "ltd", "limited",
    "lp", "llp", "pc", "pllc", "plc", "pa", "na", "incorporated", "foundation", "church",
    "association", "trust", "society", "institute", "ministries", "fund",
})
_ORG_FILLER = frozenset({"the", "a", "an", "of", "and", "&"})
_PERSON_TITLE_BREAK_RE = re.compile(r"[,;:()\u2013\u2014-]")


def _person_role_tokens(value: str, with_breaks: bool = False):
    """The value's words, lower case. `with_breaks`: also, per word, whether
    punctuation (a comma, a dash, a bracket) stands right before it."""
    toks: List[str] = []
    breaks: List[bool] = []
    text = value.replace("&", " & ").lower()
    pos, pending = 0, False
    for m in re.finditer(r"[^\s,;:()\[\]{}/\\|\"\u2013\u2014-]+", text):
        pending = pending or bool(_PERSON_TITLE_BREAK_RE.search(text[pos:m.start()]))
        pos = m.end()
        tok = m.group(0).strip("'`")
        if not re.fullmatch(r"[a-z]\.", tok):          # an initial keeps its dot ("j.")
            tok = tok.strip(".")
        if tok:
            toks.append(tok)
            breaks.append(pending)
            pending = False
    return (toks, breaks) if with_breaks else toks


def _is_person_word(tok: str) -> bool:
    """A word a person's name can be made of - an initial ("J.", "J") or a word
    that is no function word, business / legal-form word or role word."""
    if re.fullmatch(r"[a-z]\.?", tok):
        return tok.endswith(".") or tok not in ("a", "i")
    if not _PERSON_WORD_RE.fullmatch(tok):
        return False
    return (tok not in _NOT_A_PERSON_WORDS and tok not in _glue_words()[0]
            and tok not in _PERSON_ROLE_WORDS and tok not in _PERSON_ROLE_MODIFIERS)


def is_person_in_a_role(value: Any) -> bool:
    """True when `value` names a PERSON in his job at an organisation -
    "Berger Owner of Choice Electric", "Eric Berger, Managing Member of Choice
    Electric LLC" - never a company named after a role ("Owner Operator Trucking
    LLC", "Partners of Michigan Inc"). See the note above."""
    if not isinstance(value, str) or not value.strip():
        return False
    toks, breaks = _person_role_tokens(value, with_breaks=True)
    if not toks or len(toks) > _PERSON_ROLE_MAX_TOKENS:
        return False
    i = 0
    while i < len(toks) and toks[i] in _PERSON_TITLES:
        i += 1
    start = i
    role_or_modifier = _PERSON_ROLE_WORDS | _PERSON_ROLE_MODIFIERS
    while i < len(toks) and toks[i] not in role_or_modifier:
        if not _is_person_word(toks[i]):
            return False
        i += 1
    if not 1 <= i - start <= 4:
        return False
    j = i
    while j < len(toks) and (toks[j] in role_or_modifier or toks[j] in _PERSON_ROLE_CONNECTORS):
        j += 1
    title = toks[i:j]
    if not title or title[0] in _PERSON_ROLE_CONNECTORS or title[-1] in _PERSON_ROLE_CONNECTORS:
        return False
    if not any(t in _PERSON_ROLE_WORDS for t in title):
        return False
    if j >= len(toks) or toks[j] not in _PERSON_ROLE_PREPOSITIONS:
        return False
    org = [t for t in toks[j + 1:] if re.search(r"[a-z0-9]", t) and t not in _ORG_FILLER]
    if not org:
        return False
    if breaks[i]:
        return True                    # "Eric Berger, Owner of ..." - set apart
    # Run together ("Berger Owner of Choice Electric") the value must read as a
    # person: the organisation names no legal form or body of its own ("Lord
    # Agent of Change LLC" is a company) and is more than one word ("Michigan
    # Secretary of State", "Liberty Agent for Change" are names).
    return org[-1] not in _ORG_DESIGNATORS and len(org) >= 2


def is_not_a_party_name(value: Any) -> bool:
    """True when a value in an insured-name fact names no insured: a party ROLE
    ("Certificate Holder"), a column heading ("S.B. MO."), a PERSON IN A ROLE
    ("Berger Owner of Choice Electric", 21 Oct 2026) or a PLACEHOLDER ("FIO",
    "TBD", "Sample", "N/A", 22 Oct 2026 - `is_party_placeholder`). The one
    insured-name door: the per-document drop, the merge vote and its floor, the
    identity checks, Submission Integrity, `insured_scope` and the Documents
    list all ask it."""
    return (is_party_role_label(value) or is_abbreviation_heading(value)
            or is_person_in_a_role(value) or is_party_placeholder(value))


# ── A PLACEHOLDER IS NOT A PARTY (22 Oct 2026, Orbin "Not done") ────────────
# What a document prints in a party's PLACE when it names nobody, beside the
# role words of `_PARTY_ROLE_LABELS`: a certificate's informational disclaimer
# and its initialism (the Orbin COI's holder was "FIO" - an initialism reads
# exactly like "3M", "EMC" or "CRS", so the shape test `names_a_party` passed
# it), a deferral ("to be determined", "TBA") and a specimen marker ("Sample",
# "Void"). Plus everything that carries no information at all - the one door
# for that, `answer_semantics.is_placeholder_text` ("N/A", "unknown", "--").
#
# WHOLE VALUES ONLY, like the role words: "Various Builders LLC", "Sample
# Electric Inc", "Void Studios LLC", "FIO Holdings LLC" and "TBA Electric" are
# names. A spaced or dotted initialism ("F.I.O.", "F I O") is the same word.
# Kept apart from `is_party_role_label` on purpose: Guard 3c reads that one on
# every gap-filled box and reports "a party ROLE".
_PARTY_PLACEHOLDERS: FrozenSet[str] = frozenset({
    "for informational purposes only", "for information purposes only",
    "for informational purpose only", "for informational purposes",
    "for information purposes", "for information only", "for info only",
    "informational purposes only", "information purposes only",
    "informational only", "information only", "fio", "fipo",
    "to be determined", "to be announced", "to be advised", "to be confirmed",
    "to be named", "to be provided", "tbd", "tba", "tbc", "tbn",
    "sample", "specimen", "void", "voided", "sample only", "specimen only",
    # A BACK-REFERENCE holds the place too (27 Oct 2026, Lane B item 3): a person
    # answering a name question with "Same as above" / "See above" names nobody
    # - the box it points at is not on this form, nor in the facts. Whole values
    # only, like the rest ("Same Day Delivery LLC" is a name).
    "see above", "as above", "same as above", "see below", "as below",
    "same as below", "ditto", "same", "same as applicant", "same as the applicant",
    "same as insured", "same as the insured", "same as named insured",
    "same as the named insured",
})


def is_party_name_fact(field: Any) -> bool:
    """Does this FACT hold the name of a party - a person or an organisation?

    The one answer to "is this a name question?", read off the fact key's own
    shape exactly as `_infer_field_category` reads it for normalisation (the
    explicit NAME / CARRIER sets, any "..._name" key, the curated holder key)
    - but NOT its loose "carrier anywhere in the key" branch, which also
    catches a carrier's WEBSITE, narrative and market (`carrier_website`,
    `qn_carrier_narrative`, `carrier_market`, `has_motor_carrier_coverage`).
    A carrier fact is a name here only when the key ENDS naming the party
    (`prior_carrier`, `wc_prior_carrier`, `..._insurer`). Used by the person-
    answer door (`answer_semantics.interpret_answer`) and the editor write-back,
    so a non-answer or a back-reference never becomes a party's name."""
    f = str(field or "").strip().lower()
    if not f:
        return False
    if f in NAME_FIELDS or f in CARRIER_FIELDS or f in _NAME_LIKE_KEYS:
        return True
    return f.endswith("_name") or f.endswith("_carrier") or f.endswith("_insurer")


def is_placeholder_fein(value: Any) -> bool:
    """True when a tax ID's nine digits are one digit repeated - "00-0000000",
    "000000000", "11-1111111", "99-9999999". The IRS never issues one; a form
    or a person types it to hold the place of a number they do not have (strict
    review, 29 Oct 2026: an all-zero FEIN filled Tier 2 and printed on every
    form). ONE rule for the answer door (`fact_registry._is_fein`,
    `validators.validate_fein`) and the extraction merge
    (`answer_semantics.extracted_non_answer`). Deliberately NOT "123456789":
    no IRS rule makes it impossible, and the review plan's sample answer is
    "12-3456789". Anything that is not nine digits is not judged here."""
    if value is None or isinstance(value, bool):
        return False
    digits = re.sub(r"[\s\-]", "", str(value))
    return len(digits) == 9 and digits.isdigit() and len(set(digits)) == 1


def is_party_placeholder(value: Any) -> bool:
    """True when the WHOLE value holds a party's place without naming one -
    "FIO", "For Informational Purposes Only", "TBD", "Sample", "Void", or a
    value that carries no information ("N/A", "Unknown", "--"). Never true of a
    name that merely contains such a word. See the note above."""
    if not isinstance(value, str) or not value.strip():
        return False
    s = re.sub(r"[^a-z0-9 ]+", " ", value.strip().lower())
    s = re.sub(r"\s+", " ", s).strip()
    if s in _PARTY_PLACEHOLDERS:
        return True
    toks = s.split()
    if len(toks) > 1 and all(len(t) == 1 for t in toks) \
            and "".join(toks) in _PARTY_PLACEHOLDERS:
        return True                          # "F.I.O." / "F I O" = "FIO"
    try:
        from services.answer_semantics import is_placeholder_text
        return bool(is_placeholder_text(value))
    except Exception:                                        # noqa: BLE001
        return False


# ── A VEHICLE'S USE / RADIUS IS NOT WHAT THE BUSINESS DOES (13 Oct 2026) ──────
# The owner's run 18f6914f: `operations_description` = "LOCAL SERVICE" - the
# Business Auto Policy's vehicle schedule prints it in every row's "Radius of
# Operation / Use" column (the same document's `auto_vehicle_use` = "service"),
# and extraction read it as the business description, which then stood as "in
# place" on the review screen and would print as the ACORD 125's description of
# operations.
#
# VOCABULARY IS NECESSARY, NOT SUFFICIENT (review, same night): "LONG DISTANCE
# HAULING", "Local retail business" and "Local farm" are real descriptions made
# of the same words. So the ruling needs a STRUCTURAL second condition: the
# description restates the vehicle use the SAME evidence states
# (`auto_vehicle_use`), and a person's own or confirmed words always stand.
_VEHICLE_USE_ONLY_WORDS = frozenset({
    "local", "intermediate", "long", "distance", "radius", "commute", "commuting", "zone",
})
_VEHICLE_USE_WORDS = _VEHICLE_USE_ONLY_WORDS | frozenset({
    "service", "commercial", "retail", "business", "personal", "pleasure", "farm",
    "use", "miles", "mile", "mi", "of", "to", "and",
})


def is_vehicle_use_label(value: Any) -> bool:
    """True when `value` is made only of vehicle use / radius words with at
    least one word that exists only there ("LOCAL SERVICE", "Intermediate")."""
    words = re.findall(r"[a-z]+", str(value or "").lower())
    if not words or len(words) > 5:
        return False
    return (all(w in _VEHICLE_USE_WORDS for w in words)
            and any(w in _VEHICLE_USE_ONLY_WORDS for w in words))


def description_restates_vehicle_use(description: Any, vehicle_use: Any) -> bool:
    """A business description that only restates the vehicle use class the
    same evidence states: a vehicle-use label carrying every word of
    `vehicle_use` ("LOCAL SERVICE" over use "service")."""
    if not is_vehicle_use_label(description):
        return False
    use_words = set(re.findall(r"[a-z]+", str(vehicle_use or "").lower())) - {"of", "to", "and", "use"}
    desc_words = set(re.findall(r"[a-z]+", str(description or "").lower()))
    return bool(use_words) and use_words <= desc_words


# Z37 (W2, 24 Oct 2026): "Business auto coverage for a fleet of vehicles garaged
# in Denver, Colorado." printed as the business description on ACORD 125 / 130 /
# both 131s - the model's summary of the AUTO POLICY. Talk of coverage, a policy
# or where autos are garaged describes the insurance, not the business. Two
# conditions, both required: that vocabulary AND words the documents do not
# print (a printed description always stands). One reading for the merge's
# per-document pass and the AI fill's guard.
# Strong talk names the insurance itself; one weak word ("policies", "garaged",
# a bare "coverage") is also ordinary business wording - an insurance agency
# "selling commercial policies", a trucker's "tractors garaged at the Denver
# terminal", a guard firm's "24/7 coverage" - so it takes two of them.
_COVERAGE_TALK_RE = re.compile(
    r"\b(?:covered\s+autos?|declarations|endorsements?|insured\s+under|"
    r"(?:auto(?:mobile)?|liability|property|umbrella|excess|physical\s+damage|"
    r"compensation|hired|non-?owned)\s+coverages?)\b", re.I)
_COVERAGE_TALK_WEAK_RE = re.compile(r"\b(coverages?|polic(?:y|ies)|garaged)\b", re.I)


def _folded_words(text: Any) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(text or "").lower()))


def describes_insurance_not_business(value: Any, document_text: Any) -> bool:
    """True when `value`, offered as what the business does, talks about the
    insurance (coverage / policy / garaging) in words `document_text` does not
    print. False for an empty value or no text to judge against."""
    text = str(value or "").strip()
    if not text or not str(document_text or "").strip():
        return False
    weak = {re.sub(r"(?:ies|s)$", "", w.lower()) for w in _COVERAGE_TALK_WEAK_RE.findall(text)}
    if not _COVERAGE_TALK_RE.search(text) and len(weak) < 2:
        return False
    words = _folded_words(text)
    return bool(words) and words not in _folded_words(document_text)


def vehicle_use_as_operations(facts: Any) -> bool:
    """The ONE ruling (scorer, stamper, fix-window pre-fill, questionnaire):
    the package's operations description is its vehicles' use class and no
    person stated or confirmed it - so it is not an answer. Who stated or
    confirmed it is the one door's call, `fact_state.confirmed_by_person`
    (21 Oct 2026, review L1)."""
    if not isinstance(facts, dict):
        return False
    raw = facts.get("operations_description")
    env = raw if isinstance(raw, dict) else {}
    from services.fact_state import confirmed_by_person
    if confirmed_by_person(raw):
        return False
    use = facts.get("auto_vehicle_use")
    use = use.get("value") if isinstance(use, dict) else use
    return description_restates_vehicle_use(env.get("value") if env else raw, use)


def is_party_role_label(value: Any) -> bool:
    """True when this "name" is an ACORD party ROLE rather than a party.

    A generic role word is what a document prints when it is describing the
    arrangement instead of naming anybody, so on a name field it carries no
    signal at all.
    """
    s = str(value or "").strip().lower()
    if not s:
        return False
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s in _PARTY_ROLE_LABELS


# ── WHAT THE BUSINESS IS: ONE CLASSIFICATION DOOR (2026-09-05) ───────────────
# NAICS sector -> the kind of business it names. An official published taxonomy,
# not a keyword list. Deliberately PARTIAL: sectors whose reading is genuinely
# arguable (54 Professional Services is "office" or "service" depending on who
# you ask; 53 Real Estate is not "apartments") are absent, and absent means the
# caller falls back to whatever weaker signal it has.
#
# Lives here rather than in `pdf_service` because TWO consumers now need it and
# they must not each keep a copy: the ACORD 125 NATURE OF BUSINESS boxes, and
# `cross_form_validator`'s crime-exposure advisory - which was reading the same
# narrative with the same bare substring test and firing "the business mentions
# 'retail'" at a food wholesaler.
_NAICS_SECTOR_TO_BUSINESS_TYPE: Dict[str, str] = {
    "31": "Manufacturing", "32": "Manufacturing", "33": "Manufacturing",
    "42": "Wholesale",
    "44": "Retail", "45": "Retail",
    "61": "Institutional", "62": "Institutional",
    "23": "Contractor",
}
_NAICS_SUBSECTOR_TO_BUSINESS_TYPE: Dict[str, str] = {
    "722": "Restaurant",          # Food Services and Drinking Places
    "52": "Financial",            # Finance and Insurance
}


def naics_business_type(naics_code: Any) -> Optional[str]:
    """The kind of business this NAICS code names, or None if it cannot say."""
    raw = re.sub(r"\D", "", str(naics_code or ""))
    if len(raw) < 2:
        return None
    return (_NAICS_SUBSECTOR_TO_BUSINESS_TYPE.get(raw[:3])
            or _NAICS_SUBSECTOR_TO_BUSINESS_TYPE.get(raw[:2])
            or _NAICS_SECTOR_TO_BUSINESS_TYPE.get(raw[:2]))


def is_insurance_bureau(value: Any) -> bool:
    """True when this name is a rating / advisory bureau rather than an insurer.

    A bureau's name reaches a carrier fact because it is printed on the policy
    as the author of the coverage FORMS. It is never the party on the risk, so
    on a carrier field it is not a value at all.
    """
    s = str(value or "").strip().lower()
    if not s:
        return False
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if s in _INSURANCE_BUREAUS:
        return True
    # "AAIS Form CL-100", "ISO Commercial Lines" - the bureau named as the
    # AUTHOR of something. Only ever the LEADING token, so "Verisk Insurance
    # Company" (were one to exist) is untouched by a trailing match.
    head = s.split(" ")[0]
    if head in _INSURANCE_BUREAUS and len(s.split()) <= 4:
        return True
    return False


def _infer_field_category(field: str) -> Optional[str]:
    """Infer a normalization category from the SHAPE of a fact key.

    The explicit *_FIELDS sets are the authoritative overrides; this is the
    fallback so any SECONDARY or NEW key carrying a known data type still gets
    type-correct normalization instead of silently dropping to the generic text
    normalizer (Beta Report §5: normalization must be generic for any document,
    not only the canonical identity fields). Returns one of
    {"date", "address", "carrier", "name"} or None.
    """
    if not field:
        return None
    f = field.lower()
    # Date: any "..._date" key (effective / expiration / retro / completion / ...).
    if f.endswith("_date"):
        return "date"
    # Address: any "..._address" / "..._addresses" key.
    if f.endswith("_address") or f.endswith("_addresses"):
        return "address"
    # Carrier: any key naming a carrier/insurer - but NOT a NAIC code, a coverage
    # "type", or a generic "_code" (those are not carrier NAMES).
    if ("carrier" in f or "insurer" in f) and "naic" not in f \
            and not f.endswith("_type") and not f.endswith("_code"):
        return "carrier"
    # Organization name: any "..._name" key, plus curated holder/payee keys.
    if f.endswith("_name") or f in _NAME_LIKE_KEYS:
        return "name"
    return None


def is_carrier_field(field: str) -> bool:
    """True when ``field`` names a carrier/insurer.

    Mirrors the carrier dispatch in normalize_value (explicit set OR inferred
    shape) so the cross-document detector labels carrier differences - including
    secondary keys like wc_prior_carrier - as a REVIEW item rather than a
    definitive conflict (Beta Report §5.2).
    """
    return field in CARRIER_FIELDS or _infer_field_category(field) == "carrier"


# ── Entity suffixes / synonyms ────────────────────────────────────────────────

# Trailing entity-type suffixes stripped from organization NAMES so the name
# identity ("orbin contracting") is compared without the legal suffix.
_ENTITY_SUFFIXES = (
    "limited liability company", "limited liability partnership",
    "limited partnership", "incorporated", "corporation", "company", "limited",
    "llc", "inc", "corp", "co", "ltd", "llp", "lp", "pllc", "pc", "pa", "dba",
)

# Entity-type SYNONYMS (Beta Report §5.2). Each variant maps to a canonical
# token so "LLC" and "Limited Liability Company" compare equal. Sorted longest
# phrase first at module load so multi-word phrases are matched before the
# single words they contain.
_ENTITY_TYPE_SYNONYMS = {
    "limited liability company": "llc",
    # ── V1 H4 (client section 9), 2026-08-27 ────────────────────────────────
    # Section 9.1's Entity Type key rule is *"Normalize equivalent legal
    # formats"*, and it was failing on ACORD'S OWN WORDING. Measured before
    # this line existed:
    #     values_conflict("entity_type", ["LLC", "Limited Liability Corporation"])
    #         -> True
    # because the full phrase was not a key here, so the longest-first pass
    # matched the bare words instead: "limited" -> "ltd" and "corporation" ->
    # "corp", giving "ltd liability corp". ACORD 125's own checkbox is labelled
    # "Limited Liability Corporation", so the single most likely spelling on a
    # real form raised a false Data Consistency conflict against "LLC" - and
    # `entity_type` IS a reconcilable field, so that reached a producer as a
    # review item on two values that are the same company.
    # It also mis-classified the FORM: `entity_family` reads this function's
    # output, so "Limited Liability Corporation" came back `corporation` and
    # would have ticked the Corporation box for an LLC.
    # Four more equivalences on the same footing, each measured as a live false
    # conflict: Sole Proprietor / Sole Proprietorship, Nonprofit / Non-Profit /
    # Not For Profit, Corporation / Incorporated, Partnership / General
    # Partnership.
    # DELIBERATELY NOT FOLDED, because they are genuinely different entities and
    # principle 4 says a real disagreement stays visible: Limited Partnership
    # and Limited Liability Partnership keep their own tokens (an LP is not a
    # GP), S Corporation keeps its own (its own ACORD box, and a different tax
    # election), and Municipality / Government Entity are left to the producer
    # rather than folded on our own authority (principle 7).
    "limited liability corporation": "llc",
    "limited liability co": "llc",
    "sole proprietorship": "sole prop",
    "sole proprietor": "sole prop",
    "not for profit": "nonprofit",
    "non profit": "nonprofit",
    "nonprofit": "nonprofit",
    "general partnership": "partnership",
    "llc": "llc",
    "professional limited liability company": "pllc",
    "pllc": "pllc",
    "limited liability partnership": "llp",
    "llp": "llp",
    "limited partnership": "lp",
    "lp": "lp",
    # "Acme Inc" and "Acme Corporation" are the same LEGAL ENTITY TYPE, and
    # ACORD prints one Corporation box for both. Folded 2026-08-27 (V1 H4);
    # safe because this table is read by `normalize_entity_type` alone, which
    # is dispatched only for entity_type values - company NAME comparison uses
    # `normalize_name` / `strict_entity_key` and is untouched.
    "incorporated": "corp",
    "inc": "corp",
    "corporation": "corp",
    "corp": "corp",
    "professional corporation": "pc",
    "company": "co",
    "co": "co",
    "limited": "ltd",
    "ltd": "ltd",
}

# Insurance-terminology SYNONYMS (Beta Report §5.2). Variant -> canonical token.
#
# NOTE: "BI = Building" is included per §5.2 client decision (Option C accepted).
# "BI" is ambiguous in commercial insurance (Bodily Injury / Business Interruption
# / Building) but the client accepted global mapping as the report specifies.
_INSURANCE_SYNONYMS = {
    "combined single limit": "csl",
    "csl": "csl",
    "commercial general liability": "cgl",
    "cgl": "cgl",
    "general liability": "gl",
    "gl": "gl",
    "workers compensation": "wc",
    "workers comp": "wc",
    "workmans compensation": "wc",
    "workman s compensation": "wc",
    "wc": "wc",
    "business personal property": "bpp",
    "bpp": "bpp",
    "total insured value": "tiv",
    "tiv": "tiv",
    "employment practices liability insurance": "epli",
    "employment practices liability": "epli",
    "epli": "epli",
    "hired and non owned auto": "hnoa",
    "hired non owned auto": "hnoa",
    "hired and nonowned auto": "hnoa",
    "hnoa": "hnoa",
    "construction occupancy protection exposure": "cope",
    "cope": "cope",
}

# Build a single longest-first replacement table for the general normalizer so
# "commercial general liability" is consumed before "general liability".
_GENERAL_SYNONYMS = dict(_INSURANCE_SYNONYMS)
_GENERAL_SYNONYMS_SORTED = sorted(
    _GENERAL_SYNONYMS.items(), key=lambda kv: len(kv[0]), reverse=True
)
_ENTITY_TYPE_SYNONYMS_SORTED = sorted(
    _ENTITY_TYPE_SYNONYMS.items(), key=lambda kv: len(kv[0]), reverse=True
)


# ── Address terms (Beta Report §5.2) ──────────────────────────────────────────

# Street-suffix words -> USPS-style abbreviation (full word and abbrev compare
# equal).  Keyed by full word; the abbreviation is the canonical token.
_STREET_SUFFIXES = {
    "street": "st", "st": "st",
    "avenue": "ave", "ave": "ave", "av": "ave",
    "road": "rd", "rd": "rd",
    "drive": "dr", "dr": "dr",
    "boulevard": "blvd", "blvd": "blvd",
    "lane": "ln", "ln": "ln",
    "court": "ct", "ct": "ct",
    "place": "pl", "pl": "pl",
    "circle": "cir", "cir": "cir",
    "terrace": "ter", "ter": "ter",
    "parkway": "pkwy", "pkwy": "pkwy",
    "highway": "hwy", "hwy": "hwy",
    "square": "sq", "sq": "sq",
    "trail": "trl", "trl": "trl",
    "way": "way",
}

# Unit / secondary-designator markers dropped entirely so "#D13", "Unit D13",
# "Ste D13" and "D13" all collapse to "d13" (Beta Report §5.2: Suite = Ste,
# Unit = Unit or #, #D13 = D13).
_UNIT_MARKERS = frozenset({
    "suite", "ste", "unit", "apt", "apartment", "no", "number", "rm", "room",
    "fl", "floor", "bldg",
})

# Compass directionals collapsed to their abbreviation so "North Main" and
# "N Main" compare equal. Directionals were not enumerated in §5.2 but follow the
# same suffix-abbreviation intent. DISTINCT directions stay distinct (n != s), so
# this only suppresses formatting noise - it never merges two different addresses.
_DIRECTIONALS = {
    "north": "n", "n": "n",
    "south": "s", "s": "s",
    "east": "e", "e": "e",
    "west": "w", "w": "w",
    "northeast": "ne", "ne": "ne",
    "northwest": "nw", "nw": "nw",
    "southeast": "se", "se": "se",
    "southwest": "sw", "sw": "sw",
}

# US state full names → 2-letter abbreviation for address comparison.
# Multi-word states are listed first so regex replacement consumes the full
# phrase before any single-word subterm can match (e.g. "West Virginia" before
# "Virginia"). Applied as a phrase-level substitution in normalize_address
# BEFORE tokenizing so "Colorado" and "CO" both reduce to "co".
_US_STATE_NAME_PHRASES: List[tuple] = sorted([
    ("district of columbia", "dc"), ("new hampshire", "nh"),
    ("new jersey", "nj"), ("new mexico", "nm"), ("new york", "ny"),
    ("north carolina", "nc"), ("north dakota", "nd"),
    ("rhode island", "ri"), ("south carolina", "sc"),
    ("south dakota", "sd"), ("west virginia", "wv"),
    ("alabama", "al"), ("alaska", "ak"), ("arizona", "az"),
    ("arkansas", "ar"), ("california", "ca"), ("colorado", "co"),
    ("connecticut", "ct"), ("delaware", "de"), ("florida", "fl"),
    ("georgia", "ga"), ("hawaii", "hi"), ("idaho", "id"),
    ("illinois", "il"), ("indiana", "in"), ("iowa", "ia"),
    ("kansas", "ks"), ("kentucky", "ky"), ("louisiana", "la"),
    ("maine", "me"), ("maryland", "md"), ("massachusetts", "ma"),
    ("michigan", "mi"), ("minnesota", "mn"), ("mississippi", "ms"),
    ("missouri", "mo"), ("montana", "mt"), ("nebraska", "ne"),
    ("nevada", "nv"), ("ohio", "oh"), ("oklahoma", "ok"),
    ("oregon", "or"), ("pennsylvania", "pa"), ("tennessee", "tn"),
    ("texas", "tx"), ("utah", "ut"), ("vermont", "vt"),
    ("virginia", "va"), ("washington", "wa"), ("wisconsin", "wi"),
    ("wyoming", "wy"),
], key=lambda x: len(x[0]), reverse=True)


# ── Carrier seed alias map (Beta Report §5.2 carrier handling) ────────────────

# Lightly-normalized carrier name (lowercase, punctuation -> space, collapsed)
# -> canonical family token. Known aliases collapse to one token; everything
# else falls through to a trimmed-name comparison and is surfaced for REVIEW
# (never a definitive hard conflict).
_CARRIER_ALIASES = {
    "emc": "emc",
    "emc insurance": "emc",
    "emc insurance company": "emc",
    "emc insurance companies": "emc",
    "emc property and casualty": "emc",
    "emc property and casualty company": "emc",
    "employers mutual casualty": "emc",
    "employers mutual casualty company": "emc",
}


# ── Low-level cleaners ────────────────────────────────────────────────────────

def _basic(s: Any) -> str:
    """Lowercase, replace '&' with 'and', drop punctuation, collapse whitespace.

    Dotted initialisms are collapsed first (N.A. -> na, L.L.C. -> llc, U.S.A. ->
    usa) so periods are truly ignored per Beta Report §5.2 and a dotted entity
    suffix matches its plain form. Only sequences of 2+ single-letter-dot groups
    are collapsed, so "St.Mary" (glued OCR) and "Inc." are left untouched.
    """
    if s is None:
        return ""
    s = str(s).lower().replace("&", " and ")
    s = re.sub(r"(?:\b[a-z]\.){2,}", lambda m: m.group(0).replace(".", ""), s)
    s = re.sub(r"[^a-z0-9\s]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# ── OCR glue: one company printed with its spaces lost (24 Sep 2026) ─────────
# The client's real certificate OCR prints its insurers as
# "EMCProperty&CasualtyCompany" and "EmployersMutualCasualtyCo." - each ONE
# token. Every identity key in this module tokenises on whitespace, so the
# certificate's carrier read as a company the declarations never mention:
# a false "Carrier NAIC: documents disagree (25186, 21415)" card, the
# "Multiple carriers referenced across documents" integrity warning, and the
# header binder dropping a correct NAIC because only the SPELLING differed.
# Every fixture had typed the names WITH their spaces, so none of it was seen.
#
# A mixed-case glued token still carries its word boundaries: a lower-case
# letter followed by a capital ("CasualtyCompany") or an initialism running
# into a capitalised word ("EMCProperty"). Split there - but only when the
# split is evidently several words: three or more pieces, or a later piece
# that is a company word. "McDonald", "ThinkSmith", "PayPal", "iPhone" stay
# whole. An ALL-CAPS glued token has no boundary to read; `entity_compact_key`
# covers that case for comparisons instead of guessing at a segmentation.
_GLUE_BOUNDARY_RE = re.compile(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_GLUE_WORD_CACHE: List[FrozenSet[str]] = []

# Words that DESCRIBE a business - never a legal form, never a connector. Only
# these may re-space a name for DISPLAY: "InTownSuitesLLC" contains none, so a
# real glued brand is never rewritten into "In Town Suites LLC".
_GLUE_DESCRIPTIVE_EXTRA = frozenset({
    "agencies", "brokerage", "brokers", "broker", "risk", "solutions",
    "partners", "holdings", "specialty", "surety", "fire", "marine",
    "employers", "commercial", "capital", "bank", "trust", "authority",
    "county", "construction", "contracting", "contractors", "insurers",
    "underwriting", "management", "associates", "consulting", "benefits",
})


def _glue_words() -> Tuple[FrozenSet[str], FrozenSet[str]]:
    """(company words, descriptive words), derived from this module's own
    tables - the strict-key token canon, the legal-form suffixes and the
    carrier aliases - plus the descriptive business words above."""
    if not _GLUE_WORD_CACHE:
        legal = {w for suf in _ENTITY_SUFFIXES for w in suf.split()}
        canon = set(_STRICT_TOKEN_CANON) | set(_STRICT_TOKEN_CANON.values())
        alias = {w for a in _CARRIER_ALIASES for w in a.split()}
        company = frozenset(canon | legal | alias | _GLUE_DESCRIPTIVE_EXTRA)
        descriptive = frozenset(
            w for w in company
            if w not in legal and w not in _STRICT_NOISE_TOKENS
            and w not in {"co", "cos", "company", "companies", "emc"} and len(w) > 2)
        _GLUE_WORD_CACHE.extend([company, descriptive])
    return _GLUE_WORD_CACHE[0], _GLUE_WORD_CACHE[1]


def deglue_entity_text(value: Any, *, for_display: bool = False) -> str:
    """Re-space the mixed-case tokens OCR glued together from several words.

    ``for_display`` is the stricter test used before a name is PRINTED: a
    token is split only when one of its pieces is a descriptive business word
    (Property, Casualty, Mutual, Insurance, Agency, Solutions ...), and "&" /
    "," regain their spacing. Identity keys use the broader test (three or
    more pieces, or any company word including a legal form), because both
    printings of one company go through it and only equality matters there.
    Tokens without an internal capital boundary are returned byte-identical.
    """
    s = "" if value is None else str(value)
    if not s or not _GLUE_BOUNDARY_RE.search(s):
        return s
    company, descriptive = _glue_words()
    out: List[str] = []
    for tok in re.split(r"(\s+)", s):
        if not tok or tok.isspace() or not _GLUE_BOUNDARY_RE.search(tok):
            out.append(tok)
            continue
        pieces = [p for p in _GLUE_BOUNDARY_RE.split(tok) if p]
        words = [w for p in pieces for w in re.findall(r"[a-z]+", p.lower())]
        later = [w for p in pieces[1:] for w in re.findall(r"[a-z]+", p.lower())]
        if for_display:
            split = len(pieces) >= 2 and any(w in descriptive for w in words)
        else:
            split = len(pieces) >= 3 or any(w in company for w in later)
        if not split:
            out.append(tok)
            continue
        spaced = " ".join(pieces)
        if for_display:
            spaced = re.sub(r"\s*&\s*", " & ", spaced)
            spaced = re.sub(r",(?=[A-Za-z])", ", ", spaced)
        out.append(spaced)
    return "".join(out)


# Legal-form TAILS a glued printing leaves unexpanded ("...CasualtyCo."),
# canonicalised the way `_STRICT_TOKEN_CANON` canonicalises a spaced one.
# Longest first; a tail is rewritten, never stripped, so "LLC" and "Inc" stay
# two different entities (Round 10 fix 46).
_COMPACT_TAILS = (
    ("incorporated", "inc"), ("corporation", "corp"), ("companies", "company"),
    ("company", "company"), ("limited", "ltd"), ("cos", "company"), ("co", "company"),
)


def entity_compact_key(value: Any) -> str:
    """The strict entity key with every space removed - a comparison key that
    cannot be moved by OCR spacing. "EMCPROPERTY&CASUALTYCOMPANY",
    "EMCProperty&CasualtyCompany" and "EMC Property & Casualty Company" share
    it; "EMC Property & Casualty" and "Employers Mutual Casualty" do not, and
    neither do an LLC and an Inc of one name. Equality only - never display."""
    compact = strict_entity_key(value).replace(" ", "")
    if not compact:
        return ""
    for tail, canon in _COMPACT_TAILS:
        if compact.endswith(tail) and len(compact) - len(tail) >= 3:
            if not compact.endswith(canon):
                compact = compact[: -len(tail)] + canon
            break
    return compact


# A CLIPPED last word (29 Oct 2026 strict review): OCR / a transcriber cut at
# the box edge prints "Summit Peak Casualty Compai" for "Summit Peak Casualty
# Company". Same entity when every other word is equal, in order, and the
# shorter last word is a proper prefix (>= 4 letters) of the other's - or is
# one once its own last letter (the half-letter at the cut) is dropped. Read
# on the strict tokens AND on the plain lower-case words, because the strict
# key canonicalises a legal form ("Corporation" -> "corp") that the clipped
# printing ("Corpor") never reached. Two different names never pass: "ABC
# Roofing" / "ABC Roofers Supply" (word count, not a prefix), "Summit Peak
# Casualty" / "Summit Peak Insurance" (not a prefix). Equality only - never a
# grouping key (`entity_compact_key` stays exact), never display.
_CLIP_MIN_LETTERS = 4


def _clipped_last_word(ta: List[str], tb: List[str]) -> bool:
    if len(ta) != len(tb) or len(ta) < 2 or ta[:-1] != tb[:-1]:
        return False
    a, b = ta[-1], tb[-1]
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    if short == long_ or not short.isalpha() or len(short) < _CLIP_MIN_LETTERS:
        return False
    if long_.startswith(short):
        return True                          # "Corpor" / "Corporation"
    # The cut letter itself misread ("Compai": "Compa" + a half-letter at the
    # box edge): every letter but the last is the other word's start.
    return (len(short) < len(long_) and len(short) - 1 >= _CLIP_MIN_LETTERS
            and long_.startswith(short[:-1]))


def _plain_words(value: Any) -> List[str]:
    return re.findall(r"[a-z0-9&]+", deglue_entity_text(str(value or "")).lower())


def fuller_entity_printing(a: Any, b: Any) -> Any:
    """Of two printings `same_entity_name` calls one entity, the one to PRINT:
    ``a`` unless ``b`` is ``a`` with its clipped last word whole ("Summit Peak
    Casualty Compai" -> "Summit Peak Casualty Company"). Spelling variants
    ("Co" / "Company", "&" / "and") keep ``a`` - the caller's choice stands."""
    try:
        ka, kb = strict_entity_key(a).split(), strict_entity_key(b).split()
        pa, pb = _plain_words(a), _plain_words(b)
        clipped = _clipped_last_word(ka, kb) or _clipped_last_word(pa, pb)
        if clipped and len(" ".join(pb)) > len(" ".join(pa)):
            return b
    except Exception:                                         # noqa: BLE001
        pass
    return a


def same_entity_name(a: Any, b: Any) -> bool:
    """True when two printings name ONE legal entity by spelling: equal strict
    keys, or equal compact keys (the same name with its spaces lost), or one
    printing whose last word was clipped (`_clipped_last_word`)."""
    ka, kb = strict_entity_key(a), strict_entity_key(b)
    if ka and kb and ka == kb:
        return True
    ca, cb = entity_compact_key(a), entity_compact_key(b)
    if ca and cb and ca == cb:
        return True
    if not (ka and kb):
        return False
    try:
        return (_clipped_last_word(ka.split(), kb.split())
                or _clipped_last_word(_plain_words(a), _plain_words(b)))
    except Exception:                                         # noqa: BLE001
        return False


# ── Public normalizers ────────────────────────────────────────────────────────

def normalize_name(value: Any) -> str:
    """Organization name for identity comparison.

    Lowercase, drop punctuation/commas/periods, collapse whitespace, and strip
    trailing entity suffixes (LLC / Inc / Corp / Limited Liability Company / ...)
    so "ORBIN CONTRACTING LLC", "Orbin Contracting LLC" and "Orbin Contracting,
    LLC" all reduce to "orbin contracting". Returns '' when no usable signal.
    """
    s = _basic(deglue_entity_text(value))
    if not s:
        return ""
    changed = True
    while changed:
        changed = False
        for suf in _ENTITY_SUFFIXES:
            if s == suf:
                return ""
            if s.endswith(" " + suf):
                s = s[: -(len(suf) + 1)].strip()
                changed = True
    return s


_DATE_FORMATS = (
    "%Y-%m-%d", "%Y/%m/%d",
    "%m/%d/%Y", "%m/%d/%y",
    "%m-%d-%Y", "%m-%d-%y",
    "%m.%d.%Y", "%m.%d.%y",
    "%B %d %Y", "%b %d %Y",
    "%d %B %Y", "%d %b %Y",
    # DD-Mon-YYYY, the form carrier and agency-management systems export
    # ("15-Jul-2025", "15/Jul/25"). Found by the 2026-09-05 fuzz sweep, where
    # `15-Jul-2025` vs `07/15/2025` came back a CONFLICT - a pure formatting
    # difference producing a warning, which is exactly what the client's
    # broader normalization clause forbids.
    #
    # SAFE BECAUSE THE MONTH IS A NAME. Day-first NUMERIC ("15/07/2025") is
    # deliberately still unparsed and must stay that way: "05/09/2026" is the
    # 5th of September or the 9th of May and nothing in the string can decide
    # which, so parsing it would invent a date rather than normalise one.
    # Compact "20250715" is likewise excluded - `same_fact`'s value-shape
    # fallback tries `normalize_date` on non-date fields too, so an 8-digit
    # account or policy number would start reading as a date.
    "%d-%B-%Y", "%d-%b-%Y", "%d-%B-%y", "%d-%b-%y",
    "%d/%B/%Y", "%d/%b/%Y", "%d/%B/%y", "%d/%b/%y",
    "%B-%d-%Y", "%b-%d-%Y", "%B-%d-%y", "%b-%d-%y",
)


def normalize_date(value: Any) -> Optional[str]:
    """Canonical ISO date ('YYYY-MM-DD'), or None if not parseable.

    Treats "07/15/25", "7/15/2025", "07/15/2025" and "2025-07-15" as equal.
    Two-digit years pivot at 70 (00-69 -> 2000s, 70-99 -> 1900s), appropriate
    for policy dates. Returns None when the value cannot be parsed as a date so
    the caller can fall back to text comparison.
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    return _normalize_date_text(s)


@functools.lru_cache(maxsize=65536)
def _normalize_date_text(s: str) -> Optional[str]:
    """`normalize_date` on a stripped string, cached: a pure function the scorer
    and the review plan call tens of thousands of times per page (28 Oct: 27 of a
    40 s pre-form load). Every format needs a digit, so a digit-less value is no
    date without trying them."""
    if not any(ch.isdigit() for ch in s):
        return None
    # Strip an ordinal suffix and a leading weekday/commas for the written forms.
    s = re.sub(r"(\d+)(st|nd|rd|th)\b", r"\1", s, flags=re.IGNORECASE)
    s = s.replace(",", " ")
    s = re.sub(r"\s+", " ", s).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def normalize_entity_type(value: Any) -> str:
    """Entity-type to a canonical token. "LLC" == "Limited Liability Company".

    Extraction sometimes returns a concatenated PascalCase value with no spaces
    ("LimitedLiabilityCompany" - seen from schema-driven form fields such as
    ACORD's own entity-type enum). The synonym match below is word-boundary
    based, so it would silently miss that form and treat it as a different
    entity type than "Limited Liability Company" / "LLC". Splitting camelCase
    into words FIRST (before lowercasing) recovers the word boundaries so all
    three forms collapse to the same canonical token.
    """
    raw = "" if value is None else str(value)
    raw = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", raw)
    s = _basic(raw)
    if not s:
        return ""
    for variant, canon in _ENTITY_TYPE_SYNONYMS_SORTED:
        s = re.sub(rf"\b{re.escape(variant)}\b", canon, s)
    return re.sub(r"\s+", " ", s).strip()


# ── Legal-entity FAMILIES - V1 H4 (client section 9), 2026-08-27 ─────────────
# `normalize_entity_type` above answers "are these two the same entity type?"
# (the COMPARATOR's question, D3). It does NOT answer "which of ACORD's nine
# legal-entity boxes is this?", and three separate places were each guessing at
# that in their own vocabulary:
#
#   * FACT_REGISTRY["entity_type"]["validate"] - a literal 16-item uppercase set
#     that REFUSED 8 of the 13 options `answer_options` itself offers
#     ("Limited Liability Company", "S Corporation", "Joint Venture", ...), so a
#     producer picking from our own dropdown was told "that does not look right";
#   * `answer_options.ENTITY_TYPE_OPTIONS` - a third list, written independently;
#   * `pdf_service._derive_indicator` - an inline "limited liability company ->
#     llc" phrase loop plus substring matching, which ticked NO box for
#     "Sole Proprietorship" (ACORD's box is Individual), ticked Corporation for
#     "S Corporation", ticked BOTH Corporation and NotForProfit for "Non-Profit
#     Corporation", and ticked nothing at all for "Association" / "Municipality"
#     while asserting "No" on the Other box that exists precisely for them.
#
# ACORD's own tooltip settles the shape and it is quoted here so nobody has to
# re-derive it: *"Indicates the legal entity CODE for the named insured IS
# 'Corporation'"* - singular. The nine indicators are MUTUALLY EXCLUSIVE, and
# `NamedInsured_LegalEntity_OtherIndicator_*` pairs with
# `NamedInsured_LegalEntity_OtherDescription_*` for anything not listed.
#
# THIS IS ADDITIVE AND MUST STAY ADDITIVE. `normalize_entity_type` is untouched,
# so every conflict / equivalence decision that reads it (fact_comparison ->
# fact_equivalence -> underwriting_consistency, D3's one comparator door) behaves
# exactly as before. This function only ever CLASSIFIES.
#
# Verified 2026-08-27 to be a strict SUPERSET of the validator it replaces:
# all 16 values the old literal set accepted still map to a family, and all 13
# offered options now validate. Nothing that validated before stops validating.
ENTITY_FAMILY_INDIVIDUAL = "individual"
ENTITY_FAMILY_PARTNERSHIP = "partnership"
ENTITY_FAMILY_LLC = "llc"
ENTITY_FAMILY_CORPORATION = "corporation"
ENTITY_FAMILY_S_CORPORATION = "s_corporation"
ENTITY_FAMILY_NOT_FOR_PROFIT = "not_for_profit"
ENTITY_FAMILY_JOINT_VENTURE = "joint_venture"
ENTITY_FAMILY_TRUST = "trust"
ENTITY_FAMILY_OTHER = "other"

ENTITY_FAMILIES = (
    ENTITY_FAMILY_INDIVIDUAL, ENTITY_FAMILY_PARTNERSHIP, ENTITY_FAMILY_LLC,
    ENTITY_FAMILY_CORPORATION, ENTITY_FAMILY_S_CORPORATION,
    ENTITY_FAMILY_NOT_FOR_PROFIT, ENTITY_FAMILY_JOINT_VENTURE,
    ENTITY_FAMILY_TRUST, ENTITY_FAMILY_OTHER,
)

# ORDER IS LOAD-BEARING - most specific family first. Every one of these three
# orderings is a real case that the previous substring matching got wrong:
#   not_for_profit BEFORE corporation   -> "Non-Profit Corporation" is not a
#                                          plain Corporation (it ticked BOTH)
#   s_corporation  BEFORE corporation   -> "S Corporation" has its own ACORD box
#   llc            BEFORE partnership   -> guards the LLC/LLP pair
# Matched on WHOLE WORDS of the canonical token `normalize_entity_type` returns,
# never as bare substrings, so "corp" inside "s corp" cannot win by position.
_ENTITY_FAMILY_RULES = (
    (ENTITY_FAMILY_NOT_FOR_PROFIT, ("not for profit", "nonprofit", "non profit",
                                    "charitable", "501 c 3")),
    (ENTITY_FAMILY_S_CORPORATION, ("s corp", "subchapter s", "scorp")),
    (ENTITY_FAMILY_JOINT_VENTURE, ("joint venture", "jv")),
    (ENTITY_FAMILY_LLC, ("llc", "pllc", "limited liability co",
                         "limited liability company", "limited liability corp")),
    (ENTITY_FAMILY_TRUST, ("trust",)),
    (ENTITY_FAMILY_PARTNERSHIP, ("partnership", "llp", "lp",
                                 "limited partnership", "general partnership")),
    (ENTITY_FAMILY_INDIVIDUAL, ("individual", "sole proprietor", "sole prop",
                                "sole proprietorship", "proprietor",
                                "self employed")),
    (ENTITY_FAMILY_CORPORATION, ("corporation", "corp", "incorporated", "inc", "pc")),
    # Everything ACORD does not print a box for. These are REAL entity types, so
    # they belong on the form's Other box with their own wording in
    # OtherDescription - not silently unticked, which is what happened before.
    (ENTITY_FAMILY_OTHER, ("association", "municipality", "government",
                           "governmental", "public entity", "unincorporated",
                           "cooperative", "co op", "religious", "church",
                           "school district", "other")),
)


def entity_family(value: Any) -> Optional[str]:
    """Which ACORD legal-entity family is this, or None when we cannot tell.

    None is a real answer and callers MUST honour it: core principle 3 says a
    value we cannot classify never becomes a "No". The stamper ticks NOTHING for
    None rather than asserting the named insured is none of the nine, and the
    validator refuses it rather than storing an entity type no form can express.

    Positive evidence only, and never a guess: "Ltd" alone stays None (a UK
    private company and a US "Acme Ltd" trade name are not distinguishable here),
    which is the right-or-blank rule this codebase applies everywhere else.
    """
    s = normalize_entity_type(value)
    if not s:
        return None
    # Pad and strip punctuation so every probe below is a WHOLE-WORD test.
    s = " " + re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", s)).strip() + " "
    for family, words in _ENTITY_FAMILY_RULES:
        for word in words:
            if f" {word} " in s:
                return family
    return None


# ── ONE DOCUMENT'S ENTITY TYPE (7 Oct 2026, Choice Electric live run) ────────
# The model reads an entity type off a printed MENU by taking the first option
# word, not the ticked one: "Form Of Business: / Corporation X Limited Liability
# Company Individual" (the X ticks LLC) came back "Corporation"; a carrier menu
# with no LLC option ("X CORPORATION SOLE PROPRIETOR PARTNERSHIP OR JOINT
# VENTURE OTHER") gave "Corporation" for "CHOICE ELECTRIC LLC". Two readers then
# disagreed about the documents - the pre-form warning counted Corporation and
# LLC, the Data Consistency card only Corporation - and the warning pointed at a
# card that said "nothing to confirm".
#
# One reading, used by the merge (which corrects the per-document copy every
# later reader sees) and by submission integrity (which may run before it):
#   1. a value the document reads off a MENU (a run of lines made only of
#      entity options, tick marks and "or") counts only as the option a tick
#      mark sits beside - the box precedes its caption, so a mark binds to the
#      option after it, or to the one before it at the end of a line; no single
#      ticked option = no reading. A value the document STATES ("Entity Type:
#      LLC") or that appears on no menu is left as read.
#   2. a legal-form DESIGNATOR closing the insured's own name (LLC, L.L.C.,
#      PLLC, Inc, Corp, LP, LLP ...) decides between INCOMPATIBLE families -
#      a name ending "LLC" is not a Corporation. Compatible readings stand
#      ("S Corporation" or "Non-Profit Corporation" for an "Inc").
_ENTITY_MENU_MARK_GLYPHS_RE = re.compile(r"[☒☑✓✔✗✘■▣◼●◉]")
_ENTITY_MENU_BOXED_X_RE = re.compile(r"[\[(]\s*[xX]\s*[\])]")
_ENTITY_MENU_PHRASES = tuple(sorted({
    "limited liability company", "limited liability corporation",
    "limited liability partnership", "limited partnership", "general partnership",
    "partnership", "joint venture", "corporation", "subchapter s corporation",
    "subchapter s", "s corporation", "s corp", "not for profit corporation",
    "non profit corporation", "not for profit", "non profit", "nonprofit",
    "individual", "sole proprietor", "sole proprietorship", "proprietor", "trust",
    "association", "unincorporated association", "llc", "pllc", "llp", "lp",
    "corp", "inc", "incorporated", "other",
}, key=lambda p: (-len(p.split()), p)))
_ENTITY_MENU_CONNECTORS = frozenset({"or", "and", "specify"})
_ENTITY_STATED_LABEL_RE = re.compile(
    r"\b(?:entity|business\s+type|type\s+of\s+business|form\s+of\s+business|"
    r"organi[sz]ation|legal\s+(?:form|status|structure))\b[^:\n]{0,40}:\s*(.+)$", re.I)
_DESIGNATOR_SUFFIXES = (
    (("limited", "liability", "company"), ENTITY_FAMILY_LLC, "Limited Liability Company"),
    (("limited", "liability", "partnership"), ENTITY_FAMILY_PARTNERSHIP, "Limited Liability Partnership"),
    (("limited", "partnership"), ENTITY_FAMILY_PARTNERSHIP, "Limited Partnership"),
    (("pllc",), ENTITY_FAMILY_LLC, "Limited Liability Company"),
    (("llc",), ENTITY_FAMILY_LLC, "Limited Liability Company"),
    (("llp",), ENTITY_FAMILY_PARTNERSHIP, "Limited Liability Partnership"),
    (("lp",), ENTITY_FAMILY_PARTNERSHIP, "Limited Partnership"),
    (("incorporated",), ENTITY_FAMILY_CORPORATION, "Corporation"),
    (("corporation",), ENTITY_FAMILY_CORPORATION, "Corporation"),
    (("inc",), ENTITY_FAMILY_CORPORATION, "Corporation"),
    (("corp",), ENTITY_FAMILY_CORPORATION, "Corporation"),
)
# Pairs a designator contradicts outright. Everything else is compatible (an
# LLC can be a non-profit or elect S status; an "Inc" can be an S corporation
# or a non-profit corporation) and is never overridden.
_DESIGNATOR_CONTRADICTS = {
    ENTITY_FAMILY_LLC: frozenset({ENTITY_FAMILY_CORPORATION, ENTITY_FAMILY_PARTNERSHIP,
                                  ENTITY_FAMILY_INDIVIDUAL}),
    ENTITY_FAMILY_CORPORATION: frozenset({ENTITY_FAMILY_LLC, ENTITY_FAMILY_PARTNERSHIP,
                                          ENTITY_FAMILY_INDIVIDUAL}),
    ENTITY_FAMILY_PARTNERSHIP: frozenset({ENTITY_FAMILY_LLC, ENTITY_FAMILY_CORPORATION,
                                          ENTITY_FAMILY_INDIVIDUAL}),
}
_TICKED_FAMILY_LABEL = {
    ENTITY_FAMILY_LLC: "Limited Liability Company",
    ENTITY_FAMILY_CORPORATION: "Corporation",
    ENTITY_FAMILY_S_CORPORATION: "S Corporation",
    ENTITY_FAMILY_PARTNERSHIP: "Partnership",
    ENTITY_FAMILY_INDIVIDUAL: "Individual",
    ENTITY_FAMILY_NOT_FOR_PROFIT: "Non-Profit Corporation",
    ENTITY_FAMILY_JOINT_VENTURE: "Joint Venture",
    ENTITY_FAMILY_TRUST: "Trust",
}


def name_legal_form(name: Any) -> Optional[Tuple[str, str]]:
    """(entity family, label) of the legal-form designator CLOSING a name, or
    None. "CHOICE ELECTRIC LLC" / "Choice Electric, L.L.C." -> llc; "Acme Inc."
    -> corporation; "Acme Company", "Acme Ltd", "Smith DBA Sparky" -> None
    (no designator, or not one that names a single family)."""
    s = deglue_entity_text(name).lower().replace(".", "")
    toks = re.sub(r"[^a-z0-9&]+", " ", s).split()
    if len(toks) < 2:
        return None                      # a bare designator is not a name
    for suffix, family, label in _DESIGNATOR_SUFFIXES:
        n = len(suffix)
        if len(toks) > n and tuple(toks[-n:]) == suffix:
            return family, label
    return None


def _menu_items(line: str) -> Optional[List[Tuple[str, Optional[str], str]]]:
    """The line as [(kind, family, printed)] when it is made ONLY of entity
    options, tick marks and connectors (after an optional leading "Label:"),
    else None. kind is "opt" / "mark"."""
    s = _ENTITY_MENU_BOXED_X_RE.sub(" x ", _ENTITY_MENU_MARK_GLYPHS_RE.sub(" x ", str(line or "")))
    if ":" in s:
        head, tail = s.split(":", 1)
        if not any(re.search(rf"\b{re.escape(p)}\b", head.lower()) for p in _ENTITY_MENU_PHRASES):
            s = tail
    toks = re.sub(r"[^a-z0-9]+", " ", s.lower().replace(".", "")).split()
    if not toks:
        return None
    items: List[Tuple[str, Optional[str], str]] = []
    i = 0
    while i < len(toks):
        if toks[i] == "x":
            items.append(("mark", None, "x"))
            i += 1
            continue
        for p in _ENTITY_MENU_PHRASES:
            pt = p.split()
            if tuple(toks[i:i + len(pt)]) == tuple(pt):
                items.append(("opt", entity_family(p), p))
                i += len(pt)
                break
        else:
            if toks[i] in _ENTITY_MENU_CONNECTORS:
                i += 1
                continue
            return None                  # a word that is no option: not a menu line
    return items if any(k == "opt" for k, _f, _p in items) else None


def _entity_menus(text: Any) -> List[dict]:
    """Every entity-type MENU in ``text``: runs of menu-shaped lines with two
    or more options. Each: {"families": set, "marked": set of ticked families}.
    Cached per text (a pure read; the review plan re-scores the same documents
    dozens of times per page, 28 Oct) - every call gets its own sets."""
    return [{"families": set(f), "marked": set(m)}
            for f, m in _entity_menus_cached(str(text or ""))]


@functools.lru_cache(maxsize=256)
def _entity_menus_cached(text: str) -> Tuple[Tuple[frozenset, frozenset], ...]:
    return tuple((frozenset(m["families"]), frozenset(m["marked"]))
                 for m in _entity_menus_uncached(text))


def _entity_menus_uncached(text: Any) -> List[dict]:
    menus: List[dict] = []
    run: List[List[Tuple[str, Optional[str], str]]] = []

    def _close() -> None:
        opts = [it for line in run for it in line if it[0] == "opt"]
        if len(opts) >= 2:
            marked = set()
            for line in run:
                for i, (kind, _f, _p) in enumerate(line):
                    if kind != "mark":
                        continue
                    nxt = line[i + 1] if i + 1 < len(line) else None
                    if nxt is not None and nxt[0] == "opt":
                        marked.add(nxt[1])
                    elif nxt is None and i > 0 and line[i - 1][0] == "opt":
                        marked.add(line[i - 1][1])
            menus.append({"families": {f for _k, f, _p in opts},
                          "marked": marked})
        run.clear()

    for raw_line in str(text or "").splitlines():
        items = _menu_items(raw_line)
        if items is None:
            _close()
        else:
            run.append(items)
    _close()
    return menus


def _entity_stated_families(text: Any) -> set:
    """Families a document STATES on a labelled line ("Entity Type: LLC")."""
    out = set()
    for raw_line in str(text or "").splitlines():
        m = _ENTITY_STATED_LABEL_RE.search(raw_line)
        if not m:
            continue
        items = _menu_items(m.group(1))
        if items and len(items) == 1 and items[0][0] == "opt":
            out.add(items[0][1])
    return out


def _designator_for(own_names: Any, package_names: Any) -> Optional[Tuple[str, str]]:
    """The ONE designator the insured's names carry: the document's own name
    first; else the package's names of the same insured (all of them when the
    document names nobody and the package names one insured). Two different
    designators = None."""
    def _clean(names: Any) -> List[str]:
        return [str(n) for n in (names or []) if str(n or "").strip()]

    own, pkg = _clean(own_names), _clean(package_names)
    forms = {f for f in (name_legal_form(n) for n in own) if f}
    if not forms:
        if own:
            keys = {normalize_name(n) for n in own} - {""}
            pool = [n for n in pkg if normalize_name(n) in keys]
        else:
            pool = pkg if len({normalize_name(n) for n in pkg} - {""}) == 1 else []
        forms = {f for f in (name_legal_form(n) for n in pool) if f}
    families = {f[0] for f in forms}
    if len(families) != 1:
        return None
    return sorted(forms, key=lambda f: f[1])[0]


def settle_document_entity_type(value: Any, text: Any = None, own_names: Any = None,
                                package_names: Any = None) -> Tuple[Optional[str], Optional[str]]:
    """(the document's entity type, the rule that changed it or None).

    See the block comment above. Never raises; an unclassifiable value and a
    document with no menu and no designator come back unchanged.
    """
    try:
        raw = "" if value is None else str(value).strip()
        family = entity_family(raw) if raw else None
        if not raw or family is None:
            return (value, None)
        out: Optional[str] = raw
        rule: Optional[str] = None
        if text:
            menus = [m for m in _entity_menus(text) if family in m["families"]]
            if menus and family not in _entity_stated_families(text):
                marked = set().union(*(m["marked"] for m in menus))
                if len(marked) == 1 and next(iter(marked)) == family:
                    pass
                elif len(marked) == 1 and next(iter(marked)) in _TICKED_FAMILY_LABEL:
                    out, rule = _TICKED_FAMILY_LABEL[next(iter(marked))], "menu_tick"
                else:
                    return (None, "menu_without_one_tick")
        designator = _designator_for(own_names, package_names)
        if designator and entity_family(out) in _DESIGNATOR_CONTRADICTS.get(designator[0], ()):
            out, rule = designator[1], "name_designator"
        return (out if rule else value, rule)
    except Exception:                                         # noqa: BLE001
        return (value, None)


def normalize_address(value: Any) -> str:
    """Street address for comparison.

    Lowercases, treats '#' as a separator, expands/collapses full US state names
    to their 2-letter abbreviation (Colorado->co, New York->ny, ...), truncates a
    ZIP+4 to its 5-digit ZIP (80216-3121 == 80216 - the first 5 digits ARE the
    ZIP5, so a ZIP+4 is strictly more precision on the SAME delivery point, not a
    different one - collapsing it here is what lets the picker treat them as one
    address instead of an unresolved conflict), drops punctuation, maps
    street-suffix words to their abbreviation (Street->st, Avenue->ave, ...),
    standardizes compass directionals (North->n, ...), and removes unit markers
    (Suite/Ste/Unit/#) so "4800 DAHLIA ST #D13" and "4800 Dahlia Street Suite
    D13, Denver, Colorado 80216-3121" both reduce to the same token string.
    """
    if value is None:
        return ""
    s = str(value).lower().replace("#", " ")
    # ZIP+4 -> ZIP5, BEFORE punctuation stripping turns the hyphen into a bare
    # space (which would otherwise leave the extra 4 digits as an unmatched
    # trailing token and manufacture a false conflict against a ZIP5-only value).
    s = re.sub(r"\b(\d{5})-\d{4}\b", r"\1", s)
    # Substitute full state names before stripping punctuation so multi-word
    # names ("New York", "West Virginia") are caught as phrases. Longest phrases
    # are applied first (see _US_STATE_NAME_PHRASES sort order).
    for phrase, abbrev in _US_STATE_NAME_PHRASES:
        s = re.sub(rf"\b{re.escape(phrase)}\b", abbrev, s)
    s = re.sub(r"[^a-z0-9\s]+", " ", s)
    # Compass directionals collapse to their abbreviation HERE, before the
    # unit-join below - not in the token loop. The order is load-bearing and
    # getting it wrong was a real bug (found 2026-08-21 probing C1-C): the join
    # fired on "E 9 Mile Rd" -> "e9 mile rd" while "East 9 Mile Rd" stayed
    # "e 9 mile rd", so two printings of ONE address became a conflict - the
    # exact defect class this module exists to prevent. Normalising first makes
    # both sides identical before anything can glue them.
    s = re.sub(
        r"\b(north|south|east|west|northeast|northwest|southeast|southwest)\b",
        lambda m: _DIRECTIONALS[m.group(1)], s)
    # A unit marker glued to its number ("Apt4", "Ste12") is the same unit as
    # the spaced form; splitting it lets the marker be dropped like any other.
    s = re.sub(r"\b(suites?|ste|units?|apt|apartment|rm|room|fl|floor|bldg)(\d)",
               r"\1 \2", s)
    # A unit designator printed as letter + separator + digits ("D-13", "D 13",
    # "Suite B 5") is the same unit as "D13" / "B5": OCR and form layouts split
    # it unpredictably (V1 plan C1-B FLAG 3 - the hyphen inside the unit was
    # the one printing the picker could not fold). DIRECTIONAL letters are
    # excluded: "E 9" is East 9th - a street name, not unit E9.
    s = re.sub(r"\b(?!(?:n|s|e|w|ne|nw|se|sw)\b)([a-z])\s+(\d+[a-z]?)\b",
               r"\1\2", s)
    tokens = s.split()
    out: List[str] = []
    for tok in tokens:
        if tok in _UNIT_MARKERS:
            continue
        tok = _DIRECTIONALS.get(tok, tok)
        out.append(_STREET_SUFFIXES.get(tok, tok))
    return " ".join(out).strip()


def normalize_carrier(value: Any) -> str:
    """Carrier name to a canonical token.

    Known aliases (seed map) collapse to a family token (EMC ↔ Employers Mutual
    Casualty). Otherwise generic insurer-suffix words are stripped and the
    remaining name tokens are returned for comparison. Carrier differences are
    treated as REVIEW (not a hard conflict) by the caller.
    """
    s = _basic(deglue_entity_text(value))
    if not s:
        return ""
    if s in _CARRIER_ALIASES:
        return _CARRIER_ALIASES[s]
    # The alias map is keyed on the FULL printing, so an abbreviated legal form
    # missed it: "Employers Mutual Casualty Co." fell through to the trimmed
    # token "employers" while "... Company" answered "emc" - one carrier, two
    # families, and submission integrity reported "Multiple carriers referenced
    # across documents" on the client's package. Canonicalise the spelling the
    # way the strict key does (Co -> company, Cas -> casualty, Prop ->
    # property), then ask the alias map again. Words are expanded, never added
    # or dropped, so two different families cannot be joined here.
    canon = " ".join(_STRICT_TOKEN_CANON.get(t, t) for t in s.split())
    if canon in _CARRIER_ALIASES:
        return _CARRIER_ALIASES[canon]
    # Strip generic insurer descriptors so "EMC Property and Casualty Company"
    # and "EMC Insurance" both reduce toward "emc".
    _GENERIC = {
        "insurance", "company", "companies", "casualty", "property", "mutual",
        "group", "co", "inc", "corp", "ins", "and", "of", "the", "national",
        "indemnity", "underwriters", "assurance", "general",
    }
    tokens = [t for t in canon.split() if t not in _GENERIC]
    trimmed = " ".join(tokens).strip()
    # Re-check the alias map against the trimmed token (catches "emc" alone).
    if trimmed in _CARRIER_ALIASES:
        return _CARRIER_ALIASES[trimmed]
    return trimmed or s


_VALUATION_METHOD_CANON = {
    "rcv": "rcv", "r": "rcv", "replacement cost": "rcv", "replacement cost value": "rcv",
    "acv": "acv", "a": "acv", "actual cash value": "acv",
    "agreed amount": "agreed_amount", "v": "agreed_amount",
    "market value": "market_value", "m": "market_value",
}


def normalize_valuation_method(value: Any) -> str:
    """Canonical valuation-method key - "RCV"/"R"/"Replacement Cost" (and the
    ACV/Agreed-Amount/Market-Value equivalents) all collapse to the same
    comparison key, regardless of whether the value came from the extraction-
    normalized 3-letter industry term or the ACORD schema's own single-letter
    code convention. See VALUATION_METHOD_FIELDS for why this is its own
    narrow, field-scoped normalizer rather than a generic synonym expansion.
    """
    s = _basic(value)
    if not s:
        return ""
    return _VALUATION_METHOD_CANON.get(s, s)


def normalize_fein(value: Any) -> str:
    """Digits-only FEIN. Returns '' unless exactly 9 digits (a complete US FEIN).

    A US FEIN/EIN is exactly 9 digits. Requiring an exact length (rather than ">=
    9") means an over-long OCR/extraction artifact normalizes to '' (no signal,
    treated as absent) instead of a distinct value that could manufacture a false
    cross-document FEIN conflict. Mirrors the rule in submission_integrity so the
    two modules agree.
    """
    if value is None:
        return ""
    digits = re.sub(r"\D", "", str(value))
    return digits if len(digits) == 9 else ""


# ── A STATED PERCENTAGE (22 Oct 2026, Z33-PERCENT) ───────────────────────────
# A wind / hail or earthquake deductible is printed as a share of the insured
# value ("2%", "2% of TIV", "1.5 percent"). A value whose FIRST figure carries a
# percent unit is a percentage, never that many dollars. The one reader for
# every door that must tell the two apart: a person's answer (the amount-or-
# percent check in `fact_registry`, `answer_semantics`, the client page's
# normalizer `arq_service._normalize_amount_or_percent` and its JavaScript twin
# `frontend/src/utils/answerFormats.js`), the dec-entry backfill, the stamper's
# amount / percent boxes and the money readers. The first figure decides:
# "$25,000 or 2%" is a dollar statement, "2% / $25,000 minimum" a percentage.
# A minus sign counts only when it touches the figure ("-2%"); "Wind - 2%" is a
# separator.
#
# A FRACTION IS ONE FIGURE (22 Oct 2026, Z33-PERCENT review). A dec page prints
# a wind deductible "1-1/2%" or "1½%" as often as "1.5%", and the reader took
# its first figure "1" - no unit after it, so no percentage, and the ACORD 160
# amount box printed "$ 1-1/2%". A whole number with a proper fraction
# ("1-1/2", "1 1/2"), a fraction glyph ("1½", "½") or a plain fraction ("1/2")
# is read as one figure when its decimal is exact in six places (the
# denominator divides 10**6), so the "1.5%" it is written as is the same
# number. A date's "12/31", "80/90" or "1/3" is no such fraction, and a range
# ("1-2%") is still no percentage: its first figure "1" carries no unit.
#
# ASCII on purpose: the browser twin (`frontend/src/utils/answerFormats.js`)
# reads ASCII digits and glues a figure only to an ASCII word character.
_FRACTION_GLYPHS = {"½": (1, 2), "¼": (1, 4), "¾": (3, 4), "⅕": (1, 5), "⅖": (2, 5),
                    "⅗": (3, 5), "⅘": (4, 5), "⅛": (1, 8), "⅜": (3, 8), "⅝": (5, 8),
                    "⅞": (7, 8), "⅒": (1, 10)}
_FIRST_FIGURE_RE = re.compile(
    r"(?<![\w.,])(?P<sign>[-−–])?"
    r"(?P<num>\d+(?:-| +)\d+/\d+"
    r"|(?:\d+ ?)?[" + "".join(_FRACTION_GLYPHS) + r"]"
    r"|\d+/\d+"
    r"|\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+)", re.ASCII)
# The word ends where an ASCII word character does not follow - JavaScript's
# \b, so the browser twin ends "percent" at the same place.
_PERCENT_UNIT = r"\s*(?:%|percent(?![A-Za-z0-9_])|per\s*cent(?![A-Za-z0-9_])|pct(?![A-Za-z0-9_])\.?)"
_PERCENT_UNIT_RE = re.compile(_PERCENT_UNIT, re.I)
# A figure's last character, then a percent unit: the value speaks of a
# percentage whether or not the reader takes that figure as one ("2,5 percent",
# "$25,000 or 2%", "1-2%").
_MENTIONS_PERCENT_RE = re.compile(r"[0-9" + "".join(_FRACTION_GLYPHS) + r"]" + _PERCENT_UNIT, re.I)


def opens_with_percent_unit(text: Any) -> bool:
    """True when `text` starts with a percent unit ("%", " percent", "per
    cent", "pct") - the words that make the figure before them a percentage."""
    return bool(_PERCENT_UNIT_RE.match(str(text if text is not None else "")))


def mentions_a_percentage(value: Any) -> bool:
    """True when any figure of the value is followed by a percent unit, read as
    a percentage or not: "$25,000 or 2%" (whose FIRST figure is a dollar
    amount, so `stated_percentage` is None), "2,5 percent", "2%" - never
    "$2,500" or "2 per month". A door that reads such a value as dollars keeps
    only its first figure, so it does not read it at all."""
    if value is None or isinstance(value, (bool, int, float, list, dict)):
        return False
    return bool(_MENTIONS_PERCENT_RE.search(str(value)))


def _figure_value(num: str) -> Optional[float]:
    """The number one figure of `_FIRST_FIGURE_RE` states, or None for a
    fraction that is not proper with an exact six-place decimal."""
    glyph = _FRACTION_GLYPHS.get(num[-1:])
    if glyph is not None:
        whole_text, (n, d) = num[:-1].strip(), glyph
    elif "/" in num:
        head, den = num.rsplit("/", 1)
        parts = re.split(r"[- ]+", head)
        whole_text = parts[0] if len(parts) == 2 else ""
        n, d = int(parts[-1]), int(den)
    else:
        try:
            return float(num.replace(",", ""))
        except ValueError:
            return None
    if not 0 < n < d or 10 ** 6 % d:
        return None
    return float(f"{(int(whole_text) if whole_text else 0) + n / d:.6f}")


def _figure_text(number: float) -> str:
    return (str(int(number)) if number.is_integer()
            else f"{number:.6f}".rstrip("0").rstrip("."))


def stated_percentage(value: Any) -> Optional[Dict[str, Any]]:
    """{"number": 2.0, "figure": "2", "text": "2% of TIV", "plain": False,
    "before": "", "after": " of TIV"} when the value's first figure is printed
    as a percentage, else None.

    `text` is the value with that figure written "<n>%" ("2 %", "2 percent",
    "2.0 pct", "1-1/2%" -> "2%" / "1.5%") and everything around it kept as
    written (`before` / `after`); `plain` is True when nothing else is there. A
    "$" written straight before the figure is dropped: "$2 %" is what the old
    dollar box made of "2%" (22 Oct 2026). `number` keeps its sign, so a caller
    that takes a person's answer refuses "-2%" and "200%" itself (0 to 100). A
    figure glued to a word ("A2%") is not read."""
    if value is None or isinstance(value, (bool, int, float, list, dict)):
        return None
    s = str(value).strip()
    m = _FIRST_FIGURE_RE.search(s)
    if not m:
        return None
    unit = _PERCENT_UNIT_RE.match(s, m.end("num"))
    if not unit:
        return None
    number = _figure_value(m.group("num"))
    if number is None:
        return None
    if m.group("sign"):
        number = -number
    figure = _figure_text(number)
    # A minus sign or currency letters straight before the "$" ("-$2%",
    # "US$2%") would be reshaped into "-2%" / "US2%" by dropping it: refused
    # (review C, 22 Oct 2026).
    if re.search(r"(?:[-−–]|[A-Za-z])\$\s*$", s[:m.start()]):
        return None
    before, after = re.sub(r"\$\s*$", "", s[:m.start()]), s[unit.end():]
    text = re.sub(r"\s+", " ", f"{before}{figure}%{after}").strip()
    return {"number": number, "figure": figure, "text": text,
            "plain": not before.strip() and not after.strip(),
            "before": before, "after": after}


# A BARE FIGURE ON AN AMOUNT-OR-PERCENT DEDUCTIBLE (22 Oct 2026, owner's call).
# The deductible basis check (`cross_form_validator._deductible_basis_evident`)
# already reads a bare amount of 100 or more as flat dollars ("a percentage
# deductible is never 100 or more") and a smaller bare number on a wind /
# earthquake deductible as that peril's percentage column. A person's bare "2"
# for such a fact is read by the same line: under 100 it is "2%", 100 or more
# dollars as before. Anything carrying a "$" (or a comma, a word, a k / m) is
# not bare and stays dollars. Twin: `frontend/src/utils/answerFormats.js`
# `bareFigurePercent`.
PERCENT_DEDUCTIBLE_CEILING = 100
_BARE_FIGURE_RE = re.compile(r"\d+(?:\.\d+)?|\.\d+", re.ASCII)


def bare_figure_as_percentage(value: Any) -> Optional[Dict[str, Any]]:
    """`stated_percentage` of "<value>%" when `value` is a bare plain figure
    ("2", "1.5", ".5") under `PERCENT_DEDUCTIBLE_CEILING`, else None. A
    fraction ("1-1/2", "½") is read as before."""
    if value is None or isinstance(value, (bool, list, dict)):
        return None
    s = str(value).strip()
    if not s or not _BARE_FIGURE_RE.fullmatch(s):
        return None
    got = stated_percentage(f"{s}%")
    if got is None or not got["plain"] or not 0 <= got["number"] < PERCENT_DEDUCTIBLE_CEILING:
        return None
    return got


def normalize_general(value: Any) -> str:
    """General fallback for any scalar field with no dedicated normalizer.

    Expands insurance-terminology synonyms (CSL == Combined Single Limit,
    CGL == Commercial General Liability, ...), collapses currency/number
    formatting ($1,000,000 == 1000000 == 1,000,000.00), and strips punctuation.
    """
    if value is None:
        return ""
    s = str(value).lower().replace("&", " and ")
    # Drop currency symbols and thousands separators before synonym expansion.
    s = s.replace("$", " ")
    s = re.sub(r"(?<=\d),(?=\d)", "", s)        # 1,000,000 -> 1000000
    # Replace remaining punctuation with spaces so phrases tokenize cleanly.
    s = re.sub(r"[^a-z0-9.\s]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    for variant, canon in _GENERAL_SYNONYMS_SORTED:
        s = re.sub(rf"\b{re.escape(variant)}\b", canon, s)
    return re.sub(r"\s+", " ", _canonical_figures(s)).strip()


# A DECIMAL POINT IS PART OF ITS NUMBER (22 Oct 2026, Z33-PERCENT review). The
# last of the three rules this replaced was `(\d)\.\b`, which deleted every
# decimal point a DIGIT follows: "2.5" became "25", so "$2.5M" and "$25M",
# "2.5%" and "25%", "1.05" and "105" were one comparison key, and a client's
# "25%" replaced a document's "2.5%" without being held. It never touched the
# point that ends a sentence ("1,000." stayed "1000." against "1000"). Each
# figure is now read whole:
#   * one point between digits is a decimal point: it stays, and insignificant
#     trailing zeros go ("12.50" -> "12.5", "1,000,000.00" -> "1000000",
#     "$1.0M" -> "1m");
#   * two or more points join an identifier's digit groups ("555.123.4567",
#     "1.000.000"): its digits compare (the phone always did; "1.000.000" was
#     cut to "1." by the zero rule);
#   * a point no digit follows ends the sentence ("1,000." -> "1000");
#   * a leading point is a decimal ("$.5M" -> "0.5m").
_DOTTED_DIGITS_RE = re.compile(r"\d+(?:\.\d+)+")


def _canonical_figures(s: str) -> str:
    def _figure(m: "re.Match") -> str:
        whole, *fracs = m.group(0).split(".")
        if len(fracs) > 1:
            return whole + "".join(fracs)
        frac = fracs[0].rstrip("0")
        return f"{whole}.{frac}" if frac else whole
    s = re.sub(r"(?<![a-z0-9.])\.(?=\d)", "0.", s)
    s = _DOTTED_DIGITS_RE.sub(_figure, s)
    return re.sub(r"(\d)\.(?!\d)", r"\1", s)


# ── Dispatcher ────────────────────────────────────────────────────────────────

def _normalize_date_or_general(value: Any) -> str:
    """ISO date when parseable, else the general text normalization.

    Shared by the explicit DATE_FIELDS and any inferred "_date" key so both paths
    behave identically: a real date compares by calendar value, while an
    un-date-like string still compares as text rather than collapsing to ''.
    """
    iso = normalize_date(value)
    # Unparseable dates fall back to general text so two genuinely different
    # un-date-like strings still differ rather than both collapsing to ''.
    return iso if iso is not None else normalize_general(value)


def normalize_value(field: str, value: Any) -> str:
    """Return the canonical COMPARISON string for ``value`` given its fact key.

    Dispatch order: the explicit *_FIELDS sets first (authoritative), then a
    shape-based inference fallback (_infer_field_category) so a secondary or new
    key of a known type is still normalized correctly instead of dropping to the
    generic normalizer. '' means "no usable signal" — the caller treats it as
    absent so a missing/garbage value never manufactures a conflict.
    """
    # 1. Explicit category sets — authoritative; never changes existing behavior.
    if field in NAME_FIELDS:
        return normalize_name(value)
    if field in DATE_FIELDS:
        return _normalize_date_or_general(value)
    if field in ENTITY_TYPE_FIELDS:
        return normalize_entity_type(value)
    if field in ADDRESS_FIELDS:
        return normalize_address(value)
    if field in CARRIER_FIELDS:
        # A rating bureau on a carrier field carries NO signal - "" is what this
        # dispatcher returns for "nothing usable here", and every caller already
        # treats that as absent. So the picker never offers it as a rival
        # carrier and the comparison layer never calls it a conflict.
        if is_insurance_bureau(value):
            return ""
        return normalize_carrier(value)
    if field in FEIN_FIELDS:
        return normalize_fein(value)
    if field in VALUATION_METHOD_FIELDS:
        return normalize_valuation_method(value)
    # 1b. Yes/No (SYS-07). Placed AFTER the explicit identity sets - those are
    #     authoritative and no key belongs to both - and BEFORE the shape
    #     inference and the generic normalizer, which is what used to make
    #     "Yes" and "X" two different comparison keys. A value that is not a
    #     bare Yes/No token ("Yes - see attached") gets no opinion here and
    #     falls through to the ordinary text path exactly as before.
    if is_yes_no_field(field):
        canon = canonical_yes_no(value)
        if canon:
            return canon.lower()
    # 2. Shape-based inference for keys outside the explicit sets (Beta Report §5:
    #    normalization must be generic for any document, not only canonical keys).
    category = _infer_field_category(field)
    if category == "date":
        return _normalize_date_or_general(value)
    if category == "address":
        return normalize_address(value)
    if category == "carrier":
        return normalize_carrier(value)
    if category == "name":
        return normalize_name(value)
    # 3. Generic fallback (insurance synonyms, currency, punctuation).
    return normalize_general(value)


# ── Why two spellings were treated as one value (client UI-04) ───────────────
# The Submission Integrity card tells the broker that two visibly different
# values are the same fact. It could not say WHY, so the claim had to be taken
# on faith. This names the rule.
#
# DERIVED, not a lookup table: the branches below are the SAME dispatch
# `normalize_value` walks to decide the two values are equal, in the same
# order. A new identity key added to any *_FIELDS set, or any key matching
# `_infer_field_category`'s shapes, gets a label for free - which is the point,
# because a hand-maintained table would drift out of step with the comparison
# itself and start naming the wrong rule.

# Plain English, short enough to sit in a pill beside the values. These are
# read by a broker mid-submission, not by an underwriter reading a spec.
_EQUIVALENCE_LABELS = {
    "name":             "Name format",
    "date":             "Date format",
    "address":          "Address format",
    # NOT "Entity type" - that is the row's own label, and a pill repeating it
    # answers nothing (caught auditing the first live run against the client's
    # acceptance criteria). It is also the wrong word: "LLC" and "Limited
    # Liability Company" are not two FORMATS of one string, they are two
    # accepted terms for one thing - the client's own phrasing, "formatting or
    # accepted terminology".
    "entity_type":      "Accepted terminology",
    "carrier":          "Carrier name",
    "fein":             "ID number format",
    "valuation_method": "Valuation term",
    "yes_no":           "Yes / No wording",
    "coverage_line":    "Coverage name",
    "general":          "Wording",
}

# The ONE key whose equivalence is not decided by `normalize_value`.
# `lines_of_business` is compared through `_canon_line_leaf` / `_canon_part_leaf`
# in sqs_service, so it cannot be inferred from the dispatch below and names
# itself here instead. Kept as an explicit, commented exception rather than
# folded into the table above, so it stays obvious that it is one.
_COVERAGE_LINE_FIELDS = frozenset({"lines_of_business", "coverage_lines"})


def equivalence_category(field: str) -> str:
    """Name the normalization rule that lets two spellings of ``field`` agree.

    Returns a short human label ("Date format", "Address format", ...). Never
    returns None or "": an unrecognised key is a real, if generic, answer -
    `normalize_general` genuinely is what compared it - and a blank pill on the
    screen would read as a missing value rather than a broad rule.
    """
    if not field:
        return _EQUIVALENCE_LABELS["general"]
    if field in _COVERAGE_LINE_FIELDS:
        return _EQUIVALENCE_LABELS["coverage_line"]

    # Mirror normalize_value's dispatch order exactly. The explicit sets are
    # authoritative there, so they are authoritative here.
    if field in NAME_FIELDS:
        return _EQUIVALENCE_LABELS["name"]
    if field in DATE_FIELDS:
        return _EQUIVALENCE_LABELS["date"]
    if field in ENTITY_TYPE_FIELDS:
        return _EQUIVALENCE_LABELS["entity_type"]
    if field in ADDRESS_FIELDS:
        return _EQUIVALENCE_LABELS["address"]
    if field in CARRIER_FIELDS:
        return _EQUIVALENCE_LABELS["carrier"]
    if field in FEIN_FIELDS:
        return _EQUIVALENCE_LABELS["fein"]
    if field in VALUATION_METHOD_FIELDS:
        return _EQUIVALENCE_LABELS["valuation_method"]
    if is_yes_no_field(field):
        return _EQUIVALENCE_LABELS["yes_no"]

    inferred = _infer_field_category(field)
    if inferred in _EQUIVALENCE_LABELS:
        return _EQUIVALENCE_LABELS[inferred]
    return _EQUIVALENCE_LABELS["general"]


# ── Strict entity identity (audit 2026-08-15 round 10) ───────────────────────
# The coarse normalizers above are EQUIVALENCE tools: normalize_carrier
# collapses a carrier GROUP's printings to one family token (right for
# document clustering and the foreign-entity drop), normalize_name strips the
# entity suffix (right for matching a suffixless COI mention to the insured).
# Used as the CONFLICT comparator they are blind by construction: EMC Property
# & Casualty vs Employers Mutual Casualty both reduce to "emc", and Orbin
# Contracting LLC vs Orbin Contracting Inc both reduce to "orbin contracting" -
# so the reconciler pronounced the two REAL carriers on the client's package
# consistent and the picker never opened. That is client complaint #2 at its
# root, one layer above every stamping guard.
#
# The strict layer keeps every distinguishing word and canonicalizes only
# SPELLING (Co./Company, Inc/Incorporated, L.L.C./Limited Liability Company).
# Compatibility is token-SUBSET: a truncation ("Travelers" vs "Travelers
# Indemnity Company", a suffixless name vs its suffixed form) is the same
# entity under-specified; two names that EACH carry a word the other lacks
# (Property+Casualty vs Employers+Mutual, LLC vs Inc, Fire vs Casualty) are
# different entities and MUST conflict.
_STRICT_PHRASE_CANON: List[Tuple[str, str]] = [
    ("limited liability company", "llc"),
    ("limited liability co", "llc"),
    ("limited liability corporation", "llc"),
    ("limited partnership", "lp"),
    ("limited liability partnership", "llp"),
    ("professional corporation", "pc"),
]
_STRICT_TOKEN_CANON: Dict[str, str] = {
    "llc": "llc", "pllc": "pllc", "lp": "lp", "llp": "llp", "pc": "pc",
    "ltd": "ltd", "limited": "ltd",
    "inc": "inc", "incorporated": "inc",
    "corp": "corp", "corporation": "corp",
    "co": "company", "cos": "company", "company": "company", "companies": "company",
    "ins": "insurance", "insurance": "insurance",
    "assur": "assurance", "assurance": "assurance",
    "indem": "indemnity", "indemnity": "indemnity",
    "mut": "mutual", "mutual": "mutual",
    "cas": "casualty", "casualty": "casualty",
    "natl": "national", "national": "national",
    "grp": "group", "group": "group",
    # ── Added 2026-08-23. The client's opening paragraph names ABBREVIATIONS
    # as one of the differences that must not become a contradiction, and the
    # table already expanded `cas`/`co`/`mut` but stopped short. Measured on the
    # live package: `EMC Prop & Cas Co` and `EMC Property & Casualty Company`
    # keyed as `emc prop casualty company` vs `emc property casualty company` -
    # two "different entities" over one missing expansion. Same for
    # `Travelers Prop Cas Co of Am` vs `...Company of America`.
    #
    # THESE CANNOT FOLD TWO REAL CARRIERS. Every entry expands a CORPORATE-FORM
    # or GEOGRAPHIC word, never the distinguishing name: `EMC Property &
    # Casualty` and `Employers Mutual Casualty` still differ on `emc` vs
    # `employers mutual`, which is Round 10 fix 46 and is pinned by test.
    "prop": "property", "property": "property",
    "amer": "america", "am": "america", "america": "america",
    "american": "america",          # the qualifier, not a distinguishing name
    "intl": "international", "international": "international",
    "gen": "general", "general": "general",
    "assn": "association", "association": "association",
    "fin": "financial", "financial": "financial",
    "svc": "services", "svcs": "services", "serv": "services",
    "services": "services", "service": "services",
    "guar": "guaranty", "guaranty": "guaranty",
    "exch": "exchange", "exchange": "exchange",
    "reins": "reinsurance", "reinsurance": "reinsurance",
    "agcy": "agency", "agency": "agency",
    "underwrs": "underwriters", "underwriters": "underwriters",
}
_STRICT_NOISE_TOKENS = frozenset({"the", "of", "and", "a", "an"})


def _strict_entity_tokens(value: Any) -> FrozenSet[str]:
    # De-glued first: an OCR printing with its spaces lost must tokenise like
    # the spaced one, or every subset test below calls one company two.
    s = _basic(deglue_entity_text(value))
    if not s:
        return frozenset()
    for phrase, canon in _STRICT_PHRASE_CANON:
        s = re.sub(rf"\b{re.escape(phrase)}\b", canon, s)
    return frozenset(
        _STRICT_TOKEN_CANON.get(t, t)
        for t in s.split() if t not in _STRICT_NOISE_TOKENS)


def strict_entity_key(value: Any) -> str:
    """Spelling-canonical, distinction-preserving comparison key for a legal
    entity name (person, organization, or carrier).

    OCR glue is undone first (`deglue_entity_text`), so the certificate's
    "EmployersMutualCasualtyCo." keys exactly like the declarations'
    "EMPLOYERS MUTUAL CASUALTY COMPANY". Spaced input is untouched by that
    step, so every existing key is unchanged."""
    s = _basic(deglue_entity_text(value))
    if not s:
        return ""
    for phrase, canon in _STRICT_PHRASE_CANON:
        s = re.sub(rf"\b{re.escape(phrase)}\b", canon, s)
    out = [_STRICT_TOKEN_CANON.get(t, t)
           for t in s.split() if t not in _STRICT_NOISE_TOKENS]
    return " ".join(out)


def entity_identity_conflict(raw_values: List[Any]) -> bool:
    """True when two values name MATERIALLY different legal entities.

    Token-subset compatibility: equal sets, or one a subset of the other
    (truncation / missing suffix), are the same entity. Each carrying a token
    the other lacks is a real disagreement the review picker must surface.
    Two printings with one compact key (the same name, spaces lost) never
    conflict - an all-caps glued OCR token has no boundary to tokenise on.
    """
    vals = [v for v in raw_values if _strict_entity_tokens(v)]
    keys = [_strict_entity_tokens(v) for v in vals]
    compact = [entity_compact_key(v) for v in vals]
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            a, b = keys[i], keys[j]
            if compact[i] and compact[i] == compact[j]:
                continue
            if not (a <= b or b <= a):
                return True
    return False


def distinct_normalized(field: str, raw_values: List[Any]) -> Set[str]:
    """Set of non-empty normalized comparison keys for ``raw_values``.

    ``len(...) > 1`` means the values MATERIALLY differ after normalization and
    a conflict is warranted; ``<= 1`` means they are equivalent (formatting-only
    difference) and no conflict should be raised.
    """
    return {n for v in raw_values if (n := normalize_value(field, v))}


# ── WHO a no-loss statement is about (5 Oct 2026, CH125 6eda3069) ───────────
# Every no-loss phrase in the kit was SCOPED - "Umbrella - no known losses",
# "the umbrella has never had a claim (no known losses)", "Property - no
# losses in the past 3 years", and loss-run rows "2019-20 VFM-CPP-7781203 ...
# no losses" - while the claims sat on Auto and Property. The flag read them as
# an account-wide attestation and held Loss History at 45. The clause BEFORE the
# phrase (back to the line start or the previous sentence) decides:
#   * a policy number or a policy-year range -> "term" (a loss-run row; the
#     loss run is the verified history it belongs to, never its rival);
#   * a coverage line it names -> "line", with any "past / last N years";
#   * neither -> "account" (today's attestation).
_NO_LOSS_POLICY_RE = re.compile(
    r"\b(?:19|20)\d{2}\s*[-/]\s*(?:19|20)?\d{2}\b|\b[A-Z]{2,}[A-Z0-9-]*\d{4,}", re.I)
# A statement about ONE term in the words that follow it (Michelle review, 29
# Oct 2026): a carrier loss run prints "NO LOSSES REPORTED FOR THIS POLICY TERM
# AS OF THE VALUATION DATE" under each clean term, and the statement starts its
# line, so the policy number above it is not in its clause. Read as an account
# attestation it "conflicted" with the claims of the other terms and held Loss
# History at 45 on an ordinary multi-year loss run.
_NO_LOSS_THIS_TERM_RE = re.compile(
    r"\b(?:this|that|the\s+above|each)\s+(?:policy\s+)?(?:term|period|policy\s+year|policy)\b",
    re.I)
_NO_LOSS_YEARS_RE = re.compile(
    r"\b(?:past|last|prior|previous)\s+(\d{1,2}|one|two|three|four|five|six|seven|ten)\s+years?\b",
    re.I)
_NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
                 "seven": 7, "ten": 10}


def no_loss_statements(text: str) -> List[dict]:
    """Every no-loss assertion `detect_no_loss_assertion` would accept, with its
    scope: {"phrase", "scope": "account"|"line"|"term", "line", "years"}."""
    out: List[dict] = []
    if not text:
        return out
    try:
        from services.lob_canon import canon_line
    except Exception:                                          # noqa: BLE001
        canon_line = lambda _t: None                          # noqa: E731
    lowered = text.lower()
    seen: set = set()
    for phrase in _NO_LOSS_PHRASES:
        start = 0
        while True:
            idx = lowered.find(phrase, start)
            if idx == -1:
                break
            start = idx + len(phrase)
            if idx in seen:
                continue
            after = lowered[idx + len(phrase): idx + len(phrase) + _LOSS_CLAUSE_WINDOW]
            for _brk in _LOSS_CLAUSE_BREAK:
                _cut = after.find(_brk)
                if _cut >= 0:
                    after = after[:_cut]
            tail = after[:24].lstrip()
            if (_tail_is_a_threshold(tail) or _tail_introduces_an_exception(after)
                    or _clause_states_a_loss(lowered, idx)):
                continue
            seen.add(idx)
            head = text[max(0, idx - 160):idx]
            cut = max(head.rfind("\n"), head.rfind(". "), head.rfind("; "))
            clause = head[cut + 1:] if cut >= 0 else head
            years_m = _NO_LOSS_YEARS_RE.search(after) or _NO_LOSS_YEARS_RE.search(clause)
            years = None
            if years_m:
                raw = years_m.group(1).lower()
                years = int(raw) if raw.isdigit() else _NUMBER_WORDS.get(raw)
            line = canon_line(clause)
            if _NO_LOSS_POLICY_RE.search(clause) or _NO_LOSS_THIS_TERM_RE.search(after):
                scope = "term"
            elif line:
                scope = "line"
            else:
                scope = "account"
            out.append({"phrase": phrase, "scope": scope, "line": line, "years": years,
                        "at": idx})
    return out


def values_conflict(field: str, raw_values: List[Any]) -> bool:
    """True when ``raw_values`` materially differ after normalization."""
    return len(distinct_normalized(field, raw_values)) > 1


# ── Loss-history no-loss assertion detector ───────────────────────────────────
# Single source of truth shared by extraction_pipeline.py (drives the
# narrative_states_no_losses flag that feeds SQS scoring) and pdf_service.py
# (drives the LossHistory_NoPriorLossesIndicator_A "Check if none" checkbox).
# Previously these were two independent detectors: the SQS side used this
# phrase scan, the PDF checkbox was decided by a separate, unrelated GPT
# per-field judgment call - so the checkbox could come back "Yes" (checked,
# reads as confirmed) while the SQS panel simultaneously called the exact same
# submission "an assertion, weaker than an attestation, please confirm". Both
# surfaces now call this one function, so they can no longer disagree.
_NO_LOSS_PHRASES = (
    "no prior losses", "no losses", "no prior claims", "no claims",
    # "no known losses" is the single most common industry phrasing and is NOT
    # a superset of "no losses" (the word "known" sits between them), so it
    # must be listed explicitly. Same for the "reported"/"free" variants.
    "no known losses", "no known claims",
    "no reported losses", "no reported claims",
    "loss-free", "loss free", "claims-free", "claims free",
    "clean loss history", "favorable loss history", "clean loss record",
)
# Standard ACORD/loss-run boilerplate reads "...no claims exceeding $10,000"
# and real loss-run summaries say "no losses exceed $10,000" / "no losses over
# $X" - a THRESHOLD statement (losses exist, none cross the cap), not a
# zero-loss assertion. A bare substring match on "no losses" misreads that as
# a no-loss assertion even when real claims are attached. Skip a phrase hit
# when immediately followed by a threshold qualifier.
_NO_LOSS_QUALIFIERS = (
    "exceed", "exceeding", "over", "above", "in excess", "greater than", "more than",
)


# A qualifier only makes a THRESHOLD when an AMOUNT follows it.
#
# LIVE 2026-09-08. "over" was listed to catch "no losses over $10,000", but it
# matched on the next 20 characters with nothing checking that a figure came
# next - so the far more common TIME phrasing
#
#     "No losses over the past five years"
#
# was read as a threshold and `detect_no_loss_assertion` returned False. That is
# a producer's genuine attestation being discarded. It surfaced the moment
# `pdf_service._attests_no_loss` began delegating here: the ACORD 125
# "Check if none" box went from ticked to printing an explicit **No** - a signed
# form asserting the opposite of what the producer typed.
#
# The distinction is what follows the qualifier: a threshold names a SUM, a time
# phrase names a PERIOD. "greater than" / "in excess" are kept unconditional -
# they are never used to introduce a time span in this vocabulary.
_AMOUNT_AFTER_QUALIFIER_RE = re.compile(r"^[\s:$£€]*\d")
_TIME_QUALIFIERS = frozenset({"over", "above", "more than"})


# A NO-LOSS CLAIM THAT CARRIES A LOSS AMOUNT CONTRADICTS ITSELF.
#
# The phrase scan reads the first few words and stops, so
#
#     "Clean loss history apart from a $40,000 fire in 2023"
#
# returned True - the $40,000 fire, the entire point of the sentence, was never
# read. It scored the account 60 ("attested no losses"), and once
# `pdf_service._attests_no_loss` began delegating here it also TICKED the ACORD
# 125 "Check if none" box: a signed form asserting no losses on an account with
# a fire.
#
# WHY THIS IS A MONEY TEST AND NOT A LIST OF EXCEPTION WORDS. "apart from",
# "except", "other than", "aside from", "but for", "save for", "excluding" ...
# is an open set, and an open set is the allow-list this project's quality bar
# forbids - you are always one phrasing behind. A NON-ZERO AMOUNT is structural:
# a genuine no-loss statement never needs one, and a loss worth excepting almost
# always carries its number. Peril words ("fire", "accident") were tried and
# REJECTED - they co-occur with the negation itself ("no claims or accidents in
# the past 5 years"), so they refuse genuine attestations.
#
# SCOPED TO THE PHRASE'S OWN CLAUSE. Scanning the document would refuse every
# no-loss sentence on every dec page, since dec pages are made of dollar amounts.
#
# ZERO IS EXEMPT: "no losses, total incurred $0" is a no-loss statement stating
# its own zero, and blanking that would be the opposite of the intent.
#
# HONEST LIMIT: "clean loss history apart from one fire" carries no figure and
# still reads as an attestation. That is not covered, and no rule of this shape
# will cover it. The guarantee is the FAILURE DIRECTION - what this does catch
# resolves to blank-and-ask, never to a false "yes" on a signed form.
_LOSS_CLAUSE_BREAK = ".;!?\n\r"
_LOSS_CLAUSE_WINDOW = 200
_NONZERO_AMOUNT_RE = re.compile(
    r"(?:[$£€]\s?|\b)(?!0+(?:[.,]0+)*\b)\d[\d,]*(?:\.\d+)?\s*(?:k\b|m\b|dollars\b)?"
)
_MONEY_SHAPE_RE = re.compile(r"[$£€]\s?\d|\d[\d,]*\d\s*dollars\b|\b\d{1,3}(?:,\d{3})+\b")


# AN EXCEPTION HAS A GRAMMAR, AND THAT GRAMMAR IS A CLOSED CLASS.
#
# The money rule above catches an exception that names a figure. It does not
# catch "clean loss history apart from ONE FIRE" - no amount, so nothing
# contradicts the phrase, and it attests.
#
# THE CORRECTION THAT MADE THIS FIXABLE. This was first written off as
# unfixable, on the grounds that exception wording is infinite. It is not. What
# is infinite is the LOSS - "a fire", "the slip and fall", "that thing with the
# forklift" - which is why no list of PERILS can work and why the money rule
# names none. But the words that JOIN "everything clean" to "this one thing" are
# a closed grammatical class: exceptive prepositions and conjunctions. English
# has roughly fifteen and coins no more, the way it coins nouns.
#
# So the two rules split the space by what each can bound:
#   * an exception carrying a FIGURE      -> the money rule, no vocabulary at all
#   * an exception carrying no figure     -> this rule, a closed function-word set
#
# NEITHER touches a coordination inside the negation's own scope - "no claims OR
# ACCIDENTS in the past 5 years" has no amount and no exceptive, so it still
# attests. That case is what killed the peril-word approach and it is the
# control for this one.
#
# TAIL ONLY, deliberately. A leading exceptive ("Other than the fire, clean loss
# history") is not caught: checking the head would refuse legitimate preambles
# like "Per our review of the loss runs, no known losses". Rarer shape, and the
# money rule still covers it whenever a figure appears. Recorded, not hidden.
_EXCEPTIVE_MARKERS = (
    "except", "excepting", "excluding", "exclusive of",
    "apart from", "aside from", "other than", "otherwise than",
    "besides", "barring", "save for", "save that", "but for",
    "with the exception", "outside of", "notwithstanding",
    "aside of", "bar for",
)


def _tail_introduces_an_exception(tail: str) -> bool:
    """Does the text after a no-loss phrase carve something out of it?"""
    return any(m in tail for m in _EXCEPTIVE_MARKERS)


def _clause_states_a_loss(lowered: str, idx: int) -> bool:
    """Does the clause holding this no-loss phrase also state a loss amount?"""
    lo = max(0, idx - _LOSS_CLAUSE_WINDOW)
    clause = lowered[lo: idx + _LOSS_CLAUSE_WINDOW]
    for ch in _LOSS_CLAUSE_BREAK:
        cut = clause.rfind(ch, 0, idx - lo)
        if cut >= 0:
            clause = clause[cut + 1:]
            idx = idx - lo - cut - 1
            lo = 0
    for ch in _LOSS_CLAUSE_BREAK:
        cut = clause.find(ch, max(0, idx))
        if cut >= 0:
            clause = clause[:cut]
    for m in _MONEY_SHAPE_RE.finditer(clause):
        digits = re.sub(r"[^\d]", "", m.group())
        if digits and int(digits) > 0:
            return True
    return False


def _tail_is_a_threshold(tail: str) -> bool:
    """Does the text right after a no-loss phrase qualify it into a threshold?"""
    for q in _NO_LOSS_QUALIFIERS:
        if not tail.startswith(q):
            continue
        if q in _TIME_QUALIFIERS:
            # Ambiguous word - only a figure makes it a threshold.
            return bool(_AMOUNT_AFTER_QUALIFIER_RE.match(tail[len(q):]))
        return True
    return False


def detect_no_loss_assertion(text: str) -> bool:
    """True if ``text`` contains an unqualified "no losses/claims" assertion.

    Case-insensitive substring scan for common industry no-loss phrasing,
    guarded against threshold statements ("no losses exceed $10,000") that
    read as a match but actually mean the opposite (losses exist, capped).
    """
    if not text:
        return False
    lowered = text.lower()
    for phrase in _NO_LOSS_PHRASES:
        start = 0
        while True:
            idx = lowered.find(phrase, start)
            if idx == -1:
                break
            after = lowered[idx + len(phrase): idx + len(phrase) + _LOSS_CLAUSE_WINDOW]
            for _brk in _LOSS_CLAUSE_BREAK:
                _cut = after.find(_brk)
                if _cut >= 0:
                    after = after[:_cut]
            tail = after[:24].lstrip()
            if (not _tail_is_a_threshold(tail)
                    and not _tail_introduces_an_exception(after)
                    and not _clause_states_a_loss(lowered, idx)):
                return True
            start = idx + len(phrase)
    return False
