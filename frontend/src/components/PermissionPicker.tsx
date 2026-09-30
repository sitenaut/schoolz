import { Badge } from "./ui/Badge";

export type Permission = { key: string; label: string; description: string; sensitive: boolean; access: "read" | "write" };

/** Mirrors the backend: a `.manage` permission implies its `.view`. */
export const impliedView = (key: string) => (key.endsWith(".manage") ? key.replace(/\.manage$/, ".view") : null);

/** The "Can view" / "Can change" checkbox groups, shared by roles and API keys. */
export function PermissionPicker({
  permissions,
  picked,
  onToggle,
}: {
  permissions: Permission[];
  picked: Set<string>;
  onToggle: (key: string) => void;
}) {
  return (
    <>
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
                    <input type="checkbox" checked={on} disabled={implied} onChange={() => onToggle(p.key)} />
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
    </>
  );
}

export function permissionLabel(permissions: Permission[], key: string): string {
  const label = permissions.find((x) => x.key === key)?.label ?? key;
  return label + (key.endsWith(".manage") ? " (change)" : key.endsWith(".view") ? " (view)" : "");
}
