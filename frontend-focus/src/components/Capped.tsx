import { useState, type ReactNode } from "react";

/** A list with a hard boundary.
 *
 * Shows `cap` items and then a deliberate barrier - a button that names
 * how many are behind it - instead of scrolling on. The point is the
 * boundary itself: a list of four things is finishable, a list that keeps
 * going is not, and for an ADHD brain that difference decides whether the
 * screen gets engaged with or shut. Pressing the barrier reveals one more
 * cap's worth, never everything, so the boundary is redrawn rather than
 * removed. */
export function Capped<T>({
  items,
  cap,
  noun,
  children,
}: {
  items: T[];
  cap: number;
  noun: string;
  children: (visible: T[]) => ReactNode;
}) {
  const [shown, setShown] = useState(cap);
  const visible = items.slice(0, shown);
  const hidden = items.length - visible.length;
  // Deliberately no "(N left)" on the button: announcing the size of what's
  // behind the barrier is the wall the barrier exists to hide.
  const expanded = shown > cap;
  return (
    <>
      {children(visible)}
      {(hidden > 0 || expanded) && (
        <div className="barrier">
          {hidden > 0 && (
            <button type="button" className="show-more" onClick={() => setShown((s) => s + cap)}>
              Show {Math.min(hidden, cap)} more {noun}
            </button>
          )}
          {expanded && (
            // Snaps straight back to the cap rather than stepping down, so
            // one press restores the small list she started with.
            <button type="button" className="show-more fewer" onClick={() => setShown(cap)}>
              Show fewer
            </button>
          )}
        </div>
      )}
    </>
  );
}
