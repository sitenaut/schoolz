from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import EmailScanner
from scheduler.registry import register_job
from services.email_scanner import run_scanner


@register_job(
    kind="email.scan",
    default_name="Email scan",
    default_cron="0 7 * * *",
    description="Runs one EmailScanner's Gmail query and dispatches new messages to its purpose's processor.",
    param_schema={"type": "object", "properties": {"scanner_id": {"type": "string"}}, "required": ["scanner_id"]},
)
async def run(db: AsyncSession, params: dict) -> str | None:
    scanner_id = params.get("scanner_id")
    if not scanner_id:
        return "no scanner_id in params - nothing to do"

    scanner = (await db.execute(select(EmailScanner).where(EmailScanner.id == scanner_id))).scalar_one_or_none()
    if not scanner:
        return f"scanner {scanner_id} no longer exists"
    if not scanner.enabled:
        return f"scanner {scanner_id} is disabled"

    return await run_scanner(db, scanner)
