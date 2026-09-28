import { useCallback, useEffect, useMemo, useState } from "react";
import { apiFetch } from "../api";
import { useAuth } from "../context/AuthContext";
import { Badge } from "../components/ui/Badge";
import { ConfirmDialog } from "../components/ui/ConfirmDialog";
import { Field } from "../components/ui/Field";
import { Modal } from "../components/ui/Modal";
import { PageHeader } from "../components/ui/PageHeader";
import { SectionCard } from "../components/ui/SectionCard";
import { useToast } from "../components/ui/Toast";

type Permission = { key: string; label: string; description: string; sensitive: boolean; access: "read" | "write" };

/** Mirrors the backend: a `.manage` permission implies its `.view`. */
const impliedView = (key: string) => (key.endsWith(".manage") ? key.replace(/\.manage$/, ".view") : null);
type Role = { id: string; name: string; description: string | null; permissions: string[]; user_count: number };
type AdminUser = { id: string; email: string; username: string; is_admin: boolean; role_ids: string[]; created_at: string | null };

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

/** Super-admin-only: who can do what in the admin area. A role is a named
 * set of permissions; a user can hold several. Super admin is separate - it
 * implies every permission and is the only tier that can open this page. */
export function UsersRolesPage() {
  const { user: me } = useAuth();
  const toast = useToast();
  const [permissions, setPermissions] = useState<Permission[]>([]);
  const [roles, setRoles] = useState<Role[]>([]);
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [total, setTotal] = useState(0);
  const [q, setQ] = useState("");
  const [adminsOnly, setAdminsOnly] = useState(false);

  const [editingRole, setEditingRole] = useState<Role | "new" | null>(null);
  const [deletingRole, setDeletingRole] = useState<Role | null>(null);
  const [editingUser, setEditingUser] = useState<AdminUser | null>(null);
  const [togglingSuper, setTogglingSuper] = useState<AdminUser | null>(null);
  const [busy, setBusy] = useState(false);

  const fail = (title: string, e: unknown) => toast({ title, description: e instanceof Error ? e.message : undefined, tone: "bad" });
  const roleName = useMemo(() => new Map(roles.map((r) => [r.id, r.name])), [roles]);

  const loadRoles = useCallback(async () => {
    const r = await apiFetch("/admin/roles");
    if (r.ok) setRoles(await r.json());
  }, []);

  const loadUsers = useCallback(async () => {
    const params = new URLSearchParams({ limit: "100" });
    if (q.trim()) params.set("q", q.trim());
    if (adminsOnly) params.set("admins_only", "true");
    const r = await apiFetch(`/admin/users?${params}`);
    if (r.ok) {
      const body = await r.json();
      setUsers(body.items);
      setTotal(body.total);
    }
  }, [q, adminsOnly]);

  useEffect(() => {
    apiFetch("/admin/permissions").then((r) => (r.ok ? r.json() : [])).then(setPermissions);
    loadRoles();
  }, [loadRoles]);

  useEffect(() => {
    const t = setTimeout(loadUsers, 250);
    return () => clearTimeout(t);
  }, [loadUsers]);

  const saveRole = async (id: string | null, body: { name: string; description: string | null; permissions: string[] }) => {
    const res = await apiFetch(id ? `/admin/roles/${id}` : "/admin/roles", { method: id ? "PUT" : "POST", body: JSON.stringify(body) });
    if (!res.ok) throw new Error(await errorText(res, "Could not save role"));
    await Promise.all([loadRoles(), loadUsers()]);
    toast({ title: id ? "Role updated" : "Role created", tone: "ok" });
  };

  const deleteRole = async () => {
    if (!deletingRole) return;
    setBusy(true);
    try {
      const res = await apiFetch(`/admin/roles/${deletingRole.id}`, { method: "DELETE" });
      if (!res.ok) throw new Error(await errorText(res, "Could not delete role"));
      setDeletingRole(null);
      await Promise.all([loadRoles(), loadUsers()]);
      toast({ title: "Role deleted", tone: "ok" });
    } catch (e) {
      fail("Couldn't delete role", e);
    } finally {
      setBusy(false);
    }
  };

  const saveUserRoles = async (u: AdminUser, roleIds: string[]) => {
    const res = await apiFetch(`/admin/users/${u.id}/roles`, { method: "PUT", body: JSON.stringify({ role_ids: roleIds }) });
    if (!res.ok) throw new Error(await errorText(res, "Could not save roles"));
    await Promise.all([loadRoles(), loadUsers()]);
    toast({ title: "Roles updated", description: u.email, tone: "ok" });
  };

  const toggleSuper = async () => {
    if (!togglingSuper) return;
    setBusy(true);
    try {
      const res = await apiFetch(`/admin/users/${togglingSuper.id}/super-admin`, {
        method: "PUT",
        body: JSON.stringify({ is_admin: !togglingSuper.is_admin }),
      });
      if (!res.ok) throw new Error(await errorText(res, "Could not change super admin"));
      setTogglingSuper(null);
      await loadUsers();
      toast({ title: togglingSuper.is_admin ? "Super admin removed" : "Made super admin", description: togglingSuper.email, tone: "ok" });
    } catch (e) {
      fail("Couldn't change super admin", e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <PageHeader
        title="Users & roles"
        subtitle="Roles decide which admin tabs and actions a person gets. Super admins get everything and are the only ones who can open this page."
      />

      <SectionCard
        title="Roles"
        description="Create a role for each kind of helper, tick what it may do, then assign it to people below."
        actions={
          <button className="btn btn-primary" onClick={() => setEditingRole("new")}>
            New role
          </button>
        }
      >
        {roles.length === 0 ? (
          <p className="note">No roles yet.</p>
        ) : (
          <div style={{ display: "grid", gap: 10 }}>
            {roles.map((r) => (
              <div key={r.id} className="card" style={{ display: "flex", gap: 12, alignItems: "flex-start", justifyContent: "space-between" }}>
                <div style={{ minWidth: 0 }}>
                  <strong>{r.name}</strong> <span className="note">· {r.user_count} {r.user_count === 1 ? "person" : "people"}</span>
                  {r.description && <div className="note">{r.description}</div>}
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 6 }}>
                    {r.permissions.length === 0 ? (
                      <span className="note">No permissions</span>
                    ) : (
                      r.permissions.map((p) => (
                        <Badge key={p} tone={permissions.find((x) => x.key === p)?.sensitive ? "warn" : "info"} dot={false}>
                          {(permissions.find((x) => x.key === p)?.label ?? p) + (p.endsWith(".manage") ? " (change)" : p.endsWith(".view") ? " (view)" : "")}
                        </Badge>
                      ))
                    )}
                  </div>
                </div>
                <div style={{ display: "flex", gap: 6 }}>
                  <button className="btn" onClick={() => setEditingRole(r)}>
                    Edit
                  </button>
                  <button className="btn danger" onClick={() => setDeletingRole(r)}>
                    Delete
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </SectionCard>

      <SectionCard
        title="People"
        description="People appear here after their first sign-in."
      >
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center", marginBottom: 12 }}>
          <input
            type="search"
            placeholder="Search email or username"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            aria-label="Search users"
            style={{ flex: "1 1 220px" }}
          />
          <label style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <input type="checkbox" checked={adminsOnly} onChange={(e) => setAdminsOnly(e.target.checked)} />
            Admins only
          </label>
        </div>
        {users === null ? (
          <p className="note">Loading…</p>
        ) : users.length === 0 ? (
          <p className="note">No matching users.</p>
        ) : (
          <div style={{ display: "grid", gap: 8 }}>
            {users.map((u) => (
              <div key={u.id} className="card" style={{ display: "flex", gap: 12, justifyContent: "space-between", alignItems: "center", flexWrap: "wrap" }}>
                <div style={{ minWidth: 0 }}>
                  <strong>{u.username}</strong> <span className="note">{u.email}</span>
                  {u.id === me?.id && <span className="note"> · you</span>}
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 4 }}>
                    {u.is_admin && (
                      <Badge tone="warn" dot={false}>
                        Super admin
                      </Badge>
                    )}
                    {u.role_ids.map((id) => (
                      <Badge key={id} tone="info" dot={false}>
                        {roleName.get(id) ?? "Unknown role"}
                      </Badge>
                    ))}
                  </div>
                </div>
                <div style={{ display: "flex", gap: 6 }}>
                  <button className="btn" onClick={() => setEditingUser(u)}>
                    Roles
                  </button>
                  <button className="btn" disabled={u.id === me?.id && u.is_admin} onClick={() => setTogglingSuper(u)}
                    title={u.id === me?.id && u.is_admin ? "Ask another super admin to remove your access" : undefined}>
                    {u.is_admin ? "Remove super admin" : "Make super admin"}
                  </button>
                </div>
              </div>
            ))}
            {total > users.length && <p className="note">Showing {users.length} of {total} - search to narrow.</p>}
          </div>
        )}
      </SectionCard>

      {editingRole && (
        <RoleModal
          role={editingRole === "new" ? null : editingRole}
          permissions={permissions}
          onClose={() => setEditingRole(null)}
          onSave={async (body) => {
            await saveRole(editingRole === "new" ? null : editingRole.id, body);
            setEditingRole(null);
          }}
        />
      )}

      {editingUser && (
        <UserRolesModal
          user={editingUser}
          roles={roles}
          onClose={() => setEditingUser(null)}
          onSave={async (ids) => {
            await saveUserRoles(editingUser, ids);
            setEditingUser(null);
          }}
        />
      )}

      <ConfirmDialog
        open={!!deletingRole}
        title={`Delete role "${deletingRole?.name ?? ""}"?`}
        description={
          deletingRole && deletingRole.user_count > 0
            ? `${deletingRole.user_count} ${deletingRole.user_count === 1 ? "person loses" : "people lose"} the access this role gave them, immediately.`
            : "No one has this role."
        }
        confirmLabel="Delete role"
        danger
        busy={busy}
        onConfirm={deleteRole}
        onCancel={() => setDeletingRole(null)}
      />

      <ConfirmDialog
        open={!!togglingSuper}
        title={togglingSuper?.is_admin ? "Remove super admin?" : "Make super admin?"}
        description={
          togglingSuper?.is_admin
            ? `${togglingSuper.email} will lose access to everything they can only reach as a super admin, including this page.`
            : `${togglingSuper?.email ?? ""} will get every permission and will be able to manage users, roles and other super admins.`
        }
        confirmLabel={togglingSuper?.is_admin ? "Remove super admin" : "Make super admin"}
        danger
        busy={busy}
        onConfirm={toggleSuper}
        onCancel={() => setTogglingSuper(null)}
      />
    </div>
  );
}

function RoleModal({
  role,
  permissions,
  onClose,
  onSave,
}: {
  role: Role | null;
  permissions: Permission[];
  onClose: () => void;
  onSave: (body: { name: string; description: string | null; permissions: string[] }) => Promise<void>;
}) {
  const [name, setName] = useState(role?.name ?? "");
  const [description, setDescription] = useState(role?.description ?? "");
  const [picked, setPicked] = useState<Set<string>>(new Set(role?.permissions ?? []));
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
      await onSave({ name: name.trim(), description: description.trim() || null, permissions: [...picked] });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save role");
      setSaving(false);
    }
  };

  return (
    <Modal
      open
      onClose={onClose}
      title={role ? "Edit role" : "New role"}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" form="role-form" className="btn btn-primary" disabled={saving || !name.trim()}>
            {saving ? "Saving…" : "Save"}
          </button>
        </>
      }
    >
      <form id="role-form" onSubmit={submit}>
        {error && <div className="form-error">{error}</div>}
        <Field label="Name">
          <input value={name} onChange={(e) => setName(e.target.value)} maxLength={64} required placeholder="Newsletter editor" />
        </Field>
        <Field label="Description" hint="Optional - a note for future you.">
          <input value={description} onChange={(e) => setDescription(e.target.value)} maxLength={255} />
        </Field>
        {(["read", "write"] as const).map((access) => (
          <div key={access} style={{ marginBottom: 12 }}>
            <span style={{ display: "block", fontSize: 12, fontWeight: 700, color: "var(--ink-2)", letterSpacing: "0.02em" }}>
              {access === "read" ? "Can view" : "Can change"}
            </span>
            <span className="note" style={{ display: "block", marginTop: 2 }}>
              {access === "read" ? "See the data; change nothing." : "Create, edit and delete. Also lets them view the same area."}
            </span>
            <div className="checks" style={{ marginTop: 6 }}>
              {permissions
                .filter((p) => p.access === access)
                .map((p) => {
                  const implied = access === "read" && [...picked].some((k) => impliedView(k) === p.key);
                  const on = picked.has(p.key) || implied;
                  return (
                    <label key={p.key} className={`check ${on ? "on" : ""}`} style={{ marginBottom: 0, opacity: implied ? 0.7 : 1 }}>
                      <input type="checkbox" checked={on} disabled={implied} onChange={() => toggle(p.key)} />
                      <span>
                        <strong>{p.label}</strong> {p.sensitive && <Badge tone="warn" dot={false}>Powerful</Badge>}
                        <span className="note" style={{ display: "block" }}>
                          {p.description}
                          {implied && " (included with change access)"}
                        </span>
                      </span>
                    </label>
                  );
                })}
            </div>
          </div>
        ))}
      </form>
    </Modal>
  );
}

