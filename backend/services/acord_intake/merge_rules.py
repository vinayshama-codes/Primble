"""Who owns a fact when a package holds filled ACORD forms AND declarations.

Owner's rules (27 Oct 2026, to be confirmed by Brent - see ACORD_INTAKE.md):
  * the APPLICANT and the SUBMISSION - what the producer states - are the ACORD
    form's: name, FEIN, entity type, addresses, contacts, operations, codes,
    years in business, employees, revenue, the proposed term, new or renewal,
    the lines applied for, the remarks. A dec corroborates; a real difference
    still shows as a Data Consistency card (the per-document copies are kept).
  * the CURRENT POLICIES - what a policy states - are the declarations':
    carrier, NAIC, policy number, limits, deductibles, premiums. An ACORD's
    value there is corroboration and never outvotes a dec.
  * a PERSON's answer beats both (never touched here).
  * a PRIOR-YEAR ACORD (its proposed term ended or began over 30 days ago) gives
    the applicant's identity only - never this year's term, lines or remarks.
One table, so a rule Brent changes is a one-line change.
"""
import datetime
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

from services.fact_state import ACORD_BOX_SOURCE as ACORD_SOURCE  # noqa: E402 - one spelling

APPLICANT_FACTS = frozenset({
    "applicant_name", "dba_name", "fein", "entity_type", "mailing_address", "physical_address",
    "contact_name", "contact_phone", "contact_email", "applicant_business_phone", "applicant_website",
    "operations_description",
    "naics_code", "sic_code", "business_start_date", "years_in_business", "num_employees",
    "num_employees_full_time", "num_employees_part_time", "total_revenue", "annual_revenue",
    "applicant_member_manager_count", "state_of_operations",
})
SUBMISSION_FACTS = frozenset({
    "effective_date", "expiration_date", "is_renewal", "submission_is_new_business",
    "submission_carrier_name", "lines_of_business", "billing_plan", "audit_period",
    "additional_remarks_text",
})
ACORD_OWNED = APPLICANT_FACTS | SUBMISSION_FACTS
_PRIOR_YEAR_DAYS = 30


def is_acord_doc(d: Any) -> bool:
    return isinstance(d, dict) and bool((d.get("acord") or {}).get("forms"))


def _fv(x: Any) -> Any:
    return x.get("value") if isinstance(x, dict) and "value" in x else x


def _empty(x: Any) -> bool:
    v = _fv(x)
    return v is None or (isinstance(v, (str, list, dict)) and not v)


def _agrees(key: str, a: Any, b: Any) -> bool:
    """The one comparison door (`fact_comparison.values_agree`)."""
    try:
        from services.acord_intake.primble_record import _same_value
        return bool(_same_value(key, _fv(a), _fv(b)))
    except Exception:                                          # noqa: BLE001
        return _fv(a) == _fv(b)


def _by_person(x: Any) -> bool:
    """The ONE door (`fact_state.put_by_person`) - no second vocabulary here."""
    if not isinstance(x, dict):
        return False
    from services.fact_state import put_by_person
    return bool(put_by_person(x))


# A record's term with no readable expiration ends one policy year (plus a
# margin for a short-rate or extended term) after it began.
_OWN_TERM_MAX_DAYS = 400

def _restored(d: Any) -> dict:
    """The document's restored payload, opened (`primble_record.restored_of` -
    sealed at rest since the production review, 29 Oct 2026)."""
    from services.acord_intake.primble_record import restored_of
    return restored_of(d)


def is_prior_application(d: dict, today: Optional[datetime.date] = None, own_record: bool = False) -> bool:
    """An ACORD whose proposed term began more than 30 days ago (or ended) was
    written for an earlier term.

    `own_record` - the form carries Primble's authenticated record: it is prior ONLY
    when its term has ENDED (owner, 29 Oct 2026). The 30-day rule judged our own
    download "last year's application" a month after its effective date, so the
    same files that restored every answer on day 1 restored none from day 31
    (Choice Electric's 01/01/2027 term: 100 today, far lower from 1 Feb 2027) -
    while the policy those answers describe is still in force."""
    try:
        from services.normalization import normalize_date
        eff = normalize_date(str(_fv((d.get("facts") or {}).get("effective_date")) or ""))
        exp = normalize_date(str(_fv((d.get("facts") or {}).get("expiration_date")) or ""))
        today = today or datetime.date.today()
        if exp and datetime.date.fromisoformat(exp) <= today:
            return True
        if own_record:
            # No readable end (a blanked or mistyped expiration box): one policy
            # term from its start, with a margin, is the end - an old record must
            # not restore last term's answers as a person's (production review,
            # 29 Oct 2026: a 2023 form with no expiration restored its FEIN and
            # revenue). No start either: nothing to judge, as before.
            if not exp and eff:
                return (today - datetime.date.fromisoformat(eff)).days > _OWN_TERM_MAX_DAYS
            return False
        return bool(eff) and (today - datetime.date.fromisoformat(eff)).days > _PRIOR_YEAR_DAYS
    except Exception:                                          # noqa: BLE001
        return False


def is_application_doc(d: Any) -> bool:
    """An ACORD document holding an APPLICATION form - what the producer states.
    A certificate (ACORD 25 / 28) is a carrier's or an agent's proof of the
    EXISTING policies, often of another party (a subcontractor), never the
    applicant's own statement - it owns nothing here (review, 27 Oct 2026: a
    certificate's "description of operations" replaced the applicant's)."""
    if not is_acord_doc(d):
        return False
    try:
        from services.acord_intake.reverse_map import CERTIFICATE_FORMS, _base
    except Exception:                                          # noqa: BLE001
        CERTIFICATE_FORMS, _base = frozenset({"ACORD_25", "ACORD_28"}), (lambda x: x)
    return any(_base(str((c or {}).get("form_id") or "")) not in CERTIFICATE_FORMS
               for c in (d.get("acord") or {}).get("forms") or [])


# What a PRIOR-YEAR application may still say: who the applicant IS. Never what
# it was that year (revenue, employees, the term, the lines, the remarks).
PRIOR_IDENTITY_FACTS = frozenset({
    "applicant_name", "dba_name", "fein", "entity_type", "mailing_address", "physical_address",
    "applicant_website", "naics_code", "sic_code", "business_start_date",
})


def names_this_insured(app: dict, others: List[dict]) -> bool:
    """Does this application name the insured the other documents name? Read
    the way Submission Integrity reads it - the door that asks the producer when
    it does not (`submission_integrity._names_match`: a loss run's "Choice Elec.
    LLC", "The Choice Electric Company", a missing or other legal form are one
    insured), plus the application's own DBA and the FEIN. Positive evidence
    only: an application naming nobody, or other documents naming nobody (a
    heading read as the insured is nobody - `normalization.is_not_a_party_name`),
    keeps its ownership. One other document naming it is enough (re-review,
    27 Oct 2026: the strict legal-entity test handed a loss run's abbreviation
    the proposed term)."""
    try:
        from services.normalization import is_not_a_party_name, same_entity_name
        from services.submission_integrity import _names_match, _normalize_fein, _normalize_name
    except Exception:                                          # noqa: BLE001
        return True

    def _party(v):
        s = str(_fv(v) or "").strip()
        return s if s and not is_not_a_party_name(s) else ""

    f = app.get("facts") or {}
    raw_mine = [n for n in (_party(f.get("applicant_name")), _party(f.get("dba_name"))) if n]
    mine = [n for n in (_normalize_name(x) for x in raw_mine) if n]
    my_fein = _normalize_fein(_fv(f.get("fein")))
    if not mine:
        return True
    named = False
    for d in others:
        of = d.get("facts") or {}
        raw_theirs = [n for n in (_party(of.get("applicant_name")), _party(of.get("dba_name"))) if n]
        theirs = [n for n in (_normalize_name(x) for x in raw_theirs) if n]
        their_fein = _normalize_fein(_fv(of.get("fein")))
        if not theirs and not their_fein:
            continue
        named = True
        if (my_fein and their_fein and my_fein == their_fein) or any(
                _names_match(a, b) for a in mine for b in theirs) or any(
                same_entity_name(a, b) for a in raw_mine for b in raw_theirs):
            return True
    return not named


