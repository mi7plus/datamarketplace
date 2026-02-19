from fastapi import APIRouter, HTTPException
from typing import List
from models import Request, Submission

router = APIRouter()

# Accept submissions
@router.post("/requests/{request_id}/accept")
def accept_submissions(request_id: str, submission_ids: List[str], budget: float):
    request = get_request_by_id(request_id)  # fetch from DB
    submissions = [get_submission_by_id(sid) for sid in submission_ids]

    total_data = sum(s.data_amount for s in submissions)
    if total_data < request.required_data_amount:
        raise HTTPException(status_code=400, detail="Selected submissions do not meet required data amount.")

    total_cost = sum(s.data_amount * price_per_unit(s.data_type) for s in submissions)
    if total_cost > budget:
        raise HTTPException(status_code=400, detail="Total cost exceeds budget. Adjust budget or selection.")

    for s in submissions:
        s.status = "accepted"
        save_submission(s)

    request.accepted_submissions.extend(submissions)
    request.budget = budget
    save_request(request)
    return {"status": "success", "total_data": total_data, "total_cost": total_cost}