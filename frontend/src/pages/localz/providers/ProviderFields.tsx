import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Field } from "../../../components/ui/Field";
import { LOCALZ_COUNTIES } from "../../../lib/localz";
import {
  type AddressKind,
  type Completeness,
  type Cost,
  DAYS,
  type DayKey,
  type Delivery,
  type Hours,
  type HoursMode,
  ITEM_LABELS,
  type MonthWeek,
  type MonthlyRule,
  type ProgramPlace,
  type ProviderType,
  type ServiceEntry,
  type Signup,
  type SignupStatus,
  type Submission,
  type WhoCanCome,
  emptyHours,
  emptyPlace,
  emptySignup,
  emptyWho,
} from "../../../lib/providerPortal";

/** The pieces of the provider form, shared by the request form, the quick
 * updates screen and the reviewers' "edit before approving". */

export function CountyPicker({ value, onChange, label }: { value: string[]; onChange: (v: string[]) => void; label: string }) {
  const { t } = useTranslation();
  const toggle = (c: string) => onChange(value.includes(c) ? value.filter((x) => x !== c) : [...value, c]);
  return (
    <fieldset className="provider-fieldset">
      <legend className="lbl">{label}</legend>
      <div className="chips provider-chips">
        {LOCALZ_COUNTIES.map((c) => (
          <button type="button" key={c} className="chip" aria-pressed={value.includes(c)} onClick={() => toggle(c)}>
            {t("{{county}} County", { county: c })}
          </button>
        ))}
      </div>
    </fieldset>
  );
}

const HOURS_MODES: { key: HoursMode; label: string }[] = [
  { key: "weekly", label: "Set hours each week" },
  { key: "monthly", label: "Certain weeks of the month" },
  { key: "24_7", label: "Open 24/7" },
  { key: "appointment", label: "By appointment" },
  { key: "call", label: "Call for hours" },
];

export function HoursEditor({ value, onChange, idPrefix }: { value: Hours; onChange: (h: Hours) => void; idPrefix: string }) {
  const { t } = useTranslation();
  const setDay = (day: DayKey, ranges: { open: string; close: string }[]) => onChange({ ...value, weekly: { ...value.weekly, [day]: ranges } });
  return (
    <div>
      <div className="checks provider-radio-row" role="radiogroup" aria-label={t("Hours")}>
        {HOURS_MODES.map((m) => (
          <label key={m.key} className={`check ${value.mode === m.key ? "on" : ""}`}>
            <input type="radio" name={`${idPrefix}-hours-mode`} checked={value.mode === m.key} onChange={() => onChange({ ...value, mode: m.key })} />
            <span>{t(m.label)}</span>
          </label>
        ))}
      </div>
      {value.mode === "call" && <p className="note">{t("\"Call for hours\" needs a phone number people can call.")}</p>}
      {value.mode === "monthly" && <MonthlyEditor value={value.monthly ?? []} onChange={(monthly) => onChange({ ...value, monthly })} />}
      {value.mode === "weekly" && (
        <div className="provider-days">
          {DAYS.map((d) => {
            const ranges = value.weekly[d.key] ?? [];
            return (
              <div key={d.key} className="provider-day">
                <span className="provider-day-name">{t(d.label)}</span>
                <div className="provider-day-ranges">
                  {ranges.length === 0 && <span className="localz-muted">{t("Closed")}</span>}
                  {ranges.map((r, i) => (
                    <span key={i} className="provider-range">
                      <input
                        type="time"
                        aria-label={t("Opens")}
                        value={r.open}
                        onChange={(e) => setDay(d.key, ranges.map((x, j) => (j === i ? { ...x, open: e.target.value } : x)))}
                      />
                      <span aria-hidden>–</span>
                      <input
                        type="time"
                        aria-label={t("Closes")}
                        value={r.close}
                        onChange={(e) => setDay(d.key, ranges.map((x, j) => (j === i ? { ...x, close: e.target.value } : x)))}
                      />
                      <button type="button" className="btn ghost" onClick={() => setDay(d.key, ranges.filter((_, j) => j !== i))}>
                        {t("Remove")}
                      </button>
                    </span>
                  ))}
                  <button type="button" className="btn ghost" onClick={() => setDay(d.key, [...ranges, { open: "09:00", close: "17:00" }])}>
                    {ranges.length ? t("Add another time") : t("Add hours")}
                  </button>
                </div>
              </div>
            );
          })}
          <label className={`check ${value.alternate_weeks_from ? "on" : ""}`}>
            <input
              type="checkbox"
              checked={!!value.alternate_weeks_from}
              onChange={(e) => onChange({ ...value, alternate_weeks_from: e.target.checked ? todayIso() : null })}
            />
            <span>{t("Every other week")}</span>
          </label>
          {value.alternate_weeks_from && (
            <Field label={t("One week it happens")} hint={t("Any day in a week it's on. We count every other week from there.")}>
              <input type="date" value={value.alternate_weeks_from} onChange={(e) => onChange({ ...value, alternate_weeks_from: e.target.value || null })} />
            </Field>
          )}
        </div>
      )}
      {(value.mode === "weekly" || value.mode === "monthly") && <SeasonEditor value={value.season ?? null} onChange={(season) => onChange({ ...value, season })} />}
      <Field label={t("Anything else about your hours?")} hint={t("Optional - for example, \"Closed on holidays\". This adds to the schedule, it doesn't replace it.")}>
        <input value={value.note ?? ""} maxLength={300} onChange={(e) => onChange({ ...value, note: e.target.value || null })} />
      </Field>
    </div>
  );
}

