/** Plain privacy/cookies notice, linked from the persistent footer on every
 * page (AppShell). No consent popup by design: everything schoolz stores
 * today (localStorage school picks, Supabase Auth's own session storage,
 * an optional Gmail token, anonymous RUM performance/error data) is
 * functional or anonymous. Google Analytics (lib/analytics.ts) is the
 * exception: it sets a first-party cookie, so it is disclosed below and has
 * a per-device opt-out instead of a banner. Whether that is enough is the
 * site owner's call - revisit this page if ads or identified analytics are
 * ever added. */
import { SeoHead } from "../components/SeoHead";
import { useState } from "react";
import { isAnalyticsOptedOut, setAnalyticsOptOut } from "../lib/analytics";
import { usePrerenderReady } from "../lib/prerenderReady";

export function PrivacyPage() {
  usePrerenderReady(true);
  const [optedOut, setOptedOut] = useState(isAnalyticsOptedOut());
  return (
    <>
      <SeoHead
        title="Privacy & cookies · schoolz"
        description="What schoolz stores about visitors and account holders, and why - anonymous usage analytics, no advertising or ad tracking."
        path="/privacy"
      />
      <h2>Privacy &amp; cookies</h2>
      <p className="note">Last updated September 2026.</p>

      <p>
        schoolz ("we", "us") helps parents and guardians in South Jersey school
        districts keep up with their kids' schools. This page explains what data the
        site stores about you and why. Questions or requests (including to access,
        correct, or delete your data) can be sent to{" "}
        <a href="mailto:enr@profitnaut.com">enr@profitnaut.com</a>.
      </p>

      <h3>You don't need an account to use most of this site</h3>
      <p>
        Schools, districts, the calendar, and Smore newsletter content are public and
        browsable by anyone, with no login required. Registering is only needed for the
        optional personal layer: linking your own kids, narrowing the calendar to just
        their schools, and connecting Gmail.
      </p>

      <h3>What we store, and why</h3>
      <table className="table" style={{ marginTop: 8 }}>
        <thead>
          <tr>
            <th>What</th>
            <th>Where</th>
            <th>Why</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Your picked schools, and which are currently shown/hidden</td>
            <td>Your browser's local storage</td>
            <td>
              So the Today/Calendar/Lunch pages remember your schools without needing an
              account. Never sent to us or any third party — it stays on your device.
            </td>
          </tr>
          <tr>
            <td>Light/dark theme choice</td>
            <td>Your browser's local storage</td>
            <td>Remembers your display preference between visits.</td>
          </tr>
          <tr>
            <td>Login session</td>
            <td>A cookie/token set by our authentication provider, Supabase</td>
            <td>
              Strictly necessary to keep you signed in if you register. Set only if you
              create an account; not set for anonymous visitors.
            </td>
          </tr>
          <tr>
            <td>Anonymous performance &amp; error data (page load times, which pages are used, JS errors)</td>
            <td>Grafana Cloud, our monitoring provider</td>
            <td>
              We collect anonymous performance and error data to make the site faster. It's
              tied to a random per-visit session, never to your name, email, or children,
              and isn't shared with advertisers. Login tokens and other sensitive URL
              content are stripped before anything is sent.
            </td>
          </tr>
          <tr>
            <td>Account info (email, username), your linked children, guardian invites</td>
            <td>Our database</td>
            <td>
              Powers the optional personal layer described above. A linked child's record
              is shared only with guardians you or an auto-match connects it to — never
              made public.
            </td>
          </tr>
          <tr>
            <td>A count of visits to each public page, and roughly where visitors came from (e.g. "facebook")</td>
            <td>Our database</td>
            <td>
              So we can tell whether a post about this project actually reached anyone.{" "}
              <strong>This is a running tally, not a record of you</strong> — we store one number per page, per day,
              per source, and nothing else. No id, no IP, no profile, no cookie, nothing that could be traced back to
              a person or linked between visits. If a link brings you here with a tracking code attached (Facebook
              adds one), we read it once to label the visit "facebook" and then discard it — it's never stored or
              sent on.
            </td>
          </tr>
          <tr>
            <td>
              Anonymous usage statistics from Google Analytics: which pages are viewed, device type (phone or
              computer), approximate area, the town and school district of the schools you picked, and how you got
              here
            </td>
            <td>A first-party analytics cookie, and Google Analytics</td>
            <td>
              So we can see which towns and districts actually use schoolz and which pages help, and so this project
              can be shown to the districts it serves. Advertising features and Google signals are turned off, we
              send Google no name, email, account or child information, and personal pages are reported only as
              "account" or "children", never with anything on them. You can{" "}
              <button
                type="button"
                className="linklike"
                onClick={() => {
                  setAnalyticsOptOut(!optedOut);
                  setOptedOut(!optedOut);
                }}
              >
                {optedOut ? "turn analytics back on for this device" : "turn analytics off for this device"}
              </button>
              {optedOut ? " (currently off)" : ""}.
            </td>
          </tr>
          <tr>
            <td>
              Your survey answers (the schools you picked, what you said is hard to find, your comments, and your name
              and email if you chose to give them)
            </td>
            <td>Our database</td>
            <td>
              Only if you fill in the <a href="/survey">survey</a>. Name and email are optional and blank by default;
              your email is never shared with the district or anyone else — it's only so we can follow up. Your
              comments may be quoted to the district <strong>without your name</strong> unless you explicitly tick
              "you can use my name."
            </td>
          </tr>
          <tr>
            <td>
              Proof a survey response is genuine: the date and time it arrived, which browser sent it, and a scrambled
              one-way code that stands in for your internet connection
            </td>
            <td>Our database</td>
            <td>
              So a stack of responses can be shown to the district as real, separate people rather than one person
              submitting over and over. <strong>We never store your IP address.</strong> It's immediately scrambled
              with a secret key into a code that can't be turned back into an address, and that code is useless
              anywhere else. It isn't used to track you, isn't tied to your browsing, and isn't shared with anyone.
            </td>
          </tr>
          <tr>
            <td>Gmail read-only access token (only if you choose to connect Gmail)</td>
            <td>Our database, encrypted at rest</td>
            <td>
              Used solely to detect school newsletter links in your inbox for scanners you
              set up yourself. We never send, delete, or modify email, and this is entirely
              opt-in — nothing is connected unless you click "Connect Gmail" and complete
              Google's own consent screen.
            </td>
          </tr>
        </tbody>
      </table>

      <h3>What we don't do</h3>
      <ul>
        <li>No advertising or ad-tracking cookies of any kind — Google Analytics runs with advertising features off.</li>
        <li>No selling or sharing your data with advertisers or data brokers.</li>
        <li>No cross-site tracking — nothing here follows you to other websites.</li>
        <li>
          No identifying you personally in our performance/error monitoring — it's tied to
          a random per-visit session, not your account, name, or email.
        </li>
      </ul>

      <h3>Why there's no "accept cookies" popup</h3>
      <p>
        schoolz serves families in New Jersey, and the only non-essential thing it uses is the anonymous usage
        analytics described above, with advertising turned off. Rather than a popup, there's an opt-out you can
        use on this page at any time, and this notice says exactly what is collected. If that ever changes (for
        example ads, or analytics that identifies you), this notice and a real consent choice will change with it.
      </p>

      <h3>Third parties involved</h3>
      <ul>
        <li>
          <strong>Google Analytics</strong> — receives the anonymous usage statistics described above.
        </li>
        <li>
          <strong>Supabase</strong> — handles login/authentication for registered users.
        </li>
        <li>
          <strong>Fly.io</strong> — hosts the website and backend.
        </li>
        <li>
          <strong>Grafana Cloud</strong> — receives the anonymous performance/error data
          described above, plus backend operational metrics/logs. No account data or
          content from your inbox ever passes through it.
        </li>
        <li>
          <strong>Google</strong> — only if you connect Gmail, to read newsletter-related
          messages you've filtered for; governed by your own Google account settings.
        </li>
      </ul>

      <h3>Your rights</h3>
      <p>
        You can clear your browser's local storage at any time to remove your saved
        school picks and theme preference. If you have an account, you can delete your
        linked children yourself from the Children page, or email us to delete your
        account entirely, correct inaccurate data, or ask what we hold about you.
      </p>
    </>
  );
}
