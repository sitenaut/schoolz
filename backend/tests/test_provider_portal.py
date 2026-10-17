"""The Localz provider portal: who may do what, the request state machine,
approval, claims vs scraper refreshes, immediate vs held edits, revert,
confidential addresses and account deletion (docs/LOCALZ_DESIGN.md,
"Provider portal")."""
import os

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

import uuid
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

import database
from main import app
from models import (
    ProviderMembership,
    ResourceChangeLog,
    ResourceChangeRequest,
    ResourceOnboardingRequest,
    ResourcePrivateAddress,
    ResourceService,
    Role,
    RolePermission,
    UserRole,
)
from resources import nj211, portal
from resources.provider_types import PROVIDER_TYPES
from resources.refresh import _apply_detail, _Orgs

pytestmark = pytest.mark.anyio

SECRET_STREET = "17 Hidden Lane"
ALL_TICKED = {k: True for k in portal.CHECKLIST_ITEMS}


@pytest.fixture(autouse=True)
def _no_bot_check(monkeypatch):
    monkeypatch.delenv("TURNSTILE_SECRET_KEY", raising=False)
    monkeypatch.setenv("APP_ENV", "local")


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _register(client: AsyncClient) -> tuple[str, dict]:
    tag = uuid.uuid4().hex[:8]
    res = await client.post(
        "/auth/register", json={"email": f"prov_{tag}@example.com", "username": f"prov_{tag}", "password": "password123"}
    )
    assert res.status_code == 201, res.text
    headers = {"Authorization": f"Bearer {res.json()['access_token']}"}
    me = (await client.get("/auth/me", headers=headers)).json()
    return me["id"], headers


async def _grant(user_id: str, *permissions: str) -> None:
    async with database.SessionLocal() as db:
        if set(permissions) == {"resources.view", "resources.manage"}:
            role = (await db.execute(select(Role).where(Role.name == "Localz reviewer"))).scalar_one()
        else:
            role = Role(name=f"test-{uuid.uuid4().hex[:8]}")
            db.add(role)
            await db.flush()
            for p in permissions:
                db.add(RolePermission(role_id=role.id, permission=p))
        db.add(UserRole(user_id=user_id, role_id=role.id))
        await db.commit()


def _submission(**overrides) -> dict:
    sub = {
        "organization_name": "Maple Street Pantry",
        "services": [{"type": "food_pantry", "name": "Saturday Pantry", "description": "Groceries for anyone who needs them."}],
        "address_kind": "public",
        "address": "12 Maple St",
        "city": "Cherry Hill",
        "postal_code": "08002",
        "service_area_counties": ["Camden"],
        "hours": {"mode": "weekly", "weekly": {"sat": [{"open": "09:00", "close": "12:00"}]}},
        "phone": "856-555-0142",
        "who": {"open_to_anyone": True},
        "cost": {"kind": "free"},
        "website": "https://maplepantry.org",
        "email": "hello@maplepantry.org",
    }
    sub.update(overrides)
    return sub


async def _submitted(client, headers, **body) -> str:
    res = await client.post("/provider-portal/requests", json={"submission": _submission(), **body}, headers=headers)
    assert res.status_code == 201, res.text
    rid = res.json()["id"]
    res = await client.post(f"/provider-portal/requests/{rid}/submit", headers=headers)
    assert res.status_code == 200, res.text
    return rid


async def _approved_listing(client, provider, reviewer, **body) -> str:
    rid = await _submitted(client, provider, **body)
    res = await client.post(f"/admin/resources/onboarding/{rid}/approve", json={"checklist": ALL_TICKED}, headers=reviewer)
    assert res.status_code == 200, res.text
    return res.json()["service_ids"][0]


async def _people(client):
    _, provider = await _register(client)
    reviewer_id, reviewer = await _register(client)
    await _grant(reviewer_id, "resources.view", "resources.manage")
    return provider, reviewer


# ---- catalog ------------------------------------------------------------------------


def test_every_provider_type_has_a_localz_category():
    for t in PROVIDER_TYPES:
        assert t.category, t.key


def test_completeness_matches_the_frontend_meter():
    # frontend/src/lib/providerPortal.test.ts scores the same form 76.
    sub = portal.Submission.model_validate(_submission())
    assert portal.completeness(sub, False) == {
        "missing_core": [],
        "missing_optional": ["documents", "languages", "accessibility", "access", "how_to_apply"],
        "percent": 76,
    }


