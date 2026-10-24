import { useCallback, useEffect, useState } from "react";
import { apiFetch, apiGet } from "../api";

// A person's own rename/recolor of one class, keyed by course_key -
// backend-persisted (bucket3.py's /course-preferences), not localStorage.
//
// This was originally two localStorage-only hooks (one per-device pick
// each, in courseColors.ts/courseNames.ts). Explicit product requirement
// (2026-09-20): the pick must follow the person across their own devices,
// but stay invisible to every other guardian who can see the same
// student's data - a Student row is shared across linked guardians, so a
// device-local store was already accidentally private in the right way,
// but only by accident (it also didn't survive a second device). Moving
// this to the backend, keyed by account (not student, not device), keeps
// the same privacy property on purpose while adding the sync a pure
// localStorage version could never give.
//
// Kept as two separately-named exports (CourseColorOverrides /
// CourseNameOverrides, both just Record<courseKey, string>) purely so the
// five components that already consume these types - FocusTab,
// SubjectsTab, DetailsTab, TaskModal, CourseSheet - didn't need to change
// at all when the storage layer moved out from under them.
export type CourseColorOverrides = Record<string, string>;
export type CourseNameOverrides = Record<string, string>;

type CoursePreference = { course_key: string; custom_name: string | null; custom_color: string | null };

function withOverride(prev: Record<string, string>, courseKey: string, value: string | null): Record<string, string> {
  const next = { ...prev };
  if (value) next[courseKey] = value;
  else delete next[courseKey];
  return next;
}

/** One shared fetch, one shared piece of state, for both the color and
 * name overrides together - they're the same backend row. Loaded once per
 * session; a pick updates local state immediately (so it shows up on
 * every tab right away) and persists in the background, sending only the
 * field it changed: sending both from this copy wiped the other field
 * whenever the copy hadn't loaded yet (or its load had failed). A save
 * that fails puts the old value back, rather than showing a pick that is
 * gone on the next visit. */
export function useCoursePreferences() {
  const [names, setNames] = useState<CourseNameOverrides>({});
  const [colors, setColors] = useState<CourseColorOverrides>({});

  useEffect(() => {
    let cancelled = false;
    apiGet<CoursePreference[]>("/course-preferences").then((rows) => {
      if (cancelled || !rows) return;
      const nextNames: CourseNameOverrides = {};
      const nextColors: CourseColorOverrides = {};
      for (const row of rows) {
        if (row.custom_name) nextNames[row.course_key] = row.custom_name;
        if (row.custom_color) nextColors[row.course_key] = row.custom_color;
      }
      setNames(nextNames);
      setColors(nextColors);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const save = useCallback(async (courseKey: string, field: Partial<Omit<CoursePreference, "course_key">>) => {
    try {
      const res = await apiFetch(`/course-preferences/${encodeURIComponent(courseKey)}`, {
        method: "PUT",
        body: JSON.stringify(field),
      });
      return res.ok;
    } catch {
      return false;
    }
  }, []);

  const setName = useCallback(
    (courseKey: string, name: string | null) => {
      const trimmed = name?.trim() || null;
      const before = names[courseKey] ?? null;
      setNames((prev) => withOverride(prev, courseKey, trimmed));
      void save(courseKey, { custom_name: trimmed }).then((ok) => {
        // Only if nothing newer replaced it meanwhile.
        if (!ok) setNames((prev) => ((prev[courseKey] ?? null) === trimmed ? withOverride(prev, courseKey, before) : prev));
      });
    },
    [names, save],
  );

  const setColor = useCallback(
    (courseKey: string, hex: string | null) => {
      const before = colors[courseKey] ?? null;
      setColors((prev) => withOverride(prev, courseKey, hex));
      void save(courseKey, { custom_color: hex }).then((ok) => {
        if (!ok) setColors((prev) => ((prev[courseKey] ?? null) === hex ? withOverride(prev, courseKey, before) : prev));
      });
    },
    [colors, save],
  );

  return { names, colors, setName, setColor };
}
