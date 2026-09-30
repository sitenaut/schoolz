"""Staff lists that a school typed straight into a page body instead of using
a directory widget - confirmed on two Evesham Smart Sites schools:

- Beeler: centered paragraphs, role first ("Principal - Ryan Mahlman",
  "Music: Meredith Lowden"), then bare names under grade headings.
- Rice: a pasted spreadsheet, two data columns, name first ("Beverly Green -
  Principal"), bare names under headings ("Kindergarten", "PIRT").

Deterministic, no model. Each line is one of: a heading, "role <sep> name" /
"name <sep> role" (which order is decided per page from the lines that are
unambiguous), or a bare name that takes the current heading as its title.
Nothing here has an email. A line that can't be read confidently is skipped -
a missing teacher beats a misfiled one."""

import re

from bs4 import BeautifulSoup

_NAME_TOKEN = re.compile(r"^[A-Z][A-Za-z'’.\-]*$")
_HONORIFIC = re.compile(r"^(?:mr|mrs|ms|miss|dr)\.?\s+", re.I)
_SEP = re.compile(r"\s+[-–—]\s*|\s*[-–—]\s+|\s*:\s+|(?<=[a-z.])-(?=[A-Z])")
_HEADING = re.compile(
    r"\b(grade|kindergarten|arts|specials|specialists|resource|office|reading|math|speech|support|"
    r"preschool|directory|our school|close|contact)\b",
    re.I,
)
_GRADE = re.compile(r"\b(grade|kindergarten)\b", re.I)
_SKIP_TOKENS = {"the", "of", "and", "for", "a"}
# Words that make a capitalised phrase a job or place, never a person ("School Nurse", "World Language").
_NOT_A_NAME = {
    "school", "nurse", "counselor", "principal", "teacher", "teachers", "assistant", "assistants", "specialist",
    "specialists", "office", "language", "media", "support", "custodian", "secretary", "guidance", "psychologist",
    "worker", "social", "library", "music", "technology", "education", "spanish", "art", "arts", "reading",
}
# "Chipana & Robayo": surnames only - can't be filed under a person.
_SURNAME_PAIR = re.compile(r"^[A-Z][A-Za-z'\-]+\s*(?:&|/|and)\s*[A-Z][A-Za-z'\-]+$")


def _clean(s: str) -> str:
    s = s.replace("\xa0", " ").replace("’", "'")
    s = re.sub(r"\([^)]*\)", "", s)
    return re.sub(r"\s+", " ", s).strip(" \t-–—:")


def _name_like(s: str) -> bool:
    s = _HONORIFIC.sub("", s.strip())
    toks = s.split()
    return (
        2 <= len(toks) <= 4
        and all(_NAME_TOKEN.match(t) and t.lower() not in _SKIP_TOKENS for t in toks)
        and not any(t.lower().strip(".") in _NOT_A_NAME for t in toks)
    )


def _lines(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    root = soup.select_one("#page-content-wrapper") or soup
    for t in root(["script", "style"]):
        t.decompose()
    for br in root.find_all("br"):
        br.replace_with("\n")
    out: list[str] = []
    for table in root.find_all("table"):
        rows = [[c.get_text(" ") for c in tr.find_all(["td", "th"])] for tr in table.find_all("tr")]
        for col in range(max((len(r) for r in rows), default=0)):
            out += [ln for r in rows if col < len(r) for ln in r[col].splitlines()]
            out.append("")
        table.decompose()
    for el in root.find_all(["p", "li", "h1", "h2", "h3", "h4", "h5", "h6"]):
        if not el.find(["p", "li"]):
            out += el.get_text(" ").splitlines()
    return [c for c in (_clean(x) for x in out) if c]


def _split_people(part: str) -> list[str]:
    names = []
    for piece in re.split(r"\s*(?:&|/|\band\b)\s*", part):
        piece = _HONORIFIC.sub("", _clean(piece))
        if _name_like(piece):
            names.append(piece)
    return names


def parse(html: str) -> list[dict]:
    """[{full_name, title}] in page order; deduped by name."""
    lines = _lines(html)

    def sides(line: str):
        m = _SEP.split(line, maxsplit=1)
        return (m[0].strip(), m[1].strip()) if len(m) == 2 and m[0].strip() and m[1].strip() else None

    role_first = name_first = 0
    for line in lines:
        s = sides(line)
        if not s:
            continue
        a, b = s
        a_n, b_n = _name_like(a) or bool(_split_people(a)), _name_like(b) or bool(_split_people(b))
        if a_n and not b_n:
            name_first += 1
        elif b_n and not a_n:
            role_first += 1
    order_role_first = role_first > name_first

    out: dict[str, dict] = {}
    group: str | None = None
    group_fresh = False

    def add(name: str, title: str | None):
        out.setdefault(name.lower(), {"full_name": name, "title": title})

    for line in lines:
        s = sides(line)
        if s:
            a, b = s
            if _SURNAME_PAIR.match(a) or _SURNAME_PAIR.match(b):
                continue
            a_n, b_n = bool(_split_people(a)), bool(_split_people(b))
            if a_n and b_n:
                # both read as names ("Erica Cooke - Rdg Recovery/Int Spec."): trust the page's order
                name_part, title = (b, a) if order_role_first else (a, b)
            elif a_n:
                name_part, title = a, b
            elif b_n:
                name_part, title = b, a
            else:
                continue
            for name in _split_people(name_part):
                add(name, title)
            # an explicit entry ends the heading unless it just restates it ("Speech" / "Lisa Bisti - Speech")
            group_fresh = group_fresh and (group or "").lower() == title.lower()
            continue
        if _HEADING.search(line) or not _name_like(line):
            group, group_fresh = line, True
            continue
        # After a "name - role" line the heading may belong to another column of a pasted
        # table, so a bare name there gets no title rather than a wrong one.
        title = (f"{group} Teacher" if _GRADE.search(group) else group) if group and group_fresh else None
        add(_HONORIFIC.sub("", line), title)
    return list(out.values())
