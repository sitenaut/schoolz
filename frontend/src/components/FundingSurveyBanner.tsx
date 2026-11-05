import { useState } from "react";
import { useTranslation } from "react-i18next";
import { IconX } from "./icons";
import { todayKey } from "../lib/calendar";
import { LOCALE } from "../lib/i18n";
import { trackEvent } from "../lib/track";

// The NJ Department of Education's school funding survey ("Funding New
// Jersey's Future"), which every family should fill out. The form's own
// address, without the fbclid a copy shared on Facebook carries.
export const SURVEY_URL =
  "https://forms.cloud.microsoft/Pages/ResponsePage.aspx?id=EnNPSwndWUm2ZtW6bcj0tIkxDUlKfmpLkwSbmTabocBUMDRROVBTVUNTSlFaMktXNE9NV1lSWjRYUC4u";

// The state hasn't said when the survey closes. December 1 is a placeholder:
// the banner stops showing after it, but names it only once it's confirmed
// (set LAST_DAY_CONFIRMED).
export const LAST_DAY = "2026-12-01";
export const LAST_DAY_CONFIRMED = false;

const DONE_KEY = "schoolz_funding_survey_done";

type Props = { today?: string; lastDay?: string; showLastDay?: boolean };

/** Asks every visitor to take the survey until its last day. Gone for good
 * on this device once opened or closed, and never in the prerender's
 * browser: a crawler's snapshot would keep it past the last day. */
export function FundingSurveyBanner({ today = todayKey(), lastDay = LAST_DAY, showLastDay = LAST_DAY_CONFIRMED }: Props) {
  const { t } = useTranslation();
  const [done, setDone] = useState(() => {
    try {
      return localStorage.getItem(DONE_KEY) === "1";
    } catch {
      return false;
    }
  });
  if (done || today > lastDay || navigator.webdriver) return null;
  const finish = () => {
    try {
      localStorage.setItem(DONE_KEY, "1");
    } catch {
      /* ignore */
    }
    setDone(true);
  };
  const date = new Date(`${lastDay}T12:00:00Z`).toLocaleDateString(LOCALE, { month: "long", day: "numeric", timeZone: "UTC" });
  return (
    <div className="survey-banner" role="region" aria-label={t("School funding survey")}>
      <a
        className="link-card survey-cta"
        href={SURVEY_URL}
        target="_blank"
        rel="noreferrer"
        onClick={() => {
          trackEvent("cta_click", { page: "banner", cta: "nj_funding_survey" });
          // After the click: a link taken out of the page while it's being
          // clicked isn't followed.
          window.setTimeout(finish, 0);
        }}
      >
        <span className="season-emoji" aria-hidden="true">
          📋
        </span>
        <span>
          <b>{t("Have a say in how New Jersey funds its schools")}</b>
          <small>
            {t("Take the New Jersey Department of Education's 5-minute survey")}
            {showLastDay ? ` · ${t("Open until {{date}}", { date })}` : ""}
            {" →"}
          </small>
        </span>
      </a>
      <button className="btn icon survey-dismiss" onClick={finish} aria-label={t("Close")}>
        <IconX />
      </button>
    </div>
  );
}
