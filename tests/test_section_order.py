"""Public event page section reordering - organizer-controlled drag-and-drop
order + show/hide for existing content sections (About, Agenda, People,
Partners, Gallery, Discussion). Deliberately scoped to reordering, not a
full block-based page composer.
"""

from __future__ import annotations

from httpx import AsyncClient

from app.schemas.event import DEFAULT_SECTION_ORDER
from app.services.event_service import get_effective_section_order


class TestEffectiveSectionOrder:
    def test_none_returns_default_order(self):
        class FakeEvent:
            section_order = None

        result = get_effective_section_order(FakeEvent())
        assert [s["key"] for s in result] == DEFAULT_SECTION_ORDER
        assert all(s["visible"] for s in result)

    def test_saved_order_is_used_as_is(self):
        class FakeEvent:
            section_order = [
                {"key": "discussion", "visible": True},
                {"key": "about", "visible": False},
            ]

        result = get_effective_section_order(FakeEvent())
        keys = [s["key"] for s in result]
        assert keys[0] == "discussion"
        assert keys[1] == "about"

    def test_missing_keys_are_backfilled_as_visible(self):
        class FakeEvent:
            section_order = [{"key": "about", "visible": False}]

        result = get_effective_section_order(FakeEvent())
        keys = {s["key"] for s in result}
        assert keys == set(DEFAULT_SECTION_ORDER)
        backfilled = next(s for s in result if s["key"] == "agenda")
        assert backfilled["visible"] is True


class TestSectionOrderAPI:
    async def test_update_persists_section_order(
        self, client: AsyncClient, org, published_event, user_headers
    ):
        resp = await client.patch(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}",
            json={
                "section_order": [
                    {"key": "discussion", "visible": True},
                    {"key": "about", "visible": False},
                    {"key": "agenda", "visible": True},
                    {"key": "people", "visible": True},
                    {"key": "partners", "visible": True},
                    {"key": "gallery", "visible": True},
                ]
            },
            headers=user_headers,
        )
        assert resp.status_code == 200
        order = resp.json()["data"]["section_order"]
        assert order[0] == {"key": "discussion", "visible": True}
        assert order[1] == {"key": "about", "visible": False}

    async def test_invalid_section_key_rejected(
        self, client: AsyncClient, org, published_event, user_headers
    ):
        resp = await client.patch(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}",
            json={"section_order": [{"key": "not_a_real_section", "visible": True}]},
            headers=user_headers,
        )
        assert resp.status_code == 422


class TestPublicPageReordering:
    async def test_default_order_shows_about_before_discussion(
        self, client: AsyncClient, org, published_event, user_headers
    ):
        await client.patch(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}",
            json={"description": "A great event about testing."},
            headers=user_headers,
        )
        resp = await client.get(f"/e/{published_event.slug}")
        assert resp.status_code == 200
        assert resp.text.index("About this event") < resp.text.index(
            "Questions, comments and thoughts"
        )

    async def test_custom_order_moves_discussion_before_about(
        self, client: AsyncClient, org, published_event, user_headers
    ):
        await client.patch(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}",
            json={
                "description": "A great event about testing.",
                "section_order": [
                    {"key": "discussion", "visible": True},
                    {"key": "about", "visible": True},
                    {"key": "agenda", "visible": True},
                    {"key": "people", "visible": True},
                    {"key": "partners", "visible": True},
                    {"key": "gallery", "visible": True},
                ],
            },
            headers=user_headers,
        )
        resp = await client.get(f"/e/{published_event.slug}")
        assert resp.status_code == 200
        assert resp.text.index("Questions, comments and thoughts") < resp.text.index(
            "About this event"
        )

    async def test_hidden_section_does_not_render(
        self, client: AsyncClient, org, published_event, user_headers
    ):
        await client.patch(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}",
            json={
                "description": "Should stay hidden.",
                "section_order": [
                    {"key": "about", "visible": False},
                    {"key": "agenda", "visible": True},
                    {"key": "people", "visible": True},
                    {"key": "partners", "visible": True},
                    {"key": "gallery", "visible": True},
                    {"key": "discussion", "visible": True},
                ],
            },
            headers=user_headers,
        )
        resp = await client.get(f"/e/{published_event.slug}")
        assert resp.status_code == 200
        # The About *card* (title + description body) shouldn't render - the
        # description text alone isn't a safe marker since it's also used in
        # the page's <meta og:description> tag regardless of section visibility.
        assert "About this event" not in resp.text

    async def test_organizer_edit_page_preloads_section_order(
        self, client: AsyncClient, org, published_event, user, user_headers
    ):
        from tests.conftest import _make_token

        await client.patch(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}",
            json={
                "section_order": [
                    {"key": "gallery", "visible": False},
                    {"key": "about", "visible": True},
                    {"key": "agenda", "visible": True},
                    {"key": "people", "visible": True},
                    {"key": "partners", "visible": True},
                    {"key": "discussion", "visible": True},
                ]
            },
            headers=user_headers,
        )

        client.cookies.set("tixdoo_access", _make_token(str(user.id)))
        resp = await client.get(f"/org/{org.slug}/events/{published_event.id}/edit")
        assert resp.status_code == 200
        assert "existingSectionOrder" in resp.text
        assert "gallery" in resp.text
