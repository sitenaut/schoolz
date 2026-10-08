import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useSeasons } from "../lib/seasonal";

/** One line per running season, linking to /seasonal/<season> - the
 * Calendar's (and Local's) single entry for a whole season, rather than a
 * calendar item per night. Renders nothing when no season is running. */
export function SeasonalBanner() {
  const { t } = useTranslation();
  const { seasons } = useSeasons();
  if (!seasons.length) return null;
  return (
    <div className="seasonal-banners">
      {seasons.map((s) => (
        <Link key={s.season} to={`/seasonal/${s.season}`} className="link-card seasonal-banner">
          <span className="season-emoji" aria-hidden="true">
            {s.emoji}
          </span>
          <span>
            <b>{s.guides[0].title}</b>
            <small>
              {t("Seasonal guides")}
              {s.guides.length > 1 ? ` · +${s.guides.length - 1}` : ""} →
            </small>
          </span>
        </Link>
      ))}
    </div>
  );
}
