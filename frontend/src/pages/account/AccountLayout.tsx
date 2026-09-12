import { NavLink, Outlet } from "react-router-dom";
import { IconBell, IconSettings, IconShield, IconUser, IconUsers } from "../../components/icons";
import { PageHeader } from "../../components/ui/PageHeader";
import { useAuth } from "../../context/AuthContext";

/** Settings shell: page header + left nav rail (top scroller on mobile) +
 * the active section. Mirrors the Katalyst settings layout - one card per
 * concern, nothing buried in accordions. */
export function AccountLayout() {
  const { user } = useAuth();
  if (!user) return null;

  return (
    <>
      <PageHeader upperTitle="Account" title="Settings" subtitle="Your profile, sign-in security, notifications, and the personal layer of schoolz." />
      <div className="settings">
        <nav className="settings-nav" aria-label="Settings sections">
          <NavLink to="/account" end>
            <IconUser /> Profile
          </NavLink>
          <NavLink to="/account/security">
            <IconShield /> Security
          </NavLink>
          <NavLink to="/account/notifications">
            <IconBell /> Notifications
          </NavLink>
          <NavLink to="/account/family">
            <IconUsers /> Family
          </NavLink>
          {user.is_admin && (
            <>
              <div className="nav-sep" aria-hidden="true" />
              <NavLink to="/account/admin">
                <IconSettings /> Admin
              </NavLink>
            </>
          )}
        </nav>
        <div style={{ minWidth: 0 }}>
          <Outlet />
        </div>
      </div>
    </>
  );
}
