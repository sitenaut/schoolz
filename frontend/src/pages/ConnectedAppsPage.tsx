import { useEffect, useState } from "react";
import { apiFetch } from "../api";
import { Badge } from "../components/ui/Badge";
import { PageHeader } from "../components/ui/PageHeader";
import { SectionCard } from "../components/ui/SectionCard";
import { useToast } from "../components/ui/Toast";

type Connection = {
  id: string;
  name: string;
  key_prefix: string;
  created_at: string;
  last_used_at: string | null;
};

/** Apps connected to your own family: each reads your children, their
 * schools, school days, schoolwork and grades (GET /family/feed) and nothing
 * else. An app connects from its own side; the link it shows lands on
 * ApproveConnectedAppPage. Experimental, so super admins only. */
export function ConnectedAppsPage() {
  const toast = useToast();
  const [connections, setConnections] = useState<Connection[] | null>(null);

  useEffect(() => {
    apiFetch("/admin/family-connections")
      .then((r) => (r.ok ? r.json() : []))
      .then(setConnections)
      .catch(() => setConnections([]));
  }, []);

  const remove = async (c: Connection) => {
    const r = await apiFetch(`/admin/family-connections/${encodeURIComponent(c.id)}`, { method: "DELETE" });
    if (!r.ok) {
      toast({ title: "Couldn't disconnect it", tone: "bad" });
      return;
    }
    setConnections((cur) => (cur ?? []).filter((x) => x.id !== c.id));
    toast({ title: `${c.name} disconnected`, tone: "ok" });
  };

  const day = (iso: string) => new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });

  return (
    <div>
      <PageHeader
        title="Connected apps"
        subtitle={
          <>
            <Badge tone="warn" dot={false}>
              Experimental
            </Badge>{" "}
            Super admins only for now.
          </>
        }
      />
      <SectionCard
        title="Your family's feed"
        description="Apps here read your own children, their schools, school days, schoolwork and grades. Nothing else, and they can't change anything. Start the connection from the app; it shows a link to approve it here."
      >
        {connections === null ? (
          <p className="note">Loading…</p>
        ) : connections.length === 0 ? (
          <p className="note">No apps are connected.</p>
        ) : (
          connections.map((c) => (
            <div className="info-row" key={c.id}>
              <div className="txt">
                <b>{c.name}</b>
                <small>
                  Connected {day(c.created_at)} · {c.last_used_at ? `last read ${day(c.last_used_at)}` : "not used yet"}
                </small>
              </div>
              <button className="btn sm" onClick={() => remove(c)}>
                Disconnect
              </button>
            </div>
          ))
        )}
      </SectionCard>
    </div>
  );
}
