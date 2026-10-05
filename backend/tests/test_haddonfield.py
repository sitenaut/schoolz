from pathlib import Path

import pytest

from services.staff_roster import _parse_tablepress_directory

FIXTURES = Path(__file__).parent / "fixtures"


def test_tablepress_directory_reads_name_title_and_obfuscated_email():
    items = _parse_tablepress_directory((FIXTURES / "haddonfield_staff_directory_high.html").read_text())
    assert len(items) > 60
    ad = next(i for i in items if i["title"] == "Athletic Director")
    assert ad["full_name"].endswith("Banos")
    assert ad["email"].endswith("@haddonfield.k12.nj.us")
    # letter headers ("B") are section dividers, never people
    assert not any(i["full_name"] in {"A", "B", "C"} for i in items)


def test_tablepress_directory_department_header_applies_to_untitled_people():
    items = _parse_tablepress_directory((FIXTURES / "haddonfield_staff_directory_central.html").read_text())
    assert any(i["department"] == "Kindergarten" and not i["title"] for i in items)
    assert any(i["title"] == "Principal" for i in items)


def test_smore_short_link_counts_as_an_issue_but_author_profile_does_not():
    from services.smore_parser import _SMORE_ISSUE_HREF_RE as r

    assert r.match("https://www.smore.com/136jk")
    assert r.match("https://secure.smore.com/n/e7tky")
    assert not r.match("https://www.smore.com/u/someauthor")
    assert not r.match("https://www.smore.com/")


@pytest.mark.anyio
async def test_school_newsletters_list_newest_content_first():
    """The school page shows the first row as the newsletter, so a recurring
    row pinned to an old issue (rescanned weekly, never any new block) must
    sort behind a newer issue added as its own row."""
    import uuid
    from datetime import datetime, timedelta, timezone

    import database
    from models import School, SmoreBlock, SmoreNewsletter
    from routers.schools import list_school_newsletters

    now = datetime.now(timezone.utc)
    async with database.SessionLocal() as db:
        tag = uuid.uuid4().hex[:6]
        school = School(name=f"Newsletter Order {tag}", slug=f"newsletter-order-{tag}")
        db.add(school)
        await db.flush()
        old = SmoreNewsletter(school_id=school.id, url="https://app.smore.com/n/old", label="old", created_at=now - timedelta(days=30), last_scanned_at=now)
        new = SmoreNewsletter(school_id=school.id, url="https://app.smore.com/n/new", label="new", created_at=now - timedelta(days=3))
        db.add_all([old, new])
        await db.flush()
        db.add(SmoreBlock(newsletter_id=old.id, position=0, block_type="text", content_hash="a", first_seen_at=now - timedelta(days=30)))
        db.add(SmoreBlock(newsletter_id=new.id, position=0, block_type="text", content_hash="b", first_seen_at=now - timedelta(days=3)))
        await db.flush()
        out = await list_school_newsletters(school=school, db=db)
    assert [n.label for n in out] == ["new", "old"]
