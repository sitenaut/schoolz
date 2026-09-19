import { useState } from "react";
import { apiFetch } from "../api";
import type { LatePolicy, LatePolicyParse } from "../types";

/** Teach schoolz what one class's syllabus says about late work.
 *
 * Two ways in, because the paragraph is the thing people actually have:
 * paste it and let the model propose a structured rule, or fill the shape
 * in by hand. The parse NEVER saves directly - it comes back as a proposal
 * shown next to the teacher's own sentence, and a person presses Save. A
 * misread late policy quietly changes what the dashboard tells a kid to
 * work on next (and can hide work entirely, since a closed window drops off
 * the Focus tab), so a wrong guess has to be caught by a human first.
 *
 * The shapes are a closed set covering what real syllabi say - see
 * models.py:CourseLatePolicy. */
const SHAPES: { value: LatePolicy["shape"]; label: string; hint: string }[] = [
  { value: "full_credit", label: "Accepted, full credit", hint: "Late work loses nothing." },
  { value: "flat", label: "One flat deduction", hint: "e.g. −10% however late it is." },
  { value: "daily_decay", label: "A bit off per day", hint: "e.g. −10% a day, never below 50%." },
  { value: "window", label: "Full credit for a few days", hint: "e.g. accepted within 3 days, nothing after." },
  { value: "tiered", label: "Set bands", hint: "e.g. 1 day 90%, 3 days 75%." },
  { value: "not_accepted", label: "Not accepted at all", hint: "No late work." },
];

