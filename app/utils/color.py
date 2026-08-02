from __future__ import annotations


def contrasting_text_color(hex_color: str | None, default: str = "#000000") -> str:
    """#000000 or #ffffff — whichever reads better on top of hex_color, via
    the standard relative-luminance heuristic. Falls back to `default` for
    missing/invalid input (e.g. an org with no brand_color set)."""
    if not hex_color:
        return default
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return default
    try:
        r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return default
    luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    return "#000000" if luminance > 0.6 else "#ffffff"
