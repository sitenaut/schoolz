"""Model answers kept in `page_extractions`, keyed by a hash of what was asked,
so the same question about the same file is never paid for twice (CLAUDE.md:
a model's answer is paid-for data). A read or write failure costs one model
call, never the scan."""

import hashlib
import json
import logging

import database
from models import PageExtraction

logger = logging.getLogger(__name__)


def file_key(kind: str, prompt: str, tool: dict, content: bytes) -> str:
    """The reader kind, its prompt, its tool schema and the file's bytes: a
    change to any of them is a new question."""
    tool_json = json.dumps(tool, sort_keys=True)
    return hashlib.sha256(f"{kind}\n{prompt}\n{tool_json}\n{hashlib.sha256(content).hexdigest()}".encode()).hexdigest()


async def stored(key: str) -> list | None:
    try:
        async with database.SessionLocal() as db:
            row = await db.get(PageExtraction, key)
            return list(row.items) if row else None
    except Exception:  # noqa: BLE001 - a cache miss costs one model call, never the scan
        logger.warning("page_extraction_cache_read_failed", exc_info=True)
        return None


async def store(key: str, items: list) -> None:
    try:
        async with database.SessionLocal() as db:
            await db.merge(PageExtraction(key=key, items=items))
            await db.commit()
    except Exception:  # noqa: BLE001
        logger.warning("page_extraction_cache_write_failed", exc_info=True)
