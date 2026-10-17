import { useState } from "react";
import { useTranslation } from "react-i18next";
import { IconCheck } from "../../components/icons";
import { Modal } from "../../components/ui/Modal";
import { Switch } from "../../components/ui/Switch";
import {
  AGE_BANDS,
  type AgeBand,
  FIT_FOCUS,
  FIT_NEEDS,
  type FitAnswers,
  type FitFocus,
  type FitNeed,
  saveFit,
  useLocalzFit,
} from "../../lib/localzFit";

const AGE_LABELS: Record<AgeBand, string> = {
  u1: "Under 1",
  "1-4": "1–4",
  "5-12": "5–12",
  "13-17": "13–17",
  "18-59": "18–59",
  "60+": "60 or older",
};
const NEED_LABELS: Record<FitNeed, string> = {
  veteran_military: "Veteran or military family",
  disability: "Someone with a disability",
  pregnant_or_new_baby: "Pregnant, or a baby under 1",
  uninsured: "No health insurance",
  job_loss: "Lost a job or hours",
};
const FOCUS_LABELS: Record<FitFocus, string> = {
  women: "Women",
  men: "Men",
  lgbtq: "LGBTQ+",
  survivors: "Survivors of violence",
};

const EMPTY: FitAnswers = { ages: [], has: [], focus: [], noStatusFirst: false };

function toggle<T>(list: T[], value: T): T[] {
  return list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
}

/** "What am I eligible for?" - or, once answered, "Showing what fits you" -
 * and the sheet behind it. Every question is optional, nothing is required
 * to see listings, and the answers stay on this device (lib/localzFit.ts).
 * Gender, race and immigration status are never asked: who a service
 * focuses on is a choice of what to look for, and immigration is only
 * "show programs that don't ask first". */
export function FitButton() {
  const { t } = useTranslation();
  const saved = useLocalzFit();
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<FitAnswers>(EMPTY);
  const [remember, setRemember] = useState(false);

  const start = () => {
    setDraft(saved?.answers ?? EMPTY);
    setRemember(saved?.remember ?? false);
    setOpen(true);
  };
  const apply = () => {
    saveFit(draft, remember);
    setOpen(false);
  };
  const clear = () => {
    saveFit(null);
    setDraft(EMPTY);
    setOpen(false);
  };

  const chip = (pressed: boolean, label: string, onClick: () => void, key: string) => (
    <button type="button" className="chip localz-fit-chip" aria-pressed={pressed} onClick={onClick} key={key}>
      {pressed && <IconCheck />}
      {t(label)}
    </button>
  );

  return (
    <>
      <button className={`btn localz-fit-btn${saved ? " on" : ""}`} onClick={start}>
        <IconCheck />
        {saved ? t("Showing what fits you · Edit") : t("What am I eligible for?")}
      </button>
      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title={t("What am I eligible for?")}
        subtitle={t("Answer any of these, or none. Listings that fit get a check mark and move to the top.")}
        footer={
          <>
            {saved && (
              <button type="button" className="btn ghost" onClick={clear}>
                {t("Clear my answers")}
              </button>
            )}
            <button type="button" className="btn btn-primary" onClick={apply}>
              {t("Show what fits me")}
            </button>
          </>
        }
      >
        <div className="localz-fit-sheet">
          <fieldset className="localz-fit-group">
            <legend>{t("Ages of the people you live with or share money with")}</legend>
            <p className="localz-muted">{t("Include yourself. Count kids who stay with you at least half the time.")}</p>
            <div className="localz-fit-chips">
              {AGE_BANDS.map((b) =>
                chip(draft.ages.includes(b), AGE_LABELS[b], () => setDraft((d) => ({ ...d, ages: toggle(d.ages, b) })), b),
              )}
            </div>
          </fieldset>

          <fieldset className="localz-fit-group">
            <legend>{t("Does any of this apply to you or your household?")}</legend>
            <div className="localz-fit-chips">
              {FIT_NEEDS.map((n) =>
                chip(draft.has.includes(n), NEED_LABELS[n], () => setDraft((d) => ({ ...d, has: toggle(d.has, n) })), n),
              )}
            </div>
          </fieldset>

          <fieldset className="localz-fit-group">
            <legend>{t("Show services that focus on…")}</legend>
            <p className="localz-muted">{t("Optional. This only adds matches - it never hides anything.")}</p>
            <div className="localz-fit-chips">
              {FIT_FOCUS.map((f) =>
                chip(draft.focus.includes(f), FOCUS_LABELS[f], () => setDraft((d) => ({ ...d, focus: toggle(d.focus, f) })), f),
              )}
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

          <div className="localz-fit-group localz-fit-switch">
            <div>
              <div className="localz-fit-switch-label">{t("Remember on this device")}</div>
              <p className="localz-muted">
                {remember
                  ? t("Kept on this phone or computer until you clear it. Anyone using it could see your answers.")
                  : t("Otherwise your answers are forgotten when you close this tab or use Quick exit.")}
              </p>
            </div>
            <Switch checked={remember} onChange={setRemember} label={t("Remember on this device")} />
          </div>

          <p className="localz-where-privacy">{t("Your answers never leave this device. Localz matches them here, on your screen.")}</p>
        </div>
      </Modal>
    </>
  );
}
