// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import type { School } from "../types";

const apiFetch = vi.fn();
vi.mock("../api", () => ({ apiFetch: (...args: unknown[]) => apiFetch(...args) }));

const school = (slug: string) => ({ id: `id-${slug}`, slug, name: slug, short_name: slug }) as unknown as School;
let schools: { mySchools: School[]; loading: boolean; deviceSlugs: string[]; slugs: string[] };
vi.mock("../lib/mySchools", () => ({
  RIBBON_CHANGE_EVENT: "ribbon",
  useMySchools: () => ({
    ...schools,
    activeSchools: schools.mySchools,
    allSchools: schools.mySchools,
    activateAll: () => {},
    colorFor: () => "red",
    excludeDistrict: false,
    setExcludeDistrict: () => {},
    districtsById: new Map(),
    myTowns: [],
    setSlugs: (s: string[]) => (schools.slugs = s),
    fromAccount: false,
  }),
}));
vi.mock("../context/AuthContext", () => ({ useAuth: () => ({ user: null }) }));
vi.mock("../components/SeoHead", () => ({ SeoHead: () => null }));

import { CalendarPage, SchoolCalendarPage } from "./CalendarPage";
import { PickSchoolsPage } from "./PickSchoolsPage";

const json = (body: unknown) => ({ ok: true, status: 200, json: async () => body });
const calendarCalls = () => apiFetch.mock.calls.map((c) => String(c[0])).filter((u) => u.startsWith("/calendar"));

function Where() {
  const loc = useLocation();
  return <div data-testid="where">{loc.pathname + loc.search}</div>;
}

function at(url: string) {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route path="/calendar" element={<CalendarPage />} />
        <Route path="/schools/:schoolId/calendar" element={<SchoolCalendarPage />} />
        <Route path="/start" element={<PickSchoolsPage />} />
      </Routes>
      <Where />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  apiFetch.mockImplementation(async () => json([]));
  schools = { mySchools: [], loading: false, deviceSlugs: [], slugs: [] };
});
afterEach(() => {
  cleanup();
  apiFetch.mockReset();
});

describe("CalendarPage with no schools picked", () => {
  it("asks for a school instead of loading every school's month", async () => {
    at("/calendar");
    const link = await screen.findByRole("link", { name: "Pick your schools" });
    expect(link.getAttribute("href")).toBe("/start?next=/calendar");
    expect(screen.queryByText("Show day rotation")).toBeNull();
    expect(calendarCalls()).toEqual([]);
  });

  it("shows a placeholder, not the prompt, while it can't tell yet", () => {
    schools.loading = true;
    at("/calendar");
    expect(screen.getByText("Loading…")).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Pick your schools" })).toBeNull();
  });

  it("sends an old ?school= link to that school's own calendar page", async () => {
    at("/calendar?school=beck&date=2026-10-22&event=e1");
    expect(screen.getByTestId("where").textContent).toBe("/schools/beck/calendar?date=2026-10-22&event=e1");
    await waitFor(() => expect(calendarCalls().length).toBeGreaterThan(0));
    expect(calendarCalls().every((u) => u.includes("school_ids=beck"))).toBe(true);
  });

  it("comes back to the calendar once a school is picked", async () => {
    // Already ticked in the picker, as if the visitor had just chosen it.
    schools = { mySchools: [], loading: false, deviceSlugs: [], slugs: ["beck"] };
    at("/start?next=/calendar");
    fireEvent.click(await screen.findByRole("button", { name: /^Continue/ }));
    expect(screen.getByTestId("where").textContent).toBe("/calendar");
  });
});

describe("CalendarPage with schools picked", () => {
  it("loads only those schools", async () => {
    schools = { mySchools: [school("east"), school("beck")], loading: false, deviceSlugs: ["east", "beck"], slugs: ["east", "beck"] };
    at("/calendar");
    await waitFor(() => expect(calendarCalls()).toHaveLength(1));
    expect(calendarCalls()[0]).toContain("school_ids=east%2Cbeck");
  });
});

describe("A school's own calendar page", () => {
  beforeEach(() => {
    apiFetch.mockImplementation(async (url: string) => (url === "/schools/beck" ? json(school("beck")) : json([])));
  });

  it("shows that school's dates with nothing picked, under its name", async () => {
    at("/schools/beck/calendar");
    await waitFor(() => expect(calendarCalls()).toHaveLength(1));
    expect(calendarCalls()[0]).toContain("school_ids=beck");
    // "<school> calendar" (no i18n in tests, so the key itself), not "Calendar".
    expect(await screen.findByRole("heading", { name: /calendar$/ })).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Pick your schools" })).toBeNull();
  });

  it("goes to the whole calendar for all my schools", async () => {
    at("/schools/beck/calendar");
    fireEvent.click(await screen.findByRole("button", { name: "Show all my schools" }));
    expect(screen.getByTestId("where").textContent).toBe("/calendar");
  });

  it("says so when there's no such school", async () => {
    apiFetch.mockImplementation(async (url: string) => (url === "/schools/nope" ? { ok: false, status: 404, json: async () => ({}) } : json([])));
    at("/schools/nope/calendar");
    expect(await screen.findByText("We couldn't find that school.")).toBeTruthy();
  });
});
