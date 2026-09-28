import { GA_MEASUREMENT_ID } from "../authConfig";
import { SITE_URL } from "./site";

const INTERNAL_KEY = "schoolz_internal";
const OPTOUT_KEY = "schoolz_ga_optout";

type GtagParams = Record<string, string | number | boolean | undefined>;

declare global {
  interface Window {
    dataLayer?: unknown[];
  }
}

// Personal or token-bearing routes are reported as their template, never the
// real path, so an invite token or anything about a child can't reach Google.
// Everything else is a public page whose real path (a school's slug) is
// exactly what landing-page reporting needs.
const PRIVATE_PREFIXES = ["/account", "/admin", "/children", "/kids", "/gmail", "/login", "/register", "/forgot-password", "/reset-password", "/start", "/local"];
const TOKEN_ROUTES: [RegExp, string][] = [
  [/^\/invites\/[^/]+$/, "/invites/:token"],
  [/^\/student-invites\/[^/]+$/, "/student-invites/:token"],
];

/** The path (plus utm_* only) that GA sees for a page. utm_* stays so
 * campaign attribution works; every other query param (?school=, ?q=,
 * click ids, OAuth codes) is dropped. */
export function analyticsPath(pathname: string, search: string): string {
  for (const [pattern, template] of TOKEN_ROUTES) {
    if (pattern.test(pathname)) return template;
  }
  if (PRIVATE_PREFIXES.some((p) => pathname === p || pathname.startsWith(`${p}/`))) return pathname.split("/").slice(0, 2).join("/");
  const params = new URLSearchParams(search);
  const kept = new URLSearchParams();
  for (const [k, v] of params) if (k.toLowerCase().startsWith("utm_")) kept.set(k.toLowerCase(), v.slice(0, 100));
  const qs = kept.toString();
  return pathname + (qs ? `?${qs}` : "");
}

export type TrackGate = { id: string; webdriver: boolean; hostname: string; siteHostname: string };

/** Measurement is on only for a real browser on the real production host.
 * The hostname check keeps a prod build opened on localhost, a Fly preview
 * or the prerender service's internal address out of the numbers; webdriver
 * keeps Playwright/headless renders (including our own prerender pass) out. */
export function shouldTrack({ id, webdriver, hostname, siteHostname }: TrackGate): boolean {
  return Boolean(id) && !webdriver && hostname === siteHostname;
}

function siteHostname(): string {
  try {
    return new URL(SITE_URL).hostname;
  } catch {
    return "";
  }
}

let ready = false;

function gtag(..._args: unknown[]): void {
  // gtag.js only understands the Arguments object, not a plain array.
  (window.dataLayer ||= []).push(arguments);
}

function readInternal(): boolean {
  try {
    return localStorage.getItem(INTERNAL_KEY) === "1";
  } catch {
    return false;
  }
}

/** Marks this browser as the owner's/tester's so its traffic can be
 * excluded by GA's Internal traffic data filter (matches traffic_type). */
export function setInternalTraffic(internal: boolean): void {
  try {
    if (internal) localStorage.setItem(INTERNAL_KEY, "1");
    else localStorage.removeItem(INTERNAL_KEY);
  } catch {
    /* private mode: flag just won't persist */
  }
  if (ready) gtag("set", { traffic_type: internal ? "internal" : undefined });
}

/** ?internal=1 on any URL flags this browser once; ?internal=0 clears it. */
function applyInternalQueryFlag(): void {
  const v = new URLSearchParams(window.location.search).get("internal");
  if (v === "1") setInternalTraffic(true);
  else if (v === "0") setInternalTraffic(false);
}

export function isAnalyticsOptedOut(): boolean {
  try {
    return localStorage.getItem(OPTOUT_KEY) === "1";
  } catch {
    return false;
  }
}

/** Per-device opt-out (Privacy page). GA's own documented switch, a
 * window["ga-disable-<ID>"] flag, stops hits immediately without a reload. */
export function setAnalyticsOptOut(optOut: boolean): void {
  try {
    if (optOut) localStorage.setItem(OPTOUT_KEY, "1");
    else localStorage.removeItem(OPTOUT_KEY);
  } catch {
    /* private mode: nothing was being stored across visits anyway */
  }
  if (GA_MEASUREMENT_ID) (window as unknown as Record<string, unknown>)[`ga-disable-${GA_MEASUREMENT_ID}`] = optOut;
}

// gtag.js is ~150 KB. Members come first: it isn't fetched until the page has
// finished loading and the browser is idle, so it never competes with the
// app's own bundle or API calls. Hits pushed before then wait in dataLayer
// and are sent when the script arrives.
function loadWhenIdle(): void {
  const inject = () => {
    const script = document.createElement("script");
    script.async = true;
    script.src = `https://www.googletagmanager.com/gtag/js?id=${encodeURIComponent(GA_MEASUREMENT_ID)}`;
    document.head.appendChild(script);
  };
  const afterLoad = () => {
    if (typeof window.requestIdleCallback === "function") window.requestIdleCallback(inject, { timeout: 4000 });
    else setTimeout(inject, 1500); // Safari has no requestIdleCallback
  };
  if (document.readyState === "complete") afterLoad();
  else window.addEventListener("load", afterLoad, { once: true });
}

export function initAnalytics(): void {
  if (ready || typeof window === "undefined") return;
  if (isAnalyticsOptedOut()) {
    setAnalyticsOptOut(true);
    return;
  }
  if (!shouldTrack({ id: GA_MEASUREMENT_ID, webdriver: !!navigator.webdriver, hostname: window.location.hostname, siteHostname: siteHostname() })) return;

  applyInternalQueryFlag();
  window.dataLayer = window.dataLayer || [];
  loadWhenIdle();

  gtag("js", new Date());
  gtag("config", GA_MEASUREMENT_ID, {
    send_page_view: false,
    allow_google_signals: false,
    allow_ad_personalization_signals: false,
    ...(readInternal() ? { traffic_type: "internal" } : {}),
  });
  ready = true;
}

export function gaPageView(pathname: string, search: string, extra?: GtagParams): void {
  if (!ready) return;
  const path = analyticsPath(pathname, search);
  gtag("event", "page_view", {
    page_location: `${SITE_URL || window.location.origin}${path}`,
    page_title: document.title,
    ...extra,
  });
}

export function gaEvent(name: string, params?: GtagParams): void {
  if (!ready) return;
  gtag("event", name, params);
}

/** User-scoped properties (register each as a custom dimension in GA).
 * Values are single strings, 36 chars max, per GA's limit. */
export function gaSetUserProperties(props: Record<string, string | undefined>): void {
  if (!ready) return;
  const clean: Record<string, string | undefined> = {};
  for (const [k, v] of Object.entries(props)) clean[k] = v ? v.slice(0, 36) : undefined;
  gtag("set", "user_properties", clean);
}
