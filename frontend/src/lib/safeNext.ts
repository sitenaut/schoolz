/** Only a same-site app path, for a `?next=` to send someone back to. Sign-in
 * concatenates it after the origin for Supabase's redirect, where "@evil.com"
 * or "//evil.com" would leave the site. */
export function safeNext(raw: string | null): string {
  return raw && raw.startsWith("/") && !raw.startsWith("//") && !raw.startsWith("/\\") ? raw : "/";
}

/** A path another build on this origin serves (the Focus app at /focus/):
 * the SPA router has no route for it, so getting there takes a page load. */
export function isOutsideApp(path: string): boolean {
  return /^\/focus(\/|\?|$)/.test(path);
}

/** Where Supabase brings the browser back to after Google or an email link,
 * for a `next`. A path outside the app comes back through /login, which does
 * the page load, so only app paths ever need to be allowed redirect URLs. */
export function returnToFor(next: string): string | undefined {
  if (next === "/") return undefined;
  return isOutsideApp(next) ? `/login?next=${encodeURIComponent(next)}` : next;
}

/** Sends a signed-in visitor on to `next`: a router navigation inside the
 * app, a page load for a path outside it. */
export function goToNext(next: string, navigate: (to: string, options: { replace: boolean }) => void): void {
  if (isOutsideApp(next)) window.location.replace(next);
  else navigate(next, { replace: true });
}
