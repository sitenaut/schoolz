from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class RawEvent(BaseModel):
    """A single event as returned by a source adapter, pre-normalization."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    source: str
    source_event_id: str
    title: str
    description: str | None = None
    start_time: datetime
    end_time: datetime | None = None
    all_day: bool = False
    venue_name: str | None = None
    venue_address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    url: str | None = None
    image_url: str | None = None
    price_min: float | None = None
    price_max: float | None = None
    is_free: bool | None = None
    default_categories: list[str] = []
    raw: dict[str, Any] = {}


class Source(ABC):
    """Adapter interface. Each source produces a list of RawEvent."""

    name: str
    # Parts of a multi-feed source (e.g. one Google Calendar of several) that
    # failed while the rest fetched fine - set by fetch(), surfaced by the
    # pipeline as a partial failure so the run still goes WARNING.
    partial_failures: list[str] = []

    @abstractmethod
    async def fetch(self) -> list[RawEvent]:  # pragma: no cover — abstract
        ...