# The term the application REPLACES is the current policies' own, and it is
# the prior term - the one the loss window counts back from and the 125's
# prior-carrier grid sits under. Without an application the renewal router
# moves it (`extraction_service._route_renewal_dates`); with one, the owner rule
# below sets the proposed term first and the router never sees the declarations'
# term, so it was simply lost (round trip, 27 Oct 2026: no prior term, the loss
# window counted back from today and four of the five years of runs were
# credited). Kept as a PAIR, only when both prior slots are empty, only when it
# ends on or before the proposal and no more than one term before it.
_ONE_TERM_DAYS = 400


def _keep_displaced_current_term(merged: Dict[str, Any], displaced: Dict[str, Any]) -> List[str]:
    try:
        from services.normalization import normalize_date

        def _d(v):
            iso = normalize_date(str(_fv(v) or ""))
            return datetime.date.fromisoformat(iso) if iso else None
        old_eff, old_exp = _d(displaced.get("effective_date")), _d(displaced.get("expiration_date"))
        new_eff = _d(merged.get("effective_date"))
        if not (old_eff and old_exp and new_eff) or old_exp <= old_eff:
            return []
        if (old_eff, old_exp) == (new_eff, _d(merged.get("expiration_date"))):
            return []
        if not (old_exp <= new_eff and (new_eff - old_exp).days <= _ONE_TERM_DAYS):
            return []
        if not (_empty(merged.get("prior_effective_date")) and _empty(merged.get("prior_expiration_date"))):
            return []
        from services.extraction_service import _move_current_term_to_prior
        tmp = dict(displaced)
        _move_current_term_to_prior(tmp)
        out = []
        for k in ("prior_effective_date", "prior_expiration_date"):
            if not _empty(tmp.get(k)):
                merged[k] = tmp[k]
                out.append(k)
        if out:
            # The router's own marker for "the current term moved; the proposal
            # is the application's": section forms print the proposed term, a
            # certificate the moved one (`pdf_service._resolve_renewal_proposed_
            # period`). Without it the round trip's 126 / 127 / 130 / 131 printed
            # the declarations' 01/01/2025 over the 125's proposed 01/01/2027.
            merged["renewal_dates_routed"] = True
            out.append("renewal_dates_routed")
        return out
    except Exception as ex:                                    # noqa: BLE001
        logger.warning("acord merge rules: displaced term not kept: %s", ex)
        return []


def _prior_term_from_grid(merged: Dict[str, Any], apps: List[dict]) -> List[str]:
    """No declarations (forms only): the application's own PRIOR CARRIER grid
    states the prior term - its latest year, when every row of that year prints
    the same term and it ends on or before the proposal, within one term."""
    try:
        if not (_empty(merged.get("prior_effective_date")) and _empty(merged.get("prior_expiration_date"))):
            return []
        from services.normalization import normalize_date

        def _d(v):
            iso = normalize_date(str(_fv(v) or ""))
            return datetime.date.fromisoformat(iso) if iso else None
        new_eff = _d(merged.get("effective_date"))
        if not new_eff:
            return []
        terms = set()
        for d in apps:
            rows = _fv((d.get("facts") or {}).get("prior_coverage_by_line"))
            for r in rows if isinstance(rows, list) else []:
                if not isinstance(r, dict):
                    continue
                eff, exp = _d(r.get("effective") or r.get("effective_date")), _d(r.get("expiration") or r.get("expiration_date"))
                if eff and exp and eff < exp <= new_eff and (new_eff - exp).days <= _ONE_TERM_DAYS:
                    terms.add((eff, exp))
        if not terms:
            return []
        latest = max(t[1] for t in terms)
        effs = {t[0] for t in terms if t[1] == latest}
        if len(effs) != 1:
            return []                    # two terms end that day: no reading
        (eff,) = effs
        for k, v in (("prior_effective_date", eff), ("prior_expiration_date", latest)):
            merged[k] = {"value": v.strftime("%m/%d/%Y"), "source": ACORD_SOURCE,
                         "confidence": "acord_exact", "derivation": {"rule": "acord_prior_carrier_grid"}}
        out = ["prior_effective_date", "prior_expiration_date"]
        # The current policies' term is the prior one and the proposal is the
        # application's: the router's marker, so the section forms print the
        # proposed term rather than their line rows' 2025 dates (B1, 27 Oct).
        merged["renewal_dates_routed"] = True
        out.append("renewal_dates_routed")
        # The grid NAMES that term's carriers: the prior carrier, in the shape
        # the declarations' derivation gives it (each legal entity once, most
        # lines first, at most three - `extraction_service._derive_prior_carrier`).
        if _empty(merged.get("prior_carrier")):
            try:
                from services.normalization import strict_entity_key as _key
            except Exception:                                  # noqa: BLE001
                _key = _norm
            counts: Dict[str, int] = {}
            printing: Dict[str, str] = {}
            for d in apps:
                rows = _fv((d.get("facts") or {}).get("prior_coverage_by_line"))
                for r in rows if isinstance(rows, list) else []:
                    if not isinstance(r, dict) or _d(r.get("expiration") or r.get("expiration_date")) != latest:
                        continue
                    name = str(r.get("carrier") or "").strip()
                    k = _key(name)
                    if k:
                        printing.setdefault(k, name)
                        counts[k] = counts.get(k, 0) + 1
            if counts:
                ranked = sorted(printing, key=lambda k: (-counts[k], list(printing).index(k)))
                merged["prior_carrier"] = {"value": " / ".join(printing[k] for k in ranked[:3]),
                                           "source": ACORD_SOURCE, "confidence": "acord_exact",
                                           "derivation": {"rule": "acord_prior_carrier_grid"}}
                out.append("prior_carrier")
        return out
    except Exception as ex:                                    # noqa: BLE001
        logger.warning("acord merge rules: prior term from the grid skipped: %s", ex)
        return []


def identity_witnesses(active: List[dict]) -> List[dict]:
    """The documents that say WHO the insured is, independently of the ACORD
    forms: never another ACORD form (an application, a certificate) and never
    our SQS summary. Choice Electric's own forms uploaded beside ORBIN's
    declarations restored 23 Choice Electric person answers and took over the
    applicant's identity: the set's ACORD 28 certificate (not an application)
    was the "other document" that vouched for its ACORD 125 - one set of forms
    witnessing itself (review, 28 Oct 2026)."""
    return [d for d in active if isinstance(d, dict) and not is_acord_doc(d) and not is_summary_doc(d)]


def restoring_docs(docs: List[dict]) -> List[dict]:
    """The ACORD documents whose Primble record speaks for THIS package: active
    application forms naming the insured the other documents name - the same
    test that lets an application own the applicant's facts (`names_this_insured`).
    The record names the insured its FORM names (`primble_record._same_insured`),
    which says nothing about the package around it: Choice Electric's forms
    uploaded beside Harborline's declarations restored Choice Electric's typed
    revenue as a PERSON's answer over Harborline's documented $900,000 - a
    person's answer beats every document and `insured_scope` never scopes it
    (review, 27 Oct 2026). Last year's application restores nothing either
    (`primble_record.apply` returns none for it)."""
    active = [d for d in docs or [] if isinstance(d, dict) and not d.get("excluded")]
    others = identity_witnesses(active)
    out = [d for d in active if is_application_doc(d) and names_this_insured(d, others)]
    # Primble's SQS summary (the cover page) names its insured in its record,
    # never on a box: it speaks for the package only when it NAMES one and the
    # other documents name that insured too (or name nobody).
    for d in active:
        if not is_summary_doc(d):
            continue
        who = str((_restored(d).get("applicant")) or "").strip()
        if who and names_this_insured({"facts": {"applicant_name": who}}, others):
            out.append(d)
    return out


