"""27 Oct 2026 - items handled outside the three build lanes.

1. A quote titled "Quotation" is a quote (23 Oct #4's test package was filed as a
   narrative, so ACORD 125 page one withheld the premiums it quotes).
2. Shutdown never waits for ever on a held database connection.
3. Every detached background task the app starts is held by reference.
"""
import ast
import json
import asyncio
import os

import pytest

from services.extraction_service import classify_document

_QUOTE_TEXT = """WESTBRIDGE MUTUAL INSURANCE COMPANY
COMMERCIAL INSURANCE QUOTATION - NEW BUSINESS
Quote Number: Q-2026-118204 Quote Date: 10/20/2026
This quotation is for new business. The applicant has no prior policy with this company.
APPLICANT / NAMED INSURED
Name of Insured: Pinecrest Landscaping LLC
Mailing Address: 2215 Juniper Ave, Boulder, CO 80304
Description of Operations: Commercial landscape installation and grounds maintenance.
PROPOSED POLICY PERIOD: 12/01/2026 to 12/01/2027
COVERAGES QUOTED
Line of Business Limits Annual Premium
Commercial General Liability $1,000,000 Each Occurrence / $2,000,000 Aggregate $4,200
Commercial Auto $1,000,000 Combined Single Limit
Commercial Property Building $450,000 / BPP $120,000 $3,100
Location 1: 2215 Juniper Ave, Boulder, CO 80304 - office and equipment yard, frame construction, built 1998.
"""


def test_a_quotation_is_a_quote_whatever_the_filename():
    for name in ("Pinecrest_Quote.pdf", "scan_0001.pdf", None):
        assert classify_document(_QUOTE_TEXT, name)["doc_type"] == "quote"


def test_a_narrative_mentioning_a_quotation_once_stays_a_narrative():
    narrative = (
        "Account overview: Pinecrest Landscaping LLC has operated for 12 years. Operations: commercial "
        "landscape installation. Management: owner-run, 20 years of experience. Locations: one yard in "
        "Boulder. Loss history: no claims in five years. Coverage discussion: the insured wants higher "
        "limits. Safety: weekly tailgate meetings. We would appreciate your quotation.")
    assert classify_document(narrative, "Pinecrest narrative.docx")["doc_type"] == "narrative"


def test_a_dec_page_is_not_a_quote():
    dec = ("COMMERCIAL GENERAL LIABILITY DECLARATIONS\nPolicy Number: CGL-4471\nPolicy Period: 12/01/2025 "
           "to 12/01/2026\nNamed Insured: Pinecrest Landscaping LLC\nEach Occurrence $1,000,000\n"
           "General Aggregate $2,000,000\nTotal Premium $4,200\nThese declarations are part of the policy.")
    assert classify_document(dec, "dec.pdf")["doc_type"] != "quote"


class _StuckPool:
    def __init__(self):
        self.terminated = False

    async def close(self):
        await asyncio.sleep(3600)          # a connection never released

    def terminate(self):
        self.terminated = True


class _GoodPool:
    closed = False

    async def close(self):
        _GoodPool.closed = True


def test_close_pool_terminates_after_its_limit(monkeypatch):
    import config.database as db
    stuck = _StuckPool()
    monkeypatch.setattr(db, "_pool", stuck)
    asyncio.run(db.close_pool(timeout=0.05))
    assert stuck.terminated and db._pool is None


def test_close_pool_closes_gracefully_when_it_can(monkeypatch):
    import config.database as db
    monkeypatch.setattr(db, "_pool", _GoodPool())
    asyncio.run(db.close_pool(timeout=1))
    assert _GoodPool.closed and db._pool is None


def test_close_pool_with_no_pool_is_a_no_op(monkeypatch):
    import config.database as db
    monkeypatch.setattr(db, "_pool", None)
    asyncio.run(db.close_pool(timeout=0.01))
    assert db._pool is None


