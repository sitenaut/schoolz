"""The Localz provider portal: the submission form's shape and rules, the
review queue's checks, approval, provider edits and revert. Routers:
`routers/provider_portal.py` (providers, "Ask to be listed") and
`routers/admin_resources.py` (reviewers). Design: docs/LOCALZ_DESIGN.md,
"Provider portal".

Privacy rules this module keeps:
- A confidential address (or a service-area program's mailing address) is
  only ever in an `EncryptedText` column: `ResourceOnboardingRequest.
  private_address`, `ResourceChangeRequest.private_address` or
  `ResourcePrivateAddress`. Never in `submission`, never in a
  `resource_services` column, never in the change log (which records
  {"private_address": "changed"}).
- A confidential listing's public row has no street, town, ZIP or pin.
- Contact people (`contact_*`) are for verification only, never published.
"""
from __future__ import annotations

import hashlib
import os
import re
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models import (
    ProviderMembership,
    ResourceChangeLog,
    ResourceChangeRequest,
    ResourceOnboardingRequest,
    ResourceOrganization,
    ResourcePrivateAddress,
    ResourceService,
    RolePermission,
    User,
    UserRole,
)

from .ownership import jsonable
from .provider_types import BY_CODE, BY_KEY
from .refresh import _derive, name_key

SOURCE = "provider"
EASTERN = ZoneInfo("America/New_York")

NJ_COUNTIES = (
    "Atlantic", "Bergen", "Burlington", "Camden", "Cape May", "Cumberland", "Essex", "Gloucester", "Hudson",
    "Hunterdon", "Mercer", "Middlesex", "Monmouth", "Morris", "Ocean", "Passaic", "Salem", "Somerset",
    "Sussex", "Union", "Warren",
)
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DAY_LABELS = {"mon": "Mon", "tue": "Tue", "wed": "Wed", "thu": "Thu", "fri": "Fri", "sat": "Sat", "sun": "Sun"}

OPEN_STATUSES = ("submitted", "in_review")
EDITABLE_STATUSES = ("draft", "changes_requested")
WITHDRAWABLE_STATUSES = ("draft", "submitted", "in_review", "changes_requested")

# The reviewer checklist (docs/LOCALZ_DESIGN.md): every item ticked before
# Approve. "connected" is the phone call in v1 - it verifies the member.
CHECKLIST_ITEMS = ("exists", "connected", "core_complete", "not_duplicate", "confidential_ok")
REJECT_REASONS = ("not_a_resource", "could_not_verify", "duplicate", "outside_area", "unsafe", "other")

CORE_ITEMS = ("organization_name", "services", "address", "hours", "phone", "who", "cost")
OPTIONAL_ITEMS = ("documents", "languages", "accessibility", "website", "email", "access", "how_to_apply")

# Never accepted as a listing's link, and flagged anywhere in its text:
# people in need are targeted by scams, and a short link hides where it goes.
SHORTENER_DOMAINS = {
    "bit.ly", "tinyurl.com", "t.co", "goo.gl", "ow.ly", "is.gd", "buff.ly", "rebrand.ly", "cutt.ly", "shorturl.at",
    "tiny.cc", "rb.gy", "t.ly", "lnkd.in",
}
PAYMENT_DOMAINS = {
    "paypal.me", "paypal.com", "venmo.com", "cash.app", "cash.me", "gofundme.com", "square.link", "buy.stripe.com",
    "donate.stripe.com", "zellepay.com", "patreon.com", "ko-fi.com", "buymeacoffee.com",
}
FREE_MAIL_DOMAINS = {
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com", "icloud.com", "me.com", "live.com",
    "msn.com", "comcast.net", "verizon.net", "protonmail.com", "proton.me", "optonline.net", "ymail.com",
}

# Inquiry limits per connection ("Ask to be listed" needs no account).
INQUIRIES_PER_HOUR = 3
INQUIRIES_PER_DAY = 6
# Self-serve limits per account.
REQUESTS_PER_DAY = 5
OPEN_REQUESTS_MAX = 10


def now() -> datetime:
    return datetime.now(UTC)


def today() -> date:
    return datetime.now(EASTERN).date()


def week_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


# ---- the form ----------------------------------------------------------------


