"""Outbound email (services/mailer.py) and the provider portal's uses of it:
decision emails, verify-by-email codes and the 90-day check-in. SMTP is
replaced by a list; nothing leaves the test."""
import os

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

import re
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select, text, update

import database
from models import OutboundEmail, ProviderMembership, ResourceService
from resources import nj211, portal, portal_mail
from scheduler.jobs import email_outbox, resources_checkin
from services import mailer
from tests.test_provider_portal import ALL_TICKED, _approved_listing, _client, _people, _submission

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _no_bot_check(monkeypatch):
    monkeypatch.delenv("TURNSTILE_SECRET_KEY", raising=False)
    monkeypatch.setenv("APP_ENV", "local")


@pytest.fixture(autouse=True)
def _send_explicitly(monkeypatch):
    """In a test every session shares one connection through savepoints, so
    the request's session closing after its background task would roll the
    task's send back (in prod they're separate connections). Tests send
    with `await mailer.send_pending()` instead."""

    async def later() -> None:
        return None

    monkeypatch.setattr(mailer, "send_pending_quietly", later)


@pytest.fixture
def outbox(monkeypatch):
    """SMTP configured, and every message 'sent' into this list."""
    sent: list = []
    monkeypatch.setenv("SMTP_USERNAME", "localz@example.org")
    monkeypatch.setenv("SMTP_PASSWORD", "app-password")

    def fake_send(messages, settings):
        sent.extend(messages)
        return [None] * len(messages)

    monkeypatch.setattr(mailer, "_send_sync", fake_send)
    return sent


@pytest.fixture
def no_smtp(monkeypatch):
    monkeypatch.delenv("SMTP_USERNAME", raising=False)
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)


def _text(msg) -> str:
    return msg.get_body(("plain",)).get_content()


def _html(msg) -> str:
    return msg.get_body(("html",)).get_content()


async def _rows(kind: str) -> list[OutboundEmail]:
    async with database.SessionLocal() as db:
        return list((await db.execute(select(OutboundEmail).where(OutboundEmail.kind == kind))).scalars())


async def test_a_decision_is_emailed_and_the_sent_copy_is_erased(outbox):
    async with _client() as client:
        provider, reviewer = await _people(client)
        await _approved_listing(client, provider, reviewer)
        await mailer.send_pending()
        me = (await client.get("/auth/me", headers=provider)).json()
        mine = [m["Subject"] for m in outbox if m["To"] == me["email"]]
        assert mine == ["Localz: we have Maple Street Pantry", "Maple Street Pantry is on Localz"]
        mine = [m for m in outbox if m["Subject"] == "Maple Street Pantry is on Localz"]
        assert "/localz/providers/portal" in _text(mine[0])
        assert mine[0]["From"] == "schoolz <localz@example.org>"
        row = next(r for r in await _rows("portal.request_approved") if r.user_id == me["id"])
        assert row.status == "sent" and row.to_address is None and row.body is None

        # Changes requested and not approved say why, with the reviewer's note.
        for action, body, kind in (
            ("request-changes", {"note": "Add your Saturday hours", "fields": ["hours"]}, "changes"),
            ("reject", {"reason": "duplicate", "note": "Listed already"}, "Listed already"),
        ):
            rid = (await client.post("/provider-portal/requests", json={"submission": _submission()}, headers=provider)).json()["id"]
            await client.post(f"/provider-portal/requests/{rid}/submit", headers=provider)
            assert (await client.post(f"/admin/resources/onboarding/{rid}/{action}", json=body, headers=reviewer)).status_code == 200
            await mailer.send_pending()
            assert kind in _text(outbox[-1]) or kind in outbox[-1]["Subject"]


async def test_without_smtp_mail_waits_and_the_job_says_so(no_smtp):
    async with _client() as client:
        provider, reviewer = await _people(client)
        await _approved_listing(client, provider, reviewer)
    waiting = [r for r in await _rows("portal.request_approved") if r.status == "queued"]
    assert waiting and waiting[0].to_address  # kept, encrypted, until it can go
    async with database.SessionLocal() as db:
        result = await email_outbox.run(db, {})
    assert result.startswith("WARNING[email_not_configured]")


async def test_a_failed_send_retries_then_gives_up_and_forgets_the_address(outbox, monkeypatch):
    monkeypatch.setattr(mailer, "_send_sync", lambda messages, s: ["SMTPRecipientsRefused: no"] * len(messages))
    async with database.SessionLocal() as db:
        row = mailer.queue(db, kind="test.retry", to="x@example.org", subject="s", body="b")
        await db.commit()
        rid = row.id
    for _ in range(mailer.MAX_ATTEMPTS):
        await mailer.send_pending()
        async with database.SessionLocal() as db:
            await db.execute(update(OutboundEmail).where(OutboundEmail.id == rid).values(next_attempt_at=mailer._now()))
            await db.commit()
    async with database.SessionLocal() as db:
        row = await db.get(OutboundEmail, rid)
        assert row.status == "failed" and row.attempts == mailer.MAX_ATTEMPTS and row.to_address is None


