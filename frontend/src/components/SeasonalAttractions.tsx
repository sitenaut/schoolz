import { Badge, type Tone } from "./ui/Badge";
import type { SeasonalAttraction } from "../lib/seasonal";
import { trackEvent } from "../lib/track";

const SCARE: Record<string, { label: string; tone: Tone }> = {
  family: { label: "Not scary", tone: "ok" },
  mild: { label: "A little spooky", tone: "warn" },
  scary: { label: "Scary", tone: "bad" },
};

function shortDate(iso: string): string {
  return new Date(`${iso}T12:00:00`).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

const todayEt = () => new Date().toLocaleDateString("en-CA", { timeZone: "America/New_York" });

/** The next day it's (or may be) open, for ordering: today when open today;
 * for "select nights" venues, the later of today and its first night. */
function nextOpen(a: SeasonalAttraction, today: string): string {
  if (a.open_on_day) return today;
  return a.open_dates?.find((d) => d > today) ?? (a.starts_on > today ? a.starts_on : today);
}

function when(a: SeasonalAttraction): string {
  if (a.open_on_day) return "Open today";
  const today = todayEt();
  const next = a.open_dates?.find((d) => d > today);
  if (next) return `Next open ${shortDate(next)}`;
  return a.starts_on > today ? `Opens ${shortDate(a.starts_on)}` : `Select nights to ${shortDate(a.ends_on)}`;
}

/** The places-to-go half of /seasonal/<season>: our own list of haunts,
 * mazes, light shows and Santa visits, soonest open first, each with the
 * venue's own schedule, price and age advice and a link to its site. */
export function SeasonalAttractions({ attractions, season }: { attractions: SeasonalAttraction[]; season: string }) {
  const today = todayEt();
  // Open today first, then by the next night it opens; a venue that only
  // says "select nights" sorts after the ones known to be open that day.
  const key = (a: SeasonalAttraction) => `${nextOpen(a, today)}${a.open_on_day === null ? "1" : "0"}${a.name}`;
  const ordered = [...attractions].sort((a, b) => key(a).localeCompare(key(b)));
  return (
    <div className="seasonal-attractions">
      {ordered.map((a) => {
        const scare = a.scare_level ? SCARE[a.scare_level] : null;
        const directions = `https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(a.address)}`;
        return (
          <article key={a.id} className="card seasonal-attraction">
            <div className="seasonal-attraction-head">
              <div>
                <b>{a.name}</b>
                <small>
                  {a.venue ? `${a.venue} · ` : ""}
                  {a.town}
                </small>
              </div>
              <div className="seasonal-attraction-badges">
                {scare && <Badge tone={scare.tone}>{scare.label}</Badge>}
                <Badge tone={a.open_on_day ? "info" : "muted"} dot={false}>
                  {when(a)}
                </Badge>
              </div>
            </div>
            {a.note && <p>{a.note}</p>}
            <dl>
              {a.schedule && (
                <>
                  <dt>When</dt>
                  <dd>{a.schedule}</dd>
                </>
              )}
              {a.price && (
                <>
                  <dt>Cost</dt>
                  <dd>{a.price}</dd>
                </>
              )}
              {a.ages && (
                <>
                  <dt>Ages</dt>
                  <dd>{a.ages}</dd>
                </>
              )}
            </dl>
            <div className="seasonal-attraction-links">
              <a
                className="btn sm"
                href={a.ticket_url || a.url}
                target="_blank"
                rel="noopener"
                onClick={() => trackEvent("seasonal_attraction_open", { season, attraction_id: a.id })}
              >
                {a.ticket_url ? "Tickets & info ↗" : "Website ↗"}
              </a>
              <a className="btn sm" href={directions} target="_blank" rel="noopener">
                Directions ↗
              </a>
            </div>
          </article>
        );
      })}
    </div>
  );
}
