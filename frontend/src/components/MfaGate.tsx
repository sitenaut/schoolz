import { useEffect, useState, type ReactElement } from "react";
import { Link } from "react-router-dom";
import { Field } from "./ui/Field";
import { useAuth } from "../context/AuthContext";
import { verifiedTotpFactorId, verifyCode } from "../lib/mfa";

const SKIP_KEY = "schoolz_mfa_skip";

function skipped(): boolean {
  try {
    return sessionStorage.getItem(SKIP_KEY) === "1";
  } catch {
    return false;
  }
}

/** In front of the admin pages (SZ-18). An admin whose session hasn't passed
 * the second factor is asked for their code when they have an authenticator
 * set up, nudged to set one up when they don't, and, once MFA_ENFORCE is on,
 * not let through without it (the API refuses with code mfa_required too). */
export function MfaGate({ children }: { children: ReactElement }) {
  const { user, refresh } = useAuth();
  const needed = Boolean(user?.mfa_required && !user.mfa_passed);
  const [factorId, setFactorId] = useState<string | null | undefined>(needed ? undefined : null);
  const [skip, setSkip] = useState(skipped);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!needed) return;
    // Can't read the factors: fall back to the banner rather than lock an
    // admin out over a network blip (the API still decides).
    verifiedTotpFactorId().then(setFactorId).catch(() => setFactorId(null));
  }, [needed]);

  if (!user || !needed) return children;
  const enforced = user.mfa_enforced;

  if (factorId === undefined) return <p>Checking your sign-in…</p>;

  if (factorId) {
    if (skip && !enforced) return children;
    const submit = async (e: React.FormEvent) => {
      e.preventDefault();
      setBusy(true);
      setError(null);
      try {
        await verifyCode(factorId, code);
        await refresh();
      } catch (err) {
        setError(err instanceof Error ? err.message : "That code didn't work");
        setBusy(false);
      }
    };
    return (
      <div className="auth-card">
        <h1>Enter your code</h1>
        <p className="muted">Admin pages need the 6-digit code from your authenticator app.</p>
        <form onSubmit={submit}>
          {error && <div className="form-error">{error}</div>}
          <Field label="6-digit code">
            <input
              inputMode="numeric"
              autoComplete="one-time-code"
              pattern="[0-9 ]{6,7}"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              autoFocus
              required
            />
          </Field>
          <button className="btn btn-primary" type="submit" disabled={busy || code.replace(/\s+/g, "").length !== 6}>
            Continue
          </button>
          {!enforced && (
            <button
              type="button"
              className="btn"
              style={{ marginLeft: 8 }}
              onClick={() => {
                try {
                  sessionStorage.setItem(SKIP_KEY, "1");
                } catch {
                  /* storage blocked: skip for this page view only */
                }
                setSkip(true);
              }}
            >
              Not now
            </button>
          )}
        </form>
      </div>
    );
  }

  if (enforced) {
    return (
      <div className="auth-card">
        <h1>Set up two-step sign-in</h1>
        <p className="muted">Admin pages now need a code from an authenticator app. It takes a minute.</p>
        <Link className="btn btn-primary" to="/account/security">
          Set it up
        </Link>
      </div>
    );
  }

  return (
    <>
      <div className="form-error" role="status" style={{ margin: "12px 16px 0" }}>
        Admin pages will soon need two-step sign-in.{" "}
        <Link to="/account/security">Set up an authenticator app</Link> before then.
      </div>
      {children}
    </>
  );
}
