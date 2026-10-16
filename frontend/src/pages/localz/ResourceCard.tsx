import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { IconClock, IconPhone, IconPin } from "../../components/icons";
import { type ResourceSummary, telHref } from "../../lib/localz";

/** One service in a list: what it is, who runs it, where, when, and a phone
 * number you can tap. The details page has the rest. */
export function ResourceCard({ r }: { r: ResourceSummary }) {
  const { t } = useTranslation();
  const org = r.organization_name && r.organization_name !== r.name ? r.organization_name : null;
  const where = r.city || r.address;
  return (
    <article className="localz-card">
      <Link className="localz-card-title" to={`/localz/r/${r.id}`}>
        {r.name}
      </Link>
      {org && <div className="localz-card-org">{org}</div>}
      {r.statewide && <span className="tag localz-tag">{t("Statewide")}</span>}
      {r.description && <p className="localz-card-desc">{r.description}</p>}
      <div className="localz-card-facts">
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
