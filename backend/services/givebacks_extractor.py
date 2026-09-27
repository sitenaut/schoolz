"""Turns newly-scanned GivebacksBlock rows into SchoolContentItem rows -
the same shape of problem content_extractor.py already solved for Smore
newsletters (a vision pass over image blocks, then one structured
text-extraction call), adapted for a PTA's own multi-page Givebacks site
instead of one newsletter issue. Deliberately a separate module rather than
a change to extract_from_newsletter: that function's writes are wired to
Smore's own FKs (newsletter_id/source_block_id) closely enough that
reusing it via duck-typing would need more special-casing than just having
two callers share the pure helpers underneath.

Explicit product requirement: PTAs reuse stale flyer artwork just like
schools do (CLAUDE.md documents a real PTA flyer reading "SEPTEMBER 24,
2025" during Sept 2026), so this reuses content_extractor.py's stale-year
rollforward and stale-supersede guard rather than reinventing them."""

import logging
import time

from anthropic import AsyncAnthropic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import observability
from models import GivebacksBlock, School, SchoolContentItem
from scheduler.errors import record_parse_issue
from services.content_extractor import (
    _EXTRACTION_TOOL,
    _SYSTEM_PROMPT,
    ANTHROPIC_API_KEY,
    MODEL,
    _correct_stale_year,
    _may_supersede,
    _parse_date,
    _title_dedup_key,
    _vision_extract,
)
from services.links import unwrap_redirect
from services.tool_output import object_list, recover_spilled_input

logger = logging.getLogger(__name__)

_JOB_KIND = "givebacks.scan"


def _count_items_per_block_position(items: list[dict]) -> dict[int, int]:
    counts: dict[int, int] = {}
    for item in items:
        pos = item.get("source_block_position")
        counts[pos] = counts.get(pos, 0) + 1
    return counts


