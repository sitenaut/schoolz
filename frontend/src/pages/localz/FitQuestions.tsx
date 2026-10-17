import type { Dispatch, SetStateAction } from "react";
import { useTranslation } from "react-i18next";
import { IconCheck } from "../../components/icons";
import { Switch } from "../../components/ui/Switch";
import { AGE_BANDS, type AgeBand, FIT_FOCUS, FIT_NEEDS, type FitAnswers, type FitFocus, type FitNeed } from "../../lib/localzFit";

export const AGE_LABELS: Record<AgeBand, string> = {
  u1: "Under 1",
  "1-4": "1–4",
  "5-12": "5–12",
  "13-17": "13–17",
  "18-59": "18–59",
  "60+": "60 or older",
};
export const NEED_LABELS: Record<FitNeed, string> = {
  veteran_military: "Veteran or military family",
  disability: "Someone with a disability",
  pregnant_or_new_baby: "Pregnant, or a baby under 1",
  uninsured: "No health insurance",
  job_loss: "Lost a job or hours",
};
export const FOCUS_LABELS: Record<FitFocus, string> = {
  women: "Women",
  men: "Men",
  lgbtq: "LGBTQ+",
  survivors: "Survivors of violence",
};

export const EMPTY_ANSWERS: FitAnswers = { ages: [], has: [], focus: [], noStatusFirst: false };

function toggle<T>(list: T[], value: T): T[] {
  return list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
}

/** The questions of "What am I eligible for?", shared by the Localz sheet
 * and the account's "My services profile" editor. Every one is optional.
 * Gender, race and immigration status are never asked: who a service
 * focuses on is a choice of what to look for, and immigration is only
 * "show programs that don't ask first". */
export function FitQuestions({ draft, setDraft }: { draft: FitAnswers; setDraft: Dispatch<SetStateAction<FitAnswers>> }) {
  const { t } = useTranslation();
  const chip = (pressed: boolean, label: string, onClick: () => void, key: string) => (
    <button type="button" className="chip localz-fit-chip" aria-pressed={pressed} onClick={onClick} key={key}>
      {pressed && <IconCheck />}
      {t(label)}
    </button>
  );

  return (
    <>
      <fieldset className="localz-fit-group">
        <legend>{t("Ages of the people you live with or share money with")}</legend>
        <p className="localz-muted">{t("Include yourself. Count kids who stay with you at least half the time.")}</p>
        <div className="localz-fit-chips">
          {AGE_BANDS.map((b) => chip(draft.ages.includes(b), AGE_LABELS[b], () => setDraft((d) => ({ ...d, ages: toggle(d.ages, b) })), b))}
        </div>
      </fieldset>

      <fieldset className="localz-fit-group">
        <legend>{t("Does any of this apply to you or your household?")}</legend>
        <div className="localz-fit-chips">
          {FIT_NEEDS.map((n) => chip(draft.has.includes(n), NEED_LABELS[n], () => setDraft((d) => ({ ...d, has: toggle(d.has, n) })), n))}
        </div>
      </fieldset>

      <fieldset className="localz-fit-group">
        <legend>{t("Show services that focus on…")}</legend>
        <p className="localz-muted">{t("Optional. This only adds matches - it never hides anything.")}</p>
        <div className="localz-fit-chips">
          {FIT_FOCUS.map((f) => chip(draft.focus.includes(f), FOCUS_LABELS[f], () => setDraft((d) => ({ ...d, focus: toggle(d.focus, f) })), f))}
        </div>
      </fieldset>

      <div className="localz-fit-group localz-fit-switch">
        <div>
          <div className="localz-fit-switch-label">{t("Show programs that don't ask about immigration status first")}</div>
          <p className="localz-muted">{t("Many programs don't ask. We never ask about anyone's status.")}</p>
        </div>
        <Switch
          checked={draft.noStatusFirst}
          onChange={(v) => setDraft((d) => ({ ...d, noStatusFirst: v }))}
          label={t("Show programs that don't ask about immigration status first")}
        />
      </div>
    </>
  );
}