_TIME = r"^([01]\d|2[0-3]):[0-5]\d$"
_TIME_OR_MIDNIGHT = r"^(([01]\d|2[0-3]):[0-5]\d|24:00)$"


class HoursRange(BaseModel):
    open: str = Field(pattern=_TIME)
    close: str = Field(pattern=_TIME_OR_MIDNIGHT)


class Hours(BaseModel):
    # weekly: the schedule below; 24_7; appointment; call (needs a phone).
    mode: Literal["weekly", "24_7", "appointment", "call"] | None = None
    weekly: dict[Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"], list[HoursRange]] = Field(default_factory=dict)
    # A note on top of the schedule, never instead of it.
    note: str | None = Field(default=None, max_length=300)
    seasonal: str | None = Field(default=None, max_length=200)


class ServiceEntry(BaseModel):
    type: str | None = Field(default=None, max_length=40)
    name: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=500)

    @field_validator("type")
    @classmethod
    def _known_type(cls, value: str | None) -> str | None:
        if value and value not in BY_KEY:
            raise ValueError("Unknown kind of service")
        return value


def _county_list(values: list[str]) -> list[str]:
    out = []
    for value in values:
        county = next((c for c in NJ_COUNTIES if c.lower() == (value or "").strip().lower()), None)
        if county is None:
            raise ValueError("Unknown county")
        if county not in out:
            out.append(county)
    return out


class WhoCanCome(BaseModel):
    open_to_anyone: bool = False
    counties: list[str] = Field(default_factory=list, max_length=21)
    age_min: int | None = Field(default=None, ge=0, le=120)
    age_max: int | None = Field(default=None, ge=0, le=120)
    families_with_children: bool = False
    low_income: bool = False
    seniors: bool = False
    note: str | None = Field(default=None, max_length=300)

    @field_validator("counties")
    @classmethod
    def _counties(cls, values: list[str]) -> list[str]:
        return _county_list(values)


class Cost(BaseModel):
    kind: Literal["free", "sliding", "fee"] | None = None
    amount: str | None = Field(default=None, max_length=100)


class Submission(BaseModel):
    """The portal form. Every field is optional so a draft can be saved
    half-done; `completeness()` decides what a submit needs. No private
    address here: that travels beside it and is stored encrypted."""

    organization_name: str | None = Field(default=None, max_length=200)
    services: list[ServiceEntry] = Field(default_factory=list, max_length=10)
    address_kind: Literal["public", "confidential", "service_area"] | None = None
    address: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, max_length=100)
    postal_code: str | None = Field(default=None, pattern=r"^\d{5}$")
    service_area_counties: list[str] = Field(default_factory=list, max_length=21)
    hours: Hours = Field(default_factory=Hours)
    phone: str | None = Field(default=None, max_length=40)
    who: WhoCanCome = Field(default_factory=WhoCanCome)
    cost: Cost = Field(default_factory=Cost)
    # Strongly prompted, optional.
    documents: list[str] = Field(default_factory=list, max_length=20)
    languages: list[str] = Field(default_factory=list, max_length=20)
    accessibility: str | None = Field(default=None, max_length=300)
    website: str | None = Field(default=None, max_length=300)
    email: str | None = Field(default=None, max_length=255)
    access: Literal["walk_in", "appointment", "both"] | None = None
    how_to_apply: str | None = Field(default=None, max_length=1000)
    # Shown publicly as the contact: a role ("Pantry coordinator"), never a person.
    public_contact_role: str | None = Field(default=None, max_length=100)
    # From "Ask to be listed": what they told us before there was a form.
    what_you_provide: str | None = Field(default=None, max_length=1000)
    town: str | None = Field(default=None, max_length=100)

    @field_validator("service_area_counties")
    @classmethod
    def _counties(cls, values: list[str]) -> list[str]:
        return _county_list(values)

    @field_validator("documents", "languages")
    @classmethod
    def _short_items(cls, values: list[str]) -> list[str]:
        return [v.strip()[:200] for v in values if v and v.strip()]


def phone_digits(phone: str | None) -> str:
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits


def valid_phone(phone: str | None) -> bool:
    return len(phone_digits(phone)) == 10


