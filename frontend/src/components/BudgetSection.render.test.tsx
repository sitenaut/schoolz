// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { SchoolBudget } from "../types";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (s: string, o?: Record<string, string>) => s.replace(/{{(\w+)}}/g, (_, k) => o?.[k] ?? "") }),
}));

import { BudgetSection, money, priorYear } from "./BudgetSection";

const budget = (over: Partial<SchoolBudget> = {}): SchoolBudget => ({
  district_name: "Cherry Hill Public Schools",
  slug: null,
  budget_year: "2026-27",
  benefits_prior: 54_067_324,
  benefits_budget: 61_423_410,
  prior_basis: "revised",
  formula_aid_change: -857_788,
  levy_change_pct: 7.4,
  fund_balance_prior: 13_055_491,
  fund_balance_budget: 3_750_000,
  budget_report_url: "https://www.nj.gov/education/budget/ufb/2627/reports/07/UFB27_0800.pdf",
  aid_source_url: "https://www.nj.gov/education/stateaid/2627/FY27_GBM_District_Details.xlsx",
  statements: [],
  imported_at: "2026-10-24T00:00:00Z",
  ...over,
});

afterEach(cleanup);

describe("BudgetSection", () => {
  it("shows the state figures with their change and source links", () => {
    render(<BudgetSection budget={budget()} />);
    expect(screen.getByText("2025-26: $54.1M → 2026-27: $61.4M (+13.6%)")).toBeTruthy();
    expect(screen.getByText(/Down \$857,788 from last year/)).toBeTruthy();
    expect(screen.getByText("Up 7.4% from last year")).toBeTruthy();
    expect(screen.getByText("2025-26: $13.1M → 2026-27: $3.8M")).toBeTruthy();
    expect(screen.getByText("State budget report").getAttribute("href")).toContain("UFB27_0800.pdf");
    expect(screen.queryByText("In the district's words")).toBeNull();
  });

  it("leaves out a figure the state files don't support, and quotes the district with its source", () => {
    render(
      <BudgetSection
        budget={budget({
          benefits_prior: null,
          benefits_budget: null,
          formula_aid_change: 0,
          statements: [{ topic: "Reserves", quote: "mostly depleted", source: "Budget Clarity Hub 2026-2027", url: "https://district.example/hub", date: null }],
        })}
      />,
    );
    expect(screen.queryByText("Employee benefits")).toBeNull();
    expect(screen.getByText(/No change from last year/)).toBeTruthy();
    expect(screen.getByText("mostly depleted").tagName).toBe("Q");
    expect(screen.getByText("Budget Clarity Hub 2026-2027").getAttribute("href")).toBe("https://district.example/hub");
  });

  it("links to the district's full budget page", () => {
    render(
      <MemoryRouter>
        <BudgetSection budget={budget({ slug: "cherry-hill-school-district" })} />
      </MemoryRouter>,
    );
    expect(screen.getByText("District budget")).toBeTruthy();
    expect(screen.getByText("See the full Cherry Hill Public Schools budget").getAttribute("href")).toBe("/budgets/cherry-hill-school-district");
  });

  it("formats small amounts in full and finds the prior year", () => {
    expect(money(5_795)).toBe("$5,795");
    expect(money(1_081_920)).toBe("$1.1M");
    expect(priorYear("2026-27")).toBe("2025-26");
    expect(priorYear("2099-00")).toBe("2098-99");
  });
});
