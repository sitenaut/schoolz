"""The day-rotation marker a school calendar prints on each school day.

Numbered ("Day 3": Cherry Hill, Harrison) or lettered ("Day C": Mantua,
Swedesboro-Woolwich run A-F). Every reader goes through `parse`, so a new
spelling is added once. A lettered day keeps its letter for display and its
place in the alphabet for everything stored by number: a child's specials
are keyed on `StudentSpecial.rotation_day`, an int, so "Day C" and "Day 3"
share a row and no migration was needed.

Accepted: "Day 3", "Day C", "DAY C", "C Day" (Swedesboro-Woolwich words half
its feed that way), each with an optional trailing parenthetical - Eastern's
class order "Day 3 ( 3, 4, 1, LL)", Mantua's "DAY E (Snow Day)", the make-up
day that carries the letter it stands in for. The letter must be capital so
"a day" in a sentence never reads as one; `canonical_title` is what the feed
fetchers store, and the same rule is mirrored in
frontend/src/lib/districtItems.ts (ROTATION_RE).
"""

import re
from dataclasses import dataclass

LETTERS = "ABCDEFGHIJKL"  # StudentSpecial.rotation_day is capped at 12

_ROTATION_RE = re.compile(
    r"^\s*(?:day\s+(?P<after>\d+|(?-i:[A-L]))|(?P<before>(?-i:[A-L]))\s+day)\s*(?P<extra>\([^)]*\))?\s*$",
    re.I,
)


@dataclass(frozen=True)
class RotationDay:
    key: str  # what the calendar prints: "3" or "C"
    extra: str | None  # the trailing parenthetical, as printed

    @property
    def lettered(self) -> bool:
        return not self.key.isdigit()

    @property
    def number(self) -> int:
        """3 for "Day 3" and for "Day C": the key specials are stored under."""
        return int(self.key) if not self.lettered else LETTERS.index(self.key) + 1


def parse(title: str | None) -> RotationDay | None:
    m = _ROTATION_RE.match(title or "")
    if not m:
        return None
    return RotationDay(key=(m.group("after") or m.group("before")).upper(), extra=m.group("extra"))


def is_rotation_title(title: str | None) -> bool:
    return parse(title) is not None


def key_for(number: int, lettered: bool) -> str:
    return LETTERS[number - 1] if lettered and 1 <= number <= len(LETTERS) else str(number)


def canonical_title(title: str) -> str:
    """"DAY C", "C Day" and "C  Day" as "Day C"; anything else as it came.
    Numbered titles are left alone so Eastern's class order keeps its spacing."""
    rd = parse(title)
    if not rd or not rd.lettered:
        return title
    return f"Day {rd.key}" + (f" {rd.extra}" if rd.extra else "")
