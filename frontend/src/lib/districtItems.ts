import type { School, SchoolContentItem } from "../types";

// Same convention as the backend's own closure/half-day/delay detection
// (backend/services/school_today.py:_CLOSED_RE/_EARLY_RE/_DELAY_RE,
// frontend/src/pages/CalendarPage.tsx's pre-existing CLOSED_RE/HALF_DAY_RE)
// - kept here so both the Calendar page and the Today cards agree on what
// counts as a "no school" / "half day" status item vs. an ordinary
// district-wide event like a Board of Education meeting.
export const CLOSED_RE = /\b(schools?|district)\s+closed\b|\bno school\b|\bclosed\b|\bin-?service\b|\bconference\b/i;
export const HALF_DAY_RE = /\bearly\s+dismissal\b|\bhalf[\s-]day\b/i;
export const DELAY_RE = /\bdelayed\s+opening\b|\b\d\s*-?\s*hour\s+delay\b/i;
// Eastern Regional appends the class order: "Day 3 ( 3, 4, 1, LL, 7, 8, 5)".
const ROTATION_RE = /^\s*Day\s+\d+\s*(?:\([^)]*\))?\s*$/i;

export function isStatusItem(title: string): boolean {
  return CLOSED_RE.test(title) || HALF_DAY_RE.test(title) || DELAY_RE.test(title);
}

export function isRotationItem(title: string): boolean {
  return ROTATION_RE.test(title);
}

/** "Exclude district" hides the generic district noise (board meetings,
 * committee meetings, ...) while always keeping the things that actually
 * affect a school day - closures/half-days/delays (however they're
 * labeled) and grading/report-card dates (an earlier, deliberate ask to
 * keep those visible) - and never touches day-rotation markers, which
 * have their own separate toggle. */
export function isNoisyDistrictItem(item: SchoolContentItem): boolean {
  return item.scope === "district" && !isStatusItem(item.title) && !isRotationItem(item.title) && item.category !== "marking_period";
}

export type LabeledRow = { key: string; item: SchoolContentItem; label: string | null };

/** Expands one item into the row(s) it should render as. A scope="school"
 * item keeps its own school_name. A scope="district" item with no
 * applies_to_school_types restriction applies to literally everyone -
 * "All schools". One restricted to specific types (elementary/middle/
 * high/...) - the day-rotation markers, or a type-specific half day - is
 * expanded into one row per currently-active school of a matching type,
 * each individually labeled with that school's own name (not "Elementary
 * school"/"High school") - so "Day 3" for Bret Harte and "Day 2" for
 * Cherry Hill East on the same date read as two distinct facts instead of
 * one confusing type-labeled row. An item that matches none of the active
 * schools' types doesn't apply to anyone currently being viewed, so it's
 * dropped entirely (returns no rows). */
export function expandItemRows(
  item: SchoolContentItem,
  activeSchools: School[],
  districtName?: (districtId: string) => string | undefined,
): LabeledRow[] {
  if (item.scope === "school") {
    return [{ key: item.id, item, label: item.school_name }];
  }
  // A district's items only ever apply to its own schools - with two
  // districts active, an elementary "Day 2" from one must not be labeled
  // onto the other's elementary schools.
  const ownSchools = item.district_id ? activeSchools.filter((s) => s.district_id === item.district_id) : activeSchools;
  if (!item.applies_to_school_types?.length) {
    const spansDistricts = new Set(activeSchools.map((s) => s.district_id)).size > 1;
    const name = spansDistricts && item.district_id ? districtName?.(item.district_id) : undefined;
    return [{ key: item.id, item, label: name ? `All ${name}` : "All schools" }];
  }
  const types = new Set(item.applies_to_school_types);
  const matching = ownSchools.filter((s) => s.school_type && types.has(s.school_type));
  return matching.map((s) => ({ key: `${item.id}-${s.id}`, item, label: s.short_name || s.name }));
}