const todayIso = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

const MONTH_WEEKS: { key: MonthWeek; label: string }[] = [
  { key: 1, label: "1st" },
  { key: 2, label: "2nd" },
  { key: 3, label: "3rd" },
  { key: 4, label: "4th" },
  { key: 5, label: "5th" },
  { key: -1, label: "Last" },
];

/** "The 1st and 3rd Tuesday, 6-8 pm": one row per day and time. */
function MonthlyEditor({ value, onChange }: { value: MonthlyRule[]; onChange: (v: MonthlyRule[]) => void }) {
  const { t } = useTranslation();
  const set = (i: number, rule: MonthlyRule) => onChange(value.map((x, j) => (j === i ? rule : x)));
  return (
    <div className="provider-days">
      {value.length === 0 && <p className="note">{t("Add the day of the month it happens, for example the 3rd Wednesday.")}</p>}
      {value.map((r, i) => (
        <div key={i} className="provider-month-rule">
          <div className="chips provider-chips" role="group" aria-label={t("Which weeks")}>
            {MONTH_WEEKS.map((w) => (
              <button
                type="button"
                key={w.key}
                className="chip"
                aria-pressed={r.weeks.includes(w.key)}
                onClick={() => {
                  const weeks = r.weeks.includes(w.key) ? r.weeks.filter((x) => x !== w.key) : [...r.weeks, w.key];
                  if (weeks.length) set(i, { ...r, weeks });
                }}
              >
                {t(w.label)}
              </button>
            ))}
          </div>
          <span className="provider-range">
            <select aria-label={t("Day")} value={r.day} onChange={(e) => set(i, { ...r, day: e.target.value as DayKey })}>
              {DAYS.map((d) => (
                <option key={d.key} value={d.key}>
                  {t(d.label)}
                </option>
              ))}
            </select>
            <input type="time" aria-label={t("Opens")} value={r.open} onChange={(e) => set(i, { ...r, open: e.target.value })} />
            <span aria-hidden>–</span>
            <input type="time" aria-label={t("Closes")} value={r.close} onChange={(e) => set(i, { ...r, close: e.target.value })} />
            <button type="button" className="btn ghost" onClick={() => onChange(value.filter((_, j) => j !== i))}>
              {t("Remove")}
            </button>
          </span>
        </div>
      ))}
      {value.length < 10 && (
        <button type="button" className="btn ghost" onClick={() => onChange([...value, { weeks: [1], day: "mon", open: "09:00", close: "12:00" }])}>
          {value.length ? t("Add another day") : t("Add a day")}
        </button>
      )}
    </div>
  );
}

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const pad = (n: number) => String(n).padStart(2, "0");

