import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { Badge } from "../../components/ui/Badge";
import { useToast } from "../../components/ui/Toast";
import { downloadCsv, getAudit, getSchoolAudit, type AuditSchool, type AuditStatus, type CellDetail, type DataPointMeta } from "./auditApi";
import { AudienceToggle, useAudit } from "./AuditShell";
import {
  buildReportSections,
  countCells,
  districtReportText,
  filterSchools,
  filtersFromParams,
  fmtGenerated,
  GAP_STATUSES,
  pctLabel,
  REPORT_FOOTER,
  schoolGaps,
  schoolReportText,
  STATUS_META,
} from "./auditLib";

type Loaded = { generated: string; points: DataPointMeta[]; schools: AuditSchool<CellDetail>[]; districts: { id: string; name: string }[] };

/** Missing-data reports. /admin/audit/schools/:schoolId/report is one
 * school; /admin/audit/report is a district (?district=), or the By school
 * screen's current filters (?scope=filters&...). Same wording toggle as the
 * rest of the audit - a manager previews the district wording before
 * printing it for one. */
export function AuditReportPage() {
  const { schoolId } = useParams();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { audience } = useAudit();
  const toast = useToast();
  const [data, setData] = useState<Loaded | null>(null);
  const [error, setError] = useState("");
  const [include, setInclude] = useState<AuditStatus[]>(GAP_STATUSES);
  const byFilters = params.get("scope") === "filters";
  const districtId = schoolId ? "" : (params.get("district") ?? "");

  useEffect(() => {
    setData(null);
    const done = (d: Loaded) => {
      setData(d);
      setError("");
    };
    if (schoolId) {
      getSchoolAudit(schoolId, audience)
        .then((d) => done({ generated: d.generated_at, points: d.data_points, schools: [d.school], districts: [] }))
        .catch((e: Error) => setError(e.message));
    } else {
      getAudit<CellDetail>({ districtId: districtId || undefined, audience, detail: true })
        .then((d) =>
          done({ generated: d.generated_at, points: d.data_points, schools: byFilters ? filterSchools(d.schools, filtersFromParams(params)) : d.schools, districts: d.districts })
        )
        .catch((e: Error) => setError(e.message));
    }
  }, [schoolId, districtId, byFilters, audience, params]);

  const school = schoolId ? data?.schools[0] : undefined;
  const sections = useMemo(() => (data && !schoolId ? buildReportSections(data.schools, data.points, include) : []), [data, include, schoolId]);
  const districtName = data?.districts.find((d) => d.id === districtId)?.name;
  const title = school ? school.name : byFilters ? "Current audit filters" : (districtName ?? "All districts");
  const generated = data ? fmtGenerated(data.generated) : "";

  const copy = async () => {
    if (!data) return;
    const text = school ? schoolReportText(school, data.points, include, generated) : districtReportText(title, generated, data.schools, sections);
    try {
      await navigator.clipboard.writeText(text);
      toast({ title: "Report copied", tone: "ok" });
    } catch {
      toast({ title: "Couldn't copy - your browser blocked clipboard access", tone: "bad" });
    }
  };

  const csv = () =>
    downloadCsv({ districtId: school ? undefined : districtId || undefined, schoolId: school?.id, audience, statuses: include }).catch((e: Error) =>
      toast({ title: e.message, tone: "bad" })
    );

  const back = school ? { to: `/admin/audit/schools/${school.slug}`, label: `Back to ${school.name}` } : { to: "/admin/audit", label: "Back to audit" };

  return (
    <div className="audit audit-report-page">
      <div className="audit-report-bar no-print">
        <Link to={back.to}>{back.label}</Link>
        <div className="audit-hd-a">
          <AudienceToggle />
          <button className="btn" onClick={copy} disabled={!data}>
            Copy as text
          </button>
          <button className="btn" onClick={csv} disabled={!data}>
            Download CSV
          </button>
          <button className="btn btn-primary" onClick={() => window.print()} disabled={!data}>
            Print or save PDF
          </button>
        </div>
      </div>

      {!school && (
        <div className="audit-filters no-print">
          <label className="field">
            <span className="lbl">Report for</span>
            <select
              value={byFilters ? "__filters" : districtId}
              onChange={(e) => navigate(e.target.value === "__filters" ? `/admin/audit/report?${params.toString()}` : `/admin/audit/report${e.target.value ? `?district=${e.target.value}` : ""}`)}
            >
              <option value="">All districts</option>
              {data?.districts.map((d) => (
                <option key={d.id} value={d.id}>
                  District: {d.name}
                </option>
              ))}
              {byFilters && <option value="__filters">Current audit filters</option>}
            </select>
          </label>
          <IncludeBoxes include={include} setInclude={setInclude} />
        </div>
      )}
      {school && (
        <div className="audit-filters no-print">
          <IncludeBoxes include={include} setInclude={setInclude} />
        </div>
      )}

      {error && <div className="form-error">{error}</div>}
      {!data && !error && <div className="muted">Loading…</div>}
      {data && school && <SchoolReport school={school} points={data.points} include={include} generated={generated} />}
      {data && !school && <DistrictReport title={title} generated={generated} schools={data.schools} points={data.points} sections={sections} />}
    </div>
  );
}

