# app/authz.py
#
# Centralized object-level authorization (S1 / IDOR defense).
#
# Value on this platform = gated files + movable money, so the catastrophic bug
# is broken object-level authorization: user A reading/downloading/accepting user
# B's object by guessing an id. These reusable dependencies make the ownership +
# role checks impossible to forget per-route, and return **404 (not 403)** on an
# ownership miss so an attacker can't even confirm an object exists.

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import DataRequest, Submission, UserAuth as User, UserRole
from app.auth import get_current_user


# ---------------------------------------------------------------------------
# Assertion helpers (callable from endpoint bodies and from the dependencies)
# ---------------------------------------------------------------------------

def _not_found(what: str = "Resource"):
    # 404 everywhere an attacker is probing someone else's object — never 403,
    # which would leak that the id is real.
    return HTTPException(status_code=404, detail=f"{what} not found")


def load_request_owned(request_id: str, db: Session, user: User) -> DataRequest:
    """Return the request iff the current user is its requester; else 404."""
    r = db.query(DataRequest).filter(
        DataRequest.id == request_id,
        DataRequest.is_deleted == False,
    ).first()
    if not r or str(r.requester_id) != str(user.id):
        raise _not_found("Request")
    return r


def load_submission_for_buyer(submission_id: str, db: Session, user: User):
    """For buyer-side submission actions (accept/reject/confirm/download/expire):
    return (submission, request) iff the user owns the parent request; else 404."""
    s = db.query(Submission).filter(
        Submission.id == submission_id,
        Submission.is_deleted == False,
    ).first()
    if not s:
        raise _not_found("Submission")
    r = db.query(DataRequest).filter(DataRequest.id == str(s.request_id)).first()
    if not r or str(r.requester_id) != str(user.id):
        raise _not_found("Submission")
    return s, r


def load_submission_owned(submission_id: str, db: Session, user: User) -> Submission:
    """For provider-side actions (claim): return the submission iff the user is
    its provider; else 404."""
    s = db.query(Submission).filter(
        Submission.id == submission_id,
        Submission.is_deleted == False,
    ).first()
    if not s or str(s.provider_id) != str(user.id):
        raise _not_found("Submission")
    return s


def load_submission_party(submission_id: str, db: Session, user: User):
    """For shared views (sample preview, dispute view): return (submission, request)
    iff the user is the provider, the buyer, or an admin; else 404."""
    s = db.query(Submission).filter(
        Submission.id == submission_id,
        Submission.is_deleted == False,
    ).first()
    if not s:
        raise _not_found("Submission")
    r = db.query(DataRequest).filter(DataRequest.id == str(s.request_id)).first()
    is_provider = str(s.provider_id) == str(user.id)
    is_buyer = r is not None and str(r.requester_id) == str(user.id)
    if not (is_provider or is_buyer or user.role == UserRole.ADMIN):
        raise _not_found("Submission")
    return s, r


# ---------------------------------------------------------------------------
# FastAPI dependencies — prefer these on new object-scoped routes
# ---------------------------------------------------------------------------

def get_owned_request(
    request_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DataRequest:
    return load_request_owned(request_id, db, user)


def require_role(*roles: UserRole):
    """Dependency factory: gate a route to one or more roles (role denial is a
    legitimate 403 — it doesn't leak a specific object's existence)."""
    def _dep(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Forbidden for your role")
        return user
    return _dep


require_admin = require_role(UserRole.ADMIN)
require_requester = require_role(UserRole.REQUESTER)
require_provider = require_role(UserRole.PROVIDER)
