import { useEffect, useState } from "react";
import { apiFetch } from "../api";
import { IconInbox, IconMail, IconTrash } from "../components/icons";
import { Badge } from "../components/ui/Badge";
import { ConfirmDialog } from "../components/ui/ConfirmDialog";
import { SectionCard } from "../components/ui/SectionCard";
import { relativeTime } from "../lib/format";
import { markInboxSeen } from "../lib/notifications";

type Message = { id: string; name: string | null; email: string | null; message: string; user_id: string | null; read_at: string | null; created_at: string };

/** The admins' shared inbox for the public /contact form. Opening it marks
 * everything read for every admin (clearing the banner icon); this visit
 * still highlights what was new. */
export function InboxPage() {
  const [items, setItems] = useState<Message[] | null>(null);
  const [newIds, setNewIds] = useState<Set<string>>(new Set());
  const [deleting, setDeleting] = useState<Message | null>(null);

  useEffect(() => {
    apiFetch("/contact-messages")
      .then((r) => (r.ok ? r.json() : []))
      .then((rows: Message[]) => {
        setItems(rows);
        setNewIds(new Set(rows.filter((m) => !m.read_at).map((m) => m.id)));
        return markInboxSeen();
      });
  }, []);

  const markUnread = async (m: Message) => {
    const r = await apiFetch(`/contact-messages/${m.id}/unread`, { method: "POST" });
    if (r.ok) setNewIds((cur) => new Set(cur).add(m.id));
  };

  const remove = async () => {
    if (!deleting) return;
    const r = await apiFetch(`/contact-messages/${deleting.id}`, { method: "DELETE" });
    if (r.ok) setItems((cur) => cur?.filter((m) => m.id !== deleting.id) ?? null);
    setDeleting(null);
  };

  return (
    <SectionCard title="Inbox" description="Messages from the public contact form. Shared by every admin." icon={<IconInbox />}>
      {items === null ? (
        <p className="note">Loading…</p>
      ) : items.length === 0 ? (
        <div className="empty">No messages yet.</div>
      ) : (
        <ul className="inbox">
          {items.map((m) => (
            <li key={m.id} className={`inbox-msg${newIds.has(m.id) ? " is-new" : ""}`}>
              <div className="inbox-head">
                <b>{m.name || "Anonymous"}</b>
                {m.email && (
                  <a href={`mailto:${m.email}?subject=${encodeURIComponent("Re: your message to schoolz")}`}>{m.email}</a>
                )}
                {m.user_id && <Badge>signed in</Badge>}
                {newIds.has(m.id) && <Badge tone="info">new</Badge>}
                <span className="note inbox-when">{relativeTime(m.created_at)}</span>
              </div>
              <p className="inbox-body">{m.message}</p>
              <div className="inbox-actions">
                {m.email && (
                  <a className="btn sm" href={`mailto:${m.email}?subject=${encodeURIComponent("Re: your message to schoolz")}`}>
                    <IconMail /> Reply
                  </a>
                )}
                {!newIds.has(m.id) && (
                  <button className="btn sm" onClick={() => markUnread(m)}>
                    Mark unread
                  </button>
                )}
                <button className="btn icon danger" title="Delete" aria-label="Delete message" onClick={() => setDeleting(m)}>
                  <IconTrash />
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
      <ConfirmDialog
        open={!!deleting}
        title="Delete this message?"
        description="It's removed for every admin. This can't be undone."
        confirmLabel="Delete"
        danger
        onConfirm={remove}
        onCancel={() => setDeleting(null)}
      />
    </SectionCard>
  );
}
