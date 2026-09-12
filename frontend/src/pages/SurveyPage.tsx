import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { SeoHead } from "../components/SeoHead";
import { logoClass } from "../lib/logos";
import { useMySchools } from "../lib/mySchools";
import { usePrerenderReady } from "../lib/prerenderReady";
import { SCHOOL_TYPE_TIERS } from "../lib/schoolType";
import { trackEvent } from "../lib/track";
import { PAIN_POINT_GROUPS, loadSurveySummary, submitSurvey, type SurveySummary } from "./survey/surveyApi";

const SCALE: { value: number; label: string }[] = [
  { value: 1, label: "Constantly in the dark" },
  { value: 2, label: "" },
  { value: 3, label: "It's fine, mostly" },
  { value: 4, label: "" },
  { value: 5, label: "Works great for us" },
];

/** The public parent survey (/survey), linked from /chcomms and the
 * footer. No account, nothing required - every question can be skipped
 * except "answer at least one of them", which the backend enforces. The
 * point is evidence to hand the district, so the shape deliberately
 * mirrors docs/DISTRICT_COMMUNICATION_REPORT.md's three categories. */
export function SurveyPage() {
  const { allSchools, mySchools, loading } = useMySchools();
  const [picked, setPicked] = useState<string[]>([]);
  const [seededFromMySchools, setSeededFromMySchools] = useState(false);
  const [satisfaction, setSatisfaction] = useState<number | null>(null);
  const [painPoints, setPainPoints] = useState<string[]>([]);
  const [missingInfo, setMissingInfo] = useState("");
  const [comments, setComments] = useState("");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [shareConsent, setShareConsent] = useState<"anonymous" | "named">("anonymous");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [summary, setSummary] = useState<SurveySummary | null>(null);
  const startedRef = useRef(false);

  usePrerenderReady(!loading);

  useEffect(() => {
    loadSurveySummary().then(setSummary).catch(() => undefined);
  }, [done]);

  // If they've already picked schools elsewhere in the app, start from
  // those rather than making them do it twice. One-shot, so it never
  // fights their own clicks afterwards.
  useEffect(() => {
    if (loading || seededFromMySchools) return;
    setPicked(mySchools.map((s) => s.id));
    setSeededFromMySchools(true);
  }, [loading, mySchools, seededFromMySchools]);

  const markStarted = () => {
    if (startedRef.current) return;
    startedRef.current = true;
    trackEvent("survey_start");
  };

  const toggleSchool = (id: string) => {
    markStarted();
    setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));
  };
  const togglePain = (key: string) => {
    markStarted();
    setPainPoints((p) => (p.includes(key) ? p.filter((x) => x !== key) : [...p, key]));
  };

  const answeredSomething =
    satisfaction !== null || painPoints.length > 0 || missingInfo.trim() !== "" || comments.trim() !== "";

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await submitSurvey({
        school_ids: picked,
        satisfaction,
        pain_points: painPoints,
        missing_info: missingInfo.trim() || undefined,
        comments: comments.trim() || undefined,
        submitter_name: name.trim() || undefined,
        submitter_email: email.trim() || undefined,
        share_consent: shareConsent,
      });
      trackEvent("survey_submitted", { schools: picked.length, pain_points: painPoints.length });
      setDone(true);
      window.scrollTo({ top: 0 });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not send this - please try again");
    } finally {
      setBusy(false);
    }
  };

  const seo = (
    <SeoHead
      title="Parent survey · schoolz"
      description="Two minutes: tell us what school information is hard to find in Cherry Hill. No account needed - the results go to the district."
      path="/survey"
    />
  );

  if (done) {
    return (
      <>
        {seo}
        <div className="card" style={{ maxWidth: 620, margin: "40px auto", textAlign: "center" }}>
          <h2>Thank you — genuinely.</h2>
          <p>
            That's exactly the kind of thing that makes this worth bringing to the district.
            {summary && summary.total > 1 && (
              <>
                {" "}
                You're one of <strong>{summary.total}</strong> parents who've answered so far.
              </>
            )}
          </p>
          <p className="fine">
            One more thing that would help enormously: <Link to="/contact">send us your school's weekly newsletter link</Link> — that's
            what fills in your school's page.
          </p>
          <p style={{ marginTop: 20 }}>
            <Link to="/" className="btn btn-primary">
              See what's in the app
            </Link>
          </p>
        </div>
      </>
    );
  }

  const groups = SCHOOL_TYPE_TIERS.map((t) => ({
    ...t,
    schools: allSchools.filter((s) => (s.school_type ?? "other") === t.key),
  })).filter((g) => g.schools.length > 0);

  return (
    <>
      {seo}
      <div className="hero full">
        <h1>How's school communication working for you?</h1>
        <p>
          Two minutes, no account, nothing required. Skip anything you like. The results go to Cherry Hill Public
          Schools as part of <Link to="/chcomms">this write-up</Link> — so vent freely, it's being read.
          {summary && summary.total > 0 && (
            <>
              {" "}
              <strong>{summary.total}</strong> {summary.total === 1 ? "parent has" : "parents have"} answered so far.
            </>
          )}
        </p>
      </div>

      <form onSubmit={submit}>
        {error && <div className="form-error">{error}</div>}

        <h2 className="page-section">Which school(s) are your kids at?</h2>
        {loading ? (
          <p className="note">Loading schools…</p>
        ) : (
          groups.map((g) => (
            <div key={g.key}>
              <div className="tier">{g.label}</div>
              <div className="sgrid">
                {g.schools.map((s) => (
                  <button
                    type="button"
                    className="sopt"
                    aria-pressed={picked.includes(s.id)}
                    onClick={() => toggleSchool(s.id)}
                    key={s.id}
                  >
                    <span className="box" />
                    {s.logo_url ? <img className={logoClass("sopt-logo", s.slug)} src={s.logo_url} alt="" /> : null}
                    {s.short_name || s.name}
                  </button>
                ))}
              </div>
            </div>
          ))
        )}

        <h2 className="page-section">Overall, how well does school information reach you?</h2>
        <div className="scale" role="radiogroup" aria-label="Overall satisfaction">
          {SCALE.map((s) => (
            <button
              type="button"
              key={s.value}
              role="radio"
              aria-checked={satisfaction === s.value}
              className={`scale-opt ${satisfaction === s.value ? "on" : ""}`}
              onClick={() => {
                markStarted();
                setSatisfaction(satisfaction === s.value ? null : s.value);
              }}
            >
              <span className="scale-num">{s.value}</span>
              {s.label && <span className="scale-lbl">{s.label}</span>}
            </button>
          ))}
        </div>

        <h2 className="page-section">What's actually hard to find or easy to miss?</h2>
        <p className="note" style={{ marginTop: -4 }}>
          Check anything you've had trouble tracking down, or found out about too late. No wrong answers. This list is
          everything schoolz already pulls together for you — which is really just our best guess at what matters. If
          we guessed wrong, the next two boxes are where you say so.
        </p>
        {PAIN_POINT_GROUPS.map((group) => (
          <div key={group.title}>
            <h3 className="page-subsection">{group.title}</h3>
            <p className="smallnote" style={{ margin: "0 0 10px" }}>
              {group.hint}
            </p>
            <div className="checks">
              {group.items.map((item) => (
                <label className={`check ${painPoints.includes(item.key) ? "on" : ""}`} key={item.key}>
                  <input
                    type="checkbox"
                    checked={painPoints.includes(item.key)}
                    onChange={() => togglePain(item.key)}
                  />
                  <span>{item.label}</span>
                </label>
              ))}
            </div>
          </div>
        ))}

        <label className="field" style={{ marginTop: 20 }}>
          <span className="lbl">Anything we missed?</span>
          <input
            value={missingInfo}
            onChange={(e) => setMissingInfo(e.target.value)}
            placeholder="Something else that's hard to keep track of…"
            maxLength={2000}
          />
          <span className="help">If it's not on the list above, it belongs here.</span>
        </label>

        <label className="field">
          <span className="lbl">The open mic</span>
          <textarea
            value={comments}
            onChange={(e) => {
              markStarted();
              setComments(e.target.value);
            }}
            rows={6}
            placeholder="What would actually help? What drives you up the wall? Tell a story if you've got one…"
            maxLength={5000}
          />
          <span className="help">
            This is the part most likely to get quoted to the district — anonymously, unless you say otherwise below.
          </span>
        </label>

        <h2 className="page-section">Want to leave your name? (Totally optional)</h2>
        <label className="field">
          <span className="lbl">Name</span>
          <input value={name} onChange={(e) => setName(e.target.value)} maxLength={200} placeholder="Optional" />
        </label>
        <label className="field">
          <span className="lbl">Email</span>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            maxLength={255}
            placeholder="Optional"
          />
          <span className="help">Only so we can follow up. Never shared with the district or anyone else.</span>
        </label>

        <div className="checks" style={{ marginTop: 6 }}>
          <label className={`check ${shareConsent === "anonymous" ? "on" : ""}`}>
            <input
              type="radio"
              name="share_consent"
              checked={shareConsent === "anonymous"}
              onChange={() => setShareConsent("anonymous")}
            />
            <span>Keep me anonymous</span>
          </label>
          <label className={`check ${shareConsent === "named" ? "on" : ""}`}>
            <input
              type="radio"
              name="share_consent"
              checked={shareConsent === "named"}
              onChange={() => setShareConsent("named")}
            />
            <span>You can use my name</span>
          </label>
        </div>

        <button type="submit" className="cta" disabled={busy || !answeredSomething}>
          {busy ? "Sending…" : answeredSomething ? "Send it in" : "Answer at least one question"}
        </button>
        <p className="fine">
          We record the date and time each response comes in, plus a scrambled one-way code that stands in for your
          internet connection. We never store your IP address, and that code can't be turned back into one — it exists
          only so we can show the district these came from real, separate people. More on the{" "}
          <Link to="/privacy">privacy page</Link>.
        </p>
      </form>
    </>
  );
}
