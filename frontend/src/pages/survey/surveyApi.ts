import { apiFetch } from "../../api";

export type SurveyInput = {
  school_ids: string[];
  satisfaction: number | null;
  pain_points: string[];
  missing_info?: string;
  comments?: string;
  submitter_name?: string;
  submitter_email?: string;
  share_consent: "anonymous" | "named";
};

export type SurveySummary = {
  total: number;
  average_satisfaction: number | null;
  top_pain_points: { key: string; count: number }[];
};

/** The canonical list of things a family might struggle to keep track of.
 *
 * The first two groups are deliberately a complete inventory of what
 * schoolz already pulls together for each school today - so the list
 * doubles as "here's what we've already decided matters, based on what
 * parents told us." That makes it a starting point rather than a blank
 * page, and it makes disagreement easy to spot: an item nobody ever
 * checks is one we guessed wrong about, and the free-text box catches
 * whatever we left off entirely.
 *
 * Grouped by the three categories from docs/DISTRICT_COMMUNICATION_REPORT.md,
 * so the answers map straight back onto that report's central claim: the
 * first two groups are shared, public information that should look the
 * same at every school, and the third is personal and deliberately out of
 * this project's scope. The `key`s are what get stored and exported -
 * keep them stable, since changing one orphans every answer already given. */
export const PAIN_POINT_GROUPS: { title: string; hint: string; items: { key: string; label: string }[] }[] = [
  {
    title: "How your school works",
    hint: "Same for every family, barely changes",
    items: [
      { key: "bell_schedule", label: "What time school starts and ends — including half days and delayed openings" },
      { key: "rotation", label: "Which rotation day it is (Day 1–5, A/B blocks)" },
      { key: "absence", label: "How to report an absence" },
      { key: "transportation", label: "Buses — routes, the late bus, who to call when it's late" },
      { key: "lunch_menu", label: "Lunch menu" },
      { key: "sacc", label: "Before & after-school care (SACC)" },
      { key: "contacts", label: "Who to contact — principal, nurse, counselor, front office" },
      { key: "handbook", label: "Handbook & school policies" },
    ],
  },
  {
    title: "What's happening & what's due",
    hint: "Changes weekly — where most \"wait, that was today?\" lives",
    items: [
      { key: "calendar", label: "Calendar — closures, half days, early dismissals" },
      { key: "marking_periods", label: "Report card dates, conferences & interims" },
      { key: "deadlines", label: "Form & event deadlines — picture day, field trips, sign-ups" },
      { key: "pta", label: "PTA news, meetings & fundraisers" },
      { key: "newsletter", label: "The school's weekly newsletter" },
      { key: "special_events", label: "Spirit days & special events" },
      { key: "activities", label: "Clubs, sports & after-school activities" },
      { key: "volunteer", label: "Volunteering & how to help out" },
    ],
  },
  {
    title: "Your own child's information",
    hint: "Personal — schoolz deliberately doesn't touch this, but it helps to know how bad it is",
    items: [
      { key: "teacher_messages", label: "Messages from your child's teacher (ClassDojo, Remind, etc.)" },
      { key: "grades", label: "Grades & report cards (Genesis)" },
      { key: "assignments", label: "Assignments & homework (Google Classroom)" },
      { key: "payments", label: "Payments & lunch balances (PaySchools)" },
    ],
  },
];

export async function submitSurvey(input: SurveyInput): Promise<void> {
  const res = await apiFetch("/survey", { method: "POST", body: JSON.stringify(input) });
  if (!res.ok) {
    let msg = "Could not send this - please try again";
    try {
      const body = await res.json();
      if (typeof body.detail === "string") msg = body.detail;
      else if (Array.isArray(body.detail)) msg = body.detail.map((d: { msg: string }) => d.msg).join("; ");
    } catch {
      /* non-JSON error body */
    }
    throw new Error(msg);
  }
}

export async function loadSurveySummary(): Promise<SurveySummary | null> {
  const res = await apiFetch("/survey/summary");
  return res.ok ? res.json() : null;
}

export type PageVisitReport = {
  rows: { day: string; path: string; source: string; count: number }[];
  totals_by_path: Record<string, number>;
  totals_by_source: Record<string, number>;
};

export async function loadPageVisits(days = 30): Promise<PageVisitReport | null> {
  const res = await apiFetch(`/page-views?days=${days}`);
  return res.ok ? res.json() : null;
}
