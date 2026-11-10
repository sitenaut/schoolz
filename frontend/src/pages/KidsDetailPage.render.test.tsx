// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, within } from "@testing-library/react";

vi.mock("../api", () => ({ apiFetch: vi.fn() }));

import { GradesTab } from "./KidsDetailPage";

type Grades = NonNullable<Parameters<typeof GradesTab>[0]["grades"]>;
type Entry = Grades["entries"][number];

const entry = (over: Partial<Entry>): Entry => ({
  external_uid: over.title ?? "entry",
  course_code: "331",
  course_section: "10",
  course_name: "F: CHEM-1A 331-10",
  marking_period: "MP1",
  weekday_date: "Mon 11/9",
  title: "Lab",
  description: null,
  category: "Minor Assessments",
  score_earned: null,
  score_possible: null,
  percent: null,
  status: null,
  is_updated: false,
  ...over,
});

afterEach(cleanup);

describe("GradesTab", () => {
  it("files work under its marking period, newest period and due date first", () => {
    const grades: Grades = {
      course_grades: [
        {
          course_code: "331",
          course_section: "10",
          course_name: "F: CHEM-1A 331-10",
          marking_period: "MP1",
          grade_percent: 62,
          last_grade_posted: "11/6/26",
        },
      ],
      entries: [
        entry({ title: "Density Lab", weekday_date: "Fri 10/2", score_earned: 20, score_possible: 25, percent: 80 }),
        entry({ title: "Essay Revisions", weekday_date: "Mon 11/9", score_possible: 5 }),
        entry({ title: "Unit 4 Quiz", weekday_date: "Thu 11/12", marking_period: "MP2", score_possible: 20 }),
        entry({ title: "Summer Reading", weekday_date: "Tue 9/8", marking_period: null, status: "Exempt" }),
      ],
      marking_periods: [
        { label: "MP1", start_date: "2026-09-02", end_date: "2026-11-10" },
        { label: "MP2", start_date: "2026-11-11", end_date: "2027-01-27" },
      ],
      marking_period_discrepancies: [],
    };
    const { container } = render(<GradesTab grades={grades} />);
    const sections = [...container.querySelectorAll("section")];
    expect(sections.map((s) => s.querySelector(".section-title")?.textContent)).toEqual([
      "MP2 · 2026-11-11 – 2027-01-27",
      "MP1 · 2026-09-02 – 2026-11-10",
      "No marking period",
    ]);
    const [mp2, mp1] = sections;
    expect([...mp1.querySelectorAll(".item-title")].map((t) => t.textContent)).toEqual(["Essay Revisions", "Density Lab"]);
    // Listed by Genesis, nothing graded yet.
    expect(within(mp1).getByText("Not graded yet · 5 pts")).toBeTruthy();
    expect(within(mp1).getByText("62%")).toBeTruthy();
    expect(within(mp2).queryByRole("table")).toBeNull();
    expect(within(mp2).getByText("Not graded yet · 20 pts")).toBeTruthy();
  });
});
