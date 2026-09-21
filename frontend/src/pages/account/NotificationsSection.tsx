import { useEffect, useState } from "react";
import { apiFetch } from "../../api";
import { IconBell, IconCheck } from "../../components/icons";
import { Badge } from "../../components/ui/Badge";
import { SectionCard } from "../../components/ui/SectionCard";
import { relativeTime } from "../../lib/format";
import { markAllNotificationsSeen } from "../../lib/notifications";

type Notification = { id: string; type: string; message: string; created_at: string; read_at: string | null };

const TYPE_LABEL: Record<string, string> = { guardian_matched: "Guardian matched", invite_accepted: "Invite accepted" };

export function NotificationsSection() {
  const [items, setItems] = useState<Notification[] | null>(null);
  const [busy, setBusy] = useState(false);

  const load = () =>
    apiFetch("/notifications")
      .then((r) => (r.ok ? r.json() : []))
      .then(setItems);

  // Load first, then mark everything read: this visit still shows what was
  // new, while the banner bell clears until something new arrives.
  useEffect(() => {
    load().then(() => markAllNotificationsSeen());
  }, []);

  const markRead = async (id: string) => {
    await apiFetch(`/notifications/${id}/read`, { method: "POST" });
    setItems((cur) => cur?.map((n) => (n.id === id ? { ...n, read_at: new Date().toISOString() } : n)) ?? null);
  };

  const markAll = async () => {
    setBusy(true);
    try {
      await Promise.all((items ?? []).filter((n) => !n.read_at).map((n) => apiFetch(`/notifications/${n.id}/read`, { method: "POST" })));
      await load();
    } finally {
      setBusy(false);
    }
  };

  const unread = items?.filter((n) => !n.read_at) ?? [];
  const read = items?.filter((n) => n.read_at) ?? [];

  return (
    <SectionCard
      title="Notifications"
      description="When another guardian is matched to one of your children, or accepts an invite."
      icon={<IconBell />}
      actions={
        unread.length > 0 && (
          <button className="btn sm" onClick={markAll} disabled={busy}>
            <IconCheck /> Mark all read
          </button>
        )
      }
    >
      {items === null ? (
        <p className="note">Loading…</p>
      ) : items.length === 0 ? (
        <div className="empty">Nothing yet. You'll hear here when a guardian is linked to one of your children.</div>
      ) : (
        <>
          {unread.map((n) => (
            <div className="info-row" key={n.id}>
              <span className="ico">
                <IconBell />
              </span>
              <div className="txt">
                <b>{n.message}</b>
                <small>
                  {TYPE_LABEL[n.type] ?? n.type} · {relativeTime(n.created_at)}
                </small>
              </div>
              <button className="btn sm" onClick={() => markRead(n.id)}>
                Done
              </button>
            </div>
          ))}
          {read.length > 0 && (
            <details style={{ marginTop: 8 }}>
              <summary style={{ cursor: "pointer", color: "var(--ink-3)", fontSize: 13 }}>
                {read.length} earlier {read.length === 1 ? "notification" : "notifications"}
              </summary>
              {read.map((n) => (
                <div className="info-row" key={n.id} style={{ opacity: 0.7 }}>
                  <span className="ico">
                    <IconCheck />
                  </span>
                  <div className="txt">
                    <b>{n.message}</b>
                    <small>
                      {TYPE_LABEL[n.type] ?? n.type} · {relativeTime(n.created_at)}
                    </small>
                  </div>
                  <Badge tone="muted" dot={false}>
                    read
                  </Badge>
                </div>
              ))}
            </details>
          )}
        </>
      )}
    </SectionCard>
  );
}
