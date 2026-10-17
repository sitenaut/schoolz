import { useTranslation } from "react-i18next";
import type { ResourceSummary } from "../../lib/localz";
import { fitFor, sortByFit, useLocalzFit } from "../../lib/localzFit";
import { ResourceCard } from "./ResourceCard";

/** A list of listings. Once the visitor has said what fits them, the ones
 * that do come first, and the ones that don't sit under "Other programs that
 * might still help" - lower, never hidden. Sorting covers what's loaded so
 * far; "Show more" can bring in more good fits further down. */
export function ResourceList({ items, busy = false }: { items: ResourceSummary[]; busy?: boolean }) {
  const { t } = useTranslation();
  const answers = useLocalzFit()?.answers ?? null;
  const rows = sortByFit(items, answers).map((r) => ({ r, fit: fitFor(r.eligibility, answers) }));
  const firstNo = rows.findIndex((row) => row.fit?.level === "no");
  return (
    <div className={`localz-list${busy ? " busy" : ""}`}>
      {rows.map(({ r, fit }, i) => {
        const divider = i === firstNo;
        return (
          <div className="localz-list-item" key={r.id}>
            {divider && <h3 className="localz-list-divider">{t("Other programs that might still help")}</h3>}
            <ResourceCard r={r} fit={fit} />
          </div>
        );
      })}
    </div>
  );
}
