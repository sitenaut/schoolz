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

/** One shared fetch, one shared piece of state, for both the color and
 * name overrides together - they're the same backend row. Loaded once per
 * session; a pick updates local state immediately (so it shows up on
 * every tab right away) and persists in the background. */
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

  const save = useCallback((courseKey: string, customName: string | null, customColor: string | null) => {
    void apiFetch(`/course-preferences/${encodeURIComponent(courseKey)}`, {
      method: "PUT",
      body: JSON.stringify({ custom_name: customName, custom_color: customColor }),
    });
  }, []);

  const setName = useCallback(
    (courseKey: string, name: string | null) => {
      const trimmed = name?.trim() || null;
      setNames((prev) => {
        const next = { ...prev };
        if (trimmed) next[courseKey] = trimmed;
        else delete next[courseKey];
        return next;
      });
      // Reads the LATEST colors via a functional update's escape hatch
      // isn't available outside setState, so colors is captured from the
      // closure - safe here since setName and setColor are never called
      // for the same course_key in the same tick (the color and name
      // pickers are separate controls, never edited by the same event).
      save(courseKey, trimmed, colors[courseKey] ?? null);
    },
    [colors, save],
  );

  const setColor = useCallback(
    (courseKey: string, hex: string | null) => {
      setColors((prev) => {
        const next = { ...prev };
        if (hex) next[courseKey] = hex;
        else delete next[courseKey];
        return next;
      });
      save(courseKey, names[courseKey] ?? null, hex);
    },
    [names, save],
  );

  return { names, colors, setName, setColor };
}
