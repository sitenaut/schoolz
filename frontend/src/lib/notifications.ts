import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { apiFetch } from "../api";

const SEEN_EVENT = "schoolz:notifications-seen";

/** Unread notification count for the signed-in user, refreshed on every
 * navigation and when the tab regains focus; 0 when signed out. */
export function useUnreadNotifications(signedIn: boolean): number {
  const [count, setCount] = useState(0);
  const { pathname } = useLocation();

  useEffect(() => {
    if (!signedIn) {
      setCount(0);
      return;
    }
    let cancelled = false;
    const refresh = () =>
      apiFetch("/notifications/unread-count")
        .then((r) => (r.ok ? r.json() : { count: 0 }))
        .then((d: { count: number }) => !cancelled && setCount(d.count))
        .catch(() => undefined);
    const cleared = () => setCount(0);
    refresh();
    window.addEventListener("focus", refresh);
    window.addEventListener(SEEN_EVENT, cleared);
    return () => {
      cancelled = true;
      window.removeEventListener("focus", refresh);
      window.removeEventListener(SEEN_EVENT, cleared);
    };
  }, [signedIn, pathname]);

  return count;
}

/** Opening the notifications page counts as seeing them all. */
export async function markAllNotificationsSeen(): Promise<void> {
  const r = await apiFetch("/notifications/read-all", { method: "POST" });
  if (r.ok) window.dispatchEvent(new Event(SEEN_EVENT));
}
