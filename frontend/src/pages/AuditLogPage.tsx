import { useEffect, useState } from "react";
import { apiFetch } from "../api";
import { Badge, type Tone } from "../components/ui/Badge";
import { DataTable, type Column } from "../components/ui/DataTable";
import { PageHeader } from "../components/ui/PageHeader";
import { SectionCard } from "../components/ui/SectionCard";

export type AuditEvent = {
  id: number;
  ts: string;
  action: string;
  outcome: "success" | "denied" | "failed";
  status: number | null;
  actor_user_id: string | null;
  actor: string | null;
  credential: "session" | "api_key" | null;
  api_key_id: string | null;
  method: string | null;
  route: string | null;
  target: Record<string, string | number | boolean> | null;
  request_id: string | null;
};

type Page = { events: AuditEvent[]; next_before_id: number | null };

/** What each action means, in words (backend services/audit.py). An action
 * missing here shows as its raw name, so a new one is never hidden. */
export const ACTION_LABELS: Record<string, string> = {
  "auth.sign_in": "Signed in",
  "auth.mfa_passed": "Passed two-step sign-in",
  "account.change_password": "Changed password",
  "account.reset_password": "Reset password",
  "account.delete": "Deleted account",
  "api_key.create": "Created API key",
  "api_key.update": "Changed API key",
  "api_key.revoke": "Revoked API key",
  "api_key.device_approve": "Approved API key request",
  "api_key.device_deny": "Denied API key request",
  "api_key.device_issued": "API key handed to the script",
  "secret.request": "Asked for prod secrets",
  "secret.approve": "Approved prod secret access",
  "secret.deny": "Denied prod secret access",
  "secret.collected": "Prod secrets unlocked",
  "role.create": "Created role",
  "role.update": "Changed role",
  "role.delete": "Deleted role",
  "user.set_roles": "Changed someone's roles",
  "user.set_super_admin": "Changed super admin",
  "guardian.invite_accept": "Accepted guardian invite",
  "student_account.invite_accept": "Accepted student account invite",
  "student_account.delete": "Removed a student's login",
  "connection.connect": "Connected Gmail",
  "connection.disconnect": "Disconnected Gmail",
  "email_scanner.create": "Created email scanner",
  "email_scanner.update": "Changed email scanner",
  "email_scanner.delete": "Deleted email scanner",
  "chatbot.settings": "Changed chatbot settings",
};

/** Filter chips: each is one action prefix the API filters on. */
const CATEGORIES: { label: string; prefix: string }[] = [
  { label: "All", prefix: "" },
  { label: "Sign-ins", prefix: "auth." },
  { label: "Accounts", prefix: "account." },
  { label: "Roles", prefix: "role." },
  { label: "Admins", prefix: "user." },
  { label: "API keys", prefix: "api_key." },
  { label: "Prod secrets", prefix: "secret." },
  { label: "Children's access", prefix: "guardian." },
  { label: "Student logins", prefix: "student_account." },
  { label: "Gmail", prefix: "connection." },
  { label: "Email scanners", prefix: "email_scanner." },
  { label: "Localz", prefix: "resources." },
  { label: "Chatbot", prefix: "chatbot." },
];

const OUTCOMES: { label: string; value: "" | "denied" | "failed" }[] = [
  { label: "Any outcome", value: "" },
  { label: "Refused", value: "denied" },
  { label: "Failed", value: "failed" },
];

const OUTCOME_BADGE: Record<AuditEvent["outcome"], { tone: Tone; label: string }> = {
  success: { tone: "ok", label: "Done" },
  denied: { tone: "bad", label: "Refused" },
  failed: { tone: "warn", label: "Failed" },
};

export function actionLabel(action: string): string {
  if (ACTION_LABELS[action]) return ACTION_LABELS[action];
  if (action.startsWith("resources.")) return `Localz: ${action.slice("resources.".length).replace(/_/g, " ")}`;
  return action;
}

function targetText(target: AuditEvent["target"]): string {
  if (!target) return "";
  return Object.entries(target)
    .map(([k, v]) => `${k.replace(/_/g, " ")}: ${v}`)
    .join(" · ");
}

