import { gaEvent } from "./analytics";
import { getFaro } from "./telemetry";

type Attrs = Record<string, string | number | boolean>;

function stringify(attrs?: Attrs): Record<string, string> | undefined {
  if (!attrs) return undefined;
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(attrs)) out[k] = String(v);
  return out;
}

/** No-ops when Faro isn't initialized (local dev, vitest, RUM disabled). */
export function trackEvent(name: string, attrs?: Attrs): void {
  if (FARO_EVENTS.has(name)) getFaro()?.api.pushEvent(name, stringify(attrs));
  forwardToGa(name, attrs);
}

// Product events (actions, searches, sign-up/login, chat...) live in GA4 only,
// so they aren't collected twice. Faro keeps just the events the Grafana
// dashboards/alerts query by name: page_view and cta_click (user-experience
// dashboard) and auth_timeout (alert). Add a name here before pointing a
// Loki query at it.
const FARO_EVENTS = new Set(["page_view", "cta_click", "auth_timeout"]);

// Not forwarded: page_view is sent to GA by AppShell (it needs the scrubbed
// location and waits for auth so admin/test traffic can be flagged first);
// auth_timeout is an RUM diagnostic with no analytics meaning.
const GA_SKIP = new Set(["page_view", "auth_timeout"]);

function forwardToGa(name: string, attrs?: Attrs): void {
  if (GA_SKIP.has(name)) return;
  // "action" is a generic bucket in RUM; in GA each action gets its own
  // event name so it can be marked as a key event (e.g. action_absence).
  const gaName = name === "action" && typeof attrs?.action === "string" ? `action_${attrs.action}` : name;
  gaEvent(gaName.replace(/[^a-zA-Z0-9_]/g, "_").slice(0, 40), attrs);
}

/** valueMs: elapsed time in milliseconds for a "*_ready" measurement. */
export function trackMeasurement(type: string, valueMs: number, attrs?: Attrs): void {
  getFaro()?.api.pushMeasurement({ type, values: { value_ms: valueMs } }, { context: stringify(attrs) });
}