def test_every_detached_task_is_held_by_reference():
    """`asyncio.ensure_future` / `create_task` whose result is thrown away can be
    garbage-collected mid-run - the loop keeps only a weak reference."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    offenders = []
    for sub in ("services", "routes"):
        for dirpath, _, files in os.walk(os.path.join(root, sub)):
            for fn in files:
                if not fn.endswith(".py"):
                    continue
                path = os.path.join(dirpath, fn)
                tree = ast.parse(open(path, encoding="utf-8").read())
                for node in ast.walk(tree):
                    if (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
                            and isinstance(node.value.func, ast.Attribute)
                            and node.value.func.attr in ("ensure_future", "create_task")):
                        offenders.append(f"{os.path.relpath(path, root)}:{node.lineno}")
    assert not offenders, f"task result thrown away (keep a reference): {offenders}"


# ── 4. Dashboard search reads the CURRENT applicant name (facts are encrypted) ──
from repositories import session_repository as sr


@pytest.mark.parametrize("search,names,hit", [
    ("choice electric llc", ["CHOICE ELECTRIC, LLC"], True),
    ("oneil", ["O'Neil Roofing"], True),
    ("  Pine  ", [None, "Pinecrest Landscaping"], True),
    ("harbor", ["Choice Electric"], False),
    ("", ["anything"], True),
    ("%", ["100% Roofing"], True),            # no letters: matched literally
    ("%", ["Roofing"], False),
    ("_", ["Pine_crest"], True),
    ("ele", [None, None], False),
])
def test_name_matches_search(search, names, hit):
    assert sr.name_matches_search(search, *names) is hit


def test_every_write_keeps_an_encrypted_search_name():
    out = sr._encrypt_facts({"facts": {"applicant_name": {"value": "Choice Electric LLC"}}})
    assert out[sr.SEARCH_NAME_KEY] != "Choice Electric LLC"          # never plaintext
    assert sr._search_name(out[sr.SEARCH_NAME_KEY]) == "Choice Electric LLC"
    gone = sr._encrypt_facts({"facts": {"fein": "84-1"}, sr.SEARCH_NAME_KEY: out[sr.SEARCH_NAME_KEY]})
    assert sr.SEARCH_NAME_KEY not in gone                            # name removed -> copy removed
    assert sr._search_name(None) == "" and sr._search_name("enc:garbage") == ""


class _Conn:
    def __init__(self, rows):
        self.rows = rows

    backfilled: list = []

    async def fetch(self, sql, *a):
        assert "ILIKE" not in sql
        if "ANY($2" in sql:                               # the legacy batch
            return [{"id": r["id"], "facts": r["facts"]} for r in self.rows if r["id"] in a[1]]
        assert "facts" not in sql.split("FROM")[0]        # the list query never pulls facts
        return self.rows

    async def executemany(self, sql, pairs):
        assert "search_name" in sql and "IS NULL" in sql and "updated_at" not in sql
        _Conn.backfilled.extend(pairs)


class _Pool:
    def __init__(self, rows):
        self.rows = rows

    def acquire(self):
        pool = self

        class _Ctx:
            async def __aenter__(self):
                return _Conn(pool.rows)

            async def __aexit__(self, *a):
                return False
        return _Ctx()


def test_search_finds_a_renamed_package_and_a_legacy_one(monkeypatch):
    enc = sr._encrypt_facts({"facts": {"applicant_name": "Choice Electric LLC"}})
    legacy = sr._encrypt_facts({"facts": {"applicant_name": "Harborline Plumbing"}})["facts"]
    rows = [
        # label from upload is stale; the current name (search copy) matches
        {"id": "a", "updated_at": 2, "label": "Old Name Inc", "search_name": enc[sr.SEARCH_NAME_KEY], "facts": None},
        # saved before the search copy existed: facts decrypted once
        {"id": "b", "updated_at": 1, "label": "", "search_name": None, "facts": json.dumps(legacy)},
        {"id": "c", "updated_at": 0, "label": "Pinecrest", "search_name": None, "facts": json.dumps({"applicant_name": "x"})},
    ]
    monkeypatch.setattr(sr, "get_pool", lambda: _Pool(rows))
    sr._MATCH_CACHE.clear()
    run = lambda q: asyncio.run(sr._match_session_ids("u", q, False))
    assert run("choice") == ["a"]
    assert run("old name") == ["a"]                  # the label still counts
    assert run("harbor") == ["b"]
    assert run("pinecrest") == ["c"]
    assert run("nobody") == []
    # the legacy package got its encrypted copy back-filled, by id
    assert {pid for pid, _ in _Conn.backfilled} == {"b", "c"}
    assert all(sr._search_name(enc_) for _, enc_ in _Conn.backfilled)


# ── 5. ACORD 130: an ANNIVERSARY period needs a WC run on that anniversary ──
from services import pdf_service as pdf


def _f130(span, terms=None):
    return {"_form_id": "ACORD_130",
            "loss_history": {"value": [{"date": "03/02/2023", "line_of_business": "Workers Compensation",
                                        "paid": "1000", "reserved_amount": "0", "open": False}]},
            pdf.WC_LOSS_RUN_SPANS_KEY: [span],
            "coverage_lines": terms if terms is not None else [
                {"line": "Workers Compensation", "effective_date": "01/01/2025", "expiration_date": "01/01/2026"}]}


def test_130_anniversary_period_backed_by_the_runs_printed_period_prints():
    got = pdf.wc_period_loss_values({"PriorCoverage_EffectiveYear_A": "2023"}, _f130(["2021-01-01", "2026-01-01"]))
    assert got.get("LossHistory_ClaimCount_A") == "1"


def test_130_anniversary_period_the_runs_do_not_run_on_stays_blank():
    # The run's printed periods run 07/01 - 07/01 (a prior carrier's renewal
    # date); the current term's 01/01 anniversary is a guess for 2023.
    got = pdf.wc_period_loss_values({"PriorCoverage_EffectiveYear_A": "2023"}, _f130(["2020-07-01", "2025-07-01"]))
    assert got == {}


def test_130_a_recorded_term_needs_no_anniversary_check():
    terms = [{"line": "Workers Compensation", "effective_date": "07/15/2023", "expiration_date": "07/15/2024"}]
    got = pdf.wc_period_loss_values({"PriorCoverage_EffectiveYear_A": "2023"},
                                    _f130(["2023-01-01", "2025-01-01"], terms))
    assert got.get("LossHistory_ClaimCount_A") == "0"   # the claim (03/2023) is before the term


# ── 6. Rule (h) does not judge questions about the insured's practice / history ──
from services import scoped_evidence as se


@pytest.mark.parametrize("q,exempt", [
    ("Do subcontractors carry coverages or limits less than applicant?", True),
    ("Are subcontractors allowed to work without providing you with a certificate of insurance?", True),
    ("Has any product, work, accident or location been excluded, uninsured or self-insured from any previous coverage?", True),
    ("Any policy or coverage declined, cancelled or non-renewed during the mandated number of years?", True),
    ("Was tail coverage purchased under any previous policy?", True),
    ("Any work sublet without certificates of insurance?", True),
    ("Indicates the general aggregate limit applies per project.", False),
    ("Any operation or owned, leased or rented property not covered by this policy?", False),
    ("Indicates the claims made option applies on the general liability policy.", False),
])
def test_applicant_practice_or_history_questions_are_exempt(q, exempt):
    assert se._asks_about_the_applicants_practice_or_history(q) is exempt


# ── 7. A real name that starts with an absence word is a name ──
from services.answer_semantics import interpret_answer, name_answer_refusal

_NAMES = ["TBD Construction", "N/A Holdings", "Unknown Builders", "No Limits Roofing", "Pending Review Co",
          "None Such LLC", "Nothing Bundt Cakes", "Zero Gravity", "Ann Owens", "O'Neil & Sons",
          "Agency Partners LLC", "Holder Brothers Farm"]
_NON_ANSWERS = ["TBD", "N/A", "TBD - will send", "none at this time", "N/A see attached",
                "Unknown, ask the client", "pending from the insured", "Not sure yet", "TBD by client",
                "will send later", "No DBA", "None - no agency", "No carrier", "none", "same as above",
                "Owner", "FIO", "unknown at present", "n / a", "TBD 2026"]


@pytest.mark.parametrize("name", _NAMES)
@pytest.mark.parametrize("fact", ["applicant_name", "dba_name"])
def test_real_names_are_accepted(name, fact):
    assert not name_answer_refusal(fact, name) and interpret_answer(fact, name).value == name


@pytest.mark.parametrize("text", _NON_ANSWERS)
def test_non_answers_are_never_a_name(text):
    assert name_answer_refusal("applicant_name", text) or not interpret_answer("applicant_name", text).value


class _BackfillConn:
    def __init__(self, store):
        self.store = store

    async def fetch(self, sql, skipped, limit):
        return [{"id": k, "facts": v} for k, v in self.store["rows"].items()
                if k not in skipped and k not in self.store["filled"]][:limit]

    async def executemany(self, sql, pairs):
        if self.store.get("fail"):
            raise RuntimeError("db down")
        self.store["filled"].update(dict(pairs))


def _bf_pool(store):
    class _P:
        def acquire(self):
            class _C:
                async def __aenter__(self_):
                    return _BackfillConn(store)

                async def __aexit__(self_, *a):
                    return False
            return _C()
    return _P()


def test_startup_backfill_fills_once_and_never_loops(monkeypatch):
    enc = lambda n: json.dumps(sr._encrypt_facts({"facts": {"applicant_name": n}})["facts"])
    store = {"rows": {"a": enc("Choice Electric LLC"), "b": json.dumps("enc:other-envs-key"),
                      "c": enc(""), "d": enc("Harborline Plumbing")}, "filled": {}}
    monkeypatch.setattr(sr, "get_pool", lambda: _bf_pool(store))
    assert asyncio.run(sr.backfill_search_names(batch=2, pause=0)) == 2
    assert {k: sr._search_name(v) for k, v in store["filled"].items()} == {
        "a": "Choice Electric LLC", "d": "Harborline Plumbing"}
    store2 = {"rows": store["rows"], "filled": {}, "fail": True}     # writes fail: still ends
    monkeypatch.setattr(sr, "get_pool", lambda: _bf_pool(store2))
    asyncio.run(sr.backfill_search_names(batch=2, pause=0))


def test_the_backfill_never_runs_under_the_test_suite():
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py")).read()
    assert '"pytest" not in sys.modules' in src and "SEARCH_NAME_BACKFILL" in src


def test_the_page_and_its_count_share_one_match(monkeypatch):
    calls = []

    async def fake(u, q, a):
        calls.append(q)
        return ["x", "y"]
    monkeypatch.setattr(sr, "_match_session_ids", fake)
    sr._MATCH_CACHE.clear()
    assert asyncio.run(sr.count_sessions_for_user("u", search="Acme")) == 2
    assert asyncio.run(sr.count_sessions_for_user("u", search=" acme ")) == 2
    assert calls == ["Acme"]                       # one match for both
    asyncio.run(sr.count_sessions_for_user("u", search="acme", archived=True))
    assert len(calls) == 2                         # another list, another match
