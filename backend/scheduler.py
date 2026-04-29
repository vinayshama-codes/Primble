"""Standalone scheduler process for production deployments.

In production, SCHEDULER_ENABLED defaults to false in the API process to avoid
duplicate job execution when running multiple API workers.  Instead, run this
script as a separate ECS task (desired_count=1) or systemd service.

Usage:
    python scheduler.py

Required env vars: same as the API (DATABASE_URL, etc.)
Optional:
    SCHEDULER_ADVISORY_LOCK_ID   — integer (default 7654321098); must match the
                                   value in scheduler_service.py
"""
import asyncio
import logging
import os
import signal
import sys

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("scheduler")

# Sentry — same DSN as API and worker
_SENTRY_DSN = os.getenv("SENTRY_DSN", "")
if _SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.logging import LoggingIntegration
    sentry_sdk.init(
        dsn=_SENTRY_DSN,
        environment=os.getenv("ENVIRONMENT", "development"),
        release=os.getenv("APP_VERSION", "12.4.0"),
        traces_sample_rate=0.0,
        integrations=[LoggingIntegration(level=logging.WARNING, event_level=logging.ERROR)],
        send_default_pii=False,
    )


def _handle_signal(sig, frame):
    logger.info("Scheduler: received signal %s — shutting down", sig)
    from services.scheduler_service import stop_scheduler
    stop_scheduler()
    sys.exit(0)


def main():
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT,  _handle_signal)

    logger.info("Scheduler process starting (ENVIRONMENT=%s)", os.getenv("ENVIRONMENT", "development"))

    from services.scheduler_service import start_scheduler, scheduler

    # Force scheduler on — this process exists solely to run scheduled jobs.
    os.environ["SCHEDULER_ENABLED"] = "true"
    start_scheduler()

    if not scheduler.running:
        logger.error("Scheduler failed to start — exiting")
        sys.exit(1)

    logger.info("Scheduler running. Jobs: %s", [str(j) for j in scheduler.get_jobs()])

    # Block until killed
    try:
        asyncio.get_event_loop().run_forever()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        from services.scheduler_service import stop_scheduler
        stop_scheduler()
        logger.info("Scheduler process exited cleanly")


if __name__ == "__main__":
    main()
