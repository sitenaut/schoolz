import { describe, expect, it } from "vitest";
import { itemDateKeys } from "./calendar";

describe("itemDateKeys", () => {
  it("real case: a multi-day all-day closure covers every day, not just start_date", () => {
    // "SCHOOLS CLOSED - NJEA Convention", stored as start=2026-11-05,
    // end=2026-11-07 (ICS all-day convention: end is exclusive, one day
    // past the last actual day) - covers Nov 5 and Nov 6.
    const keys = itemDateKeys({
      start_date: "2026-11-05T05:00:00Z",
      end_date: "2026-11-07T05:00:00Z",
      is_all_day: true,
    });
    expect(keys).toEqual(["2026-11-05", "2026-11-06"]);
  });

  it("a single-day all-day item returns just that day", () => {
    const keys = itemDateKeys({ start_date: "2026-09-07T04:00:00Z", end_date: null, is_all_day: true });
    expect(keys).toEqual(["2026-09-07"]);
  });

  it("no end_date at all returns just start_date's day", () => {
    const keys = itemDateKeys({ start_date: "2026-09-22T22:30:00Z", is_all_day: false });
    expect(keys).toEqual(["2026-09-22"]);
  });

  it("a timed multi-day item treats end_date as inclusive of its day", () => {
    const keys = itemDateKeys({
      start_date: "2026-10-05T13:00:00Z",
      end_date: "2026-10-07T20:00:00Z",
      is_all_day: false,
    });
    expect(keys).toEqual(["2026-10-05", "2026-10-06", "2026-10-07"]);
  });

  it("no start_date returns no keys", () => {
    expect(itemDateKeys({ start_date: null })).toEqual([]);
  });
});
