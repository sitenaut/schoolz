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
 * click closes, body scroll locks, focus lands inside on open and returns
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
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCloseRef.current();
    };
    document.addEventListener("keydown", onKey);
    const first = panel.current?.querySelector<HTMLElement>("input, select, textarea, button:not(.modal-x)");
    (first ?? panel.current)?.focus();

    // On mobile, `position: fixed` tracks the layout viewport, not the visual
    // one - if the page is even slightly pinch-zoomed the two diverge, and
    // the fixed modal-bg (sized via inset:0 in CSS) can render with its
    // header pushed outside what's actually visible, leaving the close
    // button and backdrop unreachable. Pin the box to window.visualViewport
    // instead whenever it's available, and keep it in sync as the visual
    // viewport moves (zoom, keyboard, address-bar show/hide).
    const vv = window.visualViewport;
    const syncViewport = () => {
      if (!vv || !bg.current) return;
      bg.current.style.top = `${vv.offsetTop}px`;
      bg.current.style.left = `${vv.offsetLeft}px`;
      bg.current.style.right = "auto";
      bg.current.style.bottom = "auto";
      bg.current.style.width = `${vv.width}px`;
      bg.current.style.height = `${vv.height}px`;
    };
    syncViewport();
    vv?.addEventListener("resize", syncViewport);
    vv?.addEventListener("scroll", syncViewport);

    return () => {
      document.removeEventListener("keydown", onKey);
      vv?.removeEventListener("resize", syncViewport);
      vv?.removeEventListener("scroll", syncViewport);
      document.body.style.overflow = prevOverflow;
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
