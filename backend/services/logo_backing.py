"""Which backing disc a school logo needs to stay visible in both themes.

Districts publish logos made for their own site's header: a transparent PNG
in white ink for a dark header, or in dark ink for a white one. On the wrong
theme here the image loads fine and shows nothing. No single backing fixes
both kinds, so each logo is classified from its pixels:

- "none"  - readable on both themes as-is (or opaque: it carries its own box)
- "dark"  - light ink, needs a dark disc behind it
- "light" - dark ink, needs a light disc behind it

A wrong "none" is an invisible logo, a wrong "light"/"dark" is only a disc
behind a logo that didn't strictly need one - hence the low thresholds.
"""
import io
import logging

import httpx
from PIL import Image

logger = logging.getLogger(__name__)

BACKINGS = ("none", "light", "dark")

# The two card colours a logo sits on (--card in frontend/src/styles.css).
_LIGHT_BG = (255, 255, 255)
_DARK_BG = (31, 35, 42)
# Ink below this contrast ratio against the background can't be made out.
_MIN_CONTRAST = 1.6
# Share of the ink that has to disappear on a theme before it gets a backing.
# The dark disc asks for more: white ink is often just the fill inside a
# coloured crest that reads fine without it, and a black disc shows on the
# light theme, whereas a white disc there is invisible. Set by eye against
# every tracked logo - at these values nothing unreadable was left unbacked.
_HIDDEN_ON_LIGHT = 0.5
_HIDDEN_ON_DARK = 0.4
# An image this covered by opaque pixels is its own box - visible anywhere.
_OPAQUE_SHARE = 0.8
_SAMPLE_PX = 64


def _luminance(r: float, g: float, b: float) -> float:
    def lin(c: float) -> float:
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def _hidden(pixel: tuple[int, int, int, int], bg: tuple[int, int, int]) -> bool:
    a = pixel[3] / 255
    blended = _luminance(*(pixel[i] * a + bg[i] * (1 - a) for i in range(3)))
    bg_lum = _luminance(*bg)
    hi, lo = max(blended, bg_lum), min(blended, bg_lum)
    return (hi + 0.05) / (lo + 0.05) < _MIN_CONTRAST


def classify_logo(data: bytes) -> str:
    """Backing for the image in `data`. Anything Pillow can't read (an SVG)
    is "none" - today's behaviour - and left to a manual override."""
    try:
        image = Image.open(io.BytesIO(data)).convert("RGBA")
    except Exception:
        return "none"
    image.thumbnail((_SAMPLE_PX, _SAMPLE_PX))
    raw = image.tobytes()
    pixels = [tuple(raw[i : i + 4]) for i in range(0, len(raw), 4)]
    ink = [p for p in pixels if p[3] > 12]
    if not ink or sum(1 for p in pixels if p[3] > 230) / len(pixels) >= _OPAQUE_SHARE:
        return "none"
    on_light = sum(1 for p in ink if _hidden(p, _LIGHT_BG)) / len(ink)
    on_dark = sum(1 for p in ink if _hidden(p, _DARK_BG)) / len(ink)
    needs_dark, needs_light = on_light >= _HIDDEN_ON_LIGHT, on_dark >= _HIDDEN_ON_DARK
    if needs_dark and needs_light:
        # Ink of both kinds: back against whichever theme hides more of it.
        return "dark" if on_light >= on_dark else "light"
    return "dark" if needs_dark else "light" if needs_light else "none"


async def classify_logo_url(url: str) -> str | None:
    """Backing for the logo at `url`, or None when it couldn't be fetched
    (left unclassified, so the next scan tries again)."""
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 (schoolz-logo)"}) as client:
            resp = await client.get(url)
            resp.raise_for_status()
    except Exception as e:
        logger.info("logo fetch failed for %s: %s", url, e)
        return None
    return classify_logo(resp.content)
