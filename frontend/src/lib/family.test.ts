import { describe, expect, it } from "vitest";
import {
  awaitingSetup,
  bringsIn,
  districtSentences,
  gradesLine,
  guardiansLine,
  homeworkLine,
  joinNames,
  latestSync,
  scheduleLine,
  updateLine,
  type FamilyChild,
  type LastUpdate,
} from "./family";

const child = (over: Partial<FamilyChild> = {}): FamilyChild => ({
  id: "c1",
  first_name: "Maya",
  last_name: "Smith",
  student_id: "1234567",
  school_name: "East High",
  school_type: "high",
  grad_year: null,
  guardian_count: 1,
  district_name: "Cherry Hill Public Schools",
  has_classroom: true,
  has_genesis: true,
  classroom_seen_at: null,
  genesis_seen_at: null,
  needs_login: false,
  due_this_week: null,
  missing: null,
  classes: null,
  today: null,
  student_login_email: null,
  student_invite_email: null,
  specials_count: 0,
  ...over,
});

describe("family", () => {
  it("offers setup only for children whose school has Classroom or Genesis and nothing arrived", () => {
    const maya = child();
    const ben = child({ id: "c2", first_name: "Ben", classroom_seen_at: "2026-10-21T10:00:00Z" });
    const leo = child({ id: "c3", first_name: "Leo", has_classroom: false, has_genesis: false });
    expect(awaitingSetup([maya, ben, leo]).map((c) => c.first_name)).toEqual(["Maya"]);
  });

  it("names each district once with everything its children have", () => {
    const a = child({ has_genesis: false });
    const b = child({ id: "c2", has_classroom: false });
    const c = child({ id: "c3", district_name: null, school_name: "St. Mary", has_genesis: false });
    expect(districtSentences([a, b, c])).toEqual(["Cherry Hill Public Schools uses Google Classroom and Genesis.", "St. Mary uses Google Classroom."]);
    expect(bringsIn([a])).toBe("every assignment and what's missing");
    expect(bringsIn([a, b])).toBe("every assignment, what's missing, grades and the class schedule");
  });

  it("joins names the way a person would", () => {
    expect(joinNames(["Maya"])).toBe("Maya");
    expect(joinNames(["Maya", "Ben"])).toBe("Maya and Ben");
    expect(joinNames(["Maya", "Ben", "Leo"])).toBe("Maya, Ben and Leo");
  });

  it("describes what a row would show until data arrives, then what it shows", () => {
    expect(homeworkLine(child())).toBe("Every assignment, when it's due, and what's missing");
    expect(homeworkLine(child({ due_this_week: 0, missing: 0 }))).toBe("Nothing due this week");
    expect(homeworkLine(child({ due_this_week: 4, missing: 1 }))).toBe("4 due this week · 1 missing");
    expect(gradesLine(child())).toBe("Each class's grade and every graded assignment");
    expect(gradesLine(child({ classes: 1 }))).toBe("Grades for 1 class");
    expect(gradesLine(child({ classes: 0 }))).toBe("No grades yet");
  });

  it("only ever shows today's schedule", () => {
    const seen = { genesis_seen_at: "2026-10-21T10:00:00Z" };
    expect(scheduleLine(child())).toBe("Which class Maya is in right now, and what's next");
    expect(scheduleLine(child(seen))).toBe("Today's schedule isn't in yet");
    expect(scheduleLine(child({ ...seen, today: { state: "now", course_name: "Chemistry", room: "214", time_start: "9:52", time_end: "10:42" } }))).toBe(
      "Now: Chemistry, Room 214 · until 10:42",
    );
    expect(scheduleLine(child({ ...seen, today: { state: "next", course_name: "Lunch", room: null, time_start: "11:30", time_end: null } }))).toBe(
      "Next: Lunch at 11:30",
    );
    expect(scheduleLine(child({ ...seen, today: { state: "over", course_name: null, room: null, time_start: null, time_end: null } }))).toBe(
      "School's out for today",
    );
  });

  it("counts the other guardians, not the caller", () => {
    expect(guardiansLine(child())).toBe("Just you so far");
    expect(guardiansLine(child({ guardian_count: 2 }))).toBe("You and 1 other guardian see the same thing");
    expect(guardiansLine(child({ guardian_count: 3 }))).toBe("You and 2 other guardians see the same thing");
  });

  it("finds the newest update across children and sources", () => {
    expect(latestSync([child()])).toBeNull();
    expect(
      latestSync([child({ classroom_seen_at: "2026-10-21T10:00:00Z", genesis_seen_at: "2026-10-20T10:00:00Z" }), child({ genesis_seen_at: "2026-10-21T12:00:00Z" })]),
    ).toBe("2026-10-21T12:00:00Z");
  });
});

describe("updateLine", () => {
  const update = (summary: Partial<NonNullable<LastUpdate["summary"]>> | null): LastUpdate => ({
    id: "d1",
    reference: "D1",
    created_at: "2026-10-22T20:11:00Z",
    extension_version: "0.9.3",
    reported_at: null,
    summary: summary && {
      finished_at: "2026-10-22T20:10:00Z",
      manual: false,
      outcome: "ok",
      pages_sent: 0,
      last_sent_at: null,
      last_sent_pages: null,
      problems: [],
      not_set_up: [],
      ...summary,
    },
  });
  const fmt = (iso: string) => iso.slice(11, 16);

  it("says what the last update sent, nothing new included", () => {
    expect(updateLine(update({ pages_sent: 12 }), fmt)).toBe("Last update 20:10: 12 pages sent.");
    expect(updateLine(update({ pages_sent: 1 }), fmt)).toBe("Last update 20:10: 1 page sent.");
    expect(updateLine(update({ pages_sent: 0 }), fmt)).toBe("Last update 20:10: nothing new to send.");
  });

  it("falls back to when the log arrived for an older extension", () => {
    expect(updateLine(update(null), fmt)).toBe("Last update 20:11.");
  });
});
