"""Email scanners keep only allowed newsletter links (services/email_links.py):
which links count, that nothing else of a message is stored, and Mailchimp
campaigns becoming newsletters scanned into school content."""
import base64
import os

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update

import database
from main import app
from models import (
    EmailScanner,
    EmailScannerMatch,
    GmailToken,
    ScheduledJob,
    School,
    SchoolEmailMessage,
    SmoreNewsletter,
    User,
)
from services import email_links, email_scanner, mailchimp_parser

pytestmark = pytest.mark.anyio

PRIVATE = "Dr. Patel's office: your son's results are ready"


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def _message(plain: str = "", html: str = "", msg_id: str | None = None) -> dict:
    parts = []
    if plain:
        parts.append({"mimeType": "text/plain", "body": {"data": _b64(plain)}})
    if html:
        parts.append({"mimeType": "text/html", "body": {"data": _b64(html)}})
    # An attachment whose text holds a newsletter link: never read.
    parts.append({"mimeType": "text/plain", "filename": "notes.txt", "body": {"data": _b64("https://mailchi.mp/acct/from-attachment")}})
    return {
        "id": msg_id or uuid.uuid4().hex,
        "internalDate": "1760870400000",
        "snippet": PRIVATE,
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": [{"name": "From", "value": "Dr Patel <dr@example.com>"}, {"name": "Subject", "value": PRIVATE}],
            "parts": parts,
        },
    }


# ---- which links count ------------------------------------------------------------------


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://app.smore.com/n/ak7n1-chesterbrook?ref=email", ("smore", "https://app.smore.com/n/ak7n1-chesterbrook")),
        ("https://secure.smore.com/n/abc12", ("smore", "https://secure.smore.com/n/abc12")),
        ("https://mailchi.mp/haddonpta/october-news?e=5f3a9c0d21", ("mailchimp", "https://mailchi.mp/haddonpta/october-news")),
        (
            "https://us7.campaign-archive.com/?e=5f3a9c0d21&u=a01075c7524a6e51f4207e8b5&id=3a64dffcca",
            ("mailchimp", "https://us7.campaign-archive.com/?u=a01075c7524a6e51f4207e8b5&id=3a64dffcca"),
        ),
        # Outlook's safelinks wrapper around a real link.
        (
            "https://nam12.safelinks.protection.outlook.com/?url=https%3A%2F%2Fmailchi.mp%2Fpta%2Fnews%3Fe%3Dabc&data=x",
            ("mailchimp", "https://mailchi.mp/pta/news"),
        ),
        # Smore's "View in browser" names the issue in its path (a real BHES email); never followed.
        ("https://out.smore.com/render/qf2pn/byOgAZ?__$u__", ("smore", "https://app.smore.com/n/qf2pn")),
        # Never: tracking redirects, short links, profiles, images, archive indexes, look-alikes.
        ("https://pta.us7.list-manage.com/track/click?u=a01075c7524a&id=3a64dffcca&e=5f3a9c0d21", None),
        ("https://out.smore.com/e/abc123/xyz", None),
        ("https://out.smore.com/render/", None),
        ("http://eepurl.com/hXyZ1", None),
        ("https://www.smore.com/u/principal-jones", None),
        ("https://cdn.smore.com/u/ab/12345.jpg", None),
        ("https://mcusercontent.com/a01075c7524a6e51f4207e8b5/images/1.png", None),
        ("https://us7.campaign-archive.com/home/?u=a01075c7524a6e51f4207e8b5&id=3a64dffcca", None),
        ("https://smore.com.evil.example/n/abc12", None),
        ("https://mailchi.mp.evil.example/a/b", None),
        ("javascript:alert(1)", None),
    ],
)
def test_only_public_newsletter_pages_count(url, expected):
    assert email_links.canonical(url) == expected


