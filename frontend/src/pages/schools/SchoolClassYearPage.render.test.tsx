// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

const apiFetch = vi.fn();
vi.mock("../../api", () => ({ apiFetch: (...args: unknown[]) => apiFetch(...args) }));
vi.mock("../../context/AuthContext", () => ({ useAuth: () => ({ user: null }) }));
vi.mock("../../components/SeoHead", () => ({ SeoHead: () => null }));

import { SchoolClassYearPage } from "./SchoolClassYearPage";

const res = (status: number, body: unknown) => ({ ok: status < 400, status, json: async () => body });

function at(url: string) {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route path="/schools/:schoolId/:classSlug" element={<SchoolClassYearPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

function api(classYears: number[], schoolFound = true) {
  apiFetch.mockImplementation(async (url: string) => {
    if (url === "/schools/east") return schoolFound ? res(200, { id: "s1", slug: "east", name: "East", short_name: "East" }) : res(404, null);
    if (url === "/schools/east/class-years") return res(200, classYears.map((y) => ({
        id: `cy${y}`, school_id: "s1", grad_year: y, label: `Class of ${y}`, grade_level_principals: [], advisors: [],
        instagram_url: null, source_page_url: null, updated_at: "2026-10-01T00:00:00Z",
      })));
    return res(200, []);
  });
}

afterEach(() => {
  cleanup();
  apiFetch.mockReset();
  document.body.removeAttribute("data-prerender-ready");
});

describe("SchoolClassYearPage tells the prerender it's ready", () => {
  it("once its data has loaded", async () => {
    api([2027]);
    at("/schools/east/class-of-2027");
    await waitFor(() => expect(document.body.getAttribute("data-prerender-ready")).toBe("true"));
  });

  it("for a class the school has no page for, which says so instead of loading forever", async () => {
    api([2027]);
    at("/schools/east/class-of-2031");
    expect(await screen.findByText("No Class of 2031 page for East.")).toBeTruthy();
    expect(document.body.getAttribute("data-prerender-ready")).toBe("true");
  });

  it("for a school that doesn't exist", async () => {
    api([], false);
    at("/schools/east/class-of-2027");
    expect(await screen.findByText("This school couldn't be found.")).toBeTruthy();
    expect(document.body.getAttribute("data-prerender-ready")).toBe("true");
  });
});

const deposit = {
  id: "p1",
  school_class_year_id: "cy2027",
  sequence: 1,
  kind: "official",
  label: "Trip deposit",
  amount_cents: 75000,
  window_opens_at: null,
  window_closes_at: null,
  methods: null,
  payschools_item_name: null,
  refundable_until: null,
  notes: null,
  ticked: false,
};

function withPayments(tick: () => Promise<unknown>) {
  api([2027]);
  const base = apiFetch.getMockImplementation()!;
  apiFetch.mockImplementation(async (url: string, init?: RequestInit) => {
    if (url.endsWith("/payments")) return res(200, [deposit]);
    if (url.endsWith("/tick") && init?.method === "POST") return tick();
    return base(url);
  });
}

const boxes = () => screen.getAllByRole("checkbox", { name: "Mark Trip deposit paid" }) as HTMLInputElement[];

describe("SchoolClassYearPage payment ticks", () => {
  it("puts a tick back when the save fails", async () => {
    withPayments(async () => res(500, null));
    at("/schools/east/class-of-2027");
    await screen.findAllByRole("checkbox", { name: "Mark Trip deposit paid" });
    fireEvent.click(boxes()[0]);
    await waitFor(() => expect(boxes().every((b) => !b.checked && !b.disabled)).toBe(true));
  });

  it("can't be tapped again while its save is in flight", async () => {
    let finish: (value: unknown) => void = () => {};
    withPayments(() => new Promise((resolve) => (finish = resolve)));
    at("/schools/east/class-of-2027");
    await screen.findAllByRole("checkbox", { name: "Mark Trip deposit paid" });
    fireEvent.click(boxes()[0]);
    await waitFor(() => expect(boxes()[0].disabled).toBe(true));
    fireEvent.click(boxes()[0]);
    finish(res(200, { ...deposit, ticked: true }));
    await waitFor(() => expect(boxes()[0].checked && !boxes()[0].disabled).toBe(true));
    expect(apiFetch.mock.calls.filter(([url]) => String(url).endsWith("/tick"))).toHaveLength(1);
  });
});

describe("SchoolClassYearPage class-of tabs", () => {
  it("doesn't show one class's page under another's heading while it loads", async () => {
    api([2027, 2028]);
    const base = apiFetch.getMockImplementation()!;
    apiFetch.mockImplementation((url: string) => (url.includes("/2028/") ? new Promise(() => {}) : base(url)));
    at("/schools/east/class-of-2027");
    expect(await screen.findByRole("heading", { name: "Class of 2027" })).toBeTruthy();
    fireEvent.click(screen.getByRole("link", { name: "2028" }));
    expect(await screen.findByText("Loading…")).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Class of 2028" })).toBeNull();
  });
});
