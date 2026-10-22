// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
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
