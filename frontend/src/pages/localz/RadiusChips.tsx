import { useTranslation } from "react-i18next";
import { DEFAULT_RADIUS, RADIUS_CHOICES, saveRadius, useLocalzScope } from "../../lib/localzWhere";

/** How far to look: 2 to 50 miles from the visitor's point, or Statewide.
 * With only a county (no ZIP or phone location), it's that county or
 * Statewide. Kept on the device like the location itself. */
export function RadiusChips() {
  const { t } = useTranslation();
  const { where, radius } = useLocalzScope();
  if (!where) return null;
  const hasPoint = where.lat !== undefined && where.lon !== undefined;
  const choices = hasPoint
    ? RADIUS_CHOICES.map((r) => ({ value: r, label: r === "all" ? t("Statewide") : t("{{miles}} mi", { miles: r }) }))
    : [
        { value: DEFAULT_RADIUS, label: t("{{county}} County", { county: where.county }) },
        { value: "all" as const, label: t("Statewide") },
      ];
  const isOn = (value: number | "all") => (hasPoint ? radius === value : (radius === "all") === (value === "all"));
  return (
    <div className="localz-radius" role="group" aria-label={t("How far to look")}>
      <span className="localz-muted">{t("How far:")}</span>
      {choices.map((c) => (
        <button type="button" key={String(c.value)} className="chip" aria-pressed={isOn(c.value)} onClick={() => saveRadius(c.value)}>
          {c.label}
        </button>
      ))}
    </div>
  );
}

/** "Closest first, within 5 miles" under a list's count. */
export function RadiusNote({ miles }: { miles: number }) {
  const { t } = useTranslation();
  return <p className="localz-muted localz-radius-note">{t("Closest first, within {{miles}} miles. Phone, online and statewide help follows.", { miles })}</p>;
}