def test_extract_reads_text_and_html_never_attachments_and_honours_the_scanners_kinds():
    msg = _message(
        plain="This week: https://app.smore.com/n/week7?ref=email\nAlso " + PRIVATE,
        html='<p>Read it <a href="https://mailchi.mp/pta/oct?e=abc">here</a> '
        '<img src="https://mcusercontent.com/x/images/a.png"> '
        '<a href="https://pta.us7.list-manage.com/track/click?u=1&amp;id=2&amp;e=3">tracked</a></p>',
    )
    both = email_links.extract(msg, ["smore", "mailchimp"])
    assert both == [{"kind": "smore", "url": "https://app.smore.com/n/week7"}, {"kind": "mailchimp", "url": "https://mailchi.mp/pta/oct"}]
    assert email_links.extract(msg, ["mailchimp"]) == [{"kind": "mailchimp", "url": "https://mailchi.mp/pta/oct"}]
    assert email_links.extract(msg, ["everything"]) == []


# ---- what a scan keeps --------------------------------------------------------------------


async def _owner_and_school() -> tuple[str, str]:
    tag = uuid.uuid4().hex[:8]
    async with database.SessionLocal() as db:
        user = User(email=f"scan_{tag}@example.com", username=f"scan_{tag}", password_hash="x", is_admin=True)
        school = School(name=f"Scanner Test School {tag}", slug=f"scanner-test-{tag}", school_type="elementary")
        db.add_all([user, school])
        await db.commit()
        return user.id, school.id


async def _scanner(owner_id: str, school_id: str | None, kinds: list[str]) -> EmailScanner:
    async with database.SessionLocal() as db:
        db.add(GmailToken(user_id=owner_id, google_email="inbox@example.com", access_token="a", refresh_token="r",
                          token_expiry=datetime.now(UTC)))
        scanner = EmailScanner(owner_user_id=owner_id, google_email="inbox@example.com", name="PTA", purpose="school_email",
                               school_id=school_id, link_kinds=kinds)
        db.add(scanner)
        await db.commit()
        return scanner


@pytest.fixture
def inbox(monkeypatch):
    """The scan with Gmail stubbed: `messages` is what the search returns."""
    box = SimpleNamespace(messages=[])

    async def _service(db, token):
        return object()

    monkeypatch.setattr(email_scanner, "get_gmail_service", _service)
    monkeypatch.setattr(
        email_scanner, "fetch_all_messages_sync", lambda service, query, skip: (len(box.messages), [m for m in box.messages if m["id"] not in skip])
    )
    return box


async def test_a_scan_keeps_the_links_and_nothing_else_of_the_message(inbox):
    owner_id, school_id = await _owner_and_school()
    scanner = await _scanner(owner_id, school_id, ["smore", "mailchimp"])
    code = uuid.uuid4().hex[:8]
    with_links = _message(plain=f"{PRIVATE} https://app.smore.com/n/{code}?ref=email", html=f'<a href="https://mailchi.mp/pta/{code}?e=1">x</a>')
    without = _message(plain=PRIVATE + " https://example.com/results")
    inbox.messages = [with_links, without]

    async with database.SessionLocal() as db:
        scanner = await db.get(EmailScanner, scanner.id)
        summary = await email_scanner.run_scanner(db, scanner)
    assert "2 new - 1 with newsletter links, 1 without" in summary

    async with database.SessionLocal() as db:
        matches = (await db.execute(select(EmailScannerMatch).where(EmailScannerMatch.scanner_id == scanner.id))).scalars().all()
        assert sorted(m.processor_status for m in matches) == ["ok", "skipped"]
        for m in matches:
            assert m.sender is None and m.subject is None and m.snippet is None and m.received_at is not None
        kept = (await db.execute(select(SchoolEmailMessage).where(SchoolEmailMessage.scanner_id == scanner.id))).scalars().all()
        assert len(kept) == 1  # nothing at all for the message without links
        assert kept[0].body_text is None and kept[0].subject is None and kept[0].sender is None
        assert PRIVATE not in str(kept[0].newsletter_links)

        smore = (await db.execute(select(SmoreNewsletter).where(SmoreNewsletter.url == f"https://app.smore.com/n/{code}"))).scalar_one()
        mc = (await db.execute(select(SmoreNewsletter).where(SmoreNewsletter.url == f"https://mailchi.mp/pta/{code}"))).scalar_one()
        assert (smore.source_type, smore.school_id, mc.source_type, mc.school_id) == ("smore", school_id, "mailchimp", school_id)
        assert (await db.get(ScheduledJob, smore.scheduled_job_id)).kind == "smore.scan"
        assert (await db.get(ScheduledJob, mc.scheduled_job_id)).kind == "mailchimp.scan"

    # The same issue again - on another host, as an older ?ref= row, as a row
    # with the issue's name after its code - adds nothing.
    async with database.SessionLocal() as db:
        db.add(SmoreNewsletter(url=f"https://www.smore.com/n/{code}2?ref=email"))
        db.add(SmoreNewsletter(url=f"https://app.smore.com/n/{code}3-bret-harte-elementary-school"))
        await db.commit()
    inbox.messages = [
        _message(plain=f"https://secure.smore.com/n/{code} https://app.smore.com/n/{code}2"),
        _message(html=f'<a href="https://out.smore.com/render/{code}3/byOgAZ?__$u__">View in browser</a>'),
    ]
    async with database.SessionLocal() as db:
        await email_scanner.run_scanner(db, await db.get(EmailScanner, scanner.id))
        rows = (await db.execute(select(SmoreNewsletter).where(SmoreNewsletter.url.like(f"%/n/{code}%")))).scalars().all()
        assert len(rows) == 3


