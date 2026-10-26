from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event
from app.models.organization import Organization
from app.models.speaker import EventSpeaker, Speaker, Sponsor
from app.models.user import User
from tests.conftest import _make_token


@pytest.mark.asyncio
async def test_create_and_list_open_call(
    client: AsyncClient,
    db: AsyncSession,
    published_event: Event,
    org: Organization,
    user: User,
):
    token = _make_token(str(user.id))
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Create a Call for Papers
    payload = {
        "title": "Call for Papers - Python & Cloud 2026",
        "call_type": "speaker",
        "description": "We are seeking talks on async systems and scalable cloud infrastructure.",
        "guidelines": "Sessions are 30 minutes including 5 minutes Q&A.",
        "perks": "Free VIP admission, speaker dinner, and commemorative speaker trophy.",
        "status": "open",
        "auto_response_message": "Thanks for submitting your proposal! Decisions by Nov 15.",
        "custom_fields": [
            {
                "id": "talk_level",
                "label": "Target Audience Level",
                "field_type": "select",
                "required": True,
                "options": ["Beginner", "Intermediate", "Advanced"],
            },
        ],
    }

    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/calls",
        json=payload,
        headers=headers,
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    call_id = data["id"]
    assert data["title"] == payload["title"]
    assert data["call_type"] == "speaker"
    assert data["status"] == "open"
    assert data["submission_count"] == 0
    assert "slug" in data and len(data["slug"]) > 0

    # 2. List calls via organizer API
    list_resp = await client.get(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/calls",
        headers=headers,
    )
    assert list_resp.status_code == 200
    calls = list_resp.json()["data"]
    assert len(calls) >= 1
    assert any(c["id"] == call_id for c in calls)


