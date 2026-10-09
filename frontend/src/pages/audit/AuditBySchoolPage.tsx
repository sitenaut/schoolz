import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Badge } from "../../components/ui/Badge";
import { useToast } from "../../components/ui/Toast";
import { getAudit, getSchoolAudit, downloadCsv, type AuditGrid, type AuditSchool, type CellDetail } from "./auditApi";
import { AuditTabs, useAudit } from "./AuditShell";
import { CellActions, CellIcon } from "./AuditCell";
import { countCells, filterSchools, filtersFromParams, filtersToParams, GROUPS, pctLabel, resultLabel, STATUS_META, type SchoolFilters } from "./auditLib";

type Selected = { schoolId: string; key: string };

export function AuditBySchoolPage() {
  const { audience } = useAudit();
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const paramKey = params.toString();
  const filters = useMemo(() => filtersFromParams(new URLSearchParams(paramKey)), [paramKey]);
  const [data, setData] = useState<AuditGrid | null>(null);
  const [error, setError] = useState("");
  const [page, setPage] = useState(0);
  const [size, setSize] = useState(10);
  const [sel, setSel] = useState<Selected | null>(null);
  const [detail, setDetail] = useState<{ school: AuditSchool<CellDetail> } | null>(null);
  const detailCache = useRef(new Map<string, AuditSchool<CellDetail>>());

  const load = useCallback(() => {
    detailCache.current.clear();
    getAudit({ audience })
      .then((d) => {
        setData(d);
        setError("");
      })
      .catch((e: Error) => setError(e.message));
  }, [audience]);
  useEffect(load, [load]);

  const setFilter = (patch: Partial<SchoolFilters>) => {
    setParams(filtersToParams({ ...filters, ...patch }), { replace: true });
    setPage(0);
  };

  const points = data?.data_points ?? [];
  const matched = useMemo(() => (data ? filterSchools(data.schools, filters) : []), [data, filters]);
  const pageCount = Math.max(1, Math.ceil(matched.length / size));
  const cur = Math.min(page, pageCount - 1);
  const rows = matched.slice(cur * size, cur * size + size);

  // Tiles reflect the district/type/search filters but not the status
  // filter they themselves set, so a tile never zeroes itself out.
  const scope = useMemo(() => (data ? filterSchools(data.schools, { ...filters, status: "", col: "" }) : []), [data, filters]);
  const counts = useMemo(() => countCells(scope.flatMap((s) => Object.values(s.cells))), [scope]);

  const loadDetail = useCallback(
    async (schoolId: string, force = false) => {
      if (!force && detailCache.current.has(schoolId)) {
        setDetail({ school: detailCache.current.get(schoolId)! });
        return;
      }
      try {
        const d = await getSchoolAudit(schoolId, audience);
        detailCache.current.set(schoolId, d.school);
        setDetail({ school: d.school });
      } catch (e) {
        toast({ title: (e as Error).message, tone: "bad" });
      }
    },
    [audience, toast]
  );

  useEffect(() => {
    if (sel) loadDetail(sel.schoolId);
  }, [sel, loadDetail]);

  // Pick the first gap on first load so the panel isn't empty.
  useEffect(() => {
    if (sel || !matched.length) return;
    const s = matched[0];
    const key = points.find((p) => ["failing", "stale", "not_collecting"].includes(s.cells[p.key]?.status))?.key ?? points[0]?.key;
    if (key) setSel({ schoolId: s.id, key });
  }, [matched, points, sel]);

  const reportParams = filtersToParams(filters).toString();
  const groupSpans = GROUPS.map((g) => ({ g, n: points.filter((p) => p.group === g).length }));
  const selSchool = detail?.school.id === sel?.schoolId ? detail?.school : undefined;
  const selCell = sel && selSchool ? selSchool.cells[sel.key] : undefined;
  const selPoint = points.find((p) => p.key === sel?.key);

  const tile = (key: SchoolFilters["status"], label: string, value: number, hint: string, tone: string) => (
    <button className="stat" aria-pressed={filters.status === key} onClick={() => setFilter({ status: filters.status === key ? "" : key })}>
      <span className="stat-k">{label}</span>
      <span className={`stat-v ${tone}`}>{value}</span>
      <span className="audit-stat-hint">{hint}</span>
    </button>
  );

  return (
    <div className="audit">
      <AuditTabs
        actions={
          <>
            <button className="btn" onClick={() => downloadCsv({ districtId: filters.district || undefined, audience }).catch((e: Error) => toast({ title: e.message, tone: "bad" }))}>
              Download CSV
            </button>
            <Link className="btn btn-primary" to={`/admin/audit/report${filters.district ? `?district=${filters.district}` : ""}`}>
              Missing-data report
            </Link>
          </>
        }
      />
      {error && <div className="form-error">{error}</div>}

      <div className="stats">
        <div className="stat audit-stat-static">
          <span className="stat-k">Compliant</span>
          <span className="stat-v">{pctLabel(counts.pct)}</span>
          <span className="audit-stat-hint">
            {counts.current} of {counts.applicable} applicable data points are current
          </span>
        </div>
        {tile("not_collecting", "Not collecting", counts.not_collecting, "No source set, or the school doesn't publish it", "")}
        {tile("failing", "Failing", counts.failing, "Source set, last scan errored or warned", "bad")}
        {tile("stale", "Stale", counts.stale, "Two scheduled runs missed, or the content is out of date", "warn")}
      </div>

      <div className="audit-filters">
        <label className="field">
          <span className="lbl">Search</span>
          <input type="search" placeholder="School name" value={filters.q} onChange={(e) => setFilter({ q: e.target.value })} />
        </label>
        <label className="field">
          <span className="lbl">District</span>
          <select value={filters.district} onChange={(e) => setFilter({ district: e.target.value })}>
            <option value="">All districts</option>
            {data?.districts.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="lbl">School type</span>
          <select value={filters.type} onChange={(e) => setFilter({ type: e.target.value })}>
            <option value="">All types</option>
            <option value="preschool">Preschool</option>
            <option value="elementary">Elementary</option>
            <option value="middle">Middle</option>
            <option value="high">High</option>
            <option value="alternative">Alternative</option>
          </select>
        </label>
        <label className="field">
          <span className="lbl">Data point</span>
          <select value={filters.col} onChange={(e) => setFilter({ col: e.target.value })}>
            <option value="">Any data point</option>
            {points.map((p) => (
              <option key={p.key} value={p.key}>
                {p.label}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="lbl">Status</span>
          <select value={filters.status} onChange={(e) => setFilter({ status: e.target.value as SchoolFilters["status"] })}>
            <option value="">Any status</option>
            <option value="gap">Any gap</option>
            <option value="not_collecting">Not collecting</option>
            <option value="failing">Failing</option>
            <option value="stale">Stale</option>
          </select>
        </label>
        <label className="field">
          <span className="lbl">Order by</span>
          <select value={filters.sort} onChange={(e) => setFilter({ sort: e.target.value as SchoolFilters["sort"] })}>
            <option value="pctAsc">Least compliant first</option>
            <option value="pctDesc">Most compliant first</option>
            <option value="fail">Most failing first</option>
            <option value="stale">Most stale first</option>
            <option value="none">Most not collected first</option>
            <option value="name">School name, A to Z</option>
            <option value="district">District, then school</option>
          </select>
        </label>
        <button className="btn" onClick={() => setFilter({ q: "", district: "", type: "", col: "", status: "" })}>
          Clear filters
        </button>
      </div>

      <section className="audit-card" aria-label="Audit by school">
        <div className="audit-card-hd">
          <strong>{data ? resultLabel(cur * size, rows.length, matched.length, data.schools.length) : "Loading…"}</strong>
          <Link to={`/admin/audit/report?scope=filters${reportParams ? `&${reportParams}` : ""}`}>Missing-data report for these results</Link>
        </div>
        <div className="audit-grid-wrap">
          <table className="audit-grid">
            <thead>
              <tr className="audit-grid-groups">
                <th />
                {groupSpans.map(({ g, n }) => (
                  <th key={g} colSpan={n}>
                    {g}
                  </th>
                ))}
                <th />
              </tr>
              <tr>
                <th className="audit-grid-school">School</th>
                {points.map((p) => (
                  <th key={p.key} className="audit-grid-col" scope="col">
                    <span>{p.label}</span>
                  </th>
                ))}
                <th className="audit-grid-pct">Compliant</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((s) => (
                <tr key={s.id}>
                  <th scope="row" className="audit-grid-school">
                    <Link to={`/admin/audit/schools/${s.slug}`}>{s.name}</Link>
                    <span className="cell-sub">
                      {s.kind_label} · {s.district_name ?? "No district"}
                    </span>
                  </th>
                  {points.map((p) => {
                    const c = s.cells[p.key];
                    const on = sel?.schoolId === s.id && sel.key === p.key;
                    return (
                      <td key={p.key}>
                        <button
                          type="button"
                          className={`audit-cell ${c.status}${on ? " on" : ""}`}
                          aria-label={`${s.name}, ${p.label}: ${STATUS_META[c.status].label}`}
                          aria-pressed={on}
                          title={`${p.label}: ${STATUS_META[c.status].label}${c.tag ? ` · ${c.tag}` : ""}`}
                          onClick={() => setSel({ schoolId: s.id, key: p.key })}
                        >
                          <CellIcon status={c.status} />
                        </button>
                      </td>
                    );
                  })}
                  <td className="audit-grid-pct">
                    <span>{pctLabel(s.counts.pct)}</span>
                    <Link to={`/admin/audit/schools/${s.slug}/report`} className="btn icon sm" aria-label={`Missing-data report for ${s.name}`} title="Missing-data report">
                      <svg width="16" height="16" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                        <path d="M4.5 2.5h6l3 3v10h-9z" />
                        <path d="M10.5 2.5v3h3" />
                        <path d="M6.8 9.5h4.4M6.8 12h4.4" />
                      </svg>
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {data && !matched.length && <div className="dt-empty">No schools match these filters.</div>}
        </div>

        <div className="audit-pager">
          <label className="audit-size">
            Rows per page
            <select
              value={size}
              onChange={(e) => {
                setSize(Number(e.target.value));
                setPage(0);
              }}
            >
              <option value={10}>10</option>
              <option value={25}>25</option>
              <option value={50}>50</option>
            </select>
          </label>
          <Pager page={cur} pageCount={pageCount} onPage={setPage} />
        </div>

        <div className="audit-legend">
          {(["current", "not_collecting", "failing", "stale", "not_applicable"] as const).map((st) => (
            <span key={st}>
              <span className={`audit-cell ${st} mini`}>
                <CellIcon status={st} />
              </span>
              <strong>{STATUS_META[st].label}</strong>
              {st === "not_applicable" && ", left out of the score"}
            </span>
          ))}
          <span className="muted">Select any cell to see why.</span>
        </div>
      </section>

      <section className="audit-card audit-detail" aria-label="Selected data point">
        {sel && selPoint && selSchool && selCell ? (
          <>
            <div className="audit-detail-hd">
              <div className="audit-detail-t">
                <h2>
                  {selSchool.name} · {selPoint.label}
                </h2>
                <Badge tone={STATUS_META[selCell.status].tone}>{STATUS_META[selCell.status].label}</Badge>
                {selCell.tag && <span className="code-chip">{selCell.tag}</span>}
              </div>
              <CellActions school={selSchool} cell={selCell} onChanged={() => loadDetail(selSchool.id, true).then(load)} />
            </div>
            <div className="audit-detail-grid">
              <div>
                <div className="stat-k">Why</div>
                <div>{selCell.why}</div>
              </div>
              <div>
                <div className="stat-k">Last good data</div>
                <div>{selCell.last_label}</div>
              </div>
              <div>
                <div className="stat-k">Collected by</div>
                <div className={audience === "internal" ? "mono" : ""}>{selCell.collected_by}</div>
                <div className="cell-sub">Runs: {selCell.runs}</div>
                <div className="cell-sub">Stale after: {selCell.stale_after}</div>
              </div>
              <div>
                <div className="stat-k">Next step</div>
                <div>{selCell.next}</div>
              </div>
            </div>
          </>
        ) : (
          <div className="muted">{sel ? "Loading…" : "Select a cell"}</div>
        )}
      </section>
    </div>
  );
}

export function Pager({ page, pageCount, onPage }: { page: number; pageCount: number; onPage: (p: number) => void }) {
  return (
    <nav className="audit-pages" aria-label="Pages">
      <button type="button" className="btn" onClick={() => onPage(Math.max(0, page - 1))} disabled={page === 0}>
        Previous
      </button>
      {Array.from({ length: pageCount }, (_, i) => (
        <button key={i} type="button" className={`btn ${i === page ? "btn-primary" : ""}`} aria-label={`Page ${i + 1}`} aria-current={i === page ? "page" : undefined} onClick={() => onPage(i)}>
          {i + 1}
        </button>
      ))}
      <button type="button" className="btn" onClick={() => onPage(Math.min(pageCount - 1, page + 1))} disabled={page >= pageCount - 1}>
        Next
      </button>
    </nav>
  );
}
