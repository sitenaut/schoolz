import { describe, expect, it } from "vitest";
import type { ImportResult } from "../types";
import { importBatches, sumResults } from "./importBatches";

const page = (at: string, chars: number) => ({ captured_at: at, reduced_text: "x".repeat(chars), source_url: at });

describe("importBatches", () => {
  it("sends oldest first, whatever order the file lists them in", () => {
    const batches = importBatches([page("2026-11-03", 10), page("2026-11-01", 10), page("2026-11-02", 10)], 100, 2);
    expect(batches.map((b) => b.map((c) => c.captured_at))).toEqual([["2026-11-01", "2026-11-02"], ["2026-11-03"]]);
  });

  it("starts a new batch before the text would pass the limit", () => {
    const batches = importBatches([page("1", 60), page("2", 60), page("3", 30)], 100, 40);
    expect(batches.map((b) => b.length)).toEqual([1, 2]);
  });

  it("sends a page bigger than the limit on its own rather than dropping it", () => {
    const batches = importBatches([page("1", 10), page("2", 500), page("3", 10)], 100, 40);
    expect(batches.map((b) => b.length)).toEqual([1, 1, 1]);
  });

  it("has nothing to send for an empty file", () => {
    expect(importBatches([])).toEqual([]);
  });
});

describe("sumResults", () => {
  it("adds the counts and keeps every mismatch", () => {
    const r = (n: number, mismatch: string[]): ImportResult => ({
      captures_processed: n,
      captures_skipped_duplicate: 1,
      schedule_blocks_upserted: 0,
      work_items_upserted: n * 2,
      grade_entries_upserted: 1,
      page_kinds_seen: n,
      identity_mismatches: mismatch,
    });
    expect(sumResults([r(3, ["a"]), r(5, ["b"])])).toEqual({
      captures_processed: 8,
      captures_skipped_duplicate: 2,
      schedule_blocks_upserted: 0,
      work_items_upserted: 16,
      grade_entries_upserted: 2,
      page_kinds_seen: 5,
      identity_mismatches: ["a", "b"],
    });
  });
});
