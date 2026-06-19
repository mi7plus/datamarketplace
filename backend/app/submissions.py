# app/submissions.py
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import Optional
from uuid import UUID

from app.db import get_db
from app.models import Submission, DataRequest, UserAuth as User, SubmissionStatus
from app.auth import get_current_user
from app.ingest import validate_dataset
from app.lifecycle import validate_submission
from app.storage import get_storage

router = APIRouter()

MAX_FILE_BYTES = 100 * 1024 * 1024  # 100 MB
ALLOWED_EXTENSIONS = {"csv", "jsonl"}


@router.post("/")
async def create_submission(
    request_id: UUID = Form(...),
    offered_amount: int = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Verify request exists and is accepting submissions
    data_request = db.query(DataRequest).filter(
        DataRequest.id == str(request_id),
        DataRequest.is_deleted == False,
    ).first()
    if not data_request:
        raise HTTPException(status_code=404, detail="Request not found")
    if data_request.status not in ("open", "partially_fulfilled"):
        raise HTTPException(status_code=409, detail=f"Request is not accepting submissions (status: {data_request.status})")

    # Validate file type
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=422, detail=f"Only CSV and JSONL files are accepted, got .{ext}")

    # Read + size guard
    file_bytes = await file.read()
    if len(file_bytes) > MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 100 MB limit")

    # Run ingest validation against the request spec
    result = validate_dataset(
        file_bytes=file_bytes,
        filename=file.filename or "upload",
        spec=data_request.spec,
    )

    # Persist file (local now, MinIO in Phase 6)
    storage_key = f"{request_id}/{current_user.id}/{file.filename}"
    storage_location = get_storage().save(storage_key, file_bytes)

    # Create submission record (PENDING → VALIDATED or REJECTED_INVALID via lifecycle)
    submission = Submission(
        request_id=request_id,
        provider_id=current_user.id,
        content_link=file.filename,
        offered_amount=offered_amount,
        accepted_amount=0,
        file_size_bytes=len(file_bytes),
        mime_type=file.content_type or ("text/csv" if ext == "csv" else "application/x-jsonlines"),
        storage_location=storage_location,
        dataset_hash=result.dataset_hash,
    )
    db.add(submission)
    db.flush()  # get the id before calling lifecycle

    # Transition to VALIDATED or REJECTED_INVALID
    validate_submission(
        submission=submission,
        validated_amount=result.validated_amount,
        validation_report={
            **result.validation_report,
            "sample": result.sample,
        },
        db=db,
    )

    return {
        "id": str(submission.id),
        "status": submission.status,
        "offered_amount": submission.offered_amount,
        "validated_amount": submission.validated_amount,
        "dataset_hash": submission.dataset_hash,
        "validation_report": submission.validation_report,
    }


@router.get("/my")
def my_submissions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Provider's own submission history."""
    subs = (
        db.query(Submission)
        .filter(
            Submission.provider_id == current_user.id,
            Submission.is_deleted == False,
        )
        .order_by(Submission.created_at.desc())
        .all()
    )
    return [
        {
            "id": str(s.id),
            "request_id": str(s.request_id),
            "status": s.status,
            "offered_amount": s.offered_amount,
            "validated_amount": s.validated_amount,
            "accepted_amount": s.accepted_amount,
            "amount_due": s.amount_due,
            "content_link": s.content_link,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "validation_report": s.validation_report,
        }
        for s in subs
    ]


@router.get("/request/{request_id}")
def submissions_for_request(
    request_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Buyer sees all VALIDATED+ submissions for their request."""
    data_request = db.query(DataRequest).filter(DataRequest.id == request_id).first()
    if not data_request:
        raise HTTPException(status_code=404, detail="Request not found")
    if str(data_request.requester_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Not your request")

    subs = (
        db.query(Submission)
        .filter(
            Submission.request_id == request_id,
            Submission.status != SubmissionStatus.PENDING,
            Submission.is_deleted == False,
        )
        .order_by(Submission.created_at.desc())
        .all()
    )
    return [
        {
            "id": str(s.id),
            "provider_id": str(s.provider_id),
            "status": s.status,
            "offered_amount": s.offered_amount,
            "validated_amount": s.validated_amount,
            "accepted_amount": s.accepted_amount,
            "amount_due": s.amount_due,
            "validation_report": s.validation_report,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s in subs
    ]
