/** supabase-js builds an error's message from the response body, and when the
 * auth server answers 5xx with nothing parseable (confirmed: its SMTP login to
 * Gmail failing during sign-up returns a bare 500) that message is the literal
 * string "{}" - which is what a person saw in red under the sign-up form. Turn
 * an unreadable message into a sentence; every real message passes through. */
export function friendlyAuthError(err: { message?: string }, fallback: string): string {
  const message = (err.message ?? "").trim();
  return message === "" || message === "{}" || message === "[]" || message === "null" ? fallback : message;
}

export const SIGN_UP_FALLBACK =
  "We couldn't create your account right now - the confirmation email couldn't be sent. Please try again later, or continue with Google.";
export const RESEND_FALLBACK = "We couldn't send the confirmation email right now. Please try again later.";
export const GENERIC_AUTH_FALLBACK = "Something went wrong. Please try again.";
