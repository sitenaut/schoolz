import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Badge, StatusBadge } from "../components/ui/Badge";
import { ConfirmDialog } from "../components/ui/ConfirmDialog";
import { DataTable, type Column } from "../components/ui/DataTable";
import { PageHeader } from "../components/ui/PageHeader";
import { useToast } from "../components/ui/Toast";
import { IconEdit, IconInfo, IconPlay, IconPlus, IconRefresh, IconRefreshCw, IconSearch, IconTrash } from "../components/icons";
import { describeCron } from "../lib/cron";
import { relativeTime } from "../lib/format";
import type { SmoreNewsletter } from "../types";
import { NewsletterDetailModal } from "./smore/NewsletterDetailModal";
import { NewsletterFormModal } from "./smore/NewsletterFormModal";
import {
  deleteNewsletter,
  listNewsletters,
  loadTargets,
  reextractAll,
  runNewsletterNow,
  type TargetOption,
} from "./smore/smoreApi";

const POLL_MS = 5000;
const POLL_MAX = 36; // ~3 minutes - vision extraction on a big newsletter is the slow part
const STALE_DAYS = 8; // newsletters run weekly, so >8 days means a run was missed

function daysSince(iso: string | null): number | null {
  if (!iso) return null;
  return (Date.now() - new Date(iso).getTime()) / 86_400_000;
}

