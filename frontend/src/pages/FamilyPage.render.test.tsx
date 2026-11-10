// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import type { FamilyChild } from "../lib/family";

const apiFetch = vi.fn();
vi.mock("../api", () => ({ apiFetch: (...args: unknown[]) => apiFetch(...args) }));
// One object for the whole file: a fresh one per call is a new hook
// dependency every render, and the effects that read it loop forever.
const auth = { user: { id: "u1", student_profile_id: null }, loading: false };
vi.mock("../context/AuthContext", () => ({ useAuth: () => auth }));

import { FamilyPage } from "./FamilyPage";
import { KidsDetailPage } from "./KidsDetailPage";

const res = (status: number, body: unknown = null) => ({ ok: status < 400, status, json: async () => body });

const sam: FamilyChild = {
  id: "kid-1",
  first_name: "Sam",
  last_name: "Example",
  student_id: "000000",
  school_name: "Example High School",
  school_type: "high",
  grad_year: 2028,
  guardian_count: 1,
  district_name: null,
  has_classroom: true,
  has_genesis: true,
  classroom_seen_at: "2026-11-10T12:00:00Z",
  genesis_seen_at: "2026-11-10T12:00:00Z",
  needs_login: false,
  due_this_week: null,
  missing: null,
  classes: 1,
  today: null,
  student_login_email: null,
  student_invite_email: null,
  specials_count: 0,
};

const grades = {
  course_grades: [],
  entries: [
    {
      external_uid: "e1",
      course_code: "331",
      course_section: "10",
      course_name: "CHEMISTRY 1A",
      marking_period: "MP1",
      weekday_date: "Fri 10/2",
      title: "Density Lab",
      description: null,
      category: null,
      score_earned: 20,
      score_possible: 25,
      percent: 80,
      status: null,
      is_updated: false,
    },
  ],
  marking_periods: [],
  marking_period_discrepancies: [],
};

function serve(children: FamilyChild[]) {
  apiFetch.mockImplementation(async (url: string) => {
    if (url === "/family") return res(200, children);
    if (url.endsWith("/bucket3/student")) return res(200, { ...sam, viewer_role: "guardian" });
    if (url.endsWith("/bucket3/grades")) return res(200, grades);
    return res(404);
  });
}

function openFamily() {
  return render(
    <MemoryRouter initialEntries={["/family"]}>
      <Routes>
        <Route path="/family" element={<FamilyPage />} />
        <Route path="/kids/:studentId" element={<KidsDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

afterEach(() => {
  cleanup();
  apiFetch.mockReset();
  localStorage.clear();
});

describe("My family's Grades button", () => {
  it("opens the child's grades under Everything, leaving the saved view alone", async () => {
    localStorage.setItem("schoolz_kids_view_mode", "focused");
    serve([sam]);
    openFamily();
    fireEvent.click(await screen.findByRole("link", { name: "Grades" }));

    expect(await screen.findByText("Density Lab")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Grades" }).className).toContain("active");
    expect(screen.getByRole("button", { name: "Everything" }).className).toContain("active");
    expect(localStorage.getItem("schoolz_kids_view_mode")).toBe("focused");
  });

  it("waits until Genesis pages have arrived", async () => {
    serve([{ ...sam, genesis_seen_at: null }]);
    openFamily();
    expect(await screen.findByRole("link", { name: "Open" })).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Grades" })).toBeNull();
  });
});