def is_summary_doc(d: Any) -> bool:
    """Primble's own SQS summary re-uploaded with its record
    (`intake._summary_result`)."""
    return isinstance(d, dict) and bool((d.get("acord") or {}).get("primble_summary"))


def _restored_answers(docs: List[dict]):
    """({fact: envelope}, {facts two forms restore differently}) over the
    records that speak for the package."""
    answers: Dict[str, Any] = {}
    split: set = set()
    for d in restoring_docs(docs):
        got = _restored(d)
        for k, env in (got.get("answers") or {}).items():
            if k in answers and _fv(answers[k]) != _fv(env):
                split.add(k)
            answers.setdefault(k, env)
        split.update(_edited_answers(d))
    return answers, split


def _edited_answers(d: dict) -> set:
    """The answers whose box on THIS form was changed by hand after download
    (`primble_record.apply` -> "edited"): the form's new word is the package's,
    so no form's record restores the old answer over it (29 Oct 2026, review)."""
    return set((_restored(d).get("edited")) or [])


def apply_restored_answers(merged: Dict[str, Any], docs: List[dict]) -> List[str]:
    """A Primble record's person answers and saved tables (`primble_record.apply`,
    held on the document's ACORD record) become the PACKAGE's - a person's
    answer, as it was on the package that printed the form, never a document's
    printing. Two forms restoring different values for one answer restore
    neither (blank over wrong - the person is asked again). Only the records
    that speak for this package (`restoring_docs`)."""
    answers: Dict[str, Any] = {}
    tables: Dict[str, dict] = {}
    stores: Dict[str, Any] = {}
    split: set = set()
    for d in restoring_docs(docs):
        got = _restored(d)
        for k, env in (got.get("answers") or {}).items():
            if k in answers and _fv(answers[k]) != _fv(env):
                split.add(k)
            answers.setdefault(k, env)
        # a box edited by hand after download: the form's word, no stale restore
        split.update(_edited_answers(d))
        for k, t in (got.get("tables") or {}).items():
            if k in tables and tables[k].get("rows") != t.get("rows"):
                split.add(k)
            tables.setdefault(k, t)
        for k, v in (got.get("stores") or {}).items():
            if k in stores and stores[k] != v:
                split.add(k)
            stores.setdefault(k, v)
    moved: List[str] = []
    # Primble's own SQS summary names the insured and the proposed term it was
    # scored on: they fill a GAP the uploaded documents leave (a cover alone),
    # never over a document's statement.
    for d in restoring_docs(docs):
        if not is_summary_doc(d):
            continue
        got = _restored(d)
        restated = {"applicant_name": got.get("applicant")}
        restated.update(got.get("term") or {})
        for k, v in restated.items():
            if v and _empty(merged.get(k)):
                merged[k] = {"value": str(v), "source": ACORD_SOURCE, "confidence": "acord_exact",
                             "restored_from": "primble_record"}
                moved.append(k)
    # A person's STORES (the Policies table's edits - `primble_record.
    # _person_stores`): the pipeline re-applies them over the documents
    # (`policy_lines.carry_and_apply`), and a store the session already holds
    # always wins there - a correction made after the re-upload is never
    # overwritten by the old record.
    import copy as _copy
    for k, v in stores.items():
        if k not in split and not merged.get(k):
            merged[k] = _copy.deepcopy(v)
            moved.append(k)
    for k, env in answers.items():
        if k not in split and not _by_person(merged.get(k)):
            merged[k] = dict(env)
            moved.append(k)
    if tables:
        try:
            from services.schedule_capture import mark_human_rows
        except Exception:                                      # noqa: BLE001
            mark_human_rows = None
        for k, t in tables.items():
            if k in split or not isinstance(t.get("rows"), list):
                continue
            merged[k] = [dict(r) if isinstance(r, dict) else r for r in t["rows"]]
            if mark_human_rows:
                mark_human_rows(merged, k, t.get("saved_by") or "producer")
            moved.append(k)
            if k == "property_locations":
                # A saved location table writes the package COPE facts from its
                # rows (`premises_cope.derive_package_cope`) - the save did, so
                # the restore does: the cover-only round trip restored the table
                # and lost its construction type, a Minimum Viable COPE hard stop
                # (27 Oct 2026).
                try:
                    from services.premises_cope import derive_package_cope
                    derive_package_cope(merged, source=t.get("saved_by") or "producer")
                except Exception as ex:                        # noqa: BLE001
                    logger.warning("acord merge rules: restored table COPE skipped: %s", ex)
    if split:
        logger.info("acord merge rules: forms restore different answers for %s - none kept", sorted(split))
    return moved


def restored_confirmations(docs: List[dict]) -> Dict[str, Any]:
    """The Data Consistency picks (`underwriting_confirmations`) the records that
    speak for this package carry. Two records picking differently for one key
    restore neither (blank over wrong - the person picks again)."""
    out: Dict[str, Any] = {}
    split: set = set()
    for d in restoring_docs(docs):
        for k, v in ((_restored(d).get("confirmations")) or {}).items():
            if v is None:
                continue
            if k in out and out[k] != v:
                split.add(k)
            out.setdefault(k, v)
    return {k: v for k, v in out.items() if k not in split}


def apply_restored_flags(flags: Dict[str, Any], docs: List[dict]) -> List[str]:
    """The package flags the records that speak for this package carry
    (`primble_record._package_flags`) fill only a flag NO uploaded document
    states - a forms-only re-upload keeps what the declarations said the
    business is; a document that says otherwise wins."""
    moved: List[str] = []
    for d in restoring_docs(docs):
        for k, v in ((_restored(d).get("flags")) or {}).items():
            if v is True and k not in flags:
                flags[k] = True
                moved.append(k)
    return moved


def drop_answer_echoes(docs: List[dict]) -> List[str]:
    """Our own forms PRINT the person's answers, and a certificate (ACORD 25 /
    28) carries no record to say which boxes those are: the re-uploaded 28's wind
    box (the producer's 50%) read as a document disagreeing with the dec's 2%, a
    Data Consistency card holding the package at 85 (round trip, 27 Oct 2026).
    A box reading that IS an answer the package's records restore is that answer
    printed back - it leaves the STORED document's facts (the picker reads
    those). Only an AGREEING reading goes; a form saying something else stays a
    witness. Runs before the merge folds its document copies. Returns
    "file:fact" for each reading removed. Only the answers the package
    restores (`restoring_docs`): an answer it does not take is no echo."""
    answers, split = _restored_answers(docs)
    if not answers:
        return []
    try:
        from services.acord_intake.primble_record import _same_value
    except Exception:                                          # noqa: BLE001
        return []
    out: List[str] = []
    for d in docs or []:
        if not is_acord_doc(d) or not isinstance(d.get("facts"), dict):
            continue
        for k, env in answers.items():
            held = d["facts"].get(k)
            if (k not in split and isinstance(held, dict) and held.get("source") == ACORD_SOURCE
                    and _same_value(k, held.get("value"), env.get("value"))):
                d["facts"].pop(k, None)
                out.append(f"{d.get('filename')}:{k}")
    return out


