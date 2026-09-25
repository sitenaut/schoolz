import { useEffect, useId, useRef, type ReactNode } from "react";
import { IconX } from "../icons";

type Props = {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  subtitle?: ReactNode;
  size?: "md" | "lg" | "xl";
  footer?: ReactNode;
  children: ReactNode;
};

/** Accessible-enough dialog without a dependency: Escape closes, backdrop
 * click closes, body scroll locks (iOS-proof), stays above the on-screen
 * keyboard, focus lands inside on open and returns
 * to the opener on close. Rendered inline (no portal) - z-index stacks it
 * above the shell's sticky bars. */
export function Modal({ open, onClose, title, subtitle, size = "md", footer, children }: Props) {
  const panel = useRef<HTMLDivElement>(null);
  const bg = useRef<HTMLDivElement>(null);
  const opener = useRef<Element | null>(null);
  const titleId = useId();
  const subtitleId = useId();
  // Callers routinely pass an inline onClose (e.g. a closure that also
  // resets form state), which gets a new identity on every parent render -
  // including one triggered by typing into a field inside this modal. Kept
  // in a ref so the effect below doesn't treat that as "close changed" and
  // re-run its open/focus setup mid-keystroke.
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    if (!open) return;
    opener.current = document.activeElement;

    // Scroll lock. overflow:hidden on <body> alone doesn't stop iOS Safari
    // from scrolling the page behind the dialog (a swipe in the chat panel
    // dragged the page along and opened a gap above the keyboard), so pin
    // the body in place at its current offset and restore it on close.
    const body = document.body.style;
    const prevBody = { position: body.position, top: body.top, left: body.left, right: body.right, overflow: body.overflow };
    const scrollY = window.scrollY;
    body.position = "fixed";
    body.top = `-${scrollY}px`;
    body.left = "0";
    body.right = "0";
    body.overflow = "hidden";
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCloseRef.current();
    };
    document.addEventListener("keydown", onKey);
    const first = panel.current?.querySelector<HTMLElement>("input, select, textarea, button:not(.modal-x)");
    (first ?? panel.current)?.focus();

    // On-screen keyboard. iOS doesn't shrink the layout viewport for the
    // keyboard, it covers the bottom of it - and .modal-bg (inset: 0) is
    // sized to the layout viewport, so a bottom sheet's input ended up
    // under the keyboard. Fit the backdrop to the *visible* area,
    // vertically only, and only at scale 1: 068b297 pinned all four edges
    // to visualViewport for pinch-zoom too, and on a zoomed iPhone that put
    // the sheet off-screen with scrolling locked - the tab looked frozen
    // (reverted in 33fe008). Zoomed, this leaves the plain inset: 0 alone.
    const vv = window.visualViewport;
    const fitToKeyboard = () => {
      const el = bg.current;
      if (!vv || !el) return;
      if (Math.abs(vv.scale - 1) > 0.01) {
        el.style.top = el.style.height = el.style.bottom = "";
        return;
      }
      el.style.top = `${Math.max(0, vv.offsetTop)}px`;
      el.style.height = `${vv.height}px`;
      el.style.bottom = "auto";
    };
    fitToKeyboard();
    vv?.addEventListener("resize", fitToKeyboard);
    vv?.addEventListener("scroll", fitToKeyboard);

    return () => {
      document.removeEventListener("keydown", onKey);
      vv?.removeEventListener("resize", fitToKeyboard);
      vv?.removeEventListener("scroll", fitToKeyboard);
      Object.assign(body, prevBody);
      window.scrollTo(0, scrollY);
      (opener.current as HTMLElement | null)?.focus?.();
    };
    // Only re-run when the modal opens/closes, not on every re-render that
    // happens to hand in a new onClose closure.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  if (!open) return null;
  return (
    <div className="modal-bg" ref={bg} onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div
        className={`modal ${size}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={subtitle ? subtitleId : undefined}
        ref={panel}
        tabIndex={-1}
      >
        <div className="modal-hd">
          <div style={{ minWidth: 0 }}>
            <h2 id={titleId}>{title}</h2>
            {subtitle && (
              <div className="sub" id={subtitleId}>
                {subtitle}
              </div>
            )}
          </div>
          <button className="btn icon modal-x" onClick={onClose} aria-label="Close">
            <IconX />
          </button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-ft">{footer}</div>}
      </div>
    </div>
  );
}
