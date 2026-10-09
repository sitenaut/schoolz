import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { getDataPoints, listDistricts, type DataPointsAudit } from "./auditApi";
import { AuditTabs, useAudit } from "./AuditShell";
import { Pager } from "./AuditBySchoolPage";
import { GROUPS, pctLabel, resultLabel } from "./auditLib";

const WINDOWS: [string, string][] = [
  ["Every 2 hours, school days", "1 school day"],
  ["Every 12 hours", "36 hours"],
  ["Daily", "3 days"],
  ["Weekly", "16 days"],
  ["Twice a month", "35 days"],
  ["Monthly", "65 days"],
  ["No scan", "Not confirmed this school year"],
];

type Sort = "pctAsc" | "pctDesc" | "fail" | "stale" | "none" | "group" | "name";

export function AuditCatalogPage() {
  const { audience } = useAudit();
  const [params, setParams] = useSearchParams();
  const district = params.get("district") ?? "";
  const [data, setData] = useState<DataPointsAudit | null>(null);
  const [districts, setDistricts] = useState<{ id: string; name: string }[]>([]);
  const [error, setError] = useState("");
  const [q, setQ] = useState("");
  const [group, setGroup] = useState("");
  const [runs, setRuns] = useState<"" | "scan" | "hand">("");
  const [sort, setSort] = useState<Sort>("pctAsc");
  const [page, setPage] = useState(0);

  useEffect(() => {
    getDataPoints({ districtId: district || undefined, audience })
      .then((d) => {
        setData(d);
        setError("");
      })
      .catch((e: Error) => setError(e.message));
  }, [district, audience]);

  useEffect(() => {
    listDistricts()
      .then(setDistricts)
      .catch(() => undefined);
  }, []);

  const matched = useMemo(() => {
    if (!data) return [];
    const needle = q.trim().toLowerCase();
    const rows = data.data_points.filter((d) => {
      if (needle && !`${d.label} ${d.collected_by}`.toLowerCase().includes(needle)) return false;
      if (group && d.group !== group) return false;
      if (runs === "scan" && d.by_hand) return false;
      if (runs === "hand" && !d.by_hand) return false;
      return true;
    });
    const pct = (d: (typeof rows)[number]) => d.counts.pct ?? 101;
    const byOrder = (a: (typeof rows)[number], b: (typeof rows)[number]) => a.order - b.order;
    const sorters: Record<Sort, (a: (typeof rows)[number], b: (typeof rows)[number]) => number> = {
      pctAsc: (a, b) => pct(a) - pct(b) || byOrder(a, b),
      pctDesc: (a, b) => pct(b) - pct(a) || byOrder(a, b),
      fail: (a, b) => b.counts.failing - a.counts.failing || pct(a) - pct(b) || byOrder(a, b),
      stale: (a, b) => b.counts.stale - a.counts.stale || pct(a) - pct(b) || byOrder(a, b),
      none: (a, b) => b.counts.not_collecting - a.counts.not_collecting || pct(a) - pct(b) || byOrder(a, b),
      group: byOrder,
      name: (a, b) => a.label.localeCompare(b.label),
    };
    return rows.sort(sorters[sort]);
  }, [data, q, group, runs, sort]);

  const size = 10;
  const pageCount = Math.max(1, Math.ceil(matched.length / size));
  const cur = Math.min(page, pageCount - 1);
  const rows = matched.slice(cur * size, cur * size + size);
  const reset = <T,>(fn: (v: T) => void) => (v: T) => {
    fn(v);
    setPage(0);
  };

  return (
    <div className="audit">
      <AuditTabs />
      {error && <div className="form-error">{error}</div>}

      <section className="audit-card audit-pad" aria-label="How freshness is set">
        <div>
          <strong>A data point goes stale after two missed runs plus a grace period.</strong>{" "}
          <span className="muted">One missed run is noise; two means the schedule is no longer keeping it fresh.</span>
        </div>
        <div className="audit-windows">
          {WINDOWS.map(([k, v]) => (
            <div key={k}>
              <div className="cell-sub">{k}</div>
              <strong>{v}</strong>
            </div>
          ))}
        </div>
      </section>

      <div className="audit-filters">
        <label className="field">
          <span className="lbl">Search</span>
          <input type="search" placeholder={audience === "internal" ? "Data point or scan" : "Data point or source"} value={q} onChange={(e) => reset(setQ)(e.target.value)} />
        </label>
        <label className="field">
          <span className="lbl">District</span>
          <select
            value={district}
            onChange={(e) => {
              setParams(e.target.value ? { district: e.target.value } : {}, { replace: true });
              setPage(0);
            }}
          >
            <option value="">All districts</option>
            {districts.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="lbl">Group</span>
          <select value={group} onChange={(e) => reset(setGroup)(e.target.value)}>
            <option value="">All groups</option>
            {GROUPS.map((g) => (
              <option key={g} value={g}>
                {g}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="lbl">Collected</span>
          <select value={runs} onChange={(e) => reset(setRuns)(e.target.value as "" | "scan" | "hand")}>
            <option value="">Any way</option>
            <option value="scan">By a scheduled scan</option>
            <option value="hand">By hand, no scan</option>
          </select>
        </label>
        <label className="field">
          <span className="lbl">Order by</span>
          <select value={sort} onChange={(e) => reset(setSort)(e.target.value as Sort)}>
            <option value="pctAsc">Least compliant first</option>
            <option value="pctDesc">Most compliant first</option>
            <option value="fail">Most failing first</option>
            <option value="stale">Most stale first</option>
            <option value="none">Most not collected first</option>
            <option value="group">Group order</option>
            <option value="name">Name, A to Z</option>
          </select>
        </label>
      </div>

      <section className="audit-card" aria-label="Data points">
        <div className="audit-card-hd">
          <strong>
            {data ? `${resultLabel(cur * size, rows.length, matched.length, data.data_points.length, "data points")}, across ${data.school_count} schools` : "Loading…"}
          </strong>
        </div>
        <div className="audit-grid-wrap">
          <table className="dt audit-catalog">
            <thead>
              <tr>
                <th>Data point</th>
                <th>Collected by</th>
                <th>Runs</th>
                <th>Stale after</th>
                <th>Applies to</th>
                <th className="num">Compliant</th>
                <th>Schools</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((d) => {
                const c = d.counts;
                const parts = [`${c.current} of ${c.applicable} current`];
                if (c.not_collecting) parts.push(`${c.not_collecting} not collecting`);
                if (c.failing) parts.push(`${c.failing} failing`);
                if (c.stale) parts.push(`${c.stale} stale`);
                return (
                  <tr key={d.key}>
                    <td>
                      <div className="cell-title">{d.label}</div>
                      <div className="cell-sub">{d.group}</div>
                    </td>
                    <td className={audience === "internal" ? "mono" : ""}>{d.collected_by}</td>
                    <td>{d.runs}</td>
                    <td>
                      <strong>{d.stale_after}</strong>
                    </td>
                    <td>{d.applies}</td>
                    <td className="num">
                      <strong>{pctLabel(c.pct)}</strong>
                    </td>
                    <td>{parts.join(" · ")}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {data && !matched.length && <div className="dt-empty">No data points match these filters.</div>}
        </div>
        <div className="audit-pager">
          <div className="muted small">
            Cadences shown are the defaults; each school's cell is judged by its own scan's schedule. The district preschool directory, which creates the preschool rows themselves, isn't scored here
            {audience === "internal" ? " (see preschool_locations.scan under Scans)" : ""}.
          </div>
          <Pager page={cur} pageCount={pageCount} onPage={setPage} />
        </div>
      </section>
    </div>
  );
}
