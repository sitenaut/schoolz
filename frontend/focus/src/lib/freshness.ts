import type { SyncStatus } from "../types";

/** Where a parent gets the extension that brings this data in. */
export const BACKPACK_CAPTURE_STORE_URL =
  "https://chromewebstore.google.com/detail/backpack-capture/imjhghdlhjgoeghhgafdpclapkjcnfbe";

/** Past this, "nothing due" can no longer be said flatly. The scheduled walk
 * runs every 4 hours outside 10pm-6am, so a day means several missed runs. */
const STALE_AFTER_MS = 24 * 60 * 60 * 1000;

export type Freshness =
  | { kind: "never" }
  | { kind: "fresh" | "stale"; ago: string; needsLogin: boolean };

export function timeAgo(iso: string, now: number): string {
  const minutes = Math.round((now - Date.parse(iso)) / 60000);
  if (minutes < 2) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  return days === 1 ? "yesterday" : `${days} days ago`;
}

/** How current the Focus screen is. Classroom is what decides it when it's
 * there: everything due or missing comes from Classroom; Genesis only adds
 * grades. null when the status couldn't be loaded - say nothing rather than
 * guess. */
export function freshness(status: SyncStatus | null, now: number = Date.now()): Freshness | null {
  if (!status) return null;
  const seen = status.classroom_seen_at ?? status.genesis_seen_at;
  if (!seen) return { kind: "never" };
  return {
    kind: now - Date.parse(seen) > STALE_AFTER_MS ? "stale" : "fresh",
    ago: timeAgo(seen, now),
    needsLogin: status.needs_login,
  };
}
