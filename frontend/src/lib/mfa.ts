// Two-step sign-in for admins (SZ-18): an authenticator-app (TOTP) factor on
// the Supabase account. The backend asks for an "aal2" session on admin
// endpoints (backend/auth.py:check_admin_mfa); passing a code here upgrades
// the session, and supabase-js announces it through onAuthStateChange
// (MFA_CHALLENGE_VERIFIED), which reloads /auth/me.
//
// Never call these from inside onAuthStateChange (frontend/CLAUDE.md, the
// auth deadlock): they take the same lock.
import { supabase } from "../supabase";

export type Enrollment = { factorId: string; qrCode: string; secret: string };

function client() {
  if (!supabase) throw new Error("Two-step sign-in needs Supabase sign-in");
  return supabase;
}

function fail(error: { message?: string } | null, fallback: string): never {
  throw new Error(error?.message || fallback);
}

/** The verified authenticator-app factor, if the account has one. */
export async function verifiedTotpFactorId(): Promise<string | null> {
  const { data, error } = await client().auth.mfa.listFactors();
  if (error) fail(error, "Could not read your sign-in settings");
  return data.totp[0]?.id ?? null;
}

/** Starts adding an authenticator app: a QR code to scan, and the secret to
 * type in by hand instead. Clears any earlier attempt that was never
 * finished, since Supabase keeps those and refuses a duplicate. */
export async function startEnrollment(): Promise<Enrollment> {
  const auth = client().auth;
  const { data: factors } = await auth.mfa.listFactors();
  for (const f of factors?.all ?? []) {
    if (f.factor_type === "totp" && f.status === "unverified") await auth.mfa.unenroll({ factorId: f.id });
  }
  const { data, error } = await auth.mfa.enroll({ factorType: "totp", friendlyName: "schoolz" });
  if (error || !data) fail(error, "Could not start two-step sign-in");
  return { factorId: data.id, qrCode: data.totp.qr_code, secret: data.totp.secret };
}

/** Checks a 6-digit code against the factor; on success the session is aal2. */
export async function verifyCode(factorId: string, code: string): Promise<void> {
  const { error } = await client().auth.mfa.challengeAndVerify({ factorId, code: code.replace(/\s+/g, "") });
  if (error) fail(error, "That code didn't work");
}

export async function removeFactor(factorId: string): Promise<void> {
  const { error } = await client().auth.mfa.unenroll({ factorId });
  if (error) fail(error, "Could not turn off two-step sign-in");
}
