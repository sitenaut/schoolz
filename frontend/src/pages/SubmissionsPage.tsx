import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Badge } from "../components/ui/Badge";
import { ConfirmDialog } from "../components/ui/ConfirmDialog";
import { DataTable, type Column } from "../components/ui/DataTable";
import { PageHeader } from "../components/ui/PageHeader";
import { useToast } from "../components/ui/Toast";
import { IconInbox, IconLink, IconRefresh, IconSearch, IconTrash, IconUpload } from "../components/icons";
import { fmtDateTime, relativeTime } from "../lib/format";
import { useAuth } from "../context/AuthContext";
import { can } from "../lib/permissions";
import {
  deleteSubmission,
  listSubmissions,
  type CommunitySubmission,
} from "./submissions/submissionsApi";

type StatusFilter = "" | "pending" | "approved" | "rejected";

function statusTone(status: string): "warn" | "ok" | "bad" | "muted" {
  if (status === "pending") return "warn";
  if (status === "approved") return "ok";
  if (status === "rejected") return "bad";
  return "muted";
}

export function SubmissionsPage() {
  const toast = useToast();
  const navigate = useNavigate();
  const { user } = useAuth();
  const canEdit = can(user, "submissions.manage");
  const [rows, setRows] = useState<CommunitySubmission[]>([]);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("pending");
  const [busy, setBusy] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<CommunitySubmission | null>(null);

  const refresh = useCallback(async () => {
    try {
      setRows(await listSubmissions());
    } catch (e) {
      toast({ title: "Could not load submissions", description: e instanceof Error ? e.message : undefined, tone: "bad" });
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const counts = useMemo(() => {
    const by = { pending: 0, approved: 0, rejected: 0 };
    for (const r of rows) by[r.status as keyof typeof by]++;
    return { total: rows.length, ...by };
  }, [rows]);

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return rows.filter((r) => {
      if (statusFilter && r.status !== statusFilter) return false;
      if (!needle) return true;
      return [r.url, r.file_name, r.description, r.submitter_name, r.submitter_email, r.school_name, r.district_name]
        .filter(Boolean)
        .some((v) => v!.toLowerCase().includes(needle));
    });
  }, [rows, q, statusFilter]);

  const doDelete = async () => {
    if (!pendingDelete) return;
    setBusy(true);
    try {
      await deleteSubmission(pendingDelete.id);
      setRows((cur) => cur.filter((r) => r.id !== pendingDelete.id));
      setPendingDelete(null);
      toast({ title: "Deleted", tone: "ok" });
    } catch (e) {
      toast({ title: "Could not delete", description: e instanceof Error ? e.message : undefined, tone: "bad" });
    } finally {
      setBusy(false);
    }
  };

  const columns: Column<CommunitySubmission>[] = [
    {
      id: "kind",
      header: "",
      width: "36px",
      cell: (r) => (r.kind === "link" ? <IconLink /> : <IconUpload />),
      noLabel: true,
    },
    {
      id: "what",
      header: "Submitted",
      cell: (r) => (
        <div>
          <b>{r.kind === "link" ? r.url : r.file_name}</b>
          {r.description && <div className="note" style={{ marginTop: 2 }}>{r.description}</div>}
        </div>
      ),
    },
    {
      id: "target",
      header: "About",
      cell: (r) => r.school_name || r.district_name || <span className="note">not sure</span>,
    },
    {
      id: "from",
      header: "From",
      cell: (r) => r.submitter_name || r.submitter_email || <span className="note">anonymous</span>,
    },
    {
      id: "when",
      header: "Submitted",
      sortValue: (r) => r.created_at,
      cell: (r) => (
        <span title={fmtDateTime(r.created_at)}>{relativeTime(r.created_at)}</span>
      ),
    },
    {
      id: "status",
      header: "Status",
      cell: (r) => <Badge tone={statusTone(r.status)}>{r.status}</Badge>,
    },
  ];

  return (
    <div className="page">
      <PageHeader
        upperTitle="Admin"
        title="Submissions inbox"
        subtitle="Fliers and newsletter links the community has sent in. Open one to read it, correct what was read and choose what goes on the calendar - nothing here publishes automatically."
        actions={
          <button className="btn" onClick={refresh} title="Refresh">
            <IconRefresh /> Refresh
          </button>
        }
      />

      <div className="stats">
        {(
          [
            ["", "All", counts.total, ""],
            ["pending", "Pending", counts.pending, "warn"],
            ["approved", "Approved", counts.approved, "ok"],
            ["rejected", "Rejected", counts.rejected, "bad"],
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
          <input placeholder="Search submissions…" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
      </div>

      <DataTable
        columns={columns}
        rows={filtered}
        getRowId={(r) => r.id}
        loading={loading}
        onRowClick={(r) => navigate(`/admin/submissions/${r.id}`)}
        empty={
          <div className="empty">
            <IconInbox /> Nothing here{statusFilter ? ` (${statusFilter})` : ""}.
          </div>
        }
        defaultSort={{ id: "when", dir: "desc" }}
        rowActions={(r) =>
          canEdit ? (
            <button className="btn icon danger" title="Delete" onClick={() => setPendingDelete(r)}>
              <IconTrash />
            </button>
          ) : null
        }
      />

      <ConfirmDialog
        open={Boolean(pendingDelete)}
        title="Delete this submission?"
        description="This removes it (and its file, if any) permanently. Items already published from it stay on the calendar."
        danger
        busy={busy}
        onConfirm={doDelete}
        onCancel={() => setPendingDelete(null)}
      />
    </div>
  );
}
