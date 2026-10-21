"""Registration form field management - update endpoint (previously only
create/delete existed despite the update schema already being defined),
plus applies_to_ticket_type_ids scoping and its enforcement at checkout.
"""

from __future__ import annotations

from httpx import AsyncClient


class TestFormFieldUpdate:
    async def test_update_form_field(self, client: AsyncClient, org, published_event, user_headers):
        resp = await client.post(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/form-fields",
            json={"label": "T-shirt size", "field_type": "short_text"},
            headers=user_headers,
        )
        assert resp.status_code == 201
        ff_id = resp.json()["id"]

        resp = await client.patch(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/form-fields/{ff_id}",
            json={"label": "Shirt size", "is_required": True, "sort_order": 3},
            headers=user_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["label"] == "Shirt size"
        assert data["is_required"] is True
        assert data["sort_order"] == 3

    async def test_update_applies_to_ticket_type_ids(
        self, client: AsyncClient, org, published_event, ticket_type, user_headers
    ):
        resp = await client.post(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/form-fields",
            json={"label": "VIP question", "field_type": "short_text"},
            headers=user_headers,
        )
        ff_id = resp.json()["id"]

        resp = await client.patch(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/form-fields/{ff_id}",
            json={"applies_to_ticket_type_ids": [str(ticket_type.id)]},
            headers=user_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["applies_to_ticket_type_ids"] == [str(ticket_type.id)]

        resp = await client.patch(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/form-fields/{ff_id}",
            json={"applies_to_ticket_type_ids": []},
            headers=user_headers,
        )
        assert resp.json()["applies_to_ticket_type_ids"] is None

    async def test_checkin_staff_cannot_update_form_field(
        self, client: AsyncClient, org, published_event, user_headers, checkin_staff_headers
    ):
        resp = await client.post(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/form-fields",
            json={"label": "Question", "field_type": "short_text"},
            headers=user_headers,
        )
        ff_id = resp.json()["id"]

        resp = await client.patch(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/form-fields/{ff_id}",
            json={"label": "Hijacked"},
            headers=checkin_staff_headers,
        )
        assert resp.status_code == 403

    async def test_update_nonexistent_field_404s(
        self, client: AsyncClient, org, published_event, user_headers
    ):
        resp = await client.patch(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}"
            f"/form-fields/00000000-0000-0000-0000-000000000000",
            json={"label": "x"},
            headers=user_headers,
        )
        assert resp.status_code == 404


class TestCheckoutFieldScoping:
    async def test_form_fields_json_includes_ticket_scoping(
        self, client: AsyncClient, org, published_event, ticket_type, user_headers
    ):
        await client.post(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/form-fields",
            json={
                "label": "VIP-only question",
                "field_type": "short_text",
                "applies_to_ticket_type_ids": [str(ticket_type.id)],
            },
            headers=user_headers,
        )
        resp = await client.get(f"/e/{published_event.slug}/register")
        assert resp.status_code == 200
        assert "VIP-only question" in resp.text
        assert str(ticket_type.id) in resp.text

    async def test_organizer_edit_page_preloads_form_fields(
        self, client: AsyncClient, org, published_event, ticket_type, user, user_headers
    ):
        # Page routes (app/routers/pages.py) authenticate via the heelo_access
        # cookie, not an Authorization header - unlike the JSON API.
        from tests.conftest import _make_token

        await client.post(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/form-fields",
            json={"label": "Preloaded question", "field_type": "short_text"},
            headers=user_headers,
        )

        client.cookies.set("heelo_access", _make_token(str(user.id)))
        resp = await client.get(f"/org/{org.slug}/events/{published_event.id}/edit")
        assert resp.status_code == 200
        assert "Preloaded question" in resp.text