def apply_owner_rules(merged: Dict[str, Any], docs: List[dict]) -> List[str]:
    """Settle the merged scalars by the owner table. Returns the keys it moved."""
    moved: List[str] = []
    active = [d for d in docs or [] if isinstance(d, dict) and not d.get("excluded")]
    # An EXCLUDED ACORD document changes nothing: it used to switch on the COPE
    # derivation below, labelling the declarations' own rows "acord_form".
    # The records first - an SQS summary restores with no ACORD form uploaded.
    moved.extend(apply_restored_answers(merged, docs))
    if not any(is_acord_doc(d) for d in active):
        return moved
    apps = [d for d in active if is_application_doc(d)]
    others = [d for d in active if not is_application_doc(d)]
    # An application naming ANOTHER insured than the other documents never takes
    # over the applicant's identity: normal voting stands, and Submission
    # Integrity asks the producer (blank over wrong).
    apps = [d for d in apps if names_this_insured(d, identity_witnesses(active))]
    current = [d for d in apps if not (d.get("acord") or {}).get("prior_application")]
    prior = [d for d in apps if (d.get("acord") or {}).get("prior_application")]

    def _stated(pool, key):
        return next((d["facts"][key] for d in pool
                     if not _empty((d.get("facts") or {}).get(key))), None)

    displaced_term = {k: merged.get(k) for k in ("effective_date", "expiration_date")}
    # The proposed term is ONE application's PAIR: the first application with a
    # start date gives its own end too - never application A's start with
    # application B's end (two current 125s of one insured, a draft and a
    # revision, gave a 15-month term; production fuzz, 29 Oct 2026). Their
    # disagreement still shows as a Data Consistency card (per-document copies).
    _term_doc = next((d for d in current if not _empty((d.get("facts") or {}).get("effective_date"))), None)
    for key in ACORD_OWNED:
        if _by_person(merged.get(key)):
            continue
        if key == "expiration_date" and _term_doc is not None:
            val = (_term_doc.get("facts") or {}).get(key)
            val = None if _empty(val) else val
            held = merged.get(key)
            if val is None and isinstance(held, dict) and held.get("source") == ACORD_SOURCE:
                # another application's end, voted in beside this one's start
                merged.pop(key, None)
                moved.append(key)
                continue
        else:
            val = _stated(current, key)
        if val is None and key in PRIOR_IDENTITY_FACTS and _empty(merged.get(key)):
            # A prior-year application fills a GAP in who the applicant is -
            # it never outvotes this year's documents.
            val = _stated(prior, key)
        if (isinstance(val, dict) and val.get("derived_from") and not _empty(merged.get(key))
                and not (isinstance(merged.get(key), dict) and merged[key].get("derived_from"))):
            # A business total ADDED UP from the form's premises rows
            # (`document_settle`) never outvotes a total a document states; the
            # two still meet as a Data Consistency card (item 8, 29 Oct 2026).
            continue
        if val is not None and _fv(merged.get(key)) != _fv(val):
            merged[key] = val
            moved.append(key)
        elif val is None and prior and key not in PRIOR_IDENTITY_FACTS:
            # Only a PRIOR-YEAR application states it: last year's, not this year's.
            held = merged.get(key)
            if (isinstance(held, dict) and held.get("source") == ACORD_SOURCE
                    and any(_fv((d.get("facts") or {}).get(key)) == _fv(held) for d in prior)):
                merged.pop(key, None)
                moved.append(key)
    if {"effective_date", "expiration_date"} & set(moved):
        moved.extend(_keep_displaced_current_term(merged, displaced_term))
    # The grid's prior term is read against the PROPOSED term, so only when the
    # proposal is the application's own (or a person's). An application that
    # leaves PROPOSED EFF DATE blank leaves the declarations' CURRENT term in
    # `effective_date`, and the grid's year before it became the "prior" term:
    # the renewal router then found the prior slots full, the current term
    # (2026-27) vanished, and the year before it (2025-26, another carrier)
    # stood as the prior term and the prior carrier (review, 27 Oct 2026).
    _proposal = _stated(current, "effective_date")
    if _by_person(merged.get("effective_date")) or (
            _proposal is not None and _fv(merged.get("effective_date")) == _fv(_proposal)):
        moved.extend(_prior_term_from_grid(merged, current))
    # A current-policy fact an ACORD application supplied is outvoted by any
    # other document (a declaration, a certificate).
    for key, held in list(merged.items()):
        if key in ACORD_OWNED or not isinstance(held, dict) or held.get("source") != ACORD_SOURCE:
            continue
        stated = [d["facts"][key] for d in others
                  if isinstance(d.get("facts"), dict) and not _empty(d["facts"].get(key))
                  and d["facts"][key] is not held]
        # A document that AGREES with the form keeps the value, on that
        # document's own envelope: "the first other document" outvoted the
        # form whatever it said - the Choice Electric forms + declarations
        # round trip took the EXCESS dec's $4,000,000 as the umbrella limit
        # over the 131's $5,000,000, which the umbrella's own dec prints too
        # (review, 28 Oct 2026).
        agreeing = next((x for x in stated if _agrees(key, x, held)), None)
        if agreeing is not None:
            merged[key] = agreeing
            moved.append(key)
            continue
        rival = stated[0] if stated else None
        if rival is not None and _fv(rival) != _fv(held):
            merged[key] = rival
            moved.append(key)
    # The location rows an ACORD form printed decide the package COPE facts the
    # same way a person's table save does (`premises_cope.derive_package_cope` -
    # the one door; it never overwrites a value of another source).
    try:
        from services.premises_cope import derive_package_cope
        moved.extend(derive_package_cope(merged, source=ACORD_SOURCE) or [])
    except Exception as ex:                                    # noqa: BLE001
        logger.warning("acord merge rules: COPE derivation skipped: %s", ex)
    if moved:
        logger.info("acord merge rules: settled %s", sorted(set(moved)))
    return moved


# ── Schedules printed on several ACORD forms fold by identity ───────────────
def _norm(v: Any) -> str:
    import re
    return re.sub(r"[^a-z0-9]", "", str(_fv(v) or "").lower())


def _num(v: Any) -> str:
    n = _norm(v).lstrip("0")
    return n or ("0" if _norm(v) else "")


def _money(v: Any) -> str:
    """An amount by value: "$1,000.00" and "1000" are one amount."""
    import re
    return re.sub(r"\.0+$", "", re.sub(r"[^0-9.]", "", str(_fv(v) or "")))


def _row_key(list_key: str, row: dict) -> Optional[tuple]:
    """The identity of one schedule row; None = no identity (kept as its own row)."""
    g = row.get
    if list_key == "property_locations":
        loc = _num(g("location_number") or g("premises_number"))
        bldg = _num(g("building_number")) or "1"
        line1 = _norm(g("address_line1"))
        if loc:
            return ("loc", loc, bldg)
        if line1:
            return ("addr", line1, bldg)
        return None
    # Only a real IDENTIFIER joins two rows - never a description: two 2013
    # Chevrolet Express vans are two vans (27 Oct 2026 round trip).
    if list_key == "auto_vin_schedule":
        return ("vin", _norm(g("vin"))) if _norm(g("vin")) else None
    if list_key == "auto_drivers":
        if _norm(g("license_number")):
            return ("lic", _norm(g("license_number")))
        if _norm(g("name")) and _norm(g("dob")):
            return ("name", _norm(g("name")), _norm(g("dob")))
        return None
    if list_key == "wc_class_codes":
        return ("wc", _norm(g("code")), _norm(g("state"))) if _norm(g("code")) else None
    if list_key == "loss_history":
        if _norm(g("claim_number")):
            return ("claim", _norm(g("claim_number")))
        when = g("date") or g("claim_date")
        if not when:
            return None
        try:                             # "1/5/2024" and "01/05/2024" are one day
            from services.normalization import normalize_date
            day = normalize_date(str(_fv(when))) or _norm(when)
        except Exception:                                      # noqa: BLE001
            day = _norm(when)
        return ("loss", _norm(day), _money(g("paid")))
    if list_key == "gl_class_code_schedule":
        return ("gl", _norm(g("class_code")), _num(g("location"))) if _norm(g("class_code")) else None
    if list_key == "underlying_policies":
        # Two ACORD 131s (the umbrella's and the excess layer's) list one GL
        # policy twice: one line's policy is one row.
        try:
            from services.lob_canon import canon_line
            fam = canon_line(str(g("line") or "")) or _norm(g("line"))
        except Exception:                                      # noqa: BLE001
            fam = _norm(g("line"))
        who = _norm(g("policy_no")) or _norm(g("carrier"))
        return ("und", fam, who) if fam and who else None
    if list_key in ("coverage_lines", "prior_coverage_by_line"):
        try:
            from services.lob_canon import canon_line
            fam = canon_line(str(g("line") or "")) or _norm(g("line"))
        except Exception:                                      # noqa: BLE001
            fam = _norm(g("line"))
        try:
            from services.lob_canon import umbrella_layer
            layer = umbrella_layer(str(g("line") or "")) or ""
        except Exception:                                      # noqa: BLE001
            layer = ""
        when = _norm(g("effective_date") or g("effective") or g("year"))
        # The umbrella and the excess layer are one FAMILY and two policies.
        return ("line", fam, layer, when) if fam else None
    return None


