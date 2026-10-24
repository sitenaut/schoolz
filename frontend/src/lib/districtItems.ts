import type { School, SchoolContentItem } from "../types";
import { i18n } from "./i18n";

// Same convention as the backend's own closure/half-day/delay detection
// (backend/services/school_status.py:says_closed/STAFF_DAY_RE/EARLY_RE/
// DELAY_RE, which school_today.py's classify_day uses) - kept here so both
// the Calendar page and the Today cards agree on what counts as a "no
// school" / "half day" status item vs. an ordinary district-wide event like
// a Board of Education meeting.
export const HALF_DAY_RE = /\bearly\s+dismissal\b|\bhalf[\s-]day\b|\bsingle[\s-]session\b/i;
export const DELAY_RE = /\bdelayed\s+opening\b|\b\d\s*-?\s*hour\s+delay\b/i;
// Staff and conference days: status items, but not a closed day.
const STAFF_DAY_RE = /\bin-?service\b|\bconference\b/i;
// Eastern Regional appends the class order: "Day 3 ( 3, 4, 1, LL, 7, 8, 5)".
const ROTATION_RE = /^\s*Day\s+\d+\s*(?:\([^)]*\))?\s*$/i;

// "Closed" that belongs to something other than the school day ("OFFICE
// CLOSED", "GYM 2 CLOSED FOR REPAIRS", "Executive (Closed) Session"), and a
// school word earlier in the same clause that makes it the school after all
// ("Schools & Offices Closed, Winter Recess"). Mirrors school_status.py.
const NOT_THE_SCHOOL_CLOSED_RE =
  /\b(?:main\s+|front\s+)?(?:offices?|portals?|gym(?:nasium)?(?:\s+\d+)?|weight\s+room|library|media\s+center|pool|fields?|cafeteria|kitchen|parking\s+lot|playground|track|store|pantry|labs?)\s+(?:is\s+|are\s+|will\s+be\s+)?closed\b|\(?\bclosed\)?\s+session\b/gi;
const SCHOOL_CLOSED_RE = /\b(?:schools?|district|buildings?)\b[^,;:()\u2013\u2014-]{0,40}?\bclosed\b|\bno school\b|\bno students\b/i;

/** No school that day. A bare "closed" counts - most feeds word a closure
 * that way ("CLOSED - Winter Recess", "Columbus Day, Closed") - but not an
 * office's or a gym's. */
export function saysClosed(title: string): boolean {
  return SCHOOL_CLOSED_RE.test(title) || /\bclosed\b/i.test(title.replace(NOT_THE_SCHOOL_CLOSED_RE, " "));
}

/** One day's status from the titles landing on it, by the Today card's
 * rules: closed beats half day; anything else is an ordinary day. Staff and
 * conference days don't close it: "EARLY DISMISSAL - Staff In-Service" and
 * "Early Dismissal - Parent/Teacher Conferences" are half days, and the
 * Calendar grid painted them as closures. isStatusItem keeps them, so
 * "Exclude district" never hides an in-service day. */
export function dayStatusOf(titles: string[]): "closed" | "half" | null {
  if (titles.some(saysClosed)) return "closed";
  if (titles.some((t) => HALF_DAY_RE.test(t))) return "half";
  return null;
}

export function isStatusItem(title: string): boolean {
  return saysClosed(title) || STAFF_DAY_RE.test(title) || HALF_DAY_RE.test(title) || DELAY_RE.test(title);
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
    return [{ key: item.id, item, label: name ? i18n.t("All {{name}}", { name }) : i18n.t("All schools") }];
  }
  const types = new Set(item.applies_to_school_types);
  const matching = ownSchools.filter((s) => s.school_type && types.has(s.school_type));
  return matching.map((s) => ({ key: `${item.id}-${s.id}`, item, label: s.short_name || s.name }));
}
