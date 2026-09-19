import { useCallback, useState } from "react";

// A student's own pick for one class's color, keyed by course_key (the
// same identity Focus/Subjects/the course sheet all key on) so it's never
// ambiguous which class an override applies to, even across the raw-name
// variance between Genesis and Classroom. Client-side only, like the rest
// of this app's per-device conveniences (localStorage, not synced) - it's
// a cosmetic preference, not data the app itself needs to reason about.
const STORAGE_KEY = "focus_course_colors";

export type CourseColorOverrides = Record<string, string>;

function readOverrides(): CourseColorOverrides {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as CourseColorOverrides) : {};
  } catch {
    return {};
  }
}

function writeOverrides(overrides: CourseColorOverrides): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(overrides));
  } catch {
    /* storage unavailable - the pick just won't persist across reloads */
  }
}

/** One shared source of truth for color overrides, read once and held in
 * React state - so picking a color in the course sheet is reflected
 * immediately on the Focus tab's chips and the Subjects tiles too, without
 * each of them re-reading localStorage on their own. */
export function useCourseColorOverrides() {
  const [overrides, setOverrides] = useState<CourseColorOverrides>(() => readOverrides());

  const setColor = useCallback((courseKey: string, hex: string | null) => {
    setOverrides((prev) => {
      const next = { ...prev };
      if (hex) next[courseKey] = hex;
      else delete next[courseKey];
      writeOverrides(next);
      return next;
    });
  }, []);

  return { overrides, setColor };
}
