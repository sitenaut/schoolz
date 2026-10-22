/** Only a same-site app path, for a `?next=` to send someone back to. Sign-in
 * concatenates it after the origin for Supabase's redirect, where "@evil.com"
 * or "//evil.com" would leave the site. */
export function safeNext(raw: string | null): string {
  return raw && raw.startsWith("/") && !raw.startsWith("//") && !raw.startsWith("/\\") ? raw : "/";
}
