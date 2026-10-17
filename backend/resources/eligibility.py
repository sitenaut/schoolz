"""Turning a listing's "who can come" sentence into criteria Localz can match.

NJ 211 publishes eligibility as free text ("Open to seniors aged 60 and
over who reside in the service area"). The "What fits me?" sheet needs it
structured, so each distinct sentence is read once by Claude (Haiku, a
forced tool call, `item.get(...)` everywhere since a schema isn't enforced)
and stored in `resource_eligibility` keyed on the normalized text. About
1,500 distinct sentences cover ~2,200 listings; the commonest ones ("Open to
the public", "Call for information") are recognized here without a call.

The vocabulary is closed and mirrored in frontend/src/lib/localzFit.ts,
which does the matching in the visitor's browser - their answers never reach
us. The verbatim sentence is always shown on the listing too, so a wrong
extraction is visible, never silent. Design: docs/LOCALZ_DESIGN.md,
"Eligibility check".
"""
from __future__ import annotations

import hashlib
import logging
import re
import time
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import observability
from models import ResourceEligibility, ResourceService
from scheduler import progress
from scheduler.errors import record_parse_issue
from services.tool_output import object_list, recover_spilled_input

logger = logging.getLogger(__name__)

# Bump when the prompt or vocabulary changes: every stored row below it is
# re-extracted on the next runs.
VERSION = 1
BATCH_SIZE = 25
MAX_TEXT_CHARS = 700
_JOB_KIND = "resources.refresh"

# Things a program can require of the person or household. The first five
# are asked in the sheet; the rest are shown but can't be checked (income
# isn't asked - the listings rarely give a number).
REQUIRES = (
    "veteran_military",
    "disability",
    "pregnant_or_new_baby",
    "uninsured",
    "job_loss",
    "families_with_children",
    "low_income",
    "homeless",
)
# Who a service is *for*, matched only against what a visitor chooses to
# look for - never a fact we ask about them.
FOCUS = ("women", "men", "lgbtq", "survivors")

_OPEN = re.compile(r"^(open to (the (general )?public|all|everyone|anyone)( in (the|our|its) service area)?|none|no restrictions?|anyone)$")
_VAGUE = re.compile(r"^(please )?call (for|to)( (more|specific))? (eligibility|program|more)?\s*(information|info|details)?$|^(eligibility )?varies( by program)?$")


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower()).rstrip(" .;:!")


def text_key(text: str | None) -> str | None:
    norm = normalize(text or "")
    return hashlib.sha256(norm.encode()).hexdigest() if norm else None


def empty_criteria() -> dict[str, Any]:
    return {
        "open_to_all": False,
        "vague": False,
        "age_min": None,
        "age_max": None,
        "child_age_min": None,
        "child_age_max": None,
        "requires": [],
        "focus": [],
        # Any one stated condition is enough, not all of them.
        "either": False,
        "asks_immigration_status": False,
        "other": None,
    }


def quick_criteria(text: str) -> dict | None:
    """Criteria for the stock phrases, without a model call."""
    norm = normalize(text)
    if _OPEN.match(norm):
        return {**empty_criteria(), "open_to_all": True}
    if _VAGUE.match(norm):
        return {**empty_criteria(), "vague": True}
    return None


def _age(value: Any) -> int | None:
    try:
        age = int(value)
    except (TypeError, ValueError):
        return None
    return age if 0 <= age <= 120 else None


def clean_criteria(raw: dict) -> dict:
    """The model's answer, held to the vocabulary: unknown keys dropped,
    ages in range, enums filtered."""
    out = empty_criteria()
    out["open_to_all"] = raw.get("open_to_all") is True
    out["vague"] = raw.get("vague") is True
    out["asks_immigration_status"] = raw.get("asks_immigration_status") is True
    out["either"] = raw.get("either") is True
    for key in ("age_min", "age_max", "child_age_min", "child_age_max"):
        out[key] = _age(raw.get(key))
    for lo, hi in (("age_min", "age_max"), ("child_age_min", "child_age_max")):
        if out[lo] is not None and out[hi] is not None and out[lo] > out[hi]:
            out[lo], out[hi] = out[hi], out[lo]
    requires = raw.get("requires")
    out["requires"] = sorted({r for r in requires if r in REQUIRES}) if isinstance(requires, list) else []
    focus = raw.get("focus")
    out["focus"] = sorted({f for f in focus if f in FOCUS}) if isinstance(focus, list) else []
    other = raw.get("other")
    out["other"] = other.strip()[:120] if isinstance(other, str) and other.strip() else None
    # A ceiling of 59 or less, or a floor of 60, already says it; don't also
    # call a children's program "open to all".
    if any(out[k] is not None for k in ("age_min", "age_max", "child_age_min", "child_age_max")) or out["requires"] or out["focus"] or out["other"]:
        out["open_to_all"] = False
    return out