def _domain(url_or_email: str | None) -> str | None:
    if not url_or_email:
        return None
    value = url_or_email.strip().lower()
    if "@" in value and "/" not in value:
        host = value.rsplit("@", 1)[1]
    else:
        if not value.startswith(("http://", "https://")):
            value = "https://" + value
        host = urlparse(value).hostname or ""
    host = host.strip(".")
    return host[4:] if host.startswith("www.") else host or None


def _matches(host: str, domains: set[str]) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


def bad_link_reason(url: str | None) -> str | None:
    """Why a link can't be a listing's website, or None."""
    host = _domain(url)
    if not host:
        return None
    if _matches(host, SHORTENER_DOMAINS):
        return "Short links can't be used - please give the full web address."
    if _matches(host, PAYMENT_DOMAINS):
        return "Payment or donation links can't be a listing's website."
    return None


def check_links(sub: Submission) -> None:
    reason = bad_link_reason(sub.website)
    if reason:
        raise ValueError(reason)
    if sub.website and not sub.website.lower().startswith(("http://", "https://")):
        sub.website = "https://" + sub.website.strip()


def _hours_done(hours: Hours, phone: str | None) -> bool:
    if hours.mode == "weekly":
        return any(hours.weekly.get(d) for d in DAYS)
    if hours.mode == "call":
        return valid_phone(phone)
    return hours.mode in ("24_7", "appointment")


def _who_done(who: WhoCanCome) -> bool:
    return who.open_to_anyone or bool(
        who.counties or who.age_min is not None or who.age_max is not None or who.families_with_children
        or who.low_income or who.seniors or (who.note or "").strip()
    )


def _address_done(sub: Submission, has_private_address: bool) -> bool:
    if sub.address_kind == "public":
        return bool((sub.address or "").strip() and (sub.city or "").strip())
    if sub.address_kind == "confidential":
        return has_private_address and bool(sub.service_area_counties)
    if sub.address_kind == "service_area":
        return has_private_address and bool(sub.service_area_counties)
    return False


def completeness(sub: Submission, has_private_address: bool) -> dict:
    """What a submission still needs. Mirrored in the form's meter
    (frontend/src/lib/providerPortal.ts) - keep the two in step."""
    done = {
        "organization_name": bool((sub.organization_name or "").strip()),
        "services": bool(sub.services) and all(s.type and (s.name or "").strip() and (s.description or "").strip() for s in sub.services),
        "address": _address_done(sub, has_private_address),
        "hours": _hours_done(sub.hours, sub.phone),
        "phone": valid_phone(sub.phone),
        "who": _who_done(sub.who),
        "cost": sub.cost.kind is not None and (sub.cost.kind != "fee" or bool((sub.cost.amount or "").strip())),
        "documents": bool(sub.documents),
        "languages": bool(sub.languages),
        "accessibility": bool((sub.accessibility or "").strip()),
        "website": bool((sub.website or "").strip()),
        "email": bool((sub.email or "").strip()),
        "access": sub.access is not None,
        "how_to_apply": bool((sub.how_to_apply or "").strip()),
    }
    core_done = sum(done[k] for k in CORE_ITEMS)
    optional_done = sum(done[k] for k in OPTIONAL_ITEMS)
    percent = round(100 * (2 * core_done + optional_done) / (2 * len(CORE_ITEMS) + len(OPTIONAL_ITEMS)))
    return {
        "missing_core": [k for k in CORE_ITEMS if not done[k]],
        "missing_optional": [k for k in OPTIONAL_ITEMS if not done[k]],
        "percent": percent,
    }


# ---- form -> listing columns ---------------------------------------------------


def _clock(value: str) -> str:
    hour, minute = (int(x) for x in value.split(":"))
    if hour == 24:
        return "midnight"
    suffix = "am" if hour < 12 else "pm"
    hour12 = hour % 12 or 12
    return f"{hour12}:{minute:02d} {suffix}" if minute else f"{hour12} {suffix}"


