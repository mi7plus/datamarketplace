# app/audit.py
#
# Append-only audit trail (S6). record() adds an entry and flushes; the caller's
# transaction persists it. Best-effort by design — never let an audit write break
# the money/file operation it describes.

import logging

from app.models import AuditLog

logger = logging.getLogger("audit")


def client_ip(request) -> str | None:
    if request is None:
        return None
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else None


def record(db, action: str, *, actor_id=None, ip=None,
           object_type=None, object_id=None, meta=None) -> None:
    try:
        db.add(AuditLog(
            action=action,
            actor_id=str(actor_id) if actor_id else None,
            ip=ip,
            object_type=object_type,
            object_id=str(object_id) if object_id else None,
            meta=meta,
        ))
        db.flush()
    except Exception:
        logger.exception("audit record failed: %s %s/%s", action, object_type, object_id)
