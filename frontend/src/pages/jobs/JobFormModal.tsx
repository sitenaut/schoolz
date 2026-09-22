import { useEffect, useMemo, useState } from "react";
import { Field } from "../../components/ui/Field";
import { Modal } from "../../components/ui/Modal";
import { Switch } from "../../components/ui/Switch";
import { CRON_PRESETS, describeCron } from "../../lib/cron";
import type { JobKind, ScheduledJob, TestFetchResult } from "../../types";
import { TARGET_LABELS, createJob, testFetchJob, updateJob, type JobPayload } from "./jobsApi";
import { JsonParamsEditor, ParamsHelp, TEST_FETCH_KINDS, TestFetchResults, needsJsonParams } from "./JsonParamsEditor";

const TIMEZONES = ["America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles", "UTC"];

type Props = {
  open: boolean;
  onClose: () => void;
  onSaved: (job: ScheduledJob) => void;
  kinds: JobKind[];
  targets: Record<string, { id: string; label: string }[]>;
  /** Editing an existing job; omitted = creating. */
  job?: ScheduledJob | null;
};

export function JobFormModal({ open, onClose, onSaved, kinds, targets, job }: Props) {
  const editing = Boolean(job);
  const [kind, setKind] = useState(job?.kind ?? kinds[0]?.kind ?? "");
  const [name, setName] = useState(job?.name ?? "");
  const [nameTouched, setNameTouched] = useState(editing);
  const [description, setDescription] = useState(job?.description ?? "");
  const [cron, setCron] = useState(job?.cron_expr ?? "0 */12 * * *");
  const [timezone, setTimezone] = useState(job?.timezone ?? "America/New_York");
  const [enabled, setEnabled] = useState(job?.enabled ?? true);
  const [params, setParams] = useState<Record<string, string>>(
    Object.fromEntries(Object.entries(job?.params ?? {}).map(([k, v]) => [k, String(v ?? "")]))
  );
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [paramsText, setParamsText] = useState("");
  const [testResult, setTestResult] = useState<TestFetchResult | null>(null);
  const [testing, setTesting] = useState(false);
  const [testVerbose, setTestVerbose] = useState(false);

  const spec = useMemo(() => kinds.find((k) => k.kind === kind) ?? null, [kinds, kind]);
  const jsonMode = needsJsonParams(spec);
  const canTestFetch = TEST_FETCH_KINDS.has(kind);
  const paramKeys = useMemo(() => {
    const props = Object.keys(spec?.param_schema?.properties ?? {});
    const required = spec?.param_schema?.required ?? [];
    return [...required, ...props.filter((p) => !required.includes(p))];
  }, [spec]);

  // Reset when the modal is (re)opened for a different job.
  useEffect(() => {
    if (!open) return;
    setKind(job?.kind ?? kinds[0]?.kind ?? "");
    setName(job?.name ?? "");
    setNameTouched(Boolean(job));
    setDescription(job?.description ?? "");
    setCron(job?.cron_expr ?? kinds[0]?.default_cron ?? "0 */12 * * *");
    setTimezone(job?.timezone ?? "America/New_York");
    setEnabled(job?.enabled ?? true);
    setParams(Object.fromEntries(Object.entries(job?.params ?? {}).map(([k, v]) => [k, String(v ?? "")])));
    setParamsText(job ? JSON.stringify(job.params ?? {}, null, 2) : "");
    setTestResult(null);
    setError(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, job?.id]);

  // Creating: a new kind resets the schedule to that kind's default and,
  // until the name is hand-edited, keeps it auto-derived from kind+target.
  useEffect(() => {
    if (editing || !spec) return;
    setCron(spec.default_cron);
    setTimezone(spec.default_timezone);
    setParamsText(needsJsonParams(spec) ? JSON.stringify(spec.default_params ?? {}, null, 2) : "");
    setTestResult(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind, editing]);

  useEffect(() => {
    if (nameTouched || !spec) return;
    const targetKey = paramKeys.find((k) => targets[k]);
    const targetLabel = targetKey ? targets[targetKey]?.find((t) => t.id === params[targetKey])?.label : null;
    setName(targetLabel ? `${spec.default_name}: ${targetLabel}` : spec.default_name);
  }, [spec, params, paramKeys, targets, nameTouched]);

  const presetMatch = CRON_PRESETS.find((p) => p.expr === cron)?.expr ?? "custom";

  const parseParamsText = (): Record<string, unknown> | null => {
    try {
      return paramsText.trim() ? JSON.parse(paramsText) : {};
    } catch (e) {
      setError(`Params must be valid JSON: ${e instanceof Error ? e.message : String(e)}`);
      return null;
    }
  };

  const runTestFetch = async () => {
    const parsed = parseParamsText();
    if (parsed === null) return;
    setError(null);
    setTestResult(null);
    setTesting(true);
    try {
      setTestResult(await testFetchJob(kind, parsed, testVerbose));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Test fetch failed");
    } finally {
      setTesting(false);
    }
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const jsonParams = jsonMode ? parseParamsText() : null;
    if (jsonMode && jsonParams === null) return;
    setBusy(true);
    setError(null);
    const payload: JobPayload = {
      kind,
      name: name.trim(),
      description: description.trim() || null,
      cron_expr: cron.trim(),
      timezone,
      params: jsonParams ?? Object.fromEntries(Object.entries(params).filter(([, v]) => v !== "")),
      enabled,
    };
    try {
      const saved = job ? await updateJob(job.id, payload) : await createJob(payload);
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
      title={editing ? "Edit job" : "New scheduled job"}
      subtitle={editing ? <span className="code-chip">{job!.kind}</span> : "Pick what to scan, what it targets, and how often."}
      footer={
        <>
          {canTestFetch && (
            <div className="test-fetch-ctl">
              <button className="btn" type="button" onClick={runTestFetch} disabled={testing || busy}>
                {testing ? "Testing…" : "Test fetch"}
              </button>
              <label className="filterCheck">
                <input type="checkbox" checked={testVerbose} onChange={(e) => setTestVerbose(e.target.checked)} />
                Verbose
              </label>
            </div>
          )}
          <button className="btn" type="button" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button className="btn btn-primary" type="submit" form="job-form" disabled={busy || !kind || !name.trim()}>
            {busy ? "Saving…" : editing ? "Save changes" : "Create job"}
          </button>
        </>
      }
    >
      <form id="job-form" onSubmit={submit}>
        {error && <div className="form-error">{error}</div>}

        <div className="fgrid two">
          <Field label="Kind" hint={spec?.description} className="span2">
            <select value={kind} onChange={(e) => setKind(e.target.value)} disabled={editing} required>
              {kinds.map((k) => (
                <option key={k.kind} value={k.kind}>
                  {k.default_name} · {k.kind}
                </option>
              ))}
            </select>
          </Field>

          {jsonMode && (
            <Field label="Params (JSON)" className="span2">
              <ParamsHelp kind={spec} onInsertDefaults={(p) => setParamsText(JSON.stringify(p, null, 2))} />
              <JsonParamsEditor value={paramsText} onChange={setParamsText} />
            </Field>
          )}

          {!jsonMode && paramKeys.map((key) => {
            const options = targets[key];
            const required = spec?.param_schema?.required?.includes(key);
            return (
              <Field key={key} label={`${TARGET_LABELS[key] ?? key}${required ? "" : " (optional)"}`} className={paramKeys.length === 1 ? "span2" : ""}>
                {options ? (
                  <select value={params[key] ?? ""} onChange={(e) => setParams((p) => ({ ...p, [key]: e.target.value }))} required={required}>
                    <option value="">— choose —</option>
                    {options.map((o) => (
                      <option key={o.id} value={o.id}>
                        {o.label}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input value={params[key] ?? ""} onChange={(e) => setParams((p) => ({ ...p, [key]: e.target.value }))} required={required} />
                )}
              </Field>
            );
          })}

          <Field label="Name" className="span2">
            <input
              value={name}
              onChange={(e) => {
                setName(e.target.value);
                setNameTouched(true);
              }}
              required
              maxLength={200}
            />
          </Field>

          <Field label="Description" hint="Optional - shown in the jobs table." className="span2">
            <input value={description} onChange={(e) => setDescription(e.target.value)} maxLength={500} />
          </Field>

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
              {[...new Set([timezone, ...TIMEZONES])].map((tz) => (
                <option key={tz} value={tz}>
                  {tz}
                </option>
              ))}
            </select>
          </Field>

          <Field label="Cron expression" hint={`${describeCron(cron)} · minute hour day month weekday`} className="span2">
            <input value={cron} onChange={(e) => setCron(e.target.value)} required style={{ fontFamily: "ui-monospace, Menlo, monospace" }} />
          </Field>
        </div>

        <div className="sw-row">
          <div>
            <b>Enabled</b>
            <small>Disabled jobs stay listed but never run on schedule. You can still run them manually.</small>
          </div>
          <Switch checked={enabled} onChange={setEnabled} label="Enabled" />
        </div>

        {canTestFetch && testResult && <TestFetchResults result={testResult} />}
      </form>
    </Modal>
  );
}