_SYSTEM = """You read the "who can use this" sentence of community-service listings in New Jersey (from NJ 211) and record who each one is for, using only the fields given. Be literal: record a restriction only if the sentence states it.

Fields:
- open_to_all: true if anyone may use it, including anyone who simply wants what the service offers ("Open to the public", "Open to anyone in the service area", "Anyone seeking HIV information", "Anyone affected by cancer", "Anyone struggling with substance use"). Living in the service area is never a restriction.
- vague: true only if the sentence gives no usable rule ("Call for information", "Eligibility varies by program", "Contact the intake unit").
- age_min / age_max: ages of the person served, when stated ("seniors 60 and over" -> age_min 60; "youth ages 16 to 18" -> 16, 18; "adults" -> age_min 18; "children" with no ages -> age_max 17; "elderly" -> age_min 60). School grades: grade N is about age N+5 ("grades 6 - 10" -> 11, 15).
- child_age_min / child_age_max: for programs that serve a parent or family because of a child of a certain age ("parents of children under 5" -> child_age_max 4; "families with children 0-3" -> 0, 3). Not for programs that serve the children themselves - use age_min/age_max for those.
- requires: conditions the person or household must meet, from this list only: veteran_military (veterans, service members, military families), disability (a physical, intellectual, developmental or mental-health disability), pregnant_or_new_baby (pregnant, or a baby under 1), uninsured (no or not enough health insurance), job_loss (unemployed, laid off, lost hours), families_with_children (must have a child in the home and nothing above says so already - never alongside pregnant_or_new_baby or child ages), low_income (low income, income limits, receives SNAP/Medicaid/SSI), homeless (homeless or at risk of losing housing).
- focus: groups the service is specifically for, from this list only: women (women, girls), men (men, boys), lgbtq, survivors (of domestic violence, sexual assault or trafficking). Pregnant, postpartum or breastfeeding people are pregnant_or_new_baby, never focus women.
- either: true when the sentence lists ALTERNATIVE groups and belonging to any one is enough ("seniors 60+ or adults with disabilities", "elderly and/or disabled", "veterans, seniors and people with disabilities"). false when every stated condition must hold ("veterans who are homeless", "women 18 and older"). either never replaces the other fields: still record each group ("seniors, people with disabilities and veterans" -> age_min 60, requires disability and veteran_military, either true).
- asks_immigration_status: true only if it requires citizenship, legal residency, a Social Security number, or a particular immigration status. A service FOR immigrants or refugees does not ask - false.
- other: a gating requirement not covered above, in a few plain words: a referral, an agency's approval, enrollment in a particular program or school, a diagnosis needed to qualify, a court case, membership ("court referral", "DDD referral", "autism diagnosis", "married at least 2 years"). Do NOT list the need or situation the service itself is about (a cancer group's cancer, a recovery program's substance use, foreclosure help's foreclosure, a breastfeeding group's breastfeeding) or where someone lives. null if none.

Return one entry per numbered sentence, with its number in n."""

_TOOL = {
    "name": "record_eligibility",
    "description": "Record who each numbered sentence says the service is for.",
    "input_schema": {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "n": {"type": "integer"},
                        "open_to_all": {"type": "boolean"},
                        "vague": {"type": "boolean"},
                        "age_min": {"type": ["integer", "null"]},
                        "age_max": {"type": ["integer", "null"]},
                        "child_age_min": {"type": ["integer", "null"]},
                        "child_age_max": {"type": ["integer", "null"]},
                        "requires": {"type": "array", "items": {"type": "string", "enum": list(REQUIRES)}},
                        "focus": {"type": "array", "items": {"type": "string", "enum": list(FOCUS)}},
                        "either": {"type": "boolean"},
                        "asks_immigration_status": {"type": "boolean"},
                        "other": {"type": ["string", "null"]},
                    },
                    "required": ["n"],
                },
            }
        },
        "required": ["items"],
    },
}


def _client():
    from anthropic import AsyncAnthropic

    from services.content_extractor import ANTHROPIC_API_KEY

    return AsyncAnthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None


