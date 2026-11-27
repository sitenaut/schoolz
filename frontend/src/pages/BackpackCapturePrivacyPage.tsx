/** Privacy policy for the Backpack Capture Chrome extension (a separate
 * product from schoolz itself - see the sibling backpack-capture repo).
 * Hosted here, not as a claude.ai artifact, because the Chrome Web Store's
 * review crawler fetches the privacy-policy URL logged out; an artifact set
 * to private returns an access-denied page to a logged-out fetch, which the
 * Store treated as "not a valid privacy policy" (rejection reason: "Privacy
 * policy link does not lead to a valid privacy policy"). A route on a site
 * this project already controls avoids depending on a Claude account's
 * sharing settings for something the Store re-checks on every review.
 *
 * nginx.conf.template's bot-detection proxy is a catch-all, but
 * services/prerender.py gates it with its own explicit _ALLOWED_PATHS -
 * this path has to be added there too, or a logged-out crawler hit 404
 * exactly as if the page didn't exist. */
import { SeoHead } from "../components/SeoHead";
import { usePrerenderReady } from "../lib/prerenderReady";

const STORE_URL = "https://chromewebstore.google.com/detail/backpack-capture/imjhghdlhjgoeghhgafdpclapkjcnfbe";

export function BackpackCapturePrivacyPage() {
  usePrerenderReady(true);
  return (
    <>
      <SeoHead
        title="Backpack Capture Privacy Policy · schoolz"
        description="What the Backpack Capture Chrome extension reads, stores, and can send off your device - and the explicit actions that are the only way any of it leaves."
        path="/backpack-capture/privacy"
      />
      <h2>Backpack Capture Privacy Policy</h2>
      <p className="note">Effective November 27, 2026 · Applies to versions 0.7.x and later</p>

      <p>
        Backpack Capture is a Chrome extension, separate from schoolz's own website, that reads the Google
        Classroom and Genesis Parent Portal pages a parent already has open, so they can see what's due
        without hand-copying it. From version 0.11.0 it can also save a college student's own Canvas work.
        This page describes, plainly, what that involves - what's read, what's kept, and the specific
        actions that can move any of it off the device.
      </p>

      <h3>In short</h3>
      <ul>
        <li>
          <strong>Nothing is captured</strong> until you press Update schoolz or Start capture (or turn on
          automatic updates), and only on Classroom, on the one Genesis site you allow, and on Canvas when
          you ask it to there - Chrome enforces this, and gives the extension no other website.
        </li>
        <li>
          <strong>It never reads cookies, and never logs in unless you set up the optional Genesis sign-in
          helper</strong> (below). Otherwise it only reads the rendered page a person is already signed into.
        </li>
        <li>
          <strong>Everything stays on your device</strong> in the browser's local extension storage, until
          you export a file or choose to publish.
        </li>
        <li>
          <strong>Only you decide what leaves the device</strong>: exporting a local file, pressing Update
          now or Publish to send it to your own schoolz account, or - only if you turn them on - automatic
          updates that do the same every few hours. Your Canvas work is saved as a file on your own
          computer, and goes to your own billz account only if you connect it.
        </li>
        <li>
          <strong>No analytics, no telemetry, no advertising, no third-party trackers</strong> - anywhere in
          this extension.
        </li>
      </ul>

      <h3>What it reads</h3>
      <p>
        Backpack Capture is restricted, at the browser level, to <code>classroom.google.com</code>, to the
        Genesis Parent Portal pages (<code>/genesis/parents</code>) of the one district site you allow, and
        to your Canvas site when you ask it to read that. Chrome gives it no other website - it cannot see,
        read, or record any other page you visit.
      </p>
      <p>
        <strong>Genesis is a site you allow.</strong> Every district runs Genesis on its own address, so from
        version 0.15.0 the extension holds no Genesis site until you say yes: it shows the address (your
        children&apos;s district&apos;s, which schoolz sends it with their names, or the Genesis tab you
        opened it on), you press Allow Genesis, and Chrome asks you about that one site. You can take it
        back at any time on Chrome&apos;s own extension page. Versions before 0.15.0 named Genesis by its
        path alone, which Chrome treats as access to every website; they read only Genesis parent pages,
        and 0.15.0 removes that wider access.
      </p>
      <p>
        When capture is switched on and you open one of those pages, it reads the page's own rendered
        content: the same text and structure already visible on your screen, in the session you're already
        signed into. It strips out scripts, styles, images, and generated class names, keeping only the
        semantic content - assignment titles, due dates, class names, schedule blocks - reduced to a
        compact text form.
      </p>
      <p>
        Nothing is captured before you press <strong>Update schoolz</strong> or <strong>Start capture</strong>{" "}
        (or automatic updates you turned on run), and a badge stays visible on the toolbar icon for as long
        as capture is active.
      </p>
      <p>
        <strong>Finding your child's Google account.</strong> Update schoolz (version 0.9.0 and later) opens the
        Classroom home page of each Google account signed in to this Chrome, one at a time, and reads that
        account's name and email address to tell whether it belongs to one of your children on schoolz - by
        their name, or because you told it so. schoolz never tells the extension your children's student IDs
        (from version 0.9.5): it checks a school login's student ID itself when the pages arrive, and an
        account it says is another student's isn't opened again. The page of an account that isn't one
        of your children's is deleted from the device straight away and never sent anywhere. When it can't
        tell, it asks you once (&quot;whose Google Classroom is this?&quot;) and remembers your answer on this
        device.
      </p>

      <h3>Canvas: your own work</h3>
      <p>
        For a college student whose school uses Canvas (version 0.11.0 and later). On your own signed-in
        Canvas tab, <strong>Save my Canvas work</strong> asks Canvas, the way its own pages do, for: who you
        are; your current courses with your grade in each; each course&apos;s assignments with your
        submission (dates, score, grade, and whether it is late, missing or excused); and, from version
        0.13.0, your groups, each course&apos;s announcements, your Canvas inbox with its messages and the
        names of the people in each conversation, the events on your calendars, your To Do list and each
        course&apos;s syllabus. It keeps no assignment descriptions, submission comments or files, and it
        never marks a message read. What it read is saved as one file in your downloads. That file is not
        kept in the extension, and it never goes to schoolz.
      </p>
      <p>
        <strong>Sending it to billz</strong> (version 0.14.0 and later, off unless you connect it). billz is
        a separate, invitation-only household app. If you press Connect to billz, Chrome asks to let the
        extension read your Canvas site and reach billz, and you approve the connection on billz&apos;s own
        page by checking a code. The extension then holds a key that can do one thing: send your Canvas
        file to your own billz account. It reads nothing from billz. About every four hours, while Chrome is
        open and Canvas is signed in, it reads Canvas the same way and sends the same file. Disconnect from
        billz removes the key from billz too, and stops it.
      </p>
      <p>
        <strong>How long Canvas keeps you signed in</strong> (version 0.14.0 and later, off unless you turn
        it on). On a timer you choose, the extension asks Canvas one thing - whether this browser is signed
        in - and keeps only when it asked and the answer (in, out, or no answer). The same short log is
        saved as a file in your downloads. Nothing Canvas answers is read or kept, and nothing is sent
        anywhere.
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
            <td>Whose account</td>
            <td>
              Which of your children each Google account belongs to, and the account number it was last
              found at, so the next update goes straight there
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

      <h3>Optional: signing in to Genesis by itself</h3>
      <p>
        Genesis signs a parent out after a short while, so automatic updates often find it signed out and
        read no grades. From version 0.12.0, on a Windows computer, you can install a separate sign-in helper
        that reads your Genesis login from your own password manager (1Password). Once it&apos;s installed and
        you turn it on in the extension (More → Sign in to Genesis by itself, which asks Chrome for the
        &quot;native messaging&quot; permission), an update that finds Genesis signed out asks the helper for
        the login, types it into Genesis&apos;s own sign-in page - only on the Genesis address the helper was
        set up for - and carries on. It tries once per update; if that doesn&apos;t work, the update says so
        on My family.
      </p>
      <p>
        The extension doesn&apos;t store the login, doesn&apos;t write it to its update log, and never sends it
        to schoolz or anywhere but Genesis&apos;s sign-in page. The helper keeps only its access key for your
        password manager, encrypted for your Windows account, and a short record of when it was asked. Without
        the helper, none of this happens.
      </p>

      <h3>What it never touches</h3>
      <ul>
        <li>
          Passwords or login forms, except your Genesis login when the sign-in helper is set up: it is typed
          into Genesis&apos;s sign-in page and never kept or sent anywhere else
        </li>
        <li>Cookies, session tokens, or <code>localStorage</code> belonging to Classroom or Genesis</li>
        <li>Any website other than Classroom, the Genesis site you allowed, and your Canvas site when you ask</li>
        <li>Anything before you press Update schoolz, start a capture session, press Capture, or turn on automatic updates</li>
      </ul>
      <p>
        The extension's declared permissions reflect this directly: it has no <code>cookies</code> or{" "}
        <code>webRequest</code> permission, and from the start it can reach only Classroom and (for the
        optional features below) schoolz's own API and sign-in service. Any other site - your Genesis, your
        Canvas, billz - is one Chrome asked you about. Its <code>alarms</code> permission exists only for
        the timed things you turn on (automatic updates, sending to billz, the Canvas sign-in check), its{" "}
        <code>scripting</code> permission only reads Canvas in your Canvas tab, loads the Genesis reader on
        the Genesis site you allowed and fills Genesis&apos;s sign-in form for the helper, its{" "}
        <code>sidePanel</code> permission (version 0.16.0 and later) only lets it show itself beside the page
        instead of in a popup, and its optional{" "}
        <code>nativeMessaging</code> permission is asked for only when you turn on the Genesis sign-in
        helper, and only lets it talk to that helper.
      </p>

      <h3>What can leave your device - and only this</h3>
      <p>Only these send anything anywhere, and each is something a person chose:</p>
      <ol>
        <li>
          <strong>Export capture</strong> - writes everything currently stored to a single JSON file, saved
          wherever you choose on your own device. This is a local file save; nothing is transmitted to a
          server.
        </li>
        <li>
          <strong>Update schoolz</strong> (named Update schoolz before version 0.16.0) - opens Classroom in its own window, finds your children's Google
          accounts (see above), walks their classes the same way a capture session does, and sends what's
          new to your own schoolz family account. Only runs when you press it, after you've signed in to
          schoolz in the extension. From version 0.10.0, once you've opened your school district&apos;s
          Genesis parent portal in that Chrome (the extension remembers its address, on your device only), it
          first reads the gradebook there: Grade Summary, List Assignments and each class&apos;s Course
          Summary, for each child on your schoolz account whose name Genesis lists. A child in your Genesis
          account who isn&apos;t on schoolz is never opened. If Genesis has signed you out, it signs in with
          the sign-in helper if you set one up; otherwise, or if that doesn&apos;t work, it asks you to sign in
          on Genesis&apos;s own page or skip Genesis this time.
        </li>
        <li>
          <strong>Publish captures</strong> - sends pages you captured by hand to your own schoolz family
          account (see below). Only runs when you press Publish.
        </li>
        <li>
          <strong>Automatic updates</strong> - off by default. If you turn them on, the same thing Update
          now does runs every four hours (never between 10pm and 6am). It doesn&apos;t sign in to Genesis
          unless you&apos;ve set up the sign-in helper; without it, when Genesis has signed you out, it skips
          Genesis and goes on to Classroom. It never signs in to Google: when a
          child's sign-in expires it stops and tells schoolz, which notifies you. Turning it off stops it
          completely.
        </li>
        <li>
          <strong>The update log</strong> (version 0.9.3 and later; 0.9.1 and 0.9.2 sent it only when you
          pressed Send logs) - as each update ends, the extension sends schoolz its own record of that update,
          so one that went wrong can be looked into without you having to report it. It holds: the
          extension's version, your computer's operating system and Chrome version; which Google account
          numbers it opened and whether each was one of your children's (by your child's schoolz record,
          never another account's name or email); the web addresses of Google sign-in pages it passed
          through, without the part that can name an account; the Classroom addresses (class and assignment
          numbers, no titles) of pages that were slow or had to be reloaded; which kinds of Genesis gradebook
          page it read for each child and for which marking period (never a student ID), and the address of
          Genesis&apos;s sign-in page if it was shown, without the part after the &quot;?&quot;; whether it
          asked the sign-in helper for your Genesis login and whether signing in worked (never the login
          itself); how many
          classes and pages it
          read for each child and how many didn't load; where it stopped; and how many pages it sent. No page
          content and no names. With it goes a short summary of the update that schoolz shows you on My
          family: when it finished, how many pages it sent and when pages were last sent, which of your
          children aren't set up in that Chrome yet, and anything that needs a look, in plain sentences that
          use your child's first name (for example, that Google wants their sign-in again). It's only sent
          after an update you pressed or automatic updates you turned on. schoolz keeps it for 30 days, or 90
          if you report a problem with that update, and only the people on the schoolz team who help with
          Backpack Capture problems can read it. <strong>Report a problem</strong> on My family sends them
          your note and your account's email address, linked to that update's log.
        </li>
      </ol>
      <p>
        The two Canvas things above are the only others: <strong>Save my Canvas work</strong> writes a file
        to your own downloads, and <strong>Connect to billz</strong>, if you choose it, sends that file to
        your own billz account every few hours until you disconnect.
      </p>
      <p>
        Apart from updates (yours, or automatic ones you turned on), their logs, and a billz connection you
        made, there is no background sync or upload, and nothing about the rest of your browsing is ever
        collected.
      </p>

      <h3>Publishing to schoolz</h3>
      <p>
        Backpack Capture can optionally send your captures to your own schoolz family account so they appear
        in your child's due/missing/done view, instead of (or alongside) exporting a file by hand.
      </p>
      <p>Connecting it to your account works one of three ways:</p>
      <ul>
        <li>
          <strong>Connect to schoolz</strong> (version 0.9.0 and later) - opens schoolz in a tab, where you
          sign in the way you always do and press Connect after checking the code matches the one the
          extension shows (if the request came from a different internet connection than yours, you type that
          code in instead). The extension then gets its own key, which can only send pages, list your children's
          names (never their student IDs), report how an update went and send each update's log and summary - it can't read anything else in
          your account. Each connected
          computer is listed under Account → Security on schoolz, where you can disconnect it, and the
          extension's own Sign out removes its key.
        </li>
        <li>
          <strong>Email and password</strong> - sent directly to schoolz's sign-in service; the extension
          never stores your password, only the session token that comes back.
        </li>
        <li>
          <strong>Sign in with Google</strong> - uses Chrome's own built-in sign-in flow (
          <code>chrome.identity</code>); Google credentials are never seen by, or available to, this
          extension.
        </li>
      </ul>
      <p>
        Once you're signed in, Update schoolz and Publish send captured pages to your own schoolz account,
        where each page is filed under the child it belongs to - by its Genesis student ID, by the Classroom
        account it came from, or by your answer to &quot;whose Google Classroom is this?&quot;. A page that
        can't be matched to one of your children isn't kept. What happens to the data once it's in schoolz
        is covered by <a href="/privacy">schoolz's own privacy policy</a>.
      </p>
      <p className="note">
        Signing out clears the stored login from the extension (and, for a computer connected with Connect to
        schoolz, removes its key from your account) - it does not delete anything already sent, and does not
        close your schoolz account.
      </p>

      <h3>Children's data</h3>
      <p>
        This extension is built for parents and guardians to use on their own device, reading their own or
        their child's school-portal pages that they are already signed into, and for a college student
        reading their own Canvas. It does not collect
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
        <li>
          A Canvas file sent to billz is kept in your billz account, where you can disconnect the extension
          (Schoolwork → Canvas); the copy in your downloads is yours to delete.
        </li>
        <li>
          Uninstalling Backpack Capture deletes all locally stored captures, any saved schoolz login and the
          billz key, and gives back every site you allowed.
        </li>
      </ul>

      <h3>Changes to this policy</h3>
      <p>
        If what this extension reads, stores, or sends ever changes, this page will be updated to match,
        and the effective date above will change with it.
      </p>

      <h3>Contact</h3>
      <p>
        Backpack Capture is available from the{" "}
        <a href={STORE_URL} target="_blank" rel="noopener noreferrer">
          Chrome Web Store
        </a>
        . Questions, concerns, or reports about this policy can be
        sent to <a href="mailto:enr@profitnaut.com">enr@profitnaut.com</a>.
      </p>
      <p className="note">
        Backpack Capture reads Google Classroom, Genesis Parent Portal and Canvas locally in your browser.
        It is not affiliated with, endorsed by, or a product of Google, Genesis, Instructure (Canvas), or any
        school or school district.
      </p>
    </>
  );
}