function MonthDay({ value, onChange, label }: { value: string; onChange: (v: string) => void; label: string }) {
  const { t } = useTranslation();
  const [m, d] = value.split("-").map(Number);
  return (
    <fieldset className="provider-fieldset provider-month-day">
      <legend className="lbl">{label}</legend>
      <select aria-label={t("Month")} value={m} onChange={(e) => onChange(`${pad(Number(e.target.value))}-${pad(d)}`)}>
        {MONTHS.map((name, i) => (
          <option key={name} value={i + 1}>
            {t(name)}
          </option>
        ))}
      </select>
      <select aria-label={t("Day of the month")} value={d} onChange={(e) => onChange(`${pad(m)}-${pad(Number(e.target.value))}`)}>
        {Array.from({ length: 31 }, (_, i) => i + 1).map((n) => (
          <option key={n} value={n}>
            {n}
          </option>
        ))}
      </select>
    </fieldset>
  );
}

/** Runs only part of the year (a class term, a winter program), every year. */
function SeasonEditor({ value, onChange }: { value: { start: string; end: string } | null; onChange: (v: { start: string; end: string } | null) => void }) {
  const { t } = useTranslation();
  return (
    <div style={{ marginTop: 10 }}>
      <label className={`check ${value ? "on" : ""}`}>
        <input type="checkbox" checked={!!value} onChange={(e) => onChange(e.target.checked ? { start: "09-01", end: "06-30" } : null)} />
        <span>{t("Only part of the year")}</span>
      </label>
      {value && (
        <div className="fgrid two" style={{ marginTop: 8 }}>
          <MonthDay label={t("Starts")} value={value.start} onChange={(start) => onChange({ ...value, start })} />
          <MonthDay label={t("Ends")} value={value.end} onChange={(end) => onChange({ ...value, end })} />
        </div>
      )}
    </div>
  );
}

export function WhoEditor({ value: who, onChange }: { value: WhoCanCome; onChange: (w: WhoCanCome) => void }) {
  const { t } = useTranslation();
  return (
    <div>
      <label className={`check ${who.open_to_anyone ? "on" : ""}`}>
        <input type="checkbox" checked={who.open_to_anyone} onChange={(e) => onChange({ ...who, open_to_anyone: e.target.checked })} />
        <span>
          <strong>{t("Open to anyone")}</strong>
        </span>
      </label>
      {!who.open_to_anyone && (
        <div style={{ marginTop: 10 }}>
          <div className="checks">
            {(
              [
                ["families_with_children", "Families with children"],
                ["low_income", "People with low income"],
                ["seniors", "Adults 60 and older"],
              ] as const
            ).map(([key, label]) => (
              <label key={key} className={`check ${who[key] ? "on" : ""}`}>
                <input type="checkbox" checked={who[key]} onChange={(e) => onChange({ ...who, [key]: e.target.checked })} />
                <span>{t(label)}</span>
              </label>
            ))}
          </div>
          <div className="fgrid two" style={{ marginTop: 10 }}>
            <Field label={t("Youngest age served")} hint={t("Optional")}>
              <input type="number" min={0} max={120} value={who.age_min ?? ""} onChange={(e) => onChange({ ...who, age_min: e.target.value === "" ? null : Number(e.target.value) })} />
            </Field>
            <Field label={t("Oldest age served")} hint={t("Optional")}>
              <input type="number" min={0} max={120} value={who.age_max ?? ""} onChange={(e) => onChange({ ...who, age_max: e.target.value === "" ? null : Number(e.target.value) })} />
            </Field>
          </div>
          <CountyPicker label={t("Only for people who live in (optional)")} value={who.counties} onChange={(counties) => onChange({ ...who, counties })} />
        </div>
      )}
      <Field label={t("Anything else about who can come?")} hint={t("Optional")}>
        <input value={who.note ?? ""} maxLength={300} onChange={(e) => onChange({ ...who, note: e.target.value || null })} />
      </Field>
    </div>
  );
}

