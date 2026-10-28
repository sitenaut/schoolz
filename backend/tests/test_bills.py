"""Neighborz (routers/bills.py, routers/admin_bills.py, bills/): the whole
requester/giver flow, the limits, review, and the privacy rules - the
account number reaches only the one giver holding the bill, no free text
crosses between the two, nothing sensitive is stored in plaintext or
logged, and no API key gets in."""
import os

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

import io
import json
import logging
import re
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient
from PIL import Image
from sqlalchemy import select, text, update

import crypto
import database
from bills import catalog, flow, reader
from main import app
from models import BillHold, BillRequest, OutboundEmail, User
from permissions import PERMISSION_KEYS
from scheduler.jobs import bills_sweep
from tests.test_admin_users import _register

pytestmark = pytest.mark.anyio

ACCOUNT = "7319046628"
ZIP = "08002"
CONFIRMATION = "PSEG55K7Q2"


def _raw(account="73 1904 6628", zip_code=ZIP, amount=212.47, **extra) -> dict:
    out = {
        "is_utility_bill": True, "company": "PSE&G", "account_number": account, "service_zip": zip_code,
        "amount_due": amount, "due_date": (date.today() + timedelta(days=10)).isoformat(), "statement_date": None,
        "shutoff_notice": False, "residential": True,
    }
    out.update(extra)
    return out


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("DATA_ENCRYPTION_KEYS", Fernet.generate_key().decode())
    monkeypatch.setenv("ENCRYPTION_REQUIRE", "false")


@pytest.fixture
def reads(monkeypatch):
    """The model call, faked: returns `reads.next` and counts calls."""
    class Reads:
        next = _raw()
        calls = 0

    async def fake(data: bytes) -> dict:
        Reads.calls += 1
        return dict(Reads.next)

    monkeypatch.setattr(reader, "read_bill", fake)
    return Reads


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _png(seed: int = 0) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (12 + seed, 12), (seed * 7 % 256, 90, 140)).save(out, format="PNG")
    return out.getvalue()


async def _upload(client, h, seed=0):
    return await client.post("/bills/upload", headers=h, files={"file": ("bill.png", _png(seed), "image/png")})


async def _post(client, h, reads, seed=0, account=ACCOUNT, zip_code=ZIP, amount=21247, match=True):
    """Upload and post a bill. `match`: the bill as read carries the same
    account number as posted (anything else is an edit, held for review)."""
    if match:
        reads.next = {**reads.next, "account_number": account}
    draft = await _upload(client, h, seed)
    assert draft.status_code == 200, draft.text
    res = await client.post(
        f"/bills/{draft.json()['id']}/post", headers=h,
        json={"account_number": account, "service_zip": zip_code, "amount_cents": amount, "avatar": "fox", "understood": True},
    )
    return draft.json(), res


async def _person(client, prefix, *, aged=True, super_admin=False):
    h, uid = await _register(client, prefix, super_admin=super_admin)
    if aged:
        async with database.SessionLocal() as db:
            await db.execute(update(User).where(User.id == uid).values(created_at=datetime.now(UTC) - timedelta(days=3)))
            await db.commit()
    return h, uid


async def _settle(at: datetime) -> dict:
    async with database.SessionLocal() as db:
        return await flow.settle(db, at)


async def _bill(bill_id) -> BillRequest:
    async with database.SessionLocal() as db:
        return await db.get(BillRequest, bill_id)


def _public(rows, bill_id):
    return next((r for r in rows if r["id"] == bill_id), None)


# ------------------------------------------------------------------ flow


