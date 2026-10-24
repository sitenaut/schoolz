"""Which of a person's children each Backpack Capture page belongs to.

Lets the extension publish one batch for the whole family (POST
/bucket3/import) instead of asking a parent to pick a child first. Pure
functions over the envelopes and the caller's own students; the router does
the database work.

Evidence, strongest first:

1. **Strong identity**: a Genesis page's `studentid=` (or its "Student ID:"
   block), or a Classroom login whose email local part is numeric (this
   district's convention - see bucket3_extract.classroom_account_student_id).
   It decides on its own: a page whose strong identity matches none of the
   caller's children is never placed, whatever else says otherwise. Same
   guard rail as the per-student import's mismatch check.
2. **The extension's hint** (`student_hint` on the envelope): set by a walk
   that already knew whose Google account it was in, from this rule set or
   from the parent's own pick. Only counts if it names one of the caller's
   children.
3. **The Classroom account's display name**: school Google accounts carry
   the student's real name, so "Maya Smith" matching exactly one child's
   first and last name places it.
4. **Same Google account as a page placed above**, within this batch (by the
   envelope's `account_index`).
5. **Only one child** on the account - except a Classroom page whose login
   names someone else, which may be a parent's own account.

Anything left is reported back, with the Classroom account it came from, so
the extension can ask the parent once whose account it is.

The extension (backpack-capture's src/accounts.js) picks which logins to
walk by rules 2-3 only: a capture key never gets a student ID
(routers/students.py), so rule 1 runs here alone, and a login it blocks
comes back `other_student`, which the extension then stops walking.
"""
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

from services import bucket3_extract as ex


@dataclass(frozen=True)
class Child:
    id: str
    student_id: str
    first_name: str
    last_name: str


@dataclass(frozen=True)
class UnroutedAccount:
    account_index: int | None
    name: str | None
    email: str | None
    captures: int
    # True when the login itself names a student who isn't one of the
    # caller's children - asking the parent "whose is this?" can't help.
    other_student: bool


@dataclass
class Routing:
    by_student: dict[str, list[dict]] = field(default_factory=dict)
    unrouted: list[dict] = field(default_factory=list)
    unrouted_accounts: list[UnroutedAccount] = field(default_factory=list)


def _tokens(text: str) -> set[str]:
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return set(re.findall(r"[a-z]+", folded))


def name_matches(account_name: str, child: Child) -> bool:
    """Every part of the child's first and last name appears in the account's
    display name ("Smith, Maya" and "Maya Smith" both match Maya Smith)."""
    wanted = _tokens(child.first_name) | _tokens(child.last_name)
    return bool(wanted) and wanted <= _tokens(account_name)


def _strong_identity(envelope: dict) -> str | None:
    text = envelope.get("reduced_text") or ""
    if envelope.get("adapter") == "genesis":
        from_url = ex.genesis_student_id_from_url(envelope.get("source_url") or "")
        if from_url:
            return from_url
        identity = ex.extract_genesis_identity(text)
        return identity.student_id if identity else None
    if envelope.get("adapter") == "classroom":
        return ex.classroom_account_student_id(text)
    return None


def _account_index(envelope: dict) -> int | None:
    value = envelope.get("account_index")
    return value if isinstance(value, int) else None


def route(captures: list[dict], children: list[Child]) -> Routing:
    by_district_id = {c.student_id: c for c in children}
    by_id = {c.id: c for c in children}
    placed: dict[int, str] = {}  # index into captures -> child id
    blocked: set[int] = set()  # strong identity that isn't one of these children
    account_owner: dict[int, str] = {}  # Classroom account_index -> child id, learned from identity

    for i, envelope in enumerate(captures):
        strong = _strong_identity(envelope)
        if strong is not None:
            child = by_district_id.get(strong)
            if child is None:
                blocked.add(i)
                continue
            placed[i] = child.id
        else:
            hint = envelope.get("student_hint")
            if isinstance(hint, str) and hint in by_id:
                placed[i] = hint
                continue
            account = ex.extract_classroom_account(envelope.get("reduced_text") or "") if envelope.get("adapter") == "classroom" else None
            if not account:
                continue
            named = [c for c in children if name_matches(account[0], c)]
            if len(named) != 1:
                continue
            placed[i] = named[0].id
        index = _account_index(captures[i])
        if captures[i].get("adapter") == "classroom" and index is not None:
            account_owner.setdefault(index, placed[i])

    only_child = children[0].id if len(children) == 1 else None
    for i, envelope in enumerate(captures):
        if i in placed or i in blocked:
            continue
        is_classroom = envelope.get("adapter") == "classroom"
        index = _account_index(envelope)
        owner = account_owner.get(index) if is_classroom and index is not None else None
        if owner:
            placed[i] = owner
        # A Classroom login whose name isn't the only child's may well be a
        # parent's own (a teacher's classes, say) - ask, rather than file
        # them under the child.
        elif only_child and not (is_classroom and ex.extract_classroom_account(envelope.get("reduced_text") or "")):
            placed[i] = only_child

    result = Routing()
    unplaced_accounts: Counter[tuple[int | None, str | None, str | None, bool]] = Counter()
    for i, envelope in enumerate(captures):
        if i in placed:
            result.by_student.setdefault(placed[i], []).append(envelope)
            continue
        result.unrouted.append(envelope)
        if envelope.get("adapter") == "classroom":
            account = ex.extract_classroom_account(envelope.get("reduced_text") or "")
            key = (
                _account_index(envelope),
                account[0] if account else None,
                account[1] if account else None,
                i in blocked,
            )
            unplaced_accounts[key] += 1
    result.unrouted_accounts = [
        UnroutedAccount(account_index=index, name=name, email=email, captures=n, other_student=other)
        for (index, name, email, other), n in unplaced_accounts.items()
    ]
    return result
