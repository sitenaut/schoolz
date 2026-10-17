import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { IconClock, IconPhone, IconPin } from "../../components/icons";
import { type ResourceSummary, telHref } from "../../lib/localz";
import type { Fit } from "../../lib/localzFit";
import { FitNote } from "./FitNote";
import { ClosureNote } from "./ClosureNote";
import { ProgramNotes, deliveryLabel } from "./ProgramNotes";

/** One service in a list: what it is, who runs it, where, when, and a phone
 * number you can tap. The details page has the rest. */
export function ResourceCard({ r, fit }: { r: ResourceSummary; fit?: Fit | null }) {
  const { t } = useTranslation();
  const org = r.organization_name && r.organization_name !== r.name ? r.organization_name : null;
  const place = r.city || r.address;
  const away = r.distance_miles === undefined ? null : r.distance_miles < 1 ? t("under 1 mi") : t("{{miles}} mi", { miles: Math.round(r.distance_miles) });
  const online = deliveryLabel(r.delivery);
  const where = [place, away, online && t(online)].filter(Boolean).join(" · ");
  return (
    <article className={`localz-card${fit?.level === "yes" ? " fits" : ""}`}>
      <Link className="localz-card-title" to={`/localz/r/${r.id}`}>
        {r.name}
      </Link>
      {org && <div className="localz-card-org">{org}</div>}
      {fit && <FitNote fit={fit} />}
      {r.statewide && <span className="tag localz-tag">{t("Statewide")}</span>}
      {r.closure && <ClosureNote closure={r.closure} />}
      {r.description && <p className="localz-card-desc">{r.description}</p>}
      <div className="localz-card-facts">
        {r.location_confidential && (
          <span>
            <IconPin />
            {t("Location shared after you call")}
          </span>
        )}
        {where && (
          <span>
            <IconPin />
            {where}
          </span>
        )}
        {r.hours_text && (
          <span>
            <IconClock />
            {r.hours_text}
          </span>
        )}
      </div>
      <ProgramNotes r={r} />
      <div className="localz-card-actions">
        {r.phone && (
          <a className="btn localz-call" href={telHref(r.phone)}>
            <IconPhone />
            {r.phone}
          </a>
        )}
        <Link className="btn ghost" to={`/localz/r/${r.id}`}>
          {t("Details")}
        </Link>
        {!r.complete && <span className="localz-card-note">{t("Call to confirm details")}</span>}
      </div>
    </article>
  );
}