async def test_the_whole_flow_and_who_sees_what(reads):
    async with _client() as client:
        asker, asker_id = await _person(client, "nb_asker")
        giver, giver_id = await _person(client, "nb_giver")

        draft, posted = await _post(client, asker, reads)
        assert draft["account_number"] == ACCOUNT and draft["service_zip"] == ZIP
        assert draft["amount_due_cents"] == 21247 and draft["max_ask_cents"] == 21247 and draft["flags"] == []
        assert posted.status_code == 200, posted.text
        bill_id = posted.json()["id"]
        assert posted.json()["status"] == "available"
        assert (await _bill(bill_id)).image is None  # listed: the image is gone

        # Public, anonymous: nothing but the listing.
        listing = _public((await client.get("/bills")).json(), bill_id)
        assert listing == {
            "id": bill_id, "utility": "pseg", "utility_name": "PSE&G", "amount_cents": 21247, "due_date": listing["due_date"],
            "shutoff_notice": False, "county": "Camden", "avatar": "fox", "state": "open",
        }

        held = await client.post(f"/bills/{bill_id}/hold", headers=giver)
        assert held.status_code == 200, held.text
        hold = held.json()
        assert hold["account_number"] == ACCOUNT and hold["service_zip"] == ZIP and hold["pay_url"]
        assert _public((await client.get("/bills")).json(), bill_id)["state"] == "being_paid"
        # The requester sees that someone is paying, never who.
        mine = (await client.get("/bills/mine", headers=asker)).json()
        assert mine["posted"][0]["status"] == "claimed"
        assert giver_id not in json.dumps(mine)

        paid = await client.post(
            f"/bills/holds/{hold['id']}/paid", headers=giver,
            json={"confirmation_number": CONFIRMATION, "paid_cents": 21247, "paid_on": date.today().isoformat()},
        )
        assert paid.status_code == 200, paid.text
        assert paid.json()["status"] == "reported" and paid.json()["account_number"] is None

        mine = (await client.get("/bills/mine", headers=asker)).json()
        assert mine["posted"][0]["can_answer"] is True
        assert CONFIRMATION not in json.dumps(mine) and giver_id not in json.dumps(mine)

        answered = await client.post(f"/bills/{bill_id}/answer", headers=asker, json={"answer": "paid"})
        assert answered.json()["status"] == "paid" and answered.json()["can_thank"] is True
        assert (await client.post(f"/bills/{bill_id}/thanks", headers=asker, json={"emoji": "hello"})).status_code == 422
        assert (await client.post(f"/bills/{bill_id}/thanks", headers=asker, json={"emoji": "heart"})).status_code == 200
        assert (await client.post(f"/bills/{bill_id}/thanks", headers=asker, json={"emoji": "pray"})).status_code == 409

        gifts = (await client.get("/bills/mine", headers=giver)).json()["gifts"]
        assert gifts[0]["status"] == "confirmed" and gifts[0]["confirmation_number"] == CONFIRMATION
        assert gifts[0]["thanks"] == "heart" and gifts[0]["avatar"] == "fox"
        assert asker_id not in json.dumps(gifts)
        assert _public((await client.get("/bills")).json(), bill_id)["state"] == "paid"

        # The requester heard about the report - in words that say nothing.
        async with database.SessionLocal() as db:
            sent = (await db.execute(select(OutboundEmail).where(OutboundEmail.ref == bill_id))).scalars().all()
        assert [m.kind for m in sent] == ["bills.reported"]
        assert sent[0].subject == flow.SUBJECT
        for word in ("bill", "pse", "212", "paid", "neighbor"):
            assert word not in (sent[0].subject + sent[0].body).lower()


async def test_anonymous_callers_can_only_browse():
    async with _client() as client:
        assert (await client.get("/bills")).status_code == 200
        catalog_out = (await client.get("/bills/catalog")).json()
        assert catalog_out["avatars"] == list(catalog.AVATARS) and "heart" in catalog_out["emojis"]
        some = str(uuid.uuid4())
        for method, path in [
            ("POST", "/bills/upload"), ("POST", f"/bills/{some}/post"), ("DELETE", f"/bills/{some}"),
            ("POST", f"/bills/{some}/answer"), ("POST", f"/bills/{some}/thanks"), ("POST", f"/bills/{some}/hold"),
            ("GET", f"/bills/holds/{some}"), ("POST", f"/bills/holds/{some}/paid"), ("POST", f"/bills/holds/{some}/release"),
            ("GET", "/bills/mine"), ("GET", "/admin/bills"),
        ]:
            assert (await client.request(method, path)).status_code == 401, path


async def test_the_same_upload_is_read_once(reads):
    async with _client() as client:
        h, _ = await _person(client, "nb_reuse")
        first = (await _upload(client, h, 3)).json()
        second = (await _upload(client, h, 3)).json()
        assert first["id"] == second["id"] and reads.calls == 1
        await _upload(client, h, 4)
        assert reads.calls == 2


async def test_uploads_are_capped_per_day(reads):
    async with _client() as client:
        h, _ = await _person(client, "nb_cap")
        for seed in range(catalog.UPLOADS_PER_DAY):
            assert (await _upload(client, h, seed)).status_code == 200
        res = await _upload(client, h, 99)
        assert res.status_code == 429 and res.json()["code"] == "too_many_uploads"


async def test_only_photos_and_pdfs(reads):
    async with _client() as client:
        h, _ = await _person(client, "nb_type")
        res = await client.post("/bills/upload", headers=h, files={"file": ("bill.html", b"<html>hi</html>", "image/png")})
        assert res.status_code == 415 and reads.calls == 0


