"""Resolve an organizer-pasted stream URL (YouTube, Vimeo, a raw HLS
playlist, or any other embeddable link) into what the live page needs to
render a player. Pure function, no I/O - easy to unit test and reuse from
both the page route and anywhere else that needs it.
"""

from __future__ import annotations

import re

_YOUTUBE_RE = re.compile(r"(?:youtube\.com/(?:watch\?v=|live/|embed/)|youtu\.be/)([\w-]{6,})")
_VIMEO_RE = re.compile(r"vimeo\.com/(?:video/)?(\d+)")


def resolve_embed(url: str | None) -> dict | None:
    """Returns None if no URL is set, otherwise {"type": "iframe"|"hls",
    "embed_url": str} describing how to play it."""
    if not url or not url.strip():
        return None
    url = url.strip()

    yt_match = _YOUTUBE_RE.search(url)
    if yt_match:
        return {"type": "iframe", "embed_url": f"https://www.youtube.com/embed/{yt_match.group(1)}"}

    vimeo_match = _VIMEO_RE.search(url)
    if vimeo_match:
        return {
            "type": "iframe",
            "embed_url": f"https://player.vimeo.com/video/{vimeo_match.group(1)}",
        }

    if url.lower().split("?")[0].endswith(".m3u8"):
        return {"type": "hls", "embed_url": url}

    # Fallback: most other providers (Twitch, StreamYard, Restream, a
    # custom player page) hand out a URL that's already embeddable in an
    # iframe as-is.
    return {"type": "iframe", "embed_url": url}
