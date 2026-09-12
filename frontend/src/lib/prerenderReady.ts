import { useEffect } from "react";

/** Flags <body> once a page's own initial data fetch has resolved.
 * backend/services/prerender.py waits on this exact attribute before
 * capturing a page's HTML for a crawler - without it, a bot would be
 * handed a "Loading…" snapshot instead of real content. Static pages with
 * nothing to fetch should call this with `true` on mount. */
export function usePrerenderReady(ready: boolean): void {
  useEffect(() => {
    if (!ready) return;
    document.body.setAttribute("data-prerender-ready", "true");
    return () => {
      document.body.removeAttribute("data-prerender-ready");
    };
  }, [ready]);
}
