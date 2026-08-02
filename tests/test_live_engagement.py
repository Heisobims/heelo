"""Live polls and Q&A. Per product decision: Q&A is anonymous free-for-all —
no submission approval queue, organizer can only hide/delete after the fact.
No account/login required to vote, ask, or upvote.
"""

from __future__ import annotations

from httpx import AsyncClient


class TestPolls:
    async def test_create_poll_defaults_to_draft(
        self, client: AsyncClient, org, published_event, user_headers
    ):
        resp = await client.post(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/live/polls",
            json={"question": "Favorite talk so far?", "options": ["Talk A", "Talk B"]},
            headers=user_headers,
        )
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["status"] == "draft"
        assert len(data["options"]) == 2
        assert data["options"][0]["vote_count"] == 0

    async def test_open_poll_closes_other_open_polls(
        self, client: AsyncClient, org, published_event, user_headers
    ):
        async def _create():
            resp = await client.post(
                f"/api/v1/organizations/{org.slug}/events/{published_event.id}/live/polls",
                json={"question": "Q", "options": ["A", "B"]},
                headers=user_headers,
            )
            return resp.json()["data"]["id"]

        poll1 = await _create()
        poll2 = await _create()

        await client.post(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/live/polls/{poll1}/open",
            headers=user_headers,
        )
        await client.post(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/live/polls/{poll2}/open",
            headers=user_headers,
        )

        resp = await client.get(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/live/polls",
            headers=user_headers,
        )
        by_id = {p["id"]: p["status"] for p in resp.json()["data"]}
        assert by_id[poll1] == "closed"
        assert by_id[poll2] == "open"

    async def test_public_sees_the_open_poll(
        self, client: AsyncClient, org, published_event, user_headers
    ):
        resp = await client.post(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/live/polls",
            json={"question": "Q", "options": ["A", "B"]},
            headers=user_headers,
        )
        poll_id = resp.json()["data"]["id"]
        await client.post(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/live/polls/{poll_id}/open",
            headers=user_headers,
        )

        resp = await client.get(f"/api/v1/events/{published_event.slug}/live/poll")
        assert resp.status_code == 200
        assert resp.json()["data"]["id"] == poll_id

    async def test_public_sees_no_poll_when_none_open(self, client: AsyncClient, published_event):
        resp = await client.get(f"/api/v1/events/{published_event.slug}/live/poll")
        assert resp.status_code == 200
        assert resp.json()["data"] is None

    async def test_vote_increments_option_and_is_public(
        self, client: AsyncClient, org, published_event, user_headers
    ):
        resp = await client.post(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/live/polls",
            json={"question": "Q", "options": ["A", "B"]},
            headers=user_headers,
        )
        poll = resp.json()["data"]
        option_id = poll["options"][0]["id"]
        await client.post(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/live/polls/{poll['id']}/open",
            headers=user_headers,
        )

        resp = await client.post(
            f"/api/v1/events/{published_event.slug}/live/polls/{poll['id']}/vote",
            json={"option_id": option_id},
        )
        assert resp.status_code == 200
        voted_option = next(o for o in resp.json()["data"]["options"] if o["id"] == option_id)
        assert voted_option["vote_count"] == 1

    async def test_vote_rejected_when_poll_not_open(
        self, client: AsyncClient, org, published_event, user_headers
    ):
        resp = await client.post(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/live/polls",
            json={"question": "Q", "options": ["A", "B"]},
            headers=user_headers,
        )
        poll = resp.json()["data"]

        resp = await client.post(
            f"/api/v1/events/{published_event.slug}/live/polls/{poll['id']}/vote",
            json={"option_id": poll["options"][0]["id"]},
        )
        assert resp.status_code == 400

    async def test_checkin_staff_cannot_create_poll(
        self, client: AsyncClient, org, published_event, checkin_staff_headers
    ):
        resp = await client.post(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/live/polls",
            json={"question": "Q", "options": ["A", "B"]},
            headers=checkin_staff_headers,
        )
        assert resp.status_code == 403

    async def test_delete_poll(self, client: AsyncClient, org, published_event, user_headers):
        resp = await client.post(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/live/polls",
            json={"question": "Q", "options": ["A", "B"]},
            headers=user_headers,
        )
        poll_id = resp.json()["data"]["id"]
        resp = await client.delete(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/live/polls/{poll_id}",
            headers=user_headers,
        )
        assert resp.status_code == 204


