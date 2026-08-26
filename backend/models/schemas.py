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
        producer_answer           TEXT,
        answered_at               TEXT,
        model_version             TEXT NOT NULL,
        UNIQUE(session_id, rec_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_sqs_rec_session ON sqs_recommendation_audit(session_id)",
    "CREATE INDEX IF NOT EXISTS idx_sqs_rec_user    ON sqs_recommendation_audit(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_sqs_rec_action  ON sqs_recommendation_audit(action)",
    # The value a producer typed on a recommendation card. Also the discriminator
    # that separates "the producer answered this" (reopenable, and clearing it must
    # retract a fact) from "auto-resolved because the client's questionnaire closed
    # the gap" (nothing of the producer's to undo). Deliberately a new column rather
    # than a new `action` value: get_unresolved_recommendations() is written as
    # `action IS DISTINCT FROM 'resolved'/'dismissed'`, so an 'answered' action would
    # silently land in the download-audit and cover-page Red Flags sets.
    # ALTER as well as the CREATE above, so existing databases pick it up on restart.
    "ALTER TABLE sqs_recommendation_audit ADD COLUMN IF NOT EXISTS producer_answer TEXT",
    # E&O 5.8: when the producer typed the answer. presented_at is INSERT-only,
    # so an answer landing via the upsert's UPDATE branch had no timestamp of
    # its own until this column (2026-08-26).
    "ALTER TABLE sqs_recommendation_audit ADD COLUMN IF NOT EXISTS answered_at TEXT",
]

