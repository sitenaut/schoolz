import { useCallback, useState } from "react";

// A student's own display name for one class, keyed by course_key - same
// storage shape and same reasoning as lib/courseColors.ts (client-side
// only, a cosmetic preference, keyed by the one identity every screen that
// shows a class already shares). "GEOM A Per A 2026-27 210-1" -> "Geometry"
// is a real improvement shortCourseName's stripping rules can't always
// reach on their own.
const STORAGE_KEY = "focus_course_names";

export type CourseNameOverrides = Record<string, string>;

function readOverrides(): CourseNameOverrides {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as CourseNameOverrides) : {};
  } catch {
    return {};
  }
}

function writeOverrides(overrides: CourseNameOverrides): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(overrides));
  } catch {
    /* storage unavailable - the rename just won't persist across reloads */
  }
}

/** One shared source of truth, read once and held in React state - so
 * renaming a class in the course sheet shows up on Focus's chips and the
 * Subjects tiles immediately, the same reasoning as courseColors. */
export function useCourseDisplayNames() {
  const [overrides, setOverrides] = useState<CourseNameOverrides>(() => readOverrides());

  const setName = useCallback((courseKey: string, name: string | null) => {
    setOverrides((prev) => {
      const next = { ...prev };
      const trimmed = name?.trim();
      if (trimmed) next[courseKey] = trimmed;
      else delete next[courseKey];
      writeOverrides(next);
      return next;
    });
  }, []);

  return { overrides, setName };
}