async def test_a_processor_error_never_quotes_the_message(inbox, monkeypatch):
    owner_id, _ = await _owner_and_school()
    scanner = await _scanner(owner_id, None, ["smore"])
    inbox.messages = [_message(plain="https://app.smore.com/n/boom1")]

    def _boom(message, kinds):
        raise ValueError(PRIVATE)

    monkeypatch.setattr(email_links, "extract", _boom)
    async with database.SessionLocal() as db:
        await email_scanner.run_scanner(db, await db.get(EmailScanner, scanner.id))
        m = (await db.execute(select(EmailScannerMatch).where(EmailScannerMatch.scanner_id == scanner.id))).scalar_one()
        assert m.processor_status == "error" and m.processor_error == "ValueError"


async def test_a_message_that_fails_on_a_db_error_does_not_stop_the_scan_there(inbox):
    owner_id, school_id = await _owner_and_school()
    scanner = await _scanner(owner_id, school_id, ["smore"])
    taken, fine = uuid.uuid4().hex[:8], uuid.uuid4().hex[:8]
    async with database.SessionLocal() as db:
        # A job already holding the name the first link's scan would get.
        db.add(ScheduledJob(owner_user_id=owner_id, kind="smore.scan", name=f"Smore scan: https://app.smore.com/n/{taken}",
                            cron_expr="0 8 * * 1", params={}))
        await db.commit()
    first, second = _message(plain=f"https://app.smore.com/n/{taken}"), _message(plain=f"https://app.smore.com/n/{fine}")
    inbox.messages = [first, second]

    async with database.SessionLocal() as db:
        summary = await email_scanner.run_scanner(db, await db.get(EmailScanner, scanner.id))
    assert "1 with newsletter links, 0 without, 1 failed" in summary
    async with database.SessionLocal() as db:
        matches = {m.message_id: m for m in (await db.execute(select(EmailScannerMatch).where(EmailScannerMatch.scanner_id == scanner.id))).scalars()}
        assert (matches[first["id"]].processor_status, matches[first["id"]].processor_error) == ("error", "IntegrityError")
        assert matches[second["id"]].processor_status == "ok"
        urls = set((await db.execute(select(SmoreNewsletter.url).where(SmoreNewsletter.url.like("https://app.smore.com/n/%")))).scalars())
        assert f"https://app.smore.com/n/{fine}" in urls and f"https://app.smore.com/n/{taken}" not in urls


# ---- what a run reports ---------------------------------------------------------------------


def test_click_tracking_links_are_counted_but_never_kept():
    msg = _message(
        plain="https://out.smore.com/e/abc123/xyz http://eepurl.com/hXyZ1",
        html='<a href="https://pta.us7.list-manage.com/track/click?u=1&amp;id=2&amp;e=3">a</a>'
        '<a href="https://pta.us7.list-manage.com/track/click?u=1&amp;id=2&amp;e=3">the same one</a>'
        '<a href="https://example.com/page">not a tracker</a>',
    )
    assert email_links.extract(msg, ["smore", "mailchimp"]) == []
    assert email_links.tracking_link_count(msg) == 3


