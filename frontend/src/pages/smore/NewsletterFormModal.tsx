import { useEffect, useState } from "react";
import { Field } from "../../components/ui/Field";
import { Modal } from "../../components/ui/Modal";
import { Switch } from "../../components/ui/Switch";
import { CRON_PRESETS, describeCron } from "../../lib/cron";
import type { SmoreNewsletter } from "../../types";
import { createNewsletter, updateNewsletter, type NewsletterPayload, type TargetOption } from "./smoreApi";

type Target = "school" | "district" | "none";

type Props = {
  open: boolean;
  onClose: () => void;
  onSaved: (n: SmoreNewsletter) => void;
  targets: { schools: TargetOption[]; districts: TargetOption[] };
  newsletter?: SmoreNewsletter | null;
};

function initialTarget(n?: SmoreNewsletter | null): Target {
  if (n?.district_id) return "district";
  if (n?.school_id) return "school";
  return "school";
}

export function NewsletterFormModal({ open, onClose, onSaved, targets, newsletter }: Props) {
  const editing = Boolean(newsletter);
  const [url, setUrl] = useState(newsletter?.url ?? "");
  const [label, setLabel] = useState(newsletter?.label ?? "");
  const [target, setTarget] = useState<Target>(initialTarget(newsletter));
  const [schoolId, setSchoolId] = useState(newsletter?.school_id ?? "");
  const [districtId, setDistrictId] = useState(newsletter?.district_id ?? "");
  const [cron, setCron] = useState(newsletter?.scheduled_job?.cron_expr ?? "0 8 * * 1");
  const [timezone, setTimezone] = useState(newsletter?.scheduled_job?.timezone ?? "America/New_York");
  // Editing a newsletter with no job yet (auto-discovered, never
  // scheduled) should reflect that it's actually off right now - only a
  // brand-new newsletter defaults to on.
  const [enabled, setEnabled] = useState(newsletter ? Boolean(newsletter.scheduled_job?.enabled) : true);
  const [runOnce, setRunOnce] = useState(newsletter ? Boolean(newsletter.scheduled_job?.run_once) : false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setUrl(newsletter?.url ?? "");
    setLabel(newsletter?.label ?? "");
    setTarget(initialTarget(newsletter));
    setSchoolId(newsletter?.school_id ?? "");
    setDistrictId(newsletter?.district_id ?? "");
    setCron(newsletter?.scheduled_job?.cron_expr ?? "0 8 * * 1");
    setTimezone(newsletter?.scheduled_job?.timezone ?? "America/New_York");
    setEnabled(newsletter ? Boolean(newsletter.scheduled_job?.enabled) : true);
    setRunOnce(newsletter ? Boolean(newsletter.scheduled_job?.run_once) : false);
    setError(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, newsletter?.id]);

  const presetMatch = CRON_PRESETS.find((p) => p.expr === cron)?.expr ?? "custom";
  const canSubmit = url.trim().length > 0 && (target !== "school" || schoolId) && (target !== "district" || districtId);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const payload: NewsletterPayload = {
      url: url.trim(),
      label: label.trim() || null,
      school_id: target === "school" ? schoolId : null,
      district_id: target === "district" ? districtId : null,
      cron_expr: cron.trim(),
      timezone,
      enabled,
      run_once: runOnce,
    };
    try {
      const saved = editing ? await updateNewsletter(newsletter!.id, payload) : await createNewsletter(payload);
      onSaved(saved);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      size="lg"
      title={editing ? "Edit newsletter" : "Track a newsletter"}
      subtitle={editing ? undefined : "A hosted newsletter page (Smore or similar) to scan on a recurring schedule."}
      footer={
        <>
          <button className="btn" type="button" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button className="btn btn-primary" type="submit" form="newsletter-form" disabled={busy || !canSubmit}>
            {busy ? "Saving…" : editing ? "Save changes" : "Add newsletter"}
          </button>
        </>
      }
    >
      <form id="newsletter-form" onSubmit={submit}>
        {error && <div className="form-error">{error}</div>}

        <div className="fgrid two">
          <Field label="Smore URL" className="span2" hint="The newsletter's own page - not an author profile page (those list many issues; find the current one's own /n/ URL).">
            <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://app.smore.com/n/..." required />
          </Field>

          <Field label="Label" hint="Optional - shown instead of the raw URL.">
            <input value={label} onChange={(e) => setLabel(e.target.value)} maxLength={255} placeholder="Bret Harte Weekly" />
          </Field>

          <Field label="Belongs to">
            <select value={target} onChange={(e) => setTarget(e.target.value as Target)}>
              <option value="school">A school</option>
              <option value="district">A whole district</option>
            </select>
          </Field>

          {target === "school" ? (
            <Field label="School" className="span2">
              <select value={schoolId} onChange={(e) => setSchoolId(e.target.value)} required>
                <option value="">— choose —</option>
                {targets.schools.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.label}
                  </option>
                ))}
              </select>
            </Field>
          ) : (
            <Field label="District" className="span2" hint="Items extracted from this newsletter will be district-wide, not tied to one school.">
              <select value={districtId} onChange={(e) => setDistrictId(e.target.value)} required>
                <option value="">— choose —</option>
                {targets.districts.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.label}
                  </option>
                ))}
              </select>
            </Field>
          )}

          {!runOnce && (
            <>
              <Field label="Schedule">
                <select
                  value={presetMatch}
                  onChange={(e) => {
                    if (e.target.value !== "custom") setCron(e.target.value);
                  }}
                >
                  {CRON_PRESETS.map((p) => (
                    <option key={p.expr} value={p.expr}>
                      {p.label}
                    </option>
                  ))}
                  <option value="custom">Custom…</option>
                </select>
              </Field>
              <Field label="Timezone">
                <select value={timezone} onChange={(e) => setTimezone(e.target.value)}>
                  {["America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles", "UTC"]
                    .filter((tz, i, arr) => arr.indexOf(tz) === i)
                    .map((tz) => (
                      <option key={tz} value={tz}>
                        {tz}
                      </option>
                    ))}
                </select>
              </Field>
              <Field label="Cron expression" hint={describeCron(cron)} className="span2">
                <input value={cron} onChange={(e) => setCron(e.target.value)} required style={{ fontFamily: "ui-monospace, Menlo, monospace" }} />
              </Field>
            </>
          )}
        </div>

        <div className="sw-row">
          <div>
            <b>Run once</b>
            <small>
              Scan this URL a single time, then turn scanning off - for a newsletter that publishes a brand new URL
              every issue (Beck, Cooper, Clara Barton, and most others turn out to work this way) rather than
              updating one stable page. {editing ? "Saving" : "Adding"} with this on runs the scan immediately.
            </small>
          </div>
          <Switch checked={runOnce} onChange={setRunOnce} label="Run once" />
        </div>

        {!runOnce && (
          <div className="sw-row">
            <div>
              <b>Enabled</b>
              <small>Scans on schedule. Leave off to track the URL without scheduling a scan yet.</small>
            </div>
            <Switch checked={enabled} onChange={setEnabled} label="Enabled" />
          </div>
        )}
      </form>
    </Modal>
  );
}
