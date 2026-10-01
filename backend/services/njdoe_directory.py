"""NJ DOE "New Jersey School Directory - Public Schools" CSV (downloaded by hand;
the directory site sits behind an Incapsula bot wall, so it can't be fetched).

One row per school. It is NOT a staff directory: only the principal (with an
email), the anti-bullying specialist and the homeless liaison (names only).
Use it to fill the who-to-contact gap for schools whose own site has no
parseable roster. The state's emails are entered by hand and go stale (real
rows pair a principal with the previous principal's address), so an email is
kept only when it plausibly belongs to the named person."""

import csv
import io
import re

from services.schoolcafe import _either_contains, _norm

_DISTRICT_NOISE = {"district", "public", "schools", "school", "township", "twp", "regional", "board", "of", "education"}

_SCHOOL_NOISE = {"elementary", "middle", "high", "jr", "sr", "junior", "senior", "preschool", "center", "early", "childhood", "learning", "academy"}


def _clean(v: str | None) -> str:
    v = (v or "").strip()
    m = re.fullmatch(r'=?"?(.*?)"?', v)
    return (m.group(1) if m else v).strip()


def _district_tokens(name: str) -> set[str]:
    return set(_norm(name).split()) - _DISTRICT_NOISE


def email_matches_person(email: str | None, last_name: str) -> bool:
    if not email or "@" not in email:
        return False
    last = re.sub(r"[^a-z]", "", last_name.lower())
    return bool(last) and last in email.split("@")[0].lower()


_HONORIFICS = {"dr", "mr", "mrs", "ms", "miss", "mx"}


def same_person(a: str, b: str) -> bool:
    """Same last name and first initial, honorifics ignored ("Dr. Anthony
    Dent" / "Anthony Dent"). Deliberately loose on first names (Tony/Anthony
    would miss, which only costs an email) but strict on the surname."""
    def parts(name: str) -> list[str]:
        return [w for w in re.findall(r"[a-z]+", name.lower()) if w not in _HONORIFICS]

    pa, pb = parts(a), parts(b)
    return bool(pa and pb and len(pa) > 1 and len(pb) > 1 and pa[-1] == pb[-1] and pa[0][0] == pb[0][0])


def read_rows(path: str) -> list[dict]:
    raw = open(path, "rb").read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:  # the state's Excel export is cp1252
        text = raw.decode("cp1252")
    text = text[text.index("County Code,") :]
    rows = csv.DictReader(io.StringIO(text, newline=""))
    return [{k: _clean(v) for k, v in r.items() if k} for r in rows]


def _person(row: dict, prefix: str, title: str, email: str | None = None) -> dict | None:
    # the state's header really is spelled "HIB First Nname"
    first = row.get(f"{prefix} First Name") or row.get(f"{prefix} First Nname", "")
    last = row.get(f"{prefix} Last Name", "")
    if not (first and last):
        return None
    return {
        "full_name": f"{first} {last}",
        "title": title,
        "email": email if email_matches_person(email, last) else None,
    }


def contacts(row: dict) -> dict[str, dict]:
    """{constituent_id: {full_name, title, email}} for one CSV school row."""
    out: dict[str, dict] = {}
    principal = _person(row, "Princ.", row.get("Princ. Title 2") or "School Principal", row.get("Princ. Email"))
    if principal:
        out["njdoe:principal"] = principal
    hib = _person(row, "HIB", row.get("HIB Title2") or "Anti-Bullying Specialist")
    if hib:
        out["njdoe:hib"] = hib
    homeless = _person(row, "Homeless Liaison", row.get("Homeless Liaison Title2") or "School Homeless Liaison")
    if homeless:
        out["njdoe:homeless"] = homeless
    return out


def match_row(rows: list[dict], district_name: str, school_name: str) -> dict | None:
    """Only an unambiguous match counts - a wrong school's principal is worse than none."""
    ours = _district_tokens(district_name)
    in_district = [r for r in rows if _either_contains(ours, _district_tokens(r["District Name"]))]
    exact = [r for r in in_district if _norm(r["School Name"]) == _norm(school_name)]
    if len(exact) == 1:
        return exact[0]
    theirs = set(_norm(school_name).split())
    loose = [r for r in in_district if _either_contains(theirs, set(_norm(r["School Name"]).split()))]
    if len(loose) == 1:
        return loose[0]
    # "Beeler Elementary School" vs the state's "Helen L Beeler": compare what's left
    # once generic level words are gone. Ambiguous (two schools share a name) -> none.
    core = theirs - _SCHOOL_NOISE
    named = [r for r in in_district if _either_contains(core, set(_norm(r["School Name"]).split()) - _SCHOOL_NOISE)]
    return named[0] if len(named) == 1 else None
