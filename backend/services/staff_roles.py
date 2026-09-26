"""Deterministic role classification for staff directory titles.

The parent-facing "who to contact" grid needs a handful of roles (nurse,
counselor, main office, principal, SACC) resolved from free-text
directory titles. Real Cherry Hill titles are consistent enough for a
keyword map ("Guidance Counselor", "School counselor", "Nurse",
"Preschool Nurse", "Secretary", "SACC Coordinator", "Principal",
"Assistant Principal") - no model call needed, and the result is stable
across scans. Order matters: more specific patterns first so "Assistant
Principal" doesn't classify as "principal".
"""

import re

# (role, compiled pattern) - first match wins.
_ROLE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("assistant_principal", re.compile(r"\b(assistant|vice)\s+principal\b", re.I)),
    ("principal", re.compile(r"\bprincipal\b", re.I)),
    ("nurse", re.compile(r"\bnurse\b", re.I)),
    ("counselor", re.compile(r"\b(counselor|counsellor|guidance)\b", re.I)),
    ("sacc", re.compile(r"\bsacc\b", re.I)),
    ("secretary", re.compile(r"\b(secretary|office manager|administrative assistant|main office|office staff)\b", re.I)),
    ("social_worker", re.compile(r"\bsocial worker\b", re.I)),
    ("psychologist", re.compile(r"\bpsychologist\b", re.I)),
]

# Display order + labels for the contact grid.
CONTACT_ROLES: list[tuple[str, str]] = [
    ("secretary", "Main office"),
    ("nurse", "Nurse"),
    ("counselor", "Counselor"),
    ("principal", "Principal"),
    ("assistant_principal", "Assistant principal"),
    ("sacc", "SACC"),
    ("social_worker", "Social worker"),
]


def classify_role(title: str | None) -> str | None:
    if not title:
        return None
    for role, pattern in _ROLE_PATTERNS:
        if pattern.search(title):
            return role
    return None


# ---------------------------------------------------------------------------
# Coarse categories for the district-wide directory (/directory).
#
# `role` above is deliberately narrow - it answers "who do I contact about
# my kid" and classifies under 10% of real rows (187 of 1880 across the 27
# tracked schools). That's correct for the contact grid and useless as a
# directory filter, where a parent scanning 1880 people needs "teachers"
# and "front office" as buckets. Hence a second, coarser map over the same
# free text.
#
# Deliberately derived at query time rather than stored in a column like
# `role`: the keyword list is expected to keep getting tuned against real
# titles, and a stored column would need a migration plus a prod backfill
# (or a full re-scan of every roster) on every tweak. The whole table is
# ~1900 rows, so one scoped query per request and classification in Python
# is cheap. Revisit if this ever grows past ~10k rows.
#
# Order matters and is not alphabetical - "Athletic Director" is athletics
# before it is office, "Guidance Counselor" is support before "Director of
# Guidance" is office, and "Administrative Assistant" is office before the
# bare-assistant patterns make it an aide.
_CATEGORY_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("athletics", re.compile(r"\b(athletic|athletics|head coach|assistant coach|trainer)\b", re.I)),
    ("health", re.compile(r"\b(nurse|health office)\b", re.I)),
    (
        "support",
        re.compile(
            r"\b(counselor|counsellor|guidance|social worker|psychologist|child study|therapist|therapy"
            # Every other "speech" title in the district is therapy or
            # pathology (support); the lone exception is a teacher whose
            # title ends "Speech and Debate Coach".
            r"|speech(?!\s+and\s+debate)|occupational|behaviou?r|intervention|interventionist|specialist"
            r"|sacc|student assistance|student support|case manager"
            # An academic coach is support staff; a sports coach is not, and
            # the real titles mix them - "Literacy Coach" and "Math Teacher
            # Coach" sit alongside "English Teacher, Public Speaking
            # Teacher, Speech and Debate Coach", which is a teacher's title.
            # Hence the qualifiers rather than a bare \bcoach\b.
            r"|(?:literacy|math|instructional|academic|reading|teacher)\s+coach)\b",
            re.I,
        ),
    ),
    (
        "office",
        re.compile(
            r"\b(principal|secretary|office manager|administrative assistant|main office|administration"
            r"|administrator|superintendent|director|supervisor|coordinator|registrar|bookkeeper|clerk)\b",
            re.I,
        ),
    ),
    (
        "aide",
        re.compile(r"\b(educational assistant|instructional assistant|paraprofessional|para|aide|monitor)\b", re.I),
    ),
    ("teacher", re.compile(r"\b(teacher|instructor|librarian|media specialist|faculty)\b", re.I)),
    (
        "facilities",
        re.compile(
            r"\b(custodian|custodial|maintenance|security|campus police|food service|cafeteria|kitchen"
            r"|bus|transportation|technology|technician|it support)\b",
            re.I,
        ),
    ),
]

# Display order + labels for the directory's filter chips. "other" is the
# catch-all *and* the bucket for the 596 real rows whose source listing has
# no Titles block at all - a person with no stated title is genuinely
# uncategorizable here, not a bug, so they stay findable by name rather
# than being hidden behind a filter that never matches.
DIRECTORY_CATEGORIES: list[tuple[str, str]] = [
    ("teacher", "Teachers"),
    ("office", "Front office & admin"),
    ("support", "Counseling & support"),
    ("health", "Health"),
    ("aide", "Aides & assistants"),
    ("athletics", "Athletics"),
    ("facilities", "Facilities & operations"),
    ("other", "Other & unlisted"),
]


def classify_directory_category(title: str | None, department: str | None = None) -> str:
    """Coarse bucket for the district-wide directory. Always returns a
    category (never None) so the filter chip counts add up to the result
    total. Falls back to the department when the title is missing or
    unhelpful - real rows carry "Preschool Administration" or "Guidance"
    as a department with no title at all."""
    for text in (title, department):
        if not text:
            continue
        for category, pattern in _CATEGORY_PATTERNS:
            if pattern.search(text):
                return category
    return "other"
