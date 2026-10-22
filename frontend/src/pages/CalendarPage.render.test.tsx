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

import { CalendarPage } from "./CalendarPage";
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

  it("still shows a school page's ?school= link", async () => {
    at("/calendar?school=beck");
    await waitFor(() => expect(calendarCalls()).toHaveLength(1));
    expect(calendarCalls()[0]).toContain("school_ids=beck");
    expect(screen.queryByRole("link", { name: "Pick your schools" })).toBeNull();
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
