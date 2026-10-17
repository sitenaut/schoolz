import { type ReactNode, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { SeoHead } from "../../components/SeoHead";
import { IconAlert, IconChevronLeft, IconClock, IconLink, IconMail, IconPhone, IconPin } from "../../components/icons";
import { LOCALE } from "../../lib/i18n";
import { type ResourceDetail, categoryByKey, confirmedLabel, fetchResource, isFree, mapsHref, telHref } from "../../lib/localz";
import { describe, fitFor, useLocalzFit } from "../../lib/localzFit";
import { usePrerenderReady } from "../../lib/prerenderReady";
import { FitNote } from "./FitNote";
import { ClosureNote } from "./ClosureNote";
import { ProgramNotes, deliveryLabel } from "./ProgramNotes";

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="localz-detail-section">
      <h3>{title}</h3>
      {children}
    </section>
  );
}

/** /localz/r/:id - everything about one service, in the order someone needs
 * it: can I go, when, how do I get help, what do I bring. */
export function LocalzResourcePage() {
  const { resourceId } = useParams();
  return <ResourceView key={resourceId} resourceId={resourceId} />;
}

function ResourceView({ resourceId }: { resourceId: string | undefined }) {
  const { t } = useTranslation();
  const [r, setR] = useState<ResourceDetail | null | undefined>(undefined);
  const [error, setError] = useState(false);
  const answers = useLocalzFit()?.answers ?? null;

  useEffect(() => {
    if (!resourceId) return;
    fetchResource(resourceId)
      .then(setR)
      .catch(() => setError(true));
  }, [resourceId]);
  usePrerenderReady(r !== undefined || error);

  if (error) return <p className="note">{t("Couldn't load this just now. Try again in a moment.")}</p>;
  if (r === undefined) return <p className="note">{t("Loading…")}</p>;
  if (r === null)
    return (
      <p className="note">
        {t("This listing isn't available any more.")} <Link to="/localz">{t("See all kinds of help")}</Link>
      </p>
    );

  const category = categoryByKey(r.categories[0]);
  const org = r.organization_name && r.organization_name !== r.name ? r.organization_name : null;
  const place = [r.address, r.city, r.postal_code].filter(Boolean).join(", ");
  const fit = fitFor(r.eligibility, answers);
  const asks = r.eligibility ? describe(r.eligibility) : [];
  const map = mapsHref(r);
  const confirmed = confirmedLabel(r.last_assured_on, LOCALE);
  const online = deliveryLabel(r.delivery);

  return (
    <article className="localz-detail">
      <SeoHead title={`${r.name}${org ? ` · ${org}` : ""} · Localz`} description={r.description ?? t("Hours, phone number and how to get help.")} path={`/localz/r/${r.id}`} />
      <Link className="localz-back-link" to={category ? `/localz/${category.key}` : "/localz"}>
        <IconChevronLeft />
        {category ? t(category.label) : t("All kinds of help")}
      </Link>
      <h2>{r.name}</h2>
      {org && <div className="localz-card-org">{org}</div>}

      {r.closure && <ClosureNote closure={r.closure} />}
      {r.alert && (
        <p className="localz-alert" role="note">
          <IconAlert />
          {r.alert}
        </p>
      )}

      <div className="localz-detail-actions">
        {r.phone && (
          <a className="btn btn-primary" href={telHref(r.phone)}>
            <IconPhone />
            {t("Call {{phone}}", { phone: r.phone })}
          </a>
        )}
        {map && (
          <a className="btn" href={map} target="_blank" rel="noopener noreferrer">
            <IconPin />
            {t("Directions")}
          </a>
        )}
        {r.website && (
          <a className="btn" href={r.website} target="_blank" rel="noopener noreferrer">
            <IconLink />
            {t("Website")}
          </a>
        )}
      </div>

      {r.description && <p className="localz-detail-desc">{r.description}</p>}

      {(place || r.service_areas.length > 0 || r.location_confidential || online) && (
        <Section title={t("Where")}>
          {r.location_confidential && <p>{t("Location shared after you call")}</p>}
          {r.location_name && r.location_name !== r.organization_name && place && <p>{r.location_name}</p>}
          {place && <p>{place}</p>}
          {online && <p>{t(online)}</p>}
          {r.service_areas.length > 0 && <p className="localz-muted">{t("Serves: {{areas}}", { areas: r.service_areas.join(", ") })}</p>}
        </Section>
      )}
      <Section title={t("When")}>
        <p>
          <IconClock className="localz-inline-icon" />
          {r.hours_text || t("Call for hours")}
        </p>
        {r.week_hours_text && <p className="localz-alert">{t("This week only: {{hours}}", { hours: r.week_hours_text })}</p>}
        <ProgramNotes r={r} detail />
      </Section>
      {r.eligibility_text && (
        <Section title={t("Who can get help")}>
          <p>{r.eligibility_text}</p>
          {fit ? (
            <FitNote fit={fit} />
          ) : (
            asks.length > 0 && <p className="localz-muted">{t("In short: {{who}}", { who: asks.map((l) => t(l.text, l.vars)).join(" · ") })}</p>
          )}
        </Section>
      )}
      {r.application_process && (
        <Section title={t("How to get help")}>
          <p>{r.application_process}</p>
        </Section>
      )}
      {r.required_documents.length > 0 && (
        <Section title={t("What to bring")}>
          <ul>
            {r.required_documents.map((d) => (
              <li key={d}>{d}</li>
            ))}
          </ul>
        </Section>
      )}
      {r.fees && (
        <Section title={t("Cost")}>
          <p>{isFree(r.fees) ? t("Free") : r.fees}</p>
        </Section>
      )}
      {r.languages.length > 0 && (
        <Section title={t("Languages")}>
          <p>{r.languages.join(", ")}</p>
        </Section>
      )}
      {r.accessibility && (
        <Section title={t("Accessibility")}>
          <p>{r.accessibility}</p>
        </Section>
      )}
      {r.email && (
        <Section title={t("Email")}>
          <p>
            <a href={`mailto:${r.email}`}>
              <IconMail className="localz-inline-icon" />
              {r.email}
            </a>
          </p>
        </Section>
      )}

      <p className="localz-footnote">
        {confirmed ? t("Last confirmed {{date}}.", { date: confirmed }) + " " : ""}
        {r.source_url ? (
          <>
            <a href={r.source_url} target="_blank" rel="noopener noreferrer">
              {r.source === "childcarenj" ? t("See this provider on ChildCareNJ") : t("See this listing on NJ 211")}
            </a>{" "}
          </>
        ) : null}
        {t("Hours change - calling ahead is always a good idea.")} <Link to="/contact">{t("Something wrong? Tell us.")}</Link>
      </p>
    </article>
  );
}
