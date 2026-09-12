import { useEffect, useRef } from "react";
import { NavLink, Link, Outlet, useLocation } from "react-router-dom";
import { AuthPopover } from "./AuthPopover";
import { ThemeToggle } from "./ThemeToggle";
import { useAuth } from "../context/AuthContext";
import { useMySchools } from "../lib/mySchools";
import { IconCalendar, IconHome, IconLunch, IconSchool } from "./icons";
import { getFaro } from "../lib/telemetry";
import { trackEvent } from "../lib/track";

// Route templates for the routes registered in App.tsx - used to keep
// page_view's `route` attribute low-cardinality (a school slug or invite
// token never appears in it) instead of the raw pathname.
const ROUTE_TEMPLATES: [RegExp, string][] = [
  [/^\/schools\/[^/]+$/, "/schools/:schoolId"],
  [/^\/invites\/[^/]+$/, "/invites/:token"],
];

function routeTemplate(pathname: string): string {
  for (const [pattern, template] of ROUTE_TEMPLATES) {
    if (pattern.test(pathname)) return template;
  }
  return pathname;
}

// The ribbon's school filter has no meaning on the centrally-managed admin
// pages (they aren't scoped to "my schools" at all), nor on the contact
// form (not school-specific) - hidden there rather than just visually
// unused clutter.
const NO_SCHOOL_FILTER_PATH_PREFIXES = ["/admin", "/account", "/contact"];
// Table-heavy / settings pages get a wider content column than the feed.
const WIDE_PATH_PREFIXES = ["/admin", "/account"];

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
  const { pathname } = useLocation();
  const hideSchoolFilter = NO_SCHOOL_FILTER_PATH_PREFIXES.some((p) => pathname.startsWith(p));
  const isWide = WIDE_PATH_PREFIXES.some((p) => pathname.startsWith(p));

  const fromRouteRef = useRef<string | undefined>(undefined);
  useEffect(() => {
    const route = routeTemplate(pathname);
    const schoolMatch = pathname.match(/^\/schools\/([^/]+)$/);
    trackEvent("page_view", {
      route,
      ...(fromRouteRef.current ? { from_route: fromRouteRef.current } : {}),
      ...(schoolMatch ? { school_slug: schoolMatch[1] } : {}),
    });
    fromRouteRef.current = route;
  }, [pathname]);

  useEffect(() => {
    const faro = getFaro();
    if (!faro) return;
    faro.api.setSession({
      ...faro.api.getSession(),
      attributes: {
        logged_in: String(!!user),
        is_admin: String(!!user?.is_admin),
        schools_count: String(mySchools.length),
      },
    });
  }, [user, mySchools.length]);

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

      {mySchools.length > 0 && !hideSchoolFilter && (
        <div className="ribbon" role="group" aria-label="Switch schools">
          {mySchools.length > 1 && (
            <button
              className="ribbon-chip all"
              aria-pressed={!isFiltered}
              onClick={() => {
                activateAll();
                trackEvent("school_filter_toggle", { active_count: mySchools.length });
              }}
            >
              All
            </button>
          )}
          {mySchools.map((s) => (
            <button
              className="ribbon-chip"
              style={{ ["--c" as string]: colorFor(s.id) }}
              aria-pressed={isActive(s.id)}
              onClick={() => {
                toggleActive(s);
                trackEvent("school_filter_toggle", { active_count: mySchools.length });
              }}
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
      </nav>
      <main className={`shell-main ${isWide ? "wide" : ""}`}>
        <Outlet />
        <footer className="shell-footer">
          <Link to="/contact">Contact us</Link>
          <Link to="/privacy">Privacy &amp; cookies</Link>
        </footer>
      </main>
    </div>
  );
}
