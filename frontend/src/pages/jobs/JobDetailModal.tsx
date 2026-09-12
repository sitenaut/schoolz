import { useCallback, useEffect, useState } from "react";
import { Badge, StatusBadge } from "../../components/ui/Badge";
import { Modal } from "../../components/ui/Modal";
import { IconEdit, IconPlay, IconRefresh } from "../../components/icons";
import { describeCron } from "../../lib/cron";
import { fmtDateTime, fmtDuration, relativeTime } from "../../lib/format";
import type { JobRun, ScheduledJob } from "../../types";
import { listRuns } from "./jobsApi";

type Tab = "runs" | "overview";

type Props = {
  job: ScheduledJob | null;
  initialTab?: Tab;
  running: boolean;
  onClose: () => void;
  onRun: (job: ScheduledJob) => void;
  onEdit: (job: ScheduledJob) => void;
};

/** Everything about one job in one place - and, the reason it exists: the
 * full text of a run's warning or failure (error, error code + stage, and
 * the captured traceback/log excerpt), which is far too much for a table
 * cell. Runs tab opens by default when arriving from a status badge. */
export function JobDetailModal({ job, initialTab = "runs", running, onClose, onRun, onEdit }: Props) {
  const [tab, setTab] = useState<Tab>(initialTab);
  const [runs, setRuns] = useState<JobRun[]>([]);
  const [loading, setLoading] = useState(false);
  const [openRun, setOpenRun] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!job) return;
    setLoading(true);
    try {
      const data = await listRuns(job.id);
      setRuns(data);
      // Auto-expand the newest problem so the reason is visible without a click.
      const firstBad = data.find((r) => r.status === "error" || r.status === "warning");
      setOpenRun((cur) => cur ?? firstBad?.id ?? null);
    } finally {
      setLoading(false);
    }
  }, [job]);

  useEffect(() => {
    setTab(initialTab);
    setOpenRun(null);
    setRuns([]);
    if (job) load();
  }, [job?.id, initialTab, load, job]);

  // While a manual run is in flight the parent polls the job; refresh the
  // run list as it flips so the new row and its result show up live.
  useEffect(() => {
    if (job && !running) load();
  }, [running, job, load]);

  if (!job) return null;

  return (
    <Modal
      open={Boolean(job)}
      onClose={onClose}
      size="xl"
      title={job.name}
      subtitle={
        <>
          <span className="code-chip">{job.kind}</span>
          {job.target_label && (
            <Badge tone="info" dot={false}>
              {job.target_type}: {job.target_label}
            </Badge>
          )}
          <StatusBadge status={running ? "running" : job.last_status} />
          {job.last_error_code && <span className="code-chip">{job.last_error_code}</span>}
        </>
      }
      footer={
        <>
          <button className="btn" onClick={() => onEdit(job)}>
            <IconEdit /> Edit
          </button>
          <button className={`btn btn-primary ${running ? "spin" : ""}`} onClick={() => onRun(job)} disabled={running}>
            {running ? <IconRefresh /> : <IconPlay />} {running ? "Running…" : "Run now"}
          </button>
        </>
      }
    >
      <div className="utabs" role="tablist">
        <button role="tab" aria-selected={tab === "runs"} onClick={() => setTab("runs")}>
          Runs
        </button>
        <button role="tab" aria-selected={tab === "overview"} onClick={() => setTab("overview")}>
          Overview
        </button>
      </div>

      {tab === "overview" ? (
        <dl className="kv">
          <dt>Schedule</dt>
          <dd>
            {describeCron(job.cron_expr)} <span className="code-chip">{job.cron_expr}</span> · {job.timezone}
          </dd>
          <dt>Enabled</dt>
          <dd>{job.enabled ? "Yes" : "No - paused"}</dd>
          <dt>Next run</dt>
          <dd>{job.enabled && job.next_run_at ? `${relativeTime(job.next_run_at)} · ${fmtDateTime(job.next_run_at)}` : "—"}</dd>
          <dt>Last run</dt>
          <dd>
            {job.last_run_at ? `${relativeTime(job.last_run_at)} · ${fmtDateTime(job.last_run_at)}` : "never"}
            {job.last_duration_ms != null && ` · took ${fmtDuration(job.last_duration_ms)}`}
          </dd>
          {job.last_error && (
            <>
              <dt>Last error</dt>
              <dd className="run-err">{job.last_error}</dd>
            </>
          )}
          {job.description && (
            <>
              <dt>Description</dt>
              <dd>{job.description}</dd>
            </>
          )}
          <dt>Params</dt>
          <dd>
            <pre className="json">{JSON.stringify(job.params, null, 2)}</pre>
          </dd>
          <dt>Created</dt>
          <dd>{fmtDateTime(job.created_at)}</dd>
          <dt>Job id</dt>
          <dd>
            <span className="code-chip">{job.id}</span>
          </dd>
        </dl>
      ) : (
        <div className="runs">
          {loading && runs.length === 0 ? (
            <p className="note">Loading runs…</p>
          ) : runs.length === 0 ? (
            <div className="empty">This job hasn't run yet. Use "Run now" to trigger it.</div>
          ) : (
            runs.map((r) => {
              const isOpen = openRun === r.id;
              const problem = r.status === "error" || r.status === "warning";
              return (
                <div className="run" key={r.id}>
                  <button className="run-hd" onClick={() => setOpenRun(isOpen ? null : r.id)} aria-expanded={isOpen}>
                    <StatusBadge status={r.status} />
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontWeight: 700 }}>
                        {relativeTime(r.started_at)} <span style={{ color: "var(--ink-3)", fontWeight: 500 }}>· {fmtDateTime(r.started_at)}</span>
                      </div>
                      <div className="run-meta">
                        <span>{fmtDuration(r.duration_ms)}</span>
                        <span>{r.triggered_by === "manual" ? "manual" : "scheduled"}</span>
                        {r.error_code && <span className="code-chip">{r.error_code}</span>}
                        {r.error_stage && <span>stage: {r.error_stage}</span>}
                      </div>
                    </div>
                    <span style={{ color: "var(--ink-3)", fontSize: 12 }}>{isOpen ? "Hide" : problem ? "Why?" : "Details"}</span>
                  </button>
                  {isOpen && (
                    <div className="run-body">
                      {r.error && <div className="run-err">{r.error}</div>}
                      {r.log_excerpt ? (
                        r.status === "warning" && !r.error && !r.log_excerpt.includes("\n") ? (
                          // A warning's whole "log" is usually its one-line reason - no
                          // point printing it twice.
                          <div className="run-warn">{r.log_excerpt}</div>
                        ) : (
                          <pre className="log">{r.log_excerpt}</pre>
                        )
                      ) : (
                        !r.error && <p className="note" style={{ margin: 0 }}>No output was captured for this run.</p>
                      )}
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>
      )}
    </Modal>
  );
}
