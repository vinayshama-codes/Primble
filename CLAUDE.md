# Acordly: ACORD Form Processing Platform

## Overview

**What it does:** Acordly streamlines insurance document processing by automating ACORD form filling through data extraction and intelligent form population.

**Who uses it:** Insurance brokers and agents.

**Client:** Brent (funding development).

**Stage:** MVP (no paying customers yet, localhost deployment only).

**Current version:** 12.4.0

---

## Business Context

| Aspect | Details |
|--------|---------|
| **Problem Solved** | Reduces manual data entry and form filling for insurance professionals usin AI and perfection |
| **Target Users** | Insurance brokers/agents |
| **Revenue Model** | Pre-revenue (not yet monetized) |
| **Team Size** | 2-3 people |
| **Your Role** | Lead Architect |
| **Users Currently** | 0 (no production users) |
| **Submissions/Day** | 0 (MVP, localhost only) |

---

## Technical Stack

### Backend
- **Framework:** FastAPI (Python)
- **Database:** PostgreSQL (psycopg2)
- **API Version:** 12.4.0
- **Web Server:** Uvicorn

### Frontend
- **Framework:** React
- **Build:** Vite
- **Authentication:** Google OAuth

### AI/Processing
- **LLM:** Groq
- **OCR Providers:** AWS Textract (primary), EasyOCR, Google Cloud Vision
- **PDF Processing:** pdfplumber, pikepdf, reportlab

### AWS Services
- **S3:** Document storage
- **SQS:** Message queue (async job processing)
- **Textract:** OCR/form extraction

### Authentication & Security
- **Auth:** Google OAuth, JWT, bcrypt
- **Payments:** Stripe API

### Infrastructure & Background Jobs
- **Scheduling:** APScheduler
- **Caching:** Redis (with in-memory fallback)

---

## Supported ACORD Forms

Currently supporting 10+ ACORD forms including:
- ACORD 25 (General application)
- ACORD 28
- ACORD 101
- ACORD 125
- ACORD 140
- And others (see `backend/forms_database/` for full list)

Each form has a JSON schema mapping fields for extraction.

---

## Architecture

### Key Components

**Backend Routes:**
- `auth_routes.py` - Authentication (Google OAuth, JWT)
- `form_routes.py` - Form submission, extraction, storage
- `download_routes.py` - Generate/download completed forms
- `stripe_routes.py` - Payment processing
- `signature_routes.py` - Digital signature handling
- `arq_routes.py` - Agent Report Questionnaire endpoints
- `dev_routes.py` - Development/testing endpoints

**Services:**
- `extraction_service.py` - Extracts data from documents (OCR, form field mapping)
- `ocr_service.py` - Handles OCR provider logic (Textract/EasyOCR/Vision)
- `form_service.py` - Form validation, manipulation, schema management
- `pdf_service.py` - PDF generation and manipulation
- `arq_service.py` - ARQ workflow processing
- `cover_service.py` - Cover page handling
- `sqs_service.py` - AWS SQS queue integration
- `scheduler_service.py` - Background job scheduling

**Database:**
- `repositories/` - Data access layer (session management, etc.)
- `models/schemas.py` - Pydantic schemas for validation
- Stores: users, processing sessions, forms, signatures

---

## Critical Issues & Roadmap

### Current Blockers (Priority #1)
- **SQS & ARQ Async Processing:** Not working properly. Blocking background job processing and agent questionnaire workflows.
  - Impact: Can't offload long-running extraction jobs; forms can't route to ARQ
  - Owner: You (as lead architect)

### Major Technical Debt
- **Security/Compliance Gaps:** Missing controls for sensitive data (PII, financial info, signed docs)
  - Data types at risk: PII, insurance claims, financial data, signatures
  - Needs: Encryption at rest, field masking, audit logging, compliance hardening

- **No Automated Tests:** Only manual testing; zero test coverage
  - Risk: Regressions go undetected; hard to refactor with confidence

- **Localhost-Only Deployment:** No staging or production environment
  - Blocker for customer onboarding

### Next 3 Months
1. **Fix SQS/ARQ integration** (current blocker)
2. **Add security/compliance controls** for sensitive data
3. **Build test suite** (at least happy path coverage)
4. **Set up staging deployment** (move off localhost)