# A VEHICLE without a VIN (every redacted dec) is the same vehicle on another
# document when its description agrees and nothing contradicts it - the
# Choice Electric round trip (27 Oct 2026) printed the dec's 17 vans AND the
# ACORD 127's 17, 34 vehicles, because only a VIN joined rows. The match is
# ONE-TO-ONE across documents (a row absorbs at most one row of each other
# document), so a fleet of identical vans keeps its count: two documents each
# listing three 2014 Express G2500s give three, never one and never six. Only
# these columns can contradict a match; a column both rows state differently
# (a cost, a class, the package's own VEH #) means two vehicles.
_VEHICLE_MATCH_COLS = ("year", "vin", "vehicle_number", "cost_new", "stated_amount",
                       "class_code", "territory", "gvw")
_VEHICLE_DESC_COLS = ("make", "model")


def _same_cell(col: str, a: Any, b: Any) -> bool:
    if col in ("cost_new", "stated_amount", "gvw"):
        return _money(a) == _money(b)
    if col in ("class_code", "territory", "vehicle_number"):
        return _num(a) == _num(b)
    return _norm(a) == _norm(b)


def _vin_key(v: Any) -> str:
    """A VIN's characters (envelope unwrapped, spaces / dashes dropped, upper)."""
    return _norm(v).upper()


def _truncated_vin_of(a: dict, b: dict, fulls: Optional[Dict[str, int]] = None) -> bool:
    va, vb = _vin_key(a.get("vin")), _vin_key(b.get("vin"))
    short, full = (va, vb) if len(va) < len(vb) else (vb, va)
    if len(full) != 17 or not (11 <= len(short) <= 16) or not full.startswith(short):
        return False
    # AMBIGUOUS (review, 29 Oct 2026): a fleet bought together shares the first
    # 11-16 characters (consecutive serials). A short VIN two full VINs of the
    # package both start with names neither - it joins no row.
    if fulls is not None and sum(1 for f in fulls if f.startswith(short)) > 1:
        return False
    ya, yb = _norm(a.get("year")), _norm(b.get("year"))
    if ya and yb and ya != yb:
        return False
    # Make / model agree as words ("ProMaster 2500" on the 127, "ProMaster Cargo
    # Van 2500" on the dec - item 4, 29 Oct 2026: the kit's 4 vehicles became 6).
    return _desc_compatible(a, b)


def _describes_same_vehicle(a: dict, b: dict, full_vins: Optional[Dict[str, int]] = None) -> bool:
    """Year and make / model agree (containment: "EXPRESS G2500" in "Chevrolet
    Express G2500"), and no identity column both state disagrees."""
    if _norm(a.get("vin")) and _norm(b.get("vin")):
        # two VINs: the identity key decides - except a SHORT (invalid) VIN that
        # is the start of a full 17-character one for the same year: a dropped
        # character (OCR, a narrow column), the same vehicle (live kit, 29 Oct
        # 2026: 4 vehicles became 7). Two full VINs one character apart stay two
        # vehicles - a fleet bought together runs consecutive serials.
        return _truncated_vin_of(a, b, full_vins)
    if not (_norm(a.get("year")) and _norm(a.get("year")) == _norm(b.get("year"))):
        return False
    desc_a = "".join(_norm(a.get(c)) for c in _VEHICLE_DESC_COLS)
    desc_b = "".join(_norm(b.get(c)) for c in _VEHICLE_DESC_COLS)
    model_a, model_b = _norm(a.get("model")), _norm(b.get("model"))
    if not desc_a or not desc_b:
        return False
    if not ((model_a and model_a in desc_b) or (model_b and model_b in desc_a)):
        return False
    for col in _VEHICLE_MATCH_COLS:
        if not _empty(a.get(col)) and not _empty(b.get(col)) and not _same_cell(col, a.get(col), b.get(col)):
            return False
    return True


# ONE DRIVER, ONE POLICY, PRINTED BY A FORM AND A DECLARATION (28 Oct 2026,
# review, the CH125 forms + declarations round trip: 10 drivers became 18, 23
# prior policies 34). The ACORD 127 prints a driver's NAME (no licence or birth
# date - the form withholds them), the ACORD 125 prior grid and the 131
# underlying section a policy without its declaration's wording; the general
# merge joins rows only on identifiers, so every row came twice. A row joins a
# row of ANOTHER document it describes - one to one, as vehicles do.
def _name_tokens(v: Any) -> frozenset:
    import re
    return frozenset(t for t in re.findall(r"[a-z0-9']+", str(_fv(v) or "").lower().replace("'", ""))
                     if len(t) > 1)


def _describes_same_driver(a: dict, b: dict) -> bool:
    """The same person's name in any order ("Szymanski, Gregory" and "Gregory
    L. Szymanski"; initials ignored), at least two name words, and no licence
    or birth date both rows state that disagrees."""
    na, nb = _name_tokens(a.get("name")), _name_tokens(b.get("name"))
    if len(na) < 2 or na != nb:
        return False
    for col in ("license_number", "dob"):
        if not _empty(a.get(col)) and not _empty(b.get(col)):
            same = _same_day(a.get(col), b.get(col)) if col == "dob" else _norm(a.get(col)) == _norm(b.get(col))
            if not same:
                return False
    return True


def _same_contract_number(a: Any, b: Any) -> Optional[bool]:
    """True / False when both rows print a policy number, None when one does
    not. A number printed without its suffix ("6E74002") is the same contract
    as "6E7-40-02---26" (`fact_equivalence`'s prefix rule, by containment at
    the start)."""
    x, y = _norm(a), _norm(b)
    if not x or not y:
        return None
    short, long_ = sorted((x, y), key=len)
    return len(short) >= 5 and long_.startswith(short)


def _describes_same_policy(a: dict, b: dict) -> bool:
    try:
        from services.lob_canon import canon_line, umbrella_layer
    except Exception:                                          # noqa: BLE001
        canon_line = umbrella_layer = lambda _t: None          # noqa: E731
    num = _same_contract_number(a.get("policy_no") or a.get("policy_number"),
                                b.get("policy_no") or b.get("policy_number"))
    if num is False:
        return False
    la, lb = str(_fv(a.get("line")) or ""), str(_fv(b.get("line")) or "")
    fa, fb = canon_line(la) if la else None, canon_line(lb) if lb else None
    if fa and fb and (fa != fb or (umbrella_layer(la) or "") != (umbrella_layer(lb) or "")):
        return False
    for col in ("effective", "effective_date", "expiration", "expiration_date"):
        if not _empty(a.get(col)) and not _empty(b.get(col)) and not _same_day(a.get(col), b.get(col)):
            return False
    pa, pb = a.get("premium"), b.get("premium")
    if not _empty(pa) and not _empty(pb) and _money(pa) != _money(pb):
        return False
    if num is True:
        return True
    # No number on one side: the same line, carrier and term.
    if not (fa and fb):
        return False
    ca, cb = _norm(a.get("carrier")), _norm(b.get("carrier"))
    if not (ca and cb and (ca in cb or cb in ca)):
        return False
    return any(not _empty(a.get(c)) and not _empty(b.get(c))
               for c in ("effective", "effective_date", "expiration", "expiration_date"))


