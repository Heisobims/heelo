from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.dependencies import CurrentUser, CurrentUserID, DBSession, OrgAccess
from app.services import inbox_service as inbox_svc

router_community = APIRouter(
    prefix="/api/v1/organizations/{slug}",
    tags=["community"],
)


# ── WhatsApp inbox API ────────────────────────────────────────────────────────


class ReplyRequest(BaseModel):
    body: str


@router_community.post("/inbox/{phone}/reply", status_code=201)
async def send_inbox_reply(
    slug: str,
    phone: str,
    body: ReplyRequest,
    db: DBSession,
    org_access: OrgAccess,
    current_user: CurrentUser,
):
    org, role, _ = org_access
    if role not in ("admin", "organizer"):
        raise HTTPException(403, "Insufficient permissions.")
    if not body.body.strip():
        raise HTTPException(422, "Reply body cannot be empty.")

    msg = await inbox_svc.send_reply(
        db,
        org_id=org.id,
        sent_by=current_user.id,
        phone=phone,
        body=body.body.strip(),
    )
    return {
        "success": True,
        "data": {
            "id": str(msg.id),
            "direction": msg.direction,
            "body": msg.body,
            "status": msg.status,
            "created_at": msg.created_at.isoformat(),
        },
    }


@router_community.post("/inbox/{phone}/mark-read", status_code=200)
async def mark_thread_read(
    slug: str,
    phone: str,
    db: DBSession,
    org_access: OrgAccess,
):
    org, role, _ = org_access
    await inbox_svc.mark_thread_read(db, org.id, phone)
    return {"success": True}


# ── Follow / Unfollow ─────────────────────────────────────────────────────────


@router_community.post("/follow")
async def follow_org(
    slug: str,
    db: DBSession,
    org_access: OrgAccess,
    current_user: CurrentUser,
):
    org, _, _ = org_access
    now_following = await inbox_svc.toggle_follow(db, org_id=org.id, user_id=current_user.id)
    count = await inbox_svc.get_follower_count(db, org.id)
    return {"success": True, "data": {"following": now_following, "follower_count": count}}


# ── Event discussion comments ─────────────────────────────────────────────────

router_comments = APIRouter(prefix="/api/v1/events", tags=["comments"])


class CommentRequest(BaseModel):
    body: str = Field(..., min_length=1, max_length=2000)
    author_name: str = Field(..., min_length=1, max_length=255)


@router_comments.get("/{slug}/comments")
async def list_comments(slug: str, db: DBSession, page: int = 1):

    from sqlalchemy import desc, func, select

    from app.models.event import Event, EventComment

    event = await db.scalar(select(Event).where(Event.slug == slug))
    if not event:
        raise HTTPException(404, "Event not found.")

    per_page = 20
    stmt = (
        select(EventComment)
        .where(EventComment.event_id == event.id, EventComment.is_hidden.is_(False))
        .order_by(desc(EventComment.created_at))
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    rows = await db.scalars(stmt)
    comments = rows.all()
    total = (
        await db.scalar(
            select(func.count()).where(
                EventComment.event_id == event.id,
                EventComment.is_hidden.is_(False),
            )
        )
        or 0
    )

    return {
        "comments": [
            {
                "id": str(c.id),
                "author_name": c.author_name,
                "body": c.body,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in comments
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@router_comments.post("/{slug}/comments", status_code=201)
async def post_comment(
    slug: str, body: CommentRequest, db: DBSession, current_user_id: CurrentUserID
):
    import uuid as _uuid

    from sqlalchemy import select

    from app.models.event import Event, EventComment
    from app.models.user import User

    event = await db.scalar(select(Event).where(Event.slug == slug))
    if not event:
        raise HTTPException(404, "Event not found.")
    if event.status not in ("published", "live"):
        raise HTTPException(403, "Comments are not open for this event.")

    uid = _uuid.UUID(str(current_user_id))
    user = await db.scalar(select(User).where(User.id == uid))
    author = user.full_name if user else body.author_name

    comment = EventComment(
        event_id=event.id,
        user_id=uid,
        author_name=author,
        body=body.body.strip(),
    )
    db.add(comment)
    await db.commit()
    await db.refresh(comment)

    return {
        "comment": {
            "id": str(comment.id),
            "author_name": comment.author_name,
            "body": comment.body,
            "created_at": comment.created_at.isoformat() if comment.created_at else None,
        }
    }


@router_comments.delete("/{slug}/comments/{comment_id}", status_code=204)
async def delete_comment(slug: str, comment_id: str, db: DBSession, current_user_id: CurrentUserID):
    import uuid as _uuid

    from sqlalchemy import select

    from app.models.event import Event, EventComment

    event = await db.scalar(select(Event).where(Event.slug == slug))
    if not event:
        raise HTTPException(404, "Event not found.")

    try:
        cid = _uuid.UUID(comment_id)
    except ValueError as err:
        raise HTTPException(422, "Invalid comment ID.") from err

    comment = await db.scalar(
        select(EventComment).where(
            EventComment.id == cid,
            EventComment.event_id == event.id,
        )
    )
    if not comment:
        raise HTTPException(404, "Comment not found.")

    uid = _uuid.UUID(str(current_user_id))
    if comment.user_id != uid:
        raise HTTPException(403, "You can only delete your own comments.")

    await db.delete(comment)
    await db.commit()
