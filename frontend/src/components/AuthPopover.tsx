import { useEffect, useRef, useState } from "react";
import { AuthPanel } from "./AuthPanel";

/** The "Sign in" button in the top bar opens this instead of navigating
 * to a full page - a small anchored panel, not a page transition, since
 * signing in is meant to be a quick aside, not something that takes you
 * away from whatever you were looking at. */
export function AuthPopover() {
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<"login" | "register">("login");
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div className="authPopoverWrap" ref={ref}>
      <button className="ghost" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        Sign in
      </button>
      {open && (
        <div className="authPopover" role="dialog" aria-label={mode === "login" ? "Sign in" : "Register"}>
          <AuthPanel
            mode={mode}
            onModeChange={setMode}
            // Just close - the whole point of a popover instead of a page
            // is staying right where you were, not being redirected.
            onSuccess={() => setOpen(false)}
          />
        </div>
      )}
    </div>
  );
}
