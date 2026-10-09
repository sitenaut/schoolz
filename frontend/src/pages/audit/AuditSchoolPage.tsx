import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Badge } from "../../components/ui/Badge";
import { useToast } from "../../components/ui/Toast";
import { getSchoolAudit, runAllScans, type AuditStatus, type SchoolAudit } from "./auditApi";
import { CellActions } from "./AuditCell";
import { AudienceToggle, useAudit } from "./AuditShell";
import { GAP_STATUSES, pctLabel, STATUS_META } from "./auditLib";

type Tab = "gaps" | "ok" | "na";
const IN_TAB: Record<Tab, (s: AuditStatus) => boolean> = {
  gaps: (s) => GAP_STATUSES.includes(s),
  ok: (s) => s === "current",
  na: (s) => s === "not_applicable",
};
const RANK: Record<AuditStatus, number> = { failing: 0, stale: 1, not_collecting: 2, current: 3, not_applicable: 4 };

export function AuditSchoolPage() {
  const { schoolId = "" } = useParams();
  const { audience, showActions } = useAudit();
  const toast = useToast();
  const [data, setData] = useState<SchoolAudit | null>(null);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<Tab>("gaps");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    getSchoolAudit(schoolId, audience)
      .then((d) => {
        setData(d);
        setError("");
      })
      .catch((e: Error) => setError(e.message));
  }, [schoolId, audience]);
  useEffect(load, [load]);

  if (error) return <div className="form-error">{error}</div>;
  if (!data) return <div className="muted">Loading…</div>;
  const s = data.school;
  const c = s.counts;
  const rows = data.data_points
    .map((p) => ({ p, cell: s.cells[p.key] }))
    .filter((r) => IN_TAB[tab](r.cell.status))
    .sort((a, b) => RANK[a.cell.status] - RANK[b.cell.status] || a.p.order - b.p.order);

  const runAll = async () => {
    setBusy(true);
    try {
      const res = await runAllScans(s.id);
      toast({ title: `${res.started.length} scans started`, description: "Results show up under Scans as each finishes.", tone: "ok" });
    } catch (e) {
      toast({ title: (e as Error).message, tone: "bad" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="audit">
      <nav className="audit-crumbs" aria-label="Breadcrumb">
        <Link to="/admin/audit">Audit</Link>
        <span aria-hidden="true">/</span>
        {s.district_id ? <Link to={`/admin/audit?district=${s.district_id}`}>{s.district_name}</Link> : <span>No district</span>}
        <span aria-hidden="true">/</span>
        <span>{s.name}</span>
      </nav>
      <div className="audit-hd">
        <div className="audit-hd-l">
          <h1>{s.name}</h1>
          <div className="ph-sub">
            {s.kind_label} school · {s.district_name ?? "No district"}
          </div>
        </div>
        <div className="audit-hd-a no-print">
          <AudienceToggle />
          {showActions && (
            <button className="btn" onClick={runAll} disabled={busy}>
              Run all scans
            </button>
          )}
          <Link className="btn btn-primary" to={`/admin/audit/schools/${s.slug}/report`}>
            Missing-data report
          </Link>
        </div>
      </div>

      <section className="audit-card audit-pad audit-summary" aria-label="Summary">
        <div>
          <div className="stat-k">Compliant</div>
          <div className="stat-v">{pctLabel(c.pct)}</div>
          <div className="cell-sub">
            {c.current} of {c.applicable} applicable data points
          </div>
        </div>
        <div className="audit-summary-counts">
          <span>
            <strong>{c.current}</strong> current
          </span>
          <span>
            <strong>{c.failing}</strong> failing
          </span>
          <span>
            <strong>{c.stale}</strong> stale
          </span>
          <span>
            <strong>{c.not_collecting}</strong> not collecting
          </span>
          <span>
            <strong>{c.not_applicable}</strong> not applicable, left out of the score
          </span>
        </div>
      </section>

      <section className="audit-card" aria-label="Data points">
        <div className="tabs audit-tabs audit-card-tabs" role="tablist">
          {(
            [
              ["gaps", `Needs attention (${c.failing + c.stale + c.not_collecting})`],
              ["ok", `Current (${c.current})`],
              ["na", `Not applicable (${c.not_applicable})`],
            ] as [Tab, string][]
          ).map(([k, label]) => (
            <button key={k} type="button" role="tab" aria-selected={tab === k} className={`tab ${tab === k ? "active" : ""}`} onClick={() => setTab(k)}>
              {label}
            </button>
          ))}
        </div>
        <div className="audit-grid-wrap">
          <table className="dt audit-school-table">
            <thead>
              <tr>
                <th>Data point</th>
                <th>Status</th>
                <th>Why</th>
                <th>Collected by</th>
                <th>Next step</th>
                {showActions && <th className="no-print" />}
              </tr>
            </thead>
            <tbody>
              {rows.map(({ p, cell }) => (
                <tr key={p.key}>
                  <td className="cell-title">{p.label}</td>
                  <td>
                    <Badge tone={STATUS_META[cell.status].tone}>{STATUS_META[cell.status].label}</Badge>
                    {cell.tag && <div className="cell-sub">{cell.tag}</div>}
                  </td>
                  <td>{cell.why}</td>
                  <td>
                    <div className={audience === "internal" ? "mono" : ""}>{cell.collected_by}</div>
                    <div className="cell-sub">
                      {cell.runs} · stale after {cell.stale_after}
                    </div>
                  </td>
                  <td>{cell.next}</td>
                  {showActions && (
                    <td className="no-print">
                      {cell.status !== "not_applicable" && cell.status !== "current" && <CellActions school={s} cell={cell} onChanged={load} />}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
          {!rows.length && <div className="dt-empty">Nothing here.</div>}
        </div>
      </section>
    </div>
  );
}