export function SmoreNewslettersPage() {
  const toast = useToast();
  const [newsletters, setNewsletters] = useState<SmoreNewsletter[]>([]);
  const [targets, setTargets] = useState<{ schools: TargetOption[]; districts: TargetOption[] }>({ schools: [], districts: [] });
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState("");
  const [statusFilter, setStatusFilter] = useState<"" | "stale" | "never" | "unscheduled">("");
  const [detailId, setDetailId] = useState<string | null>(null);
  const [form, setForm] = useState<{ open: boolean; newsletter: SmoreNewsletter | null }>({ open: false, newsletter: null });
  const [pendingDelete, setPendingDelete] = useState<SmoreNewsletter | null>(null);
  const [pendingReextract, setPendingReextract] = useState<SmoreNewsletter | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [reextracting, setReextracting] = useState(false);
  const [running, setRunning] = useState<Set<string>>(new Set());
  const pollers = useRef(new Map<string, number>());

  const refresh = useCallback(async () => {
    try {
      setNewsletters(await listNewsletters());
    } catch (e) {
      toast({ title: "Could not load newsletters", description: e instanceof Error ? e.message : undefined, tone: "bad" });
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    refresh();
    loadTargets().then(setTargets).catch(() => setTargets({ schools: [], districts: [] }));
    return () => pollers.current.forEach((t) => window.clearTimeout(t));
  }, [refresh]);

  const patchLocal = (updated: SmoreNewsletter) => setNewsletters((cur) => cur.map((n) => (n.id === updated.id ? updated : n)));

  const runNow = async (n: SmoreNewsletter) => {
    if (running.has(n.id) || !n.scheduled_job) return;
    const before = n.last_scanned_at;
    setRunning((s) => new Set(s).add(n.id));
    try {
      await runNewsletterNow(n.id);
    } catch (e) {
      setRunning((s) => {
        const next = new Set(s);
        next.delete(n.id);
        return next;
      });
      toast({ title: "Could not start scan", description: e instanceof Error ? e.message : undefined, tone: "bad" });
      return;
    }
    let attempts = 0;
    const tick = async () => {
      attempts += 1;
      try {
        const fresh = await listNewsletters();
        setNewsletters(fresh);
        const current = fresh.find((f) => f.id === n.id);
        const finished = current && current.last_scanned_at !== before;
        if (finished || attempts >= POLL_MAX) {
          pollers.current.delete(n.id);
          setRunning((s) => {
            const next = new Set(s);
            next.delete(n.id);
            return next;
          });
          if (finished && current) {
            const status = current.scheduled_job?.last_status;
            const tone = status === "success" ? "ok" : status === "warning" ? "warn" : status === "error" ? "bad" : "info";
            toast({
              title: `${current.label || current.url}: scan ${status ?? "finished"}`,
              description: current.scheduled_job?.last_error ?? current.latest_summary ?? undefined,
              tone,
            });
          } else {
            toast({ title: "Still scanning", description: "This can take a while on a large newsletter - check back shortly.", tone: "warn" });
          }
          return;
        }
      } catch {
        /* transient - keep polling */
      }
      pollers.current.set(n.id, window.setTimeout(tick, POLL_MS));
    };
    pollers.current.set(n.id, window.setTimeout(tick, POLL_MS));
  };

  const confirmReextract = async () => {
    if (!pendingReextract) return;
    setReextracting(true);
    try {
      const result = await reextractAll(pendingReextract.id);
      toast({ title: "Re-extraction done", description: result.summary, tone: "ok" });
      setPendingReextract(null);
      refresh();
    } catch (e) {
      toast({ title: "Could not re-extract", description: e instanceof Error ? e.message : undefined, tone: "bad" });
    } finally {
      setReextracting(false);
    }
  };

  const confirmDelete = async () => {
    if (!pendingDelete) return;
    setDeleting(true);
    try {
      await deleteNewsletter(pendingDelete.id);
      setNewsletters((cur) => cur.filter((n) => n.id !== pendingDelete.id));
      if (detailId === pendingDelete.id) setDetailId(null);
      toast({ title: "Newsletter removed", description: pendingDelete.label || pendingDelete.url, tone: "ok" });
      setPendingDelete(null);
    } catch (e) {
      toast({ title: "Could not remove newsletter", description: e instanceof Error ? e.message : undefined, tone: "bad" });
    } finally {
      setDeleting(false);
    }
  };

  const counts = useMemo(() => {
    const c = { total: newsletters.length, stale: 0, never: 0, unscheduled: 0 };
    for (const n of newsletters) {
      if (!n.scheduled_job) c.unscheduled += 1;
      const days = daysSince(n.last_scanned_at);
      if (days === null) c.never += 1;
      else if (days > STALE_DAYS) c.stale += 1;
    }
    return c;
  }, [newsletters]);

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return newsletters.filter((n) => {
      const days = daysSince(n.last_scanned_at);
      if (statusFilter === "unscheduled" && n.scheduled_job) return false;
      if (statusFilter === "never" && days !== null) return false;
      if (statusFilter === "stale" && !(days !== null && days > STALE_DAYS)) return false;
      if (needle) {
        const hay = `${n.label ?? ""} ${n.url} ${n.school_name ?? ""} ${n.district_name ?? ""}`.toLowerCase();
        if (!hay.includes(needle)) return false;
      }
      return true;
    });
  }, [newsletters, q, statusFilter]);

  const columns: Column<SmoreNewsletter>[] = [
    {
      id: "newsletter",
      header: "Newsletter",
      sortValue: (n) => (n.label || n.url).toLowerCase(),
      cell: (n) => (
        <>
          <div className="cell-title">{n.label || n.url}</div>
          <div className="cell-sub">
            {n.school_name && <span>school: {n.school_name}</span>}
            {n.district_name && <span>district: {n.district_name}</span>}
            {!n.school_name && !n.district_name && <span>no school/district set</span>}
          </div>
        </>
      ),
    },
    {
      id: "url",
      header: "URL",
      cell: (n) => (
        <a className="mono" href={n.url} target="_blank" rel="noreferrer" style={{ wordBreak: "break-all" }}>
          {n.url.replace(/^https?:\/\//, "")}
        </a>
      ),
    },
    {
      id: "schedule",
      header: "Schedule",
      cell: (n) =>
        n.scheduled_job ? (
          n.scheduled_job.run_once ? (
            <Badge tone={n.scheduled_job.last_run_at ? "muted" : "info"} dot={false}>
              {n.scheduled_job.last_run_at ? "one-time · already ran" : "one-time · pending"}
            </Badge>
          ) : (
            <>
              <div>{describeCron(n.scheduled_job.cron_expr)}</div>
              <div className="cell-sub">
                <span className="mono">{n.scheduled_job.cron_expr}</span>
              </div>
            </>
          )
        ) : (
          <Badge tone="muted" dot={false}>
            not scheduled
          </Badge>
        ),
    },
    {
      id: "last",
      header: "Last scanned",
      sortValue: (n) => n.last_scanned_at ?? "",
      cell: (n) => {
        const isRunning = running.has(n.id);
        const days = daysSince(n.last_scanned_at);
        return (
          <button
            className="btn subtle sm"
            style={{ display: "inline-flex", flexDirection: "column", alignItems: "flex-start", gap: 2, borderRadius: 8 }}
            onClick={(e) => {
              e.stopPropagation();
              setDetailId(n.id);
            }}
          >
            <span style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
              {isRunning ? (
                <StatusBadge status="running" />
              ) : n.scheduled_job ? (
                <StatusBadge status={n.scheduled_job.last_status} />
              ) : (
                <Badge tone="muted">never run</Badge>
              )}
              {days !== null && days > STALE_DAYS && !isRunning && (
                <Badge tone="warn" dot={false}>
                  stale
                </Badge>
              )}
            </span>
            <span className="cell-sub">{n.last_scanned_at ? relativeTime(n.last_scanned_at) : "never"}</span>
          </button>
        );
      },
    },
  ];

  const detail = detailId ? newsletters.find((n) => n.id === detailId) ?? null : null;

  return (
    <>
      <PageHeader
        upperTitle="Admin"
        title="Newsletters"
        subtitle="Tracked Smore (or similar) newsletter sources. Content is extracted automatically after each scan - open a row to see what it found."
        actions={
          <>
            <button className="btn" onClick={refresh} title="Refresh">
              <IconRefresh /> Refresh
            </button>
            <button className="btn btn-primary" onClick={() => setForm({ open: true, newsletter: null })}>
              <IconPlus /> Track a newsletter
            </button>
          </>
        }
      />

      <div className="stats">
        {(
          [
            ["", "All tracked", counts.total, ""],
            ["never", "Never scanned", counts.never, "bad"],
            ["stale", `Stale (${STALE_DAYS}+ days)`, counts.stale, "warn"],
            ["unscheduled", "Not scheduled", counts.unscheduled, ""],
          ] as [typeof statusFilter, string, number, string][]
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
          <input placeholder="Search newsletters, schools…" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <span className="spacer" />
        <span className="tb-count">
          {filtered.length} of {newsletters.length}
        </span>
      </div>

      <DataTable
        columns={columns}
        rows={filtered}
        getRowId={(n) => n.id}
        loading={loading}
        defaultSort={{ id: "newsletter", dir: "asc" }}
        onRowClick={(n) => setDetailId(n.id)}
        empty={newsletters.length === 0 ? "No newsletters tracked yet - add one above." : "No newsletters match these filters."}
        rowActions={(n) => (
          <>
            <button
              className={`btn icon ${running.has(n.id) ? "spin" : ""}`}
              title={n.scheduled_job ? "Run now" : "Not scheduled - edit to enable"}
              onClick={() => runNow(n)}
              disabled={running.has(n.id) || !n.scheduled_job}
            >
              {running.has(n.id) ? <IconRefresh /> : <IconPlay />}
            </button>
            <button className="btn icon" title="Content & details" onClick={() => setDetailId(n.id)}>
              <IconInfo />
            </button>
            <button className="btn icon" title="Force re-extract every block" onClick={() => setPendingReextract(n)}>
              <IconRefreshCw />
            </button>
            <button className="btn icon" title="Edit" onClick={() => setForm({ open: true, newsletter: n })}>
              <IconEdit />
            </button>
            <button className="btn icon danger" title="Remove" onClick={() => setPendingDelete(n)}>
              <IconTrash />
            </button>
          </>
        )}
      />

      <NewsletterDetailModal
        newsletter={detail}
        running={detail ? running.has(detail.id) : false}
        onClose={() => setDetailId(null)}
        onRun={runNow}
        onEdit={(n) => setForm({ open: true, newsletter: n })}
      />

      <NewsletterFormModal
        open={form.open}
        newsletter={form.newsletter}
        targets={targets}
        onClose={() => setForm({ open: false, newsletter: null })}
        onSaved={(saved) => {
          if (form.newsletter) patchLocal(saved);
          else setNewsletters((cur) => [...cur, saved]);
          toast({ title: form.newsletter ? "Newsletter updated" : "Newsletter added", description: saved.label || saved.url, tone: "ok" });
        }}
      />

      <ConfirmDialog
        open={Boolean(pendingReextract)}
        title="Re-extract every block?"
        description={
          <>
            Re-runs extraction over every block <b>{pendingReextract?.label || pendingReextract?.url}</b> has ever fetched, not just new ones. Only do
            this if it's missing items it should have - a newsletter that already extracted correctly will get duplicate items (dedup is at the block
            level, not the item level).
          </>
        }
        confirmLabel="Re-extract everything"
        danger
        busy={reextracting}
        onConfirm={confirmReextract}
        onCancel={() => setPendingReextract(null)}
      />

      <ConfirmDialog
        open={Boolean(pendingDelete)}
        title="Remove this newsletter?"
        description={
          <>
            <b>{pendingDelete?.label || pendingDelete?.url}</b> will stop being scanned and its schedule is deleted. Already-extracted content
            (calendar items, documents) stays - it just won't be refreshed with new issues.
          </>
        }
        confirmLabel="Remove"
        danger
        busy={deleting}
        onConfirm={confirmDelete}
        onCancel={() => setPendingDelete(null)}
      />
    </>
  );
}
