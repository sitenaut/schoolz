import { shortCourseName } from "../gradez/courses";

/** My family (pages/FamilyPage.tsx): what the page says for each child,
 * from GET /family. Homework and grades are only ever offered for a child
 * whose school has Google Classroom or a Genesis Backpack Capture can read
 * (or whose data already arrived) - the backend decides that, per district. */

export type FamilyToday = {
  state: "now" | "next" | "over";
  course_name: string | null;
  room: string | null;
  time_start: string | null;
  time_end: string | null;
};

export type FamilyLowClass = {
  course_key: string;
  course_name: string | null;
  /** The caller's own rename of the class in Gradez, if any. */
  custom_name: string | null;
};

export type FamilyChild = {
  id: string;
  first_name: string;
  last_name: string;
  student_id: string;
  school_name: string | null;
  school_type: string | null;
  grad_year: number | null;
  guardian_count: number;
  district_name: string | null;
  has_classroom: boolean;
  has_genesis: boolean;
  classroom_seen_at: string | null;
  genesis_seen_at: string | null;
  needs_login: boolean;
  /** null until Classroom has sent anything - never 0 for "not connected". */
  due_this_week: number | null;
  /** Work due today and not done yet. Null until Classroom has sent anything. */
  due_today: number | null;
  missing: number | null;
  /** null until Genesis has sent anything. */
  classes: number | null;
  /** The class with the lowest grade under 50% this marking period, or null
   * when none is (or Genesis hasn't sent anything). */
  low_class: FamilyLowClass | null;
  /** Teachers' Classroom posts dated in the last seven days. Null until
   * Classroom has sent anything. */
  recent_posts: number | null;
  today: FamilyToday | null;
  student_login_email: string | null;
  student_invite_email: string | null;
  specials_count: number;
};

export const BACKPACK_CAPTURE_STORE_URL = "https://chromewebstore.google.com/detail/backpack-capture/imjhghdlhjgoeghhgafdpclapkjcnfbe";

export const offersSchoolwork = (c: FamilyChild) => c.has_classroom || c.has_genesis;
export const hasSchoolwork = (c: FamilyChild) => Boolean(c.classroom_seen_at || c.genesis_seen_at);

/** Children whose school has Classroom or Genesis but nothing has arrived
 * yet - who the setup card at the top is for. */
export const awaitingSetup = (children: FamilyChild[]) => children.filter((c) => offersSchoolwork(c) && !hasSchoolwork(c));

