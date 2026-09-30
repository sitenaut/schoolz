import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { apiFetch } from "../api";
import { PermissionPicker, permissionLabel, type Permission } from "../components/PermissionPicker";
import { Badge } from "../components/ui/Badge";
import { Field } from "../components/ui/Field";
import { PageHeader } from "../components/ui/PageHeader";
import { SectionCard } from "../components/ui/SectionCard";
import { EXPIRY_OPTIONS, ONBOARDING_PRESET } from "./ApiKeysPage";

type LoginRequest = {
  user_code: string;
  client_name: string;
  requested_ip: string | null;
  created_at: string;
  expires_at: string;
  status: "pending" | "approved" | "denied" | "issued" | "expired";
};

/** Where `scripts/schoolz-api.sh login` sends you: approve a script's login
 * request from any signed-in browser (usually a phone). The key goes
 * straight to the script; nothing here ever shows it. */
export function ApproveApiKeyPage() {
  const [params] = useSearchParams();
  const code = (params.get("code") ?? "").trim();
  const [req, setReq] = useState<LoginRequest | null>(null);
  const [missing, setMissing] = useState(false);
  const [permissions, setPermissions] = useState<Permission[]>([]);
  const [name, setName] = useState("");
  const [expiry, setExpiry] = useState("90");
  const [picked, setPicked] = useState<Set<string>>(new Set(ONBOARDING_PRESET));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // Collapsed by default: on a phone the full list pushes Approve far below the fold.
  const [editingPerms, setEditingPerms] = useState(false);

  const load = useCallback(async () => {
    if (!code) return;
    const r = await apiFetch(`/admin/api-keys/requests/${encodeURIComponent(code)}`);
    if (r.status === 404) {
      setMissing(true);
      return;
    }
    if (r.ok) {
      const body: LoginRequest = await r.json();
      setReq(body);
      setName((cur) => cur || body.client_name);
    }
  }, [code]);

  useEffect(() => {
    apiFetch("/admin/permissions").then((r) => (r.ok ? r.json() : [])).then(setPermissions);
    load();
  }, [load]);

  // After approving, watch for the script to collect its key.
  useEffect(() => {
    if (req?.status !== "approved") return;
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [req?.status, load]);

  const toggle = (key: string) =>
    setPicked((cur) => {
      const next = new Set(cur);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const answer = async (action: "approve" | "deny") => {
    setBusy(true);
    setError(null);
    try {
      const body =
        action === "approve"
          ? JSON.stringify({ name: name.trim() || null, permissions: [...picked], expires_in_days: expiry === "never" ? null : Number(expiry) })
          : undefined;
      const r = await apiFetch(`/admin/api-keys/requests/${encodeURIComponent(code)}/${action}`, { method: "POST", body });
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

  const header = <PageHeader title="Approve API key" back={{ to: "/admin/api-keys", label: "API keys" }} />;

  if (!code || missing) {
    return (
      <div>
        {header}
        <SectionCard title="No such request">
          <p className="note">This link has no valid login code. Start again from the script.</p>
        </SectionCard>
      </div>
    );
  }
  if (!req) return <div>{header}</div>;

  const done: Record<Exclude<LoginRequest["status"], "pending">, string> = {
    approved: "Approved. Waiting for the script to collect its key…",
    issued: "Done. The script has its key and saved it. You can close this page.",
    denied: "Denied. The script got nothing.",
    expired: "This request expired. Start again from the script.",
  };

  return (
    <div>
      {header}
      <SectionCard title="Login request" description="A script asked for an API key. Only approve if you started this yourself in the last few minutes.">
        <div style={{ textAlign: "center", margin: "4px 0 12px" }}>
          <div className="note">Code</div>
          <div style={{ fontFamily: "var(--mono, monospace)", fontSize: 30, fontWeight: 700, letterSpacing: "0.12em" }}>{req.user_code}</div>
          <div className="note">It must match the code the script printed.</div>
        </div>
        <dl style={{ display: "grid", gridTemplateColumns: "max-content 1fr", gap: "4px 12px", margin: 0 }}>
          <dt className="note">From</dt>
          <dd style={{ margin: 0 }}>{req.client_name}</dd>
          <dt className="note">IP</dt>
          <dd style={{ margin: 0 }}>{req.requested_ip ?? "unknown"}</dd>
          <dt className="note">Requested</dt>
          <dd style={{ margin: 0 }}>{new Date(req.created_at).toLocaleString()}</dd>
        </dl>
      </SectionCard>

      {req.status !== "pending" ? (
        <SectionCard title={req.status === "issued" ? "Key delivered" : "Status"}>
          <p style={{ margin: 0 }}>{done[req.status]}</p>
          {req.status === "issued" && (
            <p className="note">
              It's listed under <Link to="/admin/api-keys">API keys</Link>, where you can revoke it.
            </p>
          )}
        </SectionCard>
      ) : (
        <SectionCard title="What it may do">
          {error && <div className="form-error">{error}</div>}
          <Field label="Key name">
            <input value={name} onChange={(e) => setName(e.target.value)} maxLength={100} />
          </Field>
          <Field label="Expires">
            <select value={expiry} onChange={(e) => setExpiry(e.target.value)}>
              {EXPIRY_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </Field>
          {editingPerms ? (
            <PermissionPicker permissions={permissions} picked={picked} onToggle={toggle} />
          ) : (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center" }}>
              {[...picked].sort().map((p) => (
                <Badge key={p} tone={permissions.find((x) => x.key === p)?.sensitive ? "warn" : "info"} dot={false}>
                  {permissionLabel(permissions, p)}
                </Badge>
              ))}
              <button type="button" className="btn sm" onClick={() => setEditingPerms(true)}>
                Change
              </button>
            </div>
          )}
          <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", flexWrap: "wrap", marginTop: 12 }}>
            <button className="btn" disabled={busy} onClick={() => answer("deny")}>
              Deny
            </button>
            <button className="btn btn-primary" disabled={busy || picked.size === 0} onClick={() => answer("approve")}>
              {busy ? "Working…" : "Approve"}
            </button>
          </div>
        </SectionCard>
      )}
    </div>
  );
}