def hours_text(hours: Hours | dict | None) -> str | None:
    """The schedule as one line for cards and search ("Mon 9 am-12 pm; Wed
    1-4 pm" style). English, like the scraped sources' hours."""
    if hours is None:
        return None
    if isinstance(hours, dict):
        hours = Hours.model_validate(hours)
    if hours.mode == "weekly":
        parts = []
        for day in DAYS:
            ranges = hours.weekly.get(day) or []
            if ranges:
                parts.append(f"{DAY_LABELS[day]} " + ", ".join(f"{_clock(r.open)}–{_clock(r.close)}" for r in ranges))
        text = "; ".join(parts)
    elif hours.mode == "24_7":
        text = "Open 24 hours, 7 days a week"
    elif hours.mode == "appointment":
        text = "By appointment"
    elif hours.mode == "call":
        text = "Call for hours"
    else:
        text = ""
    extras = [x.strip() for x in (hours.note, hours.seasonal) if x and x.strip()]
    text = ". ".join([t for t in [text, *extras] if t])
    return text or None


def who_text(who: WhoCanCome) -> str | None:
    if who.open_to_anyone:
        return "Open to anyone" + (f". {who.note.strip()}" if (who.note or "").strip() else "")
    parts = []
    if who.families_with_children:
        parts.append("Families with children")
    if who.seniors:
        parts.append("Adults 60 and older")
    if who.age_min is not None and who.age_max is not None:
        parts.append(f"Ages {who.age_min}–{who.age_max}")
    elif who.age_min is not None:
        parts.append(f"Ages {who.age_min} and up")
    elif who.age_max is not None:
        parts.append(f"Ages {who.age_max} and under")
    if who.low_income:
        parts.append("Low income")
    if who.counties:
        word = "County" if len(who.counties) == 1 else "Counties"
        parts.append(f"Lives in {', '.join(who.counties)} {word}")
    if (who.note or "").strip():
        parts.append(who.note.strip())
    return "; ".join(parts) or None


def fees_text(cost: Cost) -> str | None:
    if cost.kind == "free":
        return "Free"
    if cost.kind == "sliding":
        return "Sliding scale" + (f": {cost.amount.strip()}" if (cost.amount or "").strip() else "")
    if cost.kind == "fee":
        return f"Fee: {(cost.amount or '').strip()}".rstrip(": ")
    return None


_ACCESS = {"walk_in": "Walk-ins welcome.", "appointment": "By appointment.", "both": "Walk in or make an appointment."}


def address_columns(kind: str | None, address: str | None, city: str | None, postal_code: str | None, counties: list[str]) -> dict:
    public = kind == "public"
    return {
        "address_kind": kind,
        "address": ((address or "").strip() or None) if public else None,
        "city": ((city or "").strip() or None) if public else None,
        "postal_code": postal_code if public else None,
        "latitude": None,
        "longitude": None,
        "service_areas": [f"{c} County, NJ" for c in counties],
    }


def type_columns(type_keys: list[str]) -> dict:
    types = [BY_KEY[k] for k in type_keys if k in BY_KEY]
    return {"taxonomy_codes": [t.code for t in types], "taxonomy_names": [t.code_name for t in types]}


def service_columns(sub: Submission, entry: ServiceEntry) -> dict:
    """The resource_services columns one service of a submission sets. All
    of them become provider-owned on approval."""
    how = " ".join(x for x in [_ACCESS.get(sub.access or ""), (sub.how_to_apply or "").strip()] if x) or None
    hours = sub.hours.model_dump(mode="json")
    return {
        "name": (entry.name or "").strip(),
        "organization_name": (sub.organization_name or "").strip() or None,
        "location_name": (sub.organization_name or "").strip() or None,
        "description": (entry.description or "").strip() or None,
        "phone": (sub.phone or "").strip() or None,
        "email": (sub.email or "").strip() or None,
        "website": (sub.website or "").strip() or None,
        **address_columns(sub.address_kind, sub.address, sub.city, sub.postal_code, sub.service_area_counties),
        "hours": hours,
        "hours_text": hours_text(sub.hours),
        "eligibility_text": who_text(sub.who),
        "application_process": how,
        "fees": fees_text(sub.cost),
        "cost_kind": sub.cost.kind,
        "required_documents": list(sub.documents),
        "languages": list(sub.languages),
        "accessibility": (sub.accessibility or "").strip() or None,
        **type_columns([entry.type] if entry.type else []),
    }


def snapshot(row: ResourceService, fields) -> dict:
    return {f: jsonable(getattr(row, f)) for f in fields}


_DATE_COLUMNS = {"closure_starts_on", "closure_ends_on", "last_assured_on"}