/** "Maya", "Maya and Ben", "Maya, Ben and Leo". */
export function joinNames(names: string[]): string {
  if (names.length <= 1) return names[0] ?? "";
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

export function systemsLabel(classroom: boolean, genesis: boolean): string {
  return [classroom && "Google Classroom", genesis && "Genesis"].filter(Boolean).join(" and ");
}

/** "Cherry Hill Public Schools uses Google Classroom and Genesis." - one per
 * district (or school, when the district isn't known), merged across the
 * children it's for. */
export function districtSentences(children: FamilyChild[]): string[] {
  const by = new Map<string, { classroom: boolean; genesis: boolean }>();
  for (const c of children) {
    const who = c.district_name ?? c.school_name ?? `${c.first_name}'s school`;
    const cur = by.get(who) ?? { classroom: false, genesis: false };
    by.set(who, { classroom: cur.classroom || c.has_classroom, genesis: cur.genesis || c.has_genesis });
  }
  return [...by].map(([who, s]) => `${who} uses ${systemsLabel(s.classroom, s.genesis)}.`);
}

/** What connecting brings in, for the systems these children have. */
export function bringsIn(children: FamilyChild[]): string {
  const classroom = children.some((c) => c.has_classroom);
  const genesis = children.some((c) => c.has_genesis);
  const parts = [...(classroom ? ["every assignment", "what's missing"] : []), ...(genesis ? ["grades", "the class schedule"] : [])];
  return joinNames(parts);
}

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

// One line under each of a child's rows on My family, each the tab of
// Gradez the row opens. Null means there is nothing to say: the data isn't
// there yet, and a row never shows a number that wasn't captured. The API
// may also predate a field (undefined), hence `== null` throughout.

/** "2 due today · 3 missing". */
export function todoLine(c: FamilyChild): string | null {
  const parts: string[] = [];
  if (c.due_today != null) parts.push(c.due_today === 0 ? "Nothing due today" : `${c.due_today} due today`);
  if (c.missing) parts.push(`${c.missing} missing`);
  return parts.length ? parts.join(" · ") : null;
}

/** "6 classes · Geometry is below 50%", flagged when a class is that low. */
export function gradesLine(c: FamilyChild): { text: string; low: boolean } | null {
  if (c.classes == null) return null;
  const count = c.classes === 0 ? "No grades yet" : plural(c.classes, "class", "classes");
  const low = c.low_class;
  if (!low) return { text: count, low: false };
  const name = low.custom_name?.trim() || (low.course_name ? shortCourseName(low.course_name) : "");
  return { text: `${count} · ${name || "A class"} is below 50%`, low: true };
}

/** "Now: Biology, Room 214". Only ever today's schedule. */
export function scheduleLine(c: FamilyChild): string | null {
  const t = c.genesis_seen_at ? c.today : null;
  if (!t) return null;
  if (t.state === "over") return "School's out for today";
  const where = t.room ? `, Room ${t.room}` : "";
  if (t.state === "now") return `Now: ${t.course_name}${where}`;
  return `Next: ${t.course_name}${where}${t.time_start ? ` at ${t.time_start}` : ""}`;
}

/** "3 posts this week". */
export function teachersLine(c: FamilyChild): string | null {
  if (c.recent_posts == null) return null;
  return c.recent_posts === 0 ? "No posts this week" : `${plural(c.recent_posts, "post", "posts")} this week`;
}

/** "You and 1 other": the other guardians, not the caller. */
export function guardiansLine(c: FamilyChild): string {
  if (c.guardian_count <= 1) return "Just you so far";
  return `You and ${plural(c.guardian_count - 1, "other", "others")}`;
}

/** Whether the child has their own login, or an invite out for one. */
export function studentLoginLine(c: FamilyChild): string {
  if (c.student_login_email) return `Signs in as ${c.student_login_email}`;
  if (c.student_invite_email) return `Invite sent to ${c.student_invite_email}`;
  return `Not invited yet. ${c.first_name} would see this same page.`;
}

/** "Grade 10" for a high schooler whose graduating class is set: a class
 * graduates in June, and the school year turns over in July (the same
 * rule as My family's graduating-class picker). */
export function gradeLevel(c: FamilyChild, now: Date = new Date()): number | null {
  if (c.school_type !== "high" || c.grad_year == null) return null;
  const yearEnds = now.getMonth() >= 6 ? now.getFullYear() + 1 : now.getFullYear();
  const grade = 12 - (c.grad_year - yearEnds);
  return grade >= 9 && grade <= 12 ? grade : null;
}

/** Same wording as Gradez's header (gradez/lib/freshness.ts). */
export function timeAgo(iso: string, now: number): string {
  const minutes = Math.round((now - Date.parse(iso)) / 60000);
  if (minutes < 2) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  return days === 1 ? "yesterday" : `${days} days ago`;
}

/** GET /capture-devices/last-update: what Backpack Capture said about the
 * last update it ran for this account, as the extension summed it up. */
export type UpdateSummary = {
  finished_at: string;
  manual: boolean;
  outcome: "ok" | "trouble";
  pages_sent: number;
  last_sent_at: string | null;
  last_sent_pages: number | null;
  problems: { student_id: string | null; text: string }[];
  not_set_up: string[];
};
export type LastUpdate = {
  id: string;
  reference: string;
  created_at: string;
  extension_version: string;
  summary: UpdateSummary | null;
  reported_at: string | null;
};

/** "Last update Oct 22, 4:10 PM: 12 pages sent." An update with nothing new
 * still counts: it looked, and everything was as before. */
export function updateLine(update: LastUpdate, fmt: (iso: string) => string): string {
  const s = update.summary;
  const when = fmt(s?.finished_at ?? update.created_at);
  if (!s) return `Last update ${when}.`;
  const sent = s.pages_sent === 1 ? "1 page sent" : s.pages_sent > 1 ? `${s.pages_sent} pages sent` : "nothing new to send";
  return `Last update ${when}: ${sent}.`;
}

/** The newest thing Backpack Capture sent for any child. */
export function latestSync(children: FamilyChild[]): string | null {
  const times = children.flatMap((c) => [c.classroom_seen_at, c.genesis_seen_at]).filter((t): t is string => Boolean(t));
  return times.length ? times.reduce((a, b) => (Date.parse(a) > Date.parse(b) ? a : b)) : null;
}
