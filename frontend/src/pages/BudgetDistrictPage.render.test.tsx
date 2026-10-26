// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import type { BudgetDistrict } from "../types";

const apiFetch = vi.fn();
vi.mock("../api", () => ({ apiFetch: (...args: unknown[]) => apiFetch(...args) }));
vi.mock("../components/SeoHead", () => ({ SeoHead: () => null }));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (s: string, o?: Record<string, string>) => s.replace(/{{(\w+)}}/g, (_, k) => o?.[k] ?? "") }),
}));

import { BudgetDistrictPage } from "./BudgetDistrictPage";

const res = (status: number, body: unknown = null) => ({ ok: status < 400, status, json: async () => body });
const median = (county: number | null, state: number | null) => ({ county, state });

const district = (over: Partial<BudgetDistrict> = {}): BudgetDistrict => ({
  slug: "cherry-hill-school-district",
  name: "Cherry Hill Public Schools",
  county: "Camden",
  state: "NJ",
  budget_year: "2026-27",
  comparable: true,
  schools: [{ slug: "cherry-hill-high-school-east", name: "Cherry Hill High School East" }],
  benefits_prior: 54_067_324,
  benefits_budget: 61_423_410,
  other_spending_prior: 194_298_869,
  other_spending_budget: 191_624_178,
  prior_basis: "revised",
  formula_aid_change: -857_788,
  levy_prior: 201_491_240,
  levy_budget: 216_322_308,
  levy_change_pct: 7.4,
  fund_balance_prior: 13_055_491,
  fund_balance_budget: 3_750_000,
  budget_report_url: "https://www.nj.gov/education/budget/ufb/2627/reports/07/UFB27_0800.pdf",
  aid_source_url: "https://www.nj.gov/education/stateaid/2627/FY27_GBM_District_Details.xlsx",
  health_costs: {
    start: { year: "2022-23", value: 33_985_121, url: "https://www.nj.gov/a23.pdf#page=105" },
    end: { year: "2024-25", value: 38_380_757, url: "https://www.nj.gov/a25.pdf#page=93" },
  },
  staffing: {
    students_per_teacher: { start: { year: "2021-22", value: 11.7 }, end: { year: "2024-25", value: 11.8 } },
    median_teacher_salary: { year: "2024-25", value: 102_148 },
    url: "https://www.nj.gov/education/spr/download/",
  },
  statements: [],
  medians: {
    benefits_change_pct: median(16, 18.2),
    other_spending_change_pct: median(2.5, 0.5),
    levy_change_pct: median(6, 5),
    health_change_pct: median(16.4, 18.1),
    students_per_teacher: median(11.1, 10.7),
    median_teacher_salary: median(75_209.5, 78_586.5),
  },
  imported_at: "2026-10-25T00:00:00Z",
  ...over,
});

function at(url: string) {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route path="/budgets/:slug" element={<BudgetDistrictPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

afterEach(() => {
  cleanup();
  apiFetch.mockReset();
  document.body.removeAttribute("data-prerender-ready");
});

describe("BudgetDistrictPage", () => {
  it("shows each figure with its change, its source and the county and state medians", async () => {
    apiFetch.mockResolvedValue(res(200, district()));
    at("/budgets/cherry-hill-school-district");
    await screen.findByText("Cherry Hill Public Schools");
    expect(apiFetch).toHaveBeenCalledWith("/budgets/cherry-hill-school-district");
    expect(screen.getByText("2025-26: $201.5M → 2026-27: $216.3M (+7.4%)")).toBeTruthy();
    expect(screen.getByText("Camden County median +6% · New Jersey median +5%")).toBeTruthy();
    expect(screen.getByText("2022-23: $34.0M → 2024-25: $38.4M (+12.9%)")).toBeTruthy();
    expect(screen.getByText("2024-25").getAttribute("href")).toBe("https://www.nj.gov/a25.pdf#page=93");
    expect(screen.getByText("2021-22: 11.7 → 2024-25: 11.8")).toBeTruthy();
    expect(screen.getByText("Cherry Hill High School East").getAttribute("href")).toBe("/schools/cherry-hill-high-school-east");
    expect(document.body.getAttribute("data-prerender-ready")).toBe("true");
  });

  it("leaves out what a district has no figures for, and its medians when it isn't comparable", async () => {
    apiFetch.mockResolvedValue(res(200, district({ comparable: false, health_costs: null, staffing: null, schools: [] })));
    at("/budgets/cherry-hill-school-district");
    await screen.findByText("Cherry Hill Public Schools");
    expect(screen.queryByText("Health insurance costs")).toBeNull();
    expect(screen.queryByText("Teachers")).toBeNull();
    expect(screen.queryByText("Schools on schoolz")).toBeNull();
    expect(screen.queryByText(/County median/)).toBeNull();
    expect(screen.getByText(/isn't counted in the county and state medians/)).toBeTruthy();
  });

  it("says not found for an unknown district, and stays unready on a server error", async () => {
    apiFetch.mockResolvedValue(res(404));
    at("/budgets/nope");
    await screen.findByText("District not found.");
    expect(document.body.getAttribute("data-prerender-ready")).toBe("true");
    cleanup();
    document.body.removeAttribute("data-prerender-ready");

    apiFetch.mockResolvedValue(res(503));
    at("/budgets/cherry-hill-school-district");
    await screen.findByText("Couldn't load this budget just now.");
    await waitFor(() => expect(document.body.getAttribute("data-prerender-ready")).toBeNull());
  });
});