# ONE CLAIM PRINTED TWICE (27 Oct 2026, the Orbin round trip). ACORD 125 prints a
# claim with its occurrence date, ACORD 131 the same claim with its report date
# only, and the loss runs with its claim number - and the fold's key read the
# occurrence date first, so the 125 and 131 rows were two claims ($4,950 total
# became $8,100) and the loss runs a third ($9,900). A claim row is the same
# claim on another document when every column both state agrees and at least
# one date both state is the same day; two claim numbers decide alone.
_CLAIM_DATE_COLS = ("date", "claim_date")
_CLAIM_AMOUNT_COLS = ("paid", "incurred", "amount", "reserved_amount")


def _same_day(a: Any, b: Any) -> bool:
    try:
        from services.normalization import normalize_date
        x, y = normalize_date(str(_fv(a))), normalize_date(str(_fv(b)))
    except Exception:                                          # noqa: BLE001
        x = y = None
    return (x == y) if (x and y) else _norm(a) == _norm(b)


def _describes_same_claim(a: dict, b: dict) -> bool:
    if _norm(a.get("claim_number")) and _norm(b.get("claim_number")):
        return _norm(a.get("claim_number")) == _norm(b.get("claim_number"))
    shared = False
    for col in _CLAIM_DATE_COLS:
        if _empty(a.get(col)) or _empty(b.get(col)):
            continue
        if not _same_day(a.get(col), b.get(col)):
            return False
        shared = True
    if not shared:
        return False
    for col in _CLAIM_AMOUNT_COLS:
        if not _empty(a.get(col)) and not _empty(b.get(col)) and _money(a.get(col)) != _money(b.get(col)):
            return False
    la, lb = a.get("line_of_business"), b.get("line_of_business")
    if not _empty(la) and not _empty(lb):
        try:
            from services.lob_canon import canon_line
            fa, fb = canon_line(str(_fv(la))), canon_line(str(_fv(lb)))
        except Exception:                                      # noqa: BLE001
            fa = fb = None
        if (fa or _norm(la)) != (fb or _norm(lb)):
            return False
    da, db = _norm(a.get("description")), _norm(b.get("description"))
    if da and db and not (da in db or db in da):
        return False
    return True


# ONE CLAIM, TWO DOCUMENTS, TWO AMOUNTS (item 7, 29 Oct 2026, the Ridgeline kit:
# the loss run's 05/17/2022 auto claim paid $18,420, the outside ACORD 125's row
# $14,820 - 12 claims for 9). `_describes_same_claim` demanded every amount agree,
# so a restated claim with a different paid figure became a second claim. A claim
# is the same EVENT when its claim numbers agree (both printed: they decide
# alone), else its date of loss is the same day and its line is compatible - the
# amounts are what the documents disagree ABOUT, recorded as rival values
# (`services/row_rivals`), never a reason for a second row. Two claims on the
# same day of different lines or carriers stay two. A narrow ACORD LOB box cuts
# the line ("General Lia", "Commercia"): a cut name stands for every line name it
# begins (`claim_line_families`).
_LINE_NAMES = (
    "General Liability", "Commercial General Liability", "Business Auto", "Commercial Auto",
    "Automobile", "Auto Liability", "Commercial Property", "Property", "Workers Compensation",
    "Workers Compensation and Employers Liability", "Commercial Umbrella", "Umbrella",
    "Excess Liability", "Inland Marine", "Commercial Inland Marine", "Crime", "Commercial Crime",
    "Cyber Liability", "Professional Liability", "Employment Practices Liability",
    "Pollution Liability", "Liquor Liability", "Garage", "Garage and Dealers", "Truckers",
)


def claim_line_families(text: Any) -> frozenset:
    """The line families a claim row's LOB text can mean; empty = unknown."""
    raw = str(_fv(text) or "").strip()
    if not raw:
        return frozenset()
    try:
        from services.lob_canon import canon_line, FAMILY_LABELS
    except Exception:                                          # noqa: BLE001
        return frozenset({_norm(raw)})
    fam = canon_line(raw)
    if fam:
        return frozenset({fam})
    cut = _norm(raw)
    if len(cut) < 4:
        return frozenset({cut})
    names = set(_LINE_NAMES) | set(FAMILY_LABELS.values())
    try:
        from services.acord_intake.reverse_map import LINE_TOKENS
        names |= set(LINE_TOKENS.values())
    except Exception:                                          # noqa: BLE001
        pass
    fams = {canon_line(n) for n in names if _norm(n).startswith(cut)}
    fams.discard(None)
    return frozenset(fams) if fams else frozenset({cut})


def same_claim_event(a: dict, b: dict) -> bool:
    """Do two claim rows describe one claim? Claim numbers decide when both print
    one; otherwise the date of loss (or, with no loss date on one side, the
    report date) is the same day, the lines are compatible and the carriers do
    not differ. The amounts never decide (they are what may disagree)."""
    if not (isinstance(a, dict) and isinstance(b, dict)):
        return False
    na, nb = _norm(a.get("claim_number")), _norm(b.get("claim_number"))
    if na and nb:
        return na == nb
    shared = False
    for col in _CLAIM_DATE_COLS:
        if _empty(a.get(col)) or _empty(b.get(col)):
            continue
        if not _same_day(a.get(col), b.get(col)):
            return False
        shared = True
        if col == "date":
            break                        # the loss date decides; a report date may lag
    if not shared:
        return False
    fa, fb = claim_line_families(a.get("line_of_business")), claim_line_families(b.get("line_of_business"))
    if fa and fb and not (fa & fb):
        return False
    ca, cb = _norm(a.get("carrier")), _norm(b.get("carrier"))
    if ca and cb and ca not in cb and cb not in ca:
        return False
    return True


def unique_claim_match(row: dict, pool: List[dict]) -> Optional[int]:
    """The index in `pool` of the ONE claim `row` restates; None when none or
    several qualify. Several on one day and line are narrowed by the amounts
    (`_describes_same_claim`) - never guessed."""
    hits = [i for i, x in enumerate(pool or []) if isinstance(x, dict) and same_claim_event(x, row)]
    if len(hits) > 1:
        hits = [i for i in hits if _describes_same_claim(pool[i], row)]
    return hits[0] if len(hits) == 1 else None


def restates_record_claim(row: dict, of_record: List[dict]) -> bool:
    """Does an ACORD form's claim row restate ONE claim the loss runs list?
    Several loss runs may print that one claim (overlapping valuations): their
    rows describe each other, so they are still one claim. Two different claims
    on that day and line are narrowed by the amounts; still two = not a
    restatement (blank over wrong - the row stays)."""
    hits = [x for x in of_record or [] if same_claim_event(x, row)]
    if len(hits) > 1 and not all(same_claim_event(hits[0], h) for h in hits[1:]):
        hits = [x for x in hits if _describes_same_claim(x, row)]
    return bool(hits) and all(same_claim_event(hits[0], h) for h in hits[1:])


def _desc_compatible(a: dict, b: dict) -> bool:
    """Make and model agree as WORDS: "ProMaster 2500" is "ProMaster Cargo Van
    2500" (the shorter description's words are all in the longer one)."""
    for col in ("make", "model"):
        sx, sy = _norm(a.get(col)), _norm(b.get(col))
        if not (sx and sy) or sx in sy or sy in sx:
            continue
        x, y = _name_tokens(a.get(col)), _name_tokens(b.get(col))
        if not (x and y and (x <= y or y <= x)):
            return False
    return True


