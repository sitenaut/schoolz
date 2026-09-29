import { useTranslation } from "react-i18next";
import { formatDate, googleCalendarQuickAddUrl } from "../lib/calendar";
import type { SchoolContentItem } from "../types";
import { TranslatedNote } from "./TranslatedNote";

const NEW_FLAGGED_CATEGORIES = new Set(["policy_change", "procedure"]);

export function ContentItemCard({ item, showSchool }: { item: SchoolContentItem; showSchool?: string }) {
  const { t } = useTranslation();
  const calendarUrl = item.start_date ? googleCalendarQuickAddUrl(item) : null;
  return (
    <li className="item-card">
      <div className="item-title">
        {item.title}
        {NEW_FLAGGED_CATEGORIES.has(item.category) && <span className="badge-new">{t("Updated")}</span>}
        {item.scope === "district" && <span className="badge-new" style={{ background: "var(--color-primary)" }}>{t("District")}</span>}
      </div>
      {showSchool && <div className="item-desc">{showSchool}</div>}
      {item.start_date && (
        <div className="item-date">
          {formatDate(item.start_date, item.is_all_day)}
          {item.end_date && ` – ${formatDate(item.end_date, item.is_all_day)}`}
        </div>
      )}
      {item.description && <div className="item-desc">{item.description}</div>}
      <TranslatedNote item={item} />
      {item.person_name && (
        <div className="item-desc">
          {item.person_name}
          {item.person_title && ` — ${item.person_title}`}
        </div>
      )}
      <div style={{ marginTop: 6, display: "flex", gap: 8 }}>
        {calendarUrl && (
          <a className="btn" href={calendarUrl} target="_blank" rel="noreferrer">
            {t("Add to Google Calendar")}
          </a>
        )}
        {item.link_url && (
          <a className="btn" href={item.link_url} target="_blank" rel="noreferrer">
            {t("Open link")}
          </a>
        )}
      </div>
    </li>
  );
}
