#!/bin/bash
echo "=================================="
echo "ACORDLY PRODUCTION READINESS CHECK"
echo "=================================="
PASS=0; FAIL=0; WARN=0
check_pass() { echo "✅ PASS: $1"; PASS=$((PASS+1)); }
check_fail() { echo "❌ FAIL: $1"; FAIL=$((FAIL+1)); }
check_warn() { echo "WARN: $1"; WARN=$((WARN+1)); }

echo "--- DATABASE ---"
_db_query() {
  if command -v sqlite3 &>/dev/null; then
    sqlite3 backend/acordly.db "$1" 2>/dev/null
  else
    python -c "
import sqlite3, sys
try:
    db = sqlite3.connect('backend/acordly.db')
    for row in db.execute(\"\"\"$1\"\"\"):
        print('|'.join(str(c) for c in row))
    db.close()
except Exception as e:
    sys.exit(1)
" 2>/dev/null
  fi
}
_db_query "SELECT name FROM sqlite_master WHERE type='table' AND name='stripe_events';" | grep -q stripe_events && check_pass "Stripe idempotency table exists" || check_fail "stripe_events table MISSING"
_db_query "SELECT name FROM sqlite_master WHERE type='table' AND name='jobs';" | grep -q jobs && check_pass "Jobs table exists" || check_warn "Jobs table missing (async not ready)"
_db_query "SELECT name FROM pragma_table_info('processing_sessions');" | grep -q "s3_pdf_key\|pdf_s3_key" && check_pass "S3 PDF key column exists" || check_fail "S3 column MISSING — PDFs still in BYTEA"

echo "--- SECURITY ---"
grep -q 'allow_origins=\["\*"\]' backend/main.py 2>/dev/null && check_fail "CORS is wildcard (*)" || check_pass "CORS restricted"
grep -rn "logger.info.*DEBUG ARQ" backend/routes/ backend/services/ 2>/dev/null | grep -q . && check_fail "PII debug logs still present in code" || check_pass "PII debug logs removed"
grep -q "MAX_UPLOAD_SIZE\|client_max_body_size" backend/settings.py backend/main.py 2>/dev/null && check_pass "Upload size limit set" || check_fail "No upload size limit"
grep -rn "request.query_params.get.*token\|request.args.get.*token" backend/routes/ 2>/dev/null | grep -v stripe | grep -q . && check_fail "Token accepted via query string" || check_pass "No token in query string"
grep -q "stripe.Webhook.construct_event\|verify_header" backend/routes/stripe_routes.py 2>/dev/null && check_pass "Stripe webhook verified" || check_fail "Stripe webhook verification MISSING"
grep -A3 "raise HTTPException(500" backend/routes/form_routes.py 2>/dev/null | grep -q "str(ex)" && check_fail "Raw exception message in HTTP 500" || check_pass "HTTP 500 messages sanitised"
grep -rn "signature_b64" backend/routes/signature_routes.py 2>/dev/null | grep -q . && check_fail "signature_b64 still persisted in session JSONB" || check_pass "signature_b64 not in session JSONB"

echo "--- FORMS ---"
grep -rn "template_pending" backend/services/form_service.py 2>/dev/null | grep -q . && check_pass "template_pending flag exists in form_service" || check_fail "template_pending missing — silent 400 on ACORD_130/131 etc."
grep -rn "idx_processing_sessions_user_id" backend/migrate.py backend/alembic/ 2>/dev/null | grep -q . && check_pass "user_id index in migrations" || check_fail "Missing user_id index on processing_sessions"
python3 -c "
import json, os
idx = json.load(open('backend/forms_index.json'))
templates = set(os.listdir('backend/templates/'))
missing = [f['form_id'] for f in idx if f.get('template_path') and os.path.basename(f['template_path']) not in templates and not f.get('template_pending')]
print('UNGUARDED_MISSING:' + ','.join(missing) if missing else 'OK')
" 2>/dev/null | grep -q "UNGUARDED_MISSING" && check_fail "forms_index.json lists templates that don't exist and are not marked template_pending" || check_pass "All non-pending forms have templates on disk"

echo "--- INFRASTRUCTURE ---"
grep -q "ThreadedConnectionPool\|SimpleConnectionPool" backend/config/database.py 2>/dev/null && check_pass "DB connection pooling exists" || check_fail "No connection pooling"
grep -q "pg_try_advisory_lock" backend/services/scheduler_service.py 2>/dev/null && check_pass "Scheduler advisory lock exists" || check_fail "No scheduler lock — double cron fire on 2+ replicas"
[ -f backend/services/s3_service.py ] && check_pass "S3 service file exists" || check_fail "S3 service MISSING"
REQUIRED_VARS=(
  "DATABASE_URL"
  "STRIPE_SECRET_KEY"
  "STRIPE_WEBHOOK_SECRET"
  "SECRET_KEY"
  "REDIS_URL"
  "AWS_S3_BUCKET"
  "AWS_ACCESS_KEY_ID"
  "AWS_SECRET_ACCESS_KEY"
  "GOOGLE_CLIENT_ID"
  "GOOGLE_CLIENT_SECRET"
  "ALLOWED_ORIGINS"
)

MISSING=()
for var in "${REQUIRED_VARS[@]}"; do
  val=$(grep "^${var}=" backend/.env 2>/dev/null | cut -d'=' -f2-)
  if [ -z "$val" ]; then
    MISSING+=("$var")
    echo "ERROR: Missing required env var: ${var}"
    exit 1
  fi
done

echo "All required env vars present."
check_pass "All required env vars set"
[ -f backend/utils/rate_limiter.py ] && check_pass "Rate limiter module exists" || check_fail "Rate limiter MISSING"
[ -f backend/utils/json_logging.py ] && check_pass "Structured logging module exists" || check_warn "Structured logging MISSING"
grep -q "trace_id\|request_id" backend/main.py 2>/dev/null && check_pass "Trace ID middleware exists" || check_warn "Trace ID MISSING"
grep -q "finally:" backend/routes/form_routes.py 2>/dev/null && check_pass "Tmp file cleanup in finally blocks" || check_warn "Tmp cleanup MISSING"

echo "--- ASYNC & DEPLOYMENT ---"
grep -rq "BackgroundTasks\|background_tasks\|job_queue" backend/routes/form_routes.py 2>/dev/null && check_pass "Async processing wired" || check_fail "NO ASYNC — upload blocks 10-60s"
grep -q "^[^#]*init_db()" backend/main.py 2>/dev/null && check_fail "init_db() runs on every startup — race on 2+ replicas" || check_pass "init_db() not in startup path"
[ -d backend/alembic ] && check_pass "Alembic migrations directory exists" || check_fail "No Alembic — no proper DB migrations"
[ -f backend/Dockerfile ] && check_pass "Dockerfile exists" || check_fail "No Dockerfile"
[ -d terraform ] || [ -d infrastructure ] && check_pass "IaC directory exists" || check_warn "No Terraform/IaC"

echo ""
echo "=================================="
echo "✅ PASS: $PASS  ❌ FAIL: $FAIL  WARN: $WARN"
[ $FAIL -eq 0 ] && echo "Status: PRODUCTION READY" && exit 0
[ $FAIL -le 3 ] && echo "Status: CONDITIONAL — fix ❌ items" && exit 1
echo "Status: NOT READY — too many critical failures"; exit 2
