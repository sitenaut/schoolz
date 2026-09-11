type P = { className?: string };
const base = { fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };

export const IconHome = ({ className }: P) => (
  <svg viewBox="0 0 24 24" className={className} {...base} aria-hidden="true">
    <path d="M3 11 12 3l9 8" />
    <path d="M5 10v10h14V10" />
  </svg>
);
export const IconCalendar = ({ className }: P) => (
  <svg viewBox="0 0 24 24" className={className} {...base} aria-hidden="true">
    <rect x="3" y="5" width="18" height="16" rx="2" />
    <path d="M3 10h18M8 3v4M16 3v4" />
  </svg>
);
export const IconLunch = ({ className }: P) => (
  <svg viewBox="0 0 24 24" className={className} {...base} aria-hidden="true">
    <path d="M4 3v8a3 3 0 0 0 6 0V3M7 3v18M17 3c-2 2-3 5-3 8h3v10" />
  </svg>
);
export const IconSchool = ({ className }: P) => (
  <svg viewBox="0 0 24 24" className={className} {...base} aria-hidden="true">
    <path d="M3 21h18M5 21V8l7-5 7 5v13" />
    <path d="M10 21v-6h4v6" />
  </svg>
);
export const IconMail = ({ className }: P) => (
  <svg viewBox="0 0 24 24" className={className} {...base} aria-hidden="true">
    <path d="M4 4h16v16H4z" />
    <path d="m4 7 8 6 8-6" />
  </svg>
);
export const IconPhone = ({ className }: P) => (
  <svg viewBox="0 0 24 24" className={className} {...base} aria-hidden="true">
    <path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1.9.4 1.8.7 2.6a2 2 0 0 1-.5 2.1L8.1 9.7a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.8.3 1.7.5 2.6.7a2 2 0 0 1 1.7 2z" />
  </svg>
);
export const IconSearch = ({ className }: P) => (
  <svg viewBox="0 0 24 24" className={className} {...base} aria-hidden="true">
    <circle cx="11" cy="11" r="7" />
    <path d="m20 20-3.5-3.5" />
  </svg>
);
export const IconSun = ({ className }: P) => (
  <svg viewBox="0 0 24 24" className={className} {...base} aria-hidden="true">
    <circle cx="12" cy="12" r="4" />
    <path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1" />
  </svg>
);
export const IconMoon = ({ className }: P) => (
  <svg viewBox="0 0 24 24" className={className} {...base} aria-hidden="true">
    <path d="M20 14.5A8.5 8.5 0 1 1 9.5 4a7 7 0 0 0 10.5 10.5z" />
  </svg>
);
export const IconAuto = ({ className }: P) => (
  <svg viewBox="0 0 24 24" className={className} {...base} aria-hidden="true">
    <circle cx="12" cy="12" r="9" />
    <path d="M12 3a9 9 0 0 0 0 18z" fill="currentColor" stroke="none" />
  </svg>
);
export const IconNewsletter = ({ className }: P) => (
  <svg viewBox="0 0 24 24" className={className} {...base} aria-hidden="true">
    <rect x="3" y="4" width="18" height="16" rx="2" />
    <path d="M3 7l9 6 9-6" />
  </svg>
);
export const IconJobs = ({ className }: P) => (
  <svg viewBox="0 0 24 24" className={className} {...base} aria-hidden="true">
    <circle cx="12" cy="12" r="9" />
    <path d="M12 7v5l3 3" />
  </svg>
);
export const IconTransfer = ({ className }: P) => (
  <svg viewBox="0 0 24 24" className={className} {...base} aria-hidden="true">
    <path d="M4 7h13M4 7l4-4M4 7l4 4" />
    <path d="M20 17H7M20 17l-4 4M20 17l-4-4" />
  </svg>
);
// Pagination (calendar month/year nav) and "back"/"forward" breadcrumb-style
// links all use these two instead of raw &larr;/&rarr; text glyphs - a
// glyph's color comes from the browser's default button/link text color
// unless something overrides it (the calendar nav buttons never did,
// which is why they read as black-on-dark-gray in dark mode); an
// stroke="currentColor" SVG always follows whatever color the
// surrounding element already resolves to.
export const IconChevronLeft = ({ className }: P) => (
  <svg viewBox="0 0 24 24" className={className} {...base} aria-hidden="true">
    <path d="M15 5 8 12l7 7" />
  </svg>
);
export const IconChevronRight = ({ className }: P) => (
  <svg viewBox="0 0 24 24" className={className} {...base} aria-hidden="true">
    <path d="M9 5l7 7-7 7" />
  </svg>
);
export const IconX = ({ className }: P) => (
  <svg viewBox="0 0 24 24" className={className} {...base} aria-hidden="true">
    <path d="M6 6l12 12M18 6 6 18" />
  </svg>
);
export const IconPlay = ({ className }: P) => (
  <svg viewBox="0 0 24 24" className={className} {...base} aria-hidden="true">
    <path d="M7 4v16l13-8z" />
  </svg>
);
export const IconEdit = ({ className }: P) => (
  <svg viewBox="0 0 24 24" className={className} {...base} aria-hidden="true">
    <path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z" />
  </svg>
);
export const IconTrash = ({ className }: P) => (
  <svg viewBox="0 0 24 24" className={className} {...base} aria-hidden="true">
    <path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14M10 10v7M14 10v7" />
  </svg>
);
export const IconRefresh = ({ className }: P) => (
  <svg viewBox="0 0 24 24" className={className} {...base} aria-hidden="true">
    <path d="M21 12a9 9 0 1 1-2.6-6.4" />
    <path d="M21 3v6h-6" />
  </svg>
);
export const IconInfo = ({ className }: P) => (
  <svg viewBox="0 0 24 24" className={className} {...base} aria-hidden="true">
    <circle cx="12" cy="12" r="9" />
    <path d="M12 11v5M12 8h.01" />
  </svg>
);
export const IconPlus = ({ className }: P) => (
  <svg viewBox="0 0 24 24" className={className} {...base} aria-hidden="true">
    <path d="M12 5v14M5 12h14" />
  </svg>
);
export const IconUser = ({ className }: P) => (
  <svg viewBox="0 0 24 24" className={className} {...base} aria-hidden="true">
    <circle cx="12" cy="8" r="4" />
    <path d="M4 21a8 8 0 0 1 16 0" />
  </svg>
);
export const IconShield = ({ className }: P) => (
  <svg viewBox="0 0 24 24" className={className} {...base} aria-hidden="true">
    <path d="M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6z" />
    <path d="m9 12 2 2 4-4" />
  </svg>
);
export const IconBell = ({ className }: P) => (
  <svg viewBox="0 0 24 24" className={className} {...base} aria-hidden="true">
    <path d="M6 16V11a6 6 0 0 1 12 0v5l2 2H4z" />
    <path d="M10 20a2 2 0 0 0 4 0" />
  </svg>
);
export const IconUsers = ({ className }: P) => (
  <svg viewBox="0 0 24 24" className={className} {...base} aria-hidden="true">
    <circle cx="9" cy="8" r="3.5" />
    <path d="M2.5 20a6.5 6.5 0 0 1 13 0M16 4.5a3.5 3.5 0 0 1 0 7M21.5 20a6.5 6.5 0 0 0-5-6.3" />
  </svg>
);
export const IconSettings = ({ className }: P) => (
  <svg viewBox="0 0 24 24" className={className} {...base} aria-hidden="true">
    <circle cx="12" cy="12" r="3" />
    <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" />
  </svg>
);
export const IconLock = ({ className }: P) => (
  <svg viewBox="0 0 24 24" className={className} {...base} aria-hidden="true">
    <rect x="4" y="11" width="16" height="10" rx="2" />
    <path d="M8 11V7a4 4 0 0 1 8 0v4" />
  </svg>
);
export const IconAlert = ({ className }: P) => (
  <svg viewBox="0 0 24 24" className={className} {...base} aria-hidden="true">
    <path d="M12 3 2 20h20z" />
    <path d="M12 10v4M12 17h.01" />
  </svg>
);
export const IconCheck = ({ className }: P) => (
  <svg viewBox="0 0 24 24" className={className} {...base} aria-hidden="true">
    <path d="m5 12 4 4L19 6" />
  </svg>
);
export const IconClock = ({ className }: P) => (
  <svg viewBox="0 0 24 24" className={className} {...base} aria-hidden="true">
    <circle cx="12" cy="12" r="9" />
    <path d="M12 7v5l3 2" />
  </svg>
);
export const IconLogout = ({ className }: P) => (
  <svg viewBox="0 0 24 24" className={className} {...base} aria-hidden="true">
    <path d="M10 4H5v16h5M14 8l4 4-4 4M18 12H9" />
  </svg>
);
export const IconImage = ({ className }: P) => (
  <svg viewBox="0 0 24 24" className={className} {...base} aria-hidden="true">
    <rect x="3" y="4" width="18" height="16" rx="2" />
    <circle cx="9" cy="10" r="1.5" />
    <path d="m4 18 5-5 3 3 4-4 4 4" />
  </svg>
);
export const IconLink = ({ className }: P) => (
  <svg viewBox="0 0 24 24" className={className} {...base} aria-hidden="true">
    <path d="M9 15l6-6M8 12l-3 3a3 3 0 0 0 4 4l3-3M16 12l3-3a3 3 0 0 0-4-4l-3 3" />
  </svg>
);
export const IconRefreshCw = ({ className }: P) => (
  <svg viewBox="0 0 24 24" className={className} {...base} aria-hidden="true">
    <path d="M4 4v6h6M20 20v-6h-6" />
    <path d="M4.5 15a8 8 0 0 0 14.4 3M19.5 9A8 8 0 0 0 5.1 6" />
  </svg>
);
