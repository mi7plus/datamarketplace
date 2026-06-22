# app/staging_dedup.py
#
# Rust ingest plan P2: the dedup overlap-and-cap as a SQL anti-join over a
# per-submission staging table, replacing the in-Python set intersection.
#
# Selected by USE_STAGING_DEDUP=true. When off, lifecycle.accept_submission keeps
# the original in-Python path (the proven fallback). Both paths MUST return the
# same creditable set; tests assert their equivalence. Either way the result is
# consumed inside the caller's FOR UPDATE transaction — the money logic is unchanged.

import os

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import SubmissionKeyStaging


def use_staging_dedup() -> bool:
    return os.getenv("USE_STAGING_DEDUP", "").lower() == "true"


def ensure_staging(db: Session, submission) -> None:
    """Make sure the submission's key hashes are in staging.

    The async Rust path bulk-writes staging directly (COPY); on the synchronous
    path we lazily derive it from submission.key_hashes the first time it's
    needed, so staging and the in-Python path share one source of truth.
    """
    sid = str(submission.id)
    existing = (
        db.query(SubmissionKeyStaging.id)
        .filter(SubmissionKeyStaging.submission_id == sid)
        .first()
    )
    if existing:
        return
    hashes = getattr(submission, "key_hashes", None) or []
    for i, kh in enumerate(hashes):
        db.add(SubmissionKeyStaging(submission_id=submission.id, ordinal=i, key_hash=kh))
    db.flush()


def creditable_via_staging(db: Session, submission, request, remaining: int) -> list[str]:
    """creditable = (staging for this submission) EXCEPT (accepted_keys for this
    request), in submission order (ordinal), capped at `remaining`.

    NOT EXISTS anti-join is the set-logic equivalent of the previous
    `[h for h in key_hashes if h not in already_accepted][:remaining]`, but the
    overlap is computed in Postgres instead of materialized in Python memory.
    """
    if remaining <= 0:
        return []
    ensure_staging(db, submission)
    rows = db.execute(
        text(
            """
            SELECT s.key_hash
            FROM submission_key_staging s
            WHERE s.submission_id = :sid
              AND NOT EXISTS (
                  SELECT 1 FROM accepted_keys a
                  WHERE a.request_id = :rid AND a.key_hash = s.key_hash
              )
            ORDER BY s.ordinal
            LIMIT :lim
            """
        ),
        {"sid": str(submission.id), "rid": str(request.id), "lim": remaining},
    ).fetchall()
    return [r[0] for r in rows]