def from_json(field: str, value: Any) -> Any:
    if field in _DATE_COLUMNS and isinstance(value, str):
        return date.fromisoformat(value)
    return value


def apply_columns(row: ResourceService, columns: dict) -> None:
    for field, value in columns.items():
        setattr(row, field, from_json(field, value))
    owned = list(row.provider_owned_fields or [])
    row.provider_owned_fields = owned + [f for f in columns if f not in owned]
    if row.address_kind == "confidential":
        # Belt and braces: nothing locating a confidential place stays public.
        row.address = row.city = row.postal_code = None
        row.latitude = row.longitude = None
        row.raw = None
    _derive(row)


async def set_private_address(db: AsyncSession, service_id: str, kind: str | None, address: str | None) -> None:
    if not address or kind not in ("confidential", "service_area"):
        return
    stored = await db.get(ResourcePrivateAddress, service_id)
    label = "confidential" if kind == "confidential" else "mailing"
    if stored is None:
        db.add(ResourcePrivateAddress(service_id=service_id, kind=label, address=address))
    else:
        stored.kind, stored.address = label, address


def log(db: AsyncSession, *, action: str, actor: User | None, actor_kind: str, service_id: str | None = None,
        request_id: str | None = None, change_request_id: str | None = None, before: dict | None = None,
        after: dict | None = None, note: str | None = None) -> ResourceChangeLog:
    entry = ResourceChangeLog(
        action=action, actor_user_id=actor.id if actor else None, actor_kind=actor_kind, service_id=service_id,
        request_id=request_id, change_request_id=change_request_id, before=before or {}, after=after or {}, note=note,
    )
    db.add(entry)
    return entry


# ---- review checks -------------------------------------------------------------


def _digits_sql(column):
    return func.right(func.regexp_replace(column, r"\D", "", "g"), 10)


async def duplicates(db: AsyncSession, sub: Submission, exclude_ids: list[str] | None = None) -> list[dict]:
    """Existing listings (any source, NJ 211 included) that look like this
    one: the same organization name, phone or street address."""
    conditions = []
    key = name_key(sub.organization_name or "")
    if key:
        conditions.append(func.regexp_replace(func.lower(ResourceService.organization_name), "[^a-z0-9]+", " ", "g") == key)
        conditions.append(ResourceService.organization_name.ilike(f"%{(sub.organization_name or '').strip()[:60]}%"))
    digits = phone_digits(sub.phone)
    if len(digits) == 10:
        conditions.append(_digits_sql(ResourceService.phone) == digits)
    street = (sub.address or "").strip()
    if sub.address_kind == "public" and len(street) >= 6:
        conditions.append(ResourceService.address.ilike(f"{street[:60]}%"))
    if not conditions:
        return []
    query = select(ResourceService).where(or_(*conditions)).order_by(ResourceService.name).limit(10)
    if exclude_ids:
        query = query.where(ResourceService.id.not_in(exclude_ids))
    rows = (await db.execute(query)).scalars().all()
    out = []
    for row in rows:
        reasons = []
        if key and name_key(row.organization_name or "") == key:
            reasons.append("same name")
        elif key:
            reasons.append("similar name")
        if len(digits) == 10 and phone_digits(row.phone)[-10:] == digits:
            reasons.append("same phone")
        if street and row.address and row.address.lower().startswith(street[:60].lower()):
            reasons.append("same address")
        out.append(listing_brief(row) | {"reasons": reasons})
    return out


def listing_brief(row: ResourceService) -> dict:
    """Public columns only - a confidential row has no address to show."""
    return {
        "id": row.id,
        "name": row.name,
        "organization_name": row.organization_name,
        "city": row.city,
        "address": row.address,
        "phone": row.phone,
        "source": row.source,
        "status": row.status,
        "location_confidential": row.address_kind == "confidential",
    }


_URL_RE = re.compile(r"(?:https?://|www\.)[^\s)]+|\b[a-z0-9-]+\.(?:ly|gl|me|link|app|co)/[^\s)]*", re.I)


