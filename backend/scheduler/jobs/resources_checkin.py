"""Scheduled job: the 90-day "Is this still right?" email to Localz
providers (resources/portal_mail.py:checkin).

A listing a provider manages, not confirmed for 90 days, gets one email to
each member, at most every 30 days. Confirming ("Yes, it's all still
right") or publishing any quick update moves `last_assured_on`."""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import ProviderMembership, ResourceService, User
from resources import portal, portal_mail
from scheduler.registry import register_job
from services import mailer

DEFAULT_PARAMS = {"stale_days": 90, "remind_every_days": 30}


async def queue_checkins(db: AsyncSession, stale_days: int, remind_every_days: int) -> dict:
    day = portal.today()
    rows = (
        await db.execute(
            select(ResourceService, ProviderMembership.user_id, User.email)
            .join(ProviderMembership, ProviderMembership.service_id == ResourceService.id)
            .join(User, User.id == ProviderMembership.user_id)
            .where(
                ResourceService.status == "active",
                or_(ResourceService.last_assured_on.is_(None), ResourceService.last_assured_on <= day - timedelta(days=stale_days)),
                or_(ResourceService.checkin_sent_on.is_(None), ResourceService.checkin_sent_on <= day - timedelta(days=remind_every_days)),
            )
        )
    ).all()
    by_person: dict[tuple[str, str], list[ResourceService]] = defaultdict(list)
    listings: set[str] = set()
    for service, user_id, email in rows:
        if email:
            by_person[(user_id, email)].append(service)
            listings.add(service.id)
    for (user_id, email), services in by_person.items():
        portal_mail.checkin(db, email, user_id, sorted(services, key=lambda s: s.name))
    for service, _, _ in rows:
        service.checkin_sent_on = day
    await db.commit()
    return {"emails": len(by_person), "listings": len(listings)}


@register_job(
    kind="resources.provider_checkin",
    default_name="Localz: is your listing still right?",
    default_cron="13 10 * * 1",
    default_params=DEFAULT_PARAMS,
    description="Emails Localz providers whose listing hasn't been confirmed in 90 days (at most every 30 days).",
)
async def run(db: AsyncSession, params: dict) -> str | None:
    summary = await queue_checkins(db, int(params.get("stale_days", 90)), int(params.get("remind_every_days", 30)))
    summary["send"] = await mailer.send_pending(limit=200)
    return json.dumps(summary)
