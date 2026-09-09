import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiFetch } from "../api";

type Connection = { google_email: string; last_synced_at: string | null; created_at: string };
type ScheduledJob = {
  id: string;
  cron_expr: string;
  enabled: boolean;
  last_run_at: string | null;
  last_status: string | null;
  last_error: string | null;
};
type Scanner = {
  id: string;
  google_email: string;
  name: string;
  from_contains: string[];
  subject_contains: string[];
  body_contains: string[];
  lookback_days: number;
  enabled: boolean;
  scheduled_job: ScheduledJob | null;
};
type SchoolEmail = {
  id: string;
  sender: string | null;
  subject: string | null;
  received_at: string | null;
  newsletter_links: { url: string }[];
};

function csvToList(value: string): string[] {
  return value
    .split(",")
    .map((v) => v.trim())
    .filter(Boolean);
}

export function GmailPage() {
  const [connections, setConnections] = useState<Connection[]>([]);
  const [scanners, setScanners] = useState<Scanner[]>([]);
  const [emails, setEmails] = useState<SchoolEmail[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [fromContains, setFromContains] = useState("");
  const [subjectContains, setSubjectContains] = useState("");
  const [cronExpr, setCronExpr] = useState("0 7 * * *");

  const loadAll = async () => {
    const [c, s, e] = await Promise.all([
      apiFetch("/gmail/connections").then((r) => (r.ok ? r.json() : [])),
      apiFetch("/email-scanners").then((r) => (r.ok ? r.json() : [])),
      apiFetch("/school-emails").then((r) => (r.ok ? r.json() : [])),
    ]);
    setConnections(c);
    setScanners(s);
    setEmails(e);
  };

  useEffect(() => {
    loadAll();
    const onMessage = (event: MessageEvent) => {
      if (event.data === "gmail:connected") loadAll();
      if (event.data === "gmail:error") setError("Gmail connection failed or was cancelled.");
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, []);

  const connectGmail = async () => {
    setError(null);
    const res = await apiFetch("/gmail/auth-url");
    const body = await res.json();
    if (!res.ok) {
      setError(body.detail ?? "Could not start Gmail connection");
      return;
    }
    window.open(body.url, "gmail-oauth", "width=500,height=700");
  };

  const disconnect = async (googleEmail: string) => {
    await apiFetch(`/gmail/disconnect?google_email=${encodeURIComponent(googleEmail)}`, { method: "DELETE" });
    loadAll();
  };

  const createScanner = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!connections[0]) {
      setError("Connect a Gmail account first.");
      return;
    }
    const res = await apiFetch("/email-scanners", {
      method: "POST",
      body: JSON.stringify({
        google_email: connections[0].google_email,
        name,
        from_contains: csvToList(fromContains),
        subject_contains: csvToList(subjectContains),
        cron_expr: cronExpr,
        purpose: "school_email",
      }),
    });
    const body = await res.json();
    if (!res.ok) {
      setError(body.detail ?? "Could not create scanner");
      return;
    }
    setName("");
    setFromContains("");
    setSubjectContains("");
    loadAll();
  };

  const runNow = async (scannerId: string) => {
    await apiFetch(`/email-scanners/${scannerId}/run-now`, { method: "POST" });
    setTimeout(loadAll, 2000);
  };

  return (
    <div style={{ maxWidth: 640, margin: "3rem auto", fontFamily: "sans-serif" }}>
      <p>
        <Link to="/">&larr; Home</Link>
      </p>
      <h1>Email Parser</h1>
      {error && <p style={{ color: "crimson" }}>{error}</p>}

      <h2>Connected Gmail accounts</h2>
      {connections.length === 0 ? (
        <p>No Gmail account connected yet.</p>
      ) : (
        <ul>
          {connections.map((c) => (
            <li key={c.google_email}>
              {c.google_email}{" "}
              <button onClick={() => disconnect(c.google_email)}>Disconnect</button>
            </li>
          ))}
        </ul>
      )}
      <button onClick={connectGmail}>Connect Gmail account</button>

      <h2>Recurring scanners</h2>
      {scanners.length === 0 ? (
        <p>No scanners yet.</p>
      ) : (
        <ul style={{ listStyle: "none", padding: 0 }}>
          {scanners.map((s) => (
            <li key={s.id} style={{ border: "1px solid #ccc", borderRadius: 6, padding: "0.75rem", marginBottom: "0.5rem" }}>
              <strong>{s.name}</strong> ({s.google_email})
              <br />
              <small>
                cron: {s.scheduled_job?.cron_expr} · last run: {s.scheduled_job?.last_status ?? "never"}
                {s.scheduled_job?.last_error && ` (${s.scheduled_job.last_error})`}
              </small>
              <br />
              <button onClick={() => runNow(s.id)}>Run now</button>
            </li>
          ))}
        </ul>
      )}

      <h3>Add a scanner</h3>
      <form onSubmit={createScanner}>
        <label>
          Name
          <input value={name} onChange={(e) => setName(e.target.value)} required />
        </label>
        <br />
        <label>
          From contains (comma-separated)
          <input value={fromContains} onChange={(e) => setFromContains(e.target.value)} placeholder="chclc.org" />
        </label>
        <br />
        <label>
          Subject contains (comma-separated)
          <input value={subjectContains} onChange={(e) => setSubjectContains(e.target.value)} />
        </label>
        <br />
        <label>
          Cron expression
          <input value={cronExpr} onChange={(e) => setCronExpr(e.target.value)} />
        </label>
        <br />
        <button type="submit">Create scanner</button>
      </form>

      <h2>Captured school emails</h2>
      {emails.length === 0 ? (
        <p>None captured yet.</p>
      ) : (
        <ul style={{ listStyle: "none", padding: 0 }}>
          {emails.map((m) => (
            <li key={m.id} style={{ border: "1px solid #ddd", borderRadius: 6, padding: "0.5rem", marginBottom: "0.4rem" }}>
              <strong>{m.subject ?? "(no subject)"}</strong>
              <br />
              <small>
                {m.sender} · {m.received_at ?? "unknown date"}
              </small>
              {m.newsletter_links.length > 0 && (
                <div>
                  Newsletter link(s): {m.newsletter_links.map((l) => l.url).join(", ")}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
