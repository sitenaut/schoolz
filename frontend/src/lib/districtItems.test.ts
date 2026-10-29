import { beforeAll, describe, expect, it } from "vitest";
import { initI18n } from "./i18n";
import { dayStatusOf, expandItemRows, isNoisyDistrictItem, isRotationItem, isStatusItem, otherGradesOnly, saysClosed, statusTitles } from "./districtItems";
import type { School, SchoolContentItem } from "../types";

beforeAll(() => initI18n());

function item(overrides: Partial<SchoolContentItem>): SchoolContentItem {
  return {
    id: "i1",
    scope: "district",
    school_name: null,
    applies_to_school_types: null,
    applies_to_grad_years: null,
    class_label: null,
    category: "event",
    title: "Board of Education Meeting",
    description: null,
    start_date: "2026-09-02T04:00:00Z",
    end_date: null,
    is_all_day: true,
    link_url: null,
    person_name: null,
    person_title: null,
    staff_member_id: null,
    source_excerpt: null,
    extracted_at: "2026-09-01T00:00:00Z",
    is_current: true,
    ...overrides,
  };
}

function school(overrides: Partial<School>): School {
  return {
    id: "s1",
    slug: "bret-harte",
    name: "Bret Harte Elementary",
    short_name: "Bret Harte",
    district_id: "d1",
    school_type: "elementary",
    address: null,
    main_phone: null,
    website_url: null,
    absence_method: null,
    absence_emails: [],
    absence_phone: null,
    absence_portal_name: null,
    absence_portal_url: null,
    absence_instructions: null,
    start_time: null,
    end_time: null,
    early_dismissal_time: null,
    delayed_opening_time: null,
    athletics_url: null,
    logo_url: null,
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  } as School;
}

describe("isStatusItem", () => {
  it("recognizes closures, half days, and delays", () => {
    expect(isStatusItem("SCHOOLS CLOSED - Labor Day")).toBe(true);
    expect(isStatusItem("Early Dismissal")).toBe(true);
    expect(isStatusItem("2 Hour Delay")).toBe(true);
  });
  it("does not flag ordinary events", () => {
    expect(isStatusItem("Board of Education Meeting")).toBe(false);
    expect(isStatusItem("Day 3")).toBe(false);
  });
});

describe("isRotationItem", () => {
  it("matches bare Day N titles only", () => {
    expect(isRotationItem("Day 3")).toBe(true);
    expect(isRotationItem("Day 12")).toBe(true);
    expect(isRotationItem("First Day of School")).toBe(false);
  });
});

describe("isNoisyDistrictItem", () => {
  it("flags generic district events but not status/rotation/grading items", () => {
    expect(isNoisyDistrictItem(item({ title: "Board of Education Meeting" }))).toBe(true);
    expect(isNoisyDistrictItem(item({ title: "SCHOOLS CLOSED - Labor Day" }))).toBe(false);
    expect(isNoisyDistrictItem(item({ title: "Day 3" }))).toBe(false);
    expect(isNoisyDistrictItem(item({ title: "Report Cards Issued", category: "marking_period" }))).toBe(false);
  });
  it("never flags a scope=school item", () => {
    expect(isNoisyDistrictItem(item({ scope: "school", title: "Board of Education Meeting" }))).toBe(false);
  });
});

