// An invite the visitor opened before they had an account. Auth in prod
// round-trips through Google or an email-confirmation link, and both land
// back on the app with whatever URL Supabase was told to return to - or the
// bare Site URL when it wasn't told at all. Keeping the invite here means
// the app can pick it back up after that round-trip regardless of where it
// landed, or even if they finish signing up in a different tab a day later.

export type InviteKind = "guardian" | "student";

// `refusedFor`: the signed-in account the invite was refused for (a
// student invite opened while a parent is signed in). AppShell doesn't
// send that account back to it on every visit; the link itself still works.
export type PendingInvite = { kind: InviteKind; token: string; refusedFor?: string };

const KEY = "schoolz.pendingInvite";

export function invitePath(invite: PendingInvite): string {
  return invite.kind === "guardian" ? `/invites/${invite.token}` : `/student-invites/${invite.token}`;
}

export function savePendingInvite(invite: PendingInvite): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(invite));
  } catch {
    // Private mode / storage disabled - the URL still carries the token.
  }
}

export function loadPendingInvite(): PendingInvite | null {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<PendingInvite>;
    if ((parsed.kind === "guardian" || parsed.kind === "student") && typeof parsed.token === "string" && parsed.token) {
      return {
        kind: parsed.kind,
        token: parsed.token,
        ...(typeof parsed.refusedFor === "string" ? { refusedFor: parsed.refusedFor } : {}),
      };
    }
    return null;
  } catch {
    return null;
  }
}

export function markPendingInviteRefused(userId: string): void {
  const pending = loadPendingInvite();
  if (pending) savePendingInvite({ ...pending, refusedFor: userId });
}

export function clearPendingInvite(): void {
  try {
    localStorage.removeItem(KEY);
  } catch {
    // ignore
  }
}
