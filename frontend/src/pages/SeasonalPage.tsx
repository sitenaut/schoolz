import { Link, useParams } from "react-router-dom";
import { SeoHead } from "../components/SeoHead";
import { usePrerenderReady } from "../lib/prerenderReady";
import { seasonLook, useSeasons } from "../lib/seasonal";
import { trackEvent } from "../lib/track";

/** /seasonal/<season> - where the top-bar season badge lands. A list of
 * links to guides other people publish, credited to them. Deliberately no
 * copied listings: the publishers ask that their curation be shared by
 * link, and the link always has their latest version. */
export function SeasonalPage() {
  const { season = "" } = useParams();
  const { seasons, loaded } = useSeasons();
  const look = seasonLook(season);
  const guides = seasons.find((s) => s.season === season)?.guides ?? [];
  const publishers = [...new Set(guides.map((g) => g.publisher))];

  usePrerenderReady(loaded);

  return (
    <div style={{ maxWidth: 640, margin: "0 auto" }}>
      <SeoHead
        title={`${look.heading} guides · South Jersey · schoolz`}
        description={
          guides.length
            ? `${guides.map((g) => g.title).join(" · ")} - linked from local publishers, all in one place for South Jersey families.`
            : `${look.heading} guides for South Jersey families, from local publishers.`
        }
        path={`/seasonal/${season}`}
      />
      <h2>
        <span aria-hidden="true">{look.emoji}</span> {look.heading}
      </h2>
      <p className="note">Guides from local publishers who put in the work to keep them current. Tap one to open it on their site.</p>

      {!loaded ? (
        <p className="note">Loading…</p>
      ) : guides.length === 0 ? (
        <div className="card">
          <p style={{ margin: 0 }}>
            Nothing is running for this season right now. <Link to="/local">See local events</Link> instead.
          </p>
        </div>
      ) : (
        <div className="seasonal-guides">
          {guides.map((g, i) => (
            <a
              key={g.id}
              className={`link-card seasonal-guide${i === 0 ? " headline" : ""}`}
              href={g.url}
              target="_blank"
              rel="noopener"
              onClick={() => trackEvent("seasonal_guide_open", { season, guide_id: g.id })}
            >
              <span>
                <b>{g.title}</b>
                <small className="seasonal-publisher">by {g.publisher}</small>
                {g.note && <small>{g.note}</small>}
              </span>
              <span className="seasonal-open" aria-hidden="true">
                ↗
              </span>
            </a>
          ))}
        </div>
      )}

      {publishers.length > 0 && (
        <p className="note" style={{ marginTop: 20 }}>
          These guides belong to {publishers.join(", ")}. schoolz only links to them; please share their pages rather than copying them.
        </p>
      )}
    </div>
  );
}
