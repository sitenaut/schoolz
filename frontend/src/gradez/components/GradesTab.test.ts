import { describe, expect, it } from "vitest";
import type { CourseGrade, CourseProgress, GradeEntry, Grades } from "../types";
import { classRows, gradedEntries, markingPeriodLabels } from "./GradesTab";

const entry = (over: Partial<GradeEntry>): GradeEntry => ({
  external_uid: "e1",
  course_code: "210",
  course_section: "1",
  course_name: "GEOMETRY",
  marking_period: "MP2",
  weekday_date: "Mon 11/9",
  title: "Quiz 3",
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

const courseGrade = (over: Partial<CourseGrade>): CourseGrade => ({
  course_code: "210",
  course_section: "1",
  course_name: "GEOMETRY",
  marking_period: "MP2",
  grade_percent: 88,
  last_grade_posted: null,
  ...over,
});

const course = (over: Partial<CourseProgress>): CourseProgress => ({
  course_key: "210-1",
  course_name: "Geometry",
  grade_percent: 88,
  marking_period: "MP2",
  total: 10,
  done: 7,
  missing: 2,
  due_soon: 1,
  completion_pct: 70,
  teacher_name: "Ms. Teacher",
  teacher_emails: ["teacher@example.com"],
  ...over,
});

const grades = (over: Partial<Grades>): Grades => ({
  course_grades: [],
  entries: [],
  marking_periods: [],
  marking_period_discrepancies: [],
  ...over,
});

describe("markingPeriodLabels", () => {
  it("lists every marking period, newest first", () => {
    const g = grades({
      marking_periods: [
        { label: "MP1", start_date: "2026-09-08", end_date: "2026-11-06" },
        { label: "MP2", start_date: "2026-11-09", end_date: "2027-01-29" },
      ],
      course_grades: [courseGrade({ marking_period: "MP1" }), courseGrade({ marking_period: "FY" })],
    });
    expect(markingPeriodLabels(g)).toEqual(["MP2", "MP1", "FY"]);
    expect(markingPeriodLabels(null)).toEqual([]);
  });
});

describe("classRows", () => {
  const courses = [course({})];

  it("takes the current marking period from /progress, with its missing count", () => {
    const rows = classRows("MP2", "MP2", courses, grades({}), {});
    expect(rows).toEqual([
      { course_key: "210-1", name: "Geometry", teacher_name: "Ms. Teacher", teacher_emails: ["teacher@example.com"], grade_percent: 88, missing: 2 },
    ]);
  });

  it("uses the reader's own name for a class", () => {
    expect(classRows("MP2", "MP2", courses, grades({}), { "210-1": "Geo" })[0].name).toBe("Geo");
  });

  it("gives a past marking period no missing count: To do only knows the current one", () => {
    const g = grades({
      course_grades: [courseGrade({ marking_period: "MP1", grade_percent: 91 })],
      entries: [entry({ marking_period: "MP1", score_earned: 9, score_possible: 10 })],
    });
    const [row] = classRows("MP1", "MP2", courses, g, {});
    expect(row.grade_percent).toBe(91);
    expect(row.missing).toBeNull();
    expect(row.name).toBe("Geometry");
  });

  it("reads Genesis's 0.00% for a class with nothing graded as no grade", () => {
    const g = grades({
      course_grades: [courseGrade({ marking_period: "MP1", grade_percent: 0 })],
      entries: [entry({ marking_period: "MP1" })],
    });
    expect(classRows("MP1", "MP2", courses, g, {})[0].grade_percent).toBeNull();
  });

  it("keeps a real zero once something is graded", () => {
    const g = grades({
      course_grades: [courseGrade({ marking_period: "MP1", grade_percent: 0 })],
      entries: [entry({ marking_period: "MP1", status: "Missing" })],
    });
    expect(classRows("MP1", "MP2", courses, g, {})[0].grade_percent).toBe(0);
  });
});

describe("gradedEntries", () => {
  it("leaves out what isn't graded, and puts the newest mark first", () => {
    const g = grades({
      entries: [
        entry({ external_uid: "old", weekday_date: "Mon 10/5", score_earned: 8, score_possible: 10 }),
        entry({ external_uid: "ungraded", weekday_date: "Tue 11/10" }),
        entry({ external_uid: "new", weekday_date: "Fri 11/6", percent: 90 }),
        entry({ external_uid: "other-mp", marking_period: "MP1", weekday_date: "Fri 11/6", percent: 70 }),
      ],
    });
    expect(gradedEntries(g, "MP2").map((e) => e.external_uid)).toEqual(["new", "old"]);
    expect(gradedEntries(g, null)).toHaveLength(3);
  });

  it("orders by when schoolz first read the grade, when it knows", () => {
    const g = grades({
      entries: [
        entry({ external_uid: "a", weekday_date: "Fri 11/6", percent: 90, graded_at: "2026-11-07T10:00:00Z" }),
        entry({ external_uid: "b", weekday_date: "Mon 10/5", percent: 80, graded_at: "2026-11-09T10:00:00Z" }),
      ],
    });
    expect(gradedEntries(g, "MP2").map((e) => e.external_uid)).toEqual(["b", "a"]);
  });
});