export function CostEditor({ value, onChange, idPrefix, freeKinds }: { value: Cost; onChange: (c: Cost) => void; idPrefix: string; freeKinds: boolean }) {
  const { t } = useTranslation();
  return (
    <div>
      <div className="checks provider-radio-row" role="radiogroup" aria-label={t("Cost")}>
        {(
          [
            ["free", "Free"],
            ["sliding", "Sliding scale"],
            ["fee", "There's a fee"],
          ] as const
        ).map(([key, label]) => (
          <label key={key} className={`check ${value.kind === key ? "on" : ""}`}>
            <input type="radio" name={`${idPrefix}-cost`} checked={value.kind === key} onChange={() => onChange({ ...value, kind: key })} />
            <span>{t(label)}</span>
          </label>
        ))}
      </div>
      {value.kind && value.kind !== "free" && (
        <Field label={t("How much?")} hint={value.kind === "sliding" ? t("Optional") : undefined}>
          <input value={value.amount ?? ""} maxLength={100} onChange={(e) => onChange({ ...value, amount: e.target.value })} />
        </Field>
      )}
      {value.kind === "fee" && freeKinds && <p className="note">{t("This kind of help is usually free, so a reviewer will ask about the fee.")}</p>}
    </div>
  );
}

const SIGNUP_CHOICES: { key: SignupStatus; label: string }[] = [
  { key: "drop_in", label: "Just come - no sign-up" },
  { key: "open", label: "Sign up now" },
  { key: "waitlist", label: "Waiting list" },
  { key: "closed", label: "Sign-ups closed for now" },
];

/** How a program takes people, with "opens again on" for a closed one. */
export function SignupEditor({ value, onChange, idPrefix }: { value: Signup; onChange: (s: Signup) => void; idPrefix: string }) {
  const { t } = useTranslation();
  return (
    <div>
      <Field label={t("How do people join?")}>
        <select id={`${idPrefix}-signup`} value={value.status ?? ""} onChange={(e) => onChange({ ...value, status: (e.target.value || null) as SignupStatus | null })}>
          <option value="">{t("Not sure / skip")}</option>
          {SIGNUP_CHOICES.map((c) => (
            <option key={c.key} value={c.key}>
              {t(c.label)}
            </option>
          ))}
        </select>
      </Field>
      {value.status === "closed" && (
        <Field label={t("Sign-ups open again on")} hint={t("Optional")}>
          <input type="date" value={value.opens_on ?? ""} onChange={(e) => onChange({ ...value, opens_on: e.target.value || null })} />
        </Field>
      )}
      {value.status && value.status !== "drop_in" && (
        <Field label={t("How to sign up")} hint={t("Optional - for example \"Call to book an interview\".")}>
          <input value={value.how ?? ""} maxLength={300} onChange={(e) => onChange({ ...value, how: e.target.value || null })} />
        </Field>
      )}
    </div>
  );
}

export const DELIVERY_CHOICES: { key: Delivery; label: string }[] = [
  { key: "in_person", label: "In person" },
  { key: "online", label: "Online only" },
  { key: "both", label: "In person or online" },
];

export function DeliverySelect({ value, onChange }: { value: Delivery | null; onChange: (d: Delivery | null) => void }) {
  const { t } = useTranslation();
  return (
    <Field label={t("In person or online?")}>
      <select value={value ?? ""} onChange={(e) => onChange((e.target.value || null) as Delivery | null)}>
        <option value="">{t("In person")}</option>
        {DELIVERY_CHOICES.filter((c) => c.key !== "in_person").map((c) => (
          <option key={c.key} value={c.key}>
            {t(c.label)}
          </option>
        ))}
      </select>
    </Field>
  );
}

function PlaceFields({ value, onChange }: { value: ProgramPlace; onChange: (p: ProgramPlace) => void }) {
  const { t } = useTranslation();
  return (
    <div className="fgrid two">
      <Field label={t("Name of the place")} hint={t("Optional - for example \"Church hall, lower level\".")}>
        <input value={value.place_name ?? ""} maxLength={200} onChange={(e) => onChange({ ...value, place_name: e.target.value })} />
      </Field>
      <Field label={t("Street address")}>
        <input value={value.address ?? ""} maxLength={200} onChange={(e) => onChange({ ...value, address: e.target.value })} />
      </Field>
      <Field label={t("Town")}>
        <input value={value.city ?? ""} maxLength={100} onChange={(e) => onChange({ ...value, city: e.target.value })} />
      </Field>
      <Field label={t("ZIP code")}>
        <input
          value={value.postal_code ?? ""}
          inputMode="numeric"
          maxLength={5}
          onChange={(e) => onChange({ ...value, postal_code: e.target.value.replace(/\D/g, "").slice(0, 5) || null })}
        />
      </Field>
    </div>
  );
}

