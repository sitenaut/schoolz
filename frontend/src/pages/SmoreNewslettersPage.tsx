import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiFetch } from "../api";

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

  const load = async () => {
    const res = await apiFetch("/smore-newsletters");
    setNewsletters(res.ok ? await res.json() : []);
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

  const runNow = async (id: string) => {
    await apiFetch(`/smore-newsletters/${id}/run-now`, { method: "POST" });
    setTimeout(load, 3000);
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
        <Link to="/">&larr; Home</Link>
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
              <button onClick={() => runNow(n.id)}>Run now</button>{" "}
              <button onClick={() => viewBlocks(n.id)}>{expandedId === n.id ? "Hide" : "View"} content</button>
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
