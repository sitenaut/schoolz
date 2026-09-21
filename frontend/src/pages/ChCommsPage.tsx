import { Link } from "react-router-dom";
import { SeoHead } from "../components/SeoHead";
import { usePrerenderReady } from "../lib/prerenderReady";
import { trackEvent } from "../lib/track";

const REPORT_URL = "https://github.com/sitenaut/schoolz/blob/main/docs/DISTRICT_COMMUNICATION_REPORT.md";
const GAPS_URL = "https://github.com/sitenaut/schoolz/blob/main/docs/DATA_GAPS.md";

const FINDINGS: { num: string; cap: string }[] = [
  { num: "3 / 28", cap: "schools where I could confirm how to report an absence" },
  { num: "2 / 28", cap: "schools publishing a bell schedule that says when early dismissal actually ends (both are high schools)" },
  { num: "13 / 28", cap: "schools with a parent handbook I could find at all" },
  { num: "8 / 28", cap: "schools whose weekly newsletter I could track down" },
];

const RECEIPTS: { lead: string; text: string }[] = [
  { lead: "7 schools", text: "have a PTA page showing a raw placeholder where the content should be." },
  { lead: "March 2021", text: "is where one school's PTA minutes stop. I'm sure they were excellent minutes." },
  { lead: '"21-22"', text: "is still in another school's PTA link — which tells you when anyone last touched it." },
];

/** The three categories, straight from the report. Colored with the
 * existing per-school palette tokens rather than new ones - they're the
 * app's established "these are distinct things" hues. */
const BUCKETS: { title: string; body: string; tag: string; color: string }[] = [
  {
    title: "How your school works",
    body: "Bell schedule, lunch, absences, buses, aftercare, who to call. Same for every family, barely changes.",
    tag: "schoolz does this",
    color: "var(--sch-1)",
  },
  {
    title: "What's happening & what's due",
    body: "Half days, picture day, form deadlines, fundraisers. Changes weekly — this is where \"wait, that was today?\" lives, and it was far and away the most common complaint I heard.",
    tag: "schoolz does this",
    color: "var(--sch-4)",
  },
  {
    title: "Your own kid's world",
    body: "Teacher messages, assignments, grades. ClassDojo, Remind, Genesis, Google Classroom. Personal, sensitive, and a genuinely different problem.",
    tag: "deliberately not touching",
    color: "var(--sch-3)",
  },
];

/** The landing page for the Facebook post - the "here's what I found,
 * here's what I need" pitch to other Cherry Hill parents. Deliberately
 * short and scannable: the full findings live in the two linked docs, and
 * this page's only job is to earn a click on one of the three asks. */