def near_vin_same_vehicle(a: dict, b: dict) -> bool:
    """Two full VINs one character apart, same year, the same VEH #, compatible
    make / model - a mistyped character IF nothing else claims either VIN (the caller checks
    that: a fleet bought together runs consecutive serials, and both documents
    then print both VINs exactly)."""
    va, vb = _vin_key(a.get("vin")), _vin_key(b.get("vin"))
    if len(va) != 17 or len(vb) != 17 or va == vb:
        return False
    if sum(1 for x, y in zip(va, vb) if x != y) != 1:
        return False
    ya, yb = _norm(a.get("year")), _norm(b.get("year"))
    if not (ya and yb and ya == yb):
        return False
    # STRUCTURAL SECOND CONDITION: both schedules give the vehicle the SAME
    # number (VEH #). Without it two full VINs one apart are two vehicles - a
    # fleet bought together runs consecutive serials (review, 29 Oct 2026,
    # `test_two_full_vins_one_apart_stay_two`).
    na, nb = _num(a.get("vehicle_number")), _num(b.get("vehicle_number"))
    if not (na and nb and na == nb):
        return False
    return _desc_compatible(a, b)


def _same_row(a: dict, b: dict) -> bool:
    sa = {k: _norm(v) for k, v in a.items() if not _empty(v) and _norm(v)}
    sb = {k: _norm(v) for k, v in b.items() if not _empty(v) and _norm(v)}
    return bool(sa) and sa == sb


# list -> (does row b describe row a's thing, never join two ACORD forms' rows).
# Vehicles and drivers: the 127 and its 101 continuation list DIFFERENT ones.
_DESCRIBES_SAME = {
    "auto_vin_schedule": (_describes_same_vehicle, True),
    "auto_drivers": (_describes_same_driver, True),
    "prior_coverage_by_line": (_describes_same_policy, False),
    "underlying_policies": (_describes_same_policy, False),
}


def fold_rows(list_key: str, rows_by_doc: List[List[dict]],
              acord_docs: Optional[List[bool]] = None) -> List[dict]:
    """Rows of one list from several documents; a row joins a row of the SAME
    identity from ANOTHER document (first value wins per column). Two rows of one
    document are never joined - two 2023 Chevrolet Express G3500 vans at the same
    cost are two vans. A vehicle without a VIN joins, one to one, a vehicle of
    another document its description agrees with (`_describes_same_vehicle`) -
    never across two ACORD forms (`acord_docs[n]`: document n is one): the 127
    and the 101 continuing its schedule list DIFFERENT vehicles, and the 127's
    2022 Equinox joined the 101's second 2022 Equinox (B1, 27 Oct 2026).
    Other rows without an identity are kept as they are."""
    out: List[dict] = []
    index: Dict[tuple, List[int]] = {}
    sources: List[set] = []
    acord = list(acord_docs or [False] * len(rows_by_doc))
    # Every full 17-character VIN the documents print (a short VIN is judged
    # against all of them, whatever order the documents come in).
    full_vins: Dict[str, int] = {}
    if list_key == "auto_vin_schedule":
        for rows in rows_by_doc:
            for r in rows or []:
                if isinstance(r, dict) and len(_vin_key(r.get("vin"))) == 17:
                    full_vins[_vin_key(r.get("vin"))] = 1
    # Per document: the VINs it prints, the driver names it lists (and how often).
    vins_by_doc: Dict[int, set] = {}
    names_by_doc: Dict[int, Dict[frozenset, int]] = {}
    for _n, rows in enumerate(rows_by_doc):
        for r in rows or []:
            if not isinstance(r, dict):
                continue
            if list_key == "auto_vin_schedule" and _vin_key(r.get("vin")):
                vins_by_doc.setdefault(_n, set()).add(_vin_key(r.get("vin")))
            if list_key == "auto_drivers":
                _nm = _name_tokens(r.get("name"))
                if _nm:
                    names_by_doc.setdefault(_n, {})[_nm] = names_by_doc.setdefault(_n, {}).get(_nm, 0) + 1

    def _may_describe(i: int, doc_no: int) -> bool:
        # Never two ACORD forms' rows in one vehicle - directly or THROUGH a
        # declaration's row: the dec's first 2022 Equinox took the 127's and
        # then the 101's (a different vehicle), and the dec's second Equinox
        # kept neither (review, 27 Oct 2026).
        return not (acord[doc_no] and any(acord[s] for s in sources[i]))
    for doc_no, rows in enumerate(rows_by_doc):
        for r in rows:
            if not isinstance(r, dict):
                continue
            k = _row_key(list_key, r)
            slot = next((i for i in index.get(k, []) if doc_no not in sources[i]), None) if k else None
            if slot is None and list_key in _DESCRIBES_SAME:
                same, one_form = _DESCRIBES_SAME[list_key]
                if same is _describes_same_vehicle:
                    same = lambda a, b: _describes_same_vehicle(a, b, full_vins)  # noqa: E731
                slot = next((i for i, held in enumerate(out)
                             if doc_no not in sources[i] and (not one_form or _may_describe(i, doc_no))
                             and same(held, r)), None)
            if slot is None:
                # The SAME row printed by another document - every column it
                # states, stated alike (the same form uploaded twice: two copies
                # of one 127 doubled a VIN-less fleet). One to one, so two
                # identical vans on one form still meet two rows.
                slot = next((i for i, held in enumerate(out)
                             if doc_no not in sources[i] and _same_row(held, r)), None)
            if slot is None and list_key == "loss_history":
                # One claim = one row: the same event on another document, its
                # amounts disagreeing or not (item 7, `same_claim_event`).
                pool = [i for i in range(len(out)) if doc_no not in sources[i]]
                hit = unique_claim_match(r, [out[i] for i in pool])
                slot = pool[hit] if hit is not None else None
            if slot is None and list_key == "auto_vin_schedule" and len(_vin_key(r.get("vin"))) == 17:
                # A full VIN one character from another document's (item 4): the
                # same vehicle when it is the ONLY such vehicle and neither VIN
                # is printed by the other side (a fleet's consecutive serials
                # are printed exactly by both documents).
                mine = vins_by_doc.get(doc_no, set())
                cands = [i for i, held in enumerate(out)
                         if doc_no not in sources[i] and _may_describe(i, doc_no)
                         and near_vin_same_vehicle(held, r)
                         and _vin_key(held.get("vin")) not in mine
                         and not any(_vin_key(r.get("vin")) in vins_by_doc.get(sd, set())
                                     for sd in sources[i])]
                slot = cands[0] if len(cands) == 1 else None
            if slot is None and list_key == "auto_drivers":
                # A driver named alike on another document, once on each side,
                # whose licence and birth date do not disagree (one side does not
                # print it): one person (item 4). Same name, different birth
                # dates = two people.
                nm = _name_tokens(r.get("name"))
                if len(nm) >= 2 and names_by_doc.get(doc_no, {}).get(nm, 0) == 1:
                    cands = [i for i, held in enumerate(out)
                             if doc_no not in sources[i] and _may_describe(i, doc_no)
                             and _name_tokens(held.get("name")) == nm
                             and not (_norm(held.get("license_number")) and _norm(r.get("license_number"))
                                      and _norm(held.get("license_number")) != _norm(r.get("license_number")))
                             # Two birth dates that differ are two people (a licence
                             # match alone makes the date a rival - `_row_key`).
                             and not (not _empty(held.get("dob")) and not _empty(r.get("dob"))
                                      and not _same_day(held.get("dob"), r.get("dob")))
                             and all(names_by_doc.get(sd, {}).get(nm, 0) == 1 for sd in sources[i])]
                    slot = cands[0] if len(cands) == 1 else None
            if slot is None:
                out.append(dict(r))
                sources.append({doc_no})
                if k is not None:
                    index.setdefault(k, []).append(len(out) - 1)
                continue
            tgt = out[slot]
            sources[slot].add(doc_no)
            for col, v in r.items():
                if _empty(tgt.get(col)) and not _empty(v):
                    tgt[col] = v
            # A short VIN joined by its full one carries the full one.
            if (list_key == "auto_vin_schedule" and len(_vin_key(r.get("vin"))) == 17
                    and len(_vin_key(tgt.get("vin"))) < 17):
                tgt["vin"] = r.get("vin")
            if k is not None and slot not in index.get(k, []):
                index.setdefault(k, []).append(slot)
    if list_key == "property_locations":
        out = _fold_identity_less_locations(out)
    return out