async def test_not_a_bill_or_another_utility_is_refused_and_cant_be_posted(reads):
    async with _client() as client:
        h, _ = await _person(client, "nb_refuse")
        reads.next = _raw(is_utility_bill=False)
        draft = (await _upload(client, h, 1)).json()
        assert draft["refused"] == "not_a_bill" and draft["account_number"] is None
        res = await client.post(f"/bills/{draft['id']}/post", headers=h,
                                json={"account_number": ACCOUNT, "service_zip": ZIP, "amount_cents": 5000, "avatar": "fox", "understood": True})
        assert res.status_code == 409
        reads.next = _raw(company="Atlantic City Electric")
        assert (await _upload(client, h, 2)).json()["refused"] == "utility_not_supported"


async def test_amount_limits(reads):
    async with _client() as client:
        h, _ = await _person(client, "nb_amount")
        draft = (await _upload(client, h, 1)).json()
        body = {"account_number": ACCOUNT, "service_zip": ZIP, "avatar": "fox", "understood": True}
        for amount in (21248, catalog.MIN_ASK_CENTS - 1):
            res = await client.post(f"/bills/{draft['id']}/post", headers=h, json={**body, "amount_cents": amount})
            assert res.json()["code"] == "amount_not_allowed"
        assert (await client.post(f"/bills/{draft['id']}/post", headers=h, json={**body, "amount_cents": 20000, "understood": False})).status_code == 400
        assert (await client.post(f"/bills/{draft['id']}/post", headers=h, json={**body, "amount_cents": 20000, "avatar": "dragon"})).status_code == 422

        reads.next = _raw(amount=1200.00)
        big = (await _upload(client, h, 2)).json()
        assert big["max_ask_cents"] == catalog.MAX_ASK_CENTS
        res = await client.post(f"/bills/{big['id']}/post", headers=h, json={**body, "amount_cents": catalog.MAX_ASK_CENTS})
        assert res.status_code == 200 and res.json()["amount_cents"] == catalog.MAX_ASK_CENTS
        # One open listing at a time.
        assert (await _upload(client, h, 3)).json()["code"] == "open_listing"


async def test_one_open_listing_per_utility_account_and_one_paid_per_60_days(reads):
    async with _client() as client:
        a, _ = await _person(client, "nb_acct_a")
        b, _ = await _person(client, "nb_acct_b")
        giver, _ = await _person(client, "nb_acct_giver")
        _, first = await _post(client, a, reads)
        bill_id = first.json()["id"]
        _, again = await _post(client, b, reads, seed=1)
        assert again.status_code == 409 and again.json()["code"] == "account_listed"

        hold = (await client.post(f"/bills/{bill_id}/hold", headers=giver)).json()
        await client.post(f"/bills/holds/{hold['id']}/paid", headers=giver,
                          json={"confirmation_number": CONFIRMATION, "paid_cents": 21247, "paid_on": date.today().isoformat()})
        await client.post(f"/bills/{bill_id}/answer", headers=a, json={"answer": "paid"})
        _, again = await _post(client, b, reads, seed=2)
        assert again.json()["code"] == "account_recently_paid"
        # A different account is fine.
        _, other = await _post(client, b, reads, seed=3, account="7319046629")
        assert other.status_code == 200


# --------------------------------------------------------------- review


async def test_an_edited_account_number_is_held_for_a_reviewer(reads):
    async with _client() as client:
        asker, _ = await _person(client, "nb_edit")
        boss, _ = await _person(client, "nb_edit_boss", super_admin=True)
        helper, _ = await _person(client, "nb_edit_helper")
        _, posted = await _post(client, asker, reads, account="7319046620", match=False)
        bill_id = posted.json()["id"]
        assert posted.json()["status"] == "held"
        assert _public((await client.get("/bills")).json(), bill_id) is None

        queue = (await client.get("/admin/bills", headers=boss)).json()
        item = next(x for x in queue["held"] if x["id"] == bill_id)
        assert item["flags"] == ["edited_account"] and item["read"]["account_number"] == "73 1904 6628"
        assert item["account_number"] == "7319046620" and item["has_image"] is True
        image = await client.get(f"/admin/bills/{bill_id}/image", headers=boss)
        assert image.status_code == 200 and image.headers["content-type"] == "image/png"
        assert image.headers["x-content-type-options"] == "nosniff"

        # Not a reviewer: nothing. A key holding every permission: nothing.
        assert (await client.get("/admin/bills", headers=helper)).status_code == 403
        assert (await client.get(f"/admin/bills/{bill_id}/image", headers=helper)).status_code == 403
        made = await client.post("/admin/api-keys", headers=boss, json={"name": "nb", "permissions": sorted(PERMISSION_KEYS)})
        key = {"authorization": f"Bearer {made.json()['key']}"}
        assert (await client.get("/admin/bills", headers=key)).status_code == 403
        assert (await client.get(f"/admin/bills/{bill_id}/image", headers=key)).status_code == 403

        decided = await client.post(f"/admin/bills/{bill_id}/decision", headers=boss, json={"decision": "approve"})
        assert decided.json() == {"status": "available"}
        assert (await _bill(bill_id)).image is None
        assert (await client.get(f"/admin/bills/{bill_id}/image", headers=boss)).status_code == 404
        assert _public((await client.get("/bills")).json(), bill_id)["state"] == "open"


