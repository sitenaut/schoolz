import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "../api";
import { PermissionPicker, permissionLabel, type Permission } from "../components/PermissionPicker";
import { Badge } from "../components/ui/Badge";
import { ConfirmDialog } from "../components/ui/ConfirmDialog";
import { DataTable, type Column } from "../components/ui/DataTable";
import { Field } from "../components/ui/Field";
import { Modal } from "../components/ui/Modal";
import { PageHeader } from "../components/ui/PageHeader";
import { SectionCard } from "../components/ui/SectionCard";
import { useToast } from "../components/ui/Toast";

type ApiKey = {
  id: string;
  name: string;
  key_prefix: string;
  permissions: string[];
  created_by_email: string | null;
  created_at: string;
  expires_at: string | null;
  last_used_at: string | null;
};
type CreatedKey = ApiKey & { key: string };

export const EXPIRY_OPTIONS = [
  { value: "30", label: "30 days" },
  { value: "90", label: "90 days" },
  { value: "365", label: "1 year" },
  { value: "never", label: "Never" },
];

/** What seeding a district or local-events sources needs: config import plus
 * editing and running the scans it creates. */
export const ONBOARDING_PRESET = ["config.manage", "scans.manage", "schools.manage", "newsletters.manage"];

const envVarName = () =>
  ["localhost", "127.0.0.1"].includes(window.location.hostname) ? "SCHOOLZ_API_KEY_LOCAL" : "SCHOOLZ_API_KEY_PROD";

async function errorText(res: Response, fallback: string): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail) && body.detail[0]?.msg) return body.detail[0].msg;
  } catch {
    /* fall through */
  }
  return fallback;
}

const fmtDate = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString() : "—");

/** Super-admin-only: bearer keys for scripts and agents (e.g. Claude Code
 * seeding a district through /admin/config/import). A key acts as the super
 * admin who made it, narrowed to the permissions ticked here, and can never
 * reach this page or Users & roles. */
export function ApiKeysPage() {
  const toast = useToast();
  const [permissions, setPermissions] = useState<Permission[]>([]);
  const [keys, setKeys] = useState<ApiKey[] | null>(null);
  const [creating, setCreating] = useState(false);
  const [created, setCreated] = useState<CreatedKey | null>(null);
  const [revoking, setRevoking] = useState<ApiKey | null>(null);
  const [editing, setEditing] = useState<ApiKey | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const r = await apiFetch("/admin/api-keys");
    if (r.ok) setKeys(await r.json());
  }, []);

  useEffect(() => {
    apiFetch("/admin/permissions").then((r) => (r.ok ? r.json() : [])).then(setPermissions);
    load();
  }, [load]);

  const create = async (body: { name: string; permissions: string[]; expires_in_days: number | null }) => {
    const res = await apiFetch("/admin/api-keys", { method: "POST", body: JSON.stringify(body) });
    if (!res.ok) throw new Error(await errorText(res, "Could not create key"));
    setCreated(await res.json());
    setCreating(false);
    await load();
  };

  const save = async (id: string, body: { name: string; permissions: string[] }) => {
    const res = await apiFetch(`/admin/api-keys/${id}`, { method: "PATCH", body: JSON.stringify(body) });
    if (!res.ok) throw new Error(await errorText(res, "Could not update key"));
    setEditing(null);
    await load();
    toast({ title: "Key updated", tone: "ok" });
  };

  const revoke = async () => {
    if (!revoking) return;
    setBusy(true);
    try {
      const res = await apiFetch(`/admin/api-keys/${revoking.id}`, { method: "DELETE" });
      if (!res.ok) throw new Error(await errorText(res, "Could not revoke key"));
      setRevoking(null);
      await load();
      toast({ title: "Key revoked", tone: "ok" });
    } catch (e) {
      toast({ title: "Couldn't revoke key", description: e instanceof Error ? e.message : undefined, tone: "bad" });
    } finally {
      setBusy(false);
    }
  };

  const columns: Column<ApiKey>[] = [
    {
      id: "name",
      header: "Name",
      sortValue: (k) => k.name.toLowerCase(),
      cell: (k) => (
        <span>
          <strong>{k.name}</strong>
          <span className="note" style={{ display: "block", fontFamily: "var(--mono, monospace)" }}>
            {k.key_prefix}…
          </span>
        </span>
      ),
    },
    {
      id: "permissions",
      header: "Can",
      cell: (k) => (
        <span style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
          {k.permissions.map((p) => (
            <Badge key={p} tone={permissions.find((x) => x.key === p)?.sensitive ? "warn" : "info"} dot={false}>
              {permissionLabel(permissions, p)}
            </Badge>
          ))}
        </span>
      ),
    },
    {
      id: "last_used_at",
      header: "Last used",
      sortValue: (k) => k.last_used_at,
      cell: (k) => (k.last_used_at ? new Date(k.last_used_at).toLocaleString() : "Never"),
    },
    {
      id: "expires_at",
      header: "Expires",
      sortValue: (k) => k.expires_at ?? "9999",
      cell: (k) =>
        k.expires_at && new Date(k.expires_at) <= new Date() ? (
          <Badge tone="bad">Expired</Badge>
        ) : k.expires_at ? (
          fmtDate(k.expires_at)
        ) : (
          "Never"
        ),
    },
    {
      id: "created_at",
      header: "Created",
      sortValue: (k) => k.created_at,
      cell: (k) => (
        <span>
          {fmtDate(k.created_at)}
          {k.created_by_email && <span className="note" style={{ display: "block" }}>{k.created_by_email}</span>}
        </span>
      ),
    },
  ];

  return (
    <div>
      <PageHeader
        title="API keys"
        subtitle="For scripts and agents such as Claude Code. A key acts as you, limited to what you tick, and can never manage users, roles or other keys."
        actions={
          <button className="btn btn-primary" onClick={() => setCreating(true)}>
            New key
          </button>
        }
      />

      <SectionCard title="Keys" description="Revoking a key stops it working on its next request.">
        <DataTable
          columns={columns}
          rows={keys ?? []}
          getRowId={(k) => k.id}
          loading={keys === null}
          defaultSort={{ id: "created_at", dir: "desc" }}
          empty="No API keys yet."
          rowActions={(k) => (
            <>
              <button className="btn sm" onClick={() => setEditing(k)}>
                Edit
              </button>
              <button className="btn sm" onClick={() => setRevoking(k)}>
                Revoke
              </button>
            </>
          )}
        />
      </SectionCard>

      {creating && <NewKeyModal permissions={permissions} onClose={() => setCreating(false)} onCreate={create} />}

      {editing && <EditKeyModal apiKey={editing} permissions={permissions} onClose={() => setEditing(null)} onSave={save} />}

      {created && <CreatedKeyModal created={created} onClose={() => setCreated(null)} />}

      <ConfirmDialog
        open={!!revoking}
        title={`Revoke "${revoking?.name ?? ""}"?`}
        description="Anything still using this key starts getting 401s immediately. This can't be undone."
        confirmLabel="Revoke key"
        danger
        busy={busy}
        onConfirm={revoke}
        onCancel={() => setRevoking(null)}
      />
    </div>
  );
}

