import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiFetch, downloadFile } from "../api";
import { IconInbox, IconJobs, IconMail, IconNewsletter, IconSchool, IconSettings, IconTransfer } from "../components/icons";
import { PageHeader } from "../components/ui/PageHeader";
import { SectionCard } from "../components/ui/SectionCard";
import { useToast } from "../components/ui/Toast";
import { listSubmissions } from "./submissions/submissionsApi";
import { loadCampaignReport, loadPageVisits, loadSurveySummary, type CampaignReport, type PageVisitReport } from "./survey/surveyApi";

type Summary = { total: number; by_status: Record<string, number>; scheduler_last_seen_at: string | null };

// The scheduler stamps its heartbeat every 30s; past this it is down or
// stuck, and every scan has stopped (the schoolz-scheduler-down alert agrees).
const SCHEDULER_STALE_SECONDS = 300;

function ago(seconds: number): string {
  if (seconds < 90) return `${Math.max(0, Math.round(seconds))}s ago`;
  if (seconds < 5400) return `${Math.round(seconds / 60)}m ago`;
  if (seconds < 172800) return `${Math.round(seconds / 3600)}h ago`;
  return `${Math.round(seconds / 86400)}d ago`;
}

function FunnelRow({ label, count }: { label: string; count: number }) {
  return (
    <div className="funnel-row">
      <span>{label}</span>
      <b>{count}</b>
    </div>
  );
}

export function AdminOverviewPage() {
  const toast = useToast();
  const [summary, setSummary] = useState<Summary | null>(null);
  // Seconds since the scheduler's last tick, measured when the summary loads.
  const [schedulerAge, setSchedulerAge] = useState<number | null>(null);
  const [downloading, setDownloading] = useState(false);
  const [pendingSubmissions, setPendingSubmissions] = useState<number | null>(null);
  const [surveyCount, setSurveyCount] = useState<number | null>(null);
  const [visits, setVisits] = useState<PageVisitReport | null>(null);
  const [campaign, setCampaign] = useState<CampaignReport | null>(null);

  useEffect(() => {
    apiFetch("/scheduled-jobs/runs/summary")
      .then((r) => (r.ok ? r.json() : null))
      .then((data: Summary | null) => {
        setSummary(data);
        const seen = data?.scheduler_last_seen_at;
        setSchedulerAge(seen ? (Date.now() - new Date(seen).getTime()) / 1000 : null);
      })
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
    loadCampaignReport()
      .then(setCampaign)
      .catch(() => setCampaign(null));
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
      <PageHeader upperTitle="Admin" title="Overview" subtitle="Scan health, campaign traffic, and shortcuts into the admin tools." />
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
          <div className="stat" title="When the scheduler last checked in. It does every 30 seconds; if this is stale, no scan is running.">
            <span className="stat-k">Scheduler seen</span>
            <span className={`stat-v ${schedulerAge === null ? "" : schedulerAge > SCHEDULER_STALE_SECONDS ? "bad" : "ok"}`}>
              {!summary ? "—" : schedulerAge === null ? "never" : ago(schedulerAge)}
            </span>
          </div>
        </div>
      </SectionCard>

      <SectionCard
        title="Campaign"
        description="How the Facebook post - and everything downstream of it - is doing. Counted server-side, so ad blockers don't hide it."
        icon={<IconTransfer />}
      >
        {!campaign || campaign.total_visits === 0 ? (
          <p className="note" style={{ margin: 0 }}>
            No visits recorded yet.
          </p>
        ) : (
          <>
            <div className="stats" style={{ marginBottom: 4 }}>
              <div className="stat">
                <span className="stat-k">Total visits</span>
                <span className="stat-v">{campaign.total_visits}</span>
              </div>
              <div className="stat">
                <span className="stat-k">Today</span>
                <span className="stat-v">{campaign.visits_today}</span>
              </div>
              <div className="stat">
                <span className="stat-k">Yesterday</span>
                <span className="stat-v">{campaign.visits_yesterday}</span>
              </div>
              <div className="stat">
                <span className="stat-k">From Facebook</span>
                <span className="stat-v">{campaign.by_source.facebook ?? 0}</span>
              </div>
              <div className="stat">
                <span className="stat-k">Direct</span>
                <span className="stat-v">{campaign.by_source.direct ?? 0}</span>
              </div>
            </div>

            <div className="section-title">Funnel</div>
            <div className="funnel">
              <FunnelRow label="Read the write-up (/chcomms)" count={campaign.chcomms_reads} />
              <FunnelRow label="Opened the survey" count={campaign.survey_opened} />
              <FunnelRow label="Completed the survey" count={campaign.survey_completed} />
              <FunnelRow label="Picked their schools (/start)" count={campaign.start_page_visits} />
            </div>

            <div className="section-title">Newsletters submitted via Contact</div>
            <div className="stats" style={{ marginBottom: 4 }}>
              <div className="stat">
                <span className="stat-k">Total</span>
                <span className="stat-v">{campaign.newsletters_submitted}</span>
              </div>
              <div className="stat">
                <span className="stat-k">Pending review</span>
                <span className={`stat-v ${campaign.newsletters_pending ? "warn" : "ok"}`}>
                  {campaign.newsletters_pending}
                </span>
              </div>
            </div>

            {visits && visits.rows.length > 0 && (
              <details style={{ marginTop: 12 }}>
                <summary>Day-by-day / page / source detail</summary>
                <table className="table" style={{ marginTop: 8 }}>
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
              </details>
            )}
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
          <Link className="link-card" to="/admin/email">
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