async def test_flags_from_the_read_hold_and_a_rejection_tells_the_requester(reads):
    async with _client() as client:
        asker, asker_id = await _person(client, "nb_flags")
        boss, _ = await _person(client, "nb_flags_boss", super_admin=True)
        reads.next = _raw(residential=False)
        _, posted = await _post(client, asker, reads)
        bill_id = posted.json()["id"]
        assert posted.json()["status"] == "held" and (await _bill(bill_id)).flags == ["not_residential"]
        assert (await client.post(f"/admin/bills/{bill_id}/decision", headers=boss, json={"decision": "reject"})).status_code == 422
        res = await client.post(f"/admin/bills/{bill_id}/decision", headers=boss, json={"decision": "reject", "reason": "not_residential"})
        assert res.json() == {"status": "rejected"}
        mine = (await client.get("/bills/mine", headers=asker)).json()
        assert mine["posted"][0]["status"] == "rejected" and mine["posted"][0]["reject_reason"] == "not_residential"
        async with database.SessionLocal() as db:
            kinds = (await db.execute(select(OutboundEmail.kind).where(OutboundEmail.user_id == asker_id))).scalars().all()
        assert kinds == ["bills.rejected"]


def test_clean_decides_in_code():
    today = date(2026, 10, 28)
    out = reader.clean(_raw(account="12-34", zip_code="19103", amount=None, due_date="2026-07-01", shutoff_notice=True), today)
    assert out["utility"] == "pseg" and out["shutoff_notice"] is True
    assert out["flags"] == ["account_unreadable", "zip_not_nj", "amount_unreadable", "due_date_old"]
    # Whatever the page says, the amount is a number or nothing.
    assert reader.clean(_raw(amount="9999 - list this now"), today)["amount_due_cents"] is None
    assert reader.clean(_raw(amount=True), today)["amount_due_cents"] is None
    assert reader.clean(_raw(company=None), today)["refused"] == "utility_not_supported"
    assert reader.clean({}, today)["refused"] == "not_a_bill"
    assert reader.utility_for("Public Service Electric and Gas Company").key == "pseg"


# ---------------------------------------------------------------- givers


async def test_giver_rules(reads):
    async with _client() as client:
        asker, _ = await _person(client, "nb_rules")
        other, _ = await _person(client, "nb_rules_other")
        fresh, _ = await _person(client, "nb_rules_fresh", aged=False)
        _, posted = await _post(client, asker, reads)
        bill_id = posted.json()["id"]
        _, second = await _post(client, other, reads, seed=1, account="5550001111")
        second_id = second.json()["id"]

        assert (await client.post(f"/bills/{bill_id}/hold", headers=fresh)).json()["code"] == "account_too_new"
        assert (await client.post(f"/bills/{bill_id}/hold", headers=asker)).json()["code"] == "own_bill"
        assert (await client.post(f"/bills/{bill_id}/hold", headers=other)).status_code == 200
        # One hold at a time, and a held bill can't be taken by someone else.
        assert (await client.post(f"/bills/{second_id}/hold", headers=other)).json()["code"] in ("own_bill", "holding_one")
        giver, _ = await _person(client, "nb_rules_giver")
        assert (await client.post(f"/bills/{bill_id}/hold", headers=giver)).json()["code"] == "not_available"
        assert (await client.post(f"/bills/{second_id}/hold", headers=giver)).status_code == 200
        assert (await client.post(f"/bills/{bill_id}/hold", headers=giver)).json()["code"] == "holding_one"


async def test_a_giver_who_posted_the_same_account_cant_hold_it(reads):
    async with _client() as client:
        a, _ = await _person(client, "nb_same_a")
        b, _ = await _person(client, "nb_same_b")
        _, first = await _post(client, a, reads)
        await client.delete(f"/bills/{first.json()['id']}", headers=a)
        _, mine = await _post(client, b, reads)  # same account, posted by someone else now
        assert mine.status_code == 200
        assert (await client.post(f"/bills/{mine.json()['id']}/hold", headers=a)).json()["code"] == "own_bill"


