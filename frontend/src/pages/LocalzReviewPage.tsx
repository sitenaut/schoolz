import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Badge } from "../components/ui/Badge";
import { DataTable, type Column } from "../components/ui/DataTable";
import { PageHeader } from "../components/ui/PageHeader";
import { useToast } from "../components/ui/Toast";
import { useAuth } from "../context/AuthContext";
import { can } from "../lib/permissions";
import { type HeldChange, type QueueItem, approveChange, fetchChanges, fetchCounts, fetchQueue, rejectChange } from "../lib/localzReview";
import { ITEM_LABELS, STATUS_LABELS, type RequestStatus } from "../lib/providerPortal";

const STATES = [
  { key: "open", label: "Waiting" },
  { key: "changes_requested", label: "Changes requested" },
  { key: "approved", label: "Approved" },
  { key: "rejected", label: "Rejected" },
  { key: "withdrawn", label: "Withdrawn" },
  { key: "all", label: "All" },
];

const ORIGINS: Record<string, string> = { self_serve: "Portal", inquiry: "Ask to be listed", admin_assisted: "Admin-assisted" };

const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString() : "-");

const show = (v: unknown) => (v === null || v === undefined || v === "" ? "(empty)" : Array.isArray(v) ? v.join(", ") || "(empty)" : typeof v === "object" ? JSON.stringify(v) : String(v));

/** /admin/resources/onboarding - the Localz review queue: new listings
 * (oldest first) and held edits to live ones. */
export function LocalzReviewPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const toast = useToast();
  const manage = can(user, "resources.manage");
  const [tab, setTab] = useState<"requests" | "changes">("requests");
  const [state, setState] = useState("open");
  const [rows, setRows] = useState<QueueItem[] | null>(null);
  const [changes, setChanges] = useState<HeldChange[] | null>(null);
  const [counts, setCounts] = useState({ onboarding: 0, changes: 0 });
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(() => {
    fetchCounts().then(setCounts).catch(() => undefined);
    fetchQueue(state).then(setRows).catch(() => setRows([]));
    fetchChanges("pending").then(setChanges).catch(() => setChanges([]));
  }, [state]);
  useEffect(load, [load]);

  const decide = async (c: HeldChange, approve: boolean) => {
    setBusy(c.id);
    try {
      await (approve ? approveChange(c.id) : rejectChange(c.id));
      toast({ title: approve ? "Change published" : "Change refused - the old value stays", tone: "ok" });
      load();
    } catch (err) {
      toast({ title: err instanceof Error ? err.message : "Failed", tone: "bad" });
    } finally {
      setBusy(null);
    }
  };

  const columns: Column<QueueItem>[] = [
    {
      id: "org",
      header: "Organization",
      cell: (r) => (
        <span>
          <strong>{r.organization_name || "(no name)"}</strong>
          {r.town ? ` · ${r.town}` : ""}
          {r.claim && (
            <>
              {" "}
              <Badge tone="info" dot={false}>
                Claim
              </Badge>
            </>
          )}
        </span>
      ),
      sortValue: (r) => r.organization_name ?? "",
    },
    { id: "origin", header: "From", cell: (r) => ORIGINS[r.origin] ?? r.origin },
    { id: "status", header: "Status", cell: (r) => STATUS_LABELS[r.status as RequestStatus] ?? r.status },
    {
      id: "complete",
      header: "Complete",
      cell: (r) => (
        <span title={r.missing_core.map((k) => ITEM_LABELS[k] ?? k).join(", ")}>
          {r.percent}%{r.missing_core.length ? ` · missing ${r.missing_core.length}` : ""}
        </span>
      ),
      sortValue: (r) => r.percent,
    },
    { id: "submitted", header: "Submitted", cell: (r) => when(r.submitted_at), sortValue: (r) => r.submitted_at ?? "" },
  ];

  return (
    <div>
      <PageHeader
        title="Localz listings"
        subtitle="Every new listing and every held edit is checked here before it goes live. Oldest first."
      />
      <div className="tabs" role="tablist" style={{ marginBottom: 16 }}>
        <button type="button" className={`tab ${tab === "requests" ? "active" : ""}`} onClick={() => setTab("requests")}>
          New listings {counts.onboarding ? `(${counts.onboarding})` : ""}
        </button>
        <button type="button" className={`tab ${tab === "changes" ? "active" : ""}`} onClick={() => setTab("changes")}>
          Held edits {counts.changes ? `(${counts.changes})` : ""}
        </button>
      </div>

      {tab === "requests" ? (
        <>
          <div className="chips" style={{ marginBottom: 12 }}>
            {STATES.map((s) => (
              <button key={s.key} type="button" className="chip" aria-pressed={state === s.key} onClick={() => setState(s.key)}>
                {s.label}
              </button>
            ))}
          </div>
          <DataTable
            columns={columns}
            rows={rows ?? []}
            loading={rows === null}
            getRowId={(r) => r.id}
            onRowClick={(r) => navigate(`/admin/resources/onboarding/${r.id}`)}
            empty="Nothing waiting."
          />
        </>
      ) : changes === null ? (
        <p className="note">Loading…</p>
      ) : changes.length === 0 ? (
        <p className="note">No held edits.</p>
      ) : (
        changes.map((c) => (
          <section key={c.id} className="card" style={{ marginBottom: 12 }}>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
              <strong>{c.service?.name ?? "(listing gone)"}</strong>
              {c.service?.organization_name && <span className="note">{c.service.organization_name}</span>}
              <Badge tone={c.kind === "source_conflict" ? "warn" : "info"} dot={false}>
                {c.kind === "source_conflict" ? `${c.source ?? "Source"} disagrees with the provider` : "Provider edit"}
              </Badge>
              <span className="note">
                {c.requested_by ? `${c.requested_by} · ` : ""}
                {when(c.created_at)}
              </span>
            </div>
            <dl className="kv" style={{ marginTop: 10 }}>
              {Object.entries(c.changes).map(([field, value]) => (
                <div key={field} style={{ display: "contents" }}>
                  <dt>{field.replace(/_/g, " ")}</dt>
                  <dd>
                    <s className="note">{show(c.before[field])}</s> → {show(value)}
                  </dd>
                </div>
              ))}
              {c.has_private_address && (
                <>
                  <dt>private address</dt>
                  <dd>{c.private_address} (never published)</dd>
                </>
              )}
            </dl>
            <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
              {c.service && <Link to={`/localz/r/${c.service.id}`}>Public listing</Link>}
              {manage && (
                <>
                  <button className="btn btn-primary" disabled={busy === c.id} onClick={() => decide(c, true)}>
                    {c.kind === "source_conflict" ? "Use the source's value" : "Approve"}
                  </button>
                  <button className="btn" disabled={busy === c.id} onClick={() => decide(c, false)}>
                    {c.kind === "source_conflict" ? "Keep the provider's" : "Refuse"}
                  </button>
                </>
              )}
            </div>
          </section>
        ))
      )}
    </div>
  );
}
