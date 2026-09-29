import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { apiFetch } from "../../api";
import { Field } from "../../components/ui/Field";
import { Modal } from "../../components/ui/Modal";
import { useToast } from "../../components/ui/Toast";
import type { BellPeriod, School } from "../../types";

type Props = {
  open: boolean;
  onClose: () => void;
  onSaved: (school: School) => void;
  school: School;
};

type Variant = "regular" | "delayed_opening" | "early_dismissal";
const VARIANTS: { key: Variant; label: string }[] = [
  { key: "regular", label: "Regular day" },
  { key: "delayed_opening", label: "Delayed opening" },
  { key: "early_dismissal", label: "Early dismissal" },
];

function emptyPeriods(): Record<Variant, BellPeriod[]> {
  return { regular: [], delayed_opening: [], early_dismissal: [] };
}

/** Admin-only editor for a school's day-level hours and, optionally, its
 * period-by-period bell schedule (drives the "what period is it right
 * now" chip on the Today card - services/bell_schedule.py). Both are
 * already fully supported by PATCH /schools/{id}; before this modal, the
 * only way to set either was a raw API call or a one-off migration. */
export function SchoolHoursModal({ open, onClose, onSaved, school }: Props) {
  const { t } = useTranslation();
  const toast = useToast();
  const [startTime, setStartTime] = useState("");
  const [endTime, setEndTime] = useState("");
  const [earlyDismissalTime, setEarlyDismissalTime] = useState("");
  const [delayedOpeningTime, setDelayedOpeningTime] = useState("");
  const [periods, setPeriods] = useState<Record<Variant, BellPeriod[]>>(emptyPeriods());
  const [activeVariant, setActiveVariant] = useState<Variant>("regular");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setStartTime(school.start_time ?? "");
    setEndTime(school.end_time ?? "");
    setEarlyDismissalTime(school.early_dismissal_time ?? "");
    setDelayedOpeningTime(school.delayed_opening_time ?? "");
    setPeriods({
      regular: school.bell_periods?.regular ?? [],
      delayed_opening: school.bell_periods?.delayed_opening ?? [],
      early_dismissal: school.bell_periods?.early_dismissal ?? [],
    });
    setActiveVariant("regular");
    setError(null);
  }, [open, school]);

  const rows = periods[activeVariant];
  const setRows = (next: BellPeriod[]) => setPeriods((p) => ({ ...p, [activeVariant]: next }));
  const updateRow = (i: number, patch: Partial<BellPeriod>) =>
    setRows(rows.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));
  const addRow = () => setRows([...rows, { name: "", start: "", end: "" }]);
  const removeRow = (i: number) => setRows(rows.filter((_, idx) => idx !== i));

  const allRows = [...periods.regular, ...periods.delayed_opening, ...periods.early_dismissal];
  const hasIncompleteRow = allRows.some((r) => !r.name.trim() || !r.start || !r.end);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const nonEmpty = Object.fromEntries(
      VARIANTS.map((v) => v.key).filter((key) => periods[key].length > 0).map((key) => [key, periods[key]]),
    );
    try {
      const res = await apiFetch(`/schools/${school.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          start_time: startTime.trim() || null,
          end_time: endTime.trim() || null,
          early_dismissal_time: earlyDismissalTime.trim() || null,
          delayed_opening_time: delayedOpeningTime.trim() || null,
          bell_periods: Object.keys(nonEmpty).length > 0 ? nonEmpty : null,
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(
          typeof body?.detail === "string"
            ? body.detail
            : Array.isArray(body?.detail)
              ? body.detail.map((d: { msg: string }) => d.msg).join("; ")
              : t("Could not save"),
        );
      }
      const saved: School = await res.json();
      onSaved(saved);
      toast({ title: t("Hours saved"), tone: "ok" });
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("Could not save"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      size="lg"
      title={t("Edit hours & bell schedule")}
      subtitle={school.short_name || school.name}
      footer={
        <>
          <button className="btn" type="button" onClick={onClose} disabled={busy}>
            {t("Cancel")}
          </button>
          <button className="btn btn-primary" type="submit" form="school-hours-form" disabled={busy || hasIncompleteRow}>
            {busy ? t("Saving…") : t("Save changes")}
          </button>
        </>
      }
    >
      <form id="school-hours-form" onSubmit={submit}>
        {error && <div className="form-error">{error}</div>}

        <div className="fgrid two">
          <Field label={t("Start time")} hint={t("Free text, e.g. 8:00 AM")}>
            <input value={startTime} onChange={(e) => setStartTime(e.target.value)} placeholder="8:00 AM" />
          </Field>
          <Field label={t("End time")}>
            <input value={endTime} onChange={(e) => setEndTime(e.target.value)} placeholder="3:00 PM" />
          </Field>
          <Field label={t("Early dismissal time")} hint={t("What time a half day lets out")}>
            <input value={earlyDismissalTime} onChange={(e) => setEarlyDismissalTime(e.target.value)} placeholder="11:45 AM" />
          </Field>
          <Field label={t("Delayed opening time")} hint={t("What time class starts on a 2-hour-delay day")}>
            <input value={delayedOpeningTime} onChange={(e) => setDelayedOpeningTime(e.target.value)} placeholder="9:30 AM" />
          </Field>
        </div>

        <div className="section-title">
          {t("Period-by-period schedule")} <span className="fine">{t('(optional — powers the "what period is it now" chip)')}</span>
        </div>
        <div className="tabs">
          {VARIANTS.map((v) => (
            <button
              type="button"
              key={v.key}
              className={`tab ${activeVariant === v.key ? "active" : ""}`}
              onClick={() => setActiveVariant(v.key)}
            >
              {t(v.label)}
              {periods[v.key].length > 0 && ` (${periods[v.key].length})`}
            </button>
          ))}
        </div>

        <div className="bell-rows">
          {rows.length === 0 && <p className="note">{t("No periods for {{variant}} yet.", { variant: t(VARIANTS.find((v) => v.key === activeVariant)!.label).toLowerCase() })}</p>}
          {rows.map((row, i) => (
            <div className="bell-row" key={i}>
              <input
                className="bell-name"
                value={row.name}
                onChange={(e) => updateRow(i, { name: e.target.value })}
                placeholder="1, L1, WIN, Outdoor Play…"
                maxLength={40}
                aria-label={t("Period name")}
              />
              <input type="time" value={row.start} onChange={(e) => updateRow(i, { start: e.target.value })} aria-label={t("Start time")} />
              <span className="bell-sep">–</span>
              <input type="time" value={row.end} onChange={(e) => updateRow(i, { end: e.target.value })} aria-label={t("End time")} />
              <button type="button" className="btn icon danger" onClick={() => removeRow(i)} aria-label={t("Remove period")}>
                ×
              </button>
            </div>
          ))}
        </div>
        <button type="button" className="btn sm" onClick={addRow}>
          {t("+ Add period")}
        </button>
      </form>
    </Modal>
  );
}