async def _extract_batch(client: Any, model: str, texts: list[str]) -> dict[int, dict]:
    prompt = "\n".join(f"{i}. {t[:MAX_TEXT_CHARS]}" for i, t in enumerate(texts, start=1))
    started = time.perf_counter()
    response = await client.messages.create(
        model=model,
        max_tokens=8192,
        extra_body={"temperature": 0},
        system=_SYSTEM,
        tools=[_TOOL],
        tool_choice={"type": "tool", "name": "record_eligibility"},
        messages=[{"role": "user", "content": prompt}],
    )
    observability.record_llm_call("resource_eligibility", model, response, time.perf_counter() - started)
    if response.stop_reason == "max_tokens":
        record_parse_issue(_JOB_KIND, "llm_max_tokens")
    tool_use = next((b for b in response.content if getattr(b, "type", None) == "tool_use"), None)
    if tool_use is None:
        return {}
    items, dropped = object_list(recover_spilled_input(tool_use.input).get("items"))
    if dropped:
        record_parse_issue(_JOB_KIND, "unexpected_format", sample=str(dropped)[:200])
    out: dict[int, dict] = {}
    for item in items:
        try:
            n = int(item.get("n"))
        except (TypeError, ValueError):
            continue
        if 1 <= n <= len(texts):
            out[n] = clean_criteria(item)
    return out


async def extract_pending(
    db: AsyncSession, limit: int = 1500, client: Any = None, model: str | None = None, summary: dict | None = None
) -> dict:
    """Extract criteria for active listings' sentences that have none at the
    current VERSION, up to `limit` sentences. Counts go into `summary` (the
    job's own, so progress checkpoints keep the crawl's numbers too).
    `client` is for tests."""
    summary = summary if summary is not None else {}
    summary.update({"eligibility_pending": 0, "eligibility_quick": 0, "eligibility_extracted": 0, "eligibility_errors": []})
    texts = (
        await db.execute(
            select(ResourceService.eligibility_text)
            .where(ResourceService.status == "active", ResourceService.eligibility_text.is_not(None))
            .distinct()
        )
    ).scalars().all()
    by_key: dict[str, str] = {}
    for text in texts:
        key = text_key(text)
        if key and key not in by_key:
            by_key[key] = text
    done = set(
        (await db.execute(select(ResourceEligibility.text_key).where(ResourceEligibility.version >= VERSION))).scalars()
    )
    pending = [(k, t) for k, t in by_key.items() if k not in done][:limit]
    summary["eligibility_pending"] = len(pending)
    if not pending:
        return summary

    now = datetime.now(UTC)
    needs_model: list[tuple[str, str]] = []
    for key, text in pending:
        quick = quick_criteria(text)
        if quick is None:
            needs_model.append((key, text))
            continue
        await db.merge(ResourceEligibility(text_key=key, text=text, criteria=quick, version=VERSION, model=None, extracted_at=now))
        summary["eligibility_quick"] += 1
    await db.commit()

    if not needs_model:
        return summary
    if client is None:
        client = _client()
        if client is None:
            summary["eligibility_errors"].append("no ANTHROPIC_API_KEY: skipped the model pass")
            return summary
    if model is None:
        from services.content_extractor import MODEL as model
    for start in range(0, len(needs_model), BATCH_SIZE):
        batch = needs_model[start : start + BATCH_SIZE]
        try:
            results = await _extract_batch(client, model, [t for _, t in batch])
        except Exception as exc:  # noqa: BLE001 - keep what earlier batches saved
            summary["eligibility_errors"].append(f"{type(exc).__name__}: {exc}"[:300])
            logger.warning("resource_eligibility_failed", extra={"error": str(exc)[:300]})
            break
        now = datetime.now(UTC)
        for n, (key, text) in enumerate(batch, start=1):
            criteria = results.get(n)
            if criteria is None:
                continue  # left pending; the next run retries it
            await db.merge(ResourceEligibility(text_key=key, text=text, criteria=criteria, version=VERSION, model=model, extracted_at=now))
            summary["eligibility_extracted"] += 1
        await db.commit()
        await progress.checkpoint(summary)
    return summary


async def criteria_for(db: AsyncSession, rows: list[ResourceService]) -> dict[str, dict]:
    """service id -> its criteria, for the rows that have any yet."""
    keys = {row.id: text_key(row.eligibility_text) for row in rows}
    wanted = {k for k in keys.values() if k}
    if not wanted:
        return {}
    found = dict(
        (await db.execute(select(ResourceEligibility.text_key, ResourceEligibility.criteria).where(ResourceEligibility.text_key.in_(wanted)))).all()
    )
    return {rid: found[k] for rid, k in keys.items() if k in found}
