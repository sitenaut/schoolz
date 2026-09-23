import { describe, expect, it } from "vitest";
import { expandItemRows, isNoisyDistrictItem, isRotationItem, isStatusItem } from "./districtItems";
import type { School, SchoolContentItem } from "../types";

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
