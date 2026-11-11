import { ROUTER_BASENAME } from "./i18n";

/** Only a same-site app path, for a `?next=` to send someone back to. Sign-in
 * concatenates it after the origin for Supabase's redirect, where "@evil.com"
 * or "//evil.com" would leave the site. */
export function safeNext(raw: string | null): string {
  return raw && raw.startsWith("/") && !raw.startsWith("//") && !raw.startsWith("/\\") ? raw : "/";
}

/** A path that takes a page load to reach. Gradez runs in a document that
 * never started analytics (lib/gradezPath.ts), so it is never navigated to
 * inside this one; /focus is its old address, which the web server redirects. */
export function isOutsideApp(path: string): boolean {
  return /^\/(focus|gradez)(\/|\?|$)/.test(path);
}

/** Where Supabase brings the browser back to after Google or an email link,
 * for a `next`. A path outside the app comes back through /login, which does
 * the page load, so only app paths ever need to be allowed redirect URLs. */
export function returnToFor(next: string): string | undefined {
  if (next === "/") return undefined;
  return isOutsideApp(next) ? `/login?next=${encodeURIComponent(next)}` : next;
}

/** Sends a signed-in visitor on to `next`: a router navigation inside the
 * app, a page load for a path outside it (under the same language prefix,
 * which the router would have added by itself). */
export function goToNext(next: string, navigate: (to: string, options: { replace: boolean }) => void): void {
  if (isOutsideApp(next)) window.location.replace(ROUTER_BASENAME + next);
  else navigate(next, { replace: true });
}
