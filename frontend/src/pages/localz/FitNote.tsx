import { useTranslation } from "react-i18next";
import { IconCheck } from "../../components/icons";
import type { Fit, FitLabel } from "../../lib/localzFit";

const PILLS: Record<Fit["level"], string | null> = {
  yes: "For you",
  open: "Open to everyone",
  check: "Check if you qualify",
  no: null,
};

/** A listing's fit, for a card or the details page: a pill (a check mark
 * for "For you"; never a red mark or "not eligible") and, beside it, who the
 * listing says it's for. */
export function FitNote({ fit }: { fit: Fit }) {
  const { t } = useTranslation();
  const label = (l: FitLabel) => t(l.text, l.vars);
  const pill = PILLS[fit.level];
  const asks = fit.asks.map(label).join(" · ");
  return (
    <div className={`localz-fit localz-fit-${fit.level}`}>
      {pill && (
        <span className="localz-fit-pill">
          {fit.level === "yes" && <IconCheck />}
          {t(pill)}
        </span>
      )}
      {asks && <span className="localz-fit-asks">{fit.level === "no" ? t("For: {{who}}", { who: asks }) : asks}</span>}
      {fit.asksStatus && <span className="localz-fit-asks">{t("Asks about immigration status")}</span>}
    </div>
  );
}