/** One program's own details: how people join, in person or online, and
 * whatever differs from the organization (times, place, who, cost). */
function ProgramDetails({
  entry,
  onChange,
  idPrefix,
  allowPlace,
  freeKind,
}: {
  entry: ServiceEntry;
  onChange: (e: ServiceEntry) => void;
  idPrefix: string;
  allowPlace: boolean;
  freeKind: boolean;
}) {
  const { t } = useTranslation();
  const own: { key: "hours" | "place" | "who" | "cost"; label: string; fresh: () => unknown }[] = [
    { key: "hours", label: "Its own days and times", fresh: emptyHours },
    ...(allowPlace ? [{ key: "place" as const, label: "It meets somewhere else", fresh: emptyPlace }] : []),
    { key: "who", label: "Its own rules on who can come", fresh: emptyWho },
    { key: "cost", label: "Its own cost", fresh: () => ({ kind: null, amount: null }) },
  ];
  return (
    <div className="provider-program-details">
      <div className="fgrid two">
        <DeliverySelect value={entry.delivery ?? null} onChange={(delivery) => onChange({ ...entry, delivery })} />
        <SignupEditor idPrefix={idPrefix} value={entry.signup ?? emptySignup()} onChange={(signup) => onChange({ ...entry, signup })} />
      </div>
      <p className="note">{t("Different from the rest of your organization? Tick what applies to this program.")}</p>
      <div className="checks">
        {own.map((o) => (
          <label key={o.key} className={`check ${entry[o.key] ? "on" : ""}`}>
            <input type="checkbox" checked={!!entry[o.key]} onChange={(e) => onChange({ ...entry, [o.key]: e.target.checked ? o.fresh() : null })} />
            <span>{t(o.label)}</span>
          </label>
        ))}
      </div>
      {entry.hours && (
        <div className="provider-subsection">
          <h4>{t("This program's days and times")}</h4>
          <HoursEditor idPrefix={`${idPrefix}-hours`} value={entry.hours} onChange={(hours) => onChange({ ...entry, hours })} />
        </div>
      )}
      {entry.place && allowPlace && (
        <div className="provider-subsection">
          <h4>{t("Where this program meets")}</h4>
          <PlaceFields value={entry.place} onChange={(place) => onChange({ ...entry, place })} />
        </div>
      )}
      {entry.who && (
        <div className="provider-subsection">
          <h4>{t("Who can come to this program")}</h4>
          <WhoEditor value={entry.who} onChange={(who) => onChange({ ...entry, who })} />
        </div>
      )}
      {entry.cost && (
        <div className="provider-subsection">
          <h4>{t("What this program costs")}</h4>
          <CostEditor idPrefix={`${idPrefix}-cost`} value={entry.cost} freeKinds={freeKind} onChange={(cost) => onChange({ ...entry, cost })} />
        </div>
      )}
    </div>
  );
}

export type AddressValue = {
  kind: AddressKind | null;
  address: string | null;
  city: string | null;
  postal_code: string | null;
  counties: string[];
};

const ADDRESS_KINDS: { key: AddressKind; label: string; hint: string }[] = [
  { key: "public", label: "A public address", hint: "People come to this address." },
  {
    key: "confidential",
    label: "A confidential location",
    hint: "For example a domestic violence shelter or safe house. We never publish it, show it on a map, or share it with search or our chatbot. Your listing shows your phone and \"Location shared after you call\".",
  },
  { key: "service_area", label: "No place to visit", hint: "For example a mobile pantry, home delivery or a hotline. Tell us the counties you serve." },
];

