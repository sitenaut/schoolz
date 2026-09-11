import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiFetch } from "../api";
import { IconChevronLeft } from "../components/icons";

type ScheduledJob = {
  id: string;
  kind: string;
  name: string;
  cron_expr: string;
  timezone: string;
  enabled: boolean;
  last_run_at: string | null;
  last_status: string | null;
  last_error: string | null;
  last_error_code: string | null;
  next_run_at: string | null;
};

const STATUS_LABEL: Record<string, string> = {
  success: "✅ Pass",
  warning: "⚠️ Warning",
  error: "❌ Failed",
  skipped: "⏭️ Skipped",
  running: "⏳ Running",
};

const STATUS_COLOR: Record<string, string> = {
  success: "#1a7f37",
  warning: "#9a6700",
  error: "#cf222e",
  skipped: "#6e7781",
  running: "#0969da",
};

export function JobsPage() {
  const [jobs, setJobs] = useState<ScheduledJob[]>([]);
  const [kindFilter, setKindFilter] = useState("");

  useEffect(() => {
    apiFetch("/scheduled-jobs")
      .then((r) => (r.ok ? r.json() : []))
      .then(setJobs);
  }, []);

  const kinds = Array.from(new Set(jobs.map((j) => j.kind))).sort();
  const filtered = kindFilter ? jobs.filter((j) => j.kind === kindFilter) : jobs;

  return (
    <div className="page" style={{ maxWidth: 900 }}>
      <Link to="/" className="back-link">
        <IconChevronLeft /> Home
      </Link>
      <h1>Scheduled Fetches</h1>
      <p className="item-desc">
        Every scan that pulls public information (district/school websites, lunch menus, handbooks, staff directories) - not Smore
        newsletters, which run on their own schedule.
      </p>

      <select value={kindFilter} onChange={(e) => setKindFilter(e.target.value)} style={{ marginBottom: 16 }}>
        <option value="">All kinds ({jobs.length})</option>
        {kinds.map((k) => (
          <option key={k} value={k}>
            {k} ({jobs.filter((j) => j.kind === k).length})
          </option>
        ))}
      </select>

      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr>
            <th style={{ textAlign: "left", borderBottom: "1px solid var(--color-border, #ddd)", padding: "6px 8px" }}>Job</th>
            <th style={{ textAlign: "left", borderBottom: "1px solid var(--color-border, #ddd)", padding: "6px 8px" }}>Kind</th>
            <th style={{ textAlign: "left", borderBottom: "1px solid var(--color-border, #ddd)", padding: "6px 8px" }}>Schedule</th>
            <th style={{ textAlign: "left", borderBottom: "1px solid var(--color-border, #ddd)", padding: "6px 8px" }}>Last run</th>
            <th style={{ textAlign: "left", borderBottom: "1px solid var(--color-border, #ddd)", padding: "6px 8px" }}>Result</th>
            <th style={{ textAlign: "left", borderBottom: "1px solid var(--color-border, #ddd)", padding: "6px 8px" }}>Next run</th>
          </tr>
        </thead>
        <tbody>
          {filtered.map((j) => (
            <tr key={j.id} style={{ borderBottom: "1px solid var(--color-border, #eee)" }}>
              <td style={{ padding: "6px 8px" }}>{j.name}</td>
              <td style={{ padding: "6px 8px" }}>{j.kind}</td>
              <td style={{ padding: "6px 8px" }}>{j.enabled ? j.cron_expr : "disabled"}</td>
              <td style={{ padding: "6px 8px" }}>{j.last_run_at ? new Date(j.last_run_at).toLocaleString() : "never"}</td>
              <td style={{ padding: "6px 8px" }}>
                {j.last_status ? (
                  <span style={{ color: STATUS_COLOR[j.last_status] ?? "inherit" }} title={j.last_error ?? undefined}>
                    {STATUS_LABEL[j.last_status] ?? j.last_status}
                  </span>
                ) : (
                  "—"
                )}
                {j.last_error_code && (
                  <code
                    style={{
                      marginLeft: 6,
                      fontSize: "0.8em",
                      padding: "1px 6px",
                      borderRadius: 4,
                      background: "var(--color-surface-muted, #f0f0f0)",
                      color: "var(--color-text-muted, #57606a)",
                    }}
                  >
                    {j.last_error_code}
                  </code>
                )}
                {j.last_error && <div className="item-desc">{j.last_error}</div>}
              </td>
              <td style={{ padding: "6px 8px" }}>{j.next_run_at ? new Date(j.next_run_at).toLocaleString() : "—"}</td>
            </tr>
          ))}
          {filtered.length === 0 && (
            <tr>
              <td colSpan={6} style={{ textAlign: "center", color: "var(--color-text-muted)" }}>
                No jobs found.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
