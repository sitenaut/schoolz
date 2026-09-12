/** The site's real public origin (e.g. "https://schoolz.sitenaut.com"),
 * baked in at build time. Needed because canonical/Open Graph URLs can't
 * just use `window.location.origin`: when the backend's prerender service
 * renders a page for a crawler (services/prerender.py), it loads the page
 * from an internal-only address (http://frontend:3000 locally,
 * http://schoolz-web.internal:3000 in prod) - using that as the canonical
 * URL would point search engines at an address they can't reach. Falls
 * back to the real browser origin when the build arg isn't set, which is
 * still correct for a normal user's browser. */
export const SITE_URL: string = (import.meta.env.VITE_PUBLIC_WEB_URL || (typeof window !== "undefined" ? window.location.origin : "")).replace(
  /\/$/,
  "",
);
