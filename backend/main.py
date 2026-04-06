import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config.database import init_db, get_db
from services.scheduler_service import start_scheduler, stop_scheduler
from routes.auth_routes import router as auth_router
from routes.form_routes import router as form_router
from routes.download_routes import router as download_router
from routes.stripe_routes import router as stripe_router
from routes.signature_routes import router as signature_router
from routes.dev_routes import router as dev_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

try:
    init_db()
except Exception as e:
    logger.error(f"DB init error: {e}")

app = FastAPI(title="Acordly API", version="12.3.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(form_router)
app.include_router(download_router)
app.include_router(stripe_router)
app.include_router(signature_router)
app.include_router(dev_router)


@app.on_event("startup")
async def startup():
    start_scheduler()


@app.on_event("shutdown")
async def shutdown():
    stop_scheduler()


@app.get("/")
def home():
    return {"message": "Acordly API v12.3.1", "status": "operational"}


@app.get("/api/health")
def health():
    try:
        conn     = get_db()
        cur      = conn.cursor()
        cur.execute("SELECT COUNT(*) as c FROM users")
        count    = cur.fetchone()["c"]
        cur.execute("SELECT COUNT(*) as c FROM processing_sessions")
        ps_count = cur.fetchone()["c"]
        cur.close()
        conn.close()
        return {"status": "healthy", "users": count, "active_sessions": ps_count}
    except Exception as e:
        return {"status": "error", "detail": str(e)}