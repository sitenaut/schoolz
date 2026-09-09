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

export function InviteAcceptPage() {
  const { token } = useParams<{ token: string }>();
  const { user } = useAuth();
  const navigate = useNavigate();
  const [preview, setPreview] = useState<Preview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [accepted, setAccepted] = useState(false);

  useEffect(() => {
    if (!token) return;
    apiFetch(`/invites/${token}`)
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
    const res = await apiFetch(`/invites/${token}/accept`, { method: "POST" });
    if (!res.ok) {
      setError((await res.json()).detail ?? "Could not accept invite");
      return;
    }
    setAccepted(true);
    setTimeout(() => navigate("/children"), 1200);
  };

  return (
    <div style={{ maxWidth: 420, margin: "4rem auto", fontFamily: "sans-serif" }}>
      <h1>Guardian invite</h1>
      {error && <p style={{ color: "crimson" }}>{error}</p>}
      {accepted && <p style={{ color: "green" }}>Accepted! Taking you to your children…</p>}
      {preview && !accepted && (
        <>
          <p>
            <strong>{preview.inviter_username}</strong> has invited you to share access to{" "}
            <strong>
              {preview.student_first_name} {preview.student_last_initial}.
            </strong>
          </p>
          {preview.status !== "pending" ? (
            <p>This invite is {preview.status}.</p>
          ) : user ? (
            <button onClick={accept}>Accept invite</button>
          ) : (
            <p>
              <Link to={`/register?next=/invites/${token}`}>Register</Link> or{" "}
              <Link to={`/login?next=/invites/${token}`}>log in</Link> to accept this invite.
            </p>
          )}
        </>
      )}
    </div>
  );
}