# A LOCATION ROW WITH NO IDENTITY IS NO PREMISES (27 Oct 2026, the Orbin round
# trip): ACORD 186 prints the business's full-time employee count and nothing
# else, the reader filed it as a location row, and one premises became two
# (LOC 2 on the 125, 130 and 131). A row with no address, no location number
# and no building number joins the ONE premises when there is exactly one
# (filling only its empty cells); beside several it says which none - dropped.
_LOCATION_IDENTITY_COLS = ("address_line1", "address", "location_number", "premises_number",
                           "building_number", "address_city")


def _fold_identity_less_locations(rows: List[dict]) -> List[dict]:
    named = [r for r in rows if any(not _empty(r.get(c)) for c in _LOCATION_IDENTITY_COLS)]
    bare = [r for r in rows if r not in named]
    if not bare or not named:
        return rows
    if len(named) == 1:
        for r in bare:
            for col, v in r.items():
                if _empty(named[0].get(col)) and not _empty(v):
                    named[0][col] = v
    return named


# ── Box readings are the form's statement, not the model's guess ─────────────
# The merge's per-document pre-pass is a row of rules that police what the MODEL
# read: an AI vehicle use must sit beside a "use" label in the text, a payroll
# period must be named, a menu counts only as its ticked option, a carrier
# office's state is not the insured's. A value read off an ACORD box is none of
# those - it is what the form states - and every one of those rules judged it as
# a guess: the round trip's ACORD 127 ticked "Service" on all 17 vans, and
# `drop_unlabelled_vehicle_use` deleted it because the option's wording is
# printed nowhere in the text (27 Oct 2026). So the box readings step out of the
# pre-pass and back in before the vote. A box the Primble record names as an AI
# fill (source "ai") stays in, and is policed like any AI value.
def _box_reading(v: Any) -> bool:
    return not (isinstance(v, dict) and str(v.get("source") or "").lower() == "ai")


def lift_box_readings(docs: List[dict]) -> List[tuple]:
    """[(doc, {key: value})] - the ACORD box readings taken out of each ACORD
    document's facts. `restore_box_readings` puts them back."""
    held: List[tuple] = []
    for d in docs or []:
        if not is_acord_doc(d) or not isinstance(d.get("facts"), dict):
            continue
        rec = d.get("acord") or {}
        keys = rec.get("read_keys")
        if keys is None:                 # stored before 27 Oct night: the exact envelopes
            keys = [k for k, v in d["facts"].items()
                    if isinstance(v, dict) and v.get("source") == ACORD_SOURCE]
        out = {}
        for k in keys:
            if k in d["facts"] and _box_reading(d["facts"][k]):
                out[k] = d["facts"].pop(k)
        if out:
            held.append((d, out))
    return held


def restore_box_readings(held: List[tuple]) -> None:
    for d, kv in held or []:
        if isinstance(d.get("facts"), dict):
            d["facts"].update(kv)


# Lists whose rows the general merge cannot join across a filled ACORD and a
# declaration: a redacted dec's vehicles carry no VIN, so `_dedupe_schedule_rows`
# (identifier keys only) printed both copies of the fleet. These fold across
# EVERY document of a package holding an ACORD form, the declarations' rows
# first. Every other list keeps the general merge it has today.
_FOLD_WITH_DECLARATIONS = ("auto_vin_schedule", "auto_drivers", "prior_coverage_by_line", "underlying_policies")
# Lists another document is the record of: the carrier's loss runs list the
# claims; an ACORD form restates them (27 Oct 2026).
_LISTS_OF_RECORD = ("loss_history",)
# The form that PRINTS a schedule natively leads its fold; a form carrying it as
# a continuation (Primble's ACORD 101 "VEHICLE SCHEDULE (continued ...)" -
# vehicles 5-17) follows. In upload order the 101 came first and the 127's own
# rows 1-4 landed fifth to eighth (round trip, 27 Oct 2026).
_SCHEDULE_HOME_FORMS = {"auto_vin_schedule": "ACORD_127", "auto_drivers": "ACORD_127",
                        "wc_class_codes": "ACORD_130", "wc_officers": "ACORD_130"}


def _holds_form(d: dict, form_id: str) -> bool:
    return any(str((c or {}).get("form_id") or "").split("__")[0] == form_id
               for c in (d.get("acord") or {}).get("forms") or [])


def fold_acord_lists(docs: List[dict], primary: dict):
    """(docs, primary) where every ACORD document's schedule rows are folded into
    the FIRST ACORD document's copy and removed from the other ACORD copies; a
    `_FOLD_WITH_DECLARATIONS` list folds the other documents' rows too, into the
    first document holding them. Copies only: the stored per-document facts are
    not touched."""
    acord_idx = [i for i, d in enumerate(docs or []) if is_acord_doc(d) and not d.get("excluded")]
    if not acord_idx:
        return docs, primary
    view = list(docs)

    def _copy(i):
        if view[i] is docs[i]:
            view[i] = dict(docs[i], facts=dict(docs[i].get("facts") or {}))
        return view[i]

    def _rows(i, k):
        held = _fv((view[i].get("facts") or {}).get(k))
        return [r for r in held if isinstance(r, dict)] if isinstance(held, list) else []

    keys = set()
    for i in acord_idx:
        for k, v in (docs[i].get("facts") or {}).items():
            if isinstance(_fv(v), list) and _fv(v) and isinstance(_fv(v)[0], dict):
                keys.add(k)
    for k in keys:
        members = list(acord_idx)
        home = _SCHEDULE_HOME_FORMS.get(k)
        if home:
            members.sort(key=lambda i: 0 if _holds_form(docs[i], home) else 1)   # stable
        if k in _FOLD_WITH_DECLARATIONS:
            others = [i for i, d in enumerate(docs or []) if i not in acord_idx and isinstance(d, dict)
                      and not d.get("excluded") and _rows(i, k)]
            members = others + members            # the declarations' rows first
        members = [i for i in members if _rows(i, k)]
        # (One ACORD form beside the loss runs is still checked against them.)
        if len(members) < 2 and not (k in _LISTS_OF_RECORD and members and members[0] in acord_idx):
            continue
        rows_by_doc = [_rows(i, k) for i in members]
        base = _copy(members[0])
        for i in members[1:]:
            _copy(i)["facts"].pop(k, None)
        held = base["facts"].get(k)
        folded = fold_rows(k, rows_by_doc, [i in acord_idx for i in members])
        if k in _LISTS_OF_RECORD:
            # A claim the loss runs list is theirs: the ACORD row restating it
            # adds no second claim (the loss runs' own rows are untouched).
            of_record = [r for i, d in enumerate(docs or []) if i not in acord_idx and isinstance(d, dict)
                         and not d.get("excluded") for r in _rows(i, k)]
            folded = [r for r in folded if not restates_record_claim(r, of_record)]
        base["facts"][k] = dict(held, value=folded) if isinstance(held, dict) and "value" in held else folded
    new_primary = next((view[i] for i, d in enumerate(docs) if d is primary), primary)
    return view, new_primary
