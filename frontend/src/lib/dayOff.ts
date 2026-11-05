import type { School, SchoolToday } from "../types";
import { DEFAULT_NEAR, type NearChoice, makeNear } from "./eventsNear";

/** The Today page's day-off card: on a weekday the schools shown are closed,
 * a few things to do nearby (GET /local-events/day-off) and a question for
 * the chatbot. Built only on closures the backend classified
 * (school_today.py:days_off) - a wrong "no school" is worse than none. */

/** How far ahead the card starts: the weekend before a Monday closure,
 * Tuesday for a Thursday-Friday one. The backend lists a week of closed
 * days; a week's notice would keep the card up for most of every week with
 * a closure in it. */
export const PLAN_AHEAD_DAYS = 3;
/** On the closure day itself, past this hour most of the day's picks are
 * over, so the card moves on to the next day off, if one is coming. */
export const TODAY_UNTIL_HOUR = 15;

export type DayOffPlan = {
  date: string;
  daysAhead: number;
  label: string | null;
  /** The schools shown that are out that day. */
  schools: School[];
  /** Every school shown is out, so the card needn't name them. */
  allOut: boolean;
  audience: "kids" | "teens";
};

function daysBetween(from: string, to: string): number {
  return Math.round((Date.parse(to + "T12:00:00Z") - Date.parse(from + "T12:00:00Z")) / 86_400_000);
}

/** The soonest day off for the cards shown, or null. `today` is a
 * school-local YYYY-MM-DD and `hour` the school-local hour. */
export function planDayOff(cards: SchoolToday[], today: string, hour: number): DayOffPlan | null {
  const out = new Map<string, { schools: School[]; label: string | null }>();
  for (const card of cards) {
    for (const d of card.days_off ?? []) {
      const ahead = daysBetween(today, d.date);
      if (ahead < 0 || ahead > PLAN_AHEAD_DAYS || (ahead === 0 && hour >= TODAY_UNTIL_HOUR)) continue;
      const day = out.get(d.date) ?? { schools: [], label: null };
      day.schools.push(card.school);
      day.label ??= d.label;
      out.set(d.date, day);
    }
  }
  const date = [...out.keys()].sort()[0];
  if (!date) return null;
  const { schools, label } = out.get(date)!;
  return {
    date,
    daysAhead: daysBetween(today, date),
    label,
    schools,
    allOut: schools.length === cards.length,
    // Teens only when it's high schoolers alone who are out.
    audience: schools.every((s) => s.school_type === "high") ? "teens" : "kids",
  };
}

/** "Cherry Hill" from "1200 Brace Rd, Cherry Hill, NJ 08034". */
export function townOf(address: string | null): string | null {
  const m = address?.match(/,\s*([^,]+?),\s*(?:NJ|New Jersey|PA|Pennsylvania|DE|Delaware)\b/i);
  return m ? m[1].trim() : null;
}

/** Where to look for things to do. A place the visitor chose on /local wins -
 * that is where they are. Otherwise the first out school we have a position
 * for, then Cherry Hill. `place` names the point the picks are measured
 * from (null: the device's own position); `town` is for the chatbot, which
 * takes a town, never coordinates. */
export function dayOffNear(saved: NearChoice, schools: School[]): { choice: NearChoice; place: string | null; town: string } {
  const schoolTown = schools.map((s) => townOf(s.address)).find(Boolean) ?? null;
  if (saved.near.kind === "place") return { choice: saved, place: saved.near.label, town: saved.near.label };
  if (saved.near.kind === "device") return { choice: saved, place: null, town: schoolTown ?? DEFAULT_NEAR.label };
  const s = schools.find((x) => x.latitude != null && x.longitude != null);
  if (!s) return { choice: saved, place: saved.near.label, town: schoolTown ?? saved.near.label };
  const name = townOf(s.address) ?? s.short_name ?? s.name;
  return { choice: { near: makeNear(name, s.latitude!, s.longitude!, "default"), radius: saved.radius }, place: name, town: name };
}
