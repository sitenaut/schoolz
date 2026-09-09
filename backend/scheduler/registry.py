from dataclasses import dataclass, field
from typing import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

JobHandler = Callable[[AsyncSession, dict], Awaitable["str | None"]]


@dataclass
class JobSpec:
    kind: str
    handler: JobHandler
    default_name: str
    default_cron: str
    description: str
    default_timezone: str = "America/New_York"
    default_params: dict = field(default_factory=dict)
    param_schema: dict | None = None


registry: dict[str, JobSpec] = {}


def register_job(
    *,
    kind: str,
    default_name: str,
    default_cron: str,
    description: str,
    default_timezone: str = "America/New_York",
    default_params: dict | None = None,
    param_schema: dict | None = None,
):
    def decorator(handler: JobHandler) -> JobHandler:
        registry[kind] = JobSpec(
            kind=kind,
            handler=handler,
            default_name=default_name,
            default_cron=default_cron,
            default_timezone=default_timezone,
            description=description,
            default_params=default_params or {},
            param_schema=param_schema,
        )
        return handler

    return decorator
