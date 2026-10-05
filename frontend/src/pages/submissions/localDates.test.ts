import { describe, expect, it } from "vitest";
import { formatWhen, joinLocal, splitLocal } from "./localDates";

describe("submission item dates", () => {
  it("formats the flyer's shapes", () => {
    expect(formatWhen("2026-10-14T17:00:00", "2026-10-14T22:00:00")).toBe("Wed Oct 14 · 5–10 pm");
    expect(formatWhen("2026-12-05T11:00:00", "2026-12-05T15:00:00")).toBe("Sat Dec 5 · 11 am–3 pm");
    expect(formatWhen("2026-10-23T18:30:00", null)).toBe("Fri Oct 23 · 6:30 pm");
    expect(formatWhen("2026-11-01", null)).toBe("Sun Nov 1");
    expect(formatWhen("2026-12-23", "2027-01-01")).toBe("Wed Dec 23 – Fri Jan 1");
    expect(formatWhen(null, null)).toBe("No date");
  });

  it("round-trips through the edit form", () => {
    for (const [start, end] of [
      ["2026-10-14T17:00:00", "2026-10-14T22:00:00"],
      ["2026-10-23T18:30:00", ""],
      ["2026-11-01", ""],
      ["2026-12-23", "2027-01-01"],
    ]) {
      expect(joinLocal(splitLocal(start, end || null))).toEqual({ start_local: start, end_local: end });
    }
  });

  it("clears both when the date is removed", () => {
    expect(joinLocal({ date: "", time: "17:00", endDate: "", endTime: "22:00" })).toEqual({ start_local: "", end_local: "" });
  });
});
