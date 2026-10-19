/** Plain privacy/cookies notice, linked from the persistent footer on every
 * page (AppShell). No consent popup by design: everything schoolz stores
 * about an anonymous visitor is functional or anonymous. Google Analytics
 * (lib/analytics.ts) is the exception: it sets a first-party cookie, so it
 * is disclosed below and has a per-device opt-out instead of a banner.
 *
 * Every row here is a promise: when what a feature stores, sends or logs
 * changes, this page changes in the same PR. The Localz rows follow
 * docs/LOCALZ_DESIGN.md; the upload row is the deliberate exception to "no
 * IPs" (frontend/CLAUDE.md). */
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
        description="What schoolz and Localz store about visitors and account holders, who else sees it, and how to delete it - no advertising or ad tracking."
        path="/privacy"
      />
      <h2>Privacy &amp; cookies</h2>
      <p className="note">Last updated October 17, 2026.</p>

      <p>
        schoolz ("we", "us") helps parents and guardians in South Jersey keep up with their kids' schools, and
        Localz, part of schoolz, helps people find local help with food, housing, health and more. This page
        explains what the site stores about you, who else sees it, and why. Questions or requests (including to
        access, correct, or delete your data) can be sent to{" "}
        <a href="mailto:enr@profitnaut.com">enr@profitnaut.com</a>.
      </p>

      <h3>You don't need an account to use most of this site</h3>
      <p>
        Schools, districts, the calendar, newsletters, lunch menus, the staff directory, local events and Localz
        are public, with no login. Registering is only needed for the optional personal layer: linking your own
        kids, narrowing the calendar to their schools, and the Kids View of their assignments and grades.
      </p>

      <h3>What we store, and why</h3>
      <h4>On your device</h4>
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
              So the Today/Calendar/Lunch pages remember your schools without needing an account. Never sent to us
              or any third party — it stays on your device.
            </td>
          </tr>
          <tr>
            <td>The place and distance you choose on the Local events page</td>
            <td>Your browser's local storage</td>
            <td>
              So the page shows events near you. Your device's location is requested only if you press "Use my
              current location". The point is rounded to about half a mile and sent with the events request to
              work out distances; we don't save it. An address or ZIP code you type is passed to the U.S. Census
              Bureau and OpenStreetMap geocoders to find it on the map, and isn't saved by us either.
            </td>
          </tr>
          <tr>
            <td>
              Your location in Localz: the county, and the ZIP code, area code or rounded point you set it from, and
              how far you want to look
            </td>
            <td>Your browser's local storage</td>
            <td>
              So Localz shows help that serves where you are. A ZIP code, area code or your device's location is
              turned into a county on your device, using a list of New Jersey ZIP codes built into the site - none
              of them is sent to us or anyone else. Your device's location is requested only if you press "Use my
              current location", and is rounded to about half a mile before it's kept. A search sends only the
              county name and, to list help closest first, a wide box around you (whole half-degrees of latitude
              and longitude, tens of miles across); your device measures the distances itself. What you type into Localz search is sent to us only to find matching listings - in the
              request body, never in the page address - and we don't save it. Localz pages never load Google
              Analytics, and which listing you open is stripped from our performance data.
            </td>
          </tr>
          <tr>
            <td>
              Your answers to "What am I eligible for?" in Localz (ages in your household, things like being a
              veteran, and which services you'd like to see first)
            </td>
            <td>Your browser's session storage, or its local storage if you tick "Remember on this device"</td>
            <td>
              So Localz can put the listings that fit you first. They're matched on your device against what each
              listing says about who it's for - your answers are never sent to us or anyone else, unless you choose
              to save them to your account (below). Without "Remember on this device" they're forgotten when you
              close the tab or press Quick exit. With it, they're kept under a name that doesn't say what they are,
              for 90 days at most, and "Forget this device" or Quick exit removes them at once. We never ask about
              gender, race or immigration status.
            </td>
          </tr>
          <tr>
            <td>Light/dark theme choice, and your language</td>
            <td>Your browser's local storage</td>
            <td>Remembers your display preferences between visits.</td>
          </tr>
          <tr>
            <td>Login session</td>
            <td>A token set by our authentication provider, Supabase</td>
            <td>
              Strictly necessary to keep you signed in if you register. Set only if you create an account; not set
              for anonymous visitors.
            </td>
          </tr>
        </tbody>
      </table>

      <h4>Anonymous measurement</h4>
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
            <td>Anonymous performance &amp; error data (page load times, which pages are used, JS errors)</td>
            <td>Grafana Cloud, our monitoring provider</td>
            <td>
              We collect anonymous performance and error data to make the site faster. It's tied to a random
              per-visit session, never to your name, email, or children, and isn't shared with advertisers. Login
              tokens, invite links, which Localz listing you opened, and other sensitive URL content are stripped
              before anything is sent.
            </td>
          </tr>
          <tr>
            <td>A count of visits to each public page, and roughly where visitors came from (e.g. "facebook")</td>
            <td>Our database</td>
            <td>
              So we can tell whether a post about this project actually reached anyone.{" "}
              <strong>This is a running tally, not a record of you</strong> — we store one number per page, per
              day, per source, and nothing else. No id, no IP, no profile, no cookie, nothing that could be traced
              back to a person or linked between visits. If a link brings you here with a tracking code attached
              (Facebook adds one), we read it once to label the visit "facebook" and then discard it — it's never
              stored or sent on.
            </td>
          </tr>
          <tr>
            <td>
              Anonymous usage statistics from Google Analytics: which pages are viewed, device type (phone or
              computer), approximate area, the town and school district of the schools you picked, which schools'
              pages and Today cards were shown, and how you got here
            </td>
            <td>A first-party analytics cookie, and Google Analytics</td>
            <td>
              So we can see which towns and districts actually use schoolz and which pages help, and so this project
              can be shown to the districts it serves. Advertising features and Google signals are turned off, we
              send Google no name, email, account or child information, and personal pages are reported only as
              "account" or "children", never with anything on them. Localz pages and the kids' Focus app send
              Google nothing. You can{" "}
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
        </tbody>
      </table>

      <h4>If you have an account</h4>
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
            <td>Account info (email, username), your linked children (name, student ID, school), guardian invites</td>
            <td>Our database</td>
            <td>
              Powers the personal layer described above. A child's record is shared only with the guardians linked
              to it — by an invite, or when two guardians add the same child, in which case every linked guardian
              is told — and is never made public.
            </td>
          </tr>
          <tr>
            <td>
              Your child's schoolwork in the Kids View: the school-portal pages you publish from Backpack Capture
              (assignments, due dates, grades, class schedule), and what's read from them
            </td>
            <td>Our database</td>
            <td>
              Only if you publish captures from the{" "}
              <a href="/backpack-capture/privacy">Backpack Capture</a> browser extension. The pages are read by our
              own code, not by an AI service, into your child's due/missing/done lists and grades, which every
              guardian linked to that child — and the child, if they have their own login — can see. We keep a
              trimmed copy of each page you published so it can be read again when we improve the reader.
            </td>
          </tr>
          <tr>
            <td>
              Things you add about your child's classes: specials days, late-work policies, teacher exceptions, and
              help requests your child sends from Focus
            </td>
            <td>Our database</td>
            <td>
              Facts about the child are shared with every guardian linked to them. A help request records which
              assignment and what kind of help; the message itself is sent from your child's own email app — we
              never send email to teachers.
            </td>
          </tr>
          <tr>
            <td>Your own preferences: renamed or recolored classes, "I've paid this" ticks, notification read-state</td>
            <td>Our database</td>
            <td>Kept per account, so another guardian of the same child never sees them.</td>
          </tr>
          <tr>
            <td>
              Your saved Localz answers ("My services profile"): the same answers as "What am I eligible for?",
              and the date you agreed to save them
            </td>
            <td>Our database, encrypted with a key of its own</td>
            <td>
              Only if you turn on "Save to my account" and agree on a separate screen that explains it first, so
              you can use the same answers wherever you're signed in. Only you can see them: not other guardians,
              even ones linked to the same children, not schools, and no page, report or tool in schoolz shows them
              to the people who run the site. They're stored as one locked block that our server opens only to
              show it to you, and they're never used for anything else or sent to an AI service. Delete them with
              one tap in Account, My services profile, or by withdrawing your consent; they're deleted right away,
              and with your account if you delete it. Like everything else, a deleted copy can remain in our
              encrypted backups until they're replaced (see "How long we keep it").
            </td>
          </tr>
          <tr>
            <td>A child's own login (email, and which child it belongs to)</td>
            <td>Our database, and Supabase for the sign-in</td>
            <td>
              Only if a guardian invites the child to sign in to Focus. The child sees the same schoolwork their
              guardians do. Focus loads no analytics.
            </td>
          </tr>
          <tr>
            <td>Gmail read-only access token (site administrators only)</td>
            <td>Our database, encrypted at rest</td>
            <td>
              Used solely to find school newsletter links in an inbox an administrator connects to keep the public
              pages current. We never send, delete, or modify email. Guardians aren't offered this.
            </td>
          </tr>
          <tr>
            <td>If you list a program on Localz: your account email, the contact person you give us, and the emails we send you</td>
            <td>Our database; the emails go out through Google (Gmail)</td>
            <td>
              Seen by our reviewers, to check the listing is really yours. We email you about your request, codes to confirm it's
              you, and a reminder every few months to check your listing. Our copy of each email is erased once it's sent; Gmail keeps
              one in our sent mail. People looking for help are never emailed.
            </td>
          </tr>
        </tbody>
      </table>

      <h4>Things you choose to send us</h4>
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
            <td>Your messages to the assistant (the chat button), and its answers</td>
            <td>Sent to our AI provider, Anthropic; not saved by us</td>
            <td>
              To answer your question. The conversation lives only in the open page and is gone when you reload.
              If you're signed in, the assistant can look up your own children's schedules and schoolwork to answer
              you, read-only. Our server logs record which lookups the assistant made — for public lookups, what it
              searched for; for your children, only which kind of lookup — never your messages. To keep the
              assistant from being flooded, we count messages per internet connection over 10 minutes using a
              scrambled one-way code, never your IP address; those counts are deleted after a day.{" "}
              <a href="https://www.anthropic.com/legal/privacy" target="_blank" rel="noopener noreferrer">
                Anthropic's privacy policy
              </a>{" "}
              covers what it does with the text it receives.
            </td>
          </tr>
          <tr>
            <td>Your name, email and message, if you use the contact form</td>
            <td>Our database</td>
            <td>Read by the people who run schoolz so we can answer you. Name and email are optional.</td>
          </tr>
          <tr>
            <td>
              Your survey answers (the schools you picked, what you said is hard to find, your comments, and your
              name and email if you chose to give them)
            </td>
            <td>Our database</td>
            <td>
              Only if you fill in the <a href="/survey">survey</a>. Name and email are optional and blank by
              default; your email is never shared with the district or anyone else — it's only so we can follow up.
              Your comments may be quoted to the district <strong>without your name</strong> unless you explicitly
              tick "you can use my name."
            </td>
          </tr>
          <tr>
            <td>
              Proof a survey response is genuine: the date and time it arrived, which browser sent it, and a
              scrambled one-way code that stands in for your internet connection
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
            <td>
              A security record of account and access changes: when you change or reset your password, delete your
              account, accept an invitation to a child's records, or remove a student's login, plus everything
              admins do to accounts, roles, keys and connected inboxes
            </td>
            <td>Our database</td>
            <td>
              So we can always answer "who changed this, and when". Each entry holds what was done, by which
              account, the date and time, and a scrambled one-way code in place of your IP address. Never passwords,
              invitation links or the contents of anything. Entries can't be edited or deleted, are seen only by
              the people who run schoolz, and stay after the account they mention is deleted.
            </td>
          </tr>
          <tr>
            <td>
              Where an upload came from: your IP address, which browser sent it, the page it was sent from, the date
              and time, and a fingerprint (hash) of the file
            </td>
            <td>Our database</td>
            <td>
              Only if you use the <a href="/upload">upload form</a>, and unlike the survey this is your{" "}
              <strong>real IP address</strong>. It's the one place a stranger can put a file on this site, so we
              keep a record of who sent what to protect the families who use it. The record is kept even if the
              upload is deleted or refused, is seen only by the people who run schoolz, and is handed to law
              enforcement or the National Center for Missing &amp; Exploited Children if someone uploads illegal
              content. It isn't used for advertising or to track you around the site. That form also runs
              Cloudflare Turnstile, a check that you're a person, which is loaded from Cloudflare only on that page.
            </td>
          </tr>
        </tbody>
      </table>

      <h3>Where AI is used</h3>
      <p>
        We use Anthropic's Claude for the assistant (above), to read public school newsletters, calendars and
        flyers, to translate public school content into Spanish, Chinese, Korean and Hindi, to read who a Localz
        listing serves, and for three Kids View helpers. Those three send the least they can: a "how to approach
        this" tip gets only an assignment's title and class name, shared by everyone in that class; "help me plan"
        gets only your child's open assignment titles, class names and due dates, with no name or student ID; and
        reading a late-work policy gets only the syllabus paragraph you paste. Your Localz answers (on your device
        or saved to your account) and location never go to an AI service.
      </p>

      <h3>What we don't do</h3>
      <ul>
        <li>No advertising or ad-tracking cookies of any kind — Google Analytics runs with advertising features off.</li>
        <li>No selling or sharing your data with advertisers or data brokers.</li>
        <li>No cross-site tracking — nothing here follows you to other websites.</li>
        <li>
          No identifying you personally in our performance/error monitoring — it's tied to a random per-visit
          session, not your account, name, or email.
        </li>
        <li>No email from us: schoolz doesn't send newsletters or alerts. The only email you'll get is sign-in mail from Supabase.</li>
      </ul>

      <h3>Why there's no "accept cookies" popup</h3>
      <p>
        schoolz serves families in New Jersey, and the only non-essential thing it uses is the anonymous usage
        analytics described above, with advertising turned off. Rather than a popup, there's an opt-out you can use
        on this page at any time, and this notice says exactly what is collected. If that ever changes (for example
        ads, or analytics that identifies you), this notice and a real consent choice will change with it.
      </p>

      <h3>Third parties involved</h3>
      <ul>
        <li>
          <strong>Supabase</strong> — handles sign-in, and hosts our database.
        </li>
        <li>
          <strong>Fly.io</strong> — hosts the website and backend.
        </li>
        <li>
          <strong>Anthropic</strong> — the AI service described above.
        </li>
        <li>
          <strong>Google Analytics</strong> — receives the anonymous usage statistics described above.
        </li>
        <li>
          <strong>Grafana Cloud</strong> — receives the anonymous performance/error data described above, plus
          backend operational metrics and logs. No account data, schoolwork or chat messages pass through it.
        </li>
        <li>
          <strong>Cloudflare</strong> — stores our encrypted nightly backups, and runs the person check on the
          upload form.
        </li>
        <li>
          <strong>GitHub</strong> — runs the nightly backup job, which encrypts the backup before storing it.
        </li>
        <li>
          <strong>U.S. Census Bureau and OpenStreetMap</strong> — only an address or ZIP code you type on the Local
          events page, to find it on the map.
        </li>
      </ul>

      <h3>How long we keep it</h3>
      <ul>
        <li>Account data is kept until you delete your account.</li>
        <li>
          Saved Localz answers are kept until you delete them, withdraw your consent, or delete your account,
          whichever comes first. Answers remembered on your device expire after 90 days.
        </li>
        <li>
          Our database is backed up every night, and each backup is encrypted before it's stored. Daily backups are kept 35
          days and the first-of-the-month backup 400 days, so something you delete can survive in an encrypted
          backup for up to about 13 months before it's gone for good. Backups are only ever used to recover from a
          failure.
        </li>
        <li>Contact messages, survey responses and upload records are kept until we delete them.</li>
        <li>Security records of account and access changes are kept permanently.</li>
      </ul>

      <h3>Your rights</h3>
      <p>
        You can clear your browser's storage at any time to remove everything kept on your device. If you have an
        account, you can remove a child from your account on the Children page, and delete your whole account on
        the Account page. Deleting your account removes your login, your links to your children, your invites,
        your notifications, your own preferences, your saved Localz answers and your consent records, and the
        Backpack Capture pages you published. A child's record
        and schoolwork stay for any other guardian still linked to them; if you were the last one, email us and we
        will delete the child's record too. Email us as well to correct inaccurate data or to ask what we hold
        about you.
      </p>
    </>
  );
}
