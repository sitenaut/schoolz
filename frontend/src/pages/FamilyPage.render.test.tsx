// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { FamilyChild } from "../lib/family";

const apiFetch = vi.fn();
vi.mock("../api", () => ({ apiFetch: (...args: unknown[]) => apiFetch(...args) }));
// One object for the whole file: a fresh one per call is a new hook
// dependency every render, and the effects that read it loop forever.
const auth = { user: { id: "u1", student_profile_id: null as string | null }, loading: false };
vi.mock("../context/AuthContext", () => ({ useAuth: () => auth }));

import { FamilyPage } from "./FamilyPage";

const res = (status: number, body: unknown = null) => ({ ok: status < 400, status, json: async () => body });

// Sent an hour ago, so the data counts as fresh.
const sentAt = new Date(Date.now() - 60 * 60 * 1000).toISOString();

const sam: FamilyChild = {
  id: "kid-1",
  first_name: "Sam",
  last_name: "Example",
  student_id: "000000",
  school_name: "Example High School",
  school_type: "high",
  grad_year: null,
  guardian_count: 2,
  district_name: null,
  has_classroom: true,
  has_genesis: true,
  classroom_seen_at: sentAt,
  genesis_seen_at: sentAt,
  needs_login: false,
  due_this_week: 4,
  due_today: 2,
  missing: 3,
  classes: 6,
  low_class: { course_key: "210-1", course_name: "Geometry", custom_name: null },
  recent_posts: 3,
  today: { state: "now", course_name: "Biology", room: "214", time_start: "9:52", time_end: "10:42" },
  student_login_email: null,
  student_invite_email: null,
  specials_count: 0,
};

function serve(children: FamilyChild[]) {
  apiFetch.mockImplementation(async (url: string) => {
    if (url === "/family") return res(200, children);
    if (url.endsWith("/student-account")) return res(200, { has_account: false, account_email: null, pending_invite_email: null });
    return res(404);
  });
}

function openFamily() {
  return render(
    <MemoryRouter initialEntries={["/family"]}>
      <FamilyPage />
    </MemoryRouter>,
  );
}

const card = async () => within(await screen.findByRole("region", { name: "Sam Example" }));
const row = (scope: Awaited<ReturnType<typeof card>>, title: string) => scope.getByText(title).closest("a")!;

afterEach(() => {
  cleanup();
  apiFetch.mockReset();
  auth.user.student_profile_id = null;
  vi.unstubAllGlobals();
});

describe("My family's card", () => {
  it("opens the child's Gradez page with a plain link", async () => {
    serve([sam]);
    openFamily();
    const c = await card();
    expect(c.getByRole("link", { name: "Open" }).getAttribute("href")).toBe("/gradez?student=kid-1");
    expect(c.getByText("Example High School")).toBeTruthy();
  });

  it("gives each row the tab it is named for, with what that tab says", async () => {
    serve([sam]);
    openFamily();
    const c = await card();
    expect(row(c, "To do").getAttribute("href")).toBe("/gradez?student=kid-1");
    expect(row(c, "Grades").getAttribute("href")).toBe("/gradez?student=kid-1&tab=grades");
    expect(row(c, "Schedule").getAttribute("href")).toBe("/gradez?student=kid-1&tab=schedule");
    expect(row(c, "Teachers").getAttribute("href")).toBe("/gradez?student=kid-1&tab=teachers");

    expect(c.getByText("2 due today · 3 missing")).toBeTruthy();
    expect(c.getByText("6 classes · Geometry is below 50%").className).toContain("warn");
    expect(c.getByText("Now: Biology, Room 214")).toBeTruthy();
    expect(c.getByText("3 posts this week")).toBeTruthy();
  });

  it("says nothing on a row it wasn't told", async () => {
    serve([{ ...sam, due_today: null, missing: null, classes: null, low_class: null, recent_posts: null, today: null }]);
    openFamily();
    const c = await card();
    for (const title of ["To do", "Grades", "Schedule", "Teachers"]) {
      expect(row(c, title).textContent).toBe(title);
    }
  });

  it("doesn't flag grades when no class is below 50%", async () => {
    serve([{ ...sam, low_class: null }]);
    openFamily();
    expect((await card()).getByText("6 classes").className).not.toContain("warn");
  });

  it("calls a low class by the caller's own name for it", async () => {
    serve([{ ...sam, low_class: { course_key: "210-1", course_name: "Geometry", custom_name: "Geo" } }]);
    openFamily();
    expect((await card()).getByText("6 classes · Geo is below 50%")).toBeTruthy();
  });

  it("links to About this data, green only while the data is fresh", async () => {
    serve([sam]);
    openFamily();
    const link = (await screen.findByText(/^Schoolwork updated/)).closest("a")!;
    expect(link.getAttribute("href")).toBe("/gradez?student=kid-1&sheet=data");
    expect(link.className).toContain("fam-data-ok");
  });

  it("doesn't call two-day-old data fresh", async () => {
    const old = new Date(Date.now() - 2 * 24 * 60 * 60 * 1000).toISOString();
    serve([{ ...sam, classroom_seen_at: old, genesis_seen_at: old }]);
    openFamily();
    const link = (await screen.findByText(/^Schoolwork updated/)).closest("a")!;
    expect(link.className).not.toContain("fam-data-ok");
  });

  it("waits for schoolwork before offering the tabs, but always offers Open", async () => {
    serve([{ ...sam, classroom_seen_at: null, genesis_seen_at: null }]);
    openFamily();
    const c = await card();
    expect(c.getByRole("link", { name: "Open" })).toBeTruthy();
    expect(c.queryByText("To do")).toBeNull();
    expect(screen.queryByText(/^Schoolwork updated/)).toBeNull();
  });

  it("opens the student-login invite and the guardian invite from People", async () => {
    serve([sam]);
    openFamily();
    const c = await card();
    expect(c.getByText("Not invited yet. Sam would see this same page.")).toBeTruthy();
    expect(c.getByText("You and 1 other")).toBeTruthy();

    fireEvent.click(c.getByRole("button", { name: "Invite Sam to their own login" }));
    expect(await c.findByText("Sam's email address")).toBeTruthy();

    fireEvent.click(c.getByRole("button", { name: /Guardians/ }));
    expect(c.getByText("Their email address")).toBeTruthy();
    expect(c.queryByText("Sam's email address")).toBeNull();
  });
});

describe("A student's own login on My family", () => {
  it("goes to their own Gradez page with a page load", () => {
    const replace = vi.fn();
    vi.stubGlobal("location", { ...window.location, replace });
    auth.user.student_profile_id = "kid-1";
    serve([sam]);
    const { container } = openFamily();
    expect(replace).toHaveBeenCalledWith("/gradez?student=kid-1");
    expect(container.textContent).toBe("");
    expect(apiFetch).not.toHaveBeenCalledWith("/family");
  });
});
