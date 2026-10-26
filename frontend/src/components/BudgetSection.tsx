import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { LOCALE } from "../lib/i18n";
import type { DistrictBudgetStatement, SchoolBudget } from "../types";

/** "2026-27" -> "2025-26" */
export function priorYear(year: string): string {
  const start = Number(year.slice(0, 4)) - 1;
  return `${start}-${String((start + 1) % 100).padStart(2, "0")}`;
}

/** $54.1M, but $412,092 and $5,795 in full: a small district's figures stay exact. */
export function money(v: number): string {
  const big = Math.abs(v) >= 1_000_000;
  return new Intl.NumberFormat(LOCALE, {
    style: "currency",
    currency: "USD",
    notation: big ? "compact" : "standard",
    maximumFractionDigits: big ? 1 : 0,
  }).format(v);
}

export function pct(v: number): string {
  return new Intl.NumberFormat(LOCALE, { style: "percent", maximumFractionDigits: 1, signDisplay: "exceptZero" }).format(v / 100);
}

function day(iso: string): string {
  return new Date(`${iso}T12:00:00`).toLocaleDateString(LOCALE, { month: "short", day: "numeric", year: "numeric" });
}

/** A few lines quoted from the district's own budget documents, each linked
 * to its source - shown only for districts whose audit profile supports them. */
export function BudgetQuotes({ statements }: { statements: DistrictBudgetStatement[] }) {
  const { t } = useTranslation();
  if (statements.length === 0) return null;
  return (
    <div className="budget-quotes">
      <b>{t("In the district's words")}</b>
      <ul>
        {statements.map((s) => (
          <li key={s.quote}>
            <span className="topic">{t(s.topic)}</span>
            <q lang="en">{s.quote}</q>{" "}
            <a href={s.url} target="_blank" rel="noreferrer">
              {s.date ? t("{{source}}, {{date}}", { source: s.source, date: day(s.date) }) : s.source}
            </a>
          </li>
        ))}
      </ul>
      <p className="note">
        {t("Quoted from the district's own budget documents. The district may count costs differently from the state's figures above.")}
      </p>
    </div>
  );
}

/** The school page's budget section: the district's figures from the state's
 * own files, each linked to its source, then (for some districts) a few lines
 * quoted from the district's own budget documents, and a link to the
 * district's full /budgets page. Every figure is the whole district's: the
 * state publishes none per school. Numbers and sources only: no rankings, and
 * nothing that reads as a verdict on the district. */
export function BudgetSection({ budget }: { budget: SchoolBudget }) {
  const { t } = useTranslation();
  const year = budget.budget_year;
  const prior = priorYear(year);
  const b = budget;
  const change = (v: number, up: string, down: string, fmt: (n: number) => string) =>
    v > 0 ? t(up, { amount: fmt(v), pct: fmt(v) }) : v < 0 ? t(down, { amount: fmt(-v), pct: fmt(-v) }) : t("No change from last year");
  return (
    <>
      <div className="h-row">
        <h2>{t("District budget")}</h2>
        {b.budget_report_url && (
          <a href={b.budget_report_url} target="_blank" rel="noreferrer">
            {t("State budget report")}
          </a>
        )}
      </div>
      <div className="sacc budget">
        <p className="note" style={{ marginTop: 0 }}>
          {t("{{district}}, {{year}} budget, from New Jersey Department of Education files.", { district: b.district_name, year })}
        </p>
        <ul className="qa">
          {b.benefits_prior != null && b.benefits_budget != null && (
            <li>
              <b>{t("Employee benefits")}</b>
              <span>
                {t("{{prior}}: {{from}} → {{year}}: {{to}} ({{change}})", {
                  prior,
                  year,
                  from: money(b.benefits_prior),
                  to: money(b.benefits_budget),
                  change: b.benefits_prior ? pct((b.benefits_budget / b.benefits_prior - 1) * 100) : "—",
                })}
                {b.prior_basis === "original" && ` ${t("The {{prior}} figure is the original budget; no revised one was filed.", { prior })}`}
              </span>
            </li>
          )}
          {b.formula_aid_change != null && (
            <li>
              <b>{t("State school aid")}</b>
              <span>
                {change(b.formula_aid_change, "Up {{amount}} from last year", "Down {{amount}} from last year", money)}{" "}
                {b.aid_source_url && (
                  <a href={b.aid_source_url} target="_blank" rel="noreferrer">
                    {t("State aid file")}
                  </a>
                )}
              </span>
            </li>
          )}
          {b.levy_change_pct != null && (
            <li>
              <b>{t("Local school tax levy")}</b>
              <span>{change(b.levy_change_pct, "Up {{pct}} from last year", "Down {{pct}} from last year", (n) => pct(n).replace(/^[+-]/, ""))}</span>
            </li>
          )}
          {b.fund_balance_prior != null && b.fund_balance_budget != null && (
            <li>
              <b>{t("Surplus budgeted to balance the budget")}</b>
              <span>{t("{{prior}}: {{from}} → {{year}}: {{to}}", { prior, year, from: money(b.fund_balance_prior), to: money(b.fund_balance_budget) })}</span>
              {/* UFB "Budgeted Fund Balance-Operating Budget": what the district plans to spend, which a parent could easily read as what's left */}
              <small className="note" style={{ display: "block" }}>
                {t("Planned amount, not what is left in reserve. Does not include capital or maintenance reserve withdrawals.")}
              </small>
            </li>
          )}
        </ul>
        <BudgetQuotes statements={b.statements} />
        {b.slug && (
          <p style={{ margin: "12px 0 0" }}>
            <Link to={`/budgets/${b.slug}`}>{t("See the full {{district}} budget", { district: b.district_name })}</Link>
          </p>
        )}
      </div>
    </>
  );
}
