import { stripLangPrefix } from "./i18n";

/** Gradez, a child's schoolwork page. Takes a router path (no /es prefix). */
export function isGradezPath(pathname: string): boolean {
  return pathname === "/gradez" || pathname.startsWith("/gradez/");
}

/** Whether this document was loaded at a Gradez address. Analytics and RUM
 * start once per document (main.tsx) and never in one of these, so a page
 * showing a child's schoolwork carries no third-party script and reports
 * nothing. That only holds if getting into Gradez is a page load, never a
 * router navigation: see lib/safeNext.ts and GradezDocument in App.tsx. */
export const GRADEZ_DOCUMENT = typeof window !== "undefined" && isGradezPath(stripLangPrefix(window.location.pathname));

/** Gradez's address for one child, optionally on one tab. */
export function gradezHref(studentId?: string | null, tab?: "todo" | "grades" | "schedule" | "teachers", extra?: Record<string, string>): string {
  const params = new URLSearchParams();
  if (studentId) params.set("student", studentId);
  if (tab && tab !== "todo") params.set("tab", tab);
  for (const [key, value] of Object.entries(extra ?? {})) params.set(key, value);
  const query = params.toString();
  return query ? `/gradez?${query}` : "/gradez";
}