@pytest.mark.asyncio
async def test_update_and_delete_open_call(
    client: AsyncClient,
    db: AsyncSession,
    published_event: Event,
    org: Organization,
    user: User,
):
    token = _make_token(str(user.id))
    headers = {"Authorization": f"Bearer {token}"}

    # Create call
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/calls",
        json={
            "title": "Volunteer Call",
            "call_type": "volunteer",
            "status": "draft",
        },
        headers=headers,
    )
    assert resp.status_code == 201
    call_id = resp.json()["data"]["id"]

    # Update call
    patch_resp = await client.patch(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/calls/{call_id}",
        json={
            "title": "Call for Event Volunteers & Crew",
            "status": "open",
            "perks": "Free event t-shirt and lunch provided",
        },
        headers=headers,
    )
    assert patch_resp.status_code == 200
    updated = patch_resp.json()["data"]
    assert updated["title"] == "Call for Event Volunteers & Crew"
    assert updated["status"] == "open"
    assert updated["perks"] == "Free event t-shirt and lunch provided"

    # Delete call
    del_resp = await client.delete(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/calls/{call_id}",
        headers=headers,
    )
    assert del_resp.status_code == 200

    # Verify 404 after delete
    get_resp = await client.get(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/calls/{call_id}",
        headers=headers,
    )
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_public_submission_and_review_workflow(
    client: AsyncClient,
    db: AsyncSession,
    published_event: Event,
    org: Organization,
    user: User,
):
    token = _make_token(str(user.id))
    org_headers = {"Authorization": f"Bearer {token}"}

    # 1. Organizer creates open call
    call_resp = await client.post(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/calls",
        json={
            "title": "Conference Keynotes & Talks",
            "call_type": "speaker",
            "status": "open",
            "custom_fields": [
                {
                    "id": "experience",
                    "label": "Previous speaking experience",
                    "field_type": "text",
                    "required": False,
                },
            ],
        },
        headers=org_headers,
    )
    assert call_resp.status_code == 201
    call_data = call_resp.json()["data"]
    call_id = call_data["id"]

    # 2. Public lists calls
    pub_list_resp = await client.get(f"/api/v1/events/{published_event.slug}/calls")
    assert pub_list_resp.status_code == 200
    pub_calls = pub_list_resp.json()["data"]
    assert any(c["id"] == call_id for c in pub_calls)

    # 3. Public submits proposal
    sub_payload = {
        "name": "Grace Hopper",
        "email": "grace@navy.mil",
        "phone": "+1-555-0199",
        "organization_name": "US Navy & Harvard",
        "job_title": "Rear Admiral / Computer Scientist",
        "bio": "Pioneer of computer programming and compiler development.",
        "title": "Compilers and Nanosecond Architecture",
        "proposal_summary": (
            "A deep dive into compiler construction and machine instruction pipelining."
        ),
        "details": "We explore optimization passes and register allocation algorithms.",
        "category_or_track": "Deep Tech",
        "attachment_url": "https://slides.example.com/compilers.pdf",
        "custom_answers": {"experience": "Keynote at national computing symposium."},
    }

    sub_resp = await client.post(
        f"/api/v1/events/{published_event.slug}/calls/{call_id}/apply",
        json=sub_payload,
    )
    assert sub_resp.status_code == 201
    sub_data = sub_resp.json()["data"]
    submission_id = sub_data["id"]
    assert sub_data["title"] == sub_payload["title"]
    assert sub_data["status"] == "submitted"

    # 4. Check submission status publicly
    status_resp = await client.get(f"/api/v1/open-calls/submissions/{submission_id}/status")
    assert status_resp.status_code == 200
    assert status_resp.json()["data"]["status"] == "submitted"

    # 5. Organizer lists submissions
    org_subs_resp = await client.get(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/calls/{call_id}/submissions",
        headers=org_headers,
    )
    assert org_subs_resp.status_code == 200
    subs = org_subs_resp.json()["data"]
    assert len(subs) == 1
    assert subs[0]["name"] == "Grace Hopper"

    # 6. Organizer reviews submission (shortlist & rate 5 stars)
    review_resp = await client.patch(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/calls/{call_id}/submissions/{submission_id}/review",
        json={
            "status": "shortlisted",
            "rating": 5,
            "organizer_notes": "Outstanding proposal. Ideal keynote session.",
            "feedback_to_applicant": "Your proposal has been shortlisted for the keynote slot.",
        },
        headers=org_headers,
    )
    assert review_resp.status_code == 200
    rev_data = review_resp.json()["data"]
    assert rev_data["status"] == "shortlisted"
    assert rev_data["rating"] == 5
    assert rev_data["organizer_notes"] == "Outstanding proposal. Ideal keynote session."

    # 7. One-click promote proposal to Speaker
    promote_resp = await client.post(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/calls/{call_id}/submissions/{submission_id}/promote",
        json={"role_type": "keynote"},
        headers=org_headers,
    )
    assert promote_resp.status_code == 200
    promoted_sub = promote_resp.json()["data"]
    assert promoted_sub["status"] == "accepted"
    speaker_id = promoted_sub["promoted_to_speaker_id"]
    assert speaker_id is not None

    # Verify speaker exists in database and is linked to the event
    sp = await db.scalar(select(Speaker).where(Speaker.id == uuid.UUID(speaker_id)))
    assert sp is not None
    assert sp.name == "Grace Hopper"
    assert sp.title == "Rear Admiral / Computer Scientist"

    ev_sp = await db.scalar(
        select(EventSpeaker).where(
            EventSpeaker.event_id == published_event.id,
            EventSpeaker.speaker_id == sp.id,
        )
    )
    assert ev_sp is not None
    assert ev_sp.role_type == "keynote"


@pytest.mark.asyncio
async def test_promote_sponsor_proposal_workflow(
    client: AsyncClient,
    db: AsyncSession,
    published_event: Event,
    org: Organization,
    user: User,
):
    token = _make_token(str(user.id))
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Create Call for Sponsors
    call_resp = await client.post(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/calls",
        json={
            "title": "Call for Event Sponsors & Partners",
            "call_type": "sponsor",
            "status": "open",
        },
        headers=headers,
    )
    call_id = call_resp.json()["data"]["id"]

    # 2. Public submission
    sub_resp = await client.post(
        f"/api/v1/events/{published_event.slug}/calls/{call_id}/apply",
        json={
            "name": "Jane Developer",
            "email": "jane@techcorp.io",
            "organization_name": "TechCorp Global",
            "title": "Gold Sponsorship Inquiry",
            "proposal_summary": (
                "TechCorp is excited to support the conference as a premier gold sponsor."
            ),
            "social_links": {"website": "https://techcorp.io"},
        },
    )
    assert sub_resp.status_code == 201
    sub_id = sub_resp.json()["data"]["id"]

    # 3. Promote to Sponsor
    promote_resp = await client.post(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/calls/{call_id}/submissions/{sub_id}/promote",
        json={"tier": "gold"},
        headers=headers,
    )
    assert promote_resp.status_code == 200
    data = promote_resp.json()["data"]
    assert data["status"] == "accepted"
    sponsor_id = data["promoted_to_sponsor_id"]
    assert sponsor_id is not None

    # Verify sponsor entity created on event
    sponsor_row = await db.scalar(select(Sponsor).where(Sponsor.id == uuid.UUID(sponsor_id)))
    assert sponsor_row is not None
    assert sponsor_row.name == "TechCorp Global"
    assert sponsor_row.tier == "gold"
    assert sponsor_row.event_id == published_event.id


