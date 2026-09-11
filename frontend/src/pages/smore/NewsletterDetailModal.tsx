import { useCallback, useEffect, useState } from "react";
import { Badge, StatusBadge } from "../../components/ui/Badge";
import { Modal } from "../../components/ui/Modal";
import { IconEdit, IconImage, IconPlay, IconRefresh } from "../../components/icons";
import { describeCron } from "../../lib/cron";
import { fmtDateTime, relativeTime } from "../../lib/format";
import type { SmoreBlock, SmoreNewsletter } from "../../types";
import { listBlocks } from "./smoreApi";

type Tab = "content" | "overview";

type Props = {
  newsletter: SmoreNewsletter | null;
  running: boolean;
  onClose: () => void;
  onRun: (n: SmoreNewsletter) => void;
  onEdit: (n: SmoreNewsletter) => void;
};

function BlockRow({ block }: { block: SmoreBlock }) {
  return (
    <div className="run">
      <div className="run-body" style={{ borderTop: 0, paddingTop: 10 }}>
        <div className="run-meta">
          <Badge tone="muted" dot={false}>
            #{block.position} {block.block_type}
          </Badge>
          {block.pending_vision_extraction && (
            <Badge tone="warn">
              <IconImage /> awaiting vision extraction
            </Badge>
          )}
          <span>{relativeTime(block.first_seen_at)}</span>
        </div>
        {block.image_url && <img src={block.image_url} alt="" style={{ maxWidth: 220, borderRadius: 8, display: "block" }} />}
        {block.text_content && <div style={{ fontSize: 13.5 }}>{block.text_content}</div>}
        {block.vision_extracted_text && (
          <div style={{ fontSize: 13, color: "var(--ink-2)" }}>
            <b style={{ color: "var(--ink)" }}>Vision-extracted: </b>
            {block.vision_extracted_text}
          </div>
        )}
        {block.link_url && (
          <a href={block.link_url} target="_blank" rel="noreferrer" style={{ fontSize: 13 }}>
            {block.link_url}
          </a>
        )}
      </div>
    </div>
  );
}

export function NewsletterDetailModal({ newsletter, running, onClose, onRun, onEdit }: Props) {
  const [tab, setTab] = useState<Tab>("content");
  const [blocks, setBlocks] = useState<SmoreBlock[]>([]);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    if (!newsletter) return;
    setLoading(true);
    try {
      setBlocks(await listBlocks(newsletter.id));
    } finally {
      setLoading(false);
    }
  }, [newsletter]);

  useEffect(() => {
    setTab("content");
    setBlocks([]);
    if (newsletter) load();
  }, [newsletter?.id, load, newsletter]);

  useEffect(() => {
    if (newsletter && !running) load();
  }, [running, newsletter, load]);

  if (!newsletter) return null;
  const target = newsletter.school_name
    ? { type: "school", label: newsletter.school_name }
    : newsletter.district_name
      ? { type: "district", label: newsletter.district_name }
      : null;
  const pendingVision = blocks.filter((b) => b.pending_vision_extraction).length;

  return (
    <Modal
      open={Boolean(newsletter)}
      onClose={onClose}
      size="xl"
      title={newsletter.label || newsletter.url}
      subtitle={
        <>
          {target && (
            <Badge tone="info" dot={false}>
              {target.type}: {target.label}
            </Badge>
          )}
          <StatusBadge status={running ? "running" : newsletter.scheduled_job?.last_status} />
          {!newsletter.scheduled_job && (
            <Badge tone="muted" dot={false}>
              not scheduled
            </Badge>
          )}
        </>
      }
      footer={
        <>
          <button className="btn" onClick={() => onEdit(newsletter)}>
            <IconEdit /> Edit
          </button>
          <button className={`btn btn-primary ${running ? "spin" : ""}`} onClick={() => onRun(newsletter)} disabled={running || !newsletter.scheduled_job}>
            {running ? <IconRefresh /> : <IconPlay />} {running ? "Scanning…" : "Run now"}
          </button>
        </>
      }
    >
      <div className="utabs" role="tablist">
        <button role="tab" aria-selected={tab === "content"} onClick={() => setTab("content")}>
          Content {blocks.length > 0 && `(${blocks.length})`}
        </button>
        <button role="tab" aria-selected={tab === "overview"} onClick={() => setTab("overview")}>
          Overview
        </button>
      </div>

      {tab === "overview" ? (
        <dl className="kv">
          <dt>URL</dt>
          <dd>
            <a href={newsletter.url} target="_blank" rel="noreferrer">
              {newsletter.url}
            </a>
          </dd>
          {newsletter.scheduled_job && (
            <>
              <dt>Schedule</dt>
              <dd>
                {describeCron(newsletter.scheduled_job.cron_expr)} <span className="code-chip">{newsletter.scheduled_job.cron_expr}</span> ·{" "}
                {newsletter.scheduled_job.timezone}
              </dd>
              <dt>Enabled</dt>
              <dd>{newsletter.scheduled_job.enabled ? "Yes" : "No - paused"}</dd>
              <dt>Next run</dt>
              <dd>{newsletter.scheduled_job.enabled && newsletter.scheduled_job.next_run_at ? relativeTime(newsletter.scheduled_job.next_run_at) : "—"}</dd>
            </>
          )}
          <dt>Last scanned</dt>
          <dd>{newsletter.last_scanned_at ? `${relativeTime(newsletter.last_scanned_at)} · ${fmtDateTime(newsletter.last_scanned_at)}` : "never"}</dd>
          {newsletter.scheduled_job?.last_error && (
            <>
              <dt>Last error</dt>
              <dd className="run-err">{newsletter.scheduled_job.last_error}</dd>
            </>
          )}
          {newsletter.latest_summary && (
            <>
              <dt>Latest summary</dt>
              <dd>{newsletter.latest_summary}</dd>
            </>
          )}
          <dt>Created</dt>
          <dd>{fmtDateTime(newsletter.created_at)}</dd>
        </dl>
      ) : loading && blocks.length === 0 ? (
        <p className="note">Loading content…</p>
      ) : blocks.length === 0 ? (
        <div className="empty">No content fetched yet - use "Run now" to scan it for the first time.</div>
      ) : (
        <>
          {pendingVision > 0 && (
            <div className="form-error" style={{ background: "var(--warn-soft)", color: "var(--warn)" }}>
              {pendingVision} image block{pendingVision === 1 ? "" : "s"} still awaiting vision extraction.
            </div>
          )}
          <div className="runs">
            {blocks.map((b) => (
              <BlockRow block={b} key={b.id} />
            ))}
          </div>
        </>
      )}
    </Modal>
  );
}
