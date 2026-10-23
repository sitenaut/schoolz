// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import type { School } from "../types";
import { todayKey } from "../lib/calendar";

const apiFetch = vi.fn();
vi.mock("../api", () => ({ apiFetch: (...args: unknown[]) => apiFetch(...args) }));

const school = (slug: string) => ({ id: `id-${slug}`, slug, name: `${slug} school`, short_name: slug, school_type: "middle" }) as unknown as School;
let mine: School[];
let loading: boolean;
vi.mock("../lib/mySchools", () => ({
  useMySchools: () => ({ mySchools: mine, activeSchools: mine, loading, colorFor: () => "red", myTowns: [] }),
}));
vi.mock("../components/SeoHead", () => ({ SeoHead: () => null }));

import { LunchPage } from "./LunchPage";

// Dated today: a menu whose days are all past shows "not posted yet" instead.
let menuDay: string;
const menu = (slug: string) => ({
  period_label: "October 2026",
  source_pdf_url: "https://example.org/menu.pdf",
  source_page_url: "https://example.org/food",
  items: [{ id: `${slug}-1`, menu_date: `${menuDay}T16:00:00Z`, description: `${slug} pizza`, notes: null }],
});
const res = (status: number, body: unknown) => ({ ok: status < 400, status, json: async () => body });
const fetched = () => apiFetch.mock.calls.map((c) => String(c[0]));

function Where() {
  const loc = useLocation();
  return <div data-testid="where">{loc.pathname + loc.search}</div>;
}

function at(url: string) {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route path="/lunch" element={<LunchPage />} />
        <Route path="/start" element={<p>picker</p>} />
      </Routes>
      <Where />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  menuDay = todayKey();
  mine = [];
  loading = false;
  apiFetch.mockImplementation(async (url: string) => {
    const m = url.match(/^\/schools\/([^/]+)(\/lunch-menu)?$/);
    if (!m || m[1] === "nope") return res(404, null);
    return res(200, m[2] ? menu(m[1]) : school(m[1]));
  });
});
afterEach(() => {
  cleanup();
  apiFetch.mockReset();
  document.body.removeAttribute("data-prerender-ready");
});

describe("LunchPage", () => {
  it("asks for a school in place when nothing is picked and none is linked", async () => {
    at("/lunch");
    const link = await screen.findByRole("link", { name: "Pick your schools" });
    expect(link.getAttribute("href")).toBe("/start?next=/lunch");
    expect(screen.getByTestId("where").textContent).toBe("/lunch");
    expect(fetched()).toEqual([]);
    expect(document.body.getAttribute("data-prerender-ready")).toBe("true");
  });

  it("shows a linked school's menu with nothing picked, instead of sending the visitor to the picker", async () => {
    at("/lunch?school=beck&date=2026-10-22");
    expect(await screen.findByText("beck pizza")).toBeTruthy();
    expect(await screen.findByRole("button", { name: "beck" })).toBeTruthy(); // says whose menu it is
    expect(screen.getByTestId("where").textContent).toBe("/lunch?school=beck&date=2026-10-22");
    await waitFor(() => expect(document.body.getAttribute("data-prerender-ready")).toBe("true"));
  });

  it("shows the linked school, not your first one, when it isn't one of yours", async () => {
    mine = [school("east")];
    at("/lunch?school=beck");
    expect(await screen.findByText("beck pizza")).toBeTruthy();
    expect(fetched()).not.toContain("/schools/east/lunch-menu");
    // Both tabs, so you can get back to your own school's menu.
    expect(await screen.findByRole("button", { name: "beck" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "east" })).toBeTruthy();
  });

  it("falls back to your own school when the linked one doesn't exist", async () => {
    mine = [school("east")];
    at("/lunch?school=nope");
    expect(await screen.findByText("east pizza")).toBeTruthy();
  });

  it("still opens on your first school with no link", async () => {
    mine = [school("east"), school("beck")];
    at("/lunch");
    expect(await screen.findByText("east pizza")).toBeTruthy();
    await waitFor(() => expect(fetched()).toEqual(["/schools/east/lunch-menu"]));
  });

  it("says the next menu isn't posted instead of listing one that's over", async () => {
    // Burlington City showed September's menu all through October.
    menuDay = "2020-09-30";
    mine = [school("east")];
    at("/lunch");
    expect(await screen.findByText(/lunch menu hasn't been posted yet/)).toBeTruthy();
    expect(screen.queryByText("east pizza")).toBeNull();
    expect(screen.getByRole("link", { name: "Check the district's menu page" }).getAttribute("href")).toBe("https://example.org/food");
    await waitFor(() => expect(document.body.getAttribute("data-prerender-ready")).toBe("true"));
  });
});
