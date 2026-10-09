import type { Tone } from "../../components/ui/Badge";
import type { AuditSchool, AuditStatus, CellDetail, CellSummary, Counts, DataPointMeta } from "./auditApi";

export const STATUS_META: Record<AuditStatus, { label: string; tone: Tone; short: string }> = {
  current: { label: "Current", tone: "ok", short: "o" },
  stale: { label: "Stale", tone: "warn", short: "s" },
  failing: { label: "Failing", tone: "bad", short: "f" },
  not_collecting: { label: "Not collecting", tone: "muted", short: "n" },
  not_applicable: { label: "Not applicable", tone: "muted", short: "x" },
};

export const GAP_STATUSES: AuditStatus[] = ["failing", "stale", "not_collecting"];
export const GROUPS = ["Identity", "People", "Schedule", "News and events", "Services and documents"];

export function pctLabel(pct: number | null | undefined): string {
  return pct === null || pct === undefined ? "–" : `${pct}%`;
}

export function emptyCounts(): Counts {
  return { current: 0, stale: 0, failing: 0, not_collecting: 0, not_applicable: 0, applicable: 0, pct: null };
}

export function countCells(cells: Iterable<{ status: AuditStatus }>): Counts {
  const n = emptyCounts();
  for (const c of cells) n[c.status] += 1;
  n.applicable = n.current + n.stale + n.failing + n.not_collecting;
  n.pct = n.applicable ? Math.round((100 * n.current) / n.applicable) : null;
  return n;
}

// ---------- by-school filters ----------

export type SchoolFilters = {
  q: string;
  district: string; // "" = all
  type: string; // "" = all, else AuditSchool.kind
  col: string; // "" = any data point
  status: "" | "gap" | AuditStatus;
  sort: "pctAsc" | "pctDesc" | "fail" | "stale" | "none" | "name" | "district";
};

export const DEFAULT_FILTERS: SchoolFilters = { q: "", district: "", type: "", col: "", status: "", sort: "pctAsc" };

function hit(status: AuditStatus, want: SchoolFilters["status"]): boolean {
  return want === "gap" ? GAP_STATUSES.includes(status) : status === want;
}

export function filterSchools<C extends CellSummary>(schools: AuditSchool<C>[], f: SchoolFilters): AuditSchool<C>[] {
  const q = f.q.trim().toLowerCase();
  const out = schools.filter((s) => {
    if (q && !`${s.name} ${s.short_name}`.toLowerCase().includes(q)) return false;
    if (f.district && s.district_id !== f.district) return false;
    if (f.type && (s.kind ?? "") !== f.type) return false;
    if (!f.status) return true;
    const cells = f.col ? [s.cells[f.col]].filter(Boolean) : Object.values(s.cells);
    return cells.some((c) => hit(c.status, f.status));
  });
  const pct = (s: AuditSchool<C>) => s.counts.pct ?? 101;
  const byName = (a: AuditSchool<C>, b: AuditSchool<C>) => a.name.localeCompare(b.name);
  const sorters: Record<SchoolFilters["sort"], (a: AuditSchool<C>, b: AuditSchool<C>) => number> = {
    pctAsc: (a, b) => pct(a) - pct(b) || byName(a, b),
    pctDesc: (a, b) => pct(b) - pct(a) || byName(a, b),
    fail: (a, b) => b.counts.failing - a.counts.failing || pct(a) - pct(b) || byName(a, b),
    stale: (a, b) => b.counts.stale - a.counts.stale || pct(a) - pct(b) || byName(a, b),
    none: (a, b) => b.counts.not_collecting - a.counts.not_collecting || pct(a) - pct(b) || byName(a, b),
    name: byName,
    district: (a, b) => (a.district_name ?? "").localeCompare(b.district_name ?? "") || byName(a, b),
  };
  return out.sort(sorters[f.sort] ?? sorters.pctAsc);
}

export function filtersToParams(f: SchoolFilters): URLSearchParams {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(f)) if (v && v !== DEFAULT_FILTERS[k as keyof SchoolFilters]) p.set(k, v);
  return p;
}

export function filtersFromParams(p: URLSearchParams): SchoolFilters {
  const get = (k: keyof SchoolFilters) => p.get(k) ?? DEFAULT_FILTERS[k];
  return { q: get("q"), district: get("district"), type: get("type"), col: get("col"), status: get("status") as SchoolFilters["status"], sort: get("sort") as SchoolFilters["sort"] };
}

/** "Showing 1 to 10 of 19 schools", per the mockup. */
export function resultLabel(start: number, shown: number, matched: number, total: number, noun = "schools"): string {
  if (matched === 0) return `0 of ${total} ${noun}`;
  const tail = matched === total ? ` ${noun}` : ` matching ${noun} (${total} in total)`;
  return `Showing ${start + 1} to ${start + shown} of ${matched}${tail}`;
}

// ---------- reports ----------

