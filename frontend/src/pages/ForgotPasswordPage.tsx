import { useState } from "react";
import { Link } from "react-router-dom";
import { IS_SUPABASE_AUTH } from "../authConfig";
import { Field } from "../components/ui/Field";
import { sendPasswordReset } from "../lib/account";

export function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [devToken, setDevToken] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setDevToken(await sendPasswordReset(email.trim()));
      setSent(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="page">
      <div className="auth-card">
        <h1>Forgot your password?</h1>
        <p className="sub">Enter your email and we'll send a link to choose a new one.</p>
        {sent ? (
          <>
            <div className="form-ok">If an account exists for {email}, a reset link is on its way. Check your inbox (and spam).</div>
            {devToken && (
              <div className="dev-token">
                <b>Local dev mode</b> - there's no mailer, so here's your link:{" "}
                <Link to={`/reset-password?token=${encodeURIComponent(devToken)}`}>reset your password</Link>
              </div>
            )}
          </>
        ) : (
          <form onSubmit={submit}>
            {error && <div className="form-error">{error}</div>}
            <Field label="Email">
              <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus autoComplete="email" />
            </Field>
            <button className="btn btn-primary" type="submit" disabled={busy} style={{ justifyContent: "center" }}>
              {busy ? "Sending…" : "Send reset link"}
            </button>
          </form>
        )}
        <div className="ft">
          <Link to="/login">Back to sign in</Link>
          {IS_SUPABASE_AUTH && <span> · Signed up with Google? Just use “Continue with Google”.</span>}
        </div>
      </div>
    </div>
  );
}