def test_a_smore_email_whose_every_link_is_tracked_still_yields_its_issue():
    # Real case: 101 Cherry Hill emails, 380 out.smore.com links, nothing kept.
    msg = _message(html='<a href="https://out.smore.com/render/qf2pn/byOgAZ?__$u__">View in browser</a>'
                        '<a href="https://out.smore.com/e/qf2pn/aB3dE">Sign up</a>')
    assert email_links.extract(msg, ["smore"]) == [{"kind": "smore", "url": "https://app.smore.com/n/qf2pn"}]
    assert email_links.tracking_link_count(msg) == 1


async def test_a_run_records_what_it_found_by_count_and_nothing_of_the_mail(inbox):
    # A first prod run said only "scanned 100 new message(s), 0 processed ok":
    # no telling a filter that fits the wrong mail from links a scan refuses.
    owner_id, _ = await _owner_and_school()
    scanner = await _scanner(owner_id, None, ["smore"])
    code = uuid.uuid4().hex[:8]
    async with database.SessionLocal() as db:
        db.add(SmoreNewsletter(url=f"https://app.smore.com/n/old{code}"))
        await db.commit()
    inbox.messages = [
        _message(plain=f"https://app.smore.com/n/{code} https://www.smore.com/n/old{code}"),
        _message(plain=f"{PRIVATE} https://out.smore.com/e/abc/xyz"),
        _message(plain=PRIVATE),
    ]
    async with database.SessionLocal() as db:
        summary = await email_scanner.run_scanner(db, await db.get(EmailScanner, scanner.id))
        run = (await db.get(EmailScanner, scanner.id)).last_run
    assert run["query"].startswith("after:") and PRIVATE not in str(run)
    assert {k: v for k, v in run.items() if k not in ("at", "query")} == {
        "matched": 3,
        "new": 3,
        "with_links": 1,
        "without_links": 2,
        "errors": 0,
        "links": 2,
        "new_newsletters": 1,
        "waiting": 1,
        "already_tracked": 1,
        "tracking_links": 1,
    }
    assert summary.endswith(
        "3 email(s) matched, 3 new - 1 with newsletter links, 2 without; 2 link(s): 1 new newsletter(s) "
        "(1 waiting for an admin to assign), 1 already tracked; 1 click-tracking link(s) skipped, never followed"
    )

    # The same mail again: matched, but nothing new to read.
    async with database.SessionLocal() as db:
        summary = await email_scanner.run_scanner(db, await db.get(EmailScanner, scanner.id))
    assert summary.endswith(": 3 email(s) matched, 0 new")

    # A search that matches nothing at all is a warning, not a success.
    inbox.messages = []
    async with database.SessionLocal() as db:
        summary = await email_scanner.run_scanner(db, await db.get(EmailScanner, scanner.id))
        assert (await db.get(EmailScanner, scanner.id)).last_run["matched"] == 0
    assert summary.startswith("WARNING[email_no_matches]: no email matched the search 'after:")


# ---- the API --------------------------------------------------------------------------------


async def _registered_admin(client: AsyncClient) -> tuple[dict[str, str], str]:
    tag = uuid.uuid4().hex[:8]
    res = await client.post("/auth/register", json={"email": f"a_{tag}@example.com", "username": f"a_{tag}", "password": "password123"})
    headers = {"Authorization": f"Bearer {res.json()['access_token']}"}
    me = (await client.get("/auth/me", headers=headers)).json()
    async with database.SessionLocal() as db:
        await db.execute(update(User).where(User.id == me["id"]).values(is_admin=True))
        await db.commit()
    return headers, me["id"]


