// @vitest-environment jsdom
// A server error or a dropped connection is not "nothing here": each page
// below used to show its not-found or empty state (or hang on "Loading…")
// when a deploy outlasted apiFetch's one retry.
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import type { ReactElement } from "react";
import type { FamilyChild } from "../lib/family";

const apiFetch = vi.fn();
vi.mock("../api", () => ({ apiFetch: (...args: unknown[]) => apiFetch(...args) }));

// One object for the whole file: a fresh one per call is a new hook
// dependency every render, and the effects that read it loop forever.
const auth = { user: null as null | { id: string; student_profile_id: string | null }, loading: false };
vi.mock("../context/AuthContext", () => ({ useAuth: () => auth }));
const schools = { excludeDistrict: false, districtsById: new Map() };
vi.mock("../lib/mySchools", () => ({ useMySchools: () => schools }));
vi.mock("../components/SeoHead", () => ({ SeoHead: () => null }));
vi.mock("../lib/track", () => ({ trackEvent: () => {}, trackMeasurement: () => {} }));
vi.mock("../components/AbsenceButton", () => ({ AbsenceButton: () => null }));
vi.mock("../components/today", () => ({
  ContactGrid: () => null,
  CurrentPeriodChip: () => null,
  DayBlocks: () => null,
  ItemRow: () => null,
  StatusPill: () => null,
  WeekStrip: () => null,
  contactHref: () => null,
  rotationLine: () => "",
}));

import { SchoolDetailPage } from "./SchoolDetailPage";
import { FamilyPage } from "./FamilyPage";
import { KidsDetailPage } from "./KidsDetailPage";
import { SchoolClassYearPage } from "./schools/SchoolClassYearPage";

const res = (status: number, body: unknown = null) => ({ ok: status < 400, status, json: async () => body });
const ready = () => document.body.getAttribute("data-prerender-ready");

afterEach(() => {
  cleanup();
  apiFetch.mockReset();
  auth.user = null;
  document.body.removeAttribute("data-prerender-ready");
});

function at(url: string, path: string, element: ReactElement) {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route path={path} element={element} />
      </Routes>
    </MemoryRouter>,
  );
}

const schoolToday = {
  school: { id: "id-maple", slug: "maple", name: "Maple Middle School", school_type: "middle", district_id: null },
  date: "2026-10-24",
  is_school_day: true,
  status: "open",
  status_label: null,
  hours: null,
  rotation_day: null,
  current_period: null,
  transportation: null,
  lunch: { today: null, next_label: null, next: null, source_pdf_url: null },
  sacc: null,
  contacts: [],
  upcoming: [],
  alerts: [],
  week: [],
};

describe("SchoolDetailPage", () => {
  const open = () => at("/schools/maple", "/schools/:schoolId", <SchoolDetailPage />);
  // What each section answers with when it's empty.
  const section = (url: string) => res(200, /\/(sacc|transportation)$/.test(url) ? null : []);

  it("offers Try again on a server error, not 'School not found', and doesn't hand the error to a crawler", async () => {
    apiFetch.mockImplementation(async (url: string) => (url.endsWith("/today") ? res(503) : section(url)));
    open();
    expect(await screen.findByText("Couldn't load this school just now.")).toBeTruthy();
    expect(screen.queryByText("School not found.")).toBeNull();
    expect(ready()).toBeNull();

    apiFetch.mockImplementation(async (url: string) => (url.endsWith("/today") ? res(200, schoolToday) : section(url)));
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("heading", { name: "Maple Middle School" })).toBeTruthy();
    await waitFor(() => expect(ready()).toBe("true"));
  });

  it("leaves Loading when every request fails on the network", async () => {
    apiFetch.mockRejectedValue(new TypeError("Failed to fetch"));
    open();
    expect(await screen.findByText("Couldn't load this school just now.")).toBeTruthy();
  });

  it("still renders the school when only a section fails on the network", async () => {
    apiFetch.mockImplementation(async (url: string) => {
      if (url.endsWith("/today")) return res(200, schoolToday);
      if (url.endsWith("/staff")) throw new TypeError("Failed to fetch");
      return section(url);
    });
    open();
    expect(await screen.findByRole("heading", { name: "Maple Middle School" })).toBeTruthy();
  });

  it("says not found only for a 404", async () => {
    apiFetch.mockResolvedValue(res(404));
    open();
    expect(await screen.findByText("School not found.")).toBeTruthy();
    await waitFor(() => expect(ready()).toBe("true"));
  });
});