async def flags(db: AsyncSession, req: ResourceOnboardingRequest, sub: Submission, account_email: str | None) -> list[dict]:
    """Automated signals for the reviewer. Each is a prompt to look, not a
    verdict; "domain_match" is the one positive signal (v1 verification)."""
    out: list[dict] = []
    site = _domain(sub.website)
    emails = [e for e in {req.contact_email, sub.email, account_email} if e]
    for email in emails:
        host = _domain(email)
        if not host:
            continue
        if host in FREE_MAIL_DOMAINS:
            out.append({"code": "free_email", "level": "info", "message": f"{email} is a free email address - confirm by calling the listed number."})
        elif site and (host == site or host.endswith("." + site) or site.endswith("." + host)):
            out.append({"code": "domain_match", "level": "ok", "message": f"{email} matches the website's domain ({site})."})
        elif site:
            out.append({"code": "domain_mismatch", "level": "warn", "message": f"{email} doesn't match the website's domain ({site})."})
    digits = phone_digits(sub.phone)
    if len(digits) == 10:
        key = name_key(sub.organization_name or "")
        rows = (
            await db.execute(
                select(ResourceService.name, ResourceService.organization_name)
                .where(_digits_sql(ResourceService.phone) == digits, ResourceService.status == "active")
                .limit(20)
            )
        ).all()
        others = sorted({org or name for name, org in rows if name_key(org or name or "") != key})
        if others:
            out.append({"code": "phone_other_org", "level": "warn", "message": f"This phone number is listed for another organization: {', '.join(others[:3])}."})
    texts = [sub.website or "", sub.how_to_apply or "", *[(s.description or "") for s in sub.services], sub.what_you_provide or ""]
    for url in {m.group(0) for t in texts for m in _URL_RE.finditer(t)} | ({sub.website} if sub.website else set()):
        reason = bad_link_reason(url)
        if reason:
            out.append({"code": "bad_link", "level": "warn", "message": f"{url}: {reason}"})
    if sub.cost.kind == "fee":
        free_kinds = [BY_KEY[s.type].label for s in sub.services if s.type in BY_KEY and BY_KEY[s.type].normally_free]
        if free_kinds:
            out.append({"code": "fee_on_free", "level": "warn", "message": f"Charges a fee for a kind of help that's normally free ({', '.join(free_kinds)})."})
    if sub.address_kind == "confidential":
        out.append({"code": "confidential", "level": "info", "message": "Confidential address: check the public listing will show no location."})
    if req.claimed_service_id:
        managed = await db.scalar(
            select(func.count()).select_from(ProviderMembership).where(ProviderMembership.service_id == req.claimed_service_id)
        )
        if managed:
            out.append({"code": "already_managed", "level": "warn", "message": "Someone already manages this listing."})
    return out


async def reviewer_count(db: AsyncSession) -> int:
    """People who could approve: super admins and holders of resources.manage."""
    supers = set((await db.execute(select(User.id).where(User.is_admin.is_(True)))).scalars().all())
    granted = set(
        (
            await db.execute(
                select(UserRole.user_id)
                .join(RolePermission, RolePermission.role_id == UserRole.role_id)
                .where(RolePermission.permission == "resources.manage")
            )
        ).scalars().all()
    )
    return len(supers | granted)


# ---- approval --------------------------------------------------------------------


async def _organization(db: AsyncSession, name: str) -> ResourceOrganization | None:
    key = name_key(name)
    if not key:
        return None
    org = (await db.execute(select(ResourceOrganization).where(ResourceOrganization.name_key == key))).scalar_one_or_none()
    if org is None:
        org = ResourceOrganization(name=name.strip(), name_key=key)
        db.add(org)
        await db.flush()
    return org