def test_reviewer_permissions_exist_and_manage_implies_view():
    from permissions import PERMISSION_KEYS, expand

    assert {"resources.view", "resources.manage"} <= PERMISSION_KEYS
    assert "resources.view" in expand({"resources.manage"})


async def test_the_migration_seeded_the_localz_reviewer_role():
    async with database.SessionLocal() as db:
        role = (await db.execute(select(Role).where(Role.name == "Localz reviewer"))).scalar_one()
        perms = set((await db.execute(select(RolePermission.permission).where(RolePermission.role_id == role.id))).scalars())
    assert perms == {"resources.view", "resources.manage"}


# ---- permission gates ------------------------------------------------------------------


async def test_review_queue_gates():
    async with _client() as client:
        assert (await client.get("/admin/resources/onboarding")).status_code == 401
        assert (await client.post("/provider-portal/requests", json={})).status_code == 401
        _, guardian = await _register(client)
        assert (await client.get("/admin/resources/onboarding", headers=guardian)).status_code == 403
        viewer_id, viewer = await _register(client)
        await _grant(viewer_id, "resources.view")
        assert (await client.get("/admin/resources/onboarding", headers=viewer)).status_code == 200
        assert (await client.get("/admin/resources/onboarding/count", headers=viewer)).status_code == 200
        rid = await _submitted(client, guardian)
        assert (await client.get(f"/admin/resources/onboarding/{rid}", headers=viewer)).status_code == 200
        refused = await client.post(f"/admin/resources/onboarding/{rid}/approve", json={"checklist": ALL_TICKED}, headers=viewer)
        assert refused.status_code == 403
        assert (await client.post(f"/admin/resources/onboarding/{rid}/approve", json={"checklist": ALL_TICKED}, headers=guardian)).status_code == 403
        reviewer_id, reviewer = await _register(client)
        await _grant(reviewer_id, "resources.view", "resources.manage")
        assert (await client.post(f"/admin/resources/onboarding/{rid}/approve", json={"checklist": ALL_TICKED}, headers=reviewer)).status_code == 200


async def test_a_request_is_only_its_owners_and_a_draft_is_not_in_the_queue():
    async with _client() as client:
        provider, reviewer = await _people(client)
        _, other = await _register(client)
        rid = (await client.post("/provider-portal/requests", json={"submission": _submission()}, headers=provider)).json()["id"]
        assert (await client.get(f"/provider-portal/requests/{rid}", headers=other)).status_code == 404
        assert (await client.get(f"/admin/resources/onboarding/{rid}", headers=reviewer)).status_code == 404
        assert rid not in [r["id"] for r in (await client.get("/admin/resources/onboarding", headers=reviewer)).json()]


# ---- state machine -----------------------------------------------------------------------


