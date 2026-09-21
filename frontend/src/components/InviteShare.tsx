import { useState } from "react";

/** The "now get this link to them" step of both invite flows. Local mode has
 * no mailer and prod deliberately doesn't send on the guardian's behalf, so
 * the guardian sends it themselves - this just removes every excuse: the
 * phone's share sheet, a one-tap copy, or their own mail app pre-filled. */
export function InviteShare({ link, email, subject, body }: { link: string; email: string; subject: string; body: string }) {
  const [copied, setCopied] = useState(false);
  const canShare = typeof navigator !== "undefined" && typeof navigator.share === "function";

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(link);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Selecting the field is the fallback - the input below is readOnly and selects on focus.
    }
  };

  const share = () => navigator.share({ title: subject, text: body, url: link }).catch(() => undefined);

  const mailto = `mailto:${encodeURIComponent(email)}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(`${body}\n\n${link}`)}`;

  return (
    <div>
      <input readOnly value={link} onFocus={(e) => e.target.select()} style={{ width: "100%" }} aria-label="Invite link" />
      <div className="actions bare" style={{ flexWrap: "wrap", marginTop: 8 }}>
        {canShare && (
          <button type="button" className="btn btn-primary" onClick={share}>
            Share
          </button>
        )}
        <button type="button" className={`btn ${canShare ? "" : "btn-primary"}`} onClick={copy}>
          {copied ? "Copied" : "Copy link"}
        </button>
        <a className="btn" href={mailto}>
          Email it
        </a>
      </div>
      <p className="note" style={{ marginBottom: 0 }}>
        They open the link, sign in with Google or make an account, and it finishes on its own. Valid for 7 days.
      </p>
    </div>
  );
}
