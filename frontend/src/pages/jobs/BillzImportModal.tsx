import { useEffect, useState } from "react";
import { Modal } from "../../components/ui/Modal";
import type { ScheduledJob } from "../../types";
import { importBillzJobs, type BillzImportResult } from "./jobsApi";

/** Paste billz's events.refresh job(s) - the params from its editor's Copy
 * button, one job, or its whole jobs list - and get local events jobs. */
export function BillzImportModal({ open, onClose, onImported }: { open: boolean; onClose: () => void; onImported: (jobs: ScheduledJob[]) => void }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BillzImportResult | null>(null);

  useEffect(() => {
    if (!open) return;
    setText("");
    setError(null);
    setResult(null);
  }, [open]);

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await importBillzJobs(text);
      setResult(r);
      if (r.created.length) onImported(r.created);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Import failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      size="lg"
      title="Import from billz"
      subtitle="Local events sources from billz's events.refresh job."
      footer={
        <>
          <button className="btn" type="button" onClick={onClose}>
            {result ? "Done" : "Cancel"}
          </button>
          <button className="btn btn-primary" type="button" onClick={run} disabled={busy || !text.trim()}>
            {busy ? "Importing…" : "Import"}
          </button>
        </>
      }
    >
      <p className="note" style={{ marginTop: 0 }}>
        Paste any of: the params from billz's job editor (its <b>Copy</b> button), one billz job as JSON, or the whole list from billz's{" "}
        <code>GET /admin/scheduled-jobs</code>. Each <code>events.refresh</code> job becomes a <code>local_events.refresh</code> job with the same name,
        schedule and sources. Other billz jobs are skipped, and a job with the same sources as one already here isn't created twice.
      </p>
      {error && <div className="form-error">{error}</div>}
      <textarea className="json-params" value={text} spellCheck={false} onChange={(e) => setText(e.target.value.replace(/\r/g, ""))} placeholder='{"evvnt_sources": [...], "ical_sources": [...]}' />
      {result && (
        <div className="test-results">
          <div className="test-results-h">
            {result.created.length} created · {result.skipped.length} skipped
          </div>
          {result.created.map((j) => (
            <div key={j.id} className="test-source">
              <span className="badge ok">created</span> <b>{j.name}</b> <span className="muted small">{j.cron_expr}</span>
            </div>
          ))}
          {result.skipped.map((s, i) => (
            <div key={i} className="test-source">
              <span className="badge muted">skipped</span> <b>{s.name}</b> <span className="muted small">{s.reason}</span>
            </div>
          ))}
        </div>
      )}
    </Modal>
  );
}
