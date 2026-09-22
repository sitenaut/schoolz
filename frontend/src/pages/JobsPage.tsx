import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Badge, StatusBadge } from "../components/ui/Badge";
import { ConfirmDialog } from "../components/ui/ConfirmDialog";
import { DataTable, type Column } from "../components/ui/DataTable";
import { PageHeader } from "../components/ui/PageHeader";
import { Switch } from "../components/ui/Switch";
import { useToast } from "../components/ui/Toast";
import { IconEdit, IconInfo, IconPlay, IconPlus, IconRefresh, IconSearch, IconTrash } from "../components/icons";
import { describeCron } from "../lib/cron";
import { fmtDateTime, fmtDuration, relativeTime } from "../lib/format";
import { trackEvent } from "../lib/track";
import type { JobKind, ScheduledJob } from "../types";
import { JobDetailModal } from "./jobs/JobDetailModal";
import { JobFormModal } from "./jobs/JobFormModal";
import { BillzImportModal } from "./jobs/BillzImportModal";
import { deleteJob, getJob, listJobs, listKinds, loadTargetOptions, runJobNow, updateJob } from "./jobs/jobsApi";

type StatusFilter = "" | "success" | "warning" | "error" | "running" | "never";

const POLL_MS = 3000;
const POLL_MAX = 60; // ~3 minutes - vision extraction on a big newsletter is the slow case

