"""Which tracked school a chat message names, worked out before the model
sees it.

Told only "look a school up before asking", Haiku still answered "What bus
does my kid take to Beck Middle?" with "which town is Beck Middle in?" -
in 1.6s, no tool called, and there is one Beck Middle. Matching names
here and saying so in the turn's context leaves it nothing to ask about;
when several schools really fit, it gets their names and towns to ask with.
"""

import re
import time
from typing import Any

# Words that say what kind of school, not which one.
_GENERIC = {"school", "schools", "elementary", "middle", "high", "es", "ms", "hs", "the", "of", "and", "at", "st", "&"}
_TYPE_WORDS = {
    "elementary": {"elementary", "es", "primary"},
    "middle": {"middle", "ms"},
    "high": {"high", "hs"},
}
_TYPE_WORD_RE = "elementary|middle|high|school|es|ms|hs"
_MAX_LISTED = 6


def _words(text: str | None) -> list[str]:
    return [w for w in re.split(r"[^a-z0-9]+", (text or "").lower()) if w]


def _key(text: str | None) -> set[str]:
    """Distinctive words of a name: no generic words, no initials ("Henry C. Beck")."""
    return {w for w in _words(text) if w not in _GENERIC and len(w) > 1}


def town(address: str | None) -> str | None:
    """"1 Main St, Cherry Hill, NJ 08002" -> "Cherry Hill"."""
    parts = [p.strip() for p in (address or "").split(",")]
    return parts[-2] if len(parts) >= 3 else None


def match_schools(message: str, schools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The schools the message names, best first; [] when it names none.

    A school fits when every distinctive word of its name or short name is
    in the message ("cherry hill east", "beck", "kingston"). A name that is
    only its town ("Haddonfield" HS) also needs a type word, so "Haddonfield
    schools" names the district, not the high school. Failing that, the last
    word of a name alone ("Johnson Elementary" for James Johnson), used as a
    name and not part of some town's name ("Hill", "East").
    """
    said = set(_words(message))
    town_words = {w for s in schools for w in _words(town(s.get("address")))}
    full: list[tuple[int, dict]] = []
    for s in schools:
        own_town = set(_words(town(s.get("address"))))
        typed = bool(said & _TYPE_WORDS.get(s.get("school_type") or "", set()))
        best = 0
        for name in (s.get("name"), s.get("short_name")):
            key = _key(name)
            if key and key <= said and (typed or not key <= own_town):
                best = max(best, len(key))
        if best:
            full.append((best, s))
    if full:
        top = max(n for n, _ in full)
        return [s for n, s in full if n == top]
    loose = []
    for s in schools:
        last = [w for w in _words(s.get("short_name") or s.get("name")) if w not in _GENERIC and len(w) > 1]
        if not last or len(last[-1]) <= 3 or last[-1] in town_words:
            continue
        # Used as a school's name: before a type word, or ending the question.
        # Without this, "picture day" named Big Picture Learning Academy and
        # "when does winter break start" a Head Start centre.
        if re.search(rf"\b{re.escape(last[-1])}\b(?:\s+(?:{_TYPE_WORD_RE})\b|\W*$)", message.lower()):
            loose.append(s)
    return loose


def school_hint(message: str, schools: list[dict[str, Any]]) -> str | None:
    """A line for the turn's context naming the school(s) the message means, or None."""
    found = match_schools(message, schools)
    if not found or len(found) > _MAX_LISTED:
        return None

    def label(s: dict) -> str:
        where = town(s.get("address"))
        return f"{s['name']}{f' in {where}' if where else ''} (slug '{s['slug']}')"

    if len(found) == 1:
        return (
            f"The school this message names is {label(found[0])} - the only tracked school by that name. "
            "Look it up with that slug; don't ask which school or town."
        )
    return (
        "Several tracked schools fit the name in this message: " + "; ".join(label(s) for s in found)
        + ". Unless the message says which (a town, a type), ask which one they mean, by name and town."
    )


class SchoolDirectory:
    """The tracked schools, re-read at most every few minutes (a school added
    by an admin shows up without a restart)."""

    def __init__(self, ttl_s: float = 600):
        self._ttl_s = ttl_s
        self._at = 0.0
        self._rows: list[dict[str, Any]] = []

    async def rows(self, load) -> list[dict[str, Any]]:
        if not self._rows or time.monotonic() - self._at > self._ttl_s:
            self._rows = await load()
            self._at = time.monotonic()
        return self._rows