function NewKeyModal({
  permissions,
  onClose,
  onCreate,
}: {
  permissions: Permission[];
  onClose: () => void;
  onCreate: (body: { name: string; permissions: string[]; expires_in_days: number | null }) => Promise<void>;
}) {
  const [name, setName] = useState("Claude Code");
  const [expiry, setExpiry] = useState("90");
  const [picked, setPicked] = useState<Set<string>>(new Set(ONBOARDING_PRESET));
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const toggle = (key: string) =>
    setPicked((cur) => {
      const next = new Set(cur);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await onCreate({ name: name.trim(), permissions: [...picked], expires_in_days: expiry === "never" ? null : Number(expiry) });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create key");
      setSaving(false);
    }
  };

  return (
    <Modal
      open
      onClose={onClose}
      title="New API key"
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" form="api-key-form" className="btn btn-primary" disabled={saving || !name.trim() || picked.size === 0}>
            {saving ? "Creating…" : "Create key"}
          </button>
        </>
      }
    >
      <form id="api-key-form" onSubmit={submit}>
        {error && <div className="form-error">{error}</div>}
        <Field label="Name" hint="Who or what will use it.">
          <input value={name} onChange={(e) => setName(e.target.value)} maxLength={100} required />
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
        <p className="note" style={{ marginTop: 0 }}>
          Pre-ticked for onboarding: importing seed files and editing/running the scans they create.{" "}
          <button type="button" className="btn sm" onClick={() => setPicked(new Set(ONBOARDING_PRESET))}>
            Reset to onboarding
          </button>
        </p>
        <PermissionPicker permissions={permissions} picked={picked} onToggle={toggle} />
      </form>
    </Modal>
  );
}

function EditKeyModal({
  apiKey,
  permissions,
  onClose,
  onSave,
}: {
  apiKey: ApiKey;
  permissions: Permission[];
  onClose: () => void;
  onSave: (id: string, body: { name: string; permissions: string[] }) => Promise<void>;
}) {
  const [name, setName] = useState(apiKey.name);
  const [picked, setPicked] = useState<Set<string>>(new Set(apiKey.permissions));
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const toggle = (key: string) =>
    setPicked((cur) => {
      const next = new Set(cur);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await onSave(apiKey.id, { name: name.trim(), permissions: [...picked] });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update key");
      setSaving(false);
    }
  };

  return (
    <Modal
      open
      onClose={onClose}
      title="Edit API key"
      subtitle={`${apiKey.key_prefix}…`}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" form="api-key-edit-form" className="btn btn-primary" disabled={saving || !name.trim() || picked.size === 0}>
            {saving ? "Saving…" : "Save changes"}
          </button>
        </>
      }
    >
      <form id="api-key-edit-form" onSubmit={submit}>
        {error && <div className="form-error">{error}</div>}
        <Field label="Name">
          <input value={name} onChange={(e) => setName(e.target.value)} maxLength={100} required />
        </Field>
        <p className="note" style={{ marginTop: 0 }}>
          The key itself doesn't change; new permissions apply on its next request.
        </p>
        <PermissionPicker permissions={permissions} picked={picked} onToggle={toggle} />
      </form>
    </Modal>
  );
}

function CreatedKeyModal({ created, onClose }: { created: CreatedKey; onClose: () => void }) {
  const [copied, setCopied] = useState(false);
  const line = `${envVarName()}=${created.key}`;
  const copy = async () => {
    await navigator.clipboard.writeText(line);
    setCopied(true);
  };
  return (
    <Modal
      open
      onClose={onClose}
      title="Copy your key now"
      subtitle={created.name}
      footer={
        <button type="button" className="btn btn-primary" onClick={onClose}>
          Done
        </button>
      }
    >
      <p className="note" style={{ marginTop: 0 }}>
        This is the only time the key is shown. Paste the line into <code>env/api-keys.env</code>; <code>scripts/schoolz-api.sh</code> reads it
        from there.
      </p>
      <Field label="Key">
        <input readOnly value={line} onFocus={(e) => e.currentTarget.select()} style={{ fontFamily: "var(--mono, monospace)" }} />
      </Field>
      <button type="button" className="btn" onClick={copy}>
        {copied ? "Copied" : "Copy"}
      </button>
    </Modal>
  );
}
