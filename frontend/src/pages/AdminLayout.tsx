import { NavLink, Outlet } from "react-router-dom";

/** Shell for the centrally-managed admin tooling - one page with tabs
 * (Newsletters / Scans / Import-export) instead of three separate nav
 * entries, to cut down on nav clutter. Each tab keeps its own full page
 * (header, stat tiles, table) - this just swaps which one is mounted. */
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
      </div>
      <Outlet />
    </div>
  );
}