async def approve(db: AsyncSession, req: ResourceOnboardingRequest, reviewer: User, target: ResourceService | None,
                  note: str | None) -> list[ResourceService]:
    """Create (or, for a claim/merge, take over) the listing rows and the
    membership. The caller has checked status, checklist and completeness."""
    sub = Submission.model_validate(req.submission)
    org = await _organization(db, sub.organization_name or "")
    stamp, day = now(), today()
    rows: list[ResourceService] = []
    for i, entry in enumerate(sub.services):
        columns = service_columns(sub, entry)
        if i == 0 and target is not None:
            row = target
            before = snapshot(row, columns)
            apply_columns(row, columns)
            row.last_assured_on = day
            action = "onboarding.claim" if req.claimed_service_id == target.id else "onboarding.merge"
        else:
            row = ResourceService(
                source=SOURCE,
                source_record_id=f"{req.id}:{i}",
                organization_id=org.id if org else None,
                status="active",
                first_seen_at=stamp,
                last_seen_at=stamp,
                detail_fetched_at=stamp,
                last_assured_on=day,
                provider_owned_fields=[],
                listed_in_counties=[],
                categories=[],
                missing_core=[],
            )
            apply_columns(row, columns)
            db.add(row)
            await db.flush()
            before, action = {}, "onboarding.approve"
        await set_private_address(db, row.id, sub.address_kind, req.private_address)
        after = snapshot(row, columns)
        if req.private_address and sub.address_kind in ("confidential", "service_area"):
            after["private_address"] = "set"
        log(db, action=action, actor=reviewer, actor_kind="reviewer", service_id=row.id, request_id=req.id,
            before=before, after=after, note=note)
        rows.append(row)
        if req.user_id:
            membership = (
                await db.execute(
                    select(ProviderMembership).where(ProviderMembership.user_id == req.user_id, ProviderMembership.service_id == row.id)
                )
            ).scalar_one_or_none()
            if membership is None:
                membership = ProviderMembership(user_id=req.user_id, service_id=row.id, organization_id=row.organization_id, role="owner", request_id=req.id)
                db.add(membership)
            if req.checklist.get("connected"):
                # v1 verification: the reviewer called the listed number.
                membership.verified_at, membership.verified_by_user_id = stamp, reviewer.id
    req.status = "approved"
    req.service_ids = [r.id for r in rows]
    req.reviewed_by_user_id, req.reviewed_at = reviewer.id, stamp
    req.decision_note = note
    log(db, action="onboarding.decision", actor=reviewer, actor_kind="reviewer", request_id=req.id,
        after={"status": "approved", "checklist": req.checklist, "service_ids": req.service_ids}, note=note)
    return rows


# ---- provider edits to a live listing ----------------------------------------


# Publish at once for a verified member (docs/LOCALZ_DESIGN.md, "What
# publishes immediately vs. what waits for review").
IMMEDIATE_FIELDS = {
    "closure_starts_on", "closure_ends_on", "closure_note", "week_hours", "hours", "hours_text", "alert",
    "description", "languages", "required_documents", "eligibility_text", "application_process",
    "accessibility",
}
# Everything else that can be edited waits: name, organization name,
# address, phone, website, email, categories, and a free -> fee change.


def split_changes(row: ResourceService, columns: dict, verified: bool) -> tuple[dict, dict]:
    """(publish now, hold for review)."""
    if not verified:
        return {}, dict(columns)
    now_cols, held = {}, {}
    for field, value in columns.items():
        if field in IMMEDIATE_FIELDS:
            now_cols[field] = value
        elif field in ("cost_kind", "fees"):
            continue  # decided together below
        elif field in ("taxonomy_codes", "taxonomy_names"):
            continue
        else:
            held[field] = value
    if "cost_kind" in columns or "fees" in columns:
        was_free = (row.cost_kind or ("free" if (row.fees or "").strip().lower() == "free" else None)) == "free"
        target = held if was_free and columns.get("cost_kind") in ("fee", "sliding") else now_cols
        for field in ("cost_kind", "fees"):
            if field in columns:
                target[field] = columns[field]
    if "taxonomy_codes" in columns:
        adds = set(columns["taxonomy_codes"]) - set(row.taxonomy_codes or [])
        target = held if adds else now_cols
        target["taxonomy_codes"] = columns["taxonomy_codes"]
        target["taxonomy_names"] = columns.get("taxonomy_names", [BY_CODE[c].code_name if c in BY_CODE else c for c in columns["taxonomy_codes"]])
    return now_cols, held


def has_changes(row: ResourceService, columns: dict) -> dict:
    return {f: v for f, v in columns.items() if jsonable(getattr(row, f)) != v}