describe("expandItemRows", () => {
  const bretHarte = school({ id: "s1", short_name: "Bret Harte", school_type: "elementary" });
  const east = school({ id: "s2", short_name: "Cherry Hill East", school_type: "high" });

  it("labels a school-scoped item with its own school name", () => {
    const rows = expandItemRows(item({ scope: "school", school_name: "Bret Harte", applies_to_school_types: null }), [bretHarte, east]);
    expect(rows).toEqual([{ key: "i1", item: rows[0].item, label: "Bret Harte" }]);
  });

  it("labels an unrestricted district item 'All schools'", () => {
    const rows = expandItemRows(item({ applies_to_school_types: null }), [bretHarte, east]);
    expect(rows.map((r) => r.label)).toEqual(["All schools"]);
  });

  it("expands a type-restricted district item into one row per matching active school", () => {
    const rows = expandItemRows(item({ title: "Day 3", category: "event", applies_to_school_types: ["elementary"] }), [bretHarte, east]);
    expect(rows).toHaveLength(1);
    expect(rows[0].label).toBe("Bret Harte");
    expect(rows[0].key).toBe("i1-s1");
  });

  it("never labels one district's item onto another district's schools", () => {
    const chElem = school({ id: "s1", short_name: "Bret Harte", school_type: "elementary", district_id: "ch" });
    const vtElem = school({ id: "s3", short_name: "Kresson", school_type: "elementary", district_id: "vt" });
    const rows = expandItemRows(item({ title: "Day 2", district_id: "ch", applies_to_school_types: ["elementary"] }), [chElem, vtElem]);
    expect(rows.map((r) => r.label)).toEqual(["Bret Harte"]);
  });

  it("names the district on a district-wide item once active schools span two districts", () => {
    const chElem = school({ id: "s1", short_name: "Bret Harte", school_type: "elementary", district_id: "ch" });
    const vtElem = school({ id: "s3", short_name: "Kresson", school_type: "elementary", district_id: "vt" });
    const names: Record<string, string> = { ch: "Cherry Hill Public Schools" };
    const rows = expandItemRows(item({ district_id: "ch", applies_to_school_types: null }), [chElem, vtElem], (id) => names[id]);
    expect(rows.map((r) => r.label)).toEqual(["All Cherry Hill Public Schools"]);
  });

  it("drops a type-restricted item that matches none of the active schools", () => {
    const rows = expandItemRows(item({ applies_to_school_types: ["middle"] }), [bretHarte, east]);
    expect(rows).toEqual([]);
  });

  it("produces two separately-labeled rotation rows for two different tiers on the same date", () => {
    const elementaryDay = item({ id: "e1", title: "Day 3", category: "event", applies_to_school_types: ["elementary"] });
    const highDay = item({ id: "h1", title: "Day 2", category: "event", applies_to_school_types: ["high"] });
    const rows = [...expandItemRows(elementaryDay, [bretHarte, east]), ...expandItemRows(highDay, [bretHarte, east])];
    expect(rows.map((r) => `${r.item.title} [${r.label}]`)).toEqual(["Day 3 [Bret Harte]", "Day 2 [Cherry Hill East]"]);
  });
});

describe("dayStatusOf", () => {
  it("reads a day the way the Today card does", () => {
    expect(dayStatusOf(["SCHOOLS CLOSED - Labor Day"])).toBe("closed");
    expect(dayStatusOf(["EARLY DISMISSAL - Staff In-Service"])).toBe("half");
    expect(dayStatusOf(["Early Dismissal - Parent/Teacher Conferences"])).toBe("half");
    expect(dayStatusOf(["4 Hour Day for Students"])).toBe("half");
    expect(dayStatusOf(["12:50 Dismissal"])).toBe("half");
    expect(dayStatusOf(["2 PM Dismissal"])).toBe("half");
    expect(dayStatusOf(["Full Day of School - AHS ( 2:30pm Dismissal)"])).toBeNull();
    expect(dayStatusOf(["1:30 Dismissal All Preschools"])).toBeNull();
    expect(dayStatusOf(["Science conference night"])).toBeNull();
    expect(dayStatusOf(["Board of Education Meeting", "Day 3"])).toBeNull();
    // Still an in-service day for "Exclude district", which never hides one.
    expect(isStatusItem("Staff In-Service")).toBe(true);
  });
});

