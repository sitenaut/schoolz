import { useEffect, useRef } from "react";

/** A tab left open keeps running the build it loaded, for days: the tabs a
 * visitor taps through are all preloaded, so nothing ever asks the server
 * for a chunk the new build lacks and lazyPage's reload never fires. A
 * parent's Today tab showed a closure as three banners a week after the fix
 * went live. So when someone comes back to the tab after a while and a newer
 * build is live, the page reloads: at once if nothing on it was typed in and
 * no dialog is open, otherwise when they next open another page. */

// As Today's refetch on resume: a glance back at the tab costs nothing.
export const AWAY_MS = 30 * 60_000;

/** The entry script an index.html loads ("/assets/index-<hash>.js"). */
export function entryScript(html: string): string | null {
  return /<script\b[^>]*\bsrc="(\/assets\/index-[^"]+\.js)"/.exec(html)?.[1] ?? null;
}

function runningEntry(): string | null {
  return document.querySelector('script[type="module"][src^="/assets/index-"]')?.getAttribute("src") ?? null;
}

/** Whether the site now serves another build than the one running. False
 * when that can't be told: the dev server (no hashed entry), offline, or a
 * page that isn't the app (a captive portal's). */
export async function newBuildLive(running: string | null = runningEntry()): Promise<boolean> {
  if (!running) return false;
  try {
    // index.html is served no-cache; no-store keeps the browser from
    // answering with the copy this tab loaded.
    const res = await fetch("/", { cache: "no-store" });
    if (!res.ok) return false;
    const live = entryScript(await res.text());
    return live !== null && live !== running;
  } catch {
    return false;
  }
}

type Deps = {
  check: () => Promise<boolean>;
  reload: () => void;
  /** Something on the page would be lost: typed input, an open dialog. */
  busy: () => boolean;
  now: () => number;
};

/** The decisions, apart from the DOM: feed it the tab going hidden and
 * visible and each navigation. */
export function buildWatcher({ check, reload, busy, now }: Deps) {
  let hiddenAt: number | null = null;
  let stale = false;
  return {
    hidden() {
      hiddenAt = now();
    },
    async visible() {
      const away = hiddenAt === null ? 0 : now() - hiddenAt;
      hiddenAt = null;
      if (away < AWAY_MS || stale || !(await check())) return;
      stale = true;
      if (!busy()) reload();
    },
    navigated() {
      if (stale) reload();
    },
  };
}

/** Wires buildWatcher to the page; used once, in AppShell. */
export function useFreshBuild(pathname: string, skip: boolean): void {
  const touched = useRef(false);
  const watcher = useRef<ReturnType<typeof buildWatcher> | null>(null);

  useEffect(() => {
    if (skip) return;
    const w = buildWatcher({
      check: () => newBuildLive(),
      reload: () => window.location.reload(),
      busy: () => touched.current || document.querySelector('[role="dialog"]') !== null,
      now: Date.now,
    });
    watcher.current = w;
    const onInput = () => {
      touched.current = true;
    };
    const onVisibility = () => {
      if (document.visibilityState === "hidden") w.hidden();
      else void w.visible();
    };
    document.addEventListener("input", onInput, true);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      watcher.current = null;
      document.removeEventListener("input", onInput, true);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [skip]);

  // A new page: whatever was typed on the last one is gone either way, and
  // a newer build found while that page was busy loads now.
  useEffect(() => {
    touched.current = false;
    watcher.current?.navigated();
  }, [pathname]);
}
