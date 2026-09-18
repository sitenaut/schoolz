import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { apiFetch } from "../api";
import { useAuth } from "../context/AuthContext";

type Preview = {
  student_first_name: string;
  student_last_initial: string;
  inviter_username: string;
  status: string;
  expires_at: string;
};

// A guardian's invite for a student to log in as themselves. Same shape as
// InviteAcceptPage (register/login round-trips via ?next=), but accepting
// makes this login *be* the student rather than another guardian.
export function StudentInviteAcceptPage() {
  const { token } = useParams<{ token: string }>();
  const { user, refresh } = useAuth();
  const navigate = useNavigate();
  const [preview, setPreview] = useState<Preview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [accepting, setAccepting] = useState(false);

  useEffect(() => {
    if (!token) return;
    apiFetch(`/student-account-invites/${token}`)
      .then(async (res) => {
        if (!res.ok) {
          setError((await res.json()).detail ?? "Invite not found");
          return;
        }
        setPreview(await res.json());
      })
      .catch(() => setError("Could not reach the backend"));
  }, [token]);

  const accept = async () => {
    setError(null);
    setAccepting(true);
    try {
      const res = await apiFetch(`/student-account-invites/${token}/accept`, { method: "POST" });
      if (!res.ok) {
        setError((await res.json()).detail ?? "Could not accept invite");
        return;
      }
      await refresh();
      navigate("/kids", { replace: true });
    } finally {
      setAccepting(false);
    }
  };

  const next = `/student-invites/${token}`;

  return (
    <div className="page page-narrow">
      <h1>Your schoolz login</h1>
      {error && <p style={{ color: "crimson" }}>{error}</p>}
      {preview && (
        <>
          <p>
            <strong>{preview.inviter_username}</strong> set up a schoolz login for{" "}
            <strong>
              {preview.student_first_name} {preview.student_last_initial}.
            </strong>{" "}
            You'll see your schedule, assignments, and grades — the same view your family sees.
          </p>
          {preview.status !== "pending" ? (
            <p>This invite is {preview.status}.</p>
          ) : user ? (
            <>
              <p style={{ color: "#666" }}>Signed in as {user.email}.</p>
              <button onClick={accept} disabled={accepting}>
                {accepting ? "Setting up…" : "This is me — continue"}
              </button>
            </>
          ) : (
            <p>
              <Link to={`/register?next=${encodeURIComponent(next)}`}>Create your account</Link> or{" "}
              <Link to={`/login?next=${encodeURIComponent(next)}`}>sign in</Link> with the email this invite was sent
              to.
            </p>
          )}
        </>
      )}
    </div>
  );
}
