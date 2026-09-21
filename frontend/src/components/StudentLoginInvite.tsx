import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "../api";
import { InviteShare } from "./InviteShare";

type StudentAccountStatus = { has_account: boolean; account_email: string | null; pending_invite_email: string | null };

/** Guardian-only: give the child their own schoolz login (routers/
 * student_accounts.py). Shown wherever a guardian manages a child, always
 * in the open - it used to live inside a collapsed accordion on the Kids
 * page, which in practice meant nobody could find it. */
export function StudentLoginInvite({ studentId, firstName }: { studentId: string; firstName: string }) {
  const [status, setStatus] = useState<StudentAccountStatus | null>(null);
  const [email, setEmail] = useState("");
  const [invite, setInvite] = useState<{ link: string; email: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const res = await apiFetch(`/students/${studentId}/student-account`);
    setStatus(res.ok ? await res.json() : null);
  }, [studentId]);

  useEffect(() => {
    void load();
  }, [load]);

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const res = await apiFetch(`/students/${studentId}/account-invites`, { method: "POST", body: JSON.stringify({ invitee_email: email }) });
      const body = await res.json();
      if (!res.ok) {
        setError(typeof body.detail === "string" ? body.detail : "Could not create invite");
        return;
      }
      setInvite({ link: body.accept_url, email: body.invitee_email });
      setEmail("");
      await load();
    } finally {
      setBusy(false);
    }
  };

  const revoke = async () => {
    if (!confirm(`Remove ${firstName}'s own login? Their account stays, it just stops showing this data.`)) return;
    await apiFetch(`/students/${studentId}/student-account`, { method: "DELETE" });
    setInvite(null);
    await load();
  };

  if (!status) return null;

  if (status.has_account) {
    return (
      <p style={{ margin: 0 }}>
        {firstName} logs in as <strong>{status.account_email}</strong> and sees this same view.{" "}
        <button type="button" className="btn sm" onClick={revoke}>
          Remove their login
        </button>
      </p>
    );
  }

  if (invite) {
    return (
      <div>
        <p style={{ marginTop: 0 }}>
          Send {firstName} this link. They must sign in with <strong>{invite.email}</strong>.
        </p>
        <InviteShare
          link={invite.link}
          email={invite.email}
          subject={`Your schoolz login, ${firstName}`}
          body={`Hi ${firstName} - I set up a schoolz login for you so you can see your own schedule, assignments and grades. Open this link and sign in with this email address:`}
        />
        <button type="button" className="btn sm" style={{ marginTop: 8 }} onClick={() => setInvite(null)}>
          Done
        </button>
      </div>
    );
  }

  return (
    <form onSubmit={create} style={{ margin: 0 }}>
      <label style={{ marginBottom: 0 }}>
        {firstName}'s email address
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <input type="email" placeholder="the email they'll sign in with" value={email} onChange={(e) => setEmail(e.target.value)} required style={{ marginTop: 0 }} />
          <button type="submit" className="btn btn-primary" style={{ flex: "none" }} disabled={busy}>
            {busy ? "Creating…" : "Create invite"}
          </button>
        </div>
      </label>
      <p className="note" style={{ marginBottom: 0 }}>
        They'll sign in with this exact address, so pick the one they actually use.
        {status.pending_invite_email && ` An invite for ${status.pending_invite_email} is already out - a new one replaces it.`}
      </p>
      {error && <div className="banner bad" style={{ marginTop: 10 }}>{error}</div>}
    </form>
  );
}
