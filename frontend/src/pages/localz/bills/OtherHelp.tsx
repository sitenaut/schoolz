import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { type ResourceSummary, searchResources } from "../../../lib/localz";
import { ResourceList } from "../ResourceList";
import { HELP_CODES } from "./shared";

/** Localz's own listings for help with utility bills - payment assistance,
 * shutoff protection, discounted service - for the bill's county, statewide
 * programs included. Shown before a bill is posted and while it's up: a
 * program can do more than one neighbor can. */
export function OtherHelp({ county, limit = 20 }: { county: string | null; limit?: number }) {
  const { t } = useTranslation();
  const [items, setItems] = useState<ResourceSummary[] | null>(null);
  const [total, setTotal] = useState(0);

  useEffect(() => {
    let cancelled = false;
    searchResources({ county: county ?? undefined, types: HELP_CODES, page_size: limit })
      .then((found) => {
        if (cancelled) return;
        setItems(found.items);
        setTotal(found.total);
      })
      .catch(() => !cancelled && setItems([]));
    return () => {
      cancelled = true;
    };
  }, [county, limit]);

  const more = items ? total - items.length : 0;
  return (
    <div className="bills-other-help">
      {items === null ? (
        <p className="localz-lede">{t("Loading…")}</p>
      ) : items.length > 0 ? (
        <ResourceList items={items} />
      ) : (
        <p className="bills-small">{t("We couldn't load the list just now.")}</p>
      )}
      <p className="bills-small">
        {more > 0 && `${t("{{n}} more in Localz.", { n: more })} `}
        <Link to="/localz/housing-bills">{t("See all help with housing and bills")}</Link>
        {" · "}
        {t("Or call 211, any time, for help finding more.")}
      </p>
    </div>
  );
}