export type ReportGroup = { key: string; label: string; schools: string[]; why: string; next: string };
export type ReportSection = { status: AuditStatus; title: string; sub: string; total: number; groups: ReportGroup[] };

const SECTION_TITLES: Partial<Record<AuditStatus, [string, string]>> = {
  failing: ["Failing", "a source is set, but the last scan did not work"],
  stale: ["Stale", "scans work, but the data is out of date"],
  not_collecting: ["Not collecting", "no source set, or not published"],
};

/** A district report: per gap status, one row per (data point, why, next) -
 * schools that share the same reason are listed together, a different
 * reason for the same data point gets its own row. */
export function buildReportSections(schools: AuditSchool<CellDetail>[], points: DataPointMeta[], include: AuditStatus[]): ReportSection[] {
  return GAP_STATUSES.filter((s) => include.includes(s)).map((status) => {
    const groups = new Map<string, ReportGroup>();
    let total = 0;
    for (const p of points) {
      for (const s of schools) {
        const c = s.cells[p.key];
        if (!c || c.status !== status) continue;
        total += 1;
        const id = `${p.key}\u0000${c.why}\u0000${c.next}`;
        const g = groups.get(id) ?? { key: p.key, label: p.label, schools: [], why: c.why, next: c.next };
        g.schools.push(s.short_name);
        groups.set(id, g);
      }
    }
    const [title, sub] = SECTION_TITLES[status]!;
    const list = [...groups.values()].sort((a, b) => b.schools.length - a.schools.length || a.label.localeCompare(b.label));
    return { status, title, sub: `${total} data points, ${sub}`, total, groups: list };
  });
}

export function schoolGaps(school: AuditSchool<CellDetail>, points: DataPointMeta[], include: AuditStatus[]) {
  const rank: Record<string, number> = { failing: 0, stale: 1, not_collecting: 2 };
  return points
    .map((p) => ({ point: p, cell: school.cells[p.key] }))
    .filter((r) => r.cell && include.includes(r.cell.status))
    .sort((a, b) => rank[a.cell.status] - rank[b.cell.status] || a.point.order - b.point.order);
}

const FOOTER =
  "A data point is compliant when it is on file and inside its freshness window, which is two missed scheduled runs plus a grace period. Data points that do not apply to a school's type are left out of the score.";
export const REPORT_FOOTER = FOOTER;

export function districtReportText(title: string, generated: string, schools: AuditSchool<CellDetail>[], sections: ReportSection[]): string {
  const n = countCells(schools.flatMap((s) => Object.values(s.cells)));
  const lines = [
    "Missing-data report",
    title,
    `${schools.length} schools · generated ${generated}`,
    "",
    `${pctLabel(n.pct)} compliant, ${n.current} of ${n.applicable} data points. ${n.failing} failing, ${n.stale} stale, ${n.not_collecting} not collecting.`,
  ];
  for (const sec of sections) {
    lines.push("", `${sec.title} · ${sec.sub}`);
    for (const g of sec.groups) lines.push(`- ${g.label} (${g.schools.length}: ${g.schools.join(", ")})`, `  Why: ${g.why}`, `  Next step: ${g.next}`);
    if (!sec.groups.length) lines.push("- None");
  }
  lines.push("", "By school");
  for (const s of [...schools].sort((a, b) => (a.counts.pct ?? 101) - (b.counts.pct ?? 101) || a.name.localeCompare(b.name))) {
    lines.push(`- ${s.name}: ${pctLabel(s.counts.pct)} compliant, ${s.counts.failing} failing, ${s.counts.stale} stale, ${s.counts.not_collecting} not collecting`);
  }
  lines.push("", FOOTER);
  return lines.join("\n");
}

export function schoolReportText(school: AuditSchool<CellDetail>, points: DataPointMeta[], include: AuditStatus[], generated: string): string {
  const gaps = schoolGaps(school, points, include);
  const c = school.counts;
  const lines = [
    "Missing-data report",
    school.name,
    `${school.district_name ?? "No district"} · generated ${generated}`,
    "",
    `${c.current} of ${c.applicable} applicable data points are current (${pctLabel(c.pct)}). ${gaps.length} are missing: ${c.failing} failing, ${c.stale} stale, ${c.not_collecting} not collected.`,
    "",
  ];
  for (const g of gaps) lines.push(`- ${g.point.label} [${STATUS_META[g.cell.status].label}]`, `  Why: ${g.cell.why}`, `  Next step: ${g.cell.next}`);
  const ok = points.filter((p) => school.cells[p.key]?.status === "current").map((p) => p.label);
  const na = points.filter((p) => school.cells[p.key]?.status === "not_applicable").map((p) => p.label);
  lines.push("", `Current: ${ok.join(", ") || "none"}.`, `Not applicable: ${na.join(", ") || "none"}.`, "", FOOTER);
  return lines.join("\n");
}

export function fmtGenerated(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", { day: "numeric", month: "long", year: "numeric" });
}
