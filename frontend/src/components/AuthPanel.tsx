import { useState } from "react";
import { IS_SUPABASE_AUTH } from "../authConfig";
import { useAuth } from "../context/AuthContext";

type Mode = "login" | "register";

/** The actual login/register form fields and submit logic, shared by the
 * top-right popover (the normal path) and the full-page routes at
 * /login and /register (kept for deep links like an invite's
 * `?next=` redirect, which needs a real page to land on). */
export function AuthPanel({ mode, onModeChange, onSuccess }: { mode: Mode; onModeChange: (m: Mode) => void; onSuccess?: () => void }) {
  const { loginLocal, registerLocal, loginWithPasswordSupabase, registerWithPasswordSupabase, loginWithGoogle, error } = useAuth();
  const [identifier, setIdentifier] = useState("");
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [done, setDone] = useState(false);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (mode === "login") {
      if (IS_SUPABASE_AUTH) await loginWithPasswordSupabase(identifier, password);
      else await loginLocal(identifier, password);
    } else {
      if (IS_SUPABASE_AUTH) {
        await registerWithPasswordSupabase(email, password);
        setDone(true);
        return;
      }
      await registerLocal(email, username, password);
    }
    onSuccess?.();
  };

  if (done) {
    return <p className="note">Check your email to confirm your account.</p>;
  }

  return (
    <>
      <div className="tabs">
        <button className={`tab ${mode === "login" ? "active" : ""}`} onClick={() => onModeChange("login")} type="button">
          Sign in
        </button>
        <button className={`tab ${mode === "register" ? "active" : ""}`} onClick={() => onModeChange("register")} type="button">
          Register
        </button>
      </div>
      <form onSubmit={onSubmit}>
        {mode === "login" ? (
          <label>
            {IS_SUPABASE_AUTH ? "Email" : "Username or email"}
            <input value={identifier} onChange={(e) => setIdentifier(e.target.value)} required autoFocus />
          </label>
        ) : (
          <>
            <label>
              Email
              <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus />
            </label>
            {!IS_SUPABASE_AUTH && (
              <label>
                Username
                <input value={username} onChange={(e) => setUsername(e.target.value)} required />
              </label>
            )}
          </>
        )}
        <label>
          Password
          <input type="password" minLength={mode === "register" ? 8 : undefined} value={password} onChange={(e) => setPassword(e.target.value)} required />
        </label>
        {error && (
          <p className="note" style={{ color: "var(--bad)" }}>
            {error}
          </p>
        )}
        <button type="submit" className="btn btn-primary" style={{ width: "100%", justifyContent: "center" }}>
          {mode === "login" ? "Sign in" : "Create account"}
        </button>
      </form>
      {IS_SUPABASE_AUTH && (
        <button className="btn" style={{ width: "100%", justifyContent: "center", marginTop: 8 }} onClick={loginWithGoogle} type="button">
          Continue with Google
        </button>
      )}
    </>
  );
}