# E&O append-only event history (client section 5.11 / 5.12, 2026-08-26).
# One row per meaningful package event that has no durable table of its own
# (upload, extraction, client answers applied, retractions, reopens with the
# prior state they would otherwise erase) plus the SQS scoring snapshots of
# 5.12 (event_type='sqs_snapshot', written only when the score, a pillar, or
# the ceiling actually changed - never per invisible recalculation).
# INSERT-only by design: nothing in the APPLICATION may UPDATE or DELETE here.
# Lifecycle is owned solely by scheduler_service.run_audit_log_retention,
# which sweeps rows older than AUDIT_EVENTS_RETENTION_DAYS (default 180,
# floored at 180 - owner ruling 2026-08-26, Q18: the E&O record is kept for
# 6 months).
AUDIT_EVENT_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS audit_events (
        id          TEXT PRIMARY KEY,
        session_id  TEXT NOT NULL,
        user_id     TEXT,
        event_type  TEXT NOT NULL,
        event_data  JSONB,
        created_at  TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_audit_events_session ON audit_events(session_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_audit_events_type    ON audit_events(event_type)",
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

# Workstream 1 audit trail (Beta Report §4.1 + §4.2). One row per user-facing
# Submission Integrity / Document Classification event so the package history is
# queryable independently of the session JSON blob. Satisfies the §4.1 acceptance
# criterion "The system records whether the user overrode the warning" and the
# §4.2 requirement that manual classification corrections are recorded.
SUBMISSION_INTEGRITY_AUDIT_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS submission_integrity_audit (
        id                    TEXT PRIMARY KEY,
        session_id            TEXT NOT NULL,
        user_id               TEXT,
        event_type            TEXT NOT NULL CHECK(event_type IN
                                ('integrity_assessed','integrity_resolved','document_reclassified')),
        -- Integrity verdict snapshot (§4.1 — clustering result)
        integrity_status      TEXT CHECK(integrity_status IN ('high','medium','low')),
        confidence            DOUBLE PRECISION,
        review_required       BOOLEAN,
        detected_entities     JSONB,    -- distinct insured names the clustering found
        reasons               JSONB,    -- human-readable divergence reasons
        signals               JSONB,    -- raw signal counts behind the verdict
        -- Resolution action (§4.1 — remove / continue_anyway / create_separate_submissions)
        action                TEXT,
        overridden            BOOLEAN,  -- did the user override the multi-insured warning?
        removed_doc_ids       JSONB,
        acknowledged_entities JSONB,
        created_submissions   JSONB,    -- cluster -> session mapping for a split
        -- Classification correction (§4.2 — set_type / exclude / include / supporting_only)
        doc_id                TEXT,
        previous_doc_type     TEXT,
        new_doc_type          TEXT,
        model_version         TEXT,
        created_at            TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_integrity_audit_session ON submission_integrity_audit(session_id)",
    "CREATE INDEX IF NOT EXISTS idx_integrity_audit_user    ON submission_integrity_audit(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_integrity_audit_event   ON submission_integrity_audit(event_type)",
]

# Workstream 2 audit trail (Beta Report §5.1). One row per user-confirmed
# underwriting value so every "you chose X on date Y" event is queryable
# independently of the session JSON blob. Satisfies the audit requirement that
# confirmed values are traceable to a specific user and timestamp.
UNDERWRITING_CONFIRMATION_AUDIT_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS underwriting_confirmation_audit (
        id            TEXT PRIMARY KEY,
        session_id    TEXT NOT NULL,
        user_id       TEXT NOT NULL,
        fact_key      TEXT NOT NULL,
        label         TEXT NOT NULL,
        confirmed_value TEXT NOT NULL,
        previous_value  TEXT,
        confirmed_at  TEXT NOT NULL,
        candidates    JSONB,
        reason        TEXT,
        note          TEXT
    )
    """,
    # V1 plan C1 F10 (client 1.5 "Producer Resolution ... must not delete the
    # prior evidence"): every competing value, its sources and scope, and the
    # reason for the conflict, kept next to the chosen value. Existing
    # databases pick the columns up via the ALTER list in config/database.py.
    "ALTER TABLE underwriting_confirmation_audit ADD COLUMN IF NOT EXISTS candidates JSONB",
    "ALTER TABLE underwriting_confirmation_audit ADD COLUMN IF NOT EXISTS reason TEXT",
    # E&O 5.10 "any resolution note": the producer's OWN optional free text,
    # distinct from `reason` (the comparator's statement of the conflict).
    "ALTER TABLE underwriting_confirmation_audit ADD COLUMN IF NOT EXISTS note TEXT",
    "CREATE INDEX IF NOT EXISTS idx_uw_confirm_session ON underwriting_confirmation_audit(session_id)",
    "CREATE INDEX IF NOT EXISTS idx_uw_confirm_user    ON underwriting_confirmation_audit(user_id)",
]

# Figure 6: "Why are you marketing this account?" answer, split into a
# controlled reason_code (for reporting) and a free-text reason_note (the
# "Other: ..." detail), persisted independently of the processing_sessions
# JSON blob so it survives the facts-retention job and is fetchable by an
# underwriter/reviewer during an audit. One row per session - latest answer
# wins (UNIQUE session_id + ON CONFLICT upsert in audit_service.py), matching
# the product decision that this is a current-value field, not an append-only
# history.
MARKETING_REASON_AUDIT_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS marketing_reason_audit (
        id            TEXT PRIMARY KEY,
        session_id    TEXT NOT NULL UNIQUE,
        user_id       TEXT NOT NULL,
        reason_code   TEXT NOT NULL,
        reason_note   TEXT,
        is_adverse    BOOLEAN DEFAULT FALSE,
        updated_at    TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_marketing_reason_user ON marketing_reason_audit(user_id)",
]

# Per-issue resolution status for the issue rail (Recommendations / Cross-form /
# hard-stop Issues). Deliberately separate from sqs_recommendation_audit so this
# is a pure work-tracking marker: writing here never runs any SQS scoring /
# dismiss-credit logic. Keyed by the durable issue_id (issue_registry.issue_id_for)
# scoped to one session, so a status re-attaches to the same issue across re-runs.
SUBMISSION_ISSUE_STATUS_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS submission_issue_status (
        id            TEXT PRIMARY KEY,
        session_id    TEXT NOT NULL,
        user_id       TEXT,
        issue_id      TEXT NOT NULL,
        form_id       TEXT,
        field         TEXT,
        rule_code     TEXT,
        source_fact   TEXT,
        message       TEXT,
        status        TEXT CHECK(status IN ('open','resolved','dismissed')),
        reason        TEXT,
        updated_at    TEXT NOT NULL,
        UNIQUE(session_id, issue_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_issue_status_session ON submission_issue_status(session_id)",
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
    nonce: Optional[str] = None


class FormSelectionRequest(BaseModel):
    session_id: str
    selected_form_id: str


class BulkFormSelectionRequest(BaseModel):
    session_id: str
    form_ids: List[str]


class PDFUpdateRequest(BaseModel):
    session_id: str
    field_updates: Dict[str, str]


class SubmissionIntegrityResolveRequest(BaseModel):
    """Resolve a pending Submission Integrity review (Beta Report §4.1).

    action:
      - 'remove_documents'            : drop ``remove_doc_ids`` and re-assess on the rest.
      - 'continue_anyway'             : keep all docs, record an override, and proceed.
      - 'create_separate_submissions' : split the package by likely insured into one
                                        processing session per cluster and proceed
                                        with the first cluster on this session.
    """
    session_id: str
    action: str
    remove_doc_ids: List[str] = []


class DocumentReclassifyRequest(BaseModel):
    """Manually correct a document's classification (Beta Report §4.2).

    action:
      - 'set_type'        : set the document type to ``new_doc_type`` (Unknown → known).
      - 'exclude'         : exclude the document from scoring (kept for display).
      - 'include'         : re-include a document as a normal scoring participant.
      - 'supporting_only' : include facts but never select it as primary truth.
    """
    session_id: str
    doc_id: str
    action: str
    new_doc_type: Optional[str] = None


class UnderwritingConfirmRequest(BaseModel):
    """Confirm the correct value for a Core Underwriting Data element
    (Beta Report §4.3, e.g. Gross Sales) when documents disagree.

    The confirmed value is normalized, applied to the merged facts, and re-run
    through the pipeline so it flows consistently into every relevant form and
    into SQS scoring.
    """
    session_id: str
    fact_key: str
    value: str
    # E&O 5.10 "any resolution note": optional producer free text, stored on
    # the confirmation audit row. The UI may or may not offer it; the backend
    # retains it whenever sent.
    note: Optional[str] = None


class ClientAnswerResolveRequest(BaseModel):
    """Producer's decision on a client questionnaire answer that disagreed with
    the uploaded documents (V1 plan C1 F7 / C1-D, client rule 1.5).

    ``choice`` is "use_client" (apply the client's value to the generated forms
    as a producer-provenance fact) or "keep_source" (the documents stand).
    """
    session_id: str
    fact_key: str
    choice: str


class MarketingReasonRequest(BaseModel):
    """Producer-answerable "Why are you marketing this account?" captured on the
    form recommendation screen (DOUBTS-Workstream4 / Brent).

    The reason sets the carrier_marketing_reason fact and derives
    prior_carrier_adverse_action, then re-runs form recommendations so ACORD 101
    escalates to its correct tier. The answer also flows into later SQS scoring
    and Narrative Quality. session_id is taken from the URL path.
    """
    reason: str


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
    pending_token: Optional[str] = None


class UpdateProfileRequest(BaseModel):
    full_name: Optional[str] = None
    organization_name: Optional[str] = None
    # Optional producer contact phone surfaced to the client on the ARQ
    # "Contact Your Agent" card. Empty string clears it.
    phone: Optional[str] = None


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


class IssueStatusRequest(BaseModel):
    # Set the resolution status of one issue in the rail. Pure work-tracking:
    # never affects SQS scoring. `status` is validated in the route.
    session_id: str
    issue_id: str
    status: str
    reason: Optional[str] = None
    form_id: Optional[str] = None
    field: Optional[str] = None
    rule_code: Optional[str] = None
    source_fact: Optional[str] = None
    message: Optional[str] = None


class AnswerRecommendationRequest(BaseModel):
    # Producer-entered answer to a recommendation card (Fig 13). `field` is the
    # recommendation's canonical fact key; `answer` is the producer's typed value.
    session_id: str
    rec_id: str
    field: str
    answer: str
    sqs_score_at_action: Optional[int] = None
    form_id: Optional[str] = None
    # Carried so the answer can be recorded on a rec whose audit row was never
    # seeded by log_recommendations_presented (recs that first appear on a
    # recalculation). `message` is NOT NULL in sqs_recommendation_audit, so an
    # insert without it would fail.
    message: Optional[str] = None
    score_impact: Optional[int] = None


class ReopenRecommendationRequest(BaseModel):
    # Reopen a dismissed or producer-answered recommendation from the SQS panel's
    # "Reviewed" section, putting the card back in the open list.
    session_id: str
    rec_id: str
    form_id: Optional[str] = None


class ResolveIssueRequest(BaseModel):
    # Inline resolution of a Cross-Form Validation issue from the SQS panel.
    # `mode` selects the editor the producer used:
    #   field    -> `field` (a canonical fact key) + `value` (the typed value)
    #   narrative -> `text` (an ACORD 101 explanation, appended)
    #   schedule -> `schedule_key` + `rows` (the edited table)
    # `issue_id` / `code` identify the issue for logging and status marking.
    session_id: str
    issue_id: Optional[str] = None
    code: Optional[str] = None
    mode: str
    field: Optional[str] = None
    value: Optional[str] = None
    text: Optional[str] = None
    schedule_key: Optional[str] = None
    rows: Optional[List[dict]] = None
    form_id: Optional[str] = None


class ReopenIssueRequest(BaseModel):
    # Reopen a Cross-Form Validation issue from the SQS panel. For a
    # `field`-mode issue, this also clears whichever canonical fact(s) a prior
    # inline resolve wrote (Reopen must undo the fix, not just relabel a
    # validation whose value still shows on the form). Other resolution modes
    # only flip the status marker - see audit_routes.reopen_issue for why.
    session_id: str
    issue_id: Optional[str] = None
    code: Optional[str] = None
    form_id: Optional[str] = None
    message: Optional[str] = None


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