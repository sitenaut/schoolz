from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import District, DistrictTransportation
from scheduler.registry import register_job
from services.transportation import discover_transportation


@register_job(
    kind="transportation.scan",
    default_name="Transportation department scan",
    # Regular public-source cadence - the source is static policy/contact
    # pages with no realtime delay feed (checked), so nothing to gain
    # from polling faster.
    default_cron="0 */12 * * *",
    description="Parses the district's transportation department pages: office contacts, late buses, delay policy, bus stop changes, lost items.",
    param_schema={"type": "object", "properties": {"district_id": {"type": "string"}}, "required": ["district_id"]},
)
async def run(db: AsyncSession, params: dict) -> str | None:
    district_id = params.get("district_id")
    district = (await db.execute(select(District).where(District.id == district_id))).scalar_one_or_none() if district_id else None
    if not district:
        return f"district {district_id} no longer exists"
    if not district.transportation_url:
        return "district has no transportation_url configured"

    parsed = urlparse(district.transportation_url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    info = await discover_transportation(district.transportation_url, base_url)

    row = (await db.execute(select(DistrictTransportation).where(DistrictTransportation.district_id == district.id))).scalar_one_or_none()
    created = row is None
    if created:
        row = DistrictTransportation(district_id=district.id)
        db.add(row)
    for field, value in info.items():
        setattr(row, field, value)

    missing = [k for k in ("office_phone", "delay_policy", "late_bus_contractors") if not info.get(k)]
    if missing:
        return f"WARNING: parsed the department pages but found no {', '.join(missing)}"
    return f"transportation: {'created' if created else 'updated'} - {len(info['contacts'])} contacts, {len(info['late_bus_contractors'])} late-bus contractors, office {info['office_phone']}"