function IncludeBoxes({ include, setInclude }: { include: AuditStatus[]; setInclude: (v: AuditStatus[]) => void }) {
  return (
    <fieldset className="audit-include">
      <legend>Include</legend>
      {GAP_STATUSES.map((s) => (
        <label key={s}>
          <input
            type="checkbox"
            checked={include.includes(s)}
            onChange={(e) => setInclude(e.target.checked ? GAP_STATUSES.filter((x) => x === s || include.includes(x)) : include.filter((x) => x !== s))}
          />
          {STATUS_META[s].label}
        </label>
      ))}
    </fieldset>
  );
}

function DistrictReport({
  title,
  generated,
  schools,
  points,
  sections,
}: {
  title: string;
  generated: string;
  schools: AuditSchool<CellDetail>[];
  points: DataPointMeta[];
  sections: ReturnType<typeof buildReportSections>;
}) {
  const n = countCells(schools.flatMap((s) => Object.values(s.cells)));
  const bySchool = [...schools].sort((a, b) => (a.counts.pct ?? 101) - (b.counts.pct ?? 101) || a.name.localeCompare(b.name));
  return (
    <article className="audit-report">
      <header>
        <div className="ph-upper">Missing-data report</div>
        <h1>{title}</h1>
        <div className="muted">
          {schools.length} schools · {points.length} data points audited · generated {generated}
        </div>
      </header>
      <section className="audit-report-tiles">
        <div>
          <strong>{pctLabel(n.pct)}</strong>
          <span>
            compliant, {n.current} of {n.applicable} data points
          </span>
        </div>
        <div>
          <strong>{n.failing}</strong>
          <span>failing</span>
        </div>
        <div>
          <strong>{n.stale}</strong>
          <span>stale</span>
        </div>
        <div>
          <strong>{n.not_collecting}</strong>
          <span>not collecting</span>
        </div>
      </section>
      {sections.map((sec) => (
        <section key={sec.status}>
          <h2>
            {sec.title} <span className="muted">· {sec.sub}</span>
          </h2>
          {sec.groups.length ? (
            <table className="audit-report-table">
              <thead>
                <tr>
                  <th>Data point</th>
                  <th>Schools</th>
                  <th>Why</th>
                  <th>Next step</th>
                </tr>
              </thead>
              <tbody>
                {sec.groups.map((g, i) => (
                  <tr key={i}>
                    <td className="cell-title">{g.label}</td>
                    <td>
                      <strong>{g.schools.length}:</strong> {g.schools.join(", ")}
                    </td>
                    <td>{g.why}</td>
                    <td>{g.next}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="muted">None.</p>
          )}
        </section>
      ))}
      <section>
        <h2>By school</h2>
        <table className="audit-report-table">
          <thead>
            <tr>
              <th>School</th>
              <th className="num">Compliant</th>
              <th className="num">Failing</th>
              <th className="num">Stale</th>
              <th className="num">Not collecting</th>
            </tr>
          </thead>
          <tbody>
            {bySchool.map((s) => (
              <tr key={s.id}>
                <td>{s.name}</td>
                <td className="num">{pctLabel(s.counts.pct)}</td>
                <td className="num">{s.counts.failing}</td>
                <td className="num">{s.counts.stale}</td>
                <td className="num">{s.counts.not_collecting}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <footer className="muted small">{REPORT_FOOTER}</footer>
    </article>
  );
}

function kindNoun(school: AuditSchool<CellDetail>): string {
  if (!school.kind) return "this school";
  if (school.kind === "preschool") return "a preschool";
  const label = school.kind_label.toLowerCase();
  return `${/^[aeiou]/.test(label) ? "an" : "a"} ${label} school`;
}

function SchoolReport({ school, points, include, generated }: { school: AuditSchool<CellDetail>; points: DataPointMeta[]; include: AuditStatus[]; generated: string }) {
  const gaps = schoolGaps(school, points, include);
  const c = school.counts;
  const ok = points.filter((p) => school.cells[p.key]?.status === "current").map((p) => p.label);
  const na = points.filter((p) => school.cells[p.key]?.status === "not_applicable").map((p) => p.label);
  return (
    <article className="audit-report">
      <header>
        <div className="ph-upper">Missing-data report</div>
        <h1>{school.name}</h1>
        <div className="muted">
          {school.district_name ?? "No district"} · generated {generated}
        </div>
      </header>
      <p>
        <strong>
          {c.current} of {c.applicable}
        </strong>{" "}
        applicable data points are current ({pctLabel(c.pct)}).{" "}
        <strong>{c.failing + c.stale + c.not_collecting} are missing:</strong> {c.failing} failing, {c.stale} stale, {c.not_collecting} not collected.
      </p>
      {gaps.length > 0 && (
        <table className="audit-report-table">
          <thead>
            <tr>
              <th>Data point</th>
              <th>Reason</th>
              <th>Why</th>
              <th>Next step</th>
            </tr>
          </thead>
          <tbody>
            {gaps.map(({ point, cell }) => (
              <tr key={point.key}>
                <td className="cell-title">{point.label}</td>
                <td>
                  <Badge tone={STATUS_META[cell.status].tone}>{STATUS_META[cell.status].label}</Badge>
                </td>
                <td>{cell.why}</td>
                <td>{cell.next}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <section>
        <h2>Current</h2>
        <p>{ok.length ? `${ok.join(", ")}.` : "None yet."}</p>
      </section>
      <section>
        <h2>Not applicable to {kindNoun(school)}</h2>
        <p>{na.length ? `${na.join(", ")}.` : "None."}</p>
      </section>
      <footer className="muted small">{REPORT_FOOTER}</footer>
    </article>
  );
}
