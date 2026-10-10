import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { BOT_CHECK_ENABLED, BotCheck } from "../components/BotCheck";
import { Field } from "../components/ui/Field";
import { SeoHead } from "../components/SeoHead";
import { usePrerenderReady } from "../lib/prerenderReady";
import { loadTargets, submitContent, type TargetOption } from "./submissions/submissionsApi";

type Kind = "link" | "file";

const MAX_FILE_BYTES = 15 * 1024 * 1024;

/** Anyone can send us a flyer or newsletter without an account - pick the
 * file, optionally say who you are, send. It lands in the admin submissions
 * inbox as "pending"; nothing an anonymous visitor sends is published
 * without a person choosing it.
 *
 * It is also the one place a stranger can put a file on the server, so a
 * file upload carries a bot check (components/BotCheck.tsx) and the backend
 * records where every attempt came from. The page says so. */
export function UploadPage() {
  const [params] = useSearchParams();
  const [kind, setKind] = useState<Kind>(params.get("kind") === "link" ? "link" : "file");
  const [url, setUrl] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [description, setDescription] = useState("");
  const [submitterName, setSubmitterName] = useState("");
  const [submitterEmail, setSubmitterEmail] = useState("");
  const [website, setWebsite] = useState("");
  const [targetKind, setTargetKind] = useState<"unsure" | "school" | "district" | "local">("unsure");
  const [schoolId, setSchoolId] = useState("");
  const [districtId, setDistrictId] = useState("");
  const [targets, setTargets] = useState<{ schools: TargetOption[]; districts: TargetOption[] }>({
    schools: [],
    districts: [],
  });
  const [botToken, setBotToken] = useState<string | null>(null);
  const [botCheckDown, setBotCheckDown] = useState(false);
  const [botCheckRound, setBotCheckRound] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  useEffect(() => {
    loadTargets().then(setTargets).catch(() => undefined);
  }, []);

  usePrerenderReady(true);
  const needsBotCheck = BOT_CHECK_ENABLED && kind === "file";
  const tooBig = Boolean(file && file.size > MAX_FILE_BYTES);
  const canSubmit = kind === "link" ? url.trim().length > 0 : Boolean(file) && !tooBig && (!needsBotCheck || Boolean(botToken));

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await submitContent({
        url: kind === "link" ? url.trim() : undefined,
        file: kind === "file" ? file ?? undefined : undefined,
        // There's no field for it: the reviewer sees this in the sender's note
        // and still decides where the items go.
        description: (targetKind === "local" ? `[Local event] ${description.trim()}` : description.trim()).trim().slice(0, 2000) || undefined,
        submitter_name: submitterName.trim() || undefined,
        submitter_email: submitterEmail.trim() || undefined,
        school_id: targetKind === "school" ? schoolId || undefined : undefined,
        district_id: targetKind === "district" ? districtId || undefined : undefined,
        bot_token: needsBotCheck ? botToken ?? undefined : undefined,
        website: website || undefined,
      });
      setDone(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not submit this - please try again");
      // The token was spent on that try, whatever the outcome.
      setBotCheckRound((n) => n + 1);
    } finally {
      setBusy(false);
    }
  };

  if (done) {
    return (
      <div className="card" style={{ maxWidth: 560, margin: "40px auto", textAlign: "center" }}>
        <h2>Thanks!</h2>
        <p>
          We've got it. Someone on our end will take a look and add it if it checks out - we don't publish anything
          submitted this way automatically.
        </p>
        <button
          className="btn"
          onClick={() => {
            setDone(false);
            setUrl("");
            setFile(null);
            setDescription("");
            setBotToken(null);
          }}
        >
          Send another
        </button>
      </div>
    );
  }

  return (
    <div style={{ maxWidth: 560, margin: "0 auto" }}>
      <SeoHead
        title="Upload a newsletter or flyer · schoolz"
        description="Upload a school newsletter, a flyer from the backpack or a local event flyer - a real person reviews every one before it goes on the site."
        path="/upload"
      />
      <h2>Upload a newsletter or flyer</h2>
      <p className="note">
        A photo of a flyer from the backpack, a newsletter PDF, a town event poster - send it here. A real person reviews
        every one before anything is added to the site.
      </p>

      <form onSubmit={submit}>
        {error && <div className="form-error">{error}</div>}

        {kind === "file" ? (
          <Field label="Your file" hint="A photo or PDF, up to 15MB. On a phone you can take the picture right now.">
            <input
              className="upload-pick"
              type="file"
              accept="image/*,application/pdf"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              required
            />
          </Field>
        ) : (
          <Field label="Link" hint="A newsletter page, a flyer hosted online, a PDF - whatever you've got.">
            <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://..." type="url" required />
          </Field>
        )}
        {tooBig && <div className="form-error">That file is over 15MB - try a smaller photo or a PDF.</div>}
        <p className="note" style={{ marginTop: -4 }}>
          <button type="button" className="linklike" onClick={() => setKind(kind === "file" ? "link" : "file")}>
            {kind === "file" ? "Have a link instead?" : "Upload a file instead"}
          </button>
        </p>

        <div className="fgrid two">
          <Field label="Your name" hint="Optional">
            <input value={submitterName} onChange={(e) => setSubmitterName(e.target.value)} maxLength={200} autoComplete="name" />
          </Field>
          <Field label="Your email" hint="Optional - only if we need to ask a follow-up question">
            <input
              type="email"
              value={submitterEmail}
              onChange={(e) => setSubmitterEmail(e.target.value)}
              maxLength={255}
              autoComplete="email"
            />
          </Field>
        </div>

        <details className="upload-more">
          <summary>Add a note or say which school it's for (optional)</summary>
          <Field label="Anything we should know?" hint="e.g. 'the lunch menu dates' or 'this week's PTA events'.">
            <textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={3} maxLength={2000} />
          </Field>

          <Field label="What is this about?">
            <select
              value={targetKind}
              onChange={(e) => setTargetKind(e.target.value as typeof targetKind)}
              style={{ marginBottom: 8 }}
            >
              <option value="unsure">Not sure / other</option>
              <option value="school">A school</option>
              <option value="district">The whole district</option>
              <option value="local">A local event (not a school)</option>
            </select>
            {targetKind === "school" && (
              <select value={schoolId} onChange={(e) => setSchoolId(e.target.value)}>
                <option value="">— choose —</option>
                {targets.schools.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.label}
                  </option>
                ))}
              </select>
            )}
            {targetKind === "district" && (
              <select value={districtId} onChange={(e) => setDistrictId(e.target.value)}>
                <option value="">— choose —</option>
                {targets.districts.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.label}
                  </option>
                ))}
              </select>
            )}
          </Field>
        </details>

        {/* Honeypot for form-spam bots: invisible and unreachable for people. */}
        <div aria-hidden="true" style={{ position: "absolute", left: "-10000px", width: 1, height: 1, overflow: "hidden" }}>
          <label>
            Website
            <input tabIndex={-1} autoComplete="off" value={website} onChange={(e) => setWebsite(e.target.value)} />
          </label>
        </div>

        {needsBotCheck && (
          <BotCheck onToken={setBotToken} onUnavailable={() => setBotCheckDown(true)} resetKey={botCheckRound} />
        )}
        {needsBotCheck && botCheckDown && !botToken && (
          <div className="form-error">
            The "are you a person" check couldn't load - an ad or tracker blocker may be stopping it. Allow
            challenges.cloudflare.com for this page and reload.
          </div>
        )}

        <button className="btn btn-primary" type="submit" disabled={busy || !canSubmit} style={{ marginTop: 8 }}>
          {busy ? "Sending…" : kind === "file" ? "Upload" : "Send link"}
        </button>

        <p className="note upload-notice">
          To keep this safe for families, every upload is checked by a person and we record the IP address and browser
          it came from. Illegal content is reported to the authorities along with that record.{" "}
          <Link to="/privacy">Privacy</Link>
        </p>
      </form>
    </div>
  );
}
