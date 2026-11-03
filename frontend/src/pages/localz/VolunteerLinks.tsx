import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { apiFetch } from "../../api";
import { useSeasons, type SeasonalAttraction } from "../../lib/seasonal";

// Volunteer directories that cover New Jersey, by link. Nothing of theirs is
// imported: Idealist's terms forbid scraping, and NJ 211 (where Localz
// listings come from) lists almost no volunteer work to map a category to.
const DIRECTORIES: { name: string; url: string; blurb: string }[] = [
  {
    name: "Volunteer Center of South Jersey",
    url: "https://sjvolunteers.galaxydigital.com/need/",
    blurb: "Needs across South Jersey, with a family-friendly filter",
  },
  { name: "Jersey Cares", url: "https://www.jerseycares.org/", blurb: "Service projects around New Jersey, some for kids" },
  { name: "Idealist", url: "https://www.idealist.org/en/volunteer", blurb: "Volunteer listings anywhere, VolunteerMatch's included" },
  { name: "JustServe", url: "https://www.justserve.org/", blurb: "Free listings of local service projects" },
];

const SEASON_LINK: Record<string, string> = {
  fall: "Thanksgiving volunteering for families",
  winter: "Christmas volunteering for families",
};

/** Seasons whose badge is up and whose page lists volunteering, so the
 * link lands on something. [] until both requests answer, and on failure. */
function useVolunteerSeasons() {
  const { seasons } = useSeasons();
  const [withVolunteering, setWithVolunteering] = useState<Set<string>>(new Set());
  useEffect(() => {
    let cancelled = false;
    apiFetch("/seasonal-attractions?kind=volunteer")
      .then((r) => (r.ok ? r.json() : []))
      .catch(() => [])
      .then((rows: SeasonalAttraction[]) => !cancelled && setWithVolunteering(new Set(rows.map((a) => a.season))));
    return () => {
      cancelled = true;
    };
  }, []);
  return seasons.filter((s) => withVolunteering.has(s.season));
}

/** "Want to help?" at the foot of the Localz home page: the other side of
 * the same community, for people with time to give. */
export function VolunteerLinks() {
  const { t } = useTranslation();
  const seasons = useVolunteerSeasons();
  return (
    <section className="localz-give" aria-labelledby="localz-give-title">
      <h3 id="localz-give-title">{t("Want to help?")}</h3>
      <p className="localz-muted">{t("Volunteer near you, or give what a program needs.")}</p>
      {seasons.length > 0 && (
        <ul className="localz-give-seasons">
          {seasons.map((s) => (
            <li key={s.season}>
              <Link className="btn" to={`/seasonal/${s.season}#kind-volunteer`}>
                <span aria-hidden="true">{s.emoji}</span>
                {t(SEASON_LINK[s.season] ?? "Volunteering this season")}
              </Link>
            </li>
          ))}
        </ul>
      )}
      <ul className="localz-give-links">
        {DIRECTORIES.map((d) => (
          <li key={d.url}>
            <a href={d.url} target="_blank" rel="noopener noreferrer">
              {d.name}
            </a>
            <span className="localz-muted"> · {t(d.blurb)}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
