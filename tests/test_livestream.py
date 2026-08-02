"""Livestream — simple paste-your-own-URL player (YouTube/Vimeo/HLS/generic
embed), not a real video-API integration. See build-order discussion: no
paid video API account exists to integrate against and test in this
environment, so this is the deliberately scoped option.
"""

from __future__ import annotations

from httpx import AsyncClient

from app.utils.livestream import resolve_embed


class TestResolveEmbed:
    def test_none_or_empty_returns_none(self):
        assert resolve_embed(None) is None
        assert resolve_embed("") is None
        assert resolve_embed("   ") is None

    def test_youtube_watch_url(self):
        result = resolve_embed("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        assert result == {
            "type": "iframe",
            "embed_url": "https://www.youtube.com/embed/dQw4w9WgXcQ",
        }

    def test_youtube_short_url(self):
        result = resolve_embed("https://youtu.be/dQw4w9WgXcQ")
        assert result["type"] == "iframe"
        assert result["embed_url"] == "https://www.youtube.com/embed/dQw4w9WgXcQ"

    def test_youtube_live_url(self):
        result = resolve_embed("https://www.youtube.com/live/dQw4w9WgXcQ")
        assert result["embed_url"] == "https://www.youtube.com/embed/dQw4w9WgXcQ"

    def test_vimeo_url(self):
        result = resolve_embed("https://vimeo.com/76979871")
        assert result == {"type": "iframe", "embed_url": "https://player.vimeo.com/video/76979871"}

    def test_hls_url(self):
        result = resolve_embed("https://stream.example.com/live/playlist.m3u8")
        assert result == {
            "type": "hls",
            "embed_url": "https://stream.example.com/live/playlist.m3u8",
        }

    def test_hls_url_with_query_params(self):
        result = resolve_embed("https://stream.example.com/live/playlist.m3u8?token=abc123")
        assert result["type"] == "hls"

    def test_generic_url_falls_back_to_iframe(self):
        result = resolve_embed("https://streamyard.com/embed/xyz123")
        assert result == {"type": "iframe", "embed_url": "https://streamyard.com/embed/xyz123"}


class TestLivestreamAPI:
    async def test_update_persists_livestream_url(
        self, client: AsyncClient, org, published_event, user_headers
    ):
        resp = await client.patch(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}",
            json={"livestream_url": "https://youtube.com/watch?v=abc12345678"},
            headers=user_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["livestream_url"] == "https://youtube.com/watch?v=abc12345678"

    async def test_clearing_livestream_url(
        self, client: AsyncClient, org, published_event, user_headers
    ):
        await client.patch(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}",
            json={"livestream_url": "https://youtube.com/watch?v=abc12345678"},
            headers=user_headers,
        )
        resp = await client.patch(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}",
            json={"livestream_url": None},
            headers=user_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["livestream_url"] is None


class TestLivePageVideoPlayer:
    async def test_no_player_when_url_unset(self, client: AsyncClient, published_event):
        resp = await client.get(f"/e/{published_event.slug}/live")
        assert resp.status_code == 200
        assert '<div class="lv-video-wrap">' not in resp.text

    async def test_iframe_player_for_youtube(
        self, client: AsyncClient, org, published_event, user_headers
    ):
        await client.patch(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}",
            json={"livestream_url": "https://youtube.com/watch?v=abc12345678"},
            headers=user_headers,
        )
        resp = await client.get(f"/e/{published_event.slug}/live")
        assert resp.status_code == 200
        assert "lv-video-wrap" in resp.text
        assert "https://www.youtube.com/embed/abc12345678" in resp.text

    async def test_hls_player_loads_hlsjs(
        self, client: AsyncClient, org, published_event, user_headers
    ):
        await client.patch(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}",
            json={"livestream_url": "https://stream.example.com/live.m3u8"},
            headers=user_headers,
        )
        resp = await client.get(f"/e/{published_event.slug}/live")
        assert resp.status_code == 200
        assert "lv-hls-video" in resp.text
        assert "hls.min.js" in resp.text
        assert "https://stream.example.com/live.m3u8" in resp.text

    async def test_organizer_page_prefills_livestream_url(
        self, client: AsyncClient, org, published_event, user, user_headers
    ):
        from tests.conftest import _make_token

        await client.patch(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}",
            json={"livestream_url": "https://youtube.com/watch?v=abc12345678"},
            headers=user_headers,
        )
        client.cookies.set("heelo_access", _make_token(str(user.id)))
        resp = await client.get(f"/org/{org.slug}/events/{published_event.id}/live")
        assert resp.status_code == 200
        assert "https://youtube.com/watch?v=abc12345678" in resp.text
