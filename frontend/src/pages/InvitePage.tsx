import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { apiFetch } from "../api";
import { AuthPanel } from "../components/AuthPanel";
import { useAuth } from "../context/AuthContext";
import { clearPendingInvite, invitePath, savePendingInvite, type InviteKind } from "../lib/pendingInvite";

type Preview = {
  student_first_name: string;
  student_last_initial: string;
  inviter_username: string;
  status: string;
  expires_at: string;
};

type Phase =
  | { kind: "loading" }
  | { kind: "unavailable"; message: string }
  | { kind: "needs_account" }
  | { kind: "accepting" }
  | { kind: "wrong_account"; message: string }
  | { kind: "failed"; message: string }
  | { kind: "done"; studentId: string | null };

const ENDPOINTS: Record<InviteKind, { preview: (t: string) => string; accept: (t: string) => string }> = {
  guardian: { preview: (t) => `/invites/${t}`, accept: (t) => `/invites/${t}/accept` },
  student: { preview: (t) => `/student-account-invites/${t}`, accept: (t) => `/student-account-invites/${t}/accept` },
};

/** Where an invite link lands, for both kinds of invite.
 *
 * The whole job of this page is that the person never has to work out what
 * to do next. Signed out, the sign-in form is embedded right here (not a
 * link to /register), and the return path is threaded through Google and
 * the email-confirmation link so they come back to this exact URL. Signed
 * in, the invite is accepted on sight - clicking the link was the decision,
 * and the backend is what enforces who may accept. The token is also kept
 * in localStorage from the moment the page is opened, so the app can bring
 * them back even when a redirect lands somewhere else. */
export function InvitePage({ kind }: { kind: InviteKind }) {
  const { token = "" } = useParams<{ token: string }>();
  const { user, loading, refresh, logout } = useAuth();
  const navigate = useNavigate();
  const [preview, setPreview] = useState<Preview | null>(null);
  const [phase, setPhase] = useState<Phase>({ kind: "loading" });
  const [mode, setMode] = useState<"login" | "register">("register");
  const attempted = useRef(false);

  const path = invitePath({ kind, token });

  useEffect(() => {
    if (!token) return;
    apiFetch(ENDPOINTS[kind].preview(token))
      .then(async (res) => {
        if (!res.ok) {
          clearPendingInvite();
          setPhase({ kind: "unavailable", message: (await res.json()).detail ?? "This invite link isn't valid." });
          return;
        }
        const data: Preview = await res.json();
        setPreview(data);
        if (data.status !== "pending") {
          clearPendingInvite();
          setPhase({ kind: "unavailable", message: `This invite has ${data.status === "accepted" ? "already been used" : data.status}.` });
          return;
        }
        savePendingInvite({ kind, token });
        setPhase({ kind: "needs_account" });
      })
      .catch(() => setPhase({ kind: "unavailable", message: "Could not reach schoolz. Try again in a moment." }));
  }, [kind, token]);

  useEffect(() => {
    if (loading || !user || !preview || preview.status !== "pending" || attempted.current) return;
    attempted.current = true;
    setPhase({ kind: "accepting" });
    void (async () => {
      let res: Response;
      try {
        res = await apiFetch(ENDPOINTS[kind].accept(token), { method: "POST" });
      } catch {
        attempted.current = false;
        setPhase({ kind: "failed", message: "Could not reach schoolz. Try again in a moment." });
        return;
      }
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        const message = typeof body.detail === "string" ? body.detail : "Could not accept this invite.";
        // 403 is the one recoverable failure: right person, wrong login.
        // Anything else won't change on retry, so stop remembering it.
        if (res.status === 403) {
          setPhase({ kind: "wrong_account", message });
        } else {
          clearPendingInvite();
          setPhase({ kind: "failed", message });
        }
        return;
      }
      clearPendingInvite();
      if (kind === "student") await refresh();
      setPhase({ kind: "done", studentId: kind === "guardian" && typeof body.id === "string" ? body.id : null });
    })();
  }, [loading, user, preview, kind, token, refresh]);

  const switchAccount = async () => {
    attempted.current = false;
    await logout();
    setMode("login");
    setPhase({ kind: "needs_account" });
  };

  const kidName = preview ? `${preview.student_first_name} ${preview.student_last_initial}.` : "";

  return (
    <div className="page page-narrow">
      {phase.kind === "loading" && <p>Loading…</p>}

      {phase.kind === "unavailable" && (
        <div className="card">
          <h1 style={{ marginTop: 0 }}>Invite not available</h1>
          <p style={{ marginBottom: 0 }}>{phase.message} Ask whoever sent it to create a new one.</p>
        </div>
      )}

      {preview && phase.kind !== "unavailable" && phase.kind !== "done" && (
        <div className="card">
          <p className="eyebrow">{kind === "guardian" ? "Guardian invite" : "Your schoolz login"}</p>
          <h1 style={{ margin: "4px 0 8px" }}>
            {kind === "guardian" ? (
              <>
                {preview.inviter_username} invited you to follow <span style={{ whiteSpace: "nowrap" }}>{kidName}</span>
              </>
            ) : (
              <>
                {preview.inviter_username} set up a login for <span style={{ whiteSpace: "nowrap" }}>{kidName}</span>
              </>
            )}
          </h1>
          <p className="note" style={{ margin: 0 }}>
            {kind === "guardian"
              ? "Once you accept, this child appears on your schoolz account - schedule, assignments, and grades, the same view the person who invited you sees."
              : "Accepting makes this your own login: you'll see your schedule, assignments, and grades - the same view your family sees."}
          </p>
        </div>
      )}

      {phase.kind === "needs_account" && !user && (
        <div className="card">
          <h2 style={{ marginTop: 0 }}>First, a schoolz account</h2>
          <p className="note">
            {kind === "student"
              ? "Use the email address this invite was sent to. Google is quickest if that's a Google address."
              : "New here? Google is quickest. Already have an account? Sign in and the invite finishes on its own."}
          </p>
          <AuthPanel mode={mode} onModeChange={setMode} returnTo={path} />
        </div>
      )}

      {phase.kind === "accepting" && <p>Signed in as {user?.email}. Setting things up…</p>}

      {phase.kind === "wrong_account" && (
        <div className="card">
          <h2 style={{ marginTop: 0 }}>Wrong account for this invite</h2>
          <p>{phase.message}</p>
          <p className="note">You're signed in as {user?.email}.</p>
          <button className="btn btn-primary" onClick={switchAccount}>
            Sign out and use a different account
          </button>
        </div>
      )}

      {phase.kind === "failed" && (
        <div className="card">
          <div className="banner bad">{phase.message}</div>
          <button
            className="btn"
            onClick={() => {
              attempted.current = false;
              setPhase({ kind: "needs_account" });
            }}
          >
            Try again
          </button>
        </div>
      )}

      {phase.kind === "done" && (
        <div className="card">
          <p className="eyebrow">All set</p>
          <h1 style={{ margin: "4px 0 8px" }}>
            {kind === "guardian" ? `${preview?.student_first_name} is on your account` : `You're in, ${preview?.student_first_name}`}
          </h1>
          <p className="note">
            {kind === "guardian"
              ? "Nothing else to fill in - the record is shared with the person who invited you."
              : "Your family can see the same things you can. Nothing here is hidden from them."}
          </p>
          <button
            className="btn btn-primary"
            onClick={() => navigate(phase.studentId ? `/kids/${phase.studentId}` : "/kids", { replace: true })}
          >
            {kind === "guardian" ? `Open ${preview?.student_first_name}'s page` : "Open my schoolz"}
          </button>
        </div>
      )}
    </div>
  );
}