### Next 12 Months
- Launch with first customer (Brent's preferred workflows)
- Establish business model (likely SaaS subscription or per-submission)
- Scale form support (more ACORD variants)
- Performance optimization for high-volume submissions

---

## Code Organization

```
backend/
├── config/           # Database, env setup
├── models/           # Pydantic schemas
├── repositories/     # Data access layer
├── routes/           # API endpoints
├── services/         # Business logic (extraction, PDF, OCR, SQS, etc.)
├── utils/            # Validators, helpers
├── forms_database/   # ACORD form schemas & field mappings (JSON)
├── main.py           # FastAPI app, middleware, startup/shutdown
└── requirements.txt

frontend/
├── src/
│   ├── components/   # React components (form submission, ARQ, ACORD modal)
│   ├── hooks/        # Custom React hooks (useUpgradePolling)
│   └── ...
└── vite.config.js
```

---

## Critical Data Handling

**Sensitive Data Types:** PII (names, SSNs, addresses), insurance claims, financial data, signed documents

**Current State:** No encryption at rest, limited audit logging, needs compliance hardening for:
- HIPAA (health insurance)
- State insurance regulations
- PII protection (varies by state)

**Security gaps must be addressed before production launch.**

---

## Deployment & Operations

| Aspect | Current State | Needed |
|--------|---------------|--------|
| **Deployment** | Localhost only | Docker/cloud (AWS recommended) |
| **Monitoring** | None | CloudWatch, error tracking (Sentry?) |
| **Logging** | Basic console logs | Centralized logging, audit trail |
| **Testing** | Manual only | CI/CD pipeline with automated tests |
| **Health Check** | `GET /api/health` | Enhanced with SQS/database connectivity |

---

## Local Development

### Setup
```bash
# Backend
cd backend
pip install -r requirements.txt
export DATABASE_URL="postgresql://..."
uvicorn main:app --reload

# Frontend
cd frontend
npm install
npm run dev
```

### Key Environment Variables
- `DATABASE_URL` - PostgreSQL connection
- `STRIPE_API_KEY` - Stripe payments
- `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` - OAuth
- `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` - AWS (S3, SQS, Textract)
- `GROQ_API_KEY` - LLM access
- `OCR_PROVIDER` - Which OCR to use (textract, easyocr, google_vision)
- `REDIS_URL` - Cache (optional, falls back to in-memory)

---

## Key Decisions

**✅ What's Working Well:**
- FastAPI architecture (clean routes, Pydantic validation)
- Multi-provider OCR abstraction (switchable at runtime)
- ACORD form schema-driven approach (reusable, scalable)
- Google OAuth integration (easy onboarding)

**Known Workarounds:**
- SQS/ARQ not fully integrated (blocking production workflows)
- Security controls incomplete (must add before launch)
- No staging environment (hurts quality assurance)

**Would Rewrite If Time:**
- Async queue system (SQS/ARQ) - needs proper error handling and monitoring
- Test suite - needs comprehensive coverage from day one
- Deployment pipeline - needs containerization and cloud setup

---

## Notes for Future Contributors

- **Data is sensitive:** Any changes touching form data, signatures, or PII must include security review.
- **SQS/ARQ is critical:** Fixing this unlocks background job processing and customer workflows.
- **Tests matter:** Before adding features, invest in test infrastructure.
- **Ask Brent:** About compliance requirements (varies by state and customer).

<!-- code-review-graph MCP tools -->
## MCP Tools: code-review-graph

**IMPORTANT: This project has a knowledge graph. ALWAYS use the
code-review-graph MCP tools BEFORE using Grep/Glob/Read to explore
the codebase.** The graph is faster, cheaper (fewer tokens), and gives
you structural context (callers, dependents, test coverage) that file
scanning cannot.

### When to use graph tools FIRST

- **Exploring code**: `semantic_search_nodes` or `query_graph` instead of Grep
- **Understanding impact**: `get_impact_radius` instead of manually tracing imports
- **Code review**: `detect_changes` + `get_review_context` instead of reading entire files
- **Finding relationships**: `query_graph` with callers_of/callees_of/imports_of/tests_for
- **Architecture questions**: `get_architecture_overview` + `list_communities`

Fall back to Grep/Glob/Read **only** when the graph doesn't cover what you need.

### Key Tools

| Tool | Use when |
|------|----------|
| `detect_changes` | Reviewing code changes — gives risk-scored analysis |
| `get_review_context` | Need source snippets for review — token-efficient |
| `get_impact_radius` | Understanding blast radius of a change |
| `get_affected_flows` | Finding which execution paths are impacted |
| `query_graph` | Tracing callers, callees, imports, tests, dependencies |
| `semantic_search_nodes` | Finding functions/classes by name or keyword |
| `get_architecture_overview` | Understanding high-level codebase structure |
| `refactor_tool` | Planning renames, finding dead code |

### Workflow

1. The graph auto-updates on file changes (via hooks).
2. Use `detect_changes` for code review.
3. Use `get_affected_flows` to understand impact.
4. Use `query_graph` pattern="tests_for" to check coverage.