function UserRolesModal({
  user,
  roles,
  onClose,
  onSave,
}: {
  user: AdminUser;
  roles: Role[];
  onClose: () => void;
  onSave: (roleIds: string[]) => Promise<void>;
}) {
  const [picked, setPicked] = useState<Set<string>>(new Set(user.role_ids));
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const toggle = (id: string) =>
    setPicked((cur) => {
      const next = new Set(cur);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      await onSave([...picked]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save roles");
      setSaving(false);
    }
  };

  return (
    <Modal
      open
      onClose={onClose}
      title="Roles"
      subtitle={user.email}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="button" className="btn btn-primary" disabled={saving} onClick={save}>
            {saving ? "Saving…" : "Save"}
          </button>
        </>
      }
    >
      {error && <div className="form-error">{error}</div>}
      {user.is_admin && <p className="note">Super admins already hold every permission; roles here add nothing until that's removed.</p>}
      {roles.length === 0 ? (
        <p className="note">Create a role first.</p>
      ) : (
        <div className="checks">
          {roles.map((r) => (
            <label key={r.id} className={`check ${picked.has(r.id) ? "on" : ""}`} style={{ marginBottom: 0 }}>
              <input type="checkbox" checked={picked.has(r.id)} onChange={() => toggle(r.id)} />
              <span>
                <strong>{r.name}</strong>
                {r.description && <span className="note" style={{ display: "block" }}>{r.description}</span>}
              </span>
            </label>
          ))}
        </div>
      )}
    </Modal>
  );
}
