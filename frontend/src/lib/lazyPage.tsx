import { Component, Suspense, lazy, useEffect, useState, type ComponentType, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

/** Pages load as their own chunks, so a visitor opening Today never
 * downloads the admin tools, Localz or the account pages: they were most of
 * the one bundle every visitor used to load and parse before anything drew.
 * `lazyPage(() => import("./pages/X").then((m) => m.X))` gives a component
 * that renders like the page, with `preload()` to fetch it ahead of a tap. */

const RELOADED_AT_KEY = "schoolz_chunk_reload_at";
// A second failure this soon after a reload is the network or the site, not
// an old build: show the error instead of reloading in a loop.
const RELOAD_GAP_MS = 30_000;

/** Whether a failed chunk load should reload the page: true at most once per
 * RELOAD_GAP_MS. A tab left open across a deploy runs the old build, whose
 * chunks the new image no longer has, so its next page import 404s; a reload
 * picks up the new build. */
export function claimReload(storage: Pick<Storage, "getItem" | "setItem"> | null, now: number): boolean {
  if (!storage) return false;
  try {
    const last = Number(storage.getItem(RELOADED_AT_KEY) || 0);
    if (now - last < RELOAD_GAP_MS) return false;
    storage.setItem(RELOADED_AT_KEY, String(now));
    return true;
  } catch {
    return false; // storage blocked: no way to tell a first failure from a loop
  }
}

function sessionStore(): Storage | null {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

// Nothing for the first moment (a cached chunk arrives before anyone would
// notice a blank), then the same "Loading…" the pages show for their data.
function PageLoading() {
  const [show, setShow] = useState(false);
  useEffect(() => {
    const timer = window.setTimeout(() => setShow(true), 300);
    return () => window.clearTimeout(timer);
  }, []);
  return show ? <p>Loading…</p> : null;
}

function PageFailed() {
  const { t } = useTranslation();
  return (
    <div style={{ padding: "2rem", textAlign: "center" }}>
      <p>{t("This page didn't load.")}</p>
      <button className="btn" onClick={() => window.location.reload()}>
        {t("Reload")}
      </button>
    </div>
  );
}

// Keeps a failed page from blanking the whole app (the shell and its tabs
// stay usable). React still logs the error, which is how RUM sees it.
class PageBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    return this.state.failed ? <PageFailed /> : this.props.children;
  }
}

export type LazyPage<P> = ComponentType<P> & { preload: () => void };

export function lazyPage<P extends object>(load: () => Promise<ComponentType<P>>): LazyPage<P> {
  // Typed as the page itself: lazy()'s own props type doesn't follow a generic P.
  const Lazy = lazy(() =>
    load().then(
      (page) => ({ default: page }),
      (err: unknown) => {
        if (claimReload(sessionStore(), Date.now())) {
          window.location.reload();
          return new Promise<never>(() => {}); // the reload replaces this page
        }
        throw err;
      },
    ),
  ) as unknown as ComponentType<P>;
  const Page = ((props: P) => (
    <PageBoundary>
      <Suspense fallback={<PageLoading />}>
        <Lazy {...props} />
      </Suspense>
    </PageBoundary>
  )) as LazyPage<P>;
  Page.preload = () => {
    load().catch(() => {}); // a real visit retries, and handles the failure
  };
  return Page;
}

/** Fetches the pages a visitor is likely to tap next once the page has loaded
 * and the browser is idle, so the tabs open without a wait. Skipped for
 * Save-Data and for prerender renders, which never tap anything. */
export function preloadWhenIdle(pages: { preload: () => void }[], skip: boolean): void {
  if (skip || typeof window === "undefined") return;
  const connection = (navigator as Navigator & { connection?: { saveData?: boolean } }).connection;
  if (connection?.saveData) return;
  const run = () => pages.forEach((page) => page.preload());
  const afterLoad = () => {
    if (typeof window.requestIdleCallback === "function") window.requestIdleCallback(run, { timeout: 5000 });
    else window.setTimeout(run, 2000); // Safari has no requestIdleCallback
  };
  if (document.readyState === "complete") afterLoad();
  else window.addEventListener("load", afterLoad, { once: true });
}
