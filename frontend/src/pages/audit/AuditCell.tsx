import { useState } from "react";
import { Link } from "react-router-dom";
import { ConfirmDialog } from "../../components/ui/ConfirmDialog";
import { useToast } from "../../components/ui/Toast";
import { runDataPoint, setNotPublished, type AuditSchool, type AuditStatus, type CellDetail } from "./auditApi";
import { useAudit } from "./AuditShell";

export function CellIcon({ status }: { status: AuditStatus }) {
  if (status === "stale")
    return (
      <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <circle cx="8" cy="8" r="6" />
        <path d="M8 4.8V8l2.2 1.4" />
      </svg>
    );
  if (status === "failing")
    return (
      <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true">
        <path d="M8 3.5v5.5" />
        <path d="M8 12.2v.3" />
      </svg>
    );
  return <span className="audit-dot" aria-hidden="true" />;
}

function editLink(school: AuditSchool<CellDetail>, cell: CellDetail): string | null {
  switch (cell.edit) {
    case "school":
      return `/schools/${school.slug}`;
    case "district":
      return "/schools";
    case "newsletters":
      return "/admin/newsletters";
    case "scans":
      return "/admin/scans";
    default:
      return null;
  }
}

/** Run scan now / Edit source / Mark as not published. Rendered only for a
 * manager on the internal view - a view-only user gets no buttons at all,
 * not disabled ones. */
export function CellActions({ school, cell, onChanged }: { school: AuditSchool<CellDetail>; cell: CellDetail; onChanged: () => void }) {
  const { showActions } = useAudit();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [note, setNote] = useState("");
  if (!showActions) return null;

  const edit = editLink(school, cell);
  const canRun = (cell.job_ids ?? []).length > 0;
  const canMark = cell.status === "not_collecting" && !cell.not_published;

  const run = async () => {
    setBusy(true);
    try {
      const res = await runDataPoint(school.id, cell.key);
      toast({ title: res.started.length === 1 ? "Scan started" : `${res.started.length} scans started`, description: res.started.map((j) => j.name).join(", "), tone: "ok" });
    } catch (e) {
      toast({ title: (e as Error).message, tone: "bad" });
    } finally {
      setBusy(false);
    }
  };

  const mark = async (on: boolean) => {
    setBusy(true);
    try {
      await setNotPublished(school.id, cell.key, on, note.trim());
      setConfirm(false);
      setNote("");
      onChanged();
    } catch (e) {
      toast({ title: (e as Error).message, tone: "bad" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="audit-actions no-print">
      {canRun && (
        <button type="button" className="btn btn-primary" onClick={run} disabled={busy}>
          Run scan now
        </button>
      )}
      {edit && (
        <Link className="btn" to={edit}>
          Edit source
        </Link>
      )}
      {canMark && (
        <button type="button" className="btn" onClick={() => setConfirm(true)} disabled={busy}>
          Mark as not published
        </button>
      )}
      {cell.not_published && (
        <button type="button" className="btn" onClick={() => mark(false)} disabled={busy}>
          Undo not published
        </button>
      )}
      <ConfirmDialog
        open={confirm}
        title="Mark as not published?"
        description={`${school.name} doesn't publish this. It stays "not collecting" in the score, but the district report says it isn't published instead of asking for a source.`}
        confirmLabel="Mark as not published"
        busy={busy}
        onConfirm={() => mark(true)}
        onCancel={() => setConfirm(false)}
      >
        <label className="field">
          <span className="lbl">Note (optional)</span>
          <input value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Confirmed by the main office" />
        </label>
      </ConfirmDialog>
    </div>
  );
}