async def approve_change(db: AsyncSession, change: ResourceChangeRequest, reviewer: User, note: str | None) -> None:
    row = await db.get(ResourceService, change.service_id)
    before = snapshot(row, change.changes)
    apply_columns(row, change.changes)
    after = dict(change.changes)
    if change.private_address:
        await set_private_address(db, row.id, row.address_kind, change.private_address)
        after["private_address"] = "changed"
        change.private_address = None  # it lives in resource_private_addresses now
    change.status, change.reviewed_by_user_id, change.reviewed_at, change.note = "approved", reviewer.id, now(), note
    log(db, action="change.approve", actor=reviewer, actor_kind="reviewer", service_id=row.id,
        change_request_id=change.id, before=before, after=after, note=note)


REVERTIBLE = {"provider.update", "change.approve", "onboarding.claim", "onboarding.merge", "onboarding.approve"}


async def revert(db: AsyncSession, entry: ResourceChangeLog, reviewer: User) -> ResourceChangeLog:
    """Undo one logged change: put its `before` back (public columns only),
    or, for a listing that approval created, take it down."""
    row = await db.get(ResourceService, entry.service_id) if entry.service_id else None
    if row is None:
        raise ValueError("That listing no longer exists")
    if entry.action == "onboarding.approve":
        before, after = {"status": row.status}, {"status": "inactive"}
        row.status = "inactive"
    else:
        restore = {f: v for f, v in entry.before.items() if f != "private_address" and hasattr(ResourceService, f)}
        before = snapshot(row, restore)
        for field, value in restore.items():
            setattr(row, field, from_json(field, value))
        if row.address_kind == "confidential":
            row.address = row.city = row.postal_code = None
            row.latitude = row.longitude = None
        _derive(row)
        after = restore
    entry.reverted_at, entry.reverted_by_user_id = now(), reviewer.id
    return log(db, action="revert", actor=reviewer, actor_kind="reviewer", service_id=row.id, before=before,
               after=after, note=f"Reverted change {entry.id}")


# ---- account deletion ------------------------------------------------------------


async def delete_user_data(db: AsyncSession, user_id: str) -> None:
    """What deleting an account removes from the portal. The person's
    memberships and every request that never became a listing go; a listing
    they got approved stays (it's a public resource now) but the request
    forgets who asked and how to reach them. Log rows stay, unattributed."""
    await db.execute(delete(ProviderMembership).where(ProviderMembership.user_id == user_id))
    await db.execute(
        delete(ResourceOnboardingRequest).where(
            ResourceOnboardingRequest.user_id == user_id, ResourceOnboardingRequest.status != "approved"
        )
    )
    await db.execute(
        update(ResourceOnboardingRequest)
        .where(ResourceOnboardingRequest.user_id == user_id)
        .values(user_id=None, contact_name=None, contact_email=None, contact_phone=None)
    )
    await db.execute(
        update(ResourceOnboardingRequest).where(ResourceOnboardingRequest.created_by_user_id == user_id).values(created_by_user_id=None)
    )
    await db.execute(
        update(ResourceOnboardingRequest).where(ResourceOnboardingRequest.reviewed_by_user_id == user_id).values(reviewed_by_user_id=None)
    )
    await db.execute(
        delete(ResourceChangeRequest).where(ResourceChangeRequest.user_id == user_id, ResourceChangeRequest.status == "pending")
    )
    await db.execute(update(ResourceChangeRequest).where(ResourceChangeRequest.user_id == user_id).values(user_id=None))
    await db.execute(
        update(ResourceChangeRequest).where(ResourceChangeRequest.reviewed_by_user_id == user_id).values(reviewed_by_user_id=None)
    )
    await db.execute(update(ProviderMembership).where(ProviderMembership.verified_by_user_id == user_id).values(verified_by_user_id=None))
    await db.execute(update(ResourceChangeLog).where(ResourceChangeLog.actor_user_id == user_id).values(actor_user_id=None))
    await db.execute(update(ResourceChangeLog).where(ResourceChangeLog.reverted_by_user_id == user_id).values(reverted_by_user_id=None))


# ---- inquiry limit -----------------------------------------------------------------


def ip_hash(ip: str | None) -> str | None:
    """Salted one-way hash, same reasoning as the survey's: enough to count
    one connection's inquiries, never the address itself."""
    if not ip:
        return None
    salt = os.getenv("JWT_SECRET", "schoolz-localz-salt")
    return hashlib.sha256(f"{salt}:localz-inquiry:{ip}".encode()).hexdigest()