const highSchooler: FamilyChild = {
  id: "kid-1",
  first_name: "Sam",
  last_name: "Example",
  student_id: "000000",
  school_name: "Example High School",
  school_type: "high",
  grad_year: 2028,
  guardian_count: 1,
  district_name: null,
  has_classroom: false,
  has_genesis: false,
  classroom_seen_at: null,
  genesis_seen_at: null,
  needs_login: false,
  due_this_week: null,
  missing: null,
  classes: null,
  today: null,
  student_login_email: null,
  student_invite_email: null,
  specials_count: 0,
};

describe("FamilyPage", () => {
  const open = () => {
    auth.user = { id: "u1", student_profile_id: null };
    return at("/family", "/family", <FamilyPage />);
  };

  it("shows an error with Try again on a server error, never 'Add your first child'", async () => {
    apiFetch.mockImplementation(async (url: string) => (url === "/family" ? res(503) : res(200, null)));
    open();
    expect(await screen.findByText("Couldn't load your family just now.")).toBeTruthy();
    expect(screen.queryByText("Add your first child")).toBeNull();

    apiFetch.mockImplementation(async (url: string) => (url === "/family" ? res(200, [highSchooler]) : res(200, null)));
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("heading", { name: "Sam Example" })).toBeTruthy();
  });

  it("shows the error, not Loading, when the connection drops", async () => {
    apiFetch.mockRejectedValue(new TypeError("Failed to fetch"));
    open();
    expect(await screen.findByText("Couldn't load your family just now.")).toBeTruthy();
  });

  it("puts the graduating class back when saving it fails", async () => {
    apiFetch.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === "/family") return res(200, [highSchooler]);
      if (init?.method === "PATCH") return res(500);
      return res(200, null);
    });
    open();
    const select = (await screen.findByLabelText("Sam's graduating class")) as HTMLSelectElement;
    expect(select.value).toBe("2028");
    fireEvent.change(select, { target: { value: "2029" } });
    expect(await screen.findByText("Couldn't save the graduating class. Try again in a minute.")).toBeTruthy();
    expect(select.value).toBe("2028");
  });
});

describe("KidsDetailPage", () => {
  const open = () => {
    auth.user = { id: "u1", student_profile_id: null };
    return at("/kids/kid-1", "/kids/:studentId", <KidsDetailPage />);
  };

  it("offers Try again on a server error instead of 'isn't on your profile'", async () => {
    apiFetch.mockResolvedValue(res(502));
    open();
    expect(await screen.findByText("Couldn't load this page just now.")).toBeTruthy();
    expect(screen.queryByText(/isn't on your profile/)).toBeNull();

    apiFetch.mockResolvedValue(res(404));
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText(/This student isn't on your profile/)).toBeTruthy();
  });

  it("shows the error, not Loading, when the connection drops", async () => {
    apiFetch.mockRejectedValue(new TypeError("Failed to fetch"));
    open();
    expect(await screen.findByText("Couldn't load this page just now.")).toBeTruthy();
  });
});

describe("SchoolClassYearPage", () => {
  const open = () => at("/schools/example-high/class-of-2028", "/schools/:schoolId/:classSlug", <SchoolClassYearPage />);
  const school = { id: "id-example-high", slug: "example-high", name: "Example High School", short_name: "Example High" };

  it("offers Try again when the class list fails, not 'No Class of 2028 page'", async () => {
    apiFetch.mockImplementation(async (url: string) => (url.endsWith("/class-years") ? res(503) : url.endsWith("/example-high") ? res(200, school) : res(200, [])));
    open();
    expect(await screen.findByText("Couldn't load this class page just now.")).toBeTruthy();
    expect(screen.queryByText(/No Class of 2028 page/)).toBeNull();
    expect(ready()).toBeNull();

    apiFetch.mockImplementation(async (url: string) => (url.endsWith("/example-high") ? res(200, school) : res(200, [])));
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("No Class of 2028 page for Example High.")).toBeTruthy();
    await waitFor(() => expect(ready()).toBe("true"));
  });

  it("still says the school couldn't be found for a 404", async () => {
    apiFetch.mockResolvedValue(res(404));
    open();
    expect(await screen.findByText("This school couldn't be found.")).toBeTruthy();
  });
});
