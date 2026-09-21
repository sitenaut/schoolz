import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { apiFetch } from "../api";

const NOTIFICATIONS_SEEN = "schoolz:notifications-seen";
const INBOX_SEEN = "schoolz:inbox-seen";

/** An unread count from `endpoint`, refreshed on every navigation and when
 * the tab regains focus; 0 while disabled or after `seenEvent` fires. */
function useUnreadCount(endpoint: string, enabled: boolean, seenEvent: string): number {
  const [count, setCount] = useState(0);
  const { pathname } = useLocation();

  useEffect(() => {
    if (!enabled) {
      setCount(0);
      return;
    }
    let cancelled = false;
    const refresh = () =>
      apiFetch(endpoint)
        .then((r) => (r.ok ? r.json() : { count: 0 }))
        .then((d: { count: number }) => !cancelled && setCount(d.count))
        .catch(() => undefined);
    const cleared = () => setCount(0);
    refresh();
    window.addEventListener("focus", refresh);
    window.addEventListener(seenEvent, cleared);
    return () => {
      cancelled = true;
      window.removeEventListener("focus", refresh);
      window.removeEventListener(seenEvent, cleared);
    };
  }, [endpoint, enabled, seenEvent, pathname]);

  return count;
}

async function markSeen(endpoint: string, seenEvent: string): Promise<void> {
  const r = await apiFetch(endpoint, { method: "POST" });
  if (r.ok) window.dispatchEvent(new Event(seenEvent));
}

export const useUnreadNotifications = (signedIn: boolean) => useUnreadCount("/notifications/unread-count", signedIn, NOTIFICATIONS_SEEN);
/** Opening the notifications page counts as seeing them all. */
export const markAllNotificationsSeen = () => markSeen("/notifications/read-all", NOTIFICATIONS_SEEN);

export const useUnreadInbox = (isAdmin: boolean) => useUnreadCount("/contact-messages/unread-count", isAdmin, INBOX_SEEN);
/** Opening the admin inbox counts as seeing every message - shared across admins. */
export const markInboxSeen = () => markSeen("/contact-messages/read-all", INBOX_SEEN);
