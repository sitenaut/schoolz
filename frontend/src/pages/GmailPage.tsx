import { useCallback, useEffect, useRef, useState } from "react";
import { apiFetch } from "../api";
import { IconEdit, IconMail, IconPlay, IconPlus, IconRefresh, IconRefreshCw, IconTrash } from "../components/icons";
import { Badge, StatusBadge } from "../components/ui/Badge";
import { ConfirmDialog } from "../components/ui/ConfirmDialog";
import { DataTable, type Column } from "../components/ui/DataTable";
import { Field } from "../components/ui/Field";
import { FilterSelect } from "../components/ui/FilterSelect";
import { Modal } from "../components/ui/Modal";
import { PageHeader } from "../components/ui/PageHeader";
import { SectionCard } from "../components/ui/SectionCard";
import { Switch } from "../components/ui/Switch";
import { useToast } from "../components/ui/Toast";
import { useAuth } from "../context/AuthContext";
import { describeCron } from "../lib/cron";
import { fmtDateTime, relativeTime } from "../lib/format";
import { can } from "../lib/permissions";
import { loadTargets, type TargetOption } from "./smore/smoreApi";

type Connection = { google_email: string; last_synced_at: string | null; created_at: string };
type ScheduledJob = {
  id: string;
  cron_expr: string;
  enabled: boolean;
  last_run_at: string | null;
  last_status: string | null;
  last_error: string | null;
};
type Scanner = {
  id: string;
  google_email: string;
  name: string;
  from_contains: string[];
  subject_contains: string[];
  body_contains: string[];
  lookback_days: number;
  school_id: string | null;
  link_kinds: string[];
  enabled: boolean;
  scheduled_job: ScheduledJob | null;
  last_run: LastRun | null;
  /** Every email it has read, by outcome: ok (had links), skipped (none), error. */
  totals: Record<string, number>;
};
/** The latest run's accounting (EmailScanner.last_run): the search and counts, nothing from a message. */
type LastRun = {
  at: string;
  query: string;
  matched: number;
  new: number;
  with_links: number;
  without_links: number;
  errors: number;
  links: number;
  new_newsletters: number;
  waiting: number;
  already_tracked: number;
  tracking_links: number;
};
type LinkKind = { key: string; label: string };
/** What a scan keeps of one message: the newsletter links it held, nothing else. */
type SchoolEmail = {
  id: string;
  received_at: string | null;
  newsletter_links: { url: string; kind?: string }[];
};

// A run-now on prod waits for the scheduler to pick it up, then reads Gmail:
// poll until the run has finished rather than refreshing once too early.
const RUN_POLL_MS = 3000;
const RUN_WAIT_MS = 120_000;

function plural(count: number, word: string): string {
  return `${count} ${count === 1 ? word : `${word}s`}`;
}

function RunAccounting({ run, totals }: { run: LastRun | null; totals: Record<string, number> }) {
  const ok = totals.ok ?? 0;
  const skipped = totals.skipped ?? 0;
  const failed = totals.error ?? 0;
  const read = ok + skipped + failed;
  if (!run && !read) return null;
  return (
    <div className="cell-sub">
      {run && (
        <>
          <span>{run.matched === 0 ? "No email matched the search" : `${plural(run.matched, "email")} matched · ${run.new} new`}</span>
          {run.new > 0 && (
            <span>
              {run.with_links} with newsletter links · {run.without_links} without
              {run.errors > 0 && ` · ${run.errors} failed`}
            </span>
          )}
          {run.links > 0 && (
            <span>
              {plural(run.links, "link")}: {plural(run.new_newsletters, "new newsletter")}
              {run.waiting > 0 && ` (${run.waiting} waiting for an admin)`} · {run.already_tracked} already tracked
            </span>
          )}
          {run.tracking_links > 0 && <span>{plural(run.tracking_links, "click-tracking link")} skipped, never followed</span>}
          <span className="mono" style={{ wordBreak: "break-all" }}>
            {run.query}
          </span>
        </>
      )}
      {read > 0 && (
        <span>
          All runs: {plural(read, "email")} read · {ok} with links · {skipped} without
          {failed > 0 && ` · ${failed} failed`}
        </span>
      )}
    </div>
  );
}