async def test_letting_go_is_free_running_out_is_a_strike_and_two_pause(reads):
    async with _client() as client:
        asker, _ = await _person(client, "nb_strike")
        boss, _ = await _person(client, "nb_strike_boss", super_admin=True)
        giver, giver_id = await _person(client, "nb_strike_giver")
        _, posted = await _post(client, asker, reads)
        bill_id = posted.json()["id"]

        hold = (await client.post(f"/bills/{bill_id}/hold", headers=giver)).json()
        released = await client.post(f"/bills/holds/{hold['id']}/release", headers=giver)
        assert released.json()["status"] == "released" and released.json()["account_number"] is None
        assert (await client.get(f"/bills/holds/{hold['id']}", headers=giver)).json()["account_number"] is None
        assert (await _bill(bill_id)).status == "available"

        for n in (1, 2):
            hold = (await client.post(f"/bills/{bill_id}/hold", headers=giver)).json()
            assert hold["status"] == "active", hold
            done = await _settle(datetime.now(UTC) + catalog.HOLD + timedelta(minutes=n))
            assert done["holds_expired"] >= 1
            assert (await _bill(bill_id)).status == "available"
        async with database.SessionLocal() as db:
            await db.execute(update(BillHold).where(BillHold.giver_id == giver_id, BillHold.status == "expired")
                             .values(settled_at=datetime.now(UTC) - timedelta(hours=1)))
            await db.commit()
            assert await flow.strikes(db, giver_id) == 2
        assert (await client.post(f"/bills/{bill_id}/hold", headers=giver)).json()["code"] == "paused"
        assert (await client.get("/bills/mine", headers=giver)).json()["hold_blocker"] == "paused"

        queue = (await client.get("/admin/bills", headers=boss)).json()
        assert {"giver_id": giver_id, "strikes": 2} in queue["paused"]
        assert (await client.post(f"/admin/bills/givers/{giver_id}/unpause", headers=boss)).status_code == 200
        assert (await client.post(f"/bills/{bill_id}/hold", headers=giver)).status_code == 200


async def test_reporting_paid_checks_the_amount_and_date(reads):
    async with _client() as client:
        asker, _ = await _person(client, "nb_report")
        giver, _ = await _person(client, "nb_report_giver")
        _, posted = await _post(client, asker, reads)
        hold = (await client.post(f"/bills/{posted.json()['id']}/hold", headers=giver)).json()
        url = f"/bills/holds/{hold['id']}/paid"
        good = {"confirmation_number": CONFIRMATION, "paid_cents": 21247, "paid_on": date.today().isoformat()}
        assert (await client.post(url, headers=giver, json={**good, "paid_cents": 20000})).json()["code"] == "amount_mismatch"
        tomorrow = (date.today() + timedelta(days=2)).isoformat()
        assert (await client.post(url, headers=giver, json={**good, "paid_on": tomorrow})).json()["code"] == "paid_on_invalid"
        # No room for a message in the confirmation number.
        for bad in ("call me 555 0101", "abc", "x" * 31, "<b>hi</b>"):
            assert (await client.post(url, headers=giver, json={**good, "confirmation_number": bad})).status_code == 422
        assert (await client.post(url, headers=giver, json=good)).status_code == 200
        assert (await client.post(url, headers=giver, json=good)).json()["code"] == "hold_ended"


async def test_not_yet_goes_to_a_reviewer(reads):
    async with _client() as client:
        asker, _ = await _person(client, "nb_dispute")
        boss, _ = await _person(client, "nb_dispute_boss", super_admin=True)
        giver, giver_id = await _person(client, "nb_dispute_giver")
        _, posted = await _post(client, asker, reads)
        bill_id = posted.json()["id"]
        hold = (await client.post(f"/bills/{bill_id}/hold", headers=giver)).json()
        await client.post(f"/bills/holds/{hold['id']}/paid", headers=giver,
                          json={"confirmation_number": CONFIRMATION, "paid_cents": 21247, "paid_on": date.today().isoformat()})
        assert (await client.post(f"/bills/{bill_id}/answer", headers=asker, json={"answer": "not_yet"})).json()["status"] == "disputed"
        assert (await client.post(f"/bills/{bill_id}/answer", headers=asker, json={"answer": "paid"})).status_code == 409

        dispute = next(d for d in (await client.get("/admin/bills", headers=boss)).json()["disputed"] if d["bill_id"] == bill_id)
        assert dispute["confirmation_number"] == CONFIRMATION and dispute["giver_strikes"] == 0
        assert (await client.post(f"/admin/bills/{bill_id}/decision", headers=boss, json={"decision": "approve"})).status_code == 409
        assert (await client.post(f"/admin/bills/{bill_id}/decision", headers=boss, json={"decision": "relist"})).json() == {"status": "available"}
        async with database.SessionLocal() as db:
            assert (await db.get(BillHold, hold["id"])).status == "struck"
            assert await flow.strikes(db, giver_id) == 1
        gifts = (await client.get("/bills/mine", headers=giver)).json()["gifts"]
        assert gifts[0]["status"] == "struck"


