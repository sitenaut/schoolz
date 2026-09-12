import {
  createReactRouterV6Options,
  FaroRoutes as FaroRoutesImpl,
  getWebInstrumentations,
  initializeFaro,
  ReactIntegration,
  type Faro,
  type TransportItem,
} from "@grafana/faro-react";
import { TracingInstrumentation } from "@grafana/faro-web-tracing";
import { createRoutesFromChildren, matchRoutes, Routes, useLocation, useNavigationType } from "react-router-dom";
import { API_URL, APP_VERSION, FARO_URL } from "../authConfig";

let faroInstance: Faro | null = null;

// Query params that can carry a credential or one-time token - stripped
// wholesale rather than allowlisted, since a new one (e.g. a future OAuth
// provider's own param name) should be dropped by default, not leaked by
// default. Supabase's OAuth callback also puts tokens in the #hash, which
// is dropped in full below (a hash has no other legitimate use in this app).
const SENSITIVE_PARAMS = ["code", "token", "access_token", "refresh_token", "state"];

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** Rewrites a URL/path to strip credentials and collapse an invite token to
 * its route template, so it's safe to store/display in Grafana Cloud. */
export function scrubUrl(url: string): string {
  let result = url;

  // The #hash (Supabase OAuth: #access_token=...&refresh_token=...) has no
  // legitimate use here - drop it entirely rather than parsing it.
  const hashIndex = result.indexOf("#");
  if (hashIndex !== -1) {
    result = result.slice(0, hashIndex);
  }

  try {
    const isAbsolute = /^https?:\/\//i.test(result);
    const parsed = new URL(result, isAbsolute ? undefined : "http://scrub.invalid");
    let changed = false;
    for (const param of SENSITIVE_PARAMS) {
      if (parsed.searchParams.has(param)) {
        parsed.searchParams.delete(param);
        changed = true;
      }
    }
    if (changed) {
      const search = parsed.searchParams.toString();
      const path = parsed.pathname + (search ? `?${search}` : "");
      result = isAbsolute ? parsed.origin + path : path;
    }
  } catch {
    // Not a parseable URL (e.g. a bare route template) - fall through.
  }

  result = result.replace(/\/invites\/[^/?#]+/, "/invites/:token");
  return result;
}

function scrubValue(value: unknown): unknown {
  if (typeof value === "string" && (value.startsWith("http") || value.includes("/invites/"))) {
    return scrubUrl(value);
  }
  return value;
}

function scrubItem<P>(item: TransportItem<P>): TransportItem<P> {
  if (item.meta.page?.url) {
    item.meta.page.url = scrubUrl(item.meta.page.url);
  }
  if (item.meta.view?.name) {
    item.meta.view.name = scrubUrl(item.meta.view.name);
  }
  const payload = item.payload as unknown as Record<string, unknown> | undefined;
  if (payload && typeof payload === "object") {
    for (const key of Object.keys(payload)) {
      const value = payload[key];
      if (typeof value === "string") {
        payload[key] = scrubValue(value);
      } else if (value && typeof value === "object") {
        // One level deep is enough for the shapes that carry a URL
        // (event/measurement attributes, page context) - never the
        // query itself, which callers are told not to attach anyway.
        for (const nestedKey of Object.keys(value as Record<string, unknown>)) {
          const nested = (value as Record<string, unknown>)[nestedKey];
          if (typeof nested === "string") {
            (value as Record<string, unknown>)[nestedKey] = scrubValue(nested);
          }
        }
      }
    }
  }
  return item;
}

export function initTelemetry(): void {
  if (!FARO_URL || faroInstance) return;

  faroInstance = initializeFaro({
    url: FARO_URL,
    app: {
      // Must match the Frontend Observability app name registered in
      // Grafana Cloud for this collector key ("schoolz-faro", created from
      // the stock tutorial snippet without renaming) - Faro's collector
      // validates this and silently drops/rejects data on a mismatch,
      // which is exactly what showed up as "Never received any data".
      name: "schoolz-faro",
      version: APP_VERSION,
      environment: import.meta.env.MODE === "production" ? "prod" : "local",
    },
    sessionTracking: { samplingRate: 1 },
    instrumentations: [
      ...getWebInstrumentations({ captureConsole: true }),
      new TracingInstrumentation({
        instrumentationOptions: {
          // API only - never Supabase, never any third-party host.
          propagateTraceHeaderCorsUrls: [new RegExp("^" + escapeRegExp(API_URL))],
        },
      }),
      new ReactIntegration({
        router: createReactRouterV6Options({
          createRoutesFromChildren,
          matchRoutes,
          Routes,
          useLocation,
          useNavigationType,
        }),
      }),
    ],
    beforeSend: scrubItem,
  });
}

export function getFaro(): Faro | null {
  return faroInstance;
}

// FaroRoutes renders faro's *internal* Routes reference, which is only
// assigned when initializeFaro runs createReactRouterV6Options. With RUM
// off (no VITE_FARO_URL - every local build) that reference is undefined
// and React throws #130 on every route, blanking the whole app. Prod never
// saw it because RUM is on there. Fall back to the plain router Routes.
export const FaroRoutes: typeof Routes = FARO_URL ? (FaroRoutesImpl as typeof Routes) : Routes;
