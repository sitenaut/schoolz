import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Field } from "../components/ui/Field";
import { SeoHead } from "../components/SeoHead";
import { usePrerenderReady } from "../lib/prerenderReady";
import { loadTargets, submitContent, type TargetOption } from "./submissions/submissionsApi";

type Kind = "link" | "file";

/** Anyone can point us at a flier or newsletter link without becoming an
 * admin - it lands in the admin submissions inbox as "pending" for a human
 * to look at and, if it's real and useful, add by hand to the tracked
 * sources. Deliberately no auto-processing: the user's own framing was
 * "so I can curate and validate the extractions" before anything an
 * anonymous visitor sends feeds the shared/public content pipeline. */
export function SubmitSourcePage() {
  const [params] = useSearchParams();
  const [kind, setKind] = useState<Kind>(params.get("kind") === "file" ? "file" : "link");
  const [url, setUrl] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [description, setDescription] = useState("");
  const [submitterName, setSubmitterName] = useState("");
  const [submitterEmail, setSubmitterEmail] = useState("");
  const [targetKind, setTargetKind] = useState<"unsure" | "school" | "district">("unsure");
  const [schoolId, setSchoolId] = useState("");
  const [districtId, setDistrictId] = useState("");
  const [targets, setTargets] = useState<{ schools: TargetOption[]; districts: TargetOption[] }>({
    schools: [],
    districts: [],
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  useEffect(() => {
    loadTargets().then(setTargets).catch(() => undefined);
  }, []);

  usePrerenderReady(true);
  const canSubmit = kind === "link" ? url.trim().length > 0 : Boolean(file);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await submitContent({
        url: kind === "link" ? url.trim() : undefined,
        file: kind === "file" ? file ?? undefined : undefined,
        description: description.trim() || undefined,
        submitter_name: submitterName.trim() || undefined,
        submitter_email: submitterEmail.trim() || undefined,
        school_id: targetKind === "school" ? schoolId || undefined : undefined,
        district_id: targetKind === "district" ? districtId || undefined : undefined,
      });
      setDone(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not submit this - please try again");
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
          }}
        >
          Submit another
        </button>
      </div>
    );
  }

  return (
    <div style={{ maxWidth: 560, margin: "0 auto" }}>
      <SeoHead
        title="Send a flier or newsletter · schoolz"
        description="Send us a school flier or newsletter link we're not tracking yet - a real person reviews every submission."
        path="/contact/submit"
      />
      <h2>Send a flier or newsletter</h2>
      <p className="note">
        Spot a school flier or a newsletter link we're not tracking yet? Send it over - a real person reviews
        everything submitted here before it's added to the site.
      </p>

      <form onSubmit={submit}>
        {error && <div className="form-error">{error}</div>}

        <div className="tabs" role="tablist" style={{ marginBottom: 16 }}>
          <button type="button" className={`tab ${kind === "link" ? "active" : ""}`} onClick={() => setKind("link")}>
            I have a link
          </button>
          <button type="button" className={`tab ${kind === "file" ? "active" : ""}`} onClick={() => setKind("file")}>
            I have a file
          </button>
        </div>

        {kind === "link" ? (
          <Field label="Link" hint="A newsletter page, a flier hosted online, a PDF - whatever you've got.">
            <input
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://..."
              type="url"
              required
            />
          </Field>
        ) : (
          <Field label="File" hint="A photo or PDF of a flier, up to 15MB.">
            <input
              type="file"
              accept="image/*,application/pdf"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              required
            />
          </Field>
        )}

        <Field
          label="What are you hoping we pull out of this?"
          hint="Optional, but it helps - e.g. 'the lunch menu dates' or 'this week's PTA events'."
        >
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={3}
            maxLength={2000}
            placeholder="Optional"
          />
        </Field>

        <Field label="Which school or district is this about?">
          <select
            value={targetKind}
            onChange={(e) => setTargetKind(e.target.value as typeof targetKind)}
            style={{ marginBottom: 8 }}
          >
            <option value="unsure">Not sure / other</option>
            <option value="school">A school</option>
            <option value="district">The whole district</option>
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

        <div className="fgrid two">
          <Field label="Your name" hint="Optional">
            <input value={submitterName} onChange={(e) => setSubmitterName(e.target.value)} maxLength={200} />
          </Field>
          <Field label="Your email" hint="Optional - only if we need to ask a follow-up question">
            <input
              type="email"
              value={submitterEmail}
              onChange={(e) => setSubmitterEmail(e.target.value)}
              maxLength={255}
            />
          </Field>
        </div>

        <button className="btn btn-primary" type="submit" disabled={busy || !canSubmit} style={{ marginTop: 8 }}>
          {busy ? "Sending…" : "Send it over"}
        </button>
      </form>
    </div>
  );
}
