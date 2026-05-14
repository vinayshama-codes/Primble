import asyncio
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _stub_module(name, **attrs):
    mod = types.ModuleType(name)
    for key, val in attrs.items():
        setattr(mod, key, val)
    sys.modules[name] = mod
    return mod


if "groq" not in sys.modules:
    _stub_module(
        "groq",
        Groq=type("Groq", (), {"__init__": lambda self, **kw: None}),
        AsyncGroq=type("AsyncGroq", (), {"__init__": lambda self, **kw: None}),
    )

if "httpx" not in sys.modules:
    _stub_module("httpx", AsyncClient=type("AsyncClient", (), {"__init__": lambda self, **kw: None}))

if "asyncpg" not in sys.modules:
    _stub_module("asyncpg", Pool=object, Connection=object)

if "psycopg2" not in sys.modules:
    _psycopg2 = _stub_module("psycopg2")
    _psycopg2.pool = _stub_module("psycopg2.pool", ThreadedConnectionPool=object)
    _psycopg2.connect = lambda *a, **kw: None

if "stripe" not in sys.modules:
    _stub_module("stripe")

if "circuitbreaker" not in sys.modules:
    _stub_module("circuitbreaker", CircuitBreaker=type("CircuitBreaker", (), {"__init__": lambda self, **kw: None}))

if "dotenv" not in sys.modules:
    _stub_module("dotenv", load_dotenv=lambda *a, **kw: None)

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("SECRET_KEY", "ci-test-secret")
os.environ.setdefault("ENVIRONMENT", "test")


def _question_fields(questions):
    return {q["field_name"] for q in questions}


async def _noop_humanize(field_names):
    return None


def test_acord125_questions_only_use_yellow_missing_required_fields():
    import services.arq_service as arq_service
    arq_service._humanize_fields_with_groq = _noop_humanize

    questions = asyncio.run(arq_service.generate_arq_questions(
        facts={},
        flags={},
        generated_forms={
            "ACORD_125": {
                "confidence": {
                    "applicant_name": "missing_required",
                    "dba_name": "low_confidence",
                    "mailing_address": "filled",
                    "contact_email": "missing_required",
                },
                "field_state": {
                    "applicant_name": "",
                    "dba_name": "",
                    "mailing_address": "",
                    "contact_email": "client@example.com",
                },
                "client_filled_fields": [],
                "schema": {},
            }
        },
        hard_stops=[],
        soft_stops=[],
    ))

    assert _question_fields(questions) == {"applicant_name"}


def test_non_acord125_questions_keep_existing_missing_field_behavior():
    import services.arq_service as arq_service
    arq_service._humanize_fields_with_groq = _noop_humanize

    questions = asyncio.run(arq_service.generate_arq_questions(
        facts={},
        flags={},
        generated_forms={
            "ACORD_126": {
                "confidence": {
                    "dba_name": "low_confidence",
                    "mailing_address": "filled",
                    "effective_date": "missing_required",
                },
                "field_state": {
                    "dba_name": "",
                    "mailing_address": "",
                    "effective_date": "",
                },
                "client_filled_fields": [],
                "schema": {},
            }
        },
        hard_stops=[],
        soft_stops=[],
    ))

    fields = _question_fields(questions)
    assert "dba_name" in fields
    assert "mailing_address" in fields
    assert "effective_date" in fields
    assert "producer_name" in fields


def test_send_guard_filters_only_invalid_acord125_questions():
    from services.arq_service import filter_arq_questions_for_session

    generated_forms = {
        "ACORD_125": {
            "confidence": {
                "applicant_name": "missing_required",
                "dba_name": "low_confidence",
                "mailing_address": "filled",
            },
            "field_state": {
                "applicant_name": "",
                "dba_name": "",
                "mailing_address": "",
            },
        }
    }
    questions = [
        {"field_name": "applicant_name", "question": "Applicant?", "forms": "125", "form_ids": ["ACORD_125"]},
        {"field_name": "dba_name", "question": "DBA?", "forms": "125", "form_ids": ["ACORD_125"]},
        {"field_name": "mailing_address", "question": "Address?", "forms": "125, 126", "form_ids": ["ACORD_125", "ACORD_126"]},
        {"field_name": "gl_limits", "question": "GL limits?", "forms": "126", "form_ids": ["ACORD_126"]},
    ]

    guarded = filter_arq_questions_for_session(generated_forms, questions)
    by_field = {q["field_name"]: q for q in guarded}

    assert set(by_field) == {"applicant_name", "mailing_address", "gl_limits"}
    assert by_field["applicant_name"]["form_ids"] == ["ACORD_125"]
    assert by_field["mailing_address"]["form_ids"] == ["ACORD_126"]
    assert by_field["mailing_address"]["forms"] == "126"