async def test_a_scanner_moves_to_another_connected_inbox_and_rechecks_what_gave_nothing(monkeypatch):
    from scheduler import runner

    started: list[str] = []

    async def _run_job_now(job_id):
        started.append(job_id)

    monkeypatch.setattr(runner, "run_job_now", _run_job_now)
    _, school_id = await _owner_and_school()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        headers, me = await _registered_admin(client)
        async with database.SessionLocal() as db:
            for address in ("inbox@example.com", "second@example.com"):
                db.add(GmailToken(user_id=me, google_email=address, access_token="a", refresh_token="r", token_expiry=datetime.now(UTC)))
            await db.commit()
        created = await client.post("/email-scanners", json={"google_email": "inbox@example.com", "name": "PTA", "school_id": school_id}, headers=headers)
        assert created.status_code == 201, created.text
        sid, job_id = created.json()["id"], created.json()["scheduled_job"]["id"]

        moved = await client.patch(f"/email-scanners/{sid}", json={"google_email": "second@example.com"}, headers=headers)
        assert moved.status_code == 200, moved.text
        assert (moved.json()["google_email"], moved.json()["school_id"]) == ("second@example.com", school_id)
        # Only an inbox the scanner's owner has connected.
        assert (await client.patch(f"/email-scanners/{sid}", json={"google_email": "elsewhere@example.com"}, headers=headers)).status_code == 400
        assert (await client.patch(f"/email-scanners/{sid}", json={"school_id": "no-such-school"}, headers=headers)).status_code == 422
        # What the edit form sends for "No school": null clears it.
        cleared = await client.patch(f"/email-scanners/{sid}", json={"school_id": None}, headers=headers)
        assert (cleared.json()["school_id"], cleared.json()["google_email"]) == (None, "second@example.com")

        async with database.SessionLocal() as db:
            db.add_all(
                [EmailScannerMatch(scanner_id=sid, message_id=f"m{n}", processor_status=s) for n, s in enumerate(["ok", "skipped", "skipped", "error"])]
            )
            await db.commit()
        listed = next(s for s in (await client.get("/email-scanners", headers=headers)).json() if s["id"] == sid)
        assert listed["totals"] == {"ok": 1, "skipped": 2, "error": 1} and listed["last_run"] is None

        # Re-checking forgets only the mail that gave nothing; links already found stay read.
        assert (await client.post(f"/email-scanners/{sid}/run-now?recheck=true", headers=headers)).status_code == 200
        assert started == [job_id]
        listed = next(s for s in (await client.get("/email-scanners", headers=headers)).json() if s["id"] == sid)
        assert listed["totals"] == {"ok": 1}


async def test_scanner_link_kinds_come_only_from_the_catalog_and_no_message_text_is_served():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        tag = uuid.uuid4().hex[:8]
        res = await client.post("/auth/register", json={"email": f"a_{tag}@example.com", "username": f"a_{tag}", "password": "password123"})
        headers = {"Authorization": f"Bearer {res.json()['access_token']}"}
        me = (await client.get("/auth/me", headers=headers)).json()
        async with database.SessionLocal() as db:
            await db.execute(update(User).where(User.id == me["id"]).values(is_admin=True))
            await db.commit()
        await _scanner(me["id"], None, ["smore"])

        kinds = (await client.get("/email-scanners/link-kinds", headers=headers)).json()
        assert [k["key"] for k in kinds] == ["smore", "mailchimp"]
        scanner = (await client.get("/email-scanners", headers=headers)).json()[0]
        assert scanner["link_kinds"] == ["smore"]
        bad = await client.patch(f"/email-scanners/{scanner['id']}", json={"link_kinds": ["smore", "everything"]}, headers=headers)
        assert bad.status_code == 422
        assert (await client.patch(f"/email-scanners/{scanner['id']}", json={"link_kinds": []}, headers=headers)).status_code == 422
        ok = await client.patch(f"/email-scanners/{scanner['id']}", json={"link_kinds": ["mailchimp", "smore"]}, headers=headers)
        assert ok.json()["link_kinds"] == ["smore", "mailchimp"]

        async with database.SessionLocal() as db:
            # A row from before the change still holds text; it is never served.
            db.add(SchoolEmailMessage(owner_user_id=me["id"], scanner_id=scanner["id"], gmail_message_id="old", sender="dr@example.com",
                                      subject=PRIVATE, body_text=PRIVATE, newsletter_links=[]))
            await db.commit()
        served = (await client.get("/school-emails", headers=headers)).json()
        assert served and PRIVATE not in str(served) and "dr@example.com" not in str(served)


# ---- Mailchimp campaigns ----------------------------------------------------------------


