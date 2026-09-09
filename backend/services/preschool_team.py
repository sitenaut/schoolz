"""Parses the district's "Our Preschool Team" page - central preschool
administration staff (Community Parent Involvement Specialists, social
workers, instructional coaches, intervention/referral specialists, nurses)
who serve every preschool location district-wide, not one specific site.
Confirmed real: unlike a school's own Finalsite staff directory
(`.fsConstituentItem`), this page is a flat sequence of `<p>` blocks -
name (bold), title, phone, then a "Email {name}" mailto link - simple
enough to parse deterministically rather than reach for an LLM.
"""

from bs4 import BeautifulSoup


def parse_preschool_team(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    main = soup.find(id="fsPageContent") or soup

    results = []
    for p in main.find_all("p"):
        name_tag = p.find("strong")
        if not name_tag:
            continue
        name = name_tag.get_text(strip=True)

        email_anchor = p.find("a", href=lambda h: bool(h) and h.startswith("mailto:"))
        email = email_anchor["href"].replace("mailto:", "").strip() if email_anchor else None
        if not email:
            continue  # no stable id to dedup on without one

        lines = [line.strip() for line in p.get_text("\n", strip=True).split("\n") if line.strip()]
        # Layout is always: [name, title, phone, "Email {name}"] - title is
        # whatever sits between the name and the phone/email lines.
        middle = [line for line in lines if line != name and not line.lower().startswith("email")]
        title = middle[0] if middle else None
        phone = middle[1] if len(middle) > 1 else None

        results.append({"full_name": name, "title": title, "phone": phone, "email": email})
    return results
