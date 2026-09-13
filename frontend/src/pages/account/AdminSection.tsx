import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiFetch, downloadFile } from "../../api";
import { IconInbox, IconJobs, IconMail, IconNewsletter, IconSchool, IconSettings, IconTransfer } from "../../components/icons";
import { SectionCard } from "../../components/ui/SectionCard";
import { useToast } from "../../components/ui/Toast";
import { listSubmissions } from "../submissions/submissionsApi";
import { loadPageVisits, loadSurveySummary, type PageVisitReport } from "../survey/surveyApi";

type Summary = { total: number; by_status: Record<string, number> };

export function AdminSection() {
  const toast = useToast();
  const [summary, setSummary] = useState<Summary | null>(null);
  const [downloading, setDownloading] = useState(false);
  const [pendingSubmissions, setPendingSubmissions] = useState<number | null>(null);
  const [surveyCount, setSurveyCount] = useState<number | null>(null);
  const [visits, setVisits] = useState<PageVisitReport | null>(null);

  useEffect(() => {
    apiFetch("/scheduled-jobs/runs/summary")
      .then((r) => (r.ok ? r.json() : null))
      .then(setSummary)
      .catch(() => setSummary(null));
    listSubmissions("pending")
      .then((rows) => setPendingSubmissions(rows.length))
      .catch(() => setPendingSubmissions(null));
    loadSurveySummary()
      .then((s) => setSurveyCount(s?.total ?? null))
      .catch(() => setSurveyCount(null));
    loadPageVisits(30)
      .then(setVisits)
      .catch(() => setVisits(null));
  }, []);

  async function downloadSurveyCsv() {
    setDownloading(true);
    try {
      await downloadFile("/survey/responses.csv", "schoolz-survey-responses.csv");
    } catch (e) {
      toast({
        title: "Could not download the survey responses",
        description: e instanceof Error ? e.message : undefined,
        tone: "bad",
      });
    } finally {
      setDownloading(false);
    }
  }

  const s = summary?.by_status ?? {};
  return (
    <>
      <SectionCard title="Scan health" description="Enabled jobs by their last result." icon={<IconJobs />} actions={<Link className="btn sm" to="/admin/scans">Open jobs</Link>}>
        <div className="stats" style={{ marginBottom: 0 }}>
          <Link className="stat" to="/admin/scans">
            <span className="stat-k">Enabled</span>
            <span className="stat-v">{summary?.total ?? "—"}</span>
          </Link>
          <Link className="stat" to="/admin/scans">
            <span className="stat-k">Healthy</span>
            <span className="stat-v ok">{s.success ?? 0}</span>
          </Link>
          <Link className="stat" to="/admin/scans">
            <span className="stat-k">Warnings</span>
            <span className="stat-v warn">{s.warning ?? 0}</span>
          </Link>
          <Link className="stat" to="/admin/scans">
            <span className="stat-k">Failing</span>
            <span className="stat-v bad">{s.error ?? 0}</span>
          </Link>
        </div>
      </SectionCard>

      <SectionCard
        title="Traffic"
        description="Visits to the public pages over the last 30 days, by where people came from. Counted server-side, so ad blockers don't hide them."
        icon={<IconTransfer />}
      >
        {!visits || visits.rows.length === 0 ? (
          <p className="note" style={{ margin: 0 }}>
            No visits recorded yet.
          </p>
        ) : (
          <>
            <div className="stats" style={{ marginBottom: 12 }}>
              {["/chcomms", "/survey", "/"].map((path) => (
                <div className="stat" key={path}>
                  <span className="stat-k">{path}</span>
                  <span className="stat-v">{visits.totals_by_path[path] ?? 0}</span>
                </div>
              ))}
              <div className="stat">
                <span className="stat-k">From Facebook</span>
                <span className="stat-v">{visits.totals_by_source.facebook ?? 0}</span>
              </div>
            </div>
            <table className="table">
              <thead>
                <tr>
                  <th>Day</th>
                  <th>Page</th>
                  <th>Source</th>
                  <th style={{ textAlign: "right" }}>Visits</th>
                </tr>
              </thead>
              <tbody>
                {visits.rows.slice(0, 40).map((r) => (
                  <tr key={`${r.day}|${r.path}|${r.source}`}>
                    <td>{r.day}</td>
                    <td>{r.path}</td>
                    <td>{r.source}</td>
                    <td style={{ textAlign: "right" }}>{r.count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </SectionCard>

      <SectionCard title="Manage" description="The centrally-managed data sources every visitor sees." icon={<IconSettings />}>
        <div className="link-grid">
          <Link className="link-card" to="/admin/scans">
            <span className="ico">
              <IconJobs />
            </span>
            <span>
              <b>Scheduled jobs</b>
              <small>Create, pause, run, and debug scans</small>
            </span>
          </Link>
          <Link className="link-card" to="/admin/newsletters">
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
          <Link className="link-card" to="/admin/submissions">
            <span className="ico">
              <IconInbox />
            </span>
            <span>
              <b>
                Submissions inbox{" "}
                {Boolean(pendingSubmissions) && <span className="badge warn nodot">{pendingSubmissions}</span>}
              </b>
              <small>Fliers &amp; links the community sent in</small>
            </span>
          </Link>
          <button className="link-card" type="button" onClick={downloadSurveyCsv} disabled={downloading}>
            <span className="ico">
              <IconTransfer />
            </span>
            <span>
              <b>
                Survey responses{" "}
                {Boolean(surveyCount) && <span className="badge nodot">{surveyCount}</span>}
              </b>
              <small>{downloading ? "Preparing download…" : "Download every /survey answer as a spreadsheet"}</small>
            </span>
          </button>
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
