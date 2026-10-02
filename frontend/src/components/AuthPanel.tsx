import { useState } from "react";
import { Link } from "react-router-dom";
import { IS_SUPABASE_AUTH } from "../authConfig";
import { useAuth } from "../context/AuthContext";
import { Trans, useTranslation } from "react-i18next";

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
  const { t } = useTranslation();
  const {
    loginLocal,
    registerLocal,
    loginWithPasswordSupabase,
    registerWithPasswordSupabase,
    resendConfirmationEmailSupabase,
    loginWithGoogle,
    error,
  } = useAuth();
  const [identifier, setIdentifier] = useState(presetEmail ?? "");
  const [email, setEmail] = useState(presetEmail ?? "");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [done, setDone] = useState(false);
  const [resending, setResending] = useState(false);
  const [resent, setResent] = useState(false);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (mode === "login") {
      if (IS_SUPABASE_AUTH) await loginWithPasswordSupabase(identifier, password);
      else await loginLocal(identifier, password);
    } else {
      if (IS_SUPABASE_AUTH) {
        const ok = await registerWithPasswordSupabase(email, password, returnTo);
        if (ok) setDone(true);
        return;
      }
      await registerLocal(email, username, password);
    }
    onSuccess?.();
  };

  if (done) {
    return (
      <div className="card" style={{ marginBottom: 0 }}>
        <p style={{ margin: "0 0 10px" }}>
          <strong>{t("Check your email.")}</strong>{" "}
          <Trans
            i18nKey={
              returnTo
                ? "We sent a confirmation link to <1>{{email}}</1>. Tap it and you'll come straight back here to finish."
                : "We sent a confirmation link to <1>{{email}}</1>. Tap it and you'll come straight back here."
            }
            values={{ email }}
            components={{ 1: <strong /> }}
          />
        </p>
        {resent ? (
          <p className="note" style={{ color: "var(--good, #10b981)", margin: "8px 0 0" }}>
            {t("Confirmation email resent!")}
          </p>
        ) : (
          <button
            type="button"
            className="ghost sm"
            style={{ padding: 0, textDecoration: "underline" }}
            disabled={resending}
            onClick={async () => {
              setResending(true);
              const ok = await resendConfirmationEmailSupabase(email, returnTo);
              setResending(false);
              if (ok) setResent(true);
            }}
          >
            {resending ? t("Resending…") : t("Resend confirmation email")}
          </button>
        )}
      </div>
    );
  }

  return (
    <>
      {IS_SUPABASE_AUTH && (
        <>
          <button className="btn btn-primary" style={{ width: "100%", justifyContent: "center" }} onClick={() => loginWithGoogle(returnTo)} type="button">
            {t("Continue with Google")}
          </button>
          <p className="note" style={{ textAlign: "center", margin: "10px 0" }}>
            {t("or with an email and password")}
          </p>
        </>
      )}
      <div className="tabs">
        <button className={`tab ${mode === "login" ? "active" : ""}`} onClick={() => onModeChange("login")} type="button">
          {t("Sign in")}
        </button>
        <button className={`tab ${mode === "register" ? "active" : ""}`} onClick={() => onModeChange("register")} type="button">
          {t("Create account")}
        </button>
      </div>
      <form onSubmit={onSubmit}>
        {mode === "login" ? (
          <label>
            {IS_SUPABASE_AUTH ? t("Email") : t("Username or email")}
            <input value={identifier} onChange={(e) => setIdentifier(e.target.value)} required autoFocus />
          </label>
        ) : (
          <>
            <label>
              {t("Email")}
              <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus />
            </label>
            {!IS_SUPABASE_AUTH && (
              <label>
                {t("Username")}
                <input value={username} onChange={(e) => setUsername(e.target.value)} required />
              </label>
            )}
          </>
        )}
        <label>
          {t("Password")}
          <input type="password" minLength={mode === "register" ? 8 : undefined} value={password} onChange={(e) => setPassword(e.target.value)} required />
        </label>
        {mode === "login" && (
          <div className="auth-links">
            <span />
            <Link to="/forgot-password">{t("Forgot password?")}</Link>
          </div>
        )}
        {error && (
          <div style={{ margin: "10px 0" }}>
            <p className="note" style={{ color: "var(--bad)", margin: 0 }}>
              {error}
            </p>
            {IS_SUPABASE_AUTH && /email not confirmed/i.test(error) && (
              <div style={{ marginTop: 6 }}>
                {resent ? (
                  <p className="note" style={{ color: "var(--good, #10b981)", margin: 0 }}>
                    {t("Confirmation email resent!")}
                  </p>
                ) : (
                  <button
                    type="button"
                    className="ghost sm"
                    style={{ padding: 0, textDecoration: "underline" }}
                    disabled={resending}
                    onClick={async () => {
                      setResending(true);
                      const targetEmail = identifier || email;
                      const ok = await resendConfirmationEmailSupabase(targetEmail, returnTo);
                      setResending(false);
                      if (ok) setResent(true);
                    }}
                  >
                    {resending ? t("Resending…") : t("Resend confirmation email")}
                  </button>
                )}
              </div>
            )}
          </div>
        )}
        <button type="submit" className={`btn ${IS_SUPABASE_AUTH ? "" : "btn-primary"}`} style={{ width: "100%", justifyContent: "center" }}>
          {mode === "login" ? t("Sign in") : t("Create account")}
        </button>
      </form>
    </>
  );
}