export function AddressFields({
  value,
  onChange,
  privateAddress,
  onPrivateAddress,
  hasPrivateAddress,
  idPrefix,
}: {
  value: AddressValue;
  onChange: (v: AddressValue) => void;
  privateAddress: string;
  onPrivateAddress: (v: string) => void;
  hasPrivateAddress: boolean;
  idPrefix: string;
}) {
  const { t } = useTranslation();
  return (
    <div>
      <div className="checks" role="radiogroup" aria-label={t("Address")}>
        {ADDRESS_KINDS.map((k) => (
          <label key={k.key} className={`check ${value.kind === k.key ? "on" : ""}`}>
            <input type="radio" name={`${idPrefix}-address-kind`} checked={value.kind === k.key} onChange={() => onChange({ ...value, kind: k.key })} />
            <span>
              <strong>{t(k.label)}</strong>
              <span className="note" style={{ display: "block" }}>
                {t(k.hint)}
              </span>
            </span>
          </label>
        ))}
      </div>
      {value.kind === "public" && (
        <div className="fgrid two" style={{ marginTop: 12 }}>
          <Field label={t("Street address")}>
            <input value={value.address ?? ""} maxLength={200} autoComplete="street-address" onChange={(e) => onChange({ ...value, address: e.target.value })} />
          </Field>
          <Field label={t("Town")}>
            <input value={value.city ?? ""} maxLength={100} onChange={(e) => onChange({ ...value, city: e.target.value })} />
          </Field>
          <Field label={t("ZIP code")}>
            <input
              value={value.postal_code ?? ""}
              inputMode="numeric"
              maxLength={5}
              onChange={(e) => onChange({ ...value, postal_code: e.target.value.replace(/\D/g, "").slice(0, 5) || null })}
            />
          </Field>
        </div>
      )}
      {value.kind && value.kind !== "public" && (
        <div style={{ marginTop: 12 }}>
          <Field
            label={value.kind === "confidential" ? t("The confidential address") : t("A mailing address")}
            hint={
              hasPrivateAddress && !privateAddress
                ? t("An address is saved. Type a new one only to replace it.")
                : value.kind === "confidential"
                  ? t("Only our reviewers see this, to confirm the listing. It is stored encrypted and never published.")
                  : t("Only for us to confirm the listing. Never published.")
            }
          >
            <textarea rows={2} maxLength={300} value={privateAddress} onChange={(e) => onPrivateAddress(e.target.value)} />
          </Field>
        </div>
      )}
      {value.kind && (
        <CountyPicker
          label={value.kind === "public" ? t("Counties you serve (optional)") : t("Counties you serve")}
          value={value.counties}
          onChange={(counties) => onChange({ ...value, counties })}
        />
      )}
    </div>
  );
}

export function TypeSelect({ types, value, onChange, label }: { types: ProviderType[]; value: string | null; onChange: (v: string) => void; label: string }) {
  const { t } = useTranslation();
  return (
    <Field label={label}>
      <select value={value ?? ""} onChange={(e) => onChange(e.target.value)}>
        <option value="" disabled>
          {t("Pick one")}
        </option>
        {types.map((ty) => (
          <option key={ty.key} value={ty.key}>
            {t(ty.label)}
          </option>
        ))}
      </select>
    </Field>
  );
}

export function CompletenessMeter({ c }: { c: Completeness }) {
  const { t } = useTranslation();
  return (
    <div className="provider-meter" aria-live="polite">
      <div className="provider-meter-row">
        <strong>{t("{{percent}}% complete", { percent: c.percent })}</strong>
        <div className="provider-meter-bar" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={c.percent}>
          <span style={{ width: `${c.percent}%` }} />
        </div>
      </div>
      {c.missing_core.length > 0 ? (
        <p className="note">{t("Still needed: {{items}}", { items: c.missing_core.map((k) => t(ITEM_LABELS[k] ?? k)).join(", ") })}</p>
      ) : c.missing_optional.length > 0 ? (
        <p className="note">{t("Ready to send. Adding these helps people too: {{items}}", { items: c.missing_optional.map((k) => t(ITEM_LABELS[k] ?? k)).join(", ") })}</p>
      ) : (
        <p className="note">{t("Everything's filled in.")}</p>
      )}
    </div>
  );
}

const listText = (v: string[]) => v.join("\n");
const textList = (v: string) =>
  v
    .split(/\n|,/)
    .map((x) => x.trim())
    .filter(Boolean);