async def test_state_machine():
    async with _client() as client:
        provider, reviewer = await _people(client)
        res = await client.post("/provider-portal/requests", json={"submission": {"organization_name": "Half Done"}}, headers=provider)
        rid = res.json()["id"]
        assert res.json()["status"] == "draft"
        assert "hours" in res.json()["completeness"]["missing_core"]
        # Incomplete core can't be submitted.
        assert (await client.post(f"/provider-portal/requests/{rid}/submit", headers=provider)).status_code == 422
        await client.put(f"/provider-portal/requests/{rid}", json={"submission": _submission()}, headers=provider)
        sent = await client.post(f"/provider-portal/requests/{rid}/submit", headers=provider)
        assert sent.json()["status"] == "submitted" and sent.json()["completeness"]["missing_core"] == []
        # Locked while the reviewer has it.
        assert (await client.put(f"/provider-portal/requests/{rid}", json={"submission": _submission()}, headers=provider)).status_code == 409
        # The checklist moves it into review; Approve needs every item.
        partial = {**ALL_TICKED, "connected": False}
        r = await client.put(f"/admin/resources/onboarding/{rid}/checklist", json={"checklist": partial}, headers=reviewer)
        assert r.json()["status"] == "in_review"
        assert (await client.post(f"/admin/resources/onboarding/{rid}/approve", json={"checklist": partial}, headers=reviewer)).status_code == 422
        # Request changes needs a note.
        assert (await client.post(f"/admin/resources/onboarding/{rid}/request-changes", json={"note": ""}, headers=reviewer)).status_code == 422
        r = await client.post(
            f"/admin/resources/onboarding/{rid}/request-changes", json={"note": "Saturday hours look off", "fields": ["hours"]}, headers=reviewer
        )
        assert r.json()["status"] == "changes_requested"
        mine = (await client.get(f"/provider-portal/requests/{rid}", headers=provider)).json()
        assert mine["decision_note"] == "Saturday hours look off" and mine["fields_to_fix"] == ["hours"]
        # Editable again, and resubmitting returns it to the queue.
        assert (await client.put(f"/provider-portal/requests/{rid}", json={"submission": _submission()}, headers=provider)).status_code == 200
        assert (await client.post(f"/provider-portal/requests/{rid}/submit", headers=provider)).json()["status"] == "submitted"
        r = await client.post(f"/admin/resources/onboarding/{rid}/reject", json={"reason": "could_not_verify", "note": "No answer"}, headers=reviewer)
        assert r.json()["status"] == "rejected"
        assert (await client.post(f"/provider-portal/requests/{rid}/withdraw", headers=provider)).status_code == 409
        # A fresh one can be withdrawn while waiting.
        rid2 = await _submitted(client, provider)
        assert (await client.post(f"/provider-portal/requests/{rid2}/withdraw", headers=provider)).json()["status"] == "withdrawn"
        assert (await client.post(f"/admin/resources/onboarding/{rid2}/approve", json={"checklist": ALL_TICKED}, headers=reviewer)).status_code == 409
        async with database.SessionLocal() as db:
            actions = (await db.execute(select(ResourceChangeLog.action).where(ResourceChangeLog.request_id == rid))).scalars().all()
        assert actions.count("onboarding.decision") == 2


async def test_short_and_payment_links_are_refused():
    async with _client() as client:
        _, provider = await _register(client)
        for url in ("https://bit.ly/abc", "https://www.paypal.me/pantry"):
            res = await client.post("/provider-portal/requests", json={"submission": _submission(website=url)}, headers=provider)
            assert res.status_code == 422, url


# ---- approval ------------------------------------------------------------------------------


async def test_approval_creates_a_provider_listing_and_a_verified_membership():
    async with _client() as client:
        provider, reviewer = await _people(client)
        sid = await _approved_listing(client, provider, reviewer)
        async with database.SessionLocal() as db:
            row = await db.get(ResourceService, sid)
            assert row.source == "provider" and row.status == "active"
            assert row.categories == ["food"] and row.taxonomy_codes == ["BD-1800.2000"]
            assert row.hours_text == "Sat 9 am–12 pm" and row.eligibility_text == "Open to anyone" and row.fees == "Free"
            assert row.missing_core == [] and row.last_assured_on is not None
            assert "phone" in row.provider_owned_fields
            m = (await db.execute(select(ProviderMembership).where(ProviderMembership.service_id == sid))).scalar_one()
            assert m.verified_at is not None and m.verified_by_user_id
        detail = (await client.get(f"/resources/{sid}")).json()
        assert detail["name"] == "Saturday Pantry" and detail["address"] == "12 Maple St"
        listings = (await client.get("/provider-portal/listings", headers=provider)).json()
        assert [x["id"] for x in listings] == [sid] and listings[0]["verified"] is True


async def test_review_shows_duplicates_and_flags():
    async with _client() as client:
        provider, reviewer = await _people(client)
        async with database.SessionLocal() as db:
            db.add(
                ResourceService(
                    source=nj211.SOURCE, source_record_id=f"dup-{uuid.uuid4()}", name="Food Pantry",
                    organization_name="Maple Street Pantry", phone="(856) 555-0142", status="active",
                    required_documents=[], languages=[], service_areas=[], taxonomy_codes=[], taxonomy_names=[],
                    listed_in_counties=[], categories=[], missing_core=[],
                )
            )
            db.add(
                ResourceService(
                    source=nj211.SOURCE, source_record_id=f"other-{uuid.uuid4()}", name="Thrift",
                    organization_name="Somebody Else Inc", phone="856.555.0199", status="active",
                    required_documents=[], languages=[], service_areas=[], taxonomy_codes=[], taxonomy_names=[],
                    listed_in_counties=[], categories=[], missing_core=[],
                )
            )
            await db.commit()
        sub = _submission(
            phone="856-555-0199", email="pantry@gmail.com", cost={"kind": "fee", "amount": "$20"},
            how_to_apply="Pay first at https://cash.app/$pantry",
        )
        rid = (await client.post("/provider-portal/requests", json={"submission": sub}, headers=provider)).json()["id"]
        await client.post(f"/provider-portal/requests/{rid}/submit", headers=provider)
        review = (await client.get(f"/admin/resources/onboarding/{rid}", headers=reviewer)).json()
        assert any("same name" in d["reasons"] for d in review["duplicates"])
        codes = {f["code"] for f in review["flags"]}
        assert {"phone_other_org", "bad_link", "fee_on_free", "free_email"} <= codes
        count = (await client.get("/admin/resources/onboarding/count", headers=reviewer)).json()
        assert count["onboarding"] >= 1


