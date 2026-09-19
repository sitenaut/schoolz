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
 * A drag started anywhere on the card (not just the handle) also
 * participates, decided once at the moment the finger touches down: if
 * the card is already scrolled to the top, that drag can dismiss, same
 * as the handle; otherwise it's left entirely to native scrolling for the
 * whole gesture. (An earlier version tried to hand off mid-gesture by
 * re-checking scroll position on every move and cancelling a scroll
 * already in progress - that broke page scrolling, and even Chrome's own
 * pull-to-refresh, outliving the sheet itself. Deciding once at the start
 * avoids ever cancelling a scroll the browser has already committed to.)
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
  // Which pointer is mid-gesture on the card body, so a second finger (or
  // a stray event from a pointer we already let go of) can't be mistaken
  // for the one being tracked.
  const activePointerId = useRef<number | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const beginDrag = (clientY: number, timeStamp: number) => {
    startY.current = clientY;
    samples.current = [{ y: clientY, t: timeStamp }];
    sheetHeight.current = sheetRef.current?.offsetHeight ?? 0;
    setDragging(true);
  };

  const trackDrag = (clientY: number, timeStamp: number) => {
    const delta = clientY - startY.current;
    // Only downward movement drags the sheet; upward clamps to 0 so it
    // can't be dragged past its resting position.
    setDragY(Math.max(0, delta));
    samples.current.push({ y: clientY, t: timeStamp });
    const cutoff = timeStamp - VELOCITY_WINDOW_MS;
    while (samples.current.length > 1 && samples.current[0].t < cutoff) samples.current.shift();
  };

  // The handle's own gesture is fully separate from the card-level
  // scroll-then-drag handoff below - it always drags, never scrolls (there's
  // nothing to scroll in a 4px strip). Stopped from bubbling so the two
  // sets of handlers never both process the same pointer sequence: without
  // this, a handle drag also re-enters onCardPointerMove/onCardPointerEnd
  // via bubbling and runs endDrag's dismiss logic (and onClose) twice.
  const onPointerDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    e.stopPropagation();
    beginDrag(e.clientY, e.timeStamp);
    (e.target as Element).setPointerCapture(e.pointerId);
  };

  const onPointerMove = (e: ReactPointerEvent<HTMLDivElement>) => {
    e.stopPropagation();
    if (!dragging) return;
    trackDrag(e.clientY, e.timeStamp);
  };

  /** A drag starting anywhere else on the card, decided once, at the
   * moment the finger touches down - never mid-gesture. Cancelling a
   * touchmove AFTER the browser has already committed to scrolling
   * (rather than on its very first move) is exactly the pattern that
   * leaves mobile Chrome's touch/gesture state inconsistent - confirmed
   * real: an earlier version of this that re-decided on every move broke
   * page scrolling and even Chrome's own pull-to-refresh, sitewide,
   * outliving the sheet itself. So: if there's anything above to scroll
   * back to when this gesture starts, it's native scrolling only, full
   * stop, for this entire gesture - we never touch it again. Only a drag
   * that starts already at the top participates in the dismiss, the same
   * as the handle. That's a real trade-off (scrolling up through content
   * and continuing straight into a dismiss in one unbroken drag no longer
   * hands off - lift and pull again once at the top), accepted because
   * the alternative broke the page. */
  const onCardPointerDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    // A native form control (the exception date picker, a checkbox) needs
    // its own default pointer handling left completely alone - capturing
    // the pointer on one of these risks fighting whatever native UI it
    // shows on tap (a date wheel, a select dropdown).
    if (e.target instanceof HTMLInputElement || e.target instanceof HTMLSelectElement) return;
    const sheet = sheetRef.current;
    if (!sheet || sheet.scrollTop > 0) return;
    activePointerId.current = e.pointerId;
    startY.current = e.clientY;
    samples.current = [{ y: e.clientY, t: e.timeStamp }];
    (e.target as Element).setPointerCapture(e.pointerId);
  };

  const onCardPointerMove = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (activePointerId.current !== e.pointerId) return;
    if (!dragging) {
      // Upward movement here has nothing to do - the card was already at
      // the top when this gesture began, so there's nothing above to
      // reveal by scrolling further up.
      if (e.clientY - startY.current <= 0) return;
      e.preventDefault();
      beginDrag(e.clientY, e.timeStamp);
      return;
    }
    e.preventDefault();
    trackDrag(e.clientY, e.timeStamp);
  };

  const onCardPointerEnd = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (activePointerId.current !== e.pointerId) return;
    activePointerId.current = null;
    if (dragging) endDrag();
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
        onPointerDown={onCardPointerDown}
        onPointerMove={onCardPointerMove}
        onPointerUp={onCardPointerEnd}
        onPointerCancel={onCardPointerEnd}
        style={{
          transform: dragY ? `translateY(${dragY}px)` : undefined,
          transition: dragging ? "none" : undefined,
        }}
      >
        <div
          className="sheet-grab-zone"
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={(e) => {
            e.stopPropagation();
            endDrag();
          }}
          onPointerCancel={(e) => {
            e.stopPropagation();
            endDrag();
          }}
        >
          <div className="sheet-grab" aria-hidden="true" />
        </div>
        {children}
      </div>
    </div>
  );
}
