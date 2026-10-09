import { describe, expect, it } from "vitest";
import type { AuditSchool, AuditStatus, CellDetail, DataPointMeta } from "./auditApi";
import { buildReportSections, countCells, DEFAULT_FILTERS, filterSchools, filtersFromParams, filtersToParams, resultLabel, schoolReportText } from "./auditLib";

const points: DataPointMeta[] = ["news", "menu", "care"].map((key, order) => ({
  key,
  label: { news: "Newsletter", menu: "Meal menus", care: "Before and after care" }[key]!,
  group: "Services and documents",
  order,
  applies: "All schools",
  runs: "Daily",
  stale_after: "3 days",
  by_hand: false,
  collected_by: "The school website",
}));

function cell(key: string, status: AuditStatus, why = "w", next = "n"): CellDetail {
  return { key, status, tag: "", why, next, last_good: null, last_label: "", collected_by: "", runs: "", stale_after: "", internal_only: false };
}

function school(id: string, district: string, kind: string, statuses: Record<string, AuditStatus>, why: Record<string, string> = {}): AuditSchool<CellDetail> {
  const cells = Object.fromEntries(Object.entries(statuses).map(([k, s]) => [k, cell(k, s, why[k] ?? "w")]));
  return {
    id,
    slug: id,
    name: `${id} School`,
    short_name: id,
    kind,
    kind_label: kind,
    district_id: district,
    district_name: district,
    counts: countCells(Object.values(cells)),
    cells,
  };
}

const schools = [
  school("Alpha", "d1", "elementary", { news: "current", menu: "stale", care: "current" }),
  school("Beta", "d1", "middle", { news: "failing", menu: "stale", care: "not_applicable" }, { news: "expired link" }),
  school("Gamma", "d2", "high", { news: "failing", menu: "current", care: "not_applicable" }, { news: "site down" }),
];

describe("countCells", () => {
  it("leaves not applicable out of the score", () => {
    const n = countCells(schools[1].cells ? Object.values(schools[1].cells) : []);
    expect(n.applicable).toBe(2);
    expect(n.pct).toBe(0);
    expect(countCells([]).pct).toBeNull();
  });
});

describe("filterSchools", () => {
  it("filters by district, type, status and data point, least compliant first", () => {
    expect(filterSchools(schools, { ...DEFAULT_FILTERS, district: "d1" }).map((s) => s.id)).toEqual(["Beta", "Alpha"]);
    expect(filterSchools(schools, { ...DEFAULT_FILTERS, type: "high" }).map((s) => s.id)).toEqual(["Gamma"]);
    expect(filterSchools(schools, { ...DEFAULT_FILTERS, status: "stale" }).map((s) => s.id)).toEqual(["Beta", "Alpha"]);
    expect(filterSchools(schools, { ...DEFAULT_FILTERS, status: "failing", col: "menu" })).toEqual([]);
    expect(filterSchools(schools, { ...DEFAULT_FILTERS, status: "gap", sort: "name" }).map((s) => s.id)).toEqual(["Alpha", "Beta", "Gamma"]);
  });

  it("round-trips filters through the URL, dropping defaults", () => {
    const f = { ...DEFAULT_FILTERS, district: "d1", status: "gap" as const };
    const p = filtersToParams(f);
    expect(p.toString()).toBe("district=d1&status=gap");
    expect(filtersFromParams(p)).toEqual(f);
  });
});

describe("reports", () => {
  it("groups schools that share a reason and splits different reasons", () => {
    const [failing, stale] = buildReportSections(schools, points, ["failing", "stale"]);
    expect(failing.total).toBe(2);
    expect(failing.groups.map((g) => [g.label, g.schools, g.why])).toEqual([
      ["Newsletter", ["Beta"], "expired link"],
      ["Newsletter", ["Gamma"], "site down"],
    ]);
    expect(stale.groups).toEqual([{ key: "menu", label: "Meal menus", schools: ["Alpha", "Beta"], why: "w", next: "n" }]);
  });

  it("writes a plain-text school report", () => {
    const text = schoolReportText(schools[1], points, ["failing", "stale", "not_collecting"], "9 October 2026");
    expect(text).toContain("0 of 2 applicable data points are current (0%)");
    expect(text).toContain("- Newsletter [Failing]");
    expect(text).toContain("Not applicable: Before and after care.");
  });

  it("labels results like the mockup", () => {
    expect(resultLabel(0, 10, 19, 19)).toBe("Showing 1 to 10 of 19 schools");
    expect(resultLabel(10, 2, 12, 19)).toBe("Showing 11 to 12 of 12 matching schools (19 in total)");
    expect(resultLabel(0, 0, 0, 19)).toBe("0 of 19 schools");
  });
});