async def _claimed_with_source_email(client, provider, reviewer, checklist) -> str:
    async with database.SessionLocal() as db:
        row = ResourceService(
            source=nj211.SOURCE, source_record_id=f"claim-{uuid.uuid4()}", name="Food Pantry",
            organization_name="Oak Hill Pantry", phone="856-555-0101", email="director@oakhill.org", status="active",
            required_documents=[], languages=[], service_areas=[], taxonomy_codes=["BD-1800.2000"],
            taxonomy_names=["Food Pantries"], listed_in_counties=[], categories=["food"], missing_core=[],
        )
        db.add(row)
        await db.commit()
        target = row.id
    sub = _submission(organization_name="Oak Hill Pantry", email="me@gmail.com", phone="856-555-0101")
    rid = (await client.post("/provider-portal/requests", json={"submission": sub, "claimed_service_id": target}, headers=provider)).json()["id"]
    await client.post(f"/provider-portal/requests/{rid}/submit", headers=provider)
    review = (await client.get(f"/admin/resources/onboarding/{rid}", headers=reviewer)).json()
    assert review["verify_by_email"] == "d***@oakhill.org"
    r = await client.post(f"/admin/resources/onboarding/{rid}/approve", json={"checklist": checklist}, headers=reviewer)
    assert r.status_code == 200, r.text
    return target


async def test_a_claim_can_skip_the_call_and_verify_with_a_code_from_the_source_address(outbox):
    async with _client() as client:
        provider, reviewer = await _people(client)
        sid = await _claimed_with_source_email(client, provider, reviewer, {**ALL_TICKED, "connected": False})
        listing = next(x for x in (await client.get("/provider-portal/listings", headers=provider)).json() if x["id"] == sid)
        # The provider's own (gmail) address replaced the public one, but the
        # code still goes to the address NJ 211 published.
        assert listing["verified"] is False and listing["verify_by_email"] == "d***@oakhill.org"
        r = await client.post(f"/provider-portal/listings/{sid}/verify/send", headers=provider)
        assert r.status_code == 202 and r.json()["sent_to"] == "d***@oakhill.org"
        await mailer.send_pending()
        msg = outbox[-1]
        assert msg["To"] == "director@oakhill.org"
        code = re.search(r"Code: (\d{6})", _text(msg)).group(1)

        wrong = "000000" if code != "000000" else "111111"
        assert (await client.post(f"/provider-portal/listings/{sid}/verify", json={"code": wrong}, headers=provider)).status_code == 422
        assert (await client.post(f"/provider-portal/listings/{sid}/verify", json={"code": code}, headers=provider)).json() == {"verified": True}
        listing = next(x for x in (await client.get("/provider-portal/listings", headers=provider)).json() if x["id"] == sid)
        assert listing["verified"] is True and listing["verify_by_email"] is None


async def test_a_code_check_counts_the_tries_other_requests_made_meanwhile(outbox):
    # Guesses sent in parallel each load the membership before the others count
    # theirs. The check re-reads the row under a lock, so it sees every try.
    async with _client() as client:
        provider, reviewer = await _people(client)
        sid = await _claimed_with_source_email(client, provider, reviewer, {**ALL_TICKED, "connected": False})
        assert (await client.post(f"/provider-portal/listings/{sid}/verify/send", headers=provider)).status_code == 202
    async with database.SessionLocal() as db:
        membership = (await db.execute(select(ProviderMembership).where(ProviderMembership.service_id == sid))).scalar_one()
        assert membership.code_attempts == 0
        await db.execute(text("UPDATE provider_memberships SET code_attempts = :n WHERE id = :id"),
                         {"n": portal_mail.CODE_ATTEMPTS, "id": membership.id})
        assert await portal_mail.check_code(db, membership, "123456") == "Too many tries - ask for a new code."


