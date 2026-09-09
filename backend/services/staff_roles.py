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
    ("secretary", re.compile(r"\b(secretary|office manager|administrative assistant|main office)\b", re.I)),
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