export function ChCommsPage() {
  usePrerenderReady(true);
  const cta = (name: string) => trackEvent("cta_click", { page: "chcomms", cta: name });
  return (
    <>
      <SeoHead
        title="I read 28 school websites so you don't have to · schoolz"
        description="What I found about how Cherry Hill schools communicate with families - the gaps, a free open-source app that fills some of them, and the three things I'm asking parents for."
        path="/chcomms"
      />

      <div className="hero full">
        <h1>I read 28 school websites so you don't have to</h1>
        <p>
          Last week I posted about wanting some sanity around parent–school communication. A lot of you replied
          "same." So I spent a week actually checking — mostly to make sure I wasn't about to ask the district for
          something they already do.
        </p>
      </div>

      <h2 className="page-section">The short version</h2>
      <div className="chc-stats">
        {FINDINGS.map((f) => (
          <div className="chc-stat" key={f.num}>
            <span className="chc-num">{f.num}</span>
            <span className="chc-cap">{f.cap}</span>
          </div>
        ))}
      </div>

      <p>And a few specifics, because those land better than vibes:</p>
      <div className="receipts">
        {RECEIPTS.map((r) => (
          <div className="receipt" key={r.lead}>
            <span className="receipt-lead">{r.lead}</span>
            <span>{r.text}</span>
          </div>
        ))}
      </div>

      <p>
        To be clear: <strong>nobody did anything wrong here.</strong> Every school made sensible choices with the
        tools they had. Nobody coordinated those choices — so the same fact, like what time early dismissal ends or
        who to email when your kid's sick, lives somewhere different, in a different format, at all 28 of them.
      </p>

      <h2 className="page-section">There are really three kinds of information</h2>
      <div className="buckets">
        {BUCKETS.map((b, i) => (
          <div className="bucket" style={{ ["--c" as string]: b.color }} key={b.title}>
            <span className="bucket-n">{i + 1}</span>
            <h3>{b.title}</h3>
            <p>{b.body}</p>
            <span className="bucket-tag">{b.tag}</span>
          </div>
        ))}
      </div>
      <p>
        The first two are public information that should look the same at every school. That's the fixable part.
        That's what I built.
      </p>

      <h2 className="page-section">So I built a thing</h2>
      <p>
        It's called <strong>schoolz</strong> (working title — I'm very open to better). It puts buckets 1 and 2 in one
        place, per school. No account, no ads, no cost, nothing about your child.
      </p>
      <p>
        <Link to="/" className="btn btn-primary" onClick={() => cta("try_app")}>
          Try it
        </Link>
      </p>
      <p className="smallnote">
        Cherry Hill East, Bret Harte, Woodcrest, and Chesterbrook Academy Preschool have the most filled in — start
        with one of those to see what your school could look like.
      </p>

      <h2 className="page-section">Three things I need from you</h2>
      <ol className="chc-list">
        <li>
          <strong>Send me your school's newsletter.</strong> This is the big one — it's what makes your school's page
          fill in. <Link to="/contact/submit" onClick={() => cta("send_newsletter")}>Paste the link here.</Link>
        </li>
        <li>
          <strong>Take the survey.</strong> Two minutes, and it's the evidence I can actually hand the district.{" "}
          <Link to="/survey" onClick={() => cta("take_survey")}>Start here.</Link>
        </li>
        <li>
          <strong>Tell me what's wrong.</strong> Wrong phone number, stale date, missing school — I want to know.
        </li>
      </ol>

      <div className="callout">
        <strong>How to find your school's newsletter link</strong>
        <p>
          It arrives as an email (usually from an app called Smore). At the very top there's a line like{" "}
          <em>"Not displaying correctly? View in browser."</em> That link is the whole thing I need.{" "}
          <Link to="/contact/submit" onClick={() => cta("send_newsletter_callout")}>Drop it here →</Link>
        </p>
      </div>

      <h2 className="page-section">The fine print, since someone will ask</h2>
      <ul className="chc-list">
        <li>I'm not selling anything. No company, no ads, no fees, no catch.</li>
        <li>
          It touches nothing about your kid — no grades, no names, no student data. Only information already published
          publicly on school and district websites.
        </li>
        <li>It's open source, so anyone can read exactly what it does and where every fact came from.</li>
        <li>The goal is to hand all of this — findings and tool — to the district, and to have something useful in the meantime.</li>
      </ul>

      <h2 className="page-section">Want the whole thing?</h2>
      <p>
        For the genuinely curious, here's everything, unabridged:
      </p>
      <ul className="chc-list">
        <li>
          <a href={REPORT_URL} target="_blank" rel="noreferrer" onClick={() => cta("full_report")}>
            The full write-up for the district
          </a>{" "}
          — findings school by school, and what I'm asking them for.
        </li>
        <li>
          <a href={GAPS_URL} target="_blank" rel="noreferrer" onClick={() => cta("data_gaps")}>
            The gory data detail
          </a>{" "}
          — exactly what's covered, what isn't, and where it broke.
        </li>
      </ul>
      <p className="fine">
        This is a lot of words for "please send me your school's newsletter link." <Link to="/contact/submit" onClick={() => cta("send_newsletter_footer")}>Here's that link again.</Link>
      </p>
    </>
  );
}
