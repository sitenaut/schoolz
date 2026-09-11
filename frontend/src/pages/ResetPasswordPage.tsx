import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { setLocalToken } from "../api";
import { IS_SUPABASE_AUTH } from "../authConfig";
import { Field } from "../components/ui/Field";
import { useToast } from "../components/ui/Toast";
import { useAuth } from "../context/AuthContext";
import { completePasswordReset } from "../lib/account";
import { supabase } from "../supabase";

/** Landing page for the reset link. Locally the link carries ?token=; in
 * prod Supabase's emailed link lands here with a recovery session in the
 * URL hash, which supabase-js picks up on its own (PASSWORD_RECOVERY) -
 * the hash is dropped before it reaches Faro (telemetry.ts scrubUrl). */
export function ResetPasswordPage() {
  const [params] = useSearchParams();
  const token = params.get("token");
  const navigate = useNavigate();
  const toast = useToast();
  const { refresh } = useAuth();
  const [ready, setReady] = useState(!IS_SUPABASE_AUTH && Boolean(token));
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!IS_SUPABASE_AUTH || !supabase) return;
    supabase.auth.getSession().then(({ data }) => {
      if (data.session) setReady(true);
    });
    const { data: sub } = supabase.auth.onAuthStateChange((event, session) => {
      if (event === "PASSWORD_RECOVERY" || session) setReady(true);
    });
    return () => sub.subscription.unsubscribe();
  }, []);

  const mismatch = confirm.length > 0 && password !== confirm;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const accessToken = await completePasswordReset(token, password);
      if (accessToken) setLocalToken(accessToken);
      await refresh();
      toast({ title: "Password updated", description: "You're signed in with your new password.", tone: "ok" });
      navigate("/account/security", { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not reset password");
      setBusy(false);
    }
  };

  return (
    <div className="page">
      <div className="auth-card">
        <h1>Choose a new password</h1>
        <p className="sub">At least 8 characters. You'll be signed in right after.</p>
        {!ready ? (
          <div className="form-error">
            {IS_SUPABASE_AUTH
              ? "This reset link is missing or has expired. Request a new one below."
              : "This reset link is missing its token. Request a new one below."}
          </div>
        ) : (
          <form onSubmit={submit}>
            {error && <div className="form-error">{error}</div>}
            <Field label="New password">
              <input type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} minLength={8} required autoFocus />
            </Field>
            <Field label="Confirm new password" error={mismatch ? "Passwords don't match" : undefined}>
              <input type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} minLength={8} required />
            </Field>
            <button className="btn btn-primary" type="submit" disabled={busy || password.length < 8 || password !== confirm} style={{ justifyContent: "center" }}>
              {busy ? "Saving…" : "Set new password"}
            </button>
          </form>
        )}
        <div className="ft">
          <Link to="/forgot-password">Request a new link</Link> · <Link to="/login">Back to sign in</Link>
        </div>
      </div>
    </div>
  );
}
