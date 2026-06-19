# app/sweep.py
#
# Auto-release sweep entry points.
#
# 1. As a management command (cron / worker):
#        python -m app.sweep
#    Opens a DB session, releases every due submission, prints the count, exits.
#
# 2. As an in-process scheduled job (started from main.py via APScheduler):
#        start_scheduler()
#    Runs the same sweep every SWEEP_INTERVAL_MINUTES (env, default 15).
#
# Both call submissions.run_auto_release_sweep, which is idempotent.

import os
import logging

from app.db import SessionLocal
from app.submissions import run_auto_release_sweep

logger = logging.getLogger("sweep")


def sweep_once() -> int:
    """Open a session, run the sweep, close. Returns number released."""
    db = SessionLocal()
    try:
        n = run_auto_release_sweep(db)
        if n:
            logger.info("auto-release sweep released %d submission(s)", n)
        return n
    finally:
        db.close()


def start_scheduler():
    """
    Start an in-process APScheduler that runs the sweep periodically.
    Returns the scheduler (so the caller can shut it down), or None if APScheduler
    is unavailable or disabled via SWEEP_ENABLED=false.
    """
    if os.getenv("SWEEP_ENABLED", "true").lower() != "true":
        logger.info("auto-release sweep disabled via SWEEP_ENABLED")
        return None
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
    except ImportError:
        logger.warning("APScheduler not installed — in-process sweep disabled; run `python -m app.sweep` via cron")
        return None

    interval = int(os.getenv("SWEEP_INTERVAL_MINUTES", "15"))
    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(sweep_once, "interval", minutes=interval, id="auto_release_sweep")
    scheduler.start()
    logger.info("auto-release sweep scheduled every %d minute(s)", interval)
    return scheduler


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    count = sweep_once()
    print(f"Released {count} submission(s).")
