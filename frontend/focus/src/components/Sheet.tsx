import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";

// Below this, a released drag springs back open rather than dismissing -
// a light touch or an accidental brush shouldn't close it.
const DISMISS_THRESHOLD_PX = 90;
// A fast flick that hasn't travelled far yet should still dismiss - this
// is what makes it feel like a real sheet gesture instead of a slow drag
// race. Velocity is measured over roughly the last pointer-move, not the
// whole gesture, so a slow start doesn't cancel out a quick flick at the
// end.
const DISMISS_VELOCITY_PX_MS = 0.6;
// How far back the velocity sample window reaches. A single consecutive
// event-pair delta is fragile: browsers commonly round event timestamps
// (fingerprinting resistance), so two fast-arriving pointermoves can land
// in the same rounded millisecond and report dt=0, silently zeroing the
// velocity signal for a real fast flick. Averaging over a short window
// instead - the oldest sample still inside it to the newest - is the
// standard fix gesture libraries use for exactly this.
const VELOCITY_WINDOW_MS = 80;
// How long the "finish sliding away" animation runs before the sheet
// actually unmounts - matches the CSS transition below. Kept as one
// constant so the two can't drift out of sync.
const CLOSE_ANIMATION_MS = 200;

/** A bottom sheet whose grab handle does what it visually promises:
 * dragging it down dismisses the sheet, the same gesture as a native one
 * (Google/Apple system sheets, Classroom's own panels). Before this, the
 * handle was purely decorative - tapping the backdrop was the only way
 * out, which one real report called out directly: "a little line ... that
 * looks like I could just scroll it down to hide it but that's not what
 * that panel does."
 *
 * Pointer Events (not touch-only), so mouse-drag dismiss works too and
 * this is drivable by Playwright for verification without a real touch
 * device. */
export function Sheet({
  onClose,
  label,
  children,
}: {
  onClose: () => void;
  label: string;
  children: ReactNode;
}) {
  const [dragY, setDragY] = useState(0);
  const [dragging, setDragging] = useState(false);
  const [closing, setClosing] = useState(false);
  const startY = useRef(0);
  const samples = useRef<{ y: number; t: number }[]>([]);
  const sheetHeight = useRef(0);
  const sheetRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const onPointerDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    startY.current = e.clientY;
    samples.current = [{ y: e.clientY, t: e.timeStamp }];
    sheetHeight.current = sheetRef.current?.offsetHeight ?? 0;
    setDragging(true);
    (e.target as Element).setPointerCapture(e.pointerId);
  };

  const onPointerMove = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (!dragging) return;
    const delta = e.clientY - startY.current;
    // Only downward movement drags the sheet; upward clamps to 0 so it
    // can't be dragged past its resting position.
    setDragY(Math.max(0, delta));
    samples.current.push({ y: e.clientY, t: e.timeStamp });
    const cutoff = e.timeStamp - VELOCITY_WINDOW_MS;
    while (samples.current.length > 1 && samples.current[0].t < cutoff) samples.current.shift();
  };

  /** Velocity across the whole retained window, not one event-pair - see
   * VELOCITY_WINDOW_MS. Zero if too little time has elapsed to trust a
   * sample (e.g. a release on the very first move). */
  const releaseVelocity = (): number => {
    const s = samples.current;
    if (s.length < 2) return 0;
    const dt = s[s.length - 1].t - s[0].t;
    return dt > 0 ? (s[s.length - 1].y - s[0].y) / dt : 0;
  };

  const endDrag = () => {
    if (!dragging) return;
    setDragging(false);
    if (dragY > DISMISS_THRESHOLD_PX || releaseVelocity() > DISMISS_VELOCITY_PX_MS) {
      // Finish the gesture rather than teleporting the sheet away: slide
      // the rest of the way off-screen, THEN unmount. A flick released at
      // 20% of the way down should visibly continue, not vanish mid-drag.
      setClosing(true);
      setDragY(Math.max(sheetHeight.current, dragY) + 40);
      window.setTimeout(onClose, CLOSE_ANIMATION_MS);
      return;
    }
    // Released early - spring back open.
    setDragY(0);
  };

  return (
    <div className="sheet-backdrop" onClick={onClose}>
      <div
        ref={sheetRef}
        className={`sheet${closing ? " sheet-closing" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-label={label}
        onClick={(e) => e.stopPropagation()}
        style={{
          transform: dragY ? `translateY(${dragY}px)` : undefined,
          transition: dragging ? "none" : undefined,
        }}
      >
        <div
          className="sheet-grab-zone"
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={endDrag}
          onPointerCancel={endDrag}
        >
          <div className="sheet-grab" aria-hidden="true" />
        </div>
        {children}
      </div>
    </div>
  );
}
