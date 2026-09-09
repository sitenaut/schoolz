from dataclasses import dataclass
from typing import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from models import EmailScanner, EmailScannerMatch


@dataclass
class ProcessorResult:
    status: str  # "ok" | "skipped" | "error"
    artifact_kind: str | None = None
    artifact_id: str | None = None
    note: str | None = None


ProcessorFn = Callable[[AsyncSession, EmailScanner, EmailScannerMatch, dict], Awaitable[ProcessorResult]]
FinalizeFn = Callable[[AsyncSession, EmailScanner, int], Awaitable[None]]


@dataclass
class PurposeSpec:
    purpose: str
    process: ProcessorFn
    finalize: FinalizeFn | None = None


registry: dict[str, PurposeSpec] = {}


def register_processor(purpose: str, *, finalize: FinalizeFn | None = None):
    def decorator(process: ProcessorFn) -> ProcessorFn:
        registry[purpose] = PurposeSpec(purpose=purpose, process=process, finalize=finalize)
        return process

    return decorator


def get_processor(purpose: str) -> PurposeSpec | None:
    return registry.get(purpose)


from . import school_email  # noqa: E402,F401  (registers "school_email")
