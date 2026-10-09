import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { apiFetch } from "../api";
import { Badge } from "../components/ui/Badge";
import { PageHeader } from "../components/ui/PageHeader";
import { SectionCard } from "../components/ui/SectionCard";
import { SECRET_STATUS, type SecretRequest } from "./SecretRequestsPage";

/** Where `scripts/prod-secrets.sh run` sends you: read what a script or agent
 * wants to do with the prod secrets, and approve or deny it from any signed-in
 * browser (usually a phone). An approval lets that exact command use those
 * secrets once; nothing on this page shows a secret. */
export function ApproveSecretRequestPage() {
  const [params] = useSearchParams();
  const code = (params.get("code") ?? "").trim();
  const [req, setReq] = useState<SecretRequest | null>(null);
  const [missing, setMissing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!code) return;
    const r = await apiFetch(`/admin/secret-requests/${encodeURIComponent(code)}`);
    if (r.status === 404) {
      setMissing(true);
      return;
    }
    if (r.ok) setReq(await r.json());
  }, [code]);

  useEffect(() => {
    load();
  }, [load]);

  // After approving, watch for the script to pick the approval up.
  useEffect(() => {
    if (req?.status !== "approved") return;
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [req?.status, load]);

  const answer = async (action: "approve" | "deny") => {
    setBusy(true);
    setError(null);
    try {
      const r = await apiFetch(`/admin/secret-requests/${encodeURIComponent(code)}/${action}`, { method: "POST" });
      if (!r.ok) {
        const detail = await r.json().catch(() => null);
        throw new Error(typeof detail?.detail === "string" ? detail.detail : "Something went wrong");
      }
      setReq(await r.json());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  };

  const header = <PageHeader title="Approve secret access" back={{ to: "/admin/secret-requests", label: "Secret access" }} />;

  if (!code || missing) {
    return (
      <div>
        {header}
        <SectionCard title="No such request">
          <p className="note">This link has no valid request code. Ask again from the script.</p>
        </SectionCard>
      </div>
    );
  }
  if (!req) return <div>{header}</div>;

  const done: Record<Exclude<SecretRequest["status"], "pending">, string> = {
    approved: "Approved. Waiting for the script to pick it up…",
    collected: "Done. The script unlocked the vault and is running. This approval is used up.",
    denied: "Denied. The script got nothing.",
    expired: "This request expired. Ask again from the script.",
  };

  return (
    <div>
      {header}
      <SectionCard title="Request" description="A script asked to use the prod secrets. Only approve if you started this yourself in the last few minutes.">
        <div style={{ textAlign: "center", margin: "4px 0 12px" }}>
          <div className="note">Code</div>
          <div style={{ fontFamily: "var(--mono, monospace)", fontSize: 30, fontWeight: 700, letterSpacing: "0.12em" }}>{req.user_code}</div>
          <div className="note">It must match the code the script printed.</div>
        </div>
        <dl style={{ display: "grid", gridTemplateColumns: "max-content 1fr", gap: "6px 12px", margin: 0 }}>
          <dt className="note">Why</dt>
          <dd style={{ margin: 0 }}>{req.reason}</dd>
          <dt className="note">Will run</dt>
          <dd style={{ margin: 0 }}>
            <code style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{req.command}</code>
          </dd>
          <dt className="note">Secrets</dt>
          <dd style={{ margin: 0, display: "flex", flexWrap: "wrap", gap: 4 }}>
            {req.secret_names.map((n) => (
              <Badge key={n} tone="warn" dot={false}>
                {n}
              </Badge>
            ))}
          </dd>
          <dt className="note">From</dt>
          <dd style={{ margin: 0 }}>
            {req.client_name}
            {req.api_key_name ? ` (key: ${req.api_key_name})` : ""}
          </dd>
          <dt className="note">IP</dt>
          <dd style={{ margin: 0 }}>{req.requested_ip ?? "unknown"}</dd>
          <dt className="note">Asked</dt>
          <dd style={{ margin: 0 }}>{new Date(req.created_at).toLocaleString()}</dd>
        </dl>
      </SectionCard>

      {req.status !== "pending" ? (
        <SectionCard title="Status">
          <p style={{ margin: 0 }}>
            <Badge tone={SECRET_STATUS[req.status].tone}>{SECRET_STATUS[req.status].label}</Badge>
          </p>
          <p style={{ marginBottom: 0 }}>{done[req.status]}</p>
        </SectionCard>
      ) : (
        <SectionCard title="Your answer" description="Approving lets exactly this command read exactly these secrets, once, in the next few minutes.">
          {error && <div className="form-error">{error}</div>}
          <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", flexWrap: "wrap", marginTop: 12 }}>
            <button className="btn" disabled={busy} onClick={() => answer("deny")}>
              Deny
            </button>
            <button className="btn btn-primary" disabled={busy} onClick={() => answer("approve")}>
              {busy ? "Working…" : "Approve"}
            </button>
          </div>
        </SectionCard>
      )}
    </div>
  );
}