export function LatePolicyEditor({
  courseKey,
  courseName,
  studentId,
  existing,
  onSave,
  onDelete,
  onClose,
}: {
  courseKey: string;
  courseName: string | null;
  studentId: string;
  existing: LatePolicy | null;
  onSave: (policy: Partial<LatePolicy> & { course_key: string }) => Promise<boolean>;
  onDelete: (courseKey: string) => Promise<void>;
  onClose: () => void;
}) {
  const [paste, setPaste] = useState("");
  const [parsing, setParsing] = useState(false);
  const [parsed, setParsed] = useState<LatePolicyParse | null>(null);
  const [form, setForm] = useState<Partial<LatePolicy>>(
    existing ?? { shape: "flat", extension_by_request: false },
  );
  const [saving, setSaving] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  const set = (patch: Partial<LatePolicy>) => setForm((f) => ({ ...f, ...patch }));

  const readParagraph = async () => {
    if (!paste.trim()) return;
    setParsing(true);
    setNote(null);
    const res = await apiFetch(`/students/${studentId}/bucket3/late-policies/parse`, {
      method: "POST",
      body: JSON.stringify({ text: paste }),
    });
    setParsing(false);
    if (!res.ok) {
      setNote("Couldn't read that just now — you can still fill it in below.");
      return;
    }
    const out = (await res.json()) as LatePolicyParse;
    setParsed(out);
    if (!out.understood) {
      setNote("That didn't say anything clear about late work — fill it in below instead.");
      return;
    }
    // The proposal populates the form rather than saving: what's shown is
    // what will be saved, and it sits next to the sentence it came from.
    setForm((f) => ({ ...f, ...out.policy, source_text: out.source_sentence ?? paste }));
  };

  const save = async () => {
    setSaving(true);
    const ok = await onSave({
      ...form,
      course_key: courseKey,
      course_name: courseName,
      shape: form.shape ?? "flat",
    } as Partial<LatePolicy> & { course_key: string });
    setSaving(false);
    if (ok) onClose();
    else setNote("Couldn't save that — check the numbers and try again.");
  };

  const shape = form.shape ?? "flat";

  return (
    <div className="policy-editor">
      <h4 className="policy-heading">Late work in {courseName ?? "this class"}</h4>

      <label className="policy-label" htmlFor="policy-paste">
        Paste what the syllabus says
      </label>
      <textarea
        id="policy-paste"
        className="policy-paste"
        rows={3}
        placeholder="Late work is accepted for three days with a 10% deduction per day…"
        value={paste}
        onChange={(e) => setPaste(e.target.value)}
      />
      <button type="button" className="policy-read" onClick={readParagraph} disabled={parsing || !paste.trim()}>
        {parsing ? "Reading…" : "Read it for me"}
      </button>

      {parsed?.understood && parsed.summary && (
        <div className="policy-proposal">
          <p className="policy-proposal-summary">{parsed.summary}</p>
          {parsed.source_sentence && <p className="policy-source">“{parsed.source_sentence}”</p>}
          <p className="policy-confirm">Check that against the handout, then save.</p>
        </div>
      )}

      <label className="policy-label" htmlFor="policy-shape">
        Rule
      </label>
      <select
        id="policy-shape"
        className="policy-select"
        value={shape}
        onChange={(e) => set({ shape: e.target.value as LatePolicy["shape"] })}
      >
        {SHAPES.map((s) => (
          <option key={s.value} value={s.value}>
            {s.label}
          </option>
        ))}
      </select>
      <p className="policy-hint">{SHAPES.find((s) => s.value === shape)?.hint}</p>

      {shape === "flat" && (
        <NumberField label="Percent taken off" value={form.penalty_pct} onChange={(v) => set({ penalty_pct: v })} />
      )}
      {shape === "daily_decay" && (
        <>
          <NumberField
            label="Percent off per day"
            value={form.penalty_per_day}
            onChange={(v) => set({ penalty_per_day: v })}
          />
          <NumberField label="Never below (%)" value={form.floor_pct} onChange={(v) => set({ floor_pct: v })} />
        </>
      )}
      {shape === "window" && (
        <NumberField label="Days still accepted" value={form.window_days} onChange={(v) => set({ window_days: v })} />
      )}
      {shape === "tiered" && (
        <p className="policy-hint">
          {form.steps?.length
            ? form.steps.map((s) => `within ${s.days}d → ${s.credit_pct}%`).join(", ")
            : "Paste the syllabus text above to fill in the bands."}
        </p>
      )}

      {shape !== "not_accepted" && (
        <label className="policy-check">
          <input
            type="checkbox"
            checked={form.accepted_until === "marking_period_end"}
            onChange={(e) => set({ accepted_until: e.target.checked ? "marking_period_end" : null })}
          />
          Only until the marking period ends
        </label>
      )}
      <label className="policy-check">
        <input
          type="checkbox"
          checked={Boolean(form.extension_by_request)}
          onChange={(e) => set({ extension_by_request: e.target.checked })}
        />
        An extension is possible if you ask
      </label>

      {note && <p className="policy-note">{note}</p>}

      <div className="policy-actions">
        <button type="button" className="policy-save" onClick={save} disabled={saving}>
          {saving ? "Saving…" : "Save"}
        </button>
        {existing && (
          <button type="button" className="policy-remove" onClick={() => void onDelete(courseKey).then(onClose)}>
            Remove
          </button>
        )}
        <button type="button" className="policy-cancel" onClick={onClose}>
          Cancel
        </button>
      </div>
    </div>
  );
}

function NumberField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number | null | undefined;
  onChange: (v: number | null) => void;
}) {
  return (
    <label className="policy-number">
      <span>{label}</span>
      <input
        type="number"
        min={0}
        max={100}
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
      />
    </label>
  );
}

/** One line of plain English for a saved rule, so the Details tab can show
 * what's on file without reopening the editor. */
export function describePolicy(p: LatePolicy): string {
  switch (p.shape) {
    case "full_credit":
      return "Late work accepted, full credit";
    case "flat":
      return `Late work −${p.penalty_pct ?? "?"}%`;
    case "daily_decay":
      return `−${p.penalty_per_day ?? "?"}% per day${p.floor_pct != null ? `, never below ${p.floor_pct}%` : ""}`;
    case "window":
      return `Accepted within ${p.window_days ?? "?"} days`;
    case "tiered":
      return (p.steps ?? []).map((s) => `${s.days}d → ${s.credit_pct}%`).join(", ") || "Set bands";
    case "not_accepted":
      return "Late work not accepted";
    default:
      return "Late work policy on file";
  }
}
