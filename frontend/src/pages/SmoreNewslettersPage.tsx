import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiFetch } from "../api";
import { IconChevronLeft, IconChevronRight } from "../components/icons";

type ScheduledJob = {
  cron_expr: string;
  enabled: boolean;
  last_run_at: string | null;
  last_status: string | null;
  last_error: string | null;
};
type Newsletter = {
  id: string;
  url: string;
  label: string | null;
  last_scanned_at: string | null;
  scheduled_job: ScheduledJob | null;
};
type Block = {
  id: string;
  block_type: string;
  text_content: string | null;
  image_url: string | null;
  link_url: string | null;
  pending_vision_extraction: boolean;
  first_seen_at: string;
};

export function SmoreNewslettersPage() {
  const [newsletters, setNewsletters] = useState<Newsletter[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [url, setUrl] = useState("");
  const [label, setLabel] = useState("");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [blocks, setBlocks] = useState<Block[]>([]);
  const [runningIds, setRunningIds] = useState<Set<string>>(new Set());
  const [reextractingIds, setReextractingIds] = useState<Set<string>>(new Set());
  const [lastReextractResult, setLastReextractResult] = useState<{ id: string; summary: string } | null>(null);

  const load = async () => {
    const res = await apiFetch("/smore-newsletters");
    const body: Newsletter[] = res.ok ? await res.json() : [];
    setNewsletters(body);
    return body;
  };

  useEffect(() => {
    load();
  }, []);

  const addNewsletter = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    const res = await apiFetch("/smore-newsletters", {
      method: "POST",
      body: JSON.stringify({ url, label: label || null }),
    });
    const body = await res.json();
    if (!res.ok) {
      setError(body.detail ?? "Could not add newsletter");
      return;
    }
    setUrl("");
    setLabel("");
    load();
  };

  // A scan can take well over a minute (vision extraction on image blocks
  // is the slow part) - the old version fired-and-forgot with a single
  // reload 3s later, which almost never caught the finish, making the
  // button look like it did nothing. This disables the button, shows
  // "Running…", and polls until this newsletter's last_run_at actually
  // moves past the click time (or we give up after ~3 minutes).
  const runNow = async (id: string) => {
    if (runningIds.has(id)) return; // already in flight - avoid pointless "skipped" runs from double-clicks
    const before = newsletters.find((n) => n.id === id)?.scheduled_job?.last_run_at ?? null;
    setRunningIds((prev) => new Set(prev).add(id));
    setError(null);
    try {
      const res = await apiFetch(`/smore-newsletters/${id}/run-now`, { method: "POST" });
      if (!res.ok) {
        setError("Could not start the scan - try again in a moment.");
        setRunningIds((prev) => {
          const next = new Set(prev);
          next.delete(id);
          return next;
        });
        return;
      }
      for (let attempt = 0; attempt < 36; attempt++) {
        await new Promise((r) => setTimeout(r, 5000));
        const fresh = await load();
        const current = fresh.find((n) => n.id === id)?.scheduled_job?.last_run_at ?? null;
        if (current && current !== before) break;
      }
    } finally {
      setRunningIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    }
  };

  // Escape hatch for "a scan reported success but produced far fewer items
  // than the newsletter actually has" (real case: a large newsletter hit
  // the extraction call's max_tokens and landed 0 items with no error at
  // all). run-now can't fix this - it only ever extracts *newly-seen*
  // blocks, and these are already stored. This reprocesses every block the
  // newsletter has ever fetched, synchronously, so the real result comes
  // straight back instead of needing to poll. Deliberately not offered as
  // a routine refresh: reprocessing a newsletter that already extracted
  // cleanly will duplicate its items (dedup is only at the block level).
  const reextractAll = async (id: string) => {
    if (reextractingIds.has(id)) return;
    if (
      !window.confirm(
        "Re-extract every block this newsletter has ever fetched?\n\nOnly do this if it's currently missing items it should have (e.g. a scan reported success with far fewer items than expected). Re-running extraction on a newsletter that already extracted correctly will create duplicate items."
      )
    ) {
      return;
    }
    setReextractingIds((prev) => new Set(prev).add(id));
    setError(null);
    setLastReextractResult(null);
    try {
      const res = await apiFetch(`/smore-newsletters/${id}/reextract-all`, { method: "POST" });
      const body = await res.json();
      if (!res.ok) {
        setError(body.detail ?? "Could not re-extract this newsletter.");
        return;
      }
      setLastReextractResult({ id, summary: body.summary });
    } finally {
      setReextractingIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    }
  };

  const viewBlocks = async (id: string) => {
    if (expandedId === id) {
      setExpandedId(null);
      return;
    }
    const res = await apiFetch(`/smore-newsletters/${id}/blocks`);
    setBlocks(res.ok ? await res.json() : []);
    setExpandedId(id);
  };

  return (
    <div style={{ maxWidth: 640, margin: "3rem auto", fontFamily: "sans-serif" }}>
      <p>
        <Link to="/" className="back-link">
          <IconChevronLeft /> Home
        </Link>
      </p>
      <h1>School Newsletters (Smore)</h1>
      {error && <p style={{ color: "crimson" }}>{error}</p>}

      {newsletters.length === 0 ? (
        <p>No newsletters tracked yet.</p>
      ) : (
        <ul style={{ listStyle: "none", padding: 0 }}>
          {newsletters.map((n) => (
            <li key={n.id} style={{ border: "1px solid #ccc", borderRadius: 6, padding: "0.75rem", marginBottom: "0.5rem" }}>
              <strong>{n.label ?? n.url}</strong>
              <br />
              <small>
                {n.scheduled_job
                  ? `cron: ${n.scheduled_job.cron_expr} · last run: ${n.scheduled_job.last_status ?? "never"}`
                  : "not scheduled"}
                {n.last_scanned_at && ` · last scanned ${n.last_scanned_at}`}
              </small>
              <br />
              <button onClick={() => runNow(n.id)} disabled={runningIds.has(n.id)}>
                {runningIds.has(n.id) ? "Running…" : "Run now"}
              </button>{" "}
              <button onClick={() => viewBlocks(n.id)}>{expandedId === n.id ? "Hide" : "View"} content</button>{" "}
              <button
                onClick={() => reextractAll(n.id)}
                disabled={reextractingIds.has(n.id)}
                title="Re-extract every fetched block - only for a newsletter that's missing items it should have"
              >
                {reextractingIds.has(n.id) ? "Re-extracting…" : "Force re-extract"}
              </button>
              {lastReextractResult?.id === n.id && (
                <p style={{ fontSize: "0.85em", color: "#555" }}>{lastReextractResult.summary}</p>
              )}
              {expandedId === n.id && (
                <ul style={{ marginTop: "0.5rem" }}>
                  {blocks.map((b) => (
                    <li key={b.id} style={{ marginBottom: "0.5rem" }}>
                      <em>{b.block_type}</em>
                      {b.pending_vision_extraction && (
                        <span style={{ color: "#a66", marginLeft: "0.5rem" }}>
                          (image - needs vision extraction, not run yet)
                        </span>
                      )}
                      <br />
                      {b.text_content && <span>{b.text_content}</span>}
                      {b.image_url && (
                        <div>
                          <img src={b.image_url} alt="" style={{ maxWidth: 200 }} />
                        </div>
                      )}
                      {b.link_url && <div>{b.link_url}</div>}
                    </li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ul>
      )}

      <h2>Track a newsletter</h2>
      <form onSubmit={addNewsletter}>
        <label>
          Smore URL
          <input value={url} onChange={(e) => setUrl(e.target.value)} required style={{ width: "100%" }} />
        </label>
        <br />
        <label>
          Label (optional)
          <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Bret Harte Weekly" />
        </label>
        <br />
        <button type="submit">Add</button>
      </form>
    </div>
  );
}
