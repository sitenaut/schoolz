import { useEffect } from "react";

type PrerenderSignals = {
  search: string;
  userAgent: string;
  brands: string[];
  webdriver: boolean;
  /** navigator.userAgentData.platform, "" where the browser has none. */
  platform: string;
  now: number;
};

/** True when this page load is backend/services/prerender.py rendering a
 * page for a crawler, not a person. Such a load must never count as a
 * visit: every render is a fresh browser, so page_visits and Faro each
 * counted it as a new "direct" visitor - ~3,000 a day, an order of
 * magnitude over the real traffic. prerender.py adds `?prerender=1`; the
 * headless/webdriver checks catch a render without it (the droplet's
 * stealth Chromium hides webdriver but still reports HeadlessChrome).
 *
 * Crawlers that run the page's JavaScript are caught the same way: Meta's
 * AI crawler and ExaSearchBot render in a real-looking Chrome with no
 * webdriver flag, and on 2026-10-21 were 43 of 44 /calendar
 * visits. A crawler names itself in its UA, usually with a `+https://`
 * contact link no real browser carries. */
const CRAWLER_UA = /\+https?:\/\/|bot\/|crawler|spider|meta-externalagent|meta-webindexer|facebookexternalhit/i;

/** A desktop Linux Chrome six or more major versions out of date. On
 * 2026-11-03/04 one crawler opened page after page this way: Chrome 145 and
 * 147 on "X11; Linux x86_64" while stable was 156, a fresh browser session
 * for every page, one every 4-15 seconds overnight, with no webdriver flag,
 * no HeadlessChrome brand and nothing in its UA naming it. Desktop Chrome
 * updates itself, so that far behind is a bundled automation Chromium.
 * The platform must say Linux too: an old Android tablet sends this same
 * UA in desktop mode, from a Chrome its Android version can no longer
 * update, but reports "Android". Chromebooks say "CrOS" and old Windows and
 * macOS machines their own OS, so none of them match. */
const LINUX_DESKTOP_CHROME = /\(X11; Linux x86_64\) AppleWebKit\/[\d.]+ \(KHTML, like Gecko\) Chrome\/(\d+)\./;
// Stable Chrome was 156 on 2026-11-04 and ships a major version about every
// four weeks. Counting one per five keeps the estimate behind the real
// stable, so the rule only gets more lenient as time passes.
const CHROME_STABLE = { major: 156, at: Date.UTC(2026, 10, 4) };
const CHROME_WEEKS_PER_MAJOR = 5;
const STALE_MAJORS = 6;

export function isStaleLinuxChrome(userAgent: string, platform: string, now: number): boolean {
  const match = LINUX_DESKTOP_CHROME.exec(userAgent);
  if (!match || platform !== "Linux") return false;
  const weeks = (now - CHROME_STABLE.at) / (7 * 24 * 60 * 60 * 1000);
  const stable = CHROME_STABLE.major + Math.max(0, Math.floor(weeks / CHROME_WEEKS_PER_MAJOR));
  return Number(match[1]) <= stable - STALE_MAJORS;
}

export function isPrerenderLoad(signals: PrerenderSignals): boolean {
  return isOwnRender(signals.search) || isCrawlerLoad(signals);
}

/** prerender.py's own render, a cache fill on a crawler's behalf. */
export function isOwnRender(search: string): boolean {
  return new URLSearchParams(search).get("prerender") === "1";
}

/** A crawler or other automated browser loading the page itself. The visit
 * counter labels these "crawler" rather than dropping them, so the visit
 * report can say how many there were instead of leaving them to be guessed
 * at inside "direct". */
export function isCrawlerLoad({ userAgent, brands, webdriver, platform, now }: PrerenderSignals): boolean {
  return (
    webdriver ||
    /HeadlessChrome/.test(userAgent) ||
    CRAWLER_UA.test(userAgent) ||
    brands.includes("HeadlessChrome") ||
    isStaleLinuxChrome(userAgent, platform, now)
  );
}

function currentSignals(): PrerenderSignals {
  const nav = navigator as Navigator & { userAgentData?: { brands?: { brand: string }[]; platform?: string } };
  return {
    search: window.location.search,
    userAgent: nav.userAgent,
    brands: (nav.userAgentData?.brands ?? []).map((b) => b.brand),
    webdriver: !!nav.webdriver,
    platform: nav.userAgentData?.platform ?? "",
    now: Date.now(),
  };
}

/** Decided once at startup, while the landing URL still carries ?prerender=1. */
export const IS_PRERENDER = typeof window !== "undefined" && isPrerenderLoad(currentSignals());
export const IS_OWN_RENDER = typeof window !== "undefined" && isOwnRender(window.location.search);
export const IS_CRAWLER = IS_PRERENDER && !IS_OWN_RENDER;

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
