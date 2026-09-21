import { useState } from "react";
import { Link } from "react-router-dom";
import { IS_SUPABASE_AUTH } from "../authConfig";
import { useAuth } from "../context/AuthContext";

type Mode = "login" | "register";

/** The actual login/register form fields and submit logic, shared by the
 * top-right popover (the normal path), the full-page routes at /login and
 * /register, and the invite landing page (which embeds it so the person
 * never has to leave the invite to get an account).
 *
 * `returnTo` is the app path Supabase should bring the browser back to
 * after Google or an email-confirmation link - without it both land on the
 * site root and whatever the person was in the middle of is lost. */
export function AuthPanel({
  mode,
  onModeChange,
  onSuccess,
  returnTo,
  presetEmail,
}: {
  mode: Mode;
  onModeChange: (m: Mode) => void;
  onSuccess?: () => void;
  returnTo?: string;
  presetEmail?: string;
}) {
  const { loginLocal, registerLocal, loginWithPasswordSupabase, registerWithPasswordSupabase, loginWithGoogle, error } = useAuth();
  const [identifier, setIdentifier] = useState(presetEmail ?? "");
  const [email, setEmail] = useState(presetEmail ?? "");
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
        await registerWithPasswordSupabase(email, password, returnTo);
        setDone(true);
        return;
      }
      await registerLocal(email, username, password);
    }
    onSuccess?.();
  };

  if (done) {
    return (
      <div className="card" style={{ marginBottom: 0 }}>
        <p style={{ margin: 0 }}>
          <strong>Check your email.</strong> We sent a confirmation link to <strong>{email}</strong>. Tap it and you'll
          come straight back here{returnTo ? " to finish" : ""}.
        </p>
      </div>
    );
  }

  return (
    <>
      {IS_SUPABASE_AUTH && (
        <>
          <button className="btn btn-primary" style={{ width: "100%", justifyContent: "center" }} onClick={() => loginWithGoogle(returnTo)} type="button">
            Continue with Google
          </button>
          <p className="note" style={{ textAlign: "center", margin: "10px 0" }}>
            or with an email and password
          </p>
        </>
      )}
      <div className="tabs">
        <button className={`tab ${mode === "login" ? "active" : ""}`} onClick={() => onModeChange("login")} type="button">
          Sign in
        </button>
        <button className={`tab ${mode === "register" ? "active" : ""}`} onClick={() => onModeChange("register")} type="button">
          Create account
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
        {mode === "login" && (
          <div className="auth-links">
            <span />
            <Link to="/forgot-password">Forgot password?</Link>
          </div>
        )}
        {error && (
          <p className="note" style={{ color: "var(--bad)" }}>
            {error}
          </p>
        )}
        <button type="submit" className={`btn ${IS_SUPABASE_AUTH ? "" : "btn-primary"}`} style={{ width: "100%", justifyContent: "center" }}>
          {mode === "login" ? "Sign in" : "Create account"}
        </button>
      </form>
    </>
  );
}
