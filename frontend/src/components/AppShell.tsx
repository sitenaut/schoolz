import { NavLink, Link, Outlet } from "react-router-dom";
import { AuthPopover } from "./AuthPopover";
import { ThemeToggle } from "./ThemeToggle";
import { useAuth } from "../context/AuthContext";
import { useMySchools } from "../lib/mySchools";
import { IconCalendar, IconHome, IconJobs, IconLunch, IconNewsletter, IconSchool, IconTransfer } from "./icons";

/** Top bar + school-switcher ribbon + bottom tab bar (mobile) / left rail
 * (desktop). Wraps every public page; the personal/admin pages render
 * inside it too so the nav is never lost.
 *
 * The ribbon lists every school on the visitor's Today feed as a
 * toggleable chip (logo if we have one, else a color dot) plus an "All"
 * chip - tapping a school chip shows/hides just that school's card on
 * Today/Lunch without navigating anywhere, tapping "All" clears the
 * filter. This is the quick cross-page switcher; the "My schools" link
 * still goes to /start to add or remove schools from the list itself. */
export function AppShell() {
  const { user } = useAuth();
  const { mySchools, colorFor, isActive, toggleActive, activateAll, isFiltered } = useMySchools();

  return (
    <div className="shell">
      <header className="shell-top">
        <Link to="/" className="brand">
          schoolz<small>Cherry Hill, NJ</small>
        </Link>
        <div className="spacer" />
        <ThemeToggle />
        <Link to="/start" className="ghost">
          My schools
        </Link>
        {user ? (
          <Link to="/account" className="ghost">
            {user.username}
          </Link>
        ) : (
          <AuthPopover />
        )}
      </header>

      {mySchools.length > 0 && (
        <div className="ribbon" role="group" aria-label="Switch schools">
          {mySchools.length > 1 && (
            <button className="ribbon-chip all" aria-pressed={!isFiltered} onClick={activateAll}>
              All
            </button>
          )}
          {mySchools.map((s) => (
            <button
              className="ribbon-chip"
              style={{ ["--c" as string]: colorFor(s.id) }}
              aria-pressed={isActive(s.id)}
              onClick={() => toggleActive(s)}
              title={s.name}
              key={s.id}
            >
              {s.logo_url ? (
                <img className="avatar" src={s.logo_url} alt="" />
              ) : (
                <span className="dot" style={{ marginLeft: 0, width: 22, height: 22 }} />
              )}
              {s.short_name || s.name}
            </button>
          ))}
          <Link to="/start" className="ribbon-manage" aria-label="Add or remove schools" title="Add or remove schools">
            +
          </Link>
        </div>
      )}

      <nav className="shell-nav" aria-label="Sections">
        <NavLink to="/" end>
          <IconHome />
          Today
        </NavLink>
        <NavLink to="/calendar">
          <IconCalendar />
          Calendar
        </NavLink>
        <NavLink to="/lunch">
          <IconLunch />
          Lunch
        </NavLink>
        <NavLink to="/schools">
          <IconSchool />
          Schools
        </NavLink>
        {user?.is_admin && (
          <>
            <div className="nav-divider" aria-hidden="true">
              Admin
            </div>
            <NavLink to="/smore">
              <IconNewsletter />
              Newsletters
            </NavLink>
            <NavLink to="/jobs">
              <IconJobs />
              Scans
            </NavLink>
            <NavLink to="/admin/config">
              <IconTransfer />
              Import/export
            </NavLink>
          </>
        )}
      </nav>
      <main className="shell-main">
        <Outlet />
        <footer className="shell-footer">
          <Link to="/privacy">Privacy &amp; cookies</Link>
        </footer>
      </main>
    </div>
  );
}