async def test_merge_into_an_existing_record():
    async with _client() as client:
        provider, reviewer = await _people(client)
        async with database.SessionLocal() as db:
            existing = ResourceService(
                source=nj211.SOURCE, source_record_id=f"m-{uuid.uuid4()}", name="Pantry", organization_name="Maple Street Pantry",
                status="active", required_documents=[], languages=[], service_areas=[], taxonomy_codes=[], taxonomy_names=[],
                listed_in_counties=[], categories=[], missing_core=[],
            )
            db.add(existing)
            await db.commit()
            target = existing.id
        rid = await _submitted(client, provider)
        r = await client.post(
            f"/admin/resources/onboarding/{rid}/merge", json={"checklist": ALL_TICKED, "target_service_id": target}, headers=reviewer
        )
        assert r.status_code == 200 and r.json()["service_ids"] == [target]
        async with database.SessionLocal() as db:
            row = await db.get(ResourceService, target)
            assert row.source == nj211.SOURCE and row.name == "Saturday Pantry" and row.phone == "856-555-0142"
            assert (await db.execute(select(ResourceChangeLog.action).where(ResourceChangeLog.service_id == target))).scalars().all() == [
                "onboarding.merge"
            ]


async def test_admin_assisted_needs_a_second_reviewer():
    async with _client() as client:
        _, provider = await _register(client)
        a_id, a = await _register(client)
        b_id, b = await _register(client)
        await _grant(a_id, "resources.view", "resources.manage")
        await _grant(b_id, "resources.view", "resources.manage")
        res = await client.post("/admin/resources/onboarding", json={"submission": _submission(), "contact_name": "Pat"}, headers=a)
        assert res.status_code == 201 and res.json()["origin"] == "admin_assisted"
        rid = res.json()["id"]
        assert (await client.post(f"/admin/resources/onboarding/{rid}/approve", json={"checklist": ALL_TICKED}, headers=a)).status_code == 409
        assert (await client.post(f"/admin/resources/onboarding/{rid}/approve", json={"checklist": ALL_TICKED}, headers=b)).status_code == 200


# ---- claims vs scraper refresh --------------------------------------------------------------


