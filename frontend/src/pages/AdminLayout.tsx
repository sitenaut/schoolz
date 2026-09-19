import { NavLink, Outlet } from "react-router-dom";

/** Shell for the centrally-managed admin tooling - one page with tabs
 * (Newsletters / Scans / Import-export / Kids) instead of separate nav
 * entries, to cut down on nav clutter. Each tab keeps its own full page
 * (header, stat tiles, table) - this just swaps which one is mounted.
 *
 * Kids reuses the old guardian-facing /kids page verbatim rather than a
 * separate admin view of it - it dropped off the main nav (renamed/
 * repointed to the Focus app) but stays reachable here since it's still
 * a real page with real ideas worth revisiting later. */
export function AdminLayout() {
  return (
    <div>
      <div className="tabs" role="tablist" style={{ marginBottom: 20 }}>
        <NavLink to="/admin/newsletters" className={({ isActive }) => `tab ${isActive ? "active" : ""}`}>
          Newsletters
        </NavLink>
        <NavLink to="/admin/scans" className={({ isActive }) => `tab ${isActive ? "active" : ""}`}>
          Scans
        </NavLink>
        <NavLink to="/admin/config" className={({ isActive }) => `tab ${isActive ? "active" : ""}`}>
          Import/export
        </NavLink>
        <NavLink to="/admin/kids" className={({ isActive }) => `tab ${isActive ? "active" : ""}`}>
          Kids
        </NavLink>
      </div>
      <Outlet />
    </div>
  );
}