export function JobsPage() {
  const toast = useToast();
  const [jobs, setJobs] = useState<ScheduledJob[]>([]);
  const [kinds, setKinds] = useState<JobKind[]>([]);
  const [targets, setTargets] = useState<Record<string, { id: string; label: string }[]>>({});
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState("");
  const [kindFilter, setKindFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("");
  const [enabledFilter, setEnabledFilter] = useState<"" | "on" | "off">("");
  const [detail, setDetail] = useState<{ job: ScheduledJob; tab: "runs" | "overview" } | null>(null);
  const [form, setForm] = useState<{ open: boolean; job: ScheduledJob | null }>({ open: false, job: null });
  const [pendingDelete, setPendingDelete] = useState<ScheduledJob | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [running, setRunning] = useState<Set<string>>(new Set());
  const [toggling, setToggling] = useState<Set<string>>(new Set());
  const pollers = useRef(new Map<string, number>());

  const refresh = useCallback(async () => {
    try {
      setJobs(await listJobs());
    } catch (e) {
      toast({ title: "Could not load jobs", description: e instanceof Error ? e.message : undefined, tone: "bad" });
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    refresh();
    listKinds().then(setKinds).catch(() => setKinds([]));
    loadTargetOptions().then(setTargets).catch(() => setTargets({}));
    return () => pollers.current.forEach((t) => window.clearTimeout(t));
  }, [refresh]);

  const patchLocal = (updated: ScheduledJob) => {
    setJobs((cur) => cur.map((j) => (j.id === updated.id ? updated : j)));
    setDetail((cur) => (cur && cur.job.id === updated.id ? { ...cur, job: updated } : cur));
  };

  // Run-now is fire-and-forget on the backend; poll this one job until its
  // last_run_at moves past the click (or it stops reporting "running").
  const runNow = async (job: ScheduledJob) => {
    if (running.has(job.id)) return;
    const before = job.last_run_at;
    setRunning((s) => new Set(s).add(job.id));
    trackEvent("action", { action: "job_run_now", method: "click" });
    try {
      await runJobNow(job.id);
    } catch (e) {
      setRunning((s) => {
        const n = new Set(s);
        n.delete(job.id);
        return n;
      });
      toast({ title: "Could not start job", description: e instanceof Error ? e.message : undefined, tone: "bad" });
      return;
    }
    let attempts = 0;
    const tick = async () => {
      attempts += 1;
      try {
        const fresh = await getJob(job.id);
        patchLocal(fresh);
        const finished = fresh.last_run_at !== before && fresh.last_status !== "running";
        if (finished || attempts >= POLL_MAX) {
          pollers.current.delete(job.id);
          setRunning((s) => {
            const n = new Set(s);
            n.delete(job.id);
            return n;
          });
          if (finished) {
            const tone = fresh.last_status === "success" ? "ok" : fresh.last_status === "warning" ? "warn" : "bad";
            toast({
              title: `${fresh.name}: ${fresh.last_status}`,
              description: fresh.last_error ?? (fresh.last_duration_ms != null ? `Finished in ${fmtDuration(fresh.last_duration_ms)}` : undefined),
              tone,
            });
          } else {
            toast({ title: "Still running", description: "The job is taking a while - check back on its Runs tab.", tone: "warn" });
          }
          return;
        }
      } catch {
        /* transient - keep polling */
      }
      pollers.current.set(job.id, window.setTimeout(tick, POLL_MS));
    };
    pollers.current.set(job.id, window.setTimeout(tick, POLL_MS));
  };

  const toggleEnabled = async (job: ScheduledJob, enabled: boolean) => {
    setToggling((s) => new Set(s).add(job.id));
    try {
      patchLocal(await updateJob(job.id, { enabled }));
    } catch (e) {
      toast({ title: "Could not update job", description: e instanceof Error ? e.message : undefined, tone: "bad" });
    } finally {
      setToggling((s) => {
        const n = new Set(s);
        n.delete(job.id);
        return n;
      });
    }
  };

  const confirmDelete = async () => {
    if (!pendingDelete) return;
    setDeleting(true);
    try {
      await deleteJob(pendingDelete.id);
      setJobs((cur) => cur.filter((j) => j.id !== pendingDelete.id));
      setDetail((cur) => (cur?.job.id === pendingDelete.id ? null : cur));
      toast({ title: "Job deleted", description: pendingDelete.name, tone: "ok" });
      setPendingDelete(null);
    } catch (e) {
      toast({ title: "Could not delete job", description: e instanceof Error ? e.message : undefined, tone: "bad" });
    } finally {
      setDeleting(false);
    }
  };

  const counts = useMemo(() => {
    const c = { total: jobs.length, success: 0, warning: 0, error: 0, running: 0, never: 0, disabled: 0 };
    for (const j of jobs) {
      if (!j.enabled) c.disabled += 1;
      const s = running.has(j.id) ? "running" : (j.last_status ?? "never");
      if (s in c) (c as Record<string, number>)[s] += 1;
    }
    return c;
  }, [jobs, running]);

  const kindsInUse = useMemo(() => Array.from(new Set(jobs.map((j) => j.kind))).sort(), [jobs]);

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return jobs.filter((j) => {
      if (kindFilter && j.kind !== kindFilter) return false;
      if (enabledFilter === "on" && !j.enabled) return false;
      if (enabledFilter === "off" && j.enabled) return false;
      const status = running.has(j.id) ? "running" : (j.last_status ?? "never");
      if (statusFilter && status !== statusFilter) return false;
      if (needle) {
        const hay = `${j.name} ${j.kind} ${j.target_label ?? ""} ${j.last_error_code ?? ""} ${j.description ?? ""}`.toLowerCase();
        if (!hay.includes(needle)) return false;
      }
      return true;
    });
  }, [jobs, q, kindFilter, statusFilter, enabledFilter, running]);

  const columns: Column<ScheduledJob>[] = [
    {
      id: "job",
      header: "Job",
      sortValue: (j) => j.name.toLowerCase(),
      cell: (j) => (
        <>
          <div className="cell-title">{j.name}</div>
          <div className="cell-sub">
            <span className="code-chip">{j.kind}</span>
            {j.target_label && (
              <span>
                {j.target_type}: {j.target_label}
              </span>
            )}
          </div>
        </>
      ),
    },
    {
      id: "schedule",
      header: "Schedule",
      sortValue: (j) => j.cron_expr,
      cell: (j) => (
        <>
          <div>{describeCron(j.cron_expr)}</div>
          <div className="cell-sub">
            <span className="mono">{j.cron_expr}</span>
            <span>{j.timezone.replace("America/", "")}</span>
          </div>
        </>
      ),
    },
    {
      id: "last",
      header: "Last run",
      sortValue: (j) => j.last_run_at ?? "",
      cell: (j) => {
        const isRunning = running.has(j.id);
        return (
          <button
            className="btn subtle sm"
            style={{ display: "inline-flex", flexDirection: "column", alignItems: "flex-start", gap: 2, borderRadius: 8 }}
            onClick={(e) => {
              e.stopPropagation();
              setDetail({ job: j, tab: "runs" });
            }}
            title="See run history and the full reason for any warning or failure"
          >
            <span style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
              <StatusBadge status={isRunning ? "running" : j.last_status} />
              {!isRunning && j.last_error_code && <span className="code-chip">{j.last_error_code}</span>}
            </span>
            <span className="cell-sub" title={fmtDateTime(j.last_run_at)}>
              {j.last_run_at ? relativeTime(j.last_run_at) : "never"}
              {j.last_duration_ms != null && ` · ${fmtDuration(j.last_duration_ms)}`}
            </span>
          </button>
        );
      },
    },
    {
      id: "next",
      header: "Next run",
      sortValue: (j) => (j.enabled ? (j.next_run_at ?? "") : "~"),
      cell: (j) =>
        j.enabled ? (
          <span title={fmtDateTime(j.next_run_at)}>{j.next_run_at ? relativeTime(j.next_run_at) : "—"}</span>
        ) : (
          <Badge tone="muted" dot={false}>
            paused
          </Badge>
        ),
    },
    {
      id: "enabled",
      header: "On",
      width: "56px",
      cell: (j) => <Switch checked={j.enabled} disabled={toggling.has(j.id)} onChange={(v) => toggleEnabled(j, v)} label={`Enable ${j.name}`} />,
    },
  ];

  return (
    <>
      <PageHeader
        upperTitle="Admin"
        title="Scheduled jobs"
        subtitle="Every scan that keeps the site current - district feeds, school sites, newsletters, lunch menus, email scanners. Start one, pause one, or open a row to see exactly why it warned or failed."
        actions={
          <>
            <button className="btn" onClick={refresh} title="Refresh">
              <IconRefresh /> Refresh
            </button>
            <button className="btn" onClick={() => setImportOpen(true)} title="Import local events jobs from billz">
              Import from billz
            </button>
            <button className="btn btn-primary" onClick={() => setForm({ open: true, job: null })}>
              <IconPlus /> New job
            </button>
          </>
        }
      />

      <div className="stats">
        {(
          [
            ["", "All jobs", counts.total, ""],
            ["success", "Healthy", counts.success, "ok"],
            ["warning", "Warnings", counts.warning, "warn"],
            ["error", "Failing", counts.error, "bad"],
            ["never", "Never run", counts.never, ""],
          ] as [StatusFilter, string, number, string][]
        ).map(([key, label, value, tone]) => (
          <button key={label} className="stat" aria-pressed={statusFilter === key} onClick={() => setStatusFilter(statusFilter === key ? "" : key)}>
            <span className="stat-k">{label}</span>
            <span className={`stat-v ${tone}`}>{value}</span>
          </button>
        ))}
      </div>

      <div className="tb">
        <div className="search">
          <IconSearch />
          <input placeholder="Search jobs, schools, error codes…" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <select value={kindFilter} onChange={(e) => setKindFilter(e.target.value)} aria-label="Filter by kind">
          <option value="">All kinds</option>
          {kindsInUse.map((k) => (
            <option key={k} value={k}>
              {k}
            </option>
          ))}
        </select>
        <select value={enabledFilter} onChange={(e) => setEnabledFilter(e.target.value as "" | "on" | "off")} aria-label="Filter by enabled">
          <option value="">Enabled + paused</option>
          <option value="on">Enabled only</option>
          <option value="off">Paused only</option>
        </select>
        <span className="spacer" />
        <span className="tb-count">
          {filtered.length} of {jobs.length}
        </span>
      </div>

      <DataTable
        columns={columns}
        rows={filtered}
        getRowId={(j) => j.id}
        loading={loading}
        defaultSort={{ id: "job", dir: "asc" }}
        onRowClick={(j) => setDetail({ job: j, tab: "overview" })}
        empty={jobs.length === 0 ? "No jobs yet - create one, or add a school/district and its scans are created automatically." : "No jobs match these filters."}
        rowActions={(j) => (
          <>
            <button className={`btn icon ${running.has(j.id) ? "spin" : ""}`} title="Run now" onClick={() => runNow(j)} disabled={running.has(j.id)}>
              {running.has(j.id) ? <IconRefresh /> : <IconPlay />}
            </button>
            <button className="btn icon" title="Details & run history" onClick={() => setDetail({ job: j, tab: "runs" })}>
              <IconInfo />
            </button>
            <button className="btn icon" title="Edit" onClick={() => setForm({ open: true, job: j })}>
              <IconEdit />
            </button>
            <button className="btn icon danger" title="Delete" onClick={() => setPendingDelete(j)}>
              <IconTrash />
            </button>
          </>
        )}
      />

      <JobDetailModal
        job={detail?.job ?? null}
        initialTab={detail?.tab}
        running={detail ? running.has(detail.job.id) : false}
        onClose={() => setDetail(null)}
        onRun={runNow}
        onEdit={(j) => setForm({ open: true, job: j })}
      />

      <JobFormModal
        open={form.open}
        job={form.job}
        kinds={kinds}
        targets={targets}
        onClose={() => setForm({ open: false, job: null })}
        onSaved={(saved) => {
          if (form.job) patchLocal(saved);
          else setJobs((cur) => [...cur, saved]);
          toast({ title: form.job ? "Job updated" : "Job created", description: saved.name, tone: "ok" });
        }}
      />

      <BillzImportModal
        open={importOpen}
        onClose={() => setImportOpen(false)}
        onImported={(created) => {
          setJobs((cur) => [...cur, ...created]);
          toast({ title: `Imported ${created.length} job${created.length === 1 ? "" : "s"} from billz`, tone: "ok" });
        }}
      />

      <ConfirmDialog
        open={Boolean(pendingDelete)}
        title="Delete this job?"
        description={
          <>
            <b>{pendingDelete?.name}</b> will stop running and its run history goes with it. The school, district, or newsletter it scans is not
            affected - it just won't be refreshed until a new job is created.
          </>
        }
        confirmLabel="Delete job"
        danger
        busy={deleting}
        onConfirm={confirmDelete}
        onCancel={() => setPendingDelete(null)}
      />
    </>
  );
}
