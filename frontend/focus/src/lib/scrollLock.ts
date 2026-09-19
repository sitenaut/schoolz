// A reference-counted body-scroll lock, for any number of stacked sheets.
//
// Why reference-counted rather than each caller saving/restoring its own
// "original" overflow value: CourseSheet and TaskModal can be mounted at
// the same time (tapping an item inside a course's sheet opens the task
// sheet on top without closing the course sheet), each with its own Sheet
// instance. A naive per-instance lock has the second one capture the
// FIRST one's "hidden" as its own "original" value - so if both ever
// unmount in the same pass (pressing Escape while both are open fires
// both Sheets' own keydown listeners at once) and the wrong one's cleanup
// happens to run last, the page is left permanently frozen with
// `overflow: hidden` and nothing left mounted to undo it. Confirmed real,
// not theoretical - this happened.
//
// A single shared counter has no ordering to get wrong: the lock is
// applied once, on the first caller, and released once, when the last
// caller releases - regardless of how many are stacked or which order
// they close in.
let lockCount = 0;
let previousOverflow = "";

export function lockBodyScroll(): () => void {
  if (lockCount === 0) {
    previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
  }
  lockCount++;
  let released = false;
  return () => {
    // Idempotent - React StrictMode double-invokes effects in dev, and a
    // caller might reasonably call this more than once.
    if (released) return;
    released = true;
    lockCount = Math.max(0, lockCount - 1);
    if (lockCount === 0) {
      document.body.style.overflow = previousOverflow;
    }
  };
}