async function fetchPage(
  prefix: string,
  outcome: string,
  beforeId: number | null,
): Promise<{ page: Page | null; error: string | null }> {
  const params = new URLSearchParams({ limit: "50" });
  if (prefix) params.set("action", prefix);
  if (outcome) params.set("outcome", outcome);
  if (beforeId !== null) params.set("before_id", String(beforeId));
  const res = await apiFetch(`/admin/audit-log?${params}`);
  if (!res.ok) {
    return { page: null, error: res.status === 403 ? "Only super admins can read the audit log." : "Couldn't load the audit log." };
  }
  return { page: await res.json(), error: null };
}

/** Who did what to whom: the append-only audit log, newest first. Super
 * admins only; nothing here can be changed or removed. */
export function AuditLogPage() {
  const [prefix, setPrefix] = useState("");
  const [outcome, setOutcome] = useState<"" | "denied" | "failed">("");
  const [events, setEvents] = useState<AuditEvent[] | null>(null);
  const [next, setNext] = useState<number | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    fetchPage(prefix, outcome, null).then(({ page, error }) => {
      if (!live) return;
      setError(error);
      setEvents(page?.events ?? []);
      setNext(page?.next_before_id ?? null);
    });
    return () => {
      live = false;
    };
  }, [prefix, outcome]);

  const loadOlder = async () => {
    if (next === null) return;
    setLoadingMore(true);
    const { page, error } = await fetchPage(prefix, outcome, next);
    setLoadingMore(false);
    setError(error);
    if (!page) return;
    setEvents((prev) => [...(prev ?? []), ...page.events]);
    setNext(page.next_before_id);
  };

  const columns: Column<AuditEvent>[] = [
    {
      id: "ts",
      header: "When",
      cell: (e) => new Date(e.ts).toLocaleString(),
    },
    {
      id: "action",
      header: "What",
      cell: (e) => (
        <span>
          {actionLabel(e.action)}
          {targetText(e.target) && (
            <span className="note" style={{ display: "block", wordBreak: "break-word" }}>
              {targetText(e.target)}
            </span>
          )}
        </span>
      ),
    },
    {
      id: "outcome",
      header: "Outcome",
      cell: (e) => (
        <Badge tone={OUTCOME_BADGE[e.outcome].tone}>
          {OUTCOME_BADGE[e.outcome].label}
          {e.outcome !== "success" && e.status ? ` (${e.status})` : ""}
        </Badge>
      ),
    },
    {
      id: "actor",
      header: "Who",
      cell: (e) => (
        <span>
          {e.actor ?? (e.actor_user_id ? "Deleted account" : "Not signed in")}
          {e.credential === "api_key" && (
            <span className="note" style={{ display: "block" }}>
              via API key
            </span>
          )}
        </span>
      ),
    },
  ];

  return (
    <div>
      <PageHeader
        title="Audit log"
        subtitle="Who signed in and who changed access, roles, API keys, prod secrets and inbox connections. Entries can't be edited or deleted."
      />
      <SectionCard title="Events" description="Newest first. Addresses are stored scrambled, never as IP addresses.">
        <div className="chips" role="group" aria-label="Filter by kind of event" style={{ marginBottom: 8 }}>
          {CATEGORIES.map((c) => (
            <button key={c.label} className="chip" aria-pressed={prefix === c.prefix} onClick={() => {
                if (c.prefix === prefix) return;
                setEvents(null);
                setPrefix(c.prefix);
              }}>
              {c.label}
            </button>
          ))}
        </div>
        <div className="chips" role="group" aria-label="Filter by outcome" style={{ marginBottom: 12 }}>
          {OUTCOMES.map((o) => (
            <button key={o.label} className="chip" aria-pressed={outcome === o.value} onClick={() => {
                if (o.value === outcome) return;
                setEvents(null);
                setOutcome(o.value);
              }}>
              {o.label}
            </button>
          ))}
        </div>
        {error ? (
          <p className="note">{error}</p>
        ) : (
          <DataTable
            columns={columns}
            rows={events ?? []}
            getRowId={(e) => String(e.id)}
            loading={events === null}
            empty="Nothing recorded yet for this filter."
          />
        )}
        {next !== null && !error && (
          <div style={{ marginTop: 12 }}>
            <button className="btn sm" onClick={loadOlder} disabled={loadingMore}>
              {loadingMore ? "Loading…" : "Load older"}
            </button>
          </div>
        )}
      </SectionCard>
    </div>
  );
}