async def test_codes_are_limited_expire_and_never_go_to_a_typed_address(outbox):
    async with _client() as client:
        provider, reviewer = await _people(client)
        sid = await _claimed_with_source_email(client, provider, reviewer, {**ALL_TICKED, "connected": False})
        for _ in range(3):
            assert (await client.post(f"/provider-portal/listings/{sid}/verify/send", headers=provider)).status_code == 202
        assert (await client.post(f"/provider-portal/listings/{sid}/verify/send", headers=provider)).status_code == 429
        await mailer.send_pending()
        code = re.search(r"Code: (\d{6})", _text(outbox[-1])).group(1)
        async with database.SessionLocal() as db:
            await db.execute(update(ProviderMembership).where(ProviderMembership.service_id == sid)
                             .values(code_expires_at=mailer._now() - timedelta(minutes=1)))
            await db.commit()
        r = await client.post(f"/provider-portal/listings/{sid}/verify", json={"code": code}, headers=provider)
        assert r.status_code == 422 and "expired" in r.json()["detail"]

        # A brand-new listing: the address is the requester's own - phone only,
        # and the call stays required to approve.
        own = await _approved_listing(client, provider, reviewer)
        async with database.SessionLocal() as db:
            await db.execute(update(ProviderMembership).where(ProviderMembership.service_id == own).values(verified_at=None))
            await db.commit()
        assert (await client.post(f"/provider-portal/listings/{own}/verify/send", headers=provider)).status_code == 409
        rid = (await client.post("/provider-portal/requests", json={"submission": _submission()}, headers=provider)).json()["id"]
        await client.post(f"/provider-portal/requests/{rid}/submit", headers=provider)
        r = await client.post(f"/admin/resources/onboarding/{rid}/approve", json={"checklist": {**ALL_TICKED, "connected": False}}, headers=reviewer)
        assert r.status_code == 422


async def test_the_checkin_emails_stale_listings_once_and_confirming_resets_it(outbox):
    async with _client() as client:
        provider, reviewer = await _people(client)
        sid = await _approved_listing(client, provider, reviewer)
        async with database.SessionLocal() as db:
            await db.execute(update(ResourceService).where(ResourceService.id == sid)
                             .values(last_assured_on=portal.today() - timedelta(days=120)))
            await db.commit()
        async with database.SessionLocal() as db:
            await resources_checkin.run(db, resources_checkin.DEFAULT_PARAMS)
        me = (await client.get("/auth/me", headers=provider)).json()
        mine = [m for m in outbox if m["To"] == me["email"] and "still right" in m["Subject"]]
        assert len(mine) == 1 and f"/localz/providers/listings/{sid}" in _text(mine[0])

        async with database.SessionLocal() as db:  # not again within 30 days
            await resources_checkin.run(db, resources_checkin.DEFAULT_PARAMS)
        assert len([m for m in outbox if m["To"] == me["email"] and "still right" in m["Subject"]]) == 1

        r = await client.post(f"/provider-portal/listings/{sid}/confirm", headers=provider)
        assert r.json()["last_assured_on"] == portal.today().isoformat()
        assert (await client.get(f"/resources/{sid}")).json()["last_assured_on"] == portal.today().isoformat()


async def test_sending_a_request_says_we_have_it_and_an_inquiry_echoes_nothing_typed(outbox):
    async with _client() as client:
        provider, reviewer = await _people(client)
        me = (await client.get("/auth/me", headers=provider)).json()
        rid = (await client.post("/provider-portal/requests", json={"submission": _submission()}, headers=provider)).json()["id"]
        assert (await client.post(f"/provider-portal/requests/{rid}/submit", headers=provider)).status_code == 200
        await mailer.send_pending()
        assert outbox[-1]["To"] == me["email"] and outbox[-1]["Subject"] == "Localz: we have Maple Street Pantry"

        # No account: anyone could type a stranger's address, so the
        # confirmation carries none of what they typed.
        lure = "Visit spam.example now"
        body = {"organization_name": lure, "contact_name": lure, "phone": "609-555-0101", "email": "pat@example.org",
                "what_you_provide": lure, "town": "Pennsauken"}
        assert (await client.post("/provider-portal/inquiries", json=body)).status_code == 201
        await mailer.send_pending()
        msg = outbox[-1]
        assert msg["To"] == "pat@example.org" and msg["Subject"] == "Localz: we have your request"
        assert lure not in _text(msg) and lure not in msg["Subject"] and lure not in _html(msg)

        # No email given: nothing to send.
        sent = len(outbox)
        assert (await client.post("/provider-portal/inquiries", json={**body, "email": ""})).status_code == 201
        await mailer.send_pending()
        assert len(outbox) == sent


def test_the_html_part_is_the_same_words_in_the_dark_theme():
    from services import mail_html

    text = (
        'Thanks for sending <b>"Tom & Jerry\'s"</b>.\n\nCode: 123456\n\n'
        "- Pantry (not confirmed yet): https://example.org/l/1\n- Clinic: https://example.org/l/2\n\n"
        "Open your request:\nhttps://example.org/portal\n\n-- \nLocalz, from schoolz\nQuestions? https://example.org/contact\n"
    )
    out = mail_html.render("Subject <x>", text)
    assert "<b>" not in out and "&lt;b&gt;" in out and "Tom &amp; Jerry" in out
    assert mail_html.BG in out and mail_html.CARD in out
    assert ">123456</td>" in out
    assert '<a href="https://example.org/l/1"' in out and ">Pantry (not confirmed yet)</a>" in out
    assert ">Open your request</a>" in out and "Open your request:" not in out
    assert out.index("Localz, from schoolz") > out.index("Open your request")
    assert "<img" not in out and "<title>Subject &lt;x&gt;</title>" in out
