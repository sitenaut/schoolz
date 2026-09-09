/** Plain privacy/cookies notice, linked from the persistent footer on every
 * page (AppShell). No consent popup by design: everything schoolz stores
 * today (localStorage school picks, Supabase Auth's own session storage,
 * an optional Gmail token) is "strictly necessary" under GDPR/ePrivacy, so
 * there's nothing to ask permission for yet. If that changes (analytics,
 * ads), this page and a real consent banner both need revisiting. */
export function PrivacyPage() {
  return (
    <>
      <h2>Privacy &amp; cookies</h2>
      <p className="note">Last updated September 2026.</p>

      <p>
        schoolz ("we", "us") helps parents and guardians in the Cherry Hill, NJ school
        district keep up with their kids' schools. This page explains what data the
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
            <td>Account info (email, username), your linked children, guardian invites</td>
            <td>Our database</td>
            <td>
              Powers the optional personal layer described above. A linked child's record
              is shared only with guardians you or an auto-match connects it to — never
              made public.
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
        <li>No analytics, advertising, or tracking cookies of any kind.</li>
        <li>No selling or sharing your data with advertisers or data brokers.</li>
        <li>No cross-site tracking — nothing here follows you to other websites.</li>
      </ul>

      <h3>Why there's no "accept cookies" popup</h3>
      <p>
        Under GDPR and the ePrivacy Directive, a consent banner is required for
        non-essential tracking (like analytics or ad cookies) — not for things a site
        needs to function, like remembering your school picks or keeping you logged in.
        Everything schoolz currently stores falls into that "strictly necessary" /
        functional category, so there's nothing here that requires your opt-in consent.
        If that ever changes, this notice (and a real consent choice) will change with it.
      </p>

      <h3>Third parties involved</h3>
      <ul>
        <li>
          <strong>Supabase</strong> — handles login/authentication for registered users.
        </li>
        <li>
          <strong>Fly.io</strong> — hosts the website and backend.
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
