import { describe, expect, it } from "vitest";
import { describeCron } from "./cron";

describe("describeCron", () => {
  it("glosses the schedules the app actually uses", () => {
    expect(describeCron("0 */12 * * *")).toBe("Every 12 hours at :00");
    expect(describeCron("0 7 * * *")).toBe("Daily at 7:00 AM");
    expect(describeCron("0 8 * * 1")).toBe("Weekly on Monday at 8:00 AM");
    expect(describeCron("0 18 * * 0")).toBe("Weekly on Sunday at 6:00 PM");
    expect(describeCron("0 7 * * 1-5")).toBe("Weekdays at 7:00 AM");
    expect(describeCron("*/10 * * * *")).toBe("Every 10 minutes");
    expect(describeCron("30 * * * *")).toBe("Every hour at :30");
    expect(describeCron("0 9 1 * *")).toBe("Monthly on the 1st at 9:00 AM");
    expect(describeCron("15 14 * * mon,wed")).toBe("Mon, Wed at 2:15 PM");
  });

  it("glosses the biweekly and monthly day lists the per-school scans use", () => {
    expect(describeCron("12 3 3,17 * *")).toBe("Twice a month, the 3rd and 17th, at 3:12 AM");
    expect(describeCron("40 23 12,26 * *")).toBe("Twice a month, the 12th and 26th, at 11:40 PM");
    expect(describeCron("5 4 21 * *")).toBe("Monthly on the 21st at 4:05 AM");
    expect(describeCron("5 4 22 * *")).toBe("Monthly on the 22nd at 4:05 AM");
    expect(describeCron("5 4 11 * *")).toBe("Monthly on the 11th at 4:05 AM");
  });

  it("falls back to the raw expression for anything it doesn't recognize", () => {
    expect(describeCron("0 0 1 1 *")).toBe("0 0 1 1 *");
    expect(describeCron("nonsense")).toBe("nonsense");
  });
});