// Same cases as backend/tests/test_school_today.py: the two must agree.
describe("otherGradesOnly", () => {
  it("matches a grade span that stops short of the school", () => {
    expect(otherGradesOnly("DHS Prom & K-8 PCPEP Single Session", "high")).toBe(true);
    expect(otherGradesOnly("DHS Prom & K-8 PCPEP Single Session", "middle")).toBe(false);
    expect(otherGradesOnly("Single Session K-12", "high")).toBe(false);
    expect(otherGradesOnly("K-5 Single Session - Parent Conferences", "middle")).toBe(false);
    expect(otherGradesOnly("PK-4 Single Session", "middle")).toBe(true);
    expect(otherGradesOnly("Early Dismissal", "high")).toBe(false);
  });
});

describe("statusTitles", () => {
  const k8 = item({ title: "DHS Prom & K-8 PCPEP Single Session", district_id: "d1" });
  const high = school({ id: "h", short_name: "Delran High", school_type: "high", district_id: "d1" });
  const middle = school({ id: "m", short_name: "Delran Middle", school_type: "middle", district_id: "d1" });
  const elsewhere = school({ id: "e", short_name: "Kresson", school_type: "elementary", district_id: "d2" });

  it("leaves a K-8 half day off a high school's calendar, as the Today card does", () => {
    expect(dayStatusOf(statusTitles([k8], [high]))).toBeNull();
  });

  it("keeps it once a school it covers is shown", () => {
    expect(dayStatusOf(statusTitles([k8], [high, middle]))).toBe("half");
  });

  it("doesn't count another district's school as covered", () => {
    expect(dayStatusOf(statusTitles([k8], [high, elsewhere]))).toBeNull();
  });

  it("reads a school's own item for that school alone", () => {
    const own = item({ scope: "school", school_name: "Delran High", title: "K-8 Single Session" });
    expect(statusTitles([own], [high, middle])).toEqual([]);
  });
});

// Same real titles as backend/tests/test_status_lows.py: the two must agree.
describe("saysClosed", () => {
  it("keeps a bare 'closed' closure, as most feeds word it", () => {
    for (const t of [
      "CLOSED - Winter Recess",
      "Closed- Labor Day",
      "Columbus Day, Closed",
      "Schools & Offices Closed, Winter Recess",
      "Juneteenth - School/Offices Closed",
      "School - Closed: Winter Break",
      "No School - Yom Kippur",
    ]) {
      expect(saysClosed(t)).toBe(true);
      expect(dayStatusOf([t])).toBe("closed");
    }
  });

  it("closes the day for a title that is only the break's name, not an edge of it", () => {
    for (const t of ["Winter Recess", "SPRING BREAK", "Chews Spring Break", "Thanksgiving Recess (SC)", "Spring Break April 15-22"]) {
      expect(saysClosed(t)).toBe(true);
    }
    for (const t of [
      "Spring Break Begins",
      "Return from Winter Break",
      "Winter Recess - Early Dismissal",
      "ONE SESSION WINTER RECESS",
      "1/2 DAY WINTER RECESS",
      "Recess Runners Fun Run",
    ]) {
      expect(saysClosed(t)).toBe(false);
    }
  });

  it("lets a half day win over a break that starts that day", () => {
    expect(dayStatusOf(["Winter Recess", "SINGLE SESSION DAY"])).toBe("half");
    expect(dayStatusOf(["Winter Recess"])).toBe("closed");
    expect(dayStatusOf(["SCHOOLS CLOSED - Snow", "Early Dismissal"])).toBe("closed");
  });

  it("doesn't close the day for an office, a portal, a gym or a closed session", () => {
    for (const t of [
      "OFFICE CLOSED",
      "GYM 2 CLOSED FOR REPAIRS",
      "Genesis Parent & Student Portals Closed for Summer Maintenance",
      "Weight Room Closed",
      "Board of Education Meeting - Executive (Closed) Session",
      "Main Office Closed",
      "ALL District Offices Closed",
    ]) {
      expect(saysClosed(t)).toBe(false);
      expect(dayStatusOf([t])).toBeNull();
      expect(isStatusItem(t)).toBe(false);
    }
    // Asked twice: the global replace pattern keeps no state between calls.
    expect(saysClosed("OFFICE CLOSED")).toBe(false);
  });
});
