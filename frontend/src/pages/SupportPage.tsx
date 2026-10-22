import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { apiFetch } from "../api";
import { IconChevronLeft, IconWrench } from "../components/icons";
import { Badge } from "../components/ui/Badge";
import { DataTable, type Column } from "../components/ui/DataTable";
import { SectionCard } from "../components/ui/SectionCard";
import { Switch } from "../components/ui/Switch";
import { fmtDateTime } from "../lib/format";
import type { UpdateSummary } from "../lib/family";

type LogRow = {
  id: string;
  reference: string;
  created_at: string;
  user_email: string | null;
  device_name: string | null;
  extension_version: string;
  entries: number;
  outcome: string | null;
  reported_at: string | null;
};
type LogEntry = { t?: string; e?: string; run?: string | null } & Record<string, unknown>;
type LogFull = LogRow & {
  payload: { platform?: string | null; log?: LogEntry[]; last_run?: unknown; summary?: UpdateSummary | null };
};

/** Backpack Capture support (support.view): the update logs each parent's
 * extension sends, the ones they reported a problem with first. A log is a
 * list of steps, never page text. */
export function SupportPage() {
  const [params, setParams] = useSearchParams();
  const openId = params.get("log");
  const [reportedOnly, setReportedOnly] = useState(false);
  const [reference, setReference] = useState("");
  const [rows, setRows] = useState<LogRow[] | null>(null);

  useEffect(() => {
    if (openId) return;
    const q = new URLSearchParams({ limit: "50" });
    if (reportedOnly) q.set("reported", "true");
    if (reference.trim()) q.set("reference", reference.trim());
    let live = true;
    apiFetch(`/capture-devices/diagnostics?${q}`)
      .then((r) => (r.ok ? r.json() : []))
      .then((list: LogRow[]) => {
        if (live) setRows(list);
      });
    return () => {
      live = false;
    };
  }, [openId, reportedOnly, reference]);

  if (openId) return <LogDetail id={openId} onBack={() => setParams({})} />;

  const columns: Column<LogRow>[] = [
    { id: "when", header: "When", cell: (r) => fmtDateTime(r.created_at), sortValue: (r) => r.created_at },
    { id: "who", header: "Account", cell: (r) => r.user_email ?? "—", sortValue: (r) => r.user_email },
    { id: "device", header: "Computer", cell: (r) => r.device_name ?? "—" },
    { id: "version", header: "Version", cell: (r) => r.extension_version },
    {
      id: "outcome",
      header: "Update",
      cell: (r) => (
        <>
          {r.outcome === "trouble" ? <Badge tone="warn">needs a look</Badge> : r.outcome === "ok" ? <Badge tone="ok">fine</Badge> : "—"}{" "}
          {r.reported_at && <Badge tone="info">reported</Badge>}
        </>
      ),
    },
    { id: "ref", header: "Reference", cell: (r) => <code>{r.reference}</code> },
  ];

  return (
    <SectionCard
      title="Backpack Capture support"
      description="The log each update sends: which accounts and pages it opened, where it stopped, what it sent. Never what was on the pages."
      icon={<IconWrench />}
    >
      <div className="support-filters">
        <span className="support-toggle">
          <Switch checked={reportedOnly} onChange={setReportedOnly} label="Reported problems only" />
          Reported problems only
        </span>
        <input
          type="search"
          placeholder="Reference, e.g. 3F9A12BC"
          value={reference}
          onChange={(e) => setReference(e.target.value)}
          aria-label="Find a log by reference"
        />
      </div>
      <DataTable
        columns={columns}
        rows={rows ?? []}
        loading={rows === null}
        getRowId={(r) => r.id}
        onRowClick={(r) => setParams({ log: r.id })}
        empty={reportedOnly ? "No reported problems." : "No logs yet."}
        defaultSort={{ id: "when", dir: "desc" }}
      />
    </SectionCard>
  );
}

/** Everything in one entry but its time, event and update, as `key=value`. */
function entryDetails(entry: LogEntry): string {
  return Object.entries(entry)
    .filter(([k]) => k !== "t" && k !== "e" && k !== "run")
    .map(([k, v]) => `${k}=${typeof v === "string" ? v : JSON.stringify(v)}`)
    .join("  ");
}

function LogDetail({ id, onBack }: { id: string; onBack: () => void }) {
  const [log, setLog] = useState<LogFull | null | "missing">(null);

  useEffect(() => {
    let live = true;
    apiFetch(`/capture-devices/diagnostics/${encodeURIComponent(id)}`)
      .then((r) => (r.ok ? r.json() : "missing"))
      .then((body: LogFull | "missing") => {
        if (live) setLog(body);
      });
    return () => {
      live = false;
    };
  }, [id]);

  const back = (
    <button type="button" className="btn sm" onClick={onBack}>
      <IconChevronLeft /> All logs
    </button>
  );
  if (log === null) return <p className="note">Loading…</p>;
  if (log === "missing") {
    return (
      <SectionCard title="Log not found" description="Logs are deleted after 30 days, or 90 once reported." icon={<IconWrench />}>
        {back}
      </SectionCard>
    );
  }
  const s = log.payload.summary;
  const entries = log.payload.log ?? [];
  return (
    <SectionCard
      title={`Update log ${log.reference}`}
      description={`${log.user_email ?? "Unknown account"} · ${log.device_name ?? "unknown computer"} · version ${log.extension_version}${
        log.payload.platform ? ` · ${log.payload.platform}` : ""
      } · sent ${fmtDateTime(log.created_at)}`}
      icon={<IconWrench />}
    >
      {back}
      {log.reported_at && <p className="note">Reported by the parent {fmtDateTime(log.reported_at)}; their note is in the Inbox.</p>}
      {s && (
        <div className="support-summary">
          <p>
            <b>{s.outcome === "trouble" ? "Needed a look" : "Finished fine"}</b> {fmtDateTime(s.finished_at)}
            {s.manual ? " (Update now)" : " (scheduled)"}: {s.pages_sent} page{s.pages_sent === 1 ? "" : "s"} sent
            {s.last_sent_at ? `; last sent ${fmtDateTime(s.last_sent_at)}` : ""}
            {s.not_set_up.length ? `; ${s.not_set_up.length} child${s.not_set_up.length === 1 ? "" : "ren"} not set up in this Chrome` : ""}.
          </p>
          {s.problems.length > 0 && (
            <ul>
              {s.problems.map((p, i) => (
                <li key={i}>{p.text}</li>
              ))}
            </ul>
          )}
        </div>
      )}
      <ol className="support-log">
        {entries.map((entry, i) => (
          <li key={i}>
            <span className="t">{entry.t ? new Date(entry.t).toLocaleTimeString() : ""}</span>
            <b>{entry.e ?? "?"}</b>
            <span className="d">{entryDetails(entry)}</span>
          </li>
        ))}
      </ol>
    </SectionCard>
  );
}
