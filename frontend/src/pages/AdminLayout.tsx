import { NavLink, Navigate, Outlet } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { visibleAdminTabs } from "../lib/permissions";

/** Shell for the centrally-managed admin tooling - one page with tabs
 * instead of separate nav entries, to cut down on nav clutter. Each tab
 * keeps its own full page (header, stat tiles, table) - this just swaps
 * which one is mounted. A scoped admin only sees the tabs their roles
 * grant (the server enforces the same rule); "Users & roles" is super
 * admin only.
 *
 * Kids reuses the old guardian-facing /kids page verbatim rather than a
 * separate admin view of it - it dropped off the main nav (renamed/
 * repointed to the Focus app) but stays reachable here since it's still
 * a real page with real ideas worth revisiting later. */
export function AdminLayout() {
  const { user } = useAuth();
  const tabs = visibleAdminTabs(user);
  return (
    <div>
      <div className="tabs admin-tabs" role="tablist" style={{ marginBottom: 20 }}>
        {tabs.map((t) => (
          <NavLink key={t.to} to={t.to} className={({ isActive }) => `tab ${isActive ? "active" : ""}`}>
            {t.label}
          </NavLink>
        ))}
      </div>
      <Outlet />
    </div>
  );
}

/** /admin lands on the first tab this user can actually open. */
export function AdminIndexRedirect() {
  const { user } = useAuth();
  const first = visibleAdminTabs(user)[0];
  return <Navigate to={first ? first.to : "/"} replace />;
}
