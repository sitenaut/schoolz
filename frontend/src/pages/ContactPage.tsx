import { useState } from "react";
import { Link } from "react-router-dom";
import { apiFetch } from "../api";
import { IconLink, IconNewsletter, IconUpload } from "../components/icons";
import { Field } from "../components/ui/Field";
import { SectionCard } from "../components/ui/SectionCard";
import { SeoHead } from "../components/SeoHead";
import { useAuth } from "../context/AuthContext";
import { usePrerenderReady } from "../lib/prerenderReady";

/** A plain message to the people who run schoolz. It lands in the admins'
 * shared inbox (/admin/inbox); nothing is emailed or published. */
export function ContactPage() {
  const { user } = useAuth();
  const [name, setName] = useState("");
  const [email, setEmail] = useState(user?.email ?? "");
  const [message, setMessage] = useState("");
  const [website, setWebsite] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  usePrerenderReady(true);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await apiFetch("/contact-messages", {
        method: "POST",
        body: JSON.stringify({ name: name.trim() || null, email: email.trim() || null, message: message.trim(), website: website || null }),
      });
      if (!r.ok) throw new Error("Could not send this - please try again");
      setDone(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not send this - please try again");
    } finally {
      setBusy(false);
    }
  };

  if (done) {
    return (
      <div className="card" style={{ maxWidth: 560, margin: "40px auto", textAlign: "center" }}>
        <h2>Thanks - message sent</h2>
        <p>A real person reads every one.{email.trim() ? " If it needs a reply, it'll come to the email you gave." : ""}</p>
        <button
          className="btn"
          onClick={() => {
            setDone(false);
            setMessage("");
          }}
        >
          Send another
        </button>
      </div>
    );
  }

  return (
    <div style={{ maxWidth: 560, margin: "0 auto" }}>
      <SeoHead title="Contact · schoolz" description="Questions, corrections, or ideas for schoolz - a real person reads every message." path="/contact" />
      <h2>Contact</h2>
      <p className="note">
        Questions, something that looks wrong, or an idea - send it here and a real person will read it.
      </p>

      <form onSubmit={submit}>
        {error && <div className="form-error">{error}</div>}

        <Field label="Message">
          <textarea value={message} onChange={(e) => setMessage(e.target.value)} rows={6} maxLength={5000} required />
        </Field>

        <div className="fgrid two">
          <Field label="Your name" hint="Optional">
            <input value={name} onChange={(e) => setName(e.target.value)} maxLength={200} autoComplete="name" />
          </Field>
          <Field label="Your email" hint="Optional - only if you'd like a reply">
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} maxLength={255} autoComplete="email" />
          </Field>
        </div>

        {/* Honeypot for form-spam bots: invisible and unreachable for people. */}
        <div aria-hidden="true" style={{ position: "absolute", left: "-10000px", width: 1, height: 1, overflow: "hidden" }}>
          <label>
            Website
            <input tabIndex={-1} autoComplete="off" value={website} onChange={(e) => setWebsite(e.target.value)} />
          </label>
        </div>

        <button className="btn btn-primary" type="submit" disabled={busy || !message.trim()} style={{ marginTop: 8 }}>
          {busy ? "Sending…" : "Send message"}
        </button>
      </form>

      <div style={{ marginTop: 32 }}>
        <SectionCard
          title="Send a flier, newsletter, or document"
          description="A school newsletter link, a flier, a handbook, a lunch menu - anything we're not tracking yet. A real person checks it before it goes on the site."
          icon={<IconNewsletter />}
        >
          <div className="link-grid">
            <Link className="link-card" to="/contact/submit">
              <span className="ico">
                <IconLink />
              </span>
              <span>
                <b>I have a link</b>
                <small>A newsletter page, an online flier, a PDF</small>
              </span>
            </Link>
            <Link className="link-card" to="/contact/submit?kind=file">
              <span className="ico">
                <IconUpload />
              </span>
              <span>
                <b>I have a file</b>
                <small>A photo or PDF of a flier, up to 15MB</small>
              </span>
            </Link>
          </div>
        </SectionCard>
      </div>
    </div>
  );
}
