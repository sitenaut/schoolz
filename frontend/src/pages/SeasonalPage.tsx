import { Link, useParams } from "react-router-dom";
import { SeasonalAttractions } from "../components/SeasonalAttractions";
import { SeoHead } from "../components/SeoHead";
import { usePrerenderReady } from "../lib/prerenderReady";
import { seasonLook, useAttractions, useSeasons } from "../lib/seasonal";
import { trackEvent } from "../lib/track";

/** /seasonal/<season> - where the top-bar season badge lands. Places to go
 * first (our own list, from each venue's site), then links to guides other
 * people publish, credited to them. Never their listings copied: the
 * publishers ask that their curation be shared by link. */
export function SeasonalPage() {
  const { season = "" } = useParams();
  const { seasons, loaded } = useSeasons();
  const look = seasonLook(season);
  const guides = seasons.find((s) => s.season === season)?.guides ?? [];
  const publishers = [...new Set(guides.map((g) => g.publisher))];

  const { attractions, loaded: attractionsLoaded } = useAttractions(season);

  usePrerenderReady(loaded && attractionsLoaded);

  return (
    <div style={{ maxWidth: 640, margin: "0 auto" }}>
      <SeoHead
        title={`${look.heading} in South Jersey · schoolz`}
        description={
          attractions.length || guides.length
            ? `${[...attractions.map((a) => `${a.name} (${a.town})`), ...guides.map((g) => g.title)].slice(0, 6).join(" · ")} - dates, ages and links for South Jersey families.`
            : `${look.heading} in South Jersey: places to go and guides for families.`
        }
        path={`/seasonal/${season}`}
      />
      <h2>
        <span aria-hidden="true">{look.emoji}</span> {look.heading}
      </h2>
      {!(loaded && attractionsLoaded) ? (
        <p className="note">Loading…</p>
      ) : guides.length === 0 && attractions.length === 0 ? (
        <div className="card">
          <p style={{ margin: 0 }}>
            Nothing is running for this season right now. <Link to="/local">See local events</Link> instead.
          </p>
        </div>
      ) : (
        <>
          {attractions.length > 0 && guides.length > 0 && (
            <nav className="chips" aria-label="Jump to a section">
              {[
                ["places", "Places to go", attractions.length],
                ["guides", "Guides", guides.length],
              ].map(([id, label, n]) => (
                <a
                  key={id}
                  className="chip"
                  href={`#${id}`}
                  onClick={(e) => {
                    e.preventDefault();
                    document.getElementById(String(id))?.scrollIntoView({ behavior: "smooth", block: "start" });
                  }}
                >
                  {label} <span className="chip-count">{n}</span>
                </a>
              ))}
            </nav>
          )}
          {attractions.length > 0 && (
            <section id="places" style={{ scrollMarginTop: 72 }}>
              <h3>Places to go</h3>
              <p className="note">Dates, prices and ages from each venue's own site. Check there before you go: weather closes these.</p>
              <SeasonalAttractions attractions={attractions} season={season} />
            </section>
          )}
          {guides.length > 0 && (
            <section id="guides" style={{ scrollMarginTop: 72 }}>
              <h3>Guides</h3>
              <p className="note">From local publishers who put in the work to keep them current. Tap one to open it on their site.</p>
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
            </section>
          )}
        </>
      )}

      {publishers.length > 0 && (
        <p className="note" style={{ marginTop: 20 }}>
          These guides belong to {publishers.join(", ")}. schoolz only links to them; please share their pages rather than copying them.
        </p>
      )}
    </div>
  );
}