@pytest.mark.asyncio
async def test_closed_open_call_rejects_submissions(
    client: AsyncClient,
    db: AsyncSession,
    published_event: Event,
    org: Organization,
    user: User,
):
    token = _make_token(str(user.id))
    headers = {"Authorization": f"Bearer {token}"}

    # Create call as closed
    call_resp = await client.post(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/calls",
        json={
            "title": "Closed Workshop CFP",
            "call_type": "speaker",
            "status": "closed",
        },
        headers=headers,
    )
    call_id = call_resp.json()["data"]["id"]

    # Attempt submission
    sub_resp = await client.post(
        f"/api/v1/events/{published_event.slug}/calls/{call_id}/apply",
        json={
            "name": "Late Applicant",
            "email": "late@example.com",
            "title": "Talk Proposal",
            "proposal_summary": "I want to submit late.",
        },
    )
    assert sub_resp.status_code == 400
    body = sub_resp.json()
    err_msg = body.get("detail") or body.get("error", {}).get("message") or ""
    assert "closed" in err_msg.lower()


@pytest.mark.asyncio
async def test_public_html_pages_for_open_calls(
    client: AsyncClient,
    db: AsyncSession,
    published_event: Event,
    org: Organization,
    user: User,
):
    token = _make_token(str(user.id))
    headers = {"Authorization": f"Bearer {token}"}

    # Create active call
    call_resp = await client.post(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/calls",
        json={
            "title": "Community Speakers Wanted",
            "call_type": "speaker",
            "status": "open",
            "description": "Come share your knowledge.",
        },
        headers=headers,
    )
    call_data = call_resp.json()["data"]

    # 1. Check public call detail HTML page
    page_resp = await client.get(f"/events/{published_event.slug}/calls/{call_data['slug']}")
    assert page_resp.status_code == 200
    html = page_resp.text
    assert "Community Speakers Wanted" in html
    assert "Submit Your Proposal" in html
    assert published_event.title in html

    # 2. Check public event page displays open calls section
    ev_page_resp = await client.get(f"/events/{published_event.slug}")
    assert ev_page_resp.status_code == 200
    ev_html = ev_page_resp.text
    assert "Open Calls &amp; Opportunities" in ev_html or "Open Calls" in ev_html
    assert "Community Speakers Wanted" in ev_html


@pytest.mark.asyncio
async def test_chatbot_open_call_grounding(
    client: AsyncClient,
    db: AsyncSession,
    published_event: Event,
    org: Organization,
    user: User,
):
    token = _make_token(str(user.id))
    headers = {"Authorization": f"Bearer {token}"}

    # Create active call for published event
    await client.post(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/calls",
        json={
            "title": "Global Tech Talk Submissions 2026",
            "call_type": "speaker",
            "status": "open",
        },
        headers=headers,
    )

    # Ask the support chatbot on that event's page context
    chat_resp = await client.post(
        "/api/v1/support/chat",
        json={
            "message": "Is there a call for papers or speaker applications open for this event?",
            "client_context": {
                "event_slug": published_event.slug,
                "page_path": f"/e/{published_event.slug}",
            },
        },
    )
    assert chat_resp.status_code == 200
    chat_data = chat_resp.json()["data"]
    assert "Global Tech Talk Submissions 2026" in chat_data["reply"]
    assert f"/events/{published_event.slug}/calls/" in chat_data["reply"]
