/** Privacy policy for the Backpack Capture Chrome extension (a separate
 * product from schoolz itself - see the sibling backpack-capture repo).
 * Hosted here, not as a claude.ai artifact, because the Chrome Web Store's
 * review crawler fetches the privacy-policy URL logged out; an artifact set
 * to private returns an access-denied page to a logged-out fetch, which the
 * Store treated as "not a valid privacy policy" (rejection reason: "Privacy
 * policy link does not lead to a valid privacy policy"). A route on a site
 * this project already controls and already prerenders for bots (see
 * frontend/nginx.conf.template) avoids depending on a Claude account's
 * sharing settings for something the Store re-checks on every review. */
import { SeoHead } from "../components/SeoHead";
import { usePrerenderReady } from "../lib/prerenderReady";

export function BackpackCapturePrivacyPage() {
  usePrerenderReady(true);
  return (
    <>
      <SeoHead
        title="Backpack Capture Privacy Policy · schoolz"
        description="What the Backpack Capture Chrome extension reads, stores, and can send off your device - and the two explicit actions that are the only way any of it leaves."
        path="/backpack-capture/privacy"
      />
      <h2>Backpack Capture Privacy Policy</h2>
      <p className="note">Effective September 18, 2026 · Applies to versions 0.7.x and later</p>

      <p>
        Backpack Capture is a Chrome extension, separate from schoolz's own website, that reads the Google
        Classroom and Genesis Parent Portal pages a parent already has open, so they can see what's due
        without hand-copying it. This page describes, plainly, what that involves - what's read, what's
        kept, and the two specific actions that can move any of it off the device.
      </p>

      <h3>In short</h3>
      <ul>
        <li>
          <strong>Nothing is captured</strong> until you press Start capture, and only on Classroom or
          Genesis pages - Chrome enforces this, the extension's code never loads anywhere else.
        </li>
        <li>
          <strong>It never logs in, and never reads passwords or cookies.</strong> It only reads the
          rendered page a person is already signed into.
        </li>
        <li>
          <strong>Everything stays on your device</strong> in the browser's local extension storage, until
          you export a file or choose to publish.
        </li>
        <li>
          <strong>Two actions move data off the device</strong>, and both require pressing a button each
          time: exporting a local file, or publishing to your own schoolz account.
        </li>
        <li>
          <strong>No analytics, no telemetry, no advertising, no third-party trackers</strong> - anywhere in
          this extension.
        </li>
      </ul>

      <h3>What it reads</h3>
      <p>
        Backpack Capture is restricted, at the browser level, to two kinds of page:{" "}
        <code>classroom.google.com</code> and any Genesis Parent Portal page matching{" "}
        <code>*/genesis/parents*</code>. On every other site, Chrome never loads the extension's code - it
        cannot see, read, or record any other page you visit.
      </p>
      <p>
        When capture is switched on and you open one of those pages, it reads the page's own rendered
        content: the same text and structure already visible on your screen, in the session you're already
        signed into. It strips out scripts, styles, images, and generated class names, keeping only the
        semantic content - assignment titles, due dates, class names, schedule blocks - reduced to a
        compact text form.
      </p>
      <p>
        Nothing is captured before you press <strong>Start capture</strong>, and a badge stays visible on
        the toolbar icon for as long as capture is active.
      </p>

      <h3>What it stores</h3>
      <p>Each captured page is saved as one record, held only in the browser's own local extension storage:</p>
      <table className="table" style={{ marginTop: 8 }}>
        <thead>
          <tr>
            <th>Field</th>
            <th>What it holds</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Reduced text</td>
            <td>The page's stripped-down content - titles, dates, schedule and grade text</td>
          </tr>
          <tr>
            <td>Source URL</td>
            <td>The Classroom or Genesis address the page came from</td>
          </tr>
          <tr>
            <td>Timestamp &amp; time zone</td>
            <td>When the capture happened</td>
          </tr>
          <tr>
            <td>Account index / student ID</td>
            <td>
              Which Google account (<code>/u/0/</code>, <code>/u/1/</code>…) or Genesis student the page
              belongs to, so captures from more than one child don't mix together
            </td>
          </tr>
          <tr>
            <td>Status</td>
            <td>
              A confidence label (<code>ok</code>, <code>low confidence</code>, <code>layout changed?</code>,{" "}
              <code>login wall</code>) so a broken or incomplete capture is never mistaken for a good one
            </td>
          </tr>
        </tbody>
      </table>
      <p>
        None of this is transmitted anywhere by default - it sits in <code>chrome.storage.local</code>,
        readable only by this extension, on this device.
      </p>

      <h3>What it never touches</h3>
      <ul>
        <li>Passwords, or any part of a login form</li>
        <li>Cookies, session tokens, or <code>localStorage</code> belonging to Classroom or Genesis</li>
        <li>Any website other than the two listed above</li>
        <li>Anything before you explicitly start a capture session or press Capture</li>
      </ul>
      <p>
        The extension's declared permissions reflect this directly: it has no <code>cookies</code> or{" "}
        <code>webRequest</code> permission, and no access to any host beyond Classroom, Genesis, and (only
        for the optional feature below) schoolz's own API.
      </p>

      <h3>What can leave your device - and only this</h3>
      <p>Exactly two actions ever send anything anywhere, and both require a person to press a button, each time:</p>
      <ol>
        <li>
          <strong>Export capture</strong> - writes everything currently stored to a single JSON file, saved
          wherever you choose on your own device. This is a local file save; nothing is transmitted to a
          server.
        </li>
        <li>
          <strong>Publish captures</strong> - sends the same stored records to your own schoolz family
          account (see below). Off until you log in, and only runs when you press Publish.
        </li>
      </ol>
      <p>There is no background sync, no scheduled upload, and no telemetry of any kind.</p>

      <h3>Publishing to schoolz</h3>
      <p>
        Backpack Capture can optionally send your captures to your own schoolz family account so they appear
        in your child's due/missing/done view, instead of (or alongside) exporting a file by hand.
      </p>
      <p>Logging in works one of two ways, both handled by schoolz's own authentication system:</p>
      <ul>
        <li>
          <strong>Email and password</strong> - sent directly to schoolz's sign-in service; the extension
          never stores your password, only the session token that comes back.
        </li>
        <li>
          <strong>Continue with Google</strong> - uses Chrome's own built-in sign-in flow (
          <code>chrome.identity</code>); Google credentials are never seen by, or available to, this
          extension.
        </li>
      </ul>
      <p>
        Once logged in, pressing <strong>Publish captures</strong> sends every capture currently stored to
        the student you select on your own schoolz account. What happens to that data once it's in schoolz
        is covered by <a href="/privacy">schoolz's own privacy policy</a>.
      </p>
      <p className="note">
        Logging out clears the stored session from the extension only - it does not delete anything already
        published, and does not close your schoolz account.
      </p>

      <h3>Children's data</h3>
      <p>
        This extension is built for parents and guardians to use on their own device, reading their own or
        their child's school-portal pages that they are already signed into. It does not collect
        information directly from children, does not present any interface to a child, and does not
        knowingly interact with anyone under 13 as a user of the extension itself.
      </p>
      <p>
        Because the pages it reads can include a student's assignments, grades, and schedule, treat any
        exported file or published data the same way you'd treat a report card or a school folder - it
        belongs to your family, and you decide who else sees it.
      </p>

      <h3>Retention &amp; deletion</h3>
      <ul>
        <li>
          Captures stay in local storage until you delete them individually, press Clear all, or uninstall
          the extension - any of which removes them completely from this device.
        </li>
        <li>An exported file exists only where you saved it; deleting it is the same as deleting any other file you own.</li>
        <li>Data already published to schoolz is retained under schoolz's own policy, independent of this extension.</li>
        <li>Uninstalling Backpack Capture deletes all locally stored captures and any saved schoolz login.</li>
      </ul>

      <h3>Changes to this policy</h3>
      <p>
        If what this extension reads, stores, or sends ever changes, this page will be updated to match,
        and the effective date above will change with it. The extension's source is public, so any change
        in behavior is checkable directly against the code, not just this description of it.
      </p>

      <h3>Contact</h3>
      <p>
        Backpack Capture is an open-source project. Questions, concerns, or reports about this policy can be
        sent to <a href="mailto:enr@profitnaut.com">enr@profitnaut.com</a>, or filed as an issue on its
        repository:{" "}
        <a href="https://github.com/weirdaze/backpack-capture" target="_blank" rel="noopener noreferrer">
          github.com/weirdaze/backpack-capture
        </a>
        .
      </p>
      <p className="note">
        Backpack Capture reads Google Classroom and Genesis Parent Portal pages locally in your browser. It
        is not affiliated with, endorsed by, or a product of Google, Genesis, or any school district.
      </p>
    </>
  );
}
