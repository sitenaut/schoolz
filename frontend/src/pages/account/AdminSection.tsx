import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiFetch } from "../../api";
import { IconJobs, IconMail, IconNewsletter, IconSchool, IconSettings, IconTransfer } from "../../components/icons";
import { SectionCard } from "../../components/ui/SectionCard";

type Summary = { total: number; by_status: Record<string, number> };

export function AdminSection() {
  const [summary, setSummary] = useState<Summary | null>(null);

  useEffect(() => {
    apiFetch("/scheduled-jobs/runs/summary")
      .then((r) => (r.ok ? r.json() : null))
      .then(setSummary)
      .catch(() => setSummary(null));
  }, []);

  const s = summary?.by_status ?? {};
  return (
    <>
      <SectionCard title="Scan health" description="Enabled jobs by their last result." icon={<IconJobs />} actions={<Link className="btn sm" to="/jobs">Open jobs</Link>}>
        <div className="stats" style={{ marginBottom: 0 }}>
          <Link className="stat" to="/jobs">
            <span className="stat-k">Enabled</span>
            <span className="stat-v">{summary?.total ?? "—"}</span>
          </Link>
          <Link className="stat" to="/jobs">
            <span className="stat-k">Healthy</span>
            <span className="stat-v ok">{s.success ?? 0}</span>
          </Link>
          <Link className="stat" to="/jobs">
            <span className="stat-k">Warnings</span>
            <span className="stat-v warn">{s.warning ?? 0}</span>
          </Link>
          <Link className="stat" to="/jobs">
            <span className="stat-k">Failing</span>
            <span className="stat-v bad">{s.error ?? 0}</span>
          </Link>
        </div>
      </SectionCard>

      <SectionCard title="Manage" description="The centrally-managed data sources every visitor sees." icon={<IconSettings />}>
        <div className="link-grid">
          <Link className="link-card" to="/jobs">
            <span className="ico">
              <IconJobs />
            </span>
            <span>
              <b>Scheduled jobs</b>
              <small>Create, pause, run, and debug scans</small>
            </span>
          </Link>
          <Link className="link-card" to="/smore">
            <span className="ico">
              <IconNewsletter />
            </span>
            <span>
              <b>Newsletters</b>
              <small>Tracked Smore sources</small>
            </span>
          </Link>
          <Link className="link-card" to="/schools">
            <span className="ico">
              <IconSchool />
            </span>
            <span>
              <b>Schools</b>
              <small>Directory and per-school details</small>
            </span>
          </Link>
          <Link className="link-card" to="/gmail">
            <span className="ico">
              <IconMail />
            </span>
            <span>
              <b>Email scanner</b>
              <small>Connect Gmail to catch newsletter links</small>
            </span>
          </Link>
          <Link className="link-card" to="/admin/config">
            <span className="ico">
              <IconTransfer />
            </span>
            <span>
              <b>Import / export</b>
              <small>Port setup between environments</small>
            </span>
          </Link>
        </div>
      </SectionCard>
    </>
  );
}
