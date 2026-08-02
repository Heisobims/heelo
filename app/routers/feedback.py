from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException

from app.dependencies import DBSession, OrgAccess
from app.schemas.feedback import SubmitFeedbackRequest
from app.services import event_service as ev_svc
from app.services import feedback_service as fb_svc

router_feedback_public = APIRouter(prefix="/api/v1/registrations", tags=["feedback"])
router_feedback_org = APIRouter(prefix="/api/v1/organizations/{slug}/events", tags=["feedback"])


@router_feedback_public.post("/{registration_id}/feedback")
async def submit_feedback(registration_id: str, body: SubmitFeedbackRequest, db: DBSession):
    try:
        reg_id = uuid.UUID(registration_id)
    except ValueError as err:
        raise HTTPException(422, "Invalid registration ID.") from err

    feedback = await fb_svc.submit_feedback(db, reg_id, rating=body.rating, comment=body.comment)
    return {"success": True, "data": {"rating": feedback.rating, "comment": feedback.comment}}


@router_feedback_org.get("/{event_id}/feedback")
async def event_feedback_summary(event_id: uuid.UUID, access: OrgAccess, db: DBSession):
    org, _, _ = access
    event = await ev_svc.get_event_by_id(db, event_id)
    if not event or str(event.org_id) != str(org.id):
        raise HTTPException(404, "Event not found.")
    summary = await fb_svc.get_event_feedback_summary(db, event.id)
    return {"success": True, "data": summary}
