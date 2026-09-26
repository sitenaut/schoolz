import { useEffect, useLayoutEffect, useRef } from "react";
import { NavLink, Link, Outlet, useLocation, useNavigate } from "react-router-dom";
import { AuthPopover } from "./AuthPopover";
import { ChatWidget } from "./ChatWidget";
import { ThemeToggle } from "./ThemeToggle";
import { useAuth } from "../context/AuthContext";
import { logoClass } from "../lib/logos";
import { RIBBON_CHANGE_EVENT, useMySchools } from "../lib/mySchools";
import { IconBell, IconCalendar, IconDirectory, IconHome, IconInbox, IconLunch, IconPin, IconSchool, IconUsers, IconWrench } from "./icons";
import { useUnreadInbox, useUnreadNotifications } from "../lib/notifications";
import { getFaro } from "../lib/telemetry";
import { trackEvent } from "../lib/track";
import { countVisit, visitSource } from "../lib/visits";
import { invitePath, loadPendingInvite } from "../lib/pendingInvite";

// Route templates for the routes registered in App.tsx - used to keep
// page_view's `route` attribute low-cardinality (a school slug or invite
// token never appears in it) instead of the raw pathname.
const ROUTE_TEMPLATES: [RegExp, string][] = [
  [/^\/schools\/[^/]+\/class-of-\d+$/, "/schools/:schoolId/class-of-:gradYear"],
  [/^\/schools\/[^/]+$/, "/schools/:schoolId"],
  [/^\/invites\/[^/]+$/, "/invites/:token"],
  [/^\/student-invites\/[^/]+$/, "/student-invites/:token"],
];

let resumedInviteToken: string | null = null;

function routeTemplate(pathname: string): string {
  for (const [pattern, template] of ROUTE_TEMPLATES) {
    if (pattern.test(pathname)) return template;
  }
  return pathname;
}

