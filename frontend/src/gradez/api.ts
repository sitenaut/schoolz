import { apiFetch } from "../api";

export { apiFetch };

/** A GET that can't throw: null when the request failed or was refused, so a
 * tab can show what it has instead of an error for one missing piece. */
export async function apiGet<T>(path: string): Promise<T | null> {
  try {
    const res = await apiFetch(path);
    return res.ok ? ((await res.json()) as T) : null;
  } catch {
    return null;
  }
}