/** The whole listing form. `fieldsToFix` highlights what a reviewer asked to change. */
export function ListingForm({
  value,
  onChange,
  types,
  privateAddress,
  onPrivateAddress,
  hasPrivateAddress,
  fieldsToFix = [],
  organizationExtra,
}: {
  organizationExtra?: ReactNode;
  value: Submission;
  onChange: (s: Submission) => void;
  types: ProviderType[];
  privateAddress: string;
  onPrivateAddress: (v: string) => void;
  hasPrivateAddress: boolean;
  fieldsToFix?: string[];
}) {
  const { t } = useTranslation();
  const set = <K extends keyof Submission>(key: K, v: Submission[K]) => onChange({ ...value, [key]: v });
  const fix = (key: string) => (fieldsToFix.includes(key) ? " provider-fix" : "");
  const isFree = (key: string | null) => !!types.find((ty) => ty.key === key)?.normally_free;
  const freeKinds = value.services.some((s) => isFree(s.type) && !s.cost);
  const setService = (i: number, entry: ServiceEntry) => set("services", value.services.map((x, j) => (j === i ? entry : x)));
  const allOwn = (key: "hours" | "who" | "cost") => value.services.length > 0 && value.services.every((s) => !!s[key]);
  const severalNote = value.services.length > 1 ? <p className="note">{t("For all your programs, unless a program sets its own.")}</p> : null;
  const confidentialHint = value.services.some((s) => types.find((ty) => ty.key === s.type)?.confidential_hint);

  return (
    <div className="provider-form">
      <section className={`provider-section${fix("organization_name")}`}>
        <h3>{t("Your organization")}</h3>
        <Field label={t("Organization name")}>
          <input value={value.organization_name ?? ""} maxLength={200} onChange={(e) => set("organization_name", e.target.value)} />
        </Field>
        {organizationExtra}
      </section>

      <section className={`provider-section${fix("services")}`}>
        <h3>{t("What you provide")}</h3>
        {value.services.map((s, i) => (
          <div key={i} className="provider-service">
            <TypeSelect
              types={types}
              label={t("Kind of help")}
              value={s.type}
              onChange={(type) => set("services", value.services.map((x, j) => (j === i ? { ...x, type } : x)))}
            />
            <Field label={t("Program name")} hint={t("For example \"Saturday food pantry\".")}>
              <input value={s.name ?? ""} maxLength={200} onChange={(e) => set("services", value.services.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))} />
            </Field>
            <Field label={t("In one line, what people get")}>
              <input
                value={s.description ?? ""}
                maxLength={500}
                onChange={(e) => set("services", value.services.map((x, j) => (j === i ? { ...x, description: e.target.value } : x)))}
              />
            </Field>
            <ProgramDetails
              idPrefix={`svc${i}`}
              entry={s}
              onChange={(entry) => setService(i, entry)}
              allowPlace={value.address_kind !== "confidential"}
              freeKind={isFree(s.type)}
            />
            {value.services.length > 1 && (
              <button type="button" className="btn ghost" onClick={() => set("services", value.services.filter((_, j) => j !== i))}>
                {t("Remove this program")}
              </button>
            )}
          </div>
        ))}
        {value.services.length < 10 && (
          <button type="button" className="btn" onClick={() => set("services", [...value.services, { type: null, name: "", description: "" }])}>
            {t("Add another program")}
          </button>
        )}
      </section>

      <section className={`provider-section${fix("address")}`}>
        <h3>{t("Where")}</h3>
        {confidentialHint && value.address_kind !== "confidential" && <p className="note">{t("Shelters usually choose \"A confidential location\".")}</p>}
        <AddressFields
          idPrefix="req"
          value={{ kind: value.address_kind, address: value.address, city: value.city, postal_code: value.postal_code, counties: value.service_area_counties }}
          onChange={(a) => onChange({ ...value, address_kind: a.kind, address: a.address, city: a.city, postal_code: a.postal_code, service_area_counties: a.counties })}
          privateAddress={privateAddress}
          onPrivateAddress={onPrivateAddress}
          hasPrivateAddress={hasPrivateAddress}
        />
      </section>

      <section className={`provider-section${fix("hours")}`}>
        <h3>{t("Hours")}</h3>
        {allOwn("hours") ? <p className="note">{t("Each program has its own days and times. Fill this in only for your office hours.")}</p> : severalNote}
        <HoursEditor idPrefix="req" value={value.hours} onChange={(h) => set("hours", h)} />
      </section>

      <section className={`provider-section${fix("phone")}`}>
        <h3>{t("Phone")}</h3>
        <Field label={t("A public number people can call")}>
          <input type="tel" value={value.phone ?? ""} maxLength={40} autoComplete="tel" onChange={(e) => set("phone", e.target.value)} />
        </Field>
      </section>

      <section className={`provider-section${fix("who")}`}>
        <h3>{t("Who can come")}</h3>
        {allOwn("who") ? <p className="note">{t("Each program says who can come.")}</p> : severalNote}
        <WhoEditor value={value.who} onChange={(w) => set("who", w)} />
      </section>

      <section className={`provider-section${fix("cost")}`}>
        <h3>{t("Cost")}</h3>
        {allOwn("cost") ? <p className="note">{t("Each program has its own cost.")}</p> : severalNote}
        <CostEditor idPrefix="req" value={value.cost} freeKinds={freeKinds} onChange={(c) => set("cost", c)} />
      </section>

      <section className="provider-section">
        <h3>{t("More details")}</h3>
        <p className="note">{t("Optional, but each one helps people decide to come.")}</p>
        <Field label={t("What to bring")} hint={t("One per line, for example \"Photo ID\".")}>
          <textarea rows={2} value={listText(value.documents)} onChange={(e) => set("documents", textList(e.target.value))} />
        </Field>
        <Field label={t("Languages spoken")} hint={t("Separate with commas.")}>
          <input value={value.languages.join(", ")} onChange={(e) => set("languages", textList(e.target.value))} />
        </Field>
        <Field label={t("Walk-in or appointment")}>
          <select value={value.access ?? ""} onChange={(e) => set("access", (e.target.value || null) as Submission["access"])}>
            <option value="">{t("Not sure / skip")}</option>
            <option value="walk_in">{t("Walk-ins welcome")}</option>
            <option value="appointment">{t("By appointment")}</option>
            <option value="both">{t("Either")}</option>
          </select>
        </Field>
        <Field label={t("How to get help")}>
          <textarea rows={2} maxLength={1000} value={value.how_to_apply ?? ""} onChange={(e) => set("how_to_apply", e.target.value || null)} />
        </Field>
        <Field label={t("Accessibility")}>
          <input value={value.accessibility ?? ""} maxLength={300} onChange={(e) => set("accessibility", e.target.value || null)} />
        </Field>
        <div className="fgrid two">
          <Field label={t("Website")} hint={t("The full address, not a short link.")}>
            <input type="url" value={value.website ?? ""} maxLength={300} onChange={(e) => set("website", e.target.value || null)} />
          </Field>
          <Field label={t("Public email")} hint={t("Optional - shown on the listing.")}>
            <input type="email" value={value.email ?? ""} maxLength={255} onChange={(e) => set("email", e.target.value || null)} />
          </Field>
        </div>
      </section>
    </div>
  );
}

