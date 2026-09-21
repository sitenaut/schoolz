import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { trackEvent, trackMeasurement } from "../lib/track";
import { API_URL, IS_SUPABASE_AUTH } from "../authConfig";
import { supabase } from "../supabase";
import { apiFetch, setLocalToken, clearLocalToken, getLocalToken, setCachedAccessToken } from "../api";

// How long the app will sit on "Loading…" before offering the visitor a
// way out. Only reachable if the auth check never resolves at all.
const AUTH_TIMEOUT_MS = 8000;

type CurrentUser = {
  id: string;
  email: string;
  username: string;
  is_admin: boolean;
  auth_mode: string;
  sign_in_method: "password" | "google";
  created_at: string | null;
  // Set when this login belongs to a student (not a guardian) - see
  // backend routers/student_accounts.py.
  student_profile_id: string | null;
};

type AuthContextValue = {
  user: CurrentUser | null;
  loading: boolean;
  /** True once the auth check has been stuck long enough that the UI
   * should stop pretending it's still about to finish. */
  authTimedOut: boolean;
  error: string | null;
  registerLocal: (email: string, username: string, password: string) => Promise<void>;
  loginLocal: (usernameOrEmail: string, password: string) => Promise<void>;
  loginWithGoogle: (returnTo?: string) => Promise<void>;
  loginWithPasswordSupabase: (email: string, password: string) => Promise<void>;
  registerWithPasswordSupabase: (email: string, password: string, returnTo?: string) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [authTimedOut, setAuthTimedOut] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Takes whether a session exists rather than going and asking for it -
  // the callers that know already shouldn't have to ask again, and the
  // onAuthStateChange caller below mustn't.
  const loadUser = async (hasSession: boolean) => {
    try {
      // Skip the request entirely when we know there's nothing to check -
      // avoids a benign but noisy 401 in devtools on first page load.
      if (!hasSession) {
        setUser(null);
        return;
      }
      const res = await apiFetch("/auth/me");
      setUser(res.ok ? await res.json() : null);
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  };

  const refresh = async () => {
    if (IS_SUPABASE_AUTH && supabase) {
      const { data } = await supabase.auth.getSession();
      setCachedAccessToken(data.session?.access_token ?? null);
      await loadUser(Boolean(data.session));
      return;
    }
    await loadUser(IS_SUPABASE_AUTH ? false : Boolean(getLocalToken()));
  };

  useEffect(() => {
    if (IS_SUPABASE_AUTH && supabase) {
      // supabase-js serialises auth work behind an internal lock and runs
      // this callback while still holding it, so calling any supabase auth
      // method from in here deadlocks - getSession() would wait on a lock
      // its own caller owns. That is what hung the logged-in pages in prod:
      // refresh() called getSession() from this callback, and because
      // apiFetch also called getSession() per request, every in-flight
      // request piled up behind the same lock. When it never released,
      // `loading` never cleared and the page sat on "Loading…" until the
      // visitor reloaded by hand.
      //
      // So: take the token straight off the session argument this callback
      // is handed, and push the /auth/me call out of the callback entirely.
      const { data: sub } = supabase.auth.onAuthStateChange((_event, session) => {
        setCachedAccessToken(session?.access_token ?? null);
        setTimeout(() => void loadUser(Boolean(session)), 0);
      });
      // supabase-js fires INITIAL_SESSION on subscribe, so the first load
      // is already covered here - calling refresh() as well would only
      // duplicate it (and race it).
      return () => sub.subscription.unsubscribe();
    }
    void refresh();
  }, []);

  useEffect(() => {
    if (!loading) return;
    const timer = setTimeout(() => {
      setAuthTimedOut(true);
      // The one unambiguous signal that this specific failure happened -
      // everything else about it is inferred from side effects (a long
      // today_ready, a fetch that never returns).
      trackEvent("auth_timeout", { after_ms: AUTH_TIMEOUT_MS });
    }, AUTH_TIMEOUT_MS);
    return () => clearTimeout(timer);
  }, [loading]);

  // How long the auth check actually took. Previously nothing measured
  // this at all, so a stalled check was only visible second-hand, as the
  // max of today_ready.
  const authStartedAt = useRef<number>(performance.now());
  const authReported = useRef(false);
  useEffect(() => {
    if (loading || authReported.current) return;
    authReported.current = true;
    trackMeasurement("auth_ready", performance.now() - authStartedAt.current, {
      outcome: user ? "authenticated" : "anonymous",
    });
  }, [loading, user]);

  const registerLocal = async (email: string, username: string, password: string) => {
    setError(null);
    let res: Response;
    try {
      res = await apiFetch("/auth/register", {
        method: "POST",
        body: JSON.stringify({ email, username, password }),
      });
    } catch {
      setError(`Could not reach the backend at ${API_URL}`);
      return;
    }
    if (!res.ok) {
      setError((await res.json()).detail ?? "Registration failed");
      return;
    }
    const { access_token } = await res.json();
    setLocalToken(access_token);
    await refresh();
  };

  const loginLocal = async (usernameOrEmail: string, password: string) => {
    setError(null);
    let res: Response;
    try {
      res = await apiFetch("/auth/login", {
        method: "POST",
        body: JSON.stringify({ username_or_email: usernameOrEmail, password }),
      });
    } catch {
      setError(`Could not reach the backend at ${API_URL}`);
      return;
    }
    if (!res.ok) {
      setError((await res.json()).detail ?? "Login failed");
      return;
    }
    const { access_token } = await res.json();
    setLocalToken(access_token);
    await refresh();
  };

  // Supabase sends the browser back to its configured Site URL after Google
  // or an email-confirmation link unless told otherwise - which is how an
  // invite's ?next= used to get lost. `returnTo` is an app path to land on
  // instead (it must be under the project's allowed redirect URLs).
  const absoluteReturnTo = (returnTo?: string) => (returnTo ? `${window.location.origin}${returnTo}` : undefined);

  const loginWithGoogle = async (returnTo?: string) => {
    if (!supabase) return;
    setError(null);
    const { error: err } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: { redirectTo: absoluteReturnTo(returnTo) },
    });
    if (err) setError(err.message);
  };

  const loginWithPasswordSupabase = async (email: string, password: string) => {
    if (!supabase) return;
    setError(null);
    const { error: err } = await supabase.auth.signInWithPassword({ email, password });
    if (err) setError(err.message);
    else await refresh();
  };

  const registerWithPasswordSupabase = async (email: string, password: string, returnTo?: string) => {
    if (!supabase) return;
    setError(null);
    const { error: err } = await supabase.auth.signUp({
      email,
      password,
      options: { emailRedirectTo: absoluteReturnTo(returnTo) },
    });
    if (err) setError(err.message);
  };

  const logout = async () => {
    if (IS_SUPABASE_AUTH && supabase) {
      await supabase.auth.signOut();
    } else {
      clearLocalToken();
    }
    setUser(null);
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        loading,
        authTimedOut,
        error,
        registerLocal,
        loginLocal,
        loginWithGoogle,
        loginWithPasswordSupabase,
        registerWithPasswordSupabase,
        logout,
        refresh,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