class TestQuestions:
    async def test_anyone_can_submit_a_question_anonymously(
        self, client: AsyncClient, published_event
    ):
        resp = await client.post(
            f"/api/v1/events/{published_event.slug}/live/questions",
            json={"body": "What time does the venue open?"},
        )
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["author_name"] is None
        assert data["upvotes"] == 0
        assert data["is_answered"] is False

    async def test_question_visible_immediately_no_approval_queue(
        self, client: AsyncClient, published_event
    ):
        await client.post(
            f"/api/v1/events/{published_event.slug}/live/questions",
            json={"body": "Immediate visibility check"},
        )
        resp = await client.get(f"/api/v1/events/{published_event.slug}/live/questions")
        assert resp.status_code == 200
        bodies = [q["body"] for q in resp.json()["data"]]
        assert "Immediate visibility check" in bodies

    async def test_upvote_increments(self, client: AsyncClient, published_event):
        resp = await client.post(
            f"/api/v1/events/{published_event.slug}/live/questions",
            json={"body": "Upvote me"},
        )
        qid = resp.json()["data"]["id"]
        resp = await client.post(
            f"/api/v1/events/{published_event.slug}/live/questions/{qid}/upvote"
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["upvotes"] == 1

    async def test_organizer_can_hide_question_removing_it_from_public_list(
        self, client: AsyncClient, org, published_event, user_headers
    ):
        resp = await client.post(
            f"/api/v1/events/{published_event.slug}/live/questions",
            json={"body": "Should be hidden"},
        )
        qid = resp.json()["data"]["id"]

        resp = await client.patch(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/live/questions/{qid}",
            json={"is_hidden": True},
            headers=user_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["is_hidden"] is True

        resp = await client.get(f"/api/v1/events/{published_event.slug}/live/questions")
        bodies = [q["body"] for q in resp.json()["data"]]
        assert "Should be hidden" not in bodies

    async def test_organizer_list_includes_hidden(
        self, client: AsyncClient, org, published_event, user_headers
    ):
        resp = await client.post(
            f"/api/v1/events/{published_event.slug}/live/questions",
            json={"body": "Hidden but visible to organizer"},
        )
        qid = resp.json()["data"]["id"]
        await client.patch(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/live/questions/{qid}",
            json={"is_hidden": True},
            headers=user_headers,
        )

        resp = await client.get(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/live/questions",
            headers=user_headers,
        )
        bodies = [q["body"] for q in resp.json()["data"]]
        assert "Hidden but visible to organizer" in bodies

    async def test_checkin_staff_cannot_delete_question(
        self, client: AsyncClient, org, published_event, checkin_staff_headers
    ):
        resp = await client.post(
            f"/api/v1/events/{published_event.slug}/live/questions",
            json={"body": "Q"},
        )
        qid = resp.json()["data"]["id"]
        resp = await client.delete(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/live/questions/{qid}",
            headers=checkin_staff_headers,
        )
        assert resp.status_code == 403


class TestLivePages:
    async def test_attendee_live_page_is_public(self, client: AsyncClient, published_event):
        resp = await client.get(f"/e/{published_event.slug}/live")
        assert resp.status_code == 200
        assert published_event.title in resp.text

    async def test_organizer_live_page_requires_permission(
        self, client: AsyncClient, org, published_event, user
    ):
        from tests.conftest import _make_token

        client.cookies.set("heelo_access", _make_token(str(user.id)))
        resp = await client.get(f"/org/{org.slug}/events/{published_event.id}/live")
        assert resp.status_code == 200
        assert "Live" in resp.text

    async def test_organizer_live_page_403_for_checkin_staff(
        self, client: AsyncClient, org, published_event, checkin_staff_member, other_user
    ):
        from tests.conftest import _make_token

        client.cookies.set("heelo_access", _make_token(str(other_user.id)))
        resp = await client.get(f"/org/{org.slug}/events/{published_event.id}/live")
        assert resp.status_code == 403