/** Blank strings out, so the server's patterns (a 5-digit ZIP) see null. */
export function cleanSubmission(s: Submission): Submission {
  const blank = (v: string | null | undefined) => ((v ?? "").trim() ? (v ?? "").trim() : null);
  const hours = (h: Hours): Hours => ({ ...h, weekly: Object.fromEntries(Object.entries(h.weekly).filter(([, r]) => (r ?? []).length > 0)) });
  const services = s.services.map((x) => ({
    ...x,
    hours: x.hours ? hours(x.hours) : null,
    cost: x.cost ? { ...x.cost, amount: blank(x.cost.amount) } : null,
    // A confidential organization's programs never get a public place.
    place:
      x.place && s.address_kind !== "confidential"
        ? { place_name: blank(x.place.place_name), address: blank(x.place.address), city: blank(x.place.city), postal_code: blank(x.place.postal_code) }
        : null,
    signup: x.signup?.status ? { ...x.signup, how: blank(x.signup.how), opens_on: x.signup.status === "closed" ? x.signup.opens_on : null } : null,
  }));
  return {
    ...s,
    organization_name: blank(s.organization_name),
    address: blank(s.address),
    city: blank(s.city),
    postal_code: blank(s.postal_code),
    phone: blank(s.phone),
    website: blank(s.website),
    email: blank(s.email),
    services,
    hours: hours(s.hours),
    cost: { ...s.cost, amount: blank(s.cost.amount) },
  };
}