function csvToList(value: string): string[] {
  return value
    .split(",")
    .map((v) => v.trim())
    .filter(Boolean);
}

async function errorDetail(res: Response, fallback: string): Promise<string> {
  const body = await res.json().catch(() => null);
  return typeof body?.detail === "string" ? body.detail : fallback;
}

export function GmailPage() {
  const { user } = useAuth();
  const toast = useToast();
  const canEdit = can(user, "email.manage");
  const [connections, setConnections] = useState<Connection[]>([]);
  const [scanners, setScanners] = useState<Scanner[]>([]);
  const [emails, setEmails] = useState<SchoolEmail[]>([]);
  const [linkKinds, setLinkKinds] = useState<LinkKind[]>([]);
  const [schools, setSchools] = useState<TargetOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState<Set<string>>(new Set());
  const [pendingDisconnect, setPendingDisconnect] = useState<Connection | null>(null);
  const [pendingDelete, setPendingDelete] = useState<Scanner | null>(null);
  const [busy, setBusy] = useState(false);
  const timers = useRef<number[]>([]);

  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Scanner | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [account, setAccount] = useState("");
  const [name, setName] = useState("");
  const [fromContains, setFromContains] = useState("");
  const [subjectContains, setSubjectContains] = useState("");
  const [cronExpr, setCronExpr] = useState("0 7 * * *");
  const [formKinds, setFormKinds] = useState<string[]>(["smore"]);
  const [schoolId, setSchoolId] = useState("");

  const loadAll = useCallback(async () => {
    try {
      const [c, s, e, k, t] = await Promise.all([
        apiFetch("/gmail/connections").then((r) => (r.ok ? r.json() : [])),
        apiFetch("/email-scanners").then((r) => (r.ok ? r.json() : [])),
        apiFetch("/school-emails").then((r) => (r.ok ? r.json() : [])),
        apiFetch("/email-scanners/link-kinds").then((r) => (r.ok ? r.json() : [])),
        loadTargets().catch(() => ({ schools: [] as TargetOption[] })),
      ]);
      setSchools(t.schools);
      setConnections(c);
      setScanners(s);
      setEmails(e);
      setLinkKinds(k);
    } catch (e) {
      toast({ title: "Could not load the email scanner", description: e instanceof Error ? e.message : undefined, tone: "bad" });
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    loadAll();
    const onMessage = (event: MessageEvent) => {
      if (event.data === "gmail:connected") {
        toast({ title: "Gmail account connected", tone: "ok" });
        loadAll();
      }
      if (event.data === "gmail:error") toast({ title: "Gmail connection failed or was cancelled", tone: "bad" });
    };
    window.addEventListener("message", onMessage);
    return () => {
      window.removeEventListener("message", onMessage);
      timers.current.forEach((t) => window.clearTimeout(t));
    };
  }, [loadAll, toast]);

  const connectGmail = async () => {
    const res = await apiFetch("/gmail/auth-url");
    if (!res.ok) {
      toast({ title: "Could not start Gmail connection", description: await errorDetail(res, ""), tone: "bad" });
      return;
    }
    const body = await res.json();
    window.open(body.url, "gmail-oauth", "width=500,height=700");
  };

  const confirmDisconnect = async () => {
    if (!pendingDisconnect) return;
    setBusy(true);
    try {
      const res = await apiFetch(`/gmail/disconnect?google_email=${encodeURIComponent(pendingDisconnect.google_email)}`, { method: "DELETE" });
      if (!res.ok) throw new Error(await errorDetail(res, "Could not disconnect"));
      toast({ title: "Gmail account disconnected", description: pendingDisconnect.google_email, tone: "ok" });
      setPendingDisconnect(null);
      loadAll();
    } catch (e) {
      toast({ title: "Could not disconnect", description: e instanceof Error ? e.message : undefined, tone: "bad" });
    } finally {
      setBusy(false);
    }
  };

  const openForm = (s: Scanner | null = null) => {
    setFormError(null);
    setEditing(s);
    setAccount(s?.google_email ?? connections[0]?.google_email ?? "");
    setName(s?.name ?? "");
    setFromContains(s?.from_contains.join(", ") ?? "");
    setSubjectContains(s?.subject_contains.join(", ") ?? "");
    setCronExpr(s?.scheduled_job?.cron_expr ?? "0 7 * * *");
    setFormKinds(s?.link_kinds ?? ["smore"]);
    setSchoolId(s?.school_id ?? "");
    setFormOpen(true);
  };

  const saveScanner = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError(null);
    setBusy(true);
    const fields = {
      google_email: account,
      name,
      from_contains: csvToList(fromContains),
      subject_contains: csvToList(subjectContains),
      cron_expr: cronExpr,
      link_kinds: formKinds,
      school_id: schoolId || null,
    };
    try {
      const res = editing
        ? await apiFetch(`/email-scanners/${editing.id}`, { method: "PATCH", body: JSON.stringify(fields) })
        : await apiFetch("/email-scanners", { method: "POST", body: JSON.stringify({ ...fields, purpose: "school_email" }) });
      if (!res.ok) {
        setFormError(await errorDetail(res, editing ? "Could not save scanner" : "Could not create scanner"));
        return;
      }
      toast({ title: editing ? "Scanner saved" : "Scanner added", description: name, tone: "ok" });
      setFormOpen(false);
      loadAll();
    } finally {
      setBusy(false);
    }
  };

  const stopRunning = (id: string) =>
    setRunning((cur) => {
      const next = new Set(cur);
      next.delete(id);
      return next;
    });

  const runNow = async (s: Scanner, recheck = false) => {
    if (running.has(s.id)) return;
    const res = await apiFetch(`/email-scanners/${s.id}/run-now${recheck ? "?recheck=true" : ""}`, { method: "POST" });
    if (!res.ok) {
      toast({ title: "Could not start scan", description: await errorDetail(res, ""), tone: "bad" });
      return;
    }
    toast({ title: recheck ? "Re-reading emails that had no links" : "Scan started", description: s.name, tone: "info" });
    setRunning((cur) => new Set(cur).add(s.id));
    const before = s.scheduled_job?.last_run_at ?? null;
    const startedAt = Date.now();
    const poll = async () => {
      const latest = await apiFetch("/email-scanners")
        .then((r) => (r.ok ? (r.json() as Promise<Scanner[]>) : []))
        .catch(() => [] as Scanner[]);
      const job = latest.find((x) => x.id === s.id)?.scheduled_job;
      const finished = job && job.last_run_at !== before && job.last_status !== "running" && job.last_status !== "queued";
      if (finished || Date.now() - startedAt > RUN_WAIT_MS) {
        await loadAll();
        stopRunning(s.id);
        return;
      }
      timers.current.push(window.setTimeout(poll, RUN_POLL_MS));
    };
    timers.current.push(window.setTimeout(poll, RUN_POLL_MS));
  };

  const setEnabled = async (s: Scanner, enabled: boolean) => {
    const res = await apiFetch(`/email-scanners/${s.id}`, { method: "PATCH", body: JSON.stringify({ enabled }) });
    if (!res.ok) {
      toast({ title: "Could not update scanner", description: await errorDetail(res, ""), tone: "bad" });
      return;
    }
    const updated: Scanner = await res.json();
    setScanners((cur) => cur.map((x) => (x.id === updated.id ? updated : x)));
  };

  const setKinds = async (s: Scanner, kinds: string[]) => {
    if (!kinds.length) {
      toast({ title: "A scanner keeps at least one kind of link", tone: "bad" });
      return;
    }
    const res = await apiFetch(`/email-scanners/${s.id}`, { method: "PATCH", body: JSON.stringify({ link_kinds: kinds }) });
    if (!res.ok) {
      toast({ title: "Could not update scanner", description: await errorDetail(res, ""), tone: "bad" });
      return;
    }
    const updated: Scanner = await res.json();
    setScanners((cur) => cur.map((x) => (x.id === updated.id ? updated : x)));
  };

  const kindLabel = (key: string) => linkKinds.find((k) => k.key === key)?.label ?? key;
  const schoolLabel = (id: string | null) => (id ? (schools.find((x) => x.id === id)?.label ?? "a school") : null);

  const confirmDelete = async () => {
    if (!pendingDelete) return;
    setBusy(true);
    try {
      const res = await apiFetch(`/email-scanners/${pendingDelete.id}`, { method: "DELETE" });
      if (!res.ok) throw new Error(await errorDetail(res, "Could not remove scanner"));
      setScanners((cur) => cur.filter((x) => x.id !== pendingDelete.id));
      toast({ title: "Scanner removed", description: pendingDelete.name, tone: "ok" });
      setPendingDelete(null);
    } catch (e) {
      toast({ title: "Could not remove scanner", description: e instanceof Error ? e.message : undefined, tone: "bad" });
    } finally {
      setBusy(false);
    }
  };

  const scannerColumns: Column<Scanner>[] = [
    {
      id: "scanner",
      header: "Scanner",
      sortValue: (s) => s.name.toLowerCase(),
      cell: (s) => (
        <>
          <div className="cell-title">{s.name}</div>
          <div className="cell-sub">
            <span>{s.google_email}</span>
            <span>{schoolLabel(s.school_id) ?? "no school - links wait for an admin"}</span>
          </div>
        </>
      ),
    },
    {
      id: "keeps",
      header: "Keeps",
      cell: (s) =>
        canEdit ? (
          <div className="chips">
            {linkKinds.map((k) => (
              <button
                key={k.key}
                type="button"
                className="chip"
                aria-pressed={s.link_kinds.includes(k.key)}
                onClick={() => setKinds(s, s.link_kinds.includes(k.key) ? s.link_kinds.filter((x) => x !== k.key) : [...s.link_kinds, k.key])}
              >
                {k.label}
              </button>
            ))}
          </div>
        ) : (
          s.link_kinds.map(kindLabel).join(", ")
        ),
    },
    {
      id: "matches",
      header: "Matches",
      cell: (s) =>
        s.from_contains.length + s.subject_contains.length + s.body_contains.length === 0 ? (
          <Badge tone="muted" dot={false}>
            every email
          </Badge>
        ) : (
          <div className="cell-sub">
            {s.from_contains.length > 0 && <span>from: {s.from_contains.join(", ")}</span>}
            {s.subject_contains.length > 0 && <span>subject: {s.subject_contains.join(", ")}</span>}
            {s.body_contains.length > 0 && <span>body: {s.body_contains.join(", ")}</span>}
          </div>
        ),
    },
    {
      id: "schedule",
      header: "Schedule",
      cell: (s) =>
        s.scheduled_job ? (
          <>
            <div>{describeCron(s.scheduled_job.cron_expr)}</div>
            <div className="cell-sub">
              <span className="mono">{s.scheduled_job.cron_expr}</span>
            </div>
          </>
        ) : (
          <Badge tone="muted" dot={false}>
            not scheduled
          </Badge>
        ),
    },
    {
      id: "last",
      header: "Last run",
      sortValue: (s) => s.scheduled_job?.last_run_at ?? "",
      cell: (s) => (
        <>
          {running.has(s.id) ? (
            <StatusBadge status="running" />
          ) : s.scheduled_job?.last_status ? (
            <StatusBadge status={s.scheduled_job.last_status} />
          ) : (
            <Badge tone="muted">never run</Badge>
          )}
          <div className="cell-sub">
            {s.scheduled_job?.last_run_at && <span>{relativeTime(s.scheduled_job.last_run_at)}</span>}
            {s.scheduled_job?.last_error && <span>{s.scheduled_job.last_error}</span>}
          </div>
          <RunAccounting run={s.last_run} totals={s.totals} />
        </>
      ),
    },
    ...(canEdit
      ? [
          {
            id: "enabled",
            header: "Enabled",
            cell: (s: Scanner) =>
              s.scheduled_job ? (
                <Switch checked={s.scheduled_job.enabled} onChange={(next) => setEnabled(s, next)} label={`Scan ${s.name} on schedule`} />
              ) : null,
          },
        ]
      : []),
  ];

  const emailColumns: Column<SchoolEmail>[] = [
    {
      id: "received",
      header: "Received",
      sortValue: (m) => m.received_at ?? "",
      cell: (m) => (m.received_at ? fmtDateTime(m.received_at) : "—"),
    },
    {
      id: "links",
      header: "Newsletter links",
      cell: (m) =>
        m.newsletter_links.length === 0 ? (
          <Badge tone="muted" dot={false}>
            none found
          </Badge>
        ) : (
          m.newsletter_links.map((l) => (
            <div key={l.url}>
              <a className="mono" href={l.url} target="_blank" rel="noreferrer" style={{ wordBreak: "break-all" }}>
                {l.url.replace(/^https?:\/\//, "")}
              </a>
              {l.kind && <span className="note"> · {kindLabel(l.kind)}</span>}
            </div>
          ))
        ),
    },
  ];

  return (
    <>
      <PageHeader
        upperTitle="Admin"
        title="Email scanner"
        subtitle="Connect a Gmail inbox that receives school emails, then scan it on a schedule to catch the newsletter links inside them. Only those links are kept - never an email's text, subject or sender."
        actions={
          <>
            <button className="btn" onClick={loadAll} title="Refresh">
              <IconRefresh /> Refresh
            </button>
            {canEdit && (
              <button
                className="btn btn-primary"
                onClick={() => openForm()}
                disabled={connections.length === 0}
                title={connections.length === 0 ? "Connect a Gmail account first" : undefined}
              >
                <IconPlus /> Add a scanner
              </button>
            )}
          </>
        }
      />

      <SectionCard
        title="Connected Gmail accounts"
        description="Read-only access. A scanner reads from one of these inboxes."
        icon={<IconMail />}
        actions={
          canEdit && (
            <button className="btn sm" onClick={connectGmail}>
              <IconPlus /> Connect Gmail
            </button>
          )
        }
      >
        {connections.length === 0 ? (
          <p className="note" style={{ margin: 0 }}>
            {loading ? "Loading…" : "No Gmail account connected yet."}
          </p>
        ) : (
          connections.map((c) => (
            <div className="sw-row" key={c.google_email}>
              <div>
                <b>{c.google_email}</b>
                <small>
                  Connected {relativeTime(c.created_at)} · {c.last_synced_at ? `last synced ${relativeTime(c.last_synced_at)}` : "never synced"}
                </small>
              </div>
              {canEdit && (
                <button className="btn sm" onClick={() => setPendingDisconnect(c)}>
                  Disconnect
                </button>
              )}
            </div>
          ))
        )}
      </SectionCard>

      <div className="section-title">Recurring scanners</div>
      <DataTable
        columns={scannerColumns}
        rows={scanners}
        getRowId={(s) => s.id}
        loading={loading}
        defaultSort={{ id: "scanner", dir: "asc" }}
        empty="No scanners yet."
        rowActions={
          canEdit
            ? (s) => (
                <>
                  <button
                    className={`btn icon ${running.has(s.id) ? "spin" : ""}`}
                    title={s.scheduled_job ? "Run now" : "No linked schedule"}
                    onClick={() => runNow(s)}
                    disabled={running.has(s.id) || !s.scheduled_job}
                  >
                    {running.has(s.id) ? <IconRefresh /> : <IconPlay />}
                  </button>
                  <button
                    className="btn icon"
                    title="Run now, re-reading emails that had no newsletter links"
                    onClick={() => runNow(s, true)}
                    disabled={running.has(s.id) || !s.scheduled_job || !(s.totals.skipped || s.totals.error)}
                  >
                    <IconRefreshCw />
                  </button>
                  <button className="btn icon" title="Edit" onClick={() => openForm(s)}>
                    <IconEdit />
                  </button>
                  <button className="btn icon danger" title="Remove" onClick={() => setPendingDelete(s)}>
                    <IconTrash />
                  </button>
                </>
              )
            : undefined
        }
      />

      <div className="section-title">Newsletter links found</div>
      <DataTable
        columns={emailColumns}
        rows={emails}
        getRowId={(m) => m.id}
        loading={loading}
        defaultSort={{ id: "received", dir: "desc" }}
        empty="No newsletter links found yet."
      />

      <Modal
        open={formOpen}
        onClose={() => setFormOpen(false)}
        title={editing ? "Edit scanner" : "Add a scanner"}
        subtitle="Each run reads the emails matching these filters and keeps only the newsletter links of the kinds ticked below."
        footer={
          <>
            <button className="btn" type="button" onClick={() => setFormOpen(false)} disabled={busy}>
              Cancel
            </button>
            <button className="btn btn-primary" type="submit" form="scanner-form" disabled={busy || !name.trim() || !account || !formKinds.length}>
              {busy ? "Saving…" : editing ? "Save changes" : "Add scanner"}
            </button>
          </>
        }
      >
        <form id="scanner-form" onSubmit={saveScanner}>
          {formError && <div className="form-error">{formError}</div>}
          <div className="fgrid two">
            <Field label="Name" className="span2">
              <input value={name} onChange={(e) => setName(e.target.value)} required />
            </Field>
            <Field
              label="Inbox"
              className="span2"
              hint={
                editing && account !== editing.google_email
                  ? `The next run searches this inbox's mail from the last ${editing.lookback_days} days.`
                  : "The connected Gmail inbox this scanner searches."
              }
            >
              <select value={account} onChange={(e) => setAccount(e.target.value)}>
                {editing && !connections.some((c) => c.google_email === editing.google_email) && (
                  <option value={editing.google_email}>{editing.google_email} (disconnected)</option>
                )}
                {connections.map((c) => (
                  <option key={c.google_email} value={c.google_email}>
                    {c.google_email}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="From contains" hint="Comma-separated.">
              <input value={fromContains} onChange={(e) => setFromContains(e.target.value)} placeholder="chclc.org" />
            </Field>
            <Field label="Subject contains" hint="Comma-separated.">
              <input value={subjectContains} onChange={(e) => setSubjectContains(e.target.value)} />
            </Field>
            <Field label="Keep links to" hint="Nothing else from an email is kept." className="span2">
              <div className="chips">
                {linkKinds.map((k) => (
                  <button
                    key={k.key}
                    type="button"
                    className="chip"
                    aria-pressed={formKinds.includes(k.key)}
                    onClick={() => setFormKinds((cur) => (cur.includes(k.key) ? cur.filter((x) => x !== k.key) : [...cur, k.key]))}
                  >
                    {k.label}
                  </button>
                ))}
              </div>
            </Field>
            <Field
              label="School"
              hint={`Its newsletters become this school's content. Without one, a found link waits for an admin to assign it.${editing ? " Applies to links found from now on." : ""}`}
              className="span2"
            >
              <FilterSelect value={schoolId} onChange={setSchoolId} options={schools.map((x) => ({ value: x.id, label: x.label }))} placeholder="— none —" clearLabel="No school" />
            </Field>
            <Field label="Cron expression" hint={describeCron(cronExpr)} className="span2">
              <input className="mono" value={cronExpr} onChange={(e) => setCronExpr(e.target.value)} required />
            </Field>
          </div>
        </form>
      </Modal>

      <ConfirmDialog
        open={Boolean(pendingDisconnect)}
        title="Disconnect this Gmail account?"
        description={
          <>
            schoolz will stop reading <b>{pendingDisconnect?.google_email}</b>. Its scanners stay but cannot read mail until it is reconnected; links already found stay.
          </>
        }
        confirmLabel="Disconnect"
        danger
        busy={busy}
        onConfirm={confirmDisconnect}
        onCancel={() => setPendingDisconnect(null)}
      />

      <ConfirmDialog
        open={Boolean(pendingDelete)}
        title="Remove this scanner?"
        description={
          <>
            <b>{pendingDelete?.name}</b> will stop scanning and its schedule is deleted. Links already found stay.
          </>
        }
        confirmLabel="Remove"
        danger
        busy={busy}
        onConfirm={confirmDelete}
        onCancel={() => setPendingDelete(null)}
      />
    </>
  );
}
