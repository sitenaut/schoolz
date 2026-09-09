import { formatDate, googleCalendarQuickAddUrl } from "../lib/calendar";
import type { SchoolContentItem } from "../types";

const NEW_FLAGGED_CATEGORIES = new Set(["policy_change", "procedure"]);

export function ContentItemCard({ item, showSchool }: { item: SchoolContentItem; showSchool?: string }) {
  const calendarUrl = item.start_date ? googleCalendarQuickAddUrl(item) : null;
  return (
    <li className="item-card">
      <div className="item-title">
        {item.title}
        {NEW_FLAGGED_CATEGORIES.has(item.category) && <span className="badge-new">Updated</span>}
        {item.scope === "district" && <span className="badge-new" style={{ background: "var(--color-primary)" }}>District</span>}
      </div>
      {showSchool && <div className="item-desc">{showSchool}</div>}
      {item.start_date && (
        <div className="item-date">
          {formatDate(item.start_date, item.is_all_day)}
          {item.end_date && ` – ${formatDate(item.end_date, item.is_all_day)}`}
        </div>
      )}
      {item.description && <div className="item-desc">{item.description}</div>}
      {item.person_name && (
        <div className="item-desc">
          {item.person_name}
          {item.person_title && ` — ${item.person_title}`}
        </div>
      )}
      <div style={{ marginTop: 6, display: "flex", gap: 8 }}>
        {calendarUrl && (
          <a className="btn" href={calendarUrl} target="_blank" rel="noreferrer">
            Add to Google Calendar
          </a>
        )}
        {item.link_url && (
          <a className="btn" href={item.link_url} target="_blank" rel="noreferrer">
            Open link
          </a>
        )}
      </div>
    </li>
  );
}