async def test_silence_means_paid_after_a_week_and_closed_bills_are_erased(reads):
    async with _client() as client:
        asker, _ = await _person(client, "nb_silence")
        giver, _ = await _person(client, "nb_silence_giver")
        _, posted = await _post(client, asker, reads)
        bill_id = posted.json()["id"]
        hold = (await client.post(f"/bills/{bill_id}/hold", headers=giver)).json()
        await client.post(f"/bills/holds/{hold['id']}/paid", headers=giver,
                          json={"confirmation_number": CONFIRMATION, "paid_cents": 21247, "paid_on": date.today().isoformat()})
        later = datetime.now(UTC) + catalog.ANSWER_WAIT + timedelta(hours=1)
        assert (await _settle(later))["auto_confirmed"] >= 1
        bill = await _bill(bill_id)
        assert bill.status == "paid" and bill.account_number == ACCOUNT
        fp = bill.account_fingerprint

        assert (await _settle(later + catalog.ERASE_AFTER + timedelta(hours=1)))["erased"] >= 1
        bill = await _bill(bill_id)
        assert bill.account_number is None and bill.service_zip is None and bill.extraction is None
        assert bill.account_fingerprint == fp and bill.erased_at is not None
        # The giver's own record stays.
        assert (await client.get("/bills/mine", headers=giver)).json()["gifts"][0]["confirmation_number"] == CONFIRMATION


async def test_timers_for_drafts_held_bills_and_old_listings(reads):
    async with _client() as client:
        a, _ = await _person(client, "nb_timer_a")
        b, _ = await _person(client, "nb_timer_b")
        c, _ = await _person(client, "nb_timer_c")
        draft = (await _upload(client, a)).json()
        _, held = await _post(client, b, reads, seed=1, account="5550001112", match=False)
        _, listed = await _post(client, c, reads, seed=2)
        assert held.json()["status"] == "held" and listed.json()["status"] == "available"

        async with database.SessionLocal() as db:
            summary = json.loads(await bills_sweep.run(db, {}))
        assert summary["drafts_deleted"] == 0

        await _settle(datetime.now(UTC) + catalog.LISTING_LIFE + timedelta(hours=1))
        assert await _bill(draft["id"]) is None
        assert (await _bill(held.json()["id"])).status == "rejected"
        assert (await _bill(listed.json()["id"])).status == "expired"


async def test_a_hold_ending_soon_gets_one_reminder(reads):
    async with _client() as client:
        asker, _ = await _person(client, "nb_warn")
        giver, giver_id = await _person(client, "nb_warn_giver")
        _, posted = await _post(client, asker, reads)
        await client.post(f"/bills/{posted.json()['id']}/hold", headers=giver)
        soon = datetime.now(UTC) + catalog.HOLD - timedelta(hours=1)
        async with database.SessionLocal() as db:
            assert await flow.warn_ending_holds(db, soon) == 1
            assert await flow.warn_ending_holds(db, soon) == 0
            kinds = (await db.execute(select(OutboundEmail.kind).where(OutboundEmail.user_id == giver_id))).scalars().all()
        assert kinds == ["bills.hold_ending"]


async def test_withdrawing_tells_the_giver_without_a_strike(reads):
    async with _client() as client:
        asker, _ = await _person(client, "nb_withdraw")
        giver, giver_id = await _person(client, "nb_withdraw_giver")
        _, posted = await _post(client, asker, reads)
        bill_id = posted.json()["id"]
        hold = (await client.post(f"/bills/{bill_id}/hold", headers=giver)).json()
        res = await client.delete(f"/bills/{bill_id}", headers=asker)
        assert res.json()["status"] == "withdrawn"
        assert (await client.get(f"/bills/holds/{hold['id']}", headers=giver)).json()["status"] == "withdrawn"
        async with database.SessionLocal() as db:
            assert await flow.strikes(db, giver_id) == 0
            kinds = (await db.execute(select(OutboundEmail.kind).where(OutboundEmail.user_id == giver_id))).scalars().all()
        assert kinds == ["bills.withdrawn"]
        assert (await client.post(f"/bills/{bill_id}/hold", headers=giver)).status_code == 404