CAMPAIGN = """
<html><body>
<div id="awesomewrap"><div id="awesomebar">Subscribe Past Issues Translate</div></div>
<table id="bodyTable"><tr><td>
  <div class="mceText"><h1>Haddon PTA News</h1></div>
  <div class="mceText"><p>Picture Day is <b>Thursday, October 23</b>. <a href="https://haddonpta.org/picture-day">Order here</a></p></div>
  <a href="https://haddonpta.org/flyer"><img class="mceImage" src="https://mcusercontent.com/abc/images/flyer.png" alt="Fall Festival flyer"></a>
  <img src="https://cdn-images.mailchimp.com/icons/social-block-v3/facebook.png" alt="Facebook icon">
  <img class="mceImage" src="data:image/gif;base64,R0lGOD">
  <a class="mceButtonLink" href="https://haddonpta.org/volunteer">Volunteer sign-up</a>
  <div class="mceText"><p>Picture Day is <b>Thursday, October 23</b>. <a href="https://haddonpta.org/picture-day">Order here</a></p></div>
  <div class="mcnTextContent">Classic template text: book fair Nov 3-7.</div>
  <div class="mceText"><p>View email in browser update your preferences or unsubscribe</p></div>
</td></tr></table>
<script>var x = "Subscribe";</script>
</body></html>
"""


def test_a_campaign_page_becomes_text_image_and_button_blocks():
    blocks = mailchimp_parser.parse(CAMPAIGN)
    assert [(b["block_type"], b["text_content"]) for b in blocks] == [
        ("text", "Haddon PTA News"),
        ("text", "Picture Day is Thursday, October 23 . Order here"),
        ("image", "Fall Festival flyer"),
        ("text", "Volunteer sign-up"),
        ("text", "Classic template text: book fair Nov 3-7."),
    ]
    assert blocks[1]["link_url"] == "https://haddonpta.org/picture-day"
    assert blocks[2]["image_url"] == "https://mcusercontent.com/abc/images/flyer.png" and blocks[2]["link_url"] == "https://haddonpta.org/flyer"
    assert [b["position"] for b in blocks] == [0, 1, 2, 3, 4]


async def test_the_mailchimp_scan_stores_blocks_once_and_flags_a_taken_down_campaign(monkeypatch):
    from scheduler.jobs import mailchimp_scan

    extracted: list[int] = []

    async def _extract(db, newsletter, blocks, job_kind=None):
        extracted.append(len(blocks))
        return "extracted"

    pages = {"html": CAMPAIGN}

    async def _fetch(url):
        return mailchimp_parser.parse(pages["html"]) if pages["html"] else []

    monkeypatch.setattr(mailchimp_scan, "extract_from_newsletter", _extract)
    monkeypatch.setattr(mailchimp_scan, "fetch_and_parse", _fetch)
    async with database.SessionLocal() as db:
        newsletter = SmoreNewsletter(url=f"https://mailchi.mp/pta/{uuid.uuid4().hex[:8]}", source_type="mailchimp")
        db.add(newsletter)
        await db.commit()
        first = await mailchimp_scan.run(db, {"newsletter_id": newsletter.id})
        again = await mailchimp_scan.run(db, {"newsletter_id": newsletter.id})
        pages["html"] = None
        gone = await mailchimp_scan.run(db, {"newsletter_id": newsletter.id})
    assert first == "fetched 5 block(s), 5 new · extraction: extracted" and extracted == [5]
    assert again == "fetched 5 block(s), 0 new"
    assert gone.startswith("WARNING[mailchimp_no_blocks]")


async def test_a_campaign_mailchimp_took_down_reads_as_empty(monkeypatch):
    import httpx

    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "mailchi.mp":
            return httpx.Response(302, headers={"location": "https://mailchimp.com/about/mcsv-static"})
        return httpx.Response(200, text="A page about Mailchimp")

    real = httpx.AsyncClient
    monkeypatch.setattr(mailchimp_parser.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(_handler), **kw))
    assert await mailchimp_parser.fetch_and_parse("https://mailchi.mp/pta/old") == []


# ---- an issue's scan stops once its link stops arriving ------------------------------------


