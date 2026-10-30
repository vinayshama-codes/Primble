"""Lane B, 27 Oct 2026 - seven items (25sepChanges.md Z44-B).

1. One GL class-code door (both homes + a person's GL window) for every reader.
2. "A person put this value" - one fact_state door, three named questions + box labels.
3. A name question is answered by a name (non-answers, back-references, roles).
4. Rare parsing leftovers: c/o party, officer table into the next table, an
   applicant named "... Mutual ...", Home Office under the insured, "USE: N.A.".
5. Unread answers persisted (shape only, encrypted) + admin route.
6. Dismiss-then-fill: one source of points per fact (real answer route).
7. Data Consistency HIGH confidence needs a STRUCTURAL lead.
Adversarial cases first in each section.
"""
from __future__ import annotations

import ast
import asyncio
import copy
import json
import os
import pathlib
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

os.environ.setdefault("FIELD_ENCRYPTION_KEY", "kZ0aQ7Yy3pR8mN2vB6xL9tJ4hG1sD5fW8cE0uI3oA7k=")

BACKEND = pathlib.Path(__file__).resolve().parents[1]


def _harvest_reads(constants, subs=("services", "routes", "utils")):
    """{(file, function): {constant}} for every VALUE read of a constant key:
    a call argument, a subscript, or the iterable of a for-loop / comprehension."""
    out = {}
    files = [p for s in subs for p in (BACKEND / s).rglob("*.py")] + [BACKEND / "worker.py"]
    for p in sorted(files):
        tree = ast.parse(p.read_text(encoding="utf-8"))
        parents = {c: n for n in ast.walk(tree) for c in ast.iter_child_nodes(n)}

        def func_of(n):
            q = n
            while q in parents:
                q = parents[q]
                if isinstance(q, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    return q.name
            return "<module>"
        for n in ast.walk(tree):
            if not (isinstance(n, ast.Constant) and n.value in constants):
                continue
            par = parents.get(n)
            read = (isinstance(par, ast.Call) and n in par.args) or (
                isinstance(par, ast.Subscript) and par.slice is n)
            if isinstance(par, (ast.Tuple, ast.List, ast.Set)):
                gp = parents.get(par)
                read = read or (isinstance(gp, (ast.For, ast.comprehension)) and gp.iter is par)
            if read:
                out.setdefault((str(p.relative_to(BACKEND)), func_of(n)), set()).add(n.value)
    return out


# ══ 1. One GL class-code door ═════════════════════════════════════════════════
from services import cross_form_validator as CFV          # noqa: E402
from services import sqs_service as SQ                    # noqa: E402

T = {"ACORD_126", "ACORD_130"}
_SCHED_ONLY = {"gl_class_code_schedule": [{"class_code": "91580", "classification": "Electrical work"}]}


def test_codes_saved_only_in_the_schedule_are_seen_by_every_cross_form_rule():
    assert [i["code"] for i in CFV._check_gl_class_code_vs_operations(_SCHED_ONLY, {}, T)] == \
        ["gl_codes_no_operations"]
    got = CFV._check_acord101_triggers(dict(_SCHED_ONLY, operations_description="Electrical"), {}, T)
    assert any("GL class codes present" in str(i) for i in got)


def test_a_payroll_never_votes_as_a_class_code_and_a_location_is_no_classification():
    """The blob defect: "5403" inside a payroll of 540300, "office" in "Home office"."""
    f = {"wc_class_codes": [{"code": "2003", "description": "Bakery", "payroll": "540300"}],
         "gl_class_codes_by_location": [{"location": "Home office: 456 Oak Ave", "codes": ["16820 Bakeries"]}]}
    assert CFV._check_wc_gl_class_code_alignment(f, {}, T) == []


def test_clerical_gl_beside_heavy_wc_still_warns_from_the_schedule():
    f = {"wc_class_codes": [{"code": "5403", "description": "Carpentry", "payroll": "90000"}],
         "gl_class_code_schedule": [{"class_code": "41650", "classification": "Clerical Office"}]}
    assert [i["code"] for i in CFV._check_wc_gl_class_code_alignment(f, {}, T)] == ["wc_gl_class_code_mismatch"]


def test_the_ops_mismatch_reads_the_schedule_home_too():
    f = {"operations_description": "Roofing contractor installing commercial roofs",
         "gl_class_code_schedule": [{"class_code": "9079"}]}
    assert SQ._is_ops_class_code_mismatch(f, {}, "gl") is True
    assert SQ._is_ops_class_code_mismatch({"operations_description": "Roofing contractor"}, {}, "gl") is False


def test_classification_text_reads_words_not_digits_or_locations():
    f = {"gl_class_codes_by_location": [{"location": "Home Office 12 Elm", "codes": ["91580 Heating 80221"]}]}
    t = SQ.gl_classification_text(f)
    assert "heating" in t and "office" not in t and "80221" not in t
    assert SQ.gl_classification_text({}) == ""


# The register: every other direct read of a GL home answers a DIFFERENT
# question (a row it prints, an exposure, a location, a declaration) or is the
# form recommender (owner rule 8 Oct - not changed, owner's call).
_GL_READ_REGISTER = {
    ("services/sqs_service.py", "gl_classification_text"): "the door",
    ("services/sqs_service.py", "person_gl_class_codes"): "the door",
    ("services/sqs_service.py", "_dec_entries_state_payroll"): "GL exposure basis",
    ("services/sqs_service.py", "coverage_deduction_items"): "names the fix field, reads nothing",
    ("services/sqs_service.py", "cross_validate"): "RECOMMENDER (ACORD 101 escalation) - owner's call",
    ("services/form_service.py", "match_forms_deterministic"): "RECOMMENDER - owner's call",
    ("services/form_service.py", "_gl_states"): "location cells (state of operations)",
    ("services/coverage_evidence.py", "_payroll_source_is_annual"): "premium basis",
    ("services/extraction_service.py", "_is_one_gl_class_exposure"): "exposure amount",
    ("services/cover_service.py", "_gl_classifications"): "declarations' class table rows, display",
    ("services/schedule_capture.py", "gl_classification_choices"): "the GL window's own rows",
    ("services/issue_registry.py", "<module>"): "declarations",
    ("services/questionnaire.py", "<module>"): "declarations",
    ("services/pdf_service.py", "<module>"): "stamper bindings",
    ("services/pdf_service.py", "_build_amount_witnesses"): "stamper row witnesses",
    ("services/pdf_service.py", "_enforce_post_fill_guards"): "stamper guard",
    ("services/pdf_service.py", "_gl_code_only_rows"): "what the 125/126 GL CODE prints",
    ("services/pdf_service.py", "_gl_hazard_rows"): "the 126 grid rows",
    ("services/pdf_service.py", "_gl_schedule_rows"): "the 126 grid rows",
    ("services/pdf_service.py", "_person_gl_codes"): "the person's GL code printing",
    ("services/pdf_service.py", "_rating_class_identities"): "products row refusal",
}


def test_no_new_direct_reader_of_a_gl_home_outside_the_register():
    found = _harvest_reads({"gl_class_codes_by_location", "gl_class_code_schedule"})
    new = sorted(set(found) - set(_GL_READ_REGISTER))
    assert not new, f"read GL class codes through sqs_service.gl_class_codes(_present) / " \
                    f"gl_classification_text, or register the different question: {new}"


def test_the_cross_form_rules_ask_the_door_and_never_stringify_class_codes():
    import inspect
    for fn in (CFV._check_gl_class_code_vs_operations, CFV._check_wc_gl_class_code_alignment,
               CFV._check_acord101_triggers):
        src = inspect.getsource(fn)
        assert '"gl_class_codes_by_location"' not in src, fn.__name__
        assert "str(gl_codes)" not in src and "str(wc_codes)" not in src, fn.__name__


# ══ 2. One "person put this" door ═════════════════════════════════════════════
from services import fact_state as FS                     # noqa: E402

_SHAPES = {
    "typed_producer": {"value": "x", "source": "producer"},
    "typed_client": {"value": "x", "source": "client_arq", "confidence": "client_arq"},
    "picked": {"value": "x", "source": "user_confirmed"},
    "confirm_or_correct": {"value": "x", "source": "dec_entry", "evidence_state": "user_confirmed"},
    "account": {"value": "x", "source": "account", "evidence_state": "user_confirmed"},
    "document": {"value": "x", "source": "dec_entry"},
    "derived": {"value": "x", "source": "derived"},
    "bare": "x",
    "table_mark": {"source": "producer", "fingerprint": "f"},
    "never_written": {"value": "x", "source": "cross_form_conflict"},
}


@pytest.mark.parametrize("name,typed,put,confirmed", [
    ("typed_producer", True, True, True), ("typed_client", True, True, True),
    ("picked", False, True, True), ("confirm_or_correct", False, False, True),
    ("account", False, False, True), ("document", False, False, False),
    ("derived", False, False, False), ("bare", False, False, False),
    ("table_mark", False, False, False), ("never_written", False, False, False),
])
def test_three_questions_on_every_shape(name, typed, put, confirmed):
    raw = _SHAPES[name]
    assert FS.typed_by_person(raw) is typed
    assert FS.put_by_person(raw) is put
    assert FS.confirmed_by_person(raw) is confirmed


def test_put_is_between_typed_and_confirmed_and_the_vocabulary_is_one_table():
    for raw in _SHAPES.values():
        assert not FS.typed_by_person(raw) or FS.put_by_person(raw)
        assert not FS.put_by_person(raw) or FS.confirmed_by_person(raw)
    assert FS.PERSON_VALUE_SOURCES == frozenset(FS._HUMAN_SOURCES)
    assert FS.PERSON_BOX_LABELS == FS.PERSON_ENTRY_SOURCES
    assert FS.typed_box("producer") and FS.typed_box("client_arq")
    assert not FS.typed_box("user_confirmed") and not FS.typed_box("ai_verified") and not FS.typed_box(None)


def test_routed_readers_answer_through_the_door():
    from services import insured_scope, umbrella_layers, coverage_evidence, issue_registry
    for name, raw in _SHAPES.items():
        assert insured_scope._is_human(raw) is FS.put_by_person(raw), name
        assert umbrella_layers._person_sourced(raw) is FS.put_by_person(raw), name
        assert issue_registry._is_human_supplied(raw) is FS.typed_by_person(raw), name
    assert CFV._umbrella_dates_are_proposed({"umbrella_effective_date": _SHAPES["picked"]})
    assert not CFV._umbrella_dates_are_proposed({"umbrella_effective_date": _SHAPES["document"]})
    held = {"wc_payroll_period": dict(_SHAPES["typed_producer"], value_state="not_applicable")}
    assert coverage_evidence._human_recorded_state(held, "wc_payroll_period") == "not_applicable"
    held = {"wc_payroll_period": dict(_SHAPES["derived"], value_state="not_applicable")}
    assert coverage_evidence._human_recorded_state(held, "wc_payroll_period") is None


def test_no_private_person_vocabulary_outside_fact_state():
    """Every set / tuple / list literal naming a person's source lives in
    fact_state; the two kept elsewhere are DIFFERENT questions, built from it."""
    offenders = []
    for sub in ("services", "routes", "utils", "models"):
        for p in sorted((BACKEND / sub).rglob("*.py")):
            if p.name == "fact_state.py":
                continue
            for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
                if isinstance(n, (ast.Set, ast.Tuple, ast.List)):
                    vals = {e.value for e in n.elts if isinstance(e, ast.Constant)}
                    if "client_arq" in vals and vals & {"producer", "user_confirmed"}:
                        offenders.append(f"{p.relative_to(BACKEND)}:{n.lineno}")
    assert offenders == [], f"use fact_state's door (typed_by_person / put_by_person / typed_box): {offenders}"
    from services import pdf_service as PS, extraction_service as ES, loss_history_state as LH
    assert PS._TYPED_VALUE_SOURCES == FS.PERSON_ENTRY_SOURCES | {"account"}      # casing counts the account
    # our derivation names a period; a filled ACORD form's box STATES it (27 Oct 2026 round trip) - both from
    # fact_state's own constants, never a private vocabulary
    assert ES._PERIOD_NAMED_SOURCES == FS.PERSON_ENTRY_SOURCES | {"derived"} | FS.FORM_BOX_SOURCES
    assert ES._PERSON_FACT_SOURCES is FS.PERSON_VALUE_SOURCES
    assert not hasattr(LH, "_HUMAN_SOURCES")


# ══ 3. A name question is answered by a name ══════════════════════════════════
from services.answer_semantics import (                  # noqa: E402
    ABSENCE, NOT_A_NAME, UNKNOWN, VALUE, interpret_answer, name_answer_refusal,
)


@pytest.mark.parametrize("text", ["None at this time", "None currently", "Nothing yet",
                                  "N/A", "none", "n/a at this time"])
@pytest.mark.parametrize("fact", ["applicant_name", "effective_date", "mailing_address",
                                  "lines_of_business"])
def test_a_required_fact_never_takes_an_absence_in_any_spelling(fact, text):
    got = interpret_answer(fact, text)
    assert got.intent == UNKNOWN and got.reason == "required_cannot_be_absent"


@pytest.mark.parametrize("text", ["Same as above", "see above", "As above", "Ditto", "FIO",
                                  "Sample", "Void", "Owner", "Insured", "Agency", "Same as applicant"])
@pytest.mark.parametrize("fact", ["applicant_name", "dba_name", "contact_name", "carrier_name",
                                  "producer_name", "prior_carrier", "landlord_name",
                                  "submission_carrier_name", "builders_risk_owner_name"])
def test_a_placeholder_back_reference_or_role_is_no_name(fact, text):
    got = interpret_answer(fact, text)
    assert got.intent == UNKNOWN and not got.accepted, (fact, text, got)
    assert name_answer_refusal(fact, text)


@pytest.mark.parametrize("name", ["Acme Roofing LLC", "Same Day Delivery LLC", "Sample Electric Inc",
                                  "Void Studios LLC", "Smith", "FIO Holdings LLC"])
def test_a_real_name_containing_those_words_is_a_name(name):
    for fact in ("applicant_name", "dba_name", "carrier_name"):
        got = interpret_answer(fact, name)
        assert got.intent == VALUE and got.value == name


def test_an_optional_name_keeps_its_absence_and_non_name_facts_are_untouched():
    assert interpret_answer("dba_name", "None at this time").intent == ABSENCE
    assert interpret_answer("prior_carrier", "None").intent == ABSENCE
    assert interpret_answer("operations_description", "Same as above").intent == VALUE
    assert interpret_answer("qn_carrier_narrative", "Same as above").intent == VALUE
    assert name_answer_refusal("operations_description", "FIO") == ""


def test_the_client_door_holds_a_non_name_instead_of_applying_it():
    from services.arq_service import _answer_check_refusal
    assert _answer_check_refusal("dba_name", "NamedInsured_DBAName_A", "Same as above")
    assert _answer_check_refusal("mortgagee_name", "Mortgagee_A", "FIO")
    assert _answer_check_refusal("dba_name", "NamedInsured_DBAName_A", "Acme Roofing") == ""
    assert _answer_check_refusal("dba_name", "NamedInsured_DBAName_A", "None") == ""   # an absence


def test_data_consistency_confirm_refuses_a_non_name():
    from services.underwriting_consistency import validate_confirmation
    for bad in ("Same as above", "FIO", "None at this time"):
        with pytest.raises(ValueError):
            validate_confirmation("applicant_name", bad)
    assert validate_confirmation("applicant_name", "Acme Roofing LLC")


def test_the_producer_card_refuses_a_non_name():
    from routes.audit_routes import _validate_producer_answer
    ok, msg = _validate_producer_answer("applicant_name", "None at this time")
    assert not ok and msg
    ok, _ = _validate_producer_answer("contact_name", "Owner")
    assert not ok


def test_the_editor_name_check_is_wired_before_the_fact_write():
    src = (BACKEND / "routes" / "form_routes.py").read_text(encoding="utf-8")
    i = src.index("A NAME BOX TAKES A NAME")
    assert src.index("is_party_name_fact", i) < src.index('"source": "producer"}', i)


# ══ 4. Rare parsing leftovers ═════════════════════════════════════════════════
from services.insured_scope import (                     # noqa: E402
    address_is_a_party_office as _office, is_the_insureds_own_name,
)

_INS = "100 Insurance Way, Columbus OH 43215"


@pytest.mark.parametrize("above,own,expected", [
    ("Mutual Plumbing LLC   C/O   Grange Mutual", ["Mutual Plumbing LLC"], True),   # c/o in another column
    ("Mutual Plumbing LLC   C/O   Smith Accounting", ["Mutual Plumbing LLC"], False),  # a real mailing c/o
    ("Mutual Plumbing LLC, care of Grange Mutual Ins Co", ["Mutual Plumbing LLC"], True),
    ("ACME ROOFING LLC", ["Acme Roofing LLC"], False),
])
def test_4a_a_care_of_party_owns_the_address_below_it(above, own, expected):
    assert _office(_INS, [f"{above}\n{_INS}"], own_names=own) is expected


@pytest.mark.parametrize("text,expected", [
    ("NAME | TITLE | OWNERSHIP\nJane Roe | President | 60%\nCONTACT | ROLE | PHONE\n"
     "Marcus Ruiz | Secretary | 303-555-0100", set()),
    ("NAME | TITLE | OWNERSHIP\nJane Roe | President | 60%\nNAMED INSURED | ENTITY | FEIN\n"
     "Marcus Ruiz | Partner | 12-3456789", set()),
    ("NAME | TITLE | OWNERSHIP\nJane Roe | President | 60%\nEMPLOYEE | CLASS | DUTIES\n"
     "Marcus Ruiz | Manager | Field supervision", set()),
    ("| NAME | TITLE | OWN % |\n|---|---|---|\n| Jane Roe | President | 60% |\n"
     "| Marcus Ruiz | Vice President | 40% |", {"Vice President"}),
    ("NAME | TITLE | INCLUDED/EXCLUDED\nJANE ROE | MEMBER | INCLUDED\n"
     "MARCUS RUIZ | MANAGING MEMBER | EXCLUDED", {"MANAGING MEMBER"}),
])
def test_4b_an_officer_table_ends_at_the_next_tables_header(text, expected):
    from services.extraction_service import _titles_printed_for
    assert _titles_printed_for("Marcus Ruiz", [{"text": text}]) == expected


@pytest.mark.parametrize("name", ["Mutual Plumbing Company", "Farmers Mutual Grain Co-op",
                                  "Plumbers Mutual Supply Inc"])
def test_4c_an_applicant_named_mutual_is_never_its_own_insurer(name):
    from services.field_mapping_integrity import is_value_contaminated
    from services.pdf_service import _insurer_in_a_party_box
    from services.extraction_service import _page_header_insurers
    facts = {"applicant_name": {"value": name, "source": "dec_entry"}}
    assert is_the_insureds_own_name(name.upper(), facts)
    assert not is_value_contaminated("AdditionalInterest_FullName_A", name, facts)
    assert _insurer_in_a_party_box({"AdditionalInterest_FullName_A": name}, facts,
                                   {"AdditionalInterest_FullName_A"}) == {}
    page = f"[Document page 1]\n{name.upper()}\nCOMMERCIAL GENERAL LIABILITY DECLARATIONS\n"
    assert _page_header_insurers(page, facts) == []
    # a REAL insurer beside it is still read
    real = {"AdditionalInterest_FullName_A": "Grange Mutual Casualty Company"}
    assert _insurer_in_a_party_box(real, facts, set(real))
    assert not is_the_insureds_own_name("Grange Mutual Casualty Company", facts)


@pytest.mark.parametrize("text,own,expected", [
    ("AMERISURE INSURANCE COMPANY\nNamed Insured: Choice Electric LLC\nHome Office: 456 Oak Ave, Denver CO",
     ["Choice Electric LLC"], False),
    ("AMERISURE INSURANCE COMPANY\nCHOICE ELECTRIC LLC\nHome Office: 456 Oak Ave, Denver CO",
     ["Choice Electric LLC"], False),
    ("AMERISURE MUTUAL INSURANCE COMPANY\nA stock company\nHome Office: 456 Oak Ave, Denver CO",
     ["Choice Electric LLC"], True),
])
def test_4d_home_office_under_the_insureds_own_line_is_the_insureds(text, own, expected):
    assert _office("456 Oak Ave, Denver CO", [text], own_names=own) is expected


@pytest.mark.parametrize("cell,use", [("NA", None), ("N.A.", None), ("N/A", None), ("UNK", None),
                                      ("NONE", None), ("SERVICE", "Service")])
def test_4e_a_use_non_answer_in_any_spelling_is_never_the_policy_use(cell, use):
    from services.extraction_service import _read_vehicle_block_cells
    vin = "4S4BRCGC9C3217772"
    mf = {"auto_vehicle_use": {"value": "commercial", "source": "ai"},
          "auto_vin_schedule": [{"vin": vin}]}
    _read_vehicle_block_cells(mf, [{"text": f"2012 SUBARU OUTBACK ID NO {vin}.\n"
                                            f"COST NEW: 26680 RADIUS: NA USE: {cell} ."}])
    got = mf.get("auto_vehicle_use")
    value = got.get("value") if isinstance(got, dict) else got
    assert value == use if use else not value


def test_4e_an_unread_cell_decides_nothing():
    from services.extraction_service import _read_vehicle_block_cells
    vin = "4S4BRCGC9C3217772"
    mf = {"auto_vehicle_use": {"value": "commercial", "source": "ai"}, "auto_vin_schedule": [{"vin": vin}]}
    _read_vehicle_block_cells(mf, [{"text": f"ID NO {vin}.\nUSE: NOT APPL ."}])
    assert mf["auto_vehicle_use"]["value"] == "commercial"
    assert not mf["auto_vin_schedule"][0].get("use")


# ══ 5. Unread answers: shape only, encrypted, admin route ═════════════════════
from services import unread_answers as UA                 # noqa: E402


def test_the_shape_carries_no_amount_date_email_or_id():
    s = UA.shape_of("About $52,000 per yr - call pat@acme.com re VIN 1FTFW1ET5DFC10312 on 07/15/2026")
    assert "52" not in s and "pat@" not in s and "1ftfw" not in s and "2026" not in s
    assert "<email>" in s and "<id>" in s and "#" in s
    assert UA.shape_of("") == "" and UA.shape_of(None) == ""
    assert len(UA.shape_of("x " * 200)) <= 80


def test_an_unreadable_answer_is_noted_and_a_preview_is_not():
    UA._take_pending()
    interpret_answer("total_revenue", "about fifty grand-ish 12x")
    assert UA.pending_count() == 1
    with UA.not_counted():
        interpret_answer("total_revenue", "about fifty grand-ish 12x")
    assert UA.pending_count() == 1
    batch = UA._take_pending()
    assert list(batch) == [("total_revenue", "currency", UA.shape_of("about fifty grand-ish 12x"))]


class _Conn:
    def __init__(self, store):
        self.store = store

    async def execute(self, sql, *a):
        h, fact, kind, enc, count, now = a
        row = self.store.setdefault(h, {"fact_key": fact, "kind": kind, "shape_enc": enc,
                                        "seen_count": 0, "first_seen": now, "last_seen": now})
        row["seen_count"] += count
        row["last_seen"] = now

    async def fetch(self, sql, *a):
        rows = list(self.store.values())
        if "WHERE fact_key" in sql:
            rows = [r for r in rows if r["fact_key"] == a[0]]
        return sorted(rows, key=lambda r: -r["seen_count"])


class _Pool:
    def __init__(self, store):
        self.store = store

    def acquire(self):
        conn = _Conn(self.store)

        class _Ctx:
            async def __aenter__(s):
                return conn

            async def __aexit__(s, *x):
                return False
        return _Ctx()


def test_flush_upserts_one_encrypted_row_per_phrasing_and_the_report_decrypts():
    store = {}
    UA._take_pending()
    for _ in range(3):
        UA.note("total_revenue", "currency", "about 50k")
    UA.note("wc_payroll", "currency", "about 50k")
    with patch("config.database.get_pool", lambda: _Pool(store)):
        assert asyncio.run(UA.flush_pending()) == 2         # duplicates in one batch fold
        UA.note("total_revenue", "currency", "about 70k")   # same shape -> same row
        asyncio.run(UA.flush_pending())
        rows = asyncio.run(UA.top_unread(10))
    assert all(r["shape_enc"].startswith("enc:") for r in store.values())   # never plain at rest
    assert all("about" not in r["shape_enc"] for r in store.values())
    top = rows[0]
    assert (top["fact"], top["shape"], top["count"]) == ("total_revenue", "about #k", 2)
    assert set(UA.by_fact(rows)) == {"total_revenue", "wc_payroll"}


def test_a_failed_flush_keeps_the_entries():
    UA._take_pending()
    UA.note("total_revenue", "currency", "about 50k")

    def _boom():
        raise RuntimeError("no pool")
    with patch("config.database.get_pool", _boom):
        assert asyncio.run(UA.flush_pending()) == 0
    assert UA.pending_count() == 1
    UA._take_pending()


def test_schema_and_admin_route_exist():
    db = (BACKEND / "config" / "database.py").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS answer_fallthroughs" in db
    from routes import admin_routes
    r = next(r for r in admin_routes.router.routes if r.path.endswith("/unread-answers"))
    deps = [d.call for d in r.dependant.dependencies]
    assert admin_routes._require_admin in deps


# ══ 6. Dismiss-then-fill: one source of points per fact ═══════════════════════
import repositories.session_repository as sr               # noqa: E402
import routes.audit_routes as ar                           # noqa: E402
import services.arq_service as arq                         # noqa: E402
import services.audit_service as au                        # noqa: E402
from models.schemas import AnswerRecommendationRequest     # noqa: E402

_SID, _UID = "sid-laneb6", "u-laneb6"


def _md(d):
    return d.strftime("%m/%d/%Y")


def _row(drop):
    prod = lambda v: {"value": v, "source": "producer", "confidence": "filled"}   # noqa: E731
    f = {"producer_name": "Best Agency", "applicant_name": "Acme LLC",
         "mailing_address": "1 Main St, Denver, CO 80202", "lines_of_business": "General Liability",
         "entity_type": "LLC", "contact_phone": "303-555-0100", "contact_name": "Pat Doe",
         "contact_email": "pat@acme.com", "fein": "12-3456789",
         "operations_description": "Electrical contracting", "total_revenue": "$1,200,000",
         "num_employees": "12", "years_in_business": "8", "naics_code": "238210",
         "effective_date": prod(_md(datetime.now() + timedelta(days=30))),
         "expiration_date": prod(_md(datetime.now() + timedelta(days=395)))}
    f.pop(drop, None)
    return {"user_id": _UID, "facts": f, "flags": {"has_general_liability": True},
            "hard_stops": [], "soft_stops": [], "recommendations": [{"form_id": "ACORD_125"}],
            "cross_form_issues": [], "structured_issues": [], "docs": [], "integrity": {},
            "generated_forms": {"ACORD_125": {"mapped": {"NamedInsured_FullName_A": "Acme LLC"},
                                              "confidence": {"NamedInsured_FullName_A": "ai_high"},
                                              "schema": {"NamedInsured_FullName_A": {"ft": "/Tx", "tu": "Enter name"}}}},
            "selected_form_ids": ["ACORD_125"], "underwriting_consistency": {}}


class _Session:
    """The REAL answer route and recalculation over an in-memory row; the
    dismissal list is the audit table's, and `active_score_credits` is REAL."""

    def __init__(self, row, dismissed=()):
        self.store, self.dismissed = copy.deepcopy(row), list(dismissed)

    async def _get(self, _s):
        return copy.deepcopy(self.store)

    async def _upd(self, _s, payload, delete_facts=None):
        for k, v in (payload or {}).items():
            v = copy.deepcopy(v)
            if k == "facts" and isinstance(v, dict):
                m = sr.resolve_facts_write(self.store, v, _s)
                if m is not None:
                    self.store["facts"] = m
            elif k == "generated_forms" and isinstance(v, dict):
                g = self.store.setdefault("generated_forms", {})
                for fid, d in v.items():
                    g[fid] = {**g[fid], **d} if isinstance(g.get(fid), dict) else d
            else:
                self.store[k] = v
        for k in (delete_facts or []):
            self.store.get("facts", {}).pop(k, None)
        return True

    def run(self, fn, *a, **k):
        async def _none(*_a, **_k):
            return None

        async def _empty(*_a, **_k):
            return []

        async def _dism(*_a, **_k):
            return copy.deepcopy(self.dismissed)
        with patch.object(sr, "get_processing_session", self._get), \
             patch.object(sr, "upd_processing_session", self._upd), \
             patch.object(ar, "get_processing_session", self._get), \
             patch.object(ar, "log_field_change", _none), \
             patch.object(ar, "mark_recommendation_answer_recorded", _none), \
             patch.object(ar, "get_open_recommendations", _empty), \
             patch.object(au, "log_audit_event", _none), \
             patch.object(au, "log_sqs_snapshot_if_changed", _none), \
             patch.object(au, "get_open_recommendations", _empty), \
             patch.object(au, "mark_recommendation_resolved", _none), \
             patch.object(au, "sync_recommendation_cards", _none), \
             patch.object(au, "get_dismissed_recommendations", _dism):
            return asyncio.run(fn(*a, **k))

    def answer(self, field, text):
        req = AnswerRecommendationRequest(session_id=_SID, rec_id="rec_x", field=field, answer=text,
                                          message="m", score_impact=6, form_id="ACORD_125")
        return json.loads(self.run(ar.answer_recommendation, req, current_user={"id": _UID}).body)

    def score(self):
        return (self.store.get("package_sqs") or {}).get("package_sqs_score")


def _dismissal(field):
    return [{"rec_id": "rec_x", "form_id": "ACORD_125", "field": field, "message": "m",
             "score_impact": 6, "override_reason": "Client will send it", "action_at": None,
             "user_id": _UID}]


# 29 Oct 2026: "None" / "N/A" are refused on the revenue (every business has
# one), so the absences are shown on the employee count, which takes them.
@pytest.mark.parametrize("field,text", [("num_employees", "None"), ("num_employees", "N/A"),
                                        ("total_revenue", "1200000")])
def test_dismiss_then_answer_counts_the_gap_once(field, text):
    plain = _Session(_row(field))
    plain.run(arq.recalculate_session_scores, _SID)
    gap = plain.score()
    plain.answer(field, text)
    want = plain.score()                                   # the answer, no dismissal

    s = _Session(_row(field), _dismissal(field))
    s.run(arq.recalculate_session_scores, _SID)
    assert s.score() == min(100, gap + 6) or s.score() > gap      # the credit is in force
    assert s.answer(field, text)["success"]
    assert s.score() == want                                # never credit + pillar (was +6 on "None")


def test_reopen_without_the_dismissal_scores_as_never_dismissed():
    s = _Session(_row("total_revenue"))                     # the reopened row is not "dismissed"
    s.run(arq.recalculate_session_scores, _SID)
    d = _Session(_row("total_revenue"), _dismissal("total_revenue"))
    d.run(arq.recalculate_session_scores, _SID)
    d.dismissed = []
    d.run(arq.recalculate_session_scores, _SID)
    assert d.score() == s.score()


def test_a_gl_card_is_answered_by_the_gl_window():
    rows = [{"rec_id": "r", "field": "gl_class_codes_by_location", "score_impact": 5,
             "override_reason": "later", "message": "m"}]

    async def _d(*_a, **_k):
        return rows
    with patch.object(au, "get_dismissed_recommendations", _d):
        total, _ = asyncio.run(au.active_score_credits("s", facts=_SCHED_ONLY))
        assert total == 0                                   # answered through the schedule home
        total, _ = asyncio.run(au.active_score_credits("s", facts={}))
        assert total == 5


def test_the_dismiss_route_reads_encrypted_facts():
    """`data->'facts'` is "enc:...": the retirement check got no facts at all."""
    from utils.crypto import encrypt_field
    facts = {"total_revenue": {"value": "", "value_state": "explicit_no", "source": "producer"}}
    enc = encrypt_field(json.dumps(facts))
    assert ar._readable_facts(enc) == facts
    assert ar._readable_facts(json.dumps(facts)) == facts              # a legacy plain row
    assert ar._readable_facts(facts) == facts
    assert ar._readable_facts(None) is None and ar._readable_facts("garbage") is None


# ══ 7. HIGH confidence needs a structural lead ════════════════════════════════
from services.underwriting_consistency import _suggest_for_field   # noqa: E402


def _g(display, docs):
    return {"display": display, "normalized": display.lower(), "sources": [{"doc_id": d} for d in docs]}


def test_verbosity_alone_never_makes_a_high_confidence_address():
    got = _suggest_for_field("mailing_address", "identity", [
        _g("1 Main St Suite 100 Building B Attn Accounts Payable Dept Denver CO 80202", ["a"]),
        _g("1 Main St, Denver, CO 80202", ["b"])])
    assert got["confidence"] == "medium" and got["preselect"] is False


def test_a_long_annotation_never_makes_a_high_confidence_text():
    got = _suggest_for_field("carrier_name", "identity", [
        _g("EMC Insurance " + "endorsement clause words " * 6, ["a"]), _g("EMC", ["b"])])
    assert got is None or got["confidence"] != "high"


@pytest.mark.parametrize("top,second", [
    ("1 Main St, Denver, CO 80202-1234", "1 Main St, Denver, CO 80202"),     # ZIP+4 over ZIP
    ("1 Main St, Denver, CO 80202", "1 Main St Denver"),                     # ZIP + state
])
def test_a_structural_lead_is_still_high(top, second):
    got = _suggest_for_field("mailing_address", "identity", [_g(top, ["a"]), _g(second, ["b"])])
    assert got["confidence"] == "high" and got["value"] == top


def test_fein_completeness_is_high_but_never_preselected():
    got = _suggest_for_field("fein", "identity", [_g("12-3456789", ["a"]), _g("12-34567", ["b"])])
    assert got["confidence"] == "high" and got["preselect"] is False
