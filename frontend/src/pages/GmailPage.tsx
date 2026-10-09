import { useCallback, useEffect, useRef, useState } from "react";
import { apiFetch } from "../api";
import { IconMail, IconPlay, IconPlus, IconRefresh, IconTrash } from "../components/icons";
import { Badge, StatusBadge } from "../components/ui/Badge";
import { ConfirmDialog } from "../components/ui/ConfirmDialog";
import { DataTable, type Column } from "../components/ui/DataTable";
import { Field } from "../components/ui/Field";
import { Modal } from "../components/ui/Modal";
import { PageHeader } from "../components/ui/PageHeader";
import { SectionCard } from "../components/ui/SectionCard";
import { Switch } from "../components/ui/Switch";
import { useToast } from "../components/ui/Toast";
import { useAuth } from "../context/AuthContext";
import { describeCron } from "../lib/cron";
import { fmtDateTime, relativeTime } from "../lib/format";
import { can } from "../lib/permissions";

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
  enabled: boolean;
  scheduled_job: ScheduledJob | null;
};
type SchoolEmail = {
  id: string;
  sender: string | null;
  subject: string | null;
  received_at: string | null;
  newsletter_links: { url: string }[];
};

const RUN_REFRESH_MS = 2000;

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
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState<Set<string>>(new Set());
  const [pendingDisconnect, setPendingDisconnect] = useState<Connection | null>(null);
  const [pendingDelete, setPendingDelete] = useState<Scanner | null>(null);
  const [busy, setBusy] = useState(false);
  const timers = useRef<number[]>([]);

  const [formOpen, setFormOpen] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [account, setAccount] = useState("");
  const [name, setName] = useState("");
  const [fromContains, setFromContains] = useState("");
  const [subjectContains, setSubjectContains] = useState("");
  const [cronExpr, setCronExpr] = useState("0 7 * * *");

  const loadAll = useCallback(async () => {
    try {
      const [c, s, e] = await Promise.all([
        apiFetch("/gmail/connections").then((r) => (r.ok ? r.json() : [])),
        apiFetch("/email-scanners").then((r) => (r.ok ? r.json() : [])),
        apiFetch("/school-emails").then((r) => (r.ok ? r.json() : [])),
      ]);
      setConnections(c);
      setScanners(s);
      setEmails(e);
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

  const openForm = () => {
    setFormError(null);
    setAccount(connections[0]?.google_email ?? "");
    setFormOpen(true);
  };

  const createScanner = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError(null);
    setBusy(true);
    try {
      const res = await apiFetch("/email-scanners", {
        method: "POST",
        body: JSON.stringify({
          google_email: account,
          name,
          from_contains: csvToList(fromContains),
          subject_contains: csvToList(subjectContains),
          cron_expr: cronExpr,
          purpose: "school_email",
        }),
      });
      if (!res.ok) {
        setFormError(await errorDetail(res, "Could not create scanner"));
        return;
      }
      toast({ title: "Scanner added", description: name, tone: "ok" });
      setName("");
      setFromContains("");
      setSubjectContains("");
      setFormOpen(false);
      loadAll();
    } finally {
      setBusy(false);
    }
  };

  const runNow = async (s: Scanner) => {
    if (running.has(s.id)) return;
    const res = await apiFetch(`/email-scanners/${s.id}/run-now`, { method: "POST" });
    if (!res.ok) {
      toast({ title: "Could not start scan", description: await errorDetail(res, ""), tone: "bad" });
      return;
    }
    toast({ title: "Scan started", description: s.name, tone: "info" });
    setRunning((cur) => new Set(cur).add(s.id));
    timers.current.push(
      window.setTimeout(async () => {
        await loadAll();
        setRunning((cur) => {
          const next = new Set(cur);
          next.delete(s.id);
          return next;
        });
      }, RUN_REFRESH_MS)
    );
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
          </div>
        </>
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
      id: "email",
      header: "Email",
      cell: (m) => (
        <>
          <div className="cell-title">{m.subject ?? "(no subject)"}</div>
          <div className="cell-sub">
            <span>{m.sender ?? "unknown sender"}</span>
          </div>
        </>
      ),
    },
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
        subtitle="Connect a Gmail inbox that receives school emails, then scan it on a schedule to catch the newsletter links inside them."
        actions={
          <>
            <button className="btn" onClick={loadAll} title="Refresh">
              <IconRefresh /> Refresh
            </button>
            {canEdit && (
              <button
                className="btn btn-primary"
                onClick={openForm}
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
                  <button className="btn icon danger" title="Remove" onClick={() => setPendingDelete(s)}>
                    <IconTrash />
                  </button>
                </>
              )
            : undefined
        }
      />

      <div className="section-title">Captured school emails</div>
      <DataTable
        columns={emailColumns}
        rows={emails}
        getRowId={(m) => m.id}
        loading={loading}
        defaultSort={{ id: "received", dir: "desc" }}
        empty="None captured yet."
      />

      <Modal
        open={formOpen}
        onClose={() => setFormOpen(false)}
        title="Add a scanner"
        subtitle="Emails matching these filters are captured each time the scanner runs."
        footer={
          <>
            <button className="btn" type="button" onClick={() => setFormOpen(false)} disabled={busy}>
              Cancel
            </button>
            <button className="btn btn-primary" type="submit" form="scanner-form" disabled={busy || !name.trim() || !account}>
              {busy ? "Saving…" : "Add scanner"}
            </button>
          </>
        }
      >
        <form id="scanner-form" onSubmit={createScanner}>
          {formError && <div className="form-error">{formError}</div>}
          <div className="fgrid two">
            <Field label="Name" className="span2">
              <input value={name} onChange={(e) => setName(e.target.value)} required />
            </Field>
            {connections.length > 1 && (
              <Field label="Gmail account" className="span2">
                <select value={account} onChange={(e) => setAccount(e.target.value)}>
                  {connections.map((c) => (
                    <option key={c.google_email} value={c.google_email}>
                      {c.google_email}
                    </option>
                  ))}
                </select>
              </Field>
            )}
            <Field label="From contains" hint="Comma-separated.">
              <input value={fromContains} onChange={(e) => setFromContains(e.target.value)} placeholder="chclc.org" />
            </Field>
            <Field label="Subject contains" hint="Comma-separated.">
              <input value={subjectContains} onChange={(e) => setSubjectContains(e.target.value)} />
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
            schoolz will stop reading <b>{pendingDisconnect?.google_email}</b>. Its scanners stay but cannot read mail until it is reconnected; emails already captured stay.
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
            <b>{pendingDelete?.name}</b> will stop scanning and its schedule is deleted. Emails already captured stay.
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
