from __future__ import annotations

import uuid

from fastapi import APIRouter
from pydantic import BaseModel

from app.dependencies import CurrentUserID, DBSession
from app.services import connection_service as conn_svc

router_connections = APIRouter(prefix="/api/v1/connections", tags=["connections"])


def _ok(data) -> dict:
    return {"success": True, "data": data}


def _conn_dict(conn) -> dict:
    return {
        "id": str(conn.id),
        "user_id": str(conn.user_id),
        "connected_user_id": str(conn.connected_user_id),
        "event_id": str(conn.event_id) if conn.event_id else None,
        "status": conn.status,
        "message": conn.message,
        "created_at": conn.created_at.isoformat(),
    }


class SendRequestBody(BaseModel):
    target_user_id: uuid.UUID
    event_id: uuid.UUID | None = None
    message: str | None = None


@router_connections.post("", status_code=201)
async def send_connection_request(
    body: SendRequestBody, db: DBSession, current_user_id: CurrentUserID
):
    conn = await conn_svc.send_request(
        db,
        uuid.UUID(current_user_id),
        body.target_user_id,
        event_id=body.event_id,
        message=body.message,
    )
    return _ok(_conn_dict(conn))


@router_connections.post("/{connection_id}/accept")
async def accept_connection_request(
    connection_id: uuid.UUID, db: DBSession, current_user_id: CurrentUserID
):
    conn = await conn_svc.respond_request(
        db, connection_id, uuid.UUID(current_user_id), accept=True
    )
    return _ok(_conn_dict(conn))


@router_connections.post("/{connection_id}/decline")
async def decline_connection_request(
    connection_id: uuid.UUID, db: DBSession, current_user_id: CurrentUserID
):
    conn = await conn_svc.respond_request(
        db, connection_id, uuid.UUID(current_user_id), accept=False
    )
    return _ok(_conn_dict(conn))


@router_connections.get("/pending")
async def list_pending_connection_requests(db: DBSession, current_user_id: CurrentUserID):
    from sqlalchemy import select

    from app.models.user import User

    rows = await conn_svc.list_pending_requests(db, uuid.UUID(current_user_id))
    out = []
    for conn in rows:
        requester = await db.scalar(select(User).where(User.id == conn.user_id))
        out.append(
            {
                **_conn_dict(conn),
                "requester_name": requester.full_name if requester else "Someone",
                "requester_username": requester.username if requester else None,
                "requester_avatar_url": requester.avatar_url if requester else None,
            }
        )
    return _ok(out)


@router_connections.get("/status/{target_user_id}")
async def get_connection_status(
    target_user_id: uuid.UUID, db: DBSession, current_user_id: CurrentUserID
):
    status_ = await conn_svc.connection_status(db, uuid.UUID(current_user_id), target_user_id)
    return _ok({"status": status_})
