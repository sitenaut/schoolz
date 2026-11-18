// A Backpack Capture export, split into requests the API will take. It
// refuses an import over 4 MB before reading it (backend/import_size_limit.py)
// because one big request ran the API machine out of memory; a batch stays
// well under that. Oldest first, as the extension sends them, so each page's
// newest copy is the one applied last.
import type { ImportResult } from "../types";

export const BATCH_CHARS = 1_000_000;
export const BATCH_PAGES = 40;

type Capture = { captured_at?: unknown; reduced_text?: unknown };

const textLength = (c: Capture) => (typeof c.reduced_text === "string" ? c.reduced_text.length : 0);
const capturedAt = (c: Capture) => (typeof c.captured_at === "string" ? c.captured_at : "");

export function importBatches<T extends Capture>(captures: T[], maxChars = BATCH_CHARS, maxPages = BATCH_PAGES): T[][] {
  const sorted = [...captures].sort((a, b) => (capturedAt(a) < capturedAt(b) ? -1 : capturedAt(a) > capturedAt(b) ? 1 : 0));
  const batches: T[][] = [];
  let batch: T[] = [];
  let chars = 0;
  for (const capture of sorted) {
    const size = textLength(capture);
    if (batch.length && (batch.length >= maxPages || chars + size > maxChars)) {
      batches.push(batch);
      batch = [];
      chars = 0;
    }
    batch.push(capture);
    chars += size;
  }
  if (batch.length) batches.push(batch);
  return batches;
}

/** Several batches' results as one import's. */
export function sumResults(results: ImportResult[]): ImportResult {
  return results.reduce<ImportResult>(
    (sum, r) => ({
      captures_processed: sum.captures_processed + r.captures_processed,
      captures_skipped_duplicate: sum.captures_skipped_duplicate + r.captures_skipped_duplicate,
      schedule_blocks_upserted: sum.schedule_blocks_upserted + r.schedule_blocks_upserted,
      work_items_upserted: sum.work_items_upserted + r.work_items_upserted,
      grade_entries_upserted: sum.grade_entries_upserted + r.grade_entries_upserted,
      page_kinds_seen: Math.max(sum.page_kinds_seen, r.page_kinds_seen),
      identity_mismatches: [...sum.identity_mismatches, ...r.identity_mismatches],
    }),
    {
      captures_processed: 0,
      captures_skipped_duplicate: 0,
      schedule_blocks_upserted: 0,
      work_items_upserted: 0,
      grade_entries_upserted: 0,
      page_kinds_seen: 0,
      identity_mismatches: [],
    },
  );
}
