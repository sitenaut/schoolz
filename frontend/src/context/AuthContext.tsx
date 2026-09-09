import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { API_URL, IS_SUPABASE_AUTH } from "../authConfig";
import { supabase } from "../supabase";
import { apiFetch, setLocalToken, clearLocalToken, getLocalToken } from "../api";

type CurrentUser = {
  id: string;
  email: string;
  username: string;
  is_admin: boolean;
  auth_mode: string;
};

type AuthContextValue = {
  user: CurrentUser | null;
  loading: boolean;
  error: string | null;
  registerLocal: (email: string, username: string, password: string) => Promise<void>;
  loginLocal: (usernameOrEmail: string, password: string) => Promise<void>;
  loginWithGoogle: () => Promise<void>;
  loginWithPasswordSupabase: (email: string, password: string) => Promise<void>;
  registerWithPasswordSupabase: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = async () => {
    try {
      // Skip the request entirely when we know there's nothing to check -
      // avoids a benign but noisy 401 in devtools on first page load.
      if (IS_SUPABASE_AUTH) {
        if (supabase) {
          const { data } = await supabase.auth.getSession();
          if (!data.session) {
            setUser(null);
            return;
          }
        }
      } else if (!getLocalToken()) {
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

  useEffect(() => {
    refresh();
    if (IS_SUPABASE_AUTH && supabase) {
      const { data: sub } = supabase.auth.onAuthStateChange(() => refresh());
      return () => sub.subscription.unsubscribe();
    }
  }, []);

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

  const loginWithGoogle = async () => {
    if (!supabase) return;
    setError(null);
    const { error: err } = await supabase.auth.signInWithOAuth({ provider: "google" });
    if (err) setError(err.message);
  };

  const loginWithPasswordSupabase = async (email: string, password: string) => {
    if (!supabase) return;
    setError(null);
    const { error: err } = await supabase.auth.signInWithPassword({ email, password });
    if (err) setError(err.message);
    else await refresh();
  };

  const registerWithPasswordSupabase = async (email: string, password: string) => {
    if (!supabase) return;
    setError(null);
    const { error: err } = await supabase.auth.signUp({ email, password });
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
