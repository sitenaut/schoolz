// A cold page load with an expired access token makes supabase-js renew it
// before reporting INITIAL_SESSION. If that one request fails on the network
// (a mobile tab just opened, the browser cancelling it mid-navigation), it
// reports INITIAL_SESSION with no session but leaves the session in storage.
// Taken at its word, a signed-in admin opening an approval link was sent to
// /login and on to Google; a reload, whose renewal went through, had them in.
// So a null INITIAL_SESSION with a session still in storage is retried first.

const STORED_SESSION = /^sb-.+-auth-token$/;

export function hasStoredSession(storage: Pick<Storage, "length" | "key"> | undefined): boolean {
  if (!storage) return false;
  try {
    for (let i = 0; i < storage.length; i++) {
      const key = storage.key(i);
      if (key && STORED_SESSION.test(key)) return true;
    }
  } catch {
    // Storage can throw (private mode, blocked site data): nothing to recover.
  }
  return false;
}

type Refresh = () => Promise<{ data: { session: unknown | null }; error: { name?: string; status?: number } | null }>;

/** Retry the renewal a few times. "recovered" means a session came back
 * (supabase-js then announces it through onAuthStateChange); "gone" means
 * the server refused it or it never came back. */
export async function recoverSession(
  refresh: Refresh,
  delaysMs: number[] = [0, 1000, 3000],
  sleep: (ms: number) => Promise<void> = (ms) => new Promise((r) => setTimeout(r, ms)),
): Promise<"recovered" | "gone"> {
  for (const delay of delaysMs) {
    if (delay) await sleep(delay);
    try {
      const { data, error } = await refresh();
      if (data.session) return "recovered";
      // A real answer from the server (a revoked or used refresh token) is final;
      // only a network failure is worth another try.
      if (error && error.name !== "AuthRetryableFetchError") return "gone";
    } catch {
      // Network-level throw: try again.
    }
  }
  return "gone";
}
