"""The Localz saved services profile: what can be saved, the consent
purposes, and the current policy version. Design: docs/LOCALZ_DESIGN.md,
"Saved profile".

The vocabulary is exactly what the eligibility sheet asks
(frontend/src/lib/localzFit.ts; a frontend test reads this file to keep them
equal). Anything else is refused, so the profile can never become a place
to keep free text, a status or an identity.

Nothing here logs. The profile's fields and values must never reach a log
record (a test runs every route and checks).
"""
from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Bump when what's saved, or what the consent screen says, changes: every
# grant under an older version stops counting and the person is asked again.
POLICY_VERSION = 1

PURPOSE_PROFILE = "services_profile"
PURPOSE_ALERTS = "services_alerts"
PURPOSE_ALERTS_NAMED = "services_alerts_named"
PURPOSES = (PURPOSE_PROFILE, PURPOSE_ALERTS, PURPOSE_ALERTS_NAMED)
# Alerts aren't built (no outbound email yet), so only the profile can be
# granted today.
GRANTABLE = (PURPOSE_PROFILE,)

AGE_BANDS = ("u1", "1-4", "5-12", "13-17", "18-59", "60+")
NEEDS = ("veteran_military", "disability", "pregnant_or_new_baby", "uninsured", "job_loss")
FOCUS = ("women", "men", "lgbtq", "survivors")

AgeBand = Literal["u1", "1-4", "5-12", "13-17", "18-59", "60+"]
Need = Literal["veteran_military", "disability", "pregnant_or_new_baby", "uninsured", "job_loss"]
Focus = Literal["women", "men", "lgbtq", "survivors"]

# Far above the largest valid profile (every chip ticked is ~200 bytes).
MAX_STORED_BYTES = 1024


def _unique(values: list) -> list:
    if len(set(values)) != len(values):
        raise ValueError("each value at most once")
    return values


class SavedAnswers(BaseModel):
    """The sheet's answers. Unknown keys are refused."""

    model_config = ConfigDict(extra="forbid")

    ages: list[AgeBand] = Field(default_factory=list, max_length=len(AGE_BANDS))
    has: list[Need] = Field(default_factory=list, max_length=len(NEEDS))
    focus: list[Focus] = Field(default_factory=list, max_length=len(FOCUS))
    noStatusFirst: bool = False  # noqa: N815 - the sheet's own key

    @field_validator("ages", "has", "focus")
    @classmethod
    def _no_repeats(cls, v: list) -> list:
        return _unique(v)

    def is_empty(self) -> bool:
        return not (self.ages or self.has or self.focus or self.noStatusFirst)

    def dumps(self) -> str:
        out = json.dumps(self.model_dump(), separators=(",", ":"), sort_keys=True)
        if len(out.encode()) > MAX_STORED_BYTES:
            raise ValueError("profile too large")
        return out


def loads(stored: str) -> SavedAnswers:
    return SavedAnswers.model_validate_json(stored)
