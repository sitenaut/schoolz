import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { apiFetch } from "../api";
import { useAuth } from "../context/AuthContext";
import { Badge } from "../components/ui/Badge";
import { ConfirmDialog } from "../components/ui/ConfirmDialog";
import { DataTable, type Column } from "../components/ui/DataTable";
import { IconChevronLeft, IconChevronRight } from "../components/icons";
import { Field } from "../components/ui/Field";
import { Modal } from "../components/ui/Modal";
import { PageHeader } from "../components/ui/PageHeader";
import { SectionCard } from "../components/ui/SectionCard";
import { useToast } from "../components/ui/Toast";
import { PermissionPicker, permissionLabel, type Permission } from "../components/PermissionPicker";

type Role = { id: string; name: string; description: string | null; permissions: string[]; user_count: number };
type Sort = { id: string; dir: "asc" | "desc" };
const PAGE_SIZES = [25, 50, 100];
const ACCESS_FILTERS = [
  { value: "all", label: "Everyone" },
  { value: "staff", label: "Any admin access" },
  { value: "super", label: "Super admins" },
  { value: "role", label: "Has a role" },
  { value: "none", label: "No admin access" },
];

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
  const [usersLoading, setUsersLoading] = useState(true);
  const [q, setQ] = useState("");
  const [access, setAccess] = useState("all");
  const [roleFilter, setRoleFilter] = useState("");
  const [sort, setSort] = useState<Sort>({ id: "access", dir: "asc" });
  const [pageSize, setPageSize] = useState(PAGE_SIZES[0]);
  const [offset, setOffset] = useState(0);
  const latestLoad = useRef(0);

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
    // A slower, older response must never overwrite a newer one.
    const mine = ++latestLoad.current;
    setUsersLoading(true);
    const params = new URLSearchParams({ limit: String(pageSize), offset: String(offset), sort: sort.id, dir: sort.dir, access });
    if (q.trim()) params.set("q", q.trim());
    if (roleFilter) params.set("role_id", roleFilter);
    try {
      const r = await apiFetch(`/admin/users?${params}`);
      if (mine !== latestLoad.current) return;
      if (r.ok) {
        const body = await r.json();
        // Filters shrank the list out from under this page: go to the last one.
        if (body.items.length === 0 && body.total > 0 && offset > 0) {
          setOffset(Math.floor((body.total - 1) / pageSize) * pageSize);
          return;
        }
        setUsers(body.items);
        setTotal(body.total);
      }
    } finally {
      if (mine === latestLoad.current) setUsersLoading(false);
    }
  }, [q, access, roleFilter, sort, pageSize, offset]);

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

  const userColumns: Column<AdminUser>[] = [
    {
      id: "username",
      header: "Username",
      sortValue: (u) => u.username,
      cell: (u) => (
        <>
          <strong>{u.username}</strong>
          {u.id === me?.id && <span className="note"> · you</span>}
        </>
      ),
    },
    { id: "email", header: "Email", sortValue: (u) => u.email, cell: (u) => u.email },
    {
      id: "access",
      header: "Access",
      sortValue: (u) => u.role_ids.length,
      cell: (u) =>
        !u.is_admin && u.role_ids.length === 0 ? (
          <span className="note">None</span>
        ) : (
          <span style={{ display: "inline-flex", flexWrap: "wrap", gap: 6 }}>
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
          </span>
        ),
    },
    {
      id: "created_at",
      header: "Joined",
      sortValue: (u) => u.created_at,
      cell: (u) => (u.created_at ? new Date(u.created_at).toLocaleDateString() : "—"),
    },
  ];

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
                          {permissionLabel(permissions, p)}
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

      <SectionCard title="People" description="People appear here after their first sign-in.">
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center", marginBottom: 12 }}>
          <input
            type="search"
            placeholder="Search email or username"
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setOffset(0);
            }}
            aria-label="Search users"
            style={{ flex: "1 1 220px", width: "auto", margin: 0 }}
          />
          <select
            value={access}
            onChange={(e) => {
              setAccess(e.target.value);
              setOffset(0);
            }}
            aria-label="Filter by access"
            style={{ width: "auto", margin: 0 }}
          >
            {ACCESS_FILTERS.map((f) => (
              <option key={f.value} value={f.value}>
                {f.label}
              </option>
            ))}
          </select>
          <select
            value={roleFilter}
            onChange={(e) => {
              setRoleFilter(e.target.value);
              setOffset(0);
            }}
            aria-label="Filter by role"
            style={{ width: "auto", margin: 0 }}
          >
            <option value="">Any role</option>
            {roles.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name}
              </option>
            ))}
          </select>
        </div>

        <DataTable
          columns={userColumns}
          rows={users ?? []}
          getRowId={(u) => u.id}
          loading={usersLoading && users === null}
          sort={sort}
          onSortChange={(next) => {
            setSort(next);
            setOffset(0);
          }}
          empty={q || access !== "all" || roleFilter ? "No users match these filters." : "No users yet."}
          rowActions={(u) => (
            <>
              <button className="btn sm" onClick={() => setEditingUser(u)}>
                Roles
              </button>
              <button
                className="btn sm"
                disabled={u.id === me?.id && u.is_admin}
                onClick={() => setTogglingSuper(u)}
                title={u.id === me?.id && u.is_admin ? "Ask another super admin to remove your access" : undefined}
              >
                {u.is_admin ? "Remove super admin" : "Make super admin"}
              </button>
            </>
          )}
        />

        <div style={{ display: "flex", gap: 12, alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", marginTop: 12 }}>
          <span className="note" aria-live="polite" style={{ opacity: usersLoading ? 0.6 : 1 }}>
            {total === 0 ? "0 users" : `${offset + 1}–${Math.min(offset + pageSize, total)} of ${total}`}
          </span>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <label className="note" style={{ display: "flex", gap: 6, alignItems: "center", margin: 0 }}>
              Per page
              <select
                value={pageSize}
                onChange={(e) => {
                  setPageSize(Number(e.target.value));
                  setOffset(0);
                }}
                style={{ width: "auto", margin: 0 }}
              >
                {PAGE_SIZES.map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            </label>
            <button className="btn" disabled={offset === 0 || usersLoading} onClick={() => setOffset(Math.max(0, offset - pageSize))}>
              <IconChevronLeft /> Previous
            </button>
            <button className="btn" disabled={offset + pageSize >= total || usersLoading} onClick={() => setOffset(offset + pageSize)}>
              Next <IconChevronRight />
            </button>
          </div>
        </div>
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
        <PermissionPicker permissions={permissions} picked={picked} onToggle={toggle} />
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