async def extract_from_pta_page(
    db: AsyncSession, school: School, new_blocks: list[GivebacksBlock], image_bytes_by_block_id: dict[str, bytes]
) -> str:
    """image_bytes_by_block_id carries the decoded bytes for a legacy-format
    image block (GivebacksBlock.image_url is null for those - see
    services/givebacks.py's module docstring for why there's nothing to
    fetch later), keyed by the block's own id since it's only available for
    this one run."""
    if not ANTHROPIC_API_KEY:
        return "skipped - ANTHROPIC_API_KEY not configured"
    if not new_blocks:
        return "no new blocks to extract from"

    client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

    vision_failures = 0
    for block in new_blocks:
        if block.block_type == "image" and block.pending_vision_extraction:
            text = await _vision_extract(
                client, block.image_url, image_bytes=image_bytes_by_block_id.get(block.id), job_kind=_JOB_KIND
            )
            if text is None:
                vision_failures += 1
                continue
            block.vision_extracted_text = text
            block.pending_vision_extraction = False
    await db.flush()

    def _corpus_line(block: GivebacksBlock) -> str | None:
        text = block.text_content or block.vision_extracted_text
        link_suffix = f" (link: {block.link_url})" if block.link_url else ""
        if text:
            return f"[page {block.page_path}, block {block.position}, {block.block_type}] {text}{link_suffix}"
        if block.link_url:
            return f"[page {block.page_path}, block {block.position}, link] {block.link_url}"
        return None

    vision_note = (
        f"WARNING[image_unsupported]: {vision_failures} image block(s) failed vision extraction (left pending) · "
        if vision_failures
        else ""
    )
    extractable_blocks = [b for b in new_blocks if _corpus_line(b) is not None]
    if not extractable_blocks:
        return f"{vision_note}no extractable text in new blocks"

    created = 0
    skipped_dupes = 0
    truncated_chunks = 0

    _CHUNK_SIZE = 12
    for chunk_start in range(0, len(extractable_blocks), _CHUNK_SIZE):
        chunk = extractable_blocks[chunk_start : chunk_start + _CHUNK_SIZE]
        corpus_lines = [line for b in chunk if (line := _corpus_line(b)) is not None]

        current = (
            await db.execute(
                select(SchoolContentItem).where(
                    SchoolContentItem.school_id == school.id,
                    SchoolContentItem.source == "givebacks_pta",
                    SchoolContentItem.is_current.is_(True),
                )
            )
        ).scalars().all()
        current_items_context = ""
        if current:
            lines = [f"- id={i.id} [{i.category}] {i.title} (start_date={i.start_date})" for i in current]
            current_items_context = "\n\nCURRENT ITEMS for this school's PTA page (reference by id in supersedes_item_id if one of these is being corrected/updated):\n" + "\n".join(lines)

        _llm_started = time.perf_counter()
        response = await client.messages.create(
            model=MODEL,
            max_tokens=8192,
            temperature=0,
            system=_SYSTEM_PROMPT,
            tools=[_EXTRACTION_TOOL],
            tool_choice={"type": "tool", "name": "record_extraction"},
            messages=[{"role": "user", "content": "\n".join(corpus_lines) + current_items_context}],
        )
        observability.record_llm_call("content_extract", MODEL, response, time.perf_counter() - _llm_started)
        tool_use = next((b for b in response.content if b.type == "tool_use"), None)
        if not tool_use:
            continue
        data = recover_spilled_input(tool_use.input)
        if response.stop_reason == "max_tokens":
            truncated_chunks += 1
            logger.warning("givebacks_extraction_chunk_truncated", extra={"school_id": school.id, "usage": str(response.usage)})
            record_parse_issue(_JOB_KIND, "llm_max_tokens", school_id=school.id)

        block_by_position = {b.position: b for b in chunk}
        items, dropped = object_list(data.get("items"))
        if dropped:
            record_parse_issue(_JOB_KIND, "unexpected_format", school_id=school.id, sample=str(dropped)[:200])
        items_per_position = _count_items_per_block_position(items)
        for item in items:
            source_block = block_by_position.get(item.get("source_block_position"))
            is_all_day = "T" not in (item.get("start_date") or "")
            # A PTA page's own block is unambiguously about the item(s)
            # pulled from it far more often than a newsletter's - a whole
            # page is usually one flyer or one topic - but the same "don't
            # spray one passing link onto every item from a busy block"
            # caution from content_extractor.py still applies when a page
            # genuinely lists several unrelated dated things.
            fallback_link = source_block.link_url if source_block and items_per_position.get(item.get("source_block_position")) == 1 else None
            link_url = unwrap_redirect(item.get("link_url") or fallback_link)

            item_start_date = _correct_stale_year(_parse_date(item.get("start_date"), job_kind=_JOB_KIND), job_kind=_JOB_KIND, school_id=school.id)
            item_end_date = _correct_stale_year(_parse_date(item.get("end_date"), job_kind=_JOB_KIND), job_kind=_JOB_KIND, school_id=school.id)

            new_title = item["title"][:300]
            existing_row = next(
                (
                    c
                    for c in current
                    if c.category == item["category"]
                    and c.start_date == item_start_date
                    and _title_dedup_key(c.title) == _title_dedup_key(new_title)
                ),
                None,
            )
            if existing_row is not None:
                description = (item.get("description") or "").strip()
                if description and not (existing_row.description or "").strip():
                    existing_row.description = description
                if link_url and not existing_row.link_url:
                    existing_row.link_url = link_url
                skipped_dupes += 1
                continue

            new_item = SchoolContentItem(
                scope="school",
                school_id=school.id,
                source="givebacks_pta",
                category=item["category"],
                title=new_title,
                description=item.get("description"),
                start_date=item_start_date,
                end_date=item_end_date,
                is_all_day=is_all_day,
                link_url=link_url,
                person_name=item.get("person_name"),
                person_title=item.get("person_title"),
                source_excerpt=item.get("source_excerpt"),
            )
            db.add(new_item)
            await db.flush()
            created += 1
            current.append(new_item)

            supersedes_id = item.get("supersedes_item_id")
            if supersedes_id:
                old = (await db.execute(select(SchoolContentItem).where(SchoolContentItem.id == supersedes_id))).scalar_one_or_none()
                if old and old.id != new_item.id and _may_supersede(old, new_item, job_kind=_JOB_KIND):
                    old.is_current = False
                    old.superseded_by_id = new_item.id

    dupe_note = f", {skipped_dupes} duplicate item(s) already covered" if skipped_dupes else ""
    total_chunks = -(-len(extractable_blocks) // _CHUNK_SIZE)
    if truncated_chunks:
        truncated_note = f"WARNING[llm_max_tokens]: {truncated_chunks} of {total_chunks} extraction batch(es) hit max_tokens (some items may be missing) · "
    else:
        truncated_note = ""
    return f"{truncated_note}{vision_note}extracted {created} item(s){dupe_note}"
