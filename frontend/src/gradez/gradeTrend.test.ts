import { describe, expect, it } from "vitest";
import { genesisIsoDate, gradeTrend, lastGrade, weighsCategories } from "./gradeTrend";
import type { GradeEntry } from "./types";

let uid = 0;
const entry = (over: Partial<GradeEntry>): GradeEntry => ({
  external_uid: `e${++uid}`,
  course_code: "210",
  course_section: "1",
  course_name: "GEOMETRY",
  marking_period: "MP2",
  weekday_date: "Mon 11/9",
  title: "Quiz",
  description: null,
  category: null,
  score_earned: null,
  score_possible: null,
  percent: null,
  status: null,
  is_updated: false,
  graded_at: null,
  ...over,
});

describe("genesisIsoDate", () => {
  it("puts fall dates in the school year's first calendar year", () => {
    expect(genesisIsoDate("Mon 11/9", "2026-11-17")).toBe("2026-11-09");
    expect(genesisIsoDate("Fri 1/8", "2026-11-17")).toBe("2027-01-08");
  });

  it("puts fall dates in the year before when today is spring", () => {
    expect(genesisIsoDate("Mon 11/9", "2027-03-02")).toBe("2026-11-09");
    expect(genesisIsoDate("Tue 3/2", "2027-03-02")).toBe("2027-03-02");
  });

  it("reads nothing from a date it can't parse", () => {
    expect(genesisIsoDate("soon", "2026-11-17")).toBeNull();
    expect(genesisIsoDate("Mon 13/9", "2026-11-17")).toBeNull();
  });
});

describe("gradeTrend", () => {
  const today = "2026-11-17";

  it("adds points up in date order, whatever order the entries arrive in", () => {
    const days = gradeTrend(
      [
        entry({ weekday_date: "Tue 11/10", score_earned: 5, score_possible: 10 }),
        entry({ weekday_date: "Mon 9/14", score_earned: 9, score_possible: 10 }),
      ],
      today,
    );
    expect(days.map((d) => d.date)).toEqual(["2026-09-14", "2026-11-10"]);
    expect(days.map((d) => d.grade)).toEqual([90, 70]);
    expect(days[1].marks[0].percent).toBe(50);
  });

  it("counts Missing as a zero and leaves Exempt out, as Genesis does", () => {
    // The real case: 25/25 graded plus a Missing 12-pointer is Genesis's 67.6%.
    const days = gradeTrend(
      [
        entry({ weekday_date: "Mon 9/14", score_earned: 25, score_possible: 25 }),
        entry({ weekday_date: "Tue 9/15", status: "Exempt", score_possible: 5 }),
        entry({ weekday_date: "Wed 9/16", status: "Missing", score_possible: 12 }),
      ],
      today,
    );
    expect(days).toHaveLength(2);
    expect(lastGrade(days)).toBeCloseTo(67.57, 2);
    expect(days[1].marks[0]).toMatchObject({ percent: 0, missing: true });
  });

  it("puts every mark of one day on that day, and the grade after all of them", () => {
    const days = gradeTrend(
      [
        entry({ weekday_date: "Mon 9/14", title: "Quiz 1", score_earned: 10, score_possible: 10 }),
        entry({ weekday_date: "Mon 9/14", title: "Exit Ticket", score_earned: 0, score_possible: 10 }),
      ],
      today,
    );
    expect(days).toHaveLength(1);
    expect(days[0].marks).toHaveLength(2);
    expect(days[0].grade).toBe(50);
  });

  it("skips work that isn't graded yet", () => {
    const days = gradeTrend([entry({ score_possible: 20 }), entry({ weekday_date: "Tue 11/10", score_earned: 8, score_possible: 10 })], today);
    expect(days.map((d) => d.date)).toEqual(["2026-11-10"]);
  });

  it("plots a percent-only mark without counting it toward points", () => {
    const days = gradeTrend([entry({ percent: 75 })], today);
    expect(days[0].marks[0].percent).toBe(75);
    expect(days[0].grade).toBeNull();
  });

  it("counts extra credit's points without plotting a percent of zero possible", () => {
    const days = gradeTrend(
      [
        entry({ weekday_date: "Mon 9/14", score_earned: 8, score_possible: 10 }),
        entry({ weekday_date: "Tue 9/15", score_earned: 2, score_possible: 0 }),
      ],
      today,
    );
    expect(days[1].marks).toEqual([]);
    expect(days[1].grade).toBe(100);
  });
});

describe("weighsCategories", () => {
  const days = gradeTrend([entry({ score_earned: 13, score_possible: 20 })], "2026-11-17");

  it("allows for Genesis's own rounding", () => {
    expect(weighsCategories(days, 65)).toBe(false);
    expect(weighsCategories(days, 65.9)).toBe(false);
  });

  it("flags a grade the points can't reach", () => {
    expect(weighsCategories(days, 80)).toBe(true);
  });

  it("says nothing without a Genesis grade", () => {
    expect(weighsCategories(days, null)).toBe(false);
  });
});
