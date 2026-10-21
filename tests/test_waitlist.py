"""Waitlist management - organizer-facing list/remove/notify-next on top of
the existing public join flow, plus the notified_at bookkeeping fix that
makes "notify the next un-notified person" actually advance through the
queue instead of re-selecting the same person indefinitely.
"""

from __future__ import annotations

from httpx import AsyncClient


async def _join(client, published_event, ticket_type, email, name="Waiting Person"):
    """Join the waitlist and return the full organizer-visible entry (the
    public join endpoint only echoes back `position`, not the entry `id`)."""
    resp = await client.post(
        f"/api/v1/events/{published_event.slug}/waitlist",
        json={"ticket_type_id": str(ticket_type.id), "name": name, "email": email},
    )
    assert resp.status_code == 201
    return resp.json()["data"]


async def _find_entry(client, org, event, headers, email):
    resp = await client.get(
        f"/api/v1/organizations/{org.slug}/events/{event.id}/waitlist", headers=headers
    )
    return next(e for e in resp.json()["data"] if e["email"] == email)


class TestOrganizerWaitlistView:
    async def test_list_waitlist_shows_ticket_type_name(
        self, client: AsyncClient, org, published_event, ticket_type, user_headers
    ):
        await _join(client, published_event, ticket_type, "a@example.com")
        await _join(client, published_event, ticket_type, "b@example.com")

        resp = await client.get(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/waitlist",
            headers=user_headers,
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) == 2
        assert data[0]["ticket_type_name"] == ticket_type.name
        assert data[0]["position"] == 1
        assert data[1]["position"] == 2

    async def test_checkin_staff_can_view_but_not_remove(
        self,
        client: AsyncClient,
        org,
        published_event,
        ticket_type,
        user_headers,
        checkin_staff_headers,
    ):
        await _join(client, published_event, ticket_type, "c@example.com")
        entry = await _find_entry(client, org, published_event, user_headers, "c@example.com")

        resp = await client.get(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/waitlist",
            headers=checkin_staff_headers,
        )
        assert resp.status_code == 200

        resp = await client.delete(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/waitlist/{entry['id']}",
            headers=checkin_staff_headers,
        )
        assert resp.status_code == 403


class TestRemoveFromWaitlist:
    async def test_remove_closes_position_gap(
        self, client: AsyncClient, org, published_event, ticket_type, user_headers
    ):
        await _join(client, published_event, ticket_type, "a@example.com", "A")
        await _join(client, published_event, ticket_type, "b@example.com", "B")
        await _join(client, published_event, ticket_type, "c@example.com", "C")
        e1 = await _find_entry(client, org, published_event, user_headers, "a@example.com")

        resp = await client.delete(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/waitlist/{e1['id']}",
            headers=user_headers,
        )
        assert resp.status_code == 204

        resp = await client.get(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/waitlist",
            headers=user_headers,
        )
        remaining = sorted(resp.json()["data"], key=lambda e: e["position"])
        assert [e["name"] for e in remaining] == ["B", "C"]
        assert [e["position"] for e in remaining] == [1, 2]


class TestNotifyNextWaitlistEntry:
    async def test_notify_next_sets_notified_and_expiry(
        self, client: AsyncClient, org, published_event, ticket_type, user_headers
    ):
        await _join(client, published_event, ticket_type, "a@example.com", "A")
        await _join(client, published_event, ticket_type, "b@example.com", "B")

        resp = await client.post(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}"
            f"/ticket-types/{ticket_type.id}/waitlist/notify-next",
            headers=user_headers,
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["name"] == "A"
        assert data["notified_at"] is not None
        assert data["offer_expires_at"] is not None

    async def test_notify_next_advances_past_already_notified_person(
        self, client: AsyncClient, org, published_event, ticket_type, user_headers
    ):
        """Regression test: notify_next used to only set offer_expires_at, never
        notified_at, so the "next un-notified person" query kept re-selecting
        person A forever instead of moving on to B."""
        await _join(client, published_event, ticket_type, "a@example.com", "A")
        await _join(client, published_event, ticket_type, "b@example.com", "B")

        url = (
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}"
            f"/ticket-types/{ticket_type.id}/waitlist/notify-next"
        )
        first = await client.post(url, headers=user_headers)
        second = await client.post(url, headers=user_headers)

        assert first.json()["data"]["name"] == "A"
        assert second.json()["data"]["name"] == "B"

    async def test_notify_next_with_empty_waitlist_returns_none(
        self, client: AsyncClient, org, published_event, ticket_type, user_headers
    ):
        resp = await client.post(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}"
            f"/ticket-types/{ticket_type.id}/waitlist/notify-next",
            headers=user_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["data"] is None

    async def test_checkin_staff_cannot_notify_next(
        self, client: AsyncClient, org, published_event, ticket_type, checkin_staff_headers
    ):
        resp = await client.post(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}"
            f"/ticket-types/{ticket_type.id}/waitlist/notify-next",
            headers=checkin_staff_headers,
        )
        assert resp.status_code == 403


class TestCancellationTriggersWaitlistNotification:
    async def test_cancelling_a_registration_notifies_next_waitlisted_person(
        self, client: AsyncClient, org, published_event, ticket_type, registration, user_headers
    ):
        await _join(client, published_event, ticket_type, "a@example.com", "A")

        resp = await client.post(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}"
            f"/registrations/{registration.id}/cancel",
            json={"refund": False},
            headers=user_headers,
        )
        assert resp.status_code == 200

        resp = await client.get(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/waitlist",
            headers=user_headers,
        )
        entry = resp.json()["data"][0]
        assert entry["notified_at"] is not None


class TestRegistrationClaimsWaitlistSpot:
    async def test_successful_registration_removes_matching_waitlist_entry(
        self, client: AsyncClient, org, published_event, user_headers
    ):
        resp = await client.post(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/ticket-types",
            json={"name": "Free", "price": 0, "currency": "NGN", "quantity": 100},
            headers=user_headers,
        )
        free_tt_id = resp.json()["id"]

        resp = await client.post(
            f"/api/v1/events/{published_event.slug}/waitlist",
            json={
                "ticket_type_id": free_tt_id,
                "name": "Claimant",
                "email": "claimant@example.com",
            },
        )
        assert resp.status_code == 201

        resp = await client.post(
            f"/api/v1/events/{published_event.slug}/register",
            json={
                "items": [{"ticket_type_id": free_tt_id, "quantity": 1}],
                "buyer_name": "Claimant",
                "buyer_email": "claimant@example.com",
            },
        )
        assert resp.status_code in (200, 201)

        resp = await client.get(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/waitlist",
            headers=user_headers,
        )
        emails = [e["email"] for e in resp.json()["data"]]
        assert "claimant@example.com" not in emails
