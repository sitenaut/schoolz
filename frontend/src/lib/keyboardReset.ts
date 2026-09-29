import { useEffect } from "react";

/** iOS can leave the layout viewport stuck at its keyboard-open size after a
 * field loses focus or a dialog closes, so every `position: fixed; bottom`
 * element (tab bar, chat button) floats mid-page until something forces a
 * re-layout. A same-position scrollTo does that. */
export function useKeyboardViewportReset() {
  useEffect(() => {
    let timer: number | undefined;
    const nudge = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => window.scrollTo(window.scrollX, window.scrollY), 120);
    };
    const onFocusOut = (e: FocusEvent) => {
      const el = e.target as HTMLElement | null;
      if (el && /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName)) nudge();
    };
    const vv = window.visualViewport;
    let last = vv?.height ?? 0;
    const onResize = () => {
      if (!vv) return;
      if (vv.height > last + 40) nudge();
      last = vv.height;
    };
    document.addEventListener("focusout", onFocusOut);
    vv?.addEventListener("resize", onResize);
    return () => {
      window.clearTimeout(timer);
      document.removeEventListener("focusout", onFocusOut);
      vv?.removeEventListener("resize", onResize);
    };
  }, []);
}
