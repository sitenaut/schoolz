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

    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
      (opener.current as HTMLElement | null)?.focus?.();
    };
    // Only re-run when the modal opens/closes, not on every re-render that
    // happens to hand in a new onClose closure.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  if (!open) return null;
  return (
    <div className="modal-bg" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
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
