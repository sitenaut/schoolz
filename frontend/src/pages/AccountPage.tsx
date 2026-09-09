import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { APP_VERSION } from "../authConfig";
import { useAuth } from "../context/AuthContext";
import { apiFetch } from "../api";

type Notification = { id: string; type: string; message: string; created_at: string; read_at: string | null };

/** The signed-in user's own page: notifications, the personal layer
 * (children, Gmail), and admin tooling links. Replaces the old dev-style
 * home page - the home page is the Today feed now. */
export function AccountPage() {
  const { user, logout } = useAuth();
  const [notifications, setNotifications] = useState<Notification[]>([]);

  const load = () =>
    apiFetch("/notifications")
      .then((res) => (res.ok ? res.json() : []))
      .then(setNotifications);

  useEffect(() => {
    if (user) load();
  }, [user]);

  const markRead = async (id: string) => {
    await apiFetch(`/notifications/${id}/read`, { method: "POST" });
    load();
  };

  if (!user) return null;
  const unread = notifications.filter((n) => !n.read_at);

  return (
    <>
      <div className="h-row" style={{ marginTop: 0 }}>
        <h2>{user.username}</h2>
        <button onClick={logout}>Log out</button>
      </div>
      <p className="note">{user.email}</p>

      {unread.length > 0 && (
        <>
          <div className="h-row">
            <h2>Notifications</h2>
          </div>
          <div className="list">
            {unread.map((n) => (
              <div className="row" style={{ gridTemplateColumns: "1fr auto" }} key={n.id}>
                <div className="what">{n.message}</div>
                <button className="ghost" onClick={() => markRead(n.id)}>
                  Done
                </button>
              </div>
            ))}
          </div>
        </>
      )}

      <div className="h-row">
        <h2>Your family</h2>
      </div>
      <div className="list docs">
        <Link to="/children">👧 My children</Link>
        <Link to="/start">🏫 Schools on my Today page</Link>
        <Link to="/gmail">✉️ Email scanner (Gmail)</Link>
      </div>

      {user.is_admin && (
        <>
          <div className="h-row">
            <h2>Admin</h2>
          </div>
          <div className="list docs">
            <Link to="/smore">📰 Newsletter sources</Link>
            <Link to="/jobs">⏱ Scheduled fetches</Link>
            <Link to="/schools">🏫 Schools directory</Link>
          </div>
        </>
      )}
      <p className="fine">Build {APP_VERSION}</p>
    </>
  );
}
