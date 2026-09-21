// An invite the visitor opened before they had an account. Auth in prod
// round-trips through Google or an email-confirmation link, and both land
// back on the app with whatever URL Supabase was told to return to - or the
// bare Site URL when it wasn't told at all. Keeping the invite here means
// the app can pick it back up after that round-trip regardless of where it
// landed, or even if they finish signing up in a different tab a day later.

export type InviteKind = "guardian" | "student";

export type PendingInvite = { kind: InviteKind; token: string };

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
      return { kind: parsed.kind, token: parsed.token };
    }
    return null;
  } catch {
    return null;
  }
}

export function clearPendingInvite(): void {
  try {
    localStorage.removeItem(KEY);
  } catch {
    // ignore
  }
}