async def test_nobody_else_reaches_a_bill_or_a_hold(reads):
    async with _client() as client:
        asker, _ = await _person(client, "nb_owner")
        stranger, _ = await _person(client, "nb_stranger")
        boss, _ = await _person(client, "nb_owner_boss", super_admin=True)
        giver, _ = await _person(client, "nb_owner_giver")
        draft, posted = await _post(client, asker, reads)
        bill_id = posted.json()["id"]
        hold = (await client.post(f"/bills/{bill_id}/hold", headers=giver)).json()
        for who in (stranger, boss):
            assert (await client.get(f"/bills/holds/{hold['id']}", headers=who)).status_code == 404
            assert (await client.post(f"/bills/holds/{hold['id']}/release", headers=who)).status_code == 404
            assert (await client.delete(f"/bills/{bill_id}", headers=who)).status_code == 404
            assert (await client.post(f"/bills/{bill_id}/answer", headers=who, json={"answer": "paid"})).status_code == 404
            mine = (await client.get("/bills/mine", headers=who)).json()
            assert ACCOUNT not in json.dumps(mine)
        # A draft is never public or holdable.
        assert (await client.post(f"/bills/{draft['id']}/hold", headers=stranger)).status_code in (404, 409)
        assert ACCOUNT not in (await client.get("/bills")).text and ZIP not in (await client.get("/bills")).text


async def test_api_keys_are_refused_everywhere(reads):
    async with _client() as client:
        boss, _ = await _person(client, "nb_keys", super_admin=True)
        made = await client.post("/admin/api-keys", headers=boss, json={"name": "nb", "permissions": sorted(PERMISSION_KEYS)})
        key = {"authorization": f"Bearer {made.json()['key']}"}
        some = str(uuid.uuid4())
        for method, path in [
            ("POST", "/bills/upload"), ("POST", f"/bills/{some}/hold"), ("GET", f"/bills/holds/{some}"), ("GET", "/bills/mine"),
            ("DELETE", f"/bills/{some}"), ("GET", "/admin/bills"), ("POST", f"/admin/bills/{some}/decision"),
            ("POST", f"/admin/bills/givers/{some}/unpause"),
        ]:
            assert (await client.request(method, path, headers=key)).status_code == 403, path
        # The public list reads a key as an anonymous visitor.
        assert (await client.get("/bills", headers=key)).status_code == 200


async def test_without_an_encryption_key_nothing_is_posted_or_held(reads, monkeypatch):
    async with _client() as client:
        h, _ = await _person(client, "nb_nokey")
        monkeypatch.delenv("DATA_ENCRYPTION_KEYS")
        res = await _upload(client, h)
        assert res.status_code == 503 and res.json()["code"] == "encryption_unavailable"
        assert (await client.post(f"/bills/{uuid.uuid4()}/hold", headers=h)).json()["code"] == "encryption_unavailable"
        assert reads.calls == 0


async def test_secrets_are_ciphertext_at_rest(reads):
    async with _client() as client:
        asker, _ = await _person(client, "nb_cipher")
        giver, _ = await _person(client, "nb_cipher_giver")
        _, posted = await _post(client, asker, reads, account="7319046620", match=False)  # held: keeps its image
        bill_id = posted.json()["id"]
        async with database.SessionLocal() as db:
            row = (await db.execute(
                text("SELECT account_number, service_zip, extraction, image, account_fingerprint FROM bill_requests WHERE id = :i"), {"i": bill_id}
            )).one()
        for stored in row[:4]:
            assert crypto.is_encrypted(stored) and ACCOUNT[:6] not in stored and "7319046620" not in stored
            with pytest.raises(crypto.EncryptionError):
                crypto.decrypt(stored)  # not the plain configured key
        assert len(row[4]) == 64 and "7319046620" not in row[4]

        _, listed = await _post(client, giver, reads, seed=5)
        hold = (await client.post(f"/bills/{listed.json()['id']}/hold", headers=asker)).json()
        await client.post(f"/bills/holds/{hold['id']}/paid", headers=asker,
                          json={"confirmation_number": CONFIRMATION, "paid_cents": 21247, "paid_on": date.today().isoformat()})
        async with database.SessionLocal() as db:
            stored = (await db.execute(text("SELECT confirmation_number FROM bill_holds WHERE id = :i"), {"i": hold["id"]})).scalar_one()
        assert crypto.is_encrypted(stored) and CONFIRMATION not in stored


