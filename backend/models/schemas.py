from pydantic import BaseModel, EmailStr
from typing import Dict, List, Optional

# ── Audit table DDL — PostgreSQL / Supabase (imported by database.py) ────────
# Each entry is a single statement (psycopg2 does not support multi-statement
# strings; execute each one individually).

SQS_RECOMMENDATION_AUDIT_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS sqs_recommendation_audit (
        id                        TEXT PRIMARY KEY,
        session_id                TEXT NOT NULL,
        user_id                   TEXT NOT NULL,
        form_id                   TEXT,
        rec_id                    TEXT NOT NULL,
        field                     TEXT,
        recommendation_type       TEXT CHECK(recommendation_type IN
                                      ('hard_stop','soft_warning','missing_field','suggestion')),
        component                 TEXT,
        message                   TEXT NOT NULL,
        score_impact              INTEGER,
        presented_at              TEXT NOT NULL,
        action                    TEXT CHECK(action IN
                                      ('resolved','dismissed','downloaded_anyway')),
        action_at                 TEXT,
        sqs_score_at_presentation INTEGER,
        sqs_score_at_action       INTEGER,
        override_reason           TEXT,
        model_version             TEXT NOT NULL,
        UNIQUE(session_id, rec_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_sqs_rec_session ON sqs_recommendation_audit(session_id)",
    "CREATE INDEX IF NOT EXISTS idx_sqs_rec_user    ON sqs_recommendation_audit(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_sqs_rec_action  ON sqs_recommendation_audit(action)",
]

DOWNLOAD_AUDIT_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS download_audit (
        id              TEXT PRIMARY KEY,
        session_id      TEXT NOT NULL,
        user_id         TEXT,
        override_note   TEXT,
        open_rec_count  INTEGER DEFAULT 0,
        downloaded_at   TEXT NOT NULL,
        model_version   TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_download_audit_session ON download_audit(session_id)",
]

FIELD_SOURCE_AUDIT_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS field_source_audit (
        id             TEXT PRIMARY KEY,
        session_id     TEXT NOT NULL,
        user_id        TEXT NOT NULL,
        form_id        TEXT,
        field_name     TEXT NOT NULL,
        fact_key       TEXT,
        source         TEXT NOT NULL CHECK(source IN ('ai','producer','client_arq')),
        previous_value TEXT,
        new_value      TEXT,
        confidence     TEXT CHECK(confidence IN ('deterministic','filled','ai_high','ai_low')),
        changed_at     TEXT NOT NULL,
        model_version  TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_field_audit_session ON field_source_audit(session_id)",
    "CREATE INDEX IF NOT EXISTS idx_field_audit_field   ON field_source_audit(field_name)",
    "CREATE INDEX IF NOT EXISTS idx_field_audit_source  ON field_source_audit(source)",
]

JOBS_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS jobs (
        job_id           TEXT PRIMARY KEY,
        session_id       TEXT REFERENCES processing_sessions(id) ON DELETE SET NULL,
        user_id          TEXT NOT NULL,
        job_type         TEXT NOT NULL,
        status           TEXT NOT NULL DEFAULT 'pending',
        payload          JSONB,
        result           JSONB,
        error_message    TEXT,
        progress_message TEXT,
        created_at       TEXT NOT NULL,
        updated_at       TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_jobs_session_id ON jobs(session_id)",
    "CREATE INDEX IF NOT EXISTS idx_jobs_user_id    ON jobs(user_id)",
]


class SignupRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    organization_name: str
    acord_disclaimer_accepted: bool = False


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class VerifyEmailRequest(BaseModel):
    email: EmailStr
    code: str


class GoogleAuthRequest(BaseModel):
    credential: str
    nonce: str


class FormSelectionRequest(BaseModel):
    session_id: str
    selected_form_id: str


class BulkFormSelectionRequest(BaseModel):
    session_id: str
    form_ids: List[str]


class PDFUpdateRequest(BaseModel):
    session_id: str
    field_updates: Dict[str, str]


class CheckoutRequest(BaseModel):
    plan: str = "essentials"
    billing_cycle: str = "monthly"


class OverageCheckoutRequest(BaseModel):
    quantity: int


class ApplyOverageRequest(BaseModel):
    stripe_session_id: str
    qty: int


from typing import Optional


class RiskTransferFlags(BaseModel):
    """Mirrors the risk_transfer sub-object returned by the extraction prompt."""
    additional_insured_required: bool = False
    additional_insured_names: List[str] = []
    primary_noncontributory_required: bool = False
    waiver_of_subrogation_required: bool = False
    certificate_holder_name: Optional[str] = None
    loss_payee_name: Optional[str] = None
    mortgagee_name: Optional[str] = None
    specific_wording_requirements: Optional[str] = None


class ComplianceCheckItem(BaseModel):
    """One item in the compliance_checklist returned inside the SQS payload."""
    check: str
    label: str
    status: str          # "required" | "advisory" | "info"
    message: str
    advisory: Optional[str] = None


class SaveSignatureRequest(BaseModel):
    signature_data: Optional[str] = None


class CompleteProfileRequest(BaseModel):
    organization_name: str
    acord_disclaimer_accepted: bool = False


# ── Audit API request / response models ───────────────────────────────────────

class DismissRecommendationRequest(BaseModel):
    session_id: str
    rec_id: str
    override_reason: str
    sqs_score_at_action: int
    message: Optional[str] = None
    field: Optional[str] = None
    component: Optional[str] = None
    score_impact: Optional[int] = None
    form_id: Optional[str] = None


class ResolveRecommendationRequest(BaseModel):
    session_id: str
    rec_id: str
    sqs_score_at_action: int


class DownloadAnywayRequest(BaseModel):
    session_id: str
    override_reason: Optional[str] = None


class OpenRecommendationItem(BaseModel):
    rec_id: str
    field: Optional[str]
    recommendation_type: Optional[str]
    message: str
    score_impact: Optional[int]


class AuditSummaryResponse(BaseModel):
    session_id: str
    recommendations: Dict
    field_changes: Dict