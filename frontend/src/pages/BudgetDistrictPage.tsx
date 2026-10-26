import { useEffect, useState, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { apiFetch } from "../api";
import { BudgetQuotes, money, pct, priorYear } from "../components/BudgetSection";
import { SeoHead } from "../components/SeoHead";
import { LOCALE } from "../lib/i18n";
import { usePrerenderReady } from "../lib/prerenderReady";
import type { BudgetChange, BudgetDistrict, BudgetMedian } from "../types";

const ratio = (v: number) => new Intl.NumberFormat(LOCALE, { maximumFractionDigits: 1 }).format(v);
const change = (from: number, to: number) => (from ? pct((to / from - 1) * 100) : "—");
const dollars = (v: number) => new Intl.NumberFormat(LOCALE, { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(v);

/** Both sides of a change, in full where rounding would print the same
 * figure twice ("$3M → $3M (-1%)"). */
function moneyPair(from: number, to: number): [string, string] {
  const [a, b] = [money(from), money(to)];
  return a === b && from !== to ? [dollars(from), dollars(to)] : [a, b];
}

/** The state aid file's categories (keys from scripts/build_budget_facts.py). */
const AID_CATEGORIES: Record<string, string> = {
  equalization: "Equalization aid",
  special_education: "Special education aid",
  transportation: "Transportation aid",
  security: "Security aid",
  educational_adequacy: "Educational adequacy aid",
  school_choice: "School choice aid",
  vocational_expansion: "Vocational expansion stabilization aid",
  military_impact: "Military impact aid",
};

/** "<label> 2025-26, 2026-27", each year linked to the file it came from. */
function YearLinks({ label, figures }: { label: string; figures: BudgetChange }) {
  const years = [figures.start, figures.end].filter((y) => y.url);
  if (years.length === 0) return null;
  return (
    <>
      {label}{" "}
      {years.map((y, i) => (
        <span key={y.year}>
          {i > 0 && ", "}
          <a href={y.url ?? undefined} target="_blank" rel="noreferrer" style={{ whiteSpace: "nowrap" }}>
            {y.year}
          </a>
        </span>
      ))}
    </>
  );
}

/** /budgets/:slug: one district's budget year in full - spending, where the
 * money comes from, audited health costs and staffing - each figure linked
 * to the state file it came from and set against the county and state
 * medians. Numbers and sources only: no ranking, and no label that reads as
 * a verdict on the district. */
export function BudgetDistrictPage() {
  const { t } = useTranslation();
  const { slug } = useParams();
  // Kept with the slug it was loaded for, so moving to another district never
  // shows the last one's figures while the next loads.
  const [loaded, setLoaded] = useState<{ slug: string; budget: BudgetDistrict | null } | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let current = true;
    apiFetch(`/budgets/${slug}`)
      .then((r): Promise<BudgetDistrict> | null => {
        if (r.status === 404) return null;
        if (!r.ok) throw new Error(`budget ${r.status}`);
        return r.json();
      })
      .then(
        (b) => {
          if (!current) return;
          setFailed(false);
          setLoaded({ slug: slug ?? "", budget: b });
        },
        () => current && setFailed(true),
      );
    return () => {
      current = false;
    };
  }, [slug, attempt]);
  const here = loaded?.slug === slug ? loaded : null;
  const budget = here?.budget ?? null;
  const missing = !!here && !here.budget;
  // Not on `failed`: a crawler's render would store the error page.
  usePrerenderReady(!!budget || missing);

  if (missing) {
    return (
      <div className="empty">
        <p>{t("District not found.")}</p>
        <Link to="/budgets">{t("All district budgets")}</Link>
      </div>
    );
  }
  if (failed) {
    return (
      <div className="empty">
        <p>{t("Couldn't load this budget just now.")}</p>
        <button type="button" className="btn" onClick={() => setAttempt((n) => n + 1)}>
          {t("Try again")}
        </button>
      </div>
    );
  }
  if (!budget) return <p className="note">{t("Loading…")}</p>;

  const b = budget;
  const year = b.budget_year;
  const prior = priorYear(year);
  const fromTo = (from: number, to: number) => {
    const [a, z] = moneyPair(from, to);
    return t("{{prior}}: {{from}} → {{year}}: {{to}} ({{change}})", { prior, year, from: a, to: z, change: change(from, to) });
  };
  const amounts = (from: number, to: number) => {
    const [a, z] = moneyPair(from, to);
    return t("{{from}} → {{to}}", { from: a, to: z });
  };
  const median = (m: BudgetMedian | undefined, fmt: (n: number) => string): ReactNode => {
    if (!m || (m.county == null && m.state == null) || !b.comparable) return null;
    const parts = [
      m.county != null && b.county && t("{{county}} County median {{value}}", { county: b.county, value: fmt(m.county) }),
      m.state != null && t("New Jersey median {{value}}", { value: fmt(m.state) }),
    ].filter(Boolean);
    return <small className="note budget-median">{parts.join(" · ")}</small>;
  };
  const spendingPrior = b.benefits_prior != null && b.other_spending_prior != null ? b.benefits_prior + b.other_spending_prior : null;
  const spendingBudget = b.benefits_budget != null && b.other_spending_budget != null ? b.benefits_budget + b.other_spending_budget : null;
  const health = b.health_costs;
  const staffing = b.staffing;
  const aid = b.state_aid;
  const idea = b.idea_grant;
  const levyChange = (n: number) =>
    n > 0 ? t("Up {{pct}} from last year", { pct: pct(n).replace(/^[+-]/, "") }) : n < 0 ? t("Down {{pct}} from last year", { pct: pct(n).replace(/^[+-]/, "") }) : t("No change from last year");
  const limitNote = (limit: number) => {
    const p = pct(Math.abs(limit)).replace(/^[+-]/, "");
    return limit < 0
      ? t(
          "Equalization, special education, transportation and security aid together can fall by no more than {{pct}} a year, and this district is at that limit: the formula alone would have cut them further.",
          { pct: p },
        )
      : t(
          "Equalization, special education, transportation and security aid together can rise by no more than {{pct}} a year, and this district is at that limit: the formula alone would have given more.",
          { pct: p },
        );
  };

  return (
    <div className="budget-page">
      <SeoHead
        title={t("{{district}} budget {{year}} · schoolz", { district: b.name, year })}
        description={t(
          "{{district}}'s {{year}} school budget from the state's own files: employee benefits, state aid, the local school tax levy, health insurance costs and class sizes, against the county and state.",
          { district: b.name, year },
        )}
        path={`/budgets/${b.slug}`}
      />
      <p className="note" style={{ margin: 0 }}>
        <Link to="/budgets">{t("All district budgets")}</Link>
      </p>
      <div className="h-row">
        <h2>{b.name}</h2>
        {b.budget_report_url && (
          <a href={b.budget_report_url} target="_blank" rel="noreferrer">
            {t("State budget report")}
          </a>
        )}
      </div>
      <p className="note" style={{ marginTop: 0 }}>
        {b.county
          ? t("{{county}} County · {{year}} budget, from New Jersey Department of Education files.", { county: b.county, year })
          : t("{{year}} budget, from New Jersey Department of Education files.", { year })}{" "}
        {t("Budgets are set for a whole district, so every school in it shares these figures.")}
      </p>

      {(spendingPrior != null || b.benefits_prior != null) && (
        <>
          <div className="section-title">{t("Spending")}</div>
          <div className="sacc budget">
            <ul className="qa">
              {spendingPrior != null && spendingBudget != null && (
                <li>
                  <b>{t("Day-to-day spending")}</b>
                  <span>{fromTo(spendingPrior, spendingBudget)}</span>
                  <small className="note" style={{ display: "block" }}>
                    {t("The general fund's current expense: salaries, benefits, supplies and services. Not building projects or debt.")}
                  </small>
                </li>
              )}
              {b.benefits_prior != null && b.benefits_budget != null && (
                <li>
                  <b>{t("Employee benefits")}</b>
                  <span>
                    {fromTo(b.benefits_prior, b.benefits_budget)}
                    {b.prior_basis === "original" && ` ${t("The {{prior}} figure is the original budget; no revised one was filed.", { prior })}`}
                  </span>
                  {spendingBudget ? (
                    <small className="note" style={{ display: "block" }}>
                      {t("{{share}} of day-to-day spending.", { share: pct((b.benefits_budget / spendingBudget) * 100).replace(/^\+/, "") })}
                    </small>
                  ) : null}
                  {median(b.medians.benefits_change_pct, pct)}
                </li>
              )}
              {b.other_spending_prior != null && b.other_spending_budget != null && (
                <li>
                  <b>{t("Everything else")}</b>
                  <span>{fromTo(b.other_spending_prior, b.other_spending_budget)}</span>
                  {median(b.medians.other_spending_change_pct, pct)}
                </li>
              )}
            </ul>
          </div>
        </>
      )}

      <div className="section-title">{t("Where the money comes from")}</div>
      <div className="sacc budget">
        <ul className="qa">
          {b.levy_change_pct != null && (
            <li>
              <b>{t("Local school tax levy")}</b>
              <span>{b.levy_prior != null && b.levy_budget != null ? fromTo(b.levy_prior, b.levy_budget) : levyChange(b.levy_change_pct)}</span>
              {median(b.medians.levy_change_pct, pct)}
            </li>
          )}
          {aid ? (
            <>
              <li>
                <b>{t("State school aid, K–12")}</b>
                <span>{fromTo(aid.k12.start.value, aid.k12.end.value)}</span>
                {median(b.medians.state_aid_change_pct, pct)}
                {aid.categories.length > 0 && (
                  <ul className="budget-breakdown">
                    {aid.categories.map((c) => (
                      <li key={c.key}>
                        <span>{t(AID_CATEGORIES[c.key] ?? c.key)}</span>
                        <span>{amounts(c.start, c.end)}</span>
                      </li>
                    ))}
                  </ul>
                )}
                <small className="note" style={{ display: "block" }}>
                  {aid.limit_pct != null && <>{limitNote(aid.limit_pct)} </>}
                  {aid.categories.some((c) => c.key === "equalization") && (
                    <>
                      {t(
                        "Equalization aid is based on the gap between what the state's formula says a district needs and the share it expects local taxes to raise.",
                      )}{" "}
                    </>
                  )}
                  <YearLinks label={t("From the state's aid files:")} figures={aid.k12} />
                </small>
              </li>
              {aid.preschool && (
                <li>
                  <b>{t("State preschool aid")}</b>
                  <span>{fromTo(aid.preschool.start.value, aid.preschool.end.value)}</span>
                  <small className="note" style={{ display: "block" }}>
                    {t("Paid into a separate fund that can only be spent on preschool.")}{" "}
                    <YearLinks label={t("From the state's preschool aid files:")} figures={aid.preschool} />
                  </small>
                </li>
              )}
            </>
          ) : (
            b.formula_aid_change != null && (
              <li>
                <b>{t("State school aid")}</b>
                <span>
                  {b.formula_aid_change > 0
                    ? t("Up {{amount}} from last year", { amount: money(b.formula_aid_change) })
                    : b.formula_aid_change < 0
                      ? t("Down {{amount}} from last year", { amount: money(-b.formula_aid_change) })
                      : t("No change from last year")}{" "}
                  {b.aid_source_url && (
                    <a href={b.aid_source_url} target="_blank" rel="noreferrer">
                      {t("State aid file")}
                    </a>
                  )}
                </span>
              </li>
            )
          )}
          {idea && (
            <li>
              <b>{t("Federal special education grant (IDEA)")}</b>
              <span>{fromTo(idea.start.value, idea.end.value)}</span>
              {median(b.medians.idea_change_pct, pct)}
              <small className="note" style={{ display: "block" }}>
                {t("Federal money for students with disabilities, ages 3 to 21.")}{" "}
                {idea.preliminary && <>{t("The {{year}} award is the state's preliminary figure.", { year: idea.end.year })} </>}
                {!!idea.private_school_share && (
                  <>
                    {t("{{amount}} of it is set aside for students with disabilities whose parents placed them in private schools.", {
                      amount: money(idea.private_school_share),
                    })}{" "}
                  </>
                )}
                <YearLinks label={t("From the state's IDEA award files:")} figures={idea} />
              </small>
            </li>
          )}
          {b.fund_balance_prior != null && b.fund_balance_budget != null && (
            <li>
              <b>{t("Surplus budgeted to balance the budget")}</b>
              <span>{t("{{prior}}: {{from}} → {{year}}: {{to}}", { prior, year, from: money(b.fund_balance_prior), to: money(b.fund_balance_budget) })}</span>
              <small className="note" style={{ display: "block" }}>
                {t("Planned amount, not what is left in reserve. Does not include capital or maintenance reserve withdrawals.")}
              </small>
            </li>
          )}
        </ul>
      </div>

      {health && (
        <>
          <div className="section-title">{t("Health insurance costs")}</div>
          <div className="sacc budget">
            <ul className="qa">
              <li>
                <b>{t("Health benefits, audited")}</b>
                <span>
                  {t("{{prior}}: {{from}} → {{year}}: {{to}} ({{change}})", {
                    prior: health.start.year,
                    year: health.end.year,
                    from: money(health.start.value),
                    to: money(health.end.value),
                    change: change(health.start.value, health.end.value),
                  })}
                </span>
                {median(b.medians.health_change_pct, pct)}
                <small className="note" style={{ display: "block" }}>
                  <YearLinks label={t("What the district actually spent, from its audited annual financial reports:")} figures={health} />
                </small>
              </li>
            </ul>
          </div>
        </>
      )}

      {staffing && (staffing.students_per_teacher || staffing.median_teacher_salary) && (
        <>
          <div className="section-title">{t("Teachers")}</div>
          <div className="sacc budget">
            <ul className="qa">
              {staffing.students_per_teacher && (
                <li>
                  <b>{t("Students per teacher")}</b>
                  <span>
                    {t("{{prior}}: {{from}} → {{year}}: {{to}}", {
                      prior: staffing.students_per_teacher.start.year,
                      year: staffing.students_per_teacher.end.year,
                      from: ratio(staffing.students_per_teacher.start.value),
                      to: ratio(staffing.students_per_teacher.end.value),
                    })}
                  </span>
                  {median(b.medians.students_per_teacher, ratio)}
                </li>
              )}
              {staffing.median_teacher_salary && (
                <li>
                  <b>{t("Median teacher salary")}</b>
                  <span>
                    {t("{{year}}: {{amount}}", { year: staffing.median_teacher_salary.year, amount: money(staffing.median_teacher_salary.value) })}
                  </span>
                  {median(b.medians.median_teacher_salary, money)}
                </li>
              )}
            </ul>
            <small className="note" style={{ display: "block", marginTop: 8 }}>
              <a href={staffing.url} target="_blank" rel="noreferrer">
                {t("New Jersey School Performance Reports")}
              </a>
            </small>
          </div>
        </>
      )}

      {b.statements.length > 0 && (
        <div className="sacc budget budget-quotes-card">
          <BudgetQuotes statements={b.statements} />
        </div>
      )}

      {b.comparable === false && (
        <p className="note">
          {t(
            "This district isn't counted in the county and state medians: its budget isn't comparable with a typical district's (a services commission, a very small benefits line, or state aid outside the school funding formula).",
          )}
        </p>
      )}
      {b.comparable && (
        <p className="note">
          {t("Medians are across districts whose budgets are comparable; services commissions and districts outside the state aid formula are left out.")}
        </p>
      )}

      {b.schools.length > 0 && (
        <>
          <div className="section-title">{t("Schools on schoolz")}</div>
          <div className="sgrid">
            {b.schools.map((s) => (
              <Link key={s.slug} className="sopt" to={`/schools/${s.slug}`}>
                {s.name}
              </Link>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