async def test_a_claimed_record_keeps_provider_fields_when_nj211_refreshes():
    async with _client() as client:
        provider, reviewer = await _people(client)
        async with database.SessionLocal() as db:
            scraped = ResourceService(
                source=nj211.SOURCE, source_record_id=str(uuid.uuid4()), name="Food Pantry", organization_name="Maple Street Pantry",
                phone="856-555-0000", description="Old description", status="active", required_documents=[], languages=[],
                service_areas=[], taxonomy_codes=["BD-1800.2000"], taxonomy_names=["Food Pantries"], listed_in_counties=["Camden"],
                categories=["food"], missing_core=[],
            )
            db.add(scraped)
            await db.commit()
            sid = scraped.id
        hits = (await client.post("/provider-portal/match", json={"name": "maple street"}, headers=provider)).json()
        assert sid in [h["id"] for h in hits]
        rid = await _submitted(client, provider, claimed_service_id=sid)
        r = await client.post(f"/admin/resources/onboarding/{rid}/approve", json={"checklist": ALL_TICKED}, headers=reviewer)
        assert r.json()["service_ids"] == [sid]

        # NJ 211 later publishes a different phone and description.
        record = {
            "id": sid, "serviceName": "Food Pantry", "name": "Food Pantry | Maple Street Pantry", "phone": "856-555-9999",
            "description": "Scraped description", "taxonomies": [{"code": "BD-1800.2000", "name": "Food Pantries"}],
            "organizationName": "Maple Street Pantry", "transportation": "Bus 404",
        }
        async with database.SessionLocal() as db:
            row = await db.get(ResourceService, sid)
            await _apply_detail(db, _Orgs(db), row, record, datetime.now(UTC))
            await db.commit()
        async with database.SessionLocal() as db:
            row = await db.get(ResourceService, sid)
            assert row.phone == "856-555-0142"  # the provider's, not the scraper's
            assert row.description == "Groceries for anyone who needs them."
            assert row.transportation == "Bus 404"  # a field the provider never set still refreshes
            conflict = (
                await db.execute(select(ResourceChangeRequest).where(ResourceChangeRequest.service_id == sid, ResourceChangeRequest.kind == "source_conflict"))
            ).scalar_one()
            assert conflict.changes["phone"] == "856-555-9999" and conflict.status == "pending"
            # The same disagreement on the next refresh isn't queued twice.
            await _apply_detail(db, _Orgs(db), row, record, datetime.now(UTC))
            await db.commit()
            assert len((await db.execute(select(ResourceChangeRequest).where(ResourceChangeRequest.service_id == sid))).scalars().all()) == 1
        changes = (await client.get("/admin/resources/changes", headers=reviewer)).json()
        assert any(c["kind"] == "source_conflict" and c["service"]["id"] == sid for c in changes)


async def test_a_claimed_record_is_not_deactivated_when_the_source_drops_it():
    from resources.refresh import _mark_missing

    async with database.SessionLocal() as db:
        row = ResourceService(
            source=nj211.SOURCE, source_record_id=str(uuid.uuid4()), name="Claimed", status="active", missed_crawls=5,
            provider_owned_fields=["phone"], last_seen_at=datetime(2020, 1, 1, tzinfo=UTC), required_documents=[], languages=[],
            service_areas=[], taxonomy_codes=[], taxonomy_names=[], listed_in_counties=[], categories=[], missing_core=[],
        )
        db.add(row)
        await db.commit()
        await _mark_missing(db, datetime.now(UTC))
        await db.commit()
        await db.refresh(row)
        assert row.status == "active"


# ---- quick updates: immediate vs held, revert --------------------------------------------------


async def test_quick_updates_publish_and_held_edits_wait():
    async with _client() as client:
        provider, reviewer = await _people(client)
        sid = await _approved_listing(client, provider, reviewer)
        r = await client.patch(
            f"/provider-portal/listings/{sid}",
            json={"closed_today": True, "alert": "Out of produce this week", "phone": "856-555-7777", "languages": ["Spanish"]},
            headers=provider,
        )
        assert r.status_code == 200, r.text
        assert set(r.json()["applied"]) >= {"closure_starts_on", "alert", "languages"} and r.json()["held"] == ["phone"]
        detail = (await client.get(f"/resources/{sid}")).json()
        assert detail["alert"] == "Out of produce this week" and detail["closure"]["starts_on"] == portal.today().isoformat()
        assert detail["phone"] == "856-555-0142"  # old value stays live
        search = (await client.post("/resources/search", json={"query": "Saturday Pantry"})).json()
        assert search["items"][0]["closure"] is not None

        # Free -> fee and a new category are held too; fee-free changes publish.
        r = await client.patch(
            f"/provider-portal/listings/{sid}", json={"cost": {"kind": "fee", "amount": "$5"}, "types": ["food_pantry", "clothing"]}, headers=provider
        )
        assert set(r.json()["held"]) == {"cost_kind", "fees", "taxonomy_codes", "taxonomy_names"}

        changes = (await client.get("/admin/resources/changes", headers=reviewer)).json()
        phone_change = next(c for c in changes if c["service"] and c["service"]["id"] == sid and "phone" in c["changes"])
        assert (await client.post(f"/admin/resources/changes/{phone_change['id']}/approve", json={}, headers=reviewer)).status_code == 200
        assert (await client.get(f"/resources/{sid}")).json()["phone"] == "856-555-7777"

        # One-step revert of the approved phone change.
        log = (await client.get(f"/admin/resources/services/{sid}/log", headers=reviewer)).json()
        approved = next(e for e in log if e["action"] == "change.approve")
        assert approved["revertible"]
        assert (await client.post(f"/admin/resources/log/{approved['id']}/revert", headers=reviewer)).status_code == 200
        assert (await client.get(f"/resources/{sid}")).json()["phone"] == "856-555-0142"
        assert (await client.post(f"/admin/resources/log/{approved['id']}/revert", headers=reviewer)).status_code == 409

        # Reverting the alert quick update.
        log = (await client.get(f"/admin/resources/services/{sid}/log", headers=reviewer)).json()
        quick = next(e for e in log if e["action"] == "provider.update" and "alert" in e["after"])
        await client.post(f"/admin/resources/log/{quick['id']}/revert", headers=reviewer)
        assert (await client.get(f"/resources/{sid}")).json()["alert"] is None


