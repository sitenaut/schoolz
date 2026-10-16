/** /localz itself, and /local (Events), which is Localz's second tab. Kept
 * apart from lib/localz.ts so lib/analytics.ts can ask without pulling in
 * the API client. Takes a router path (no /es prefix). */
export function isLocalzPath(pathname: string): boolean {
  return pathname === "/localz" || pathname.startsWith("/localz/") || pathname === "/local";
}
