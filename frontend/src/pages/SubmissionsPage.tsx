import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Badge } from "../components/ui/Badge";
import { ConfirmDialog } from "../components/ui/ConfirmDialog";
import { DataTable, type Column } from "../components/ui/DataTable";
import { Field } from "../components/ui/Field";
import { Modal } from "../components/ui/Modal";
import { PageHeader } from "../components/ui/PageHeader";
import { useToast } from "../components/ui/Toast";
import { IconInbox, IconLink, IconPlus, IconRefresh, IconSearch, IconTrash, IconUpload } from "../components/icons";
import { fmtDateTime, relativeTime } from "../lib/format";
import { useAuth } from "../context/AuthContext";
import { can } from "../lib/permissions";
import {
  deleteSubmission,
  listAttempts,
  listSubmissions,
  loadTargets,
  submitContent,
  type CommunitySubmission,
  type SubmissionAttempt,
  type TargetOption,
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
  const [attempts, setAttempts] = useState<SubmissionAttempt[]>([]);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("pending");
  const [busy, setBusy] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<CommunitySubmission | null>(null);
  const [adding, setAdding] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [submissions, log] = await Promise.all([listSubmissions(), listAttempts()]);
      setRows(submissions);
      setAttempts(log);
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
      return [r.url, r.file_name, r.description, r.submitter_name, r.submitter_email, r.school_name, r.district_name, r.source?.ip, r.source?.user_email]
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
      setAttempts((cur) => cur.map((a) => (a.submission_id === pendingDelete.id ? { ...a, submission_id: null } : a)));
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
      cell: (r) => (
        <div>
          {r.submitter_name || r.submitter_email || r.source?.user_email || <span className="note">anonymous</span>}
          {r.source?.ip && <div className="note" style={{ marginTop: 2 }}>{r.source.ip}</div>}
        </div>
      ),
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

  const attemptColumns: Column<SubmissionAttempt>[] = [
    {
      id: "when",
      header: "When",
      sortValue: (a) => a.created_at,
      cell: (a) => <span title={fmtDateTime(a.created_at)}>{relativeTime(a.created_at)}</span>,
    },
    {
      id: "outcome",
      header: "Outcome",
      sortValue: (a) => a.outcome,
      cell: (a) => (
        <div>
          <Badge tone={a.outcome === "accepted" ? (a.submission_id ? "ok" : "muted") : "bad"}>
            {a.outcome === "accepted" && !a.submission_id ? "accepted, since deleted" : a.outcome.replace(/_/g, " ")}
          </Badge>
          {a.outcome !== "accepted" && a.detail && <div className="note" style={{ marginTop: 2 }}>{a.detail}</div>}
        </div>
      ),
    },
    {
      id: "ip",
      header: "IP address",
      sortValue: (a) => a.ip,
      cell: (a) => (a.ip ? <code>{a.ip}</code> : <span className="note">unknown</span>),
    },
    {
      id: "what",
      header: "Sent",
      cell: (a) => (
        <div style={{ overflowWrap: "anywhere", minWidth: 130 }}>
          {a.file_name || a.url || <span className="note">nothing</span>}
          {a.file_sha256 && <div className="note" style={{ marginTop: 2 }}>sha256 {a.file_sha256.slice(0, 16)}…</div>}
        </div>
      ),
    },
    {
      id: "from",
      header: "From",
      cell: (a) => a.user_email || a.submitter_name || a.submitter_email || <span className="note">anonymous</span>,
    },
    {
      id: "browser",
      header: "Browser",
      cell: (a) => <span className="note">{a.user_agent || "none sent"}</span>,
    },
  ];

  return (
    <div className="page">
      <PageHeader
        upperTitle="Admin"
        title="Submissions inbox"
        subtitle="Fliers and newsletter links the community has sent in. Open one to read it, correct what was read and choose what goes on the calendar - nothing here publishes automatically."
        actions={
          <>
            {canEdit && (
              <button className="btn btn-primary" onClick={() => setAdding(true)}>
                <IconPlus /> Add one
              </button>
            )}
            <button className="btn" onClick={refresh} title="Refresh">
              <IconRefresh /> Refresh
            </button>
          </>
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

      <h2 style={{ margin: "32px 0 4px" }}>Upload log</h2>
      <p className="note" style={{ marginBottom: 12 }}>
        Every attempt to send something, with where it came from - including ones that were refused and ones whose
        submission has been deleted. Open a submission for the full record.
      </p>
      <DataTable
        columns={attemptColumns}
        rows={attempts}
        getRowId={(a) => a.id}
        loading={loading}
        onRowClick={(a) => a.submission_id && navigate(`/admin/submissions/${a.submission_id}`)}
        empty={
          <div className="empty">
            <IconInbox /> No attempts recorded yet.
          </div>
        }
        defaultSort={{ id: "when", dir: "desc" }}
      />

      {adding && <AddSubmissionModal onClose={() => setAdding(false)} onAdded={(s) => navigate(`/admin/submissions/${s.id}`)} />}

      <ConfirmDialog
        open={Boolean(pendingDelete)}
        title="Delete this submission?"
        description="This removes it (and its file, if any) permanently. Items already published from it stay on the calendar, and where it came from stays in the upload log."
        danger
        busy={busy}
        onConfirm={doDelete}
        onCancel={() => setPendingDelete(null)}
      />
    </div>
  );
}

/** A reviewer adding a flyer or link they already have, straight into the
 * inbox. Same endpoint as the public form; being signed in with
 * submissions.manage is what stands in for the bot check. It opens on the
 * review page afterwards, since reading it is the next step. */
function AddSubmissionModal({ onClose, onAdded }: { onClose: () => void; onAdded: (s: CommunitySubmission) => void }) {
  const [kind, setKind] = useState<"file" | "link">("file");
  const [file, setFile] = useState<File | null>(null);
  const [url, setUrl] = useState("");
  const [schoolId, setSchoolId] = useState("");
  const [note, setNote] = useState("");
  const [schools, setSchools] = useState<TargetOption[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadTargets().then((t) => setSchools(t.schools)).catch(() => undefined);
  }, []);

  const ready = kind === "file" ? Boolean(file) : url.trim().length > 0;
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      onAdded(
        await submitContent({
          file: kind === "file" ? file ?? undefined : undefined,
          url: kind === "link" ? url.trim() : undefined,
          description: note.trim() || undefined,
          school_id: schoolId || undefined,
        }),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not add this");
      setBusy(false);
    }
  };

  return (
    <Modal
      open
      onClose={onClose}
      title="Add a submission"
      subtitle="Goes into this inbox as pending, then opens so you can read it."
      footer={
        <>
          <button className="btn" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary" onClick={save} disabled={busy || !ready}>
            {busy ? "Adding…" : "Add and open"}
          </button>
        </>
      }
    >
      {error && <div className="form-error">{error}</div>}
      <div className="tabs" role="tablist" style={{ marginBottom: 16 }}>
        <button type="button" className={`tab ${kind === "file" ? "active" : ""}`} onClick={() => setKind("file")}>
          A file
        </button>
        <button type="button" className={`tab ${kind === "link" ? "active" : ""}`} onClick={() => setKind("link")}>
          A link
        </button>
      </div>
      {kind === "file" ? (
        <Field label="File" hint="A photo or PDF, up to 15MB.">
          <input type="file" accept="image/*,application/pdf" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </Field>
      ) : (
        <Field label="Link">
          <input type="url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://..." />
        </Field>
      )}
      <Field label="School" hint="Optional - you can set it on the next screen. Local events don't need one.">
        <select value={schoolId} onChange={(e) => setSchoolId(e.target.value)}>
          <option value="">Not set</option>
          {schools.map((s) => (
            <option key={s.id} value={s.id}>
              {s.label}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Note" hint="Optional - shown as the sender's note.">
        <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} maxLength={2000} />
      </Field>
    </Modal>
  );
}