async def test_an_unverified_members_changes_are_all_held_and_strangers_cant_edit():
    async with _client() as client:
        provider, reviewer = await _people(client)
        sid = await _approved_listing(client, provider, reviewer)
        _, stranger = await _register(client)
        assert (await client.patch(f"/provider-portal/listings/{sid}", json={"alert": "x"}, headers=stranger)).status_code == 404
        editor_id, editor = await _register(client)
        me = (await client.get("/auth/me", headers=editor)).json()
        added = await client.post(f"/admin/resources/services/{sid}/members", json={"email": me["email"]}, headers=reviewer)
        assert added.status_code == 201 and added.json()["verified_at"] is None
        r = await client.patch(f"/provider-portal/listings/{sid}", json={"alert": "Closed for the holiday"}, headers=editor)
        assert r.json()["applied"] == [] and r.json()["held"] == ["alert"]
        assert (await client.get(f"/resources/{sid}")).json()["alert"] is None
        await client.post(f"/admin/resources/memberships/{added.json()['id']}/verify", headers=reviewer)
        r = await client.patch(f"/provider-portal/listings/{sid}", json={"alert": "Closed for the holiday"}, headers=editor)
        assert r.json()["applied"] == ["alert"]


# ---- confidential addresses --------------------------------------------------------------------


async def test_no_public_endpoint_ever_returns_a_confidential_address():
    async with _client() as client:
        provider, reviewer = await _people(client)
        sub = _submission(
            organization_name="Safe Harbor House",
            services=[{"type": "dv_shelter", "name": "Safe Harbor Shelter", "description": "Shelter for survivors and their children."}],
            address_kind="confidential", address=None, city=None, postal_code=None, service_area_counties=["Camden"],
            hours={"mode": "24_7"},
        )
        rid = (
            await client.post("/provider-portal/requests", json={"submission": sub, "private_address": f"{SECRET_STREET}, Haddonfield"}, headers=provider)
        ).json()["id"]
        mine = (await client.get(f"/provider-portal/requests/{rid}", headers=provider)).json()
        assert mine["has_private_address"] is True and SECRET_STREET not in str(mine)
        await client.post(f"/provider-portal/requests/{rid}/submit", headers=provider)
        review = (await client.get(f"/admin/resources/onboarding/{rid}", headers=reviewer)).json()
        assert review["private_address"].startswith(SECRET_STREET)  # the reviewer verifies it
        sid = (await client.post(f"/admin/resources/onboarding/{rid}/approve", json={"checklist": ALL_TICKED}, headers=reviewer)).json()[
            "service_ids"
        ][0]

        # A provider trying to publish a street address later gets it held.
        await client.patch(
            f"/provider-portal/listings/{sid}",
            json={"address": {"kind": "confidential", "counties": ["Camden"], "private_address": "99 Other Rd"}},
            headers=provider,
        )

        responses = [
            await client.get(f"/resources/{sid}"),
            await client.post("/resources/search", json={"query": "Safe Harbor"}),
            await client.post("/resources/search", json={"category": "housing-bills", "county": "Camden"}),
            await client.post("/resources/search", json={"query": "Hidden Lane"}),
            await client.post("/resources/types", json={"category": "housing-bills"}),
            await client.get("/resources/categories"),
            await client.get("/resources/categories?county=Camden"),
            await client.get("/provider-portal/types"),
            await client.post("/provider-portal/match", json={"name": "Safe Harbor"}, headers=provider),
            await client.get("/provider-portal/requests", headers=provider),
            await client.get("/provider-portal/listings", headers=provider),
        ]
        for res in responses:
            assert res.status_code == 200, (res.request.url, res.text)
            assert SECRET_STREET not in res.text and "Haddonfield" not in res.text and "99 Other Rd" not in res.text, res.request.url
        detail = responses[0].json()
        assert detail["location_confidential"] is True
        assert (detail["address"], detail["city"], detail["postal_code"], detail["latitude"]) == (None, None, None, None)
        assert responses[1].json()["items"][0]["id"] == sid
        assert responses[3].json()["total"] == 0  # not searchable by its secret street either

        # Every other public GET the API has, for good measure.
        for route in app.routes:
            path = getattr(route, "path", "")
            if "GET" in getattr(route, "methods", set()) and path.startswith("/resources") and "{" not in path:
                res = await client.get(path)
                assert SECRET_STREET not in res.text, path

        async with database.SessionLocal() as db:
            row = await db.get(ResourceService, sid)
            assert row.address is None and row.city is None and row.raw is None
            stored = await db.get(ResourcePrivateAddress, sid)
            assert stored.kind == "confidential" and stored.address.startswith(SECRET_STREET)
            logs = (await db.execute(select(ResourceChangeLog))).scalars().all()
            assert all(SECRET_STREET not in str(e.before) + str(e.after) for e in logs)
            req = await db.get(ResourceOnboardingRequest, rid)
            assert SECRET_STREET not in str(req.submission)


