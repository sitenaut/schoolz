import { useEffect } from "react";

type PrerenderSignals = { search: string; userAgent: string; brands: string[]; webdriver: boolean };

/** True when this page load is backend/services/prerender.py rendering a
 * page for a crawler, not a person. Such a load must never count as a
 * visit: every render is a fresh browser, so page_visits and Faro each
 * counted it as a new "direct" visitor - ~3,000 a day, an order of
 * magnitude over the real traffic. prerender.py adds `?prerender=1`; the
 * headless/webdriver checks catch a render without it (the droplet's
 * stealth Chromium hides webdriver but still reports HeadlessChrome). */
export function isPrerenderLoad({ search, userAgent, brands, webdriver }: PrerenderSignals): boolean {
  return (
    new URLSearchParams(search).get("prerender") === "1" ||
    webdriver ||
    /HeadlessChrome/.test(userAgent) ||
    brands.includes("HeadlessChrome")
  );
}

function currentSignals(): PrerenderSignals {
  const nav = navigator as Navigator & { userAgentData?: { brands?: { brand: string }[] } };
  return {
    search: window.location.search,
    userAgent: nav.userAgent,
    brands: (nav.userAgentData?.brands ?? []).map((b) => b.brand),
    webdriver: !!nav.webdriver,
  };
}

/** Decided once at startup, while the landing URL still carries ?prerender=1. */
export const IS_PRERENDER = typeof window !== "undefined" && isPrerenderLoad(currentSignals());

/** Flags <body> once a page's own initial data fetch has resolved.
 * backend/services/prerender.py waits on this exact attribute before
 * capturing a page's HTML for a crawler - without it, a bot would be
 * handed a "Loading…" snapshot instead of real content. Static pages with
 * nothing to fetch should call this with `true` on mount. */
export function usePrerenderReady(ready: boolean): void {
  useEffect(() => {
    if (!ready) return;
    document.body.setAttribute("data-prerender-ready", "true");
    return () => {
      document.body.removeAttribute("data-prerender-ready");
    };
  }, [ready]);
}
