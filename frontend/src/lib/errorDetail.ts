/** What to show for a failed API call. `detail` is a message, except on a
 * 422, where FastAPI sends a list of {loc, msg, ...} objects: rendered as-is
 * that throws "Objects are not valid as a React child", and a co-parent's
 * email with no dot in the domain (which the browser's email field accepts)
 * replaced all of My family with "This page didn't load". */
export function errorDetail(body: unknown, fallback: string): string {
  const detail = body && typeof body === "object" ? (body as { detail?: unknown }).detail : undefined;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((d) => (d && typeof d === "object" ? (d as { msg?: unknown }).msg : null))
      .filter((m): m is string => typeof m === "string" && m.trim() !== "");
    if (messages.length) return messages.join(" ");
  }
  return fallback;
}
