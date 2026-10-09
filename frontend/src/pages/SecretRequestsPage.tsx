import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiFetch } from "../api";
import { Badge, type Tone } from "../components/ui/Badge";
import { DataTable, type Column } from "../components/ui/DataTable";
import { PageHeader } from "../components/ui/PageHeader";
import { SectionCard } from "../components/ui/SectionCard";

export type SecretRequest = {
  user_code: string;
  client_name: string;
  reason: string;
  command: string;
  secret_names: string[];
  requested_ip: string | null;
  api_key_name: string | null;
  created_at: string;
  expires_at: string;
  status: "pending" | "approved" | "denied" | "collected" | "expired";
  decided_by: string | null;
  decided_at: string | null;
  collected_at: string | null;
};

export const SECRET_STATUS: Record<SecretRequest["status"], { tone: Tone; label: string }> = {
  pending: { tone: "info", label: "Waiting" },
  approved: { tone: "warn", label: "Approved, not used yet" },
  collected: { tone: "ok", label: "Used" },
  denied: { tone: "bad", label: "Denied" },
  expired: { tone: "muted", label: "Expired" },
};

/** The audit log of every request to use the prod secrets vault, newest first,
 * and the way back to any request still waiting for an answer. */
export function SecretRequestsPage() {
  const [rows, setRows] = useState<SecretRequest[] | null>(null);

  useEffect(() => {
    apiFetch("/admin/secret-requests")
      .then((r) => (r.ok ? r.json() : []))
      .then(setRows);
  }, []);

  const columns: Column<SecretRequest>[] = [
    {
      id: "created_at",
      header: "Asked",
      sortValue: (r) => r.created_at,
      cell: (r) => new Date(r.created_at).toLocaleString(),
    },
    {
      id: "status",
      header: "Status",
      sortValue: (r) => r.status,
      cell: (r) => (
        <Badge tone={SECRET_STATUS[r.status].tone}>{SECRET_STATUS[r.status].label}</Badge>
      ),
    },
    {
      id: "reason",
      header: "Why / what",
      cell: (r) => (
        <span>
          {r.reason}
          <code className="note" style={{ display: "block", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
            {r.command}
          </code>
        </span>
      ),
    },
    {
      id: "secrets",
      header: "Secrets",
      cell: (r) => (
        <span style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
          {r.secret_names.map((n) => (
            <Badge key={n} tone="info" dot={false}>
              {n}
            </Badge>
          ))}
        </span>
      ),
    },
    {
      id: "from",
      header: "From",
      cell: (r) => (
        <span>
          {r.client_name}
          {r.api_key_name && <span className="note" style={{ display: "block" }}>key: {r.api_key_name}</span>}
        </span>
      ),
    },
    {
      id: "decided_by",
      header: "Answered by",
      cell: (r) => r.decided_by ?? "—",
    },
  ];

  return (
    <div>
      <PageHeader
        title="Secret access"
        subtitle="Requests from scripts and agents to use the prod secrets vault. Each one states why, what it will run and which secrets it needs; an approval unlocks once, for a few minutes."
      />
      <SectionCard title="Requests" description="The most recent 50. Nothing here holds a secret value.">
        <DataTable
          columns={columns}
          rows={rows ?? []}
          getRowId={(r) => r.user_code}
          loading={rows === null}
          defaultSort={{ id: "created_at", dir: "desc" }}
          empty="No requests yet."
          rowActions={(r) =>
            r.status === "pending" ? (
              <Link className="btn sm btn-primary" to={`/admin/secret-requests/approve?code=${encodeURIComponent(r.user_code)}`}>
                Review
              </Link>
            ) : null
          }
        />
      </SectionCard>
    </div>
  );
}