_NOISE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|\d{4}-\d{2}-\d{2}[T ][\d:.+]*", re.I)


async def test_no_account_number_zip_or_confirmation_reaches_a_log(reads, caplog):
    caplog.set_level(logging.DEBUG)
    async with _client() as client:
        asker, _ = await _person(client, "nb_logs")
        giver, _ = await _person(client, "nb_logs_giver")
        caplog.clear()
        _, posted = await _post(client, asker, reads)
        bill_id = posted.json()["id"]
        hold = (await client.post(f"/bills/{bill_id}/hold", headers=giver)).json()
        await client.get(f"/bills/holds/{hold['id']}", headers=giver)
        await client.post(f"/bills/holds/{hold['id']}/paid", headers=giver,
                          json={"confirmation_number": CONFIRMATION, "paid_cents": 21247, "paid_on": date.today().isoformat()})
        await client.get("/bills/mine", headers=giver)
        await client.post(f"/bills/{bill_id}/answer", headers=asker, json={"answer": "paid"})
    assert [r for r in caplog.records if r.getMessage() == "http_request" and getattr(r, "path", "").startswith("/bills")]
    for record in caplog.records:
        blob = _NOISE.sub("<x>", record.getMessage() + " " + " ".join(f"{k}={v!r}" for k, v in vars(record).items()))
        for value in (ACCOUNT, "73 1904 6628", CONFIRMATION):
            assert value not in blob, f"{value!r} reached the log via {record.name}"
        assert f"={ZIP}" not in blob and f"'{ZIP}'" not in blob


async def test_a_reveal_is_in_the_audit_log(reads):
    async with _client() as client:
        asker, _ = await _person(client, "nb_audit")
        giver, giver_id = await _person(client, "nb_audit_giver")
        _, posted = await _post(client, asker, reads)
        hold = (await client.post(f"/bills/{posted.json()['id']}/hold", headers=giver)).json()
        await client.get(f"/bills/holds/{hold['id']}", headers=giver)
    async with database.SessionLocal() as db:
        rows = (await db.execute(
            text("SELECT action, target FROM audit_events WHERE actor_user_id = :u AND action = 'bills.account_revealed'"), {"u": giver_id}
        )).all()
    assert len(rows) == 2 and all(r[1]["hold_id"] == hold["id"] for r in rows)
    assert ACCOUNT not in json.dumps([r[1] for r in rows])


# ------------------------------------------------------- account deletion


async def test_deleting_an_account(reads):
    async with _client() as client:
        asker, asker_id = await _person(client, "nb_del")
        giver, giver_id = await _person(client, "nb_del_giver")
        other, _ = await _person(client, "nb_del_other")
        # A paid bill and an open one held by the giver.
        _, paid = await _post(client, asker, reads)
        paid_id = paid.json()["id"]
        hold = (await client.post(f"/bills/{paid_id}/hold", headers=giver)).json()
        await client.post(f"/bills/holds/{hold['id']}/paid", headers=giver,
                          json={"confirmation_number": CONFIRMATION, "paid_cents": 21247, "paid_on": date.today().isoformat()})
        await client.post(f"/bills/{paid_id}/answer", headers=asker, json={"answer": "paid"})
        _, open_bill = await _post(client, asker, reads, seed=1, account="5550001115")
        open_id = open_bill.json()["id"]
        held = (await client.post(f"/bills/{open_id}/hold", headers=giver)).json()

        assert (await client.request("DELETE", "/auth/me", headers=asker, json={"confirm": "DELETE", "password": "password123"})).status_code in (200, 204)
        assert await _bill(open_id) is None
        kept = await _bill(paid_id)
        assert kept.requester_id is None and kept.account_number is None and kept.status == "paid"
        gifts = (await client.get("/bills/mine", headers=giver)).json()["gifts"]
        assert [g["hold_id"] for g in gifts] == [hold["id"]] and gifts[0]["confirmation_number"] == CONFIRMATION
        assert held["id"] not in json.dumps(gifts)

        # A giver leaving lets go of what they hold.
        _, third = await _post(client, other, reads, seed=2, account="5550001116")
        await client.post(f"/bills/{third.json()['id']}/hold", headers=giver)
        assert (await client.request("DELETE", "/auth/me", headers=giver, json={"confirm": "DELETE", "password": "password123"})).status_code in (200, 204)
        assert (await _bill(third.json()["id"])).status == "available"
        async with database.SessionLocal() as db:
            left = (await db.execute(select(BillHold).where(BillHold.request_id == paid_id))).scalar_one()
        assert left.giver_id is None and left.confirmation_number is None
