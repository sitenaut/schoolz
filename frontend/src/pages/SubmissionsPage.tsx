import { useCallback, useEffect, useMemo, useState } from "react";
import { Badge } from "../components/ui/Badge";
import { ConfirmDialog } from "../components/ui/ConfirmDialog";
import { DataTable, type Column } from "../components/ui/DataTable";
import { Modal } from "../components/ui/Modal";
import { PageHeader } from "../components/ui/PageHeader";
import { useToast } from "../components/ui/Toast";
import { IconCheck, IconInbox, IconLink, IconRefresh, IconSearch, IconTrash, IconUpload, IconX } from "../components/icons";
import { fmtDateTime, relativeTime } from "../lib/format";
import { apiFetch } from "../api";
import {
  deleteSubmission,
  listSubmissions,
  submissionFileUrl,
  updateSubmission,
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
  const [rows, setRows] = useState<CommunitySubmission[]>([]);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("pending");
  const [detail, setDetail] = useState<CommunitySubmission | null>(null);
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<CommunitySubmission | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);

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

  useEffect(() => {
    setNotes(detail?.admin_notes ?? "");
    setPreviewUrl(null);
    if (detail?.kind === "file" && detail.file_content_type?.startsWith("image/")) {
      let revoked = "";
      apiFetch(`/submissions/${detail.id}/file`)
        .then((r) => (r.ok ? r.blob() : null))
        .then((blob) => {
          if (blob) {
            revoked = URL.createObjectURL(blob);
            setPreviewUrl(revoked);
          }
        })
        .catch(() => undefined);
      return () => {
        if (revoked) URL.revokeObjectURL(revoked);
      };
    }
  }, [detail]);

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

  const patchLocal = (updated: CommunitySubmission) => {
    setRows((cur) => cur.map((r) => (r.id === updated.id ? updated : r)));
    setDetail((cur) => (cur && cur.id === updated.id ? updated : cur));
  };

  const setStatus = async (row: CommunitySubmission, status: "approved" | "rejected", withNotes?: string) => {
    setBusy(true);
    try {
      const updated = await updateSubmission(row.id, { status, admin_notes: withNotes ?? notes });
      patchLocal(updated);
      toast({ title: status === "approved" ? "Marked approved" : "Marked rejected", tone: "ok" });
    } catch (e) {
      toast({ title: "Could not update", description: e instanceof Error ? e.message : undefined, tone: "bad" });
    } finally {
      setBusy(false);
    }
  };

  const saveNotes = async (row: CommunitySubmission) => {
    setBusy(true);
    try {
      const updated = await updateSubmission(row.id, { admin_notes: notes });
      patchLocal(updated);
      toast({ title: "Notes saved", tone: "ok" });
    } catch (e) {
      toast({ title: "Could not save notes", description: e instanceof Error ? e.message : undefined, tone: "bad" });
    } finally {
      setBusy(false);
    }
  };

  const doDelete = async () => {
    if (!pendingDelete) return;
    setBusy(true);
    try {
      await deleteSubmission(pendingDelete.id);
      setRows((cur) => cur.filter((r) => r.id !== pendingDelete.id));
      setPendingDelete(null);
      setDetail((cur) => (cur?.id === pendingDelete.id ? null : cur));
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
        subtitle="Fliers and newsletter links the community has sent in. Review each one and, if it's real and useful, add it yourself via Newsletters/Schools - nothing here publishes automatically."
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
        onRowClick={setDetail}
        empty={
          <div className="empty">
            <IconInbox /> Nothing here{statusFilter ? ` (${statusFilter})` : ""}.
          </div>
        }
        defaultSort={{ id: "when", dir: "desc" }}
        rowActions={(r) => (
          <button className="btn icon danger" title="Delete" onClick={() => setPendingDelete(r)}>
            <IconTrash />
          </button>
        )}
      />

      <Modal
        open={Boolean(detail)}
        onClose={() => setDetail(null)}
        size="lg"
        title={detail?.kind === "link" ? "Link submission" : "File submission"}
        subtitle={detail && <Badge tone={statusTone(detail.status)}>{detail.status}</Badge>}
        footer={
          detail && (
            <>
              <button className="btn solid-danger" onClick={() => setStatus(detail, "rejected")} disabled={busy}>
                <IconX /> Reject
              </button>
              <button className="btn btn-primary" onClick={() => setStatus(detail, "approved")} disabled={busy}>
                <IconCheck /> Approve
              </button>
            </>
          )
        }
      >
        {detail && (
          <dl className="kv">
            <dt>{detail.kind === "link" ? "Link" : "File"}</dt>
            <dd>
              {detail.kind === "link" ? (
                <a href={detail.url ?? undefined} target="_blank" rel="noreferrer">
                  {detail.url}
                </a>
              ) : (
                <>
                  <a href={submissionFileUrl(detail.id)} target="_blank" rel="noreferrer">
                    {detail.file_name} ({Math.round((detail.file_size ?? 0) / 1024)} KB)
                  </a>
                  {previewUrl && (
                    <img src={previewUrl} alt="" style={{ maxWidth: "100%", marginTop: 8, borderRadius: 8, display: "block" }} />
                  )}
                </>
              )}
            </dd>
            {detail.description && (
              <>
                <dt>What they're hoping for</dt>
                <dd>{detail.description}</dd>
              </>
            )}
            <dt>About</dt>
            <dd>{detail.school_name || detail.district_name || "not specified"}</dd>
            <dt>From</dt>
            <dd>
              {detail.submitter_name || "—"}
              {detail.submitter_email && ` · ${detail.submitter_email}`}
            </dd>
            <dt>Submitted</dt>
            <dd>{fmtDateTime(detail.created_at)}</dd>
            <dt>Admin notes</dt>
            <dd>
              <textarea
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                onBlur={() => detail && notes !== (detail.admin_notes ?? "") && saveNotes(detail)}
                rows={3}
                placeholder="e.g. Added as Beck's Smore newsletter"
                style={{ width: "100%" }}
              />
            </dd>
          </dl>
        )}
      </Modal>

      <ConfirmDialog
        open={Boolean(pendingDelete)}
        title="Delete this submission?"
        description="This removes it (and its file, if any) permanently."
        danger
        busy={busy}
        onConfirm={doDelete}
        onCancel={() => setPendingDelete(null)}
      />
    </div>
  );
}