def _at(day: str) -> str:
    return str(int(datetime.fromisoformat(f"{day}T12:00:00+00:00").timestamp() * 1000))


async def test_an_issue_scan_gets_a_stop_date_that_a_new_email_moves(inbox):
    owner_id, school_id = await _owner_and_school()
    scanner = await _scanner(owner_id, school_id, ["smore", "mailchimp"])
    code = uuid.uuid4().hex[:8]
    first = _message(plain=f"https://app.smore.com/n/{code} https://mailchi.mp/pta/{code}")
    first["internalDate"] = _at("2026-10-05")
    inbox.messages = [first]
    async with database.SessionLocal() as db:
        await email_scanner.run_scanner(db, await db.get(EmailScanner, scanner.id))
        smore = (await db.execute(select(SmoreNewsletter).where(SmoreNewsletter.url == f"https://app.smore.com/n/{code}"))).scalar_one()
        mc = (await db.execute(select(SmoreNewsletter).where(SmoreNewsletter.url == f"https://mailchi.mp/pta/{code}"))).scalar_one()
        smore_job, mc_job = await db.get(ScheduledJob, smore.scheduled_job_id), await db.get(ScheduledJob, mc.scheduled_job_id)
        assert smore_job.params["stop_after"] == "2026-11-02" and mc_job.params["stop_after"] == "2026-10-19"
        # It ran out and switched itself off...
        await db.execute(update(ScheduledJob).where(ScheduledJob.id == smore_job.id).values(enabled=False))
        await db.commit()

    # ...then the school sent the same link again: it runs on.
    again = _message(plain=f"https://www.smore.com/n/{code}")
    again["internalDate"] = _at("2026-10-26")
    inbox.messages = [again]
    async with database.SessionLocal() as db:
        await email_scanner.run_scanner(db, await db.get(EmailScanner, scanner.id))
        job = await db.get(ScheduledJob, smore_job.id)
        assert job.params["stop_after"] == "2026-11-23" and job.enabled

    # A scan an admin made by hand has no date, and an email never adds one.
    async with database.SessionLocal() as db:
        hand = SmoreNewsletter(url=f"https://app.smore.com/n/hand{code}", school_id=school_id)
        db.add(hand)
        await db.flush()
        hand_job = ScheduledJob(owner_user_id=owner_id, kind="smore.scan", name=f"Smore scan: hand {code}", cron_expr="0 8 * * 1",
                                params={"newsletter_id": hand.id}, enabled=True)
        db.add(hand_job)
        await db.flush()
        hand.scheduled_job_id = hand_job.id
        await db.commit()
    inbox.messages = [_message(plain=f"https://app.smore.com/n/hand{code}")]
    async with database.SessionLocal() as db:
        await email_scanner.run_scanner(db, await db.get(EmailScanner, scanner.id))
        assert (await db.get(ScheduledJob, hand_job.id)).params == {"newsletter_id": hand.id}


@pytest.mark.parametrize("job_module", ["smore_scan", "mailchimp_scan"])
async def test_a_scan_past_its_stop_date_switches_itself_off_without_fetching(monkeypatch, job_module):
    import importlib

    module = importlib.import_module(f"scheduler.jobs.{job_module}")

    async def _never(url):
        raise AssertionError("fetched a finished issue")

    monkeypatch.setattr(module, "fetch_and_parse", _never)
    owner_id, _ = await _owner_and_school()
    async with database.SessionLocal() as db:
        newsletter = SmoreNewsletter(url=f"https://mailchi.mp/pta/{uuid.uuid4().hex[:8]}", source_type="mailchimp")
        db.add(newsletter)
        await db.flush()
        params = {"newsletter_id": newsletter.id, "stop_after": "2026-01-01"}
        job = ScheduledJob(owner_user_id=owner_id, kind="mailchimp.scan", name=f"t {newsletter.id}", cron_expr="0 8 * * 1",
                           params=params, enabled=True)
        db.add(job)
        await db.flush()
        newsletter.scheduled_job_id = job.id
        await db.commit()
        result = await module.run(db, params)
        await db.commit()
        assert result.startswith("finished:") and not (await db.get(ScheduledJob, job.id)).enabled
