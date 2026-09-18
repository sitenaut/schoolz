/** The reward for an empty dashboard.
 *
 * A feed never ends, so it never lets you finish. This screen is the
 * finish line: it only appears when nothing is missing and nothing is due
 * in the horizon, and it is meant to feel earned - big, warm, and with
 * nothing else on the page competing with it. */
export function InboxZero({ finished }: { finished: number }) {
  return (
    <section className="inbox-zero" aria-live="polite">
      <svg viewBox="0 0 200 140" aria-hidden="true" className="inbox-zero-art">
        <ellipse cx="100" cy="118" rx="70" ry="10" className="shadow" />
        <path
          className="body"
          d="M40 100c0-26 22-44 52-44 22 0 38 8 48 20 6-10 14-16 26-16v18c-8 0-14 6-18 14 4 14-8 24-26 24H62c-14 0-22-6-22-16z"
        />
        <circle className="body" cx="60" cy="72" r="20" />
        <path className="ear" d="M46 60 42 42l16 10zM74 60l4-18-16 10z" />
        <path className="face" d="M52 74q4 4 8 0M62 74q4 4 8 0M56 80q4 3 8 0" fill="none" />
        <path className="tail" d="M140 108c14 0 20-10 14-18" fill="none" />
        <text x="118" y="46" className="zzz">z</text>
        <text x="132" y="34" className="zzz mid">z</text>
        <text x="148" y="20" className="zzz big">z</text>
      </svg>
      <h2>You're done for the day!</h2>
      <p>
        {finished > 0
          ? `${finished} ${finished === 1 ? "task" : "tasks"} finished. Nothing else is due today or tomorrow.`
          : "Nothing is due today or tomorrow."}
      </p>
    </section>
  );
}