// The ribbon's school filter has no meaning on the centrally-managed admin
// pages (they aren't scoped to "my schools" at all), nor on the contact
// form, the survey, or the /chcomms write-up (none are school-specific) -
// hidden there rather than just visually unused clutter.
// /directory is school-scoped, but through its own in-page school picker
// (it searches the whole district by default, which the ribbon filter
// would silently contradict).
const NO_SCHOOL_FILTER_PATH_PREFIXES = ["/admin", "/account", "/contact", "/survey", "/chcomms", "/kids", "/directory", "/local"];
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
  const { user, loading: authLoading, authTimedOut } = useAuth();
  const unreadNotifications = useUnreadNotifications(!!user);
  const unreadInbox = useUnreadInbox(!!user?.is_admin);
  const { mySchools, colorFor, isActive, toggleActive, activateAll, isFiltered } = useMySchools();
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const hideSchoolFilter = NO_SCHOOL_FILTER_PATH_PREFIXES.some((p) => pathname.startsWith(p));
  // Calendar only, by explicit product call. That page auto-scrolls ~3000px
  // to today's entry, which parks its "Only <school>" bar off the top of the
  // document - so there the ribbon stacks under the header and the bar under
  // the ribbon. Everywhere else the ribbon keeps its original top:0, where it
  // tucks under the header once the page moves: less pinned chrome on a phone
  // on pages that don't need a second bar.
  const stickyRibbon = pathname === "/calendar";

  // Both sticky bars stack at the top of the viewport, and anything a page
  // wants to pin under them (Calendar's "Only <school>" bar) needs to know
  // how tall that stack is. Measured, not hardcoded: the header's height
  // depends on the font and the viewport, and the one place that guessed it
  // (.shell-nav's `top: 57px`) was 3px off the real 53.84px - enough to
  // show a sliver of scrolling content through the gap. --ribbon-h is 0
  // when the ribbon isn't rendered at all, so the stack collapses cleanly.
  // useLayoutEffect, not useEffect: the vars have to be on :root before the
  // browser paints, or the first frame pins anything downstream at the
  // fallback offset and it visibly jumps into place.
  const headerRef = useRef<HTMLElement | null>(null);
  const ribbonRef = useRef<HTMLDivElement | null>(null);
  useLayoutEffect(() => {
    const root = document.documentElement;
    const measure = () => {
      root.style.setProperty("--header-h", `${headerRef.current?.offsetHeight ?? 54}px`);
      // 0 unless the ribbon is actually stacked below the header - the var
      // means "how much pinned chrome is above me", and an unstacked ribbon
      // sits under the header rather than adding to it.
      root.style.setProperty("--ribbon-h", `${stickyRibbon ? (ribbonRef.current?.offsetHeight ?? 0) : 0}px`);
    };
    measure();
    const ro = new ResizeObserver(measure);
    if (headerRef.current) ro.observe(headerRef.current);
    if (ribbonRef.current) ro.observe(ribbonRef.current);
    return () => ro.disconnect();
  }, [mySchools.length, hideSchoolFilter, stickyRibbon]);

  // An invite opened before signing in is finished the moment a signed-in
  // session shows up, wherever that happens - a Google redirect or an
  // email-confirmation link can land on the site root rather than back on
  // the invite (see lib/pendingInvite.ts). The invite page clears the entry
  // once it is accepted or found dead, so this can't loop.
  // Once per page load per token, so someone who lands on the invite, hits
  // a dead end there and navigates away isn't dragged back to it.
  useEffect(() => {
    if (!user) return;
    const pending = loadPendingInvite();
    if (!pending || resumedInviteToken === pending.token) return;
    resumedInviteToken = pending.token;
    const target = invitePath(pending);
    if (pathname !== target) navigate(target, { replace: true });
  }, [user, pathname, navigate]);
  const isWide = WIDE_PATH_PREFIXES.some((p) => pathname.startsWith(p));

  const fromRouteRef = useRef<string | undefined>(undefined);
  useEffect(() => {
    const route = routeTemplate(pathname);
    const schoolMatch = pathname.match(/^\/schools\/([^/]+)$/);
    trackEvent("page_view", {
      route,
      source: visitSource(),
      ...(fromRouteRef.current ? { from_route: fromRouteRef.current } : {}),
      ...(schoolMatch ? { school_slug: schoolMatch[1] } : {}),
    });
    // Server-side counterpart to the RUM event above: RUM is the richer
    // signal, this is the one that still works behind an ad blocker.
    countVisit(route);
    fromRouteRef.current = route;
  }, [pathname]);

  useEffect(() => {
    const faro = getFaro();
    if (!faro) return;
    faro.api.setSession({
      ...faro.api.getSession(),
      attributes: {
        // logged_in on its own was actively misleading: it is only
        // meaningful once the auth check has finished, so during the exact
        // failure worth catching - a check that never finishes - every
        // signal got tagged logged_in=false. Confirmed on the 2026-09-15
        // stalls, where all 8 RUM exceptions reported false while those
        // same session IDs later reported true. auth_state keeps "haven't
        // found out yet" distinct from "found out: nobody".
        auth_state: authTimedOut ? "timed_out" : authLoading ? "pending" : user ? "authenticated" : "anonymous",
        logged_in: String(!!user),
        is_admin: String(!!user?.is_admin),
        schools_count: String(mySchools.length),
        // Lets every RUM signal (web vitals, errors, the funnel events) be
        // sliced by campaign - "how did the Facebook cohort behave" rather
        // than just "how many arrived".
        source: visitSource(),
      },
    });
  }, [user, authLoading, authTimedOut, mySchools.length]);

  return (
    <div className="shell">
      <header className="shell-top" ref={headerRef}>
        <Link to="/" className="brand">
          schoolz
        </Link>
        <div className="spacer" />
        {unreadNotifications > 0 && (
          <Link
            to="/account/notifications"
            className="btn icon bell"
            title={`${unreadNotifications} new notification${unreadNotifications === 1 ? "" : "s"}`}
            aria-label={`${unreadNotifications} new notification${unreadNotifications === 1 ? "" : "s"}`}
          >
            <IconBell />
            <span className="bell-count">{unreadNotifications > 9 ? "9+" : unreadNotifications}</span>
          </Link>
        )}
        {unreadInbox > 0 && (
          <Link
            to="/admin/inbox"
            className="btn icon bell"
            title={`${unreadInbox} new message${unreadInbox === 1 ? "" : "s"} in the inbox`}
            aria-label={`${unreadInbox} new message${unreadInbox === 1 ? "" : "s"} in the inbox`}
          >
            <IconInbox />
            <span className="bell-count">{unreadInbox > 9 ? "9+" : unreadInbox}</span>
          </Link>
        )}
        {user?.is_admin && (
          <Link to="/admin" className="btn icon" title="Admin" aria-label="Admin">
            <IconWrench />
          </Link>
        )}
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
        <div className={`ribbon${stickyRibbon ? " ribbon-stacked" : ""}`} role="group" aria-label="Switch schools" ref={ribbonRef}>
          {mySchools.length > 1 && (
            <button
              className="ribbon-chip all"
              aria-pressed={!isFiltered}
              onClick={() => {
                activateAll();
                window.dispatchEvent(new Event(RIBBON_CHANGE_EVENT));
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
                window.dispatchEvent(new Event(RIBBON_CHANGE_EVENT));
                trackEvent("school_filter_toggle", { active_count: mySchools.length });
              }}
              title={s.name}
              key={s.id}
            >
              {s.logo_url ? (
                <img className={logoClass("avatar", s.slug)} src={s.logo_url} alt="" />
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
        <NavLink to="/directory">
          <IconDirectory />
          Directory
        </NavLink>
        {user && (
          // /focus is a separate app (its own Vite build, served from
          // /focus/ - see nginx.conf.template) sharing only this origin's
          // session, not a route in this router - a plain <a> forces the
          // real browser navigation it needs; a <Link>/<NavLink> would try
          // to client-route to a path this SPA has no match for.
          <a href="/focus/">
            <IconUsers />
            Gradez
          </a>
        )}
        {user && (
          <NavLink to="/local">
            <IconPin />
            Local
          </NavLink>
        )}
      </nav>
      <main className={`shell-main ${isWide ? "wide" : ""}`}>
        <Outlet />
        <footer className="shell-footer">
          <Link to="/chcomms">About</Link>
          <Link to="/survey">Survey</Link>
          <Link to="/contact">Contact</Link>
          <Link to="/privacy">Privacy &amp; cookies</Link>
        </footer>
      </main>
      <ChatWidget />
    </div>
  );
}