# ---- "Ask to be listed" ------------------------------------------------------------------------


async def test_inquiry_creates_a_submitted_request_and_is_rate_limited():
    body = {
        "organization_name": "Corner Church Pantry", "contact_name": "Pat", "phone": "609-555-0101",
        "email": "pat@example.org", "what_you_provide": "Food on Thursdays", "town": "Pennsauken",
    }
    async with _client() as client:
        for _ in range(portal.INQUIRIES_PER_HOUR):
            assert (await client.post("/provider-portal/inquiries", json=body)).status_code == 201
        assert (await client.post("/provider-portal/inquiries", json=body)).status_code == 429
        # A bot that fills the hidden field is told "ok" and nothing is stored.
        assert (await client.post("/provider-portal/inquiries", json={**body, "website": "spam"})).status_code == 201
    async with database.SessionLocal() as db:
        rows = (await db.execute(select(ResourceOnboardingRequest).where(ResourceOnboardingRequest.origin == "inquiry"))).scalars().all()
        assert len(rows) == portal.INQUIRIES_PER_HOUR
        assert all(r.status == "submitted" and r.contact_name == "Pat" and r.ip_hash and "127.0.0.1" not in r.ip_hash for r in rows)


# ---- account deletion ------------------------------------------------------------------------------


async def test_delete_account_removes_memberships_and_unfinished_requests():
    async with _client() as client:
        provider, reviewer = await _people(client)
        me = (await client.get("/auth/me", headers=provider)).json()
        sid = await _approved_listing(client, provider, reviewer)
        await client.patch(f"/provider-portal/listings/{sid}", json={"alert": "Closed Monday", "phone": "856-555-1111"}, headers=provider)
        draft = (await client.post("/provider-portal/requests", json={"submission": {"organization_name": "Draft"}}, headers=provider)).json()["id"]
        gone = await client.request("DELETE", "/auth/me", json={"confirm": "DELETE", "password": "password123"}, headers=provider)
        assert gone.status_code == 204, gone.text
        async with database.SessionLocal() as db:
            assert (await db.execute(select(ProviderMembership).where(ProviderMembership.user_id == me["id"]))).first() is None
            assert await db.get(ResourceOnboardingRequest, draft) is None
            assert (await db.execute(select(ResourceChangeRequest).where(ResourceChangeRequest.service_id == sid, ResourceChangeRequest.status == "pending"))).first() is None
            # The listing and its history stay, unattributed.
            assert (await db.get(ResourceService, sid)).status == "active"
            logs = (await db.execute(select(ResourceChangeLog).where(ResourceChangeLog.service_id == sid))).scalars().all()
            assert logs and all(e.actor_user_id != me["id"] for e in logs)
            approved = (await db.execute(select(ResourceOnboardingRequest).where(ResourceOnboardingRequest.service_ids.contains([sid])))).scalar_one()
            assert approved.user_id is None and approved.contact_email is None
