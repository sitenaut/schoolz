import { API_URL } from "../authConfig";

const SOURCE_KEY = "schoolz_visit_source";
const SEEN_KEY = "schoolz_visit_seen";

/** Where this visit came from, worked out once and remembered for the rest
 * of the browser session (first-touch attribution): a reader who lands on
 * /chcomms from Facebook and then clicks through to /survey should count as
 * one Facebook visitor on both pages, not "facebook" then "direct".
 *
 * Deliberately coarse - a label like "facebook" or "direct", never the full
 * referring URL and never a click id. Facebook appends `fbclid`, a unique
 * per-click identifier: we read it as a signal that the click came from
 * Facebook and then throw it away. It is never stored or sent anywhere. */
export function visitSource(): string {
  try {
    const remembered = sessionStorage.getItem(SOURCE_KEY);
    if (remembered) return remembered;
  } catch {
    /* private mode / storage disabled - fall through and just compute it */
  }

  const source = computeSource();
  try {
    sessionStorage.setItem(SOURCE_KEY, source);
  } catch {
    /* non-fatal: we simply recompute on the next page */
  }
  return source;
}

function computeSource(): string {
  if (typeof window === "undefined") return "direct";
  const params = new URLSearchParams(window.location.search);

  // An explicit campaign tag always wins - it's the one the link author chose.
  const utm = (params.get("utm_source") || "").trim().toLowerCase();
  if (utm) return sanitize(utm);

  // Facebook's own click id, present even when the referrer is stripped
  // (the in-app browser often sends none).
  if (params.has("fbclid")) return "facebook";

  const referrer = document.referrer;
  if (!referrer) return "direct";
  try {
    const host = new URL(referrer).hostname.toLowerCase().replace(/^www\./, "");
    if (host === window.location.hostname) return "internal";
    if (/(^|\.)facebook\.com$|(^|\.)fb\.(com|me)$/.test(host)) return "facebook";
    if (/(^|\.)instagram\.com$/.test(host)) return "instagram";
    if (/(^|\.)google\./.test(host)) return "google";
    if (/(^|\.)nextdoor\.com$/.test(host)) return "nextdoor";
    return sanitize(host);
  } catch {
    return "other";
  }
}

function sanitize(value: string): string {
  const cleaned = value.replace(/[^a-z0-9.-]/g, "").slice(0, 40);
  return cleaned || "other";
}

/** Counts one visit to `path`, at most once per browser session, so the
 * number reads as "people who came to this page" rather than being
 * inflated by back-and-forth navigation.
 *
 * Fire-and-forget: a failure here must never affect the page. The backend
 * stores only an aggregate (day, path, source) counter - see the PageVisit
 * model for why there's deliberately nothing per-visitor in it. */
export function countVisit(path: string): void {
  let seen: string[] = [];
  try {
    seen = JSON.parse(sessionStorage.getItem(SEEN_KEY) || "[]");
    if (seen.includes(path)) return;
    sessionStorage.setItem(SEEN_KEY, JSON.stringify([...seen, path]));
  } catch {
    /* storage unavailable: count it, at the cost of possible duplicates */
  }

  const body = JSON.stringify({ path, source: visitSource() });
  try {
    // sendBeacon survives the page being closed mid-request, which a plain
    // fetch does not - it's the difference between counting someone who
    // bounces after two seconds and losing them.
    if (navigator.sendBeacon) {
      navigator.sendBeacon(`${API_URL}/page-views`, new Blob([body], { type: "application/json" }));
      return;
    }
  } catch {
    /* fall through to fetch */
  }
  fetch(`${API_URL}/page-views`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
    keepalive: true,
  }).catch(() => undefined);
}
