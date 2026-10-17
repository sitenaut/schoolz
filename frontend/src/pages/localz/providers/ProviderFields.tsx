import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Field } from "../../../components/ui/Field";
import { LOCALZ_COUNTIES } from "../../../lib/localz";
import {
  type AddressKind,
  type Completeness,
  DAYS,
  type DayKey,
  type Hours,
  type HoursMode,
  ITEM_LABELS,
  type ProviderType,
  type Submission,
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
        </div>
      )}
      <Field label={t("Anything else about your hours?")} hint={t("Optional - for example, \"Closed on holidays\". This adds to the schedule, it doesn't replace it.")}>
        <input value={value.note ?? ""} maxLength={300} onChange={(e) => onChange({ ...value, note: e.target.value || null })} />
      </Field>
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
  const who = value.who;
  const freeKinds = value.services.some((s) => types.find((ty) => ty.key === s.type)?.normally_free);
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
        <label className={`check ${who.open_to_anyone ? "on" : ""}`}>
          <input type="checkbox" checked={who.open_to_anyone} onChange={(e) => set("who", { ...who, open_to_anyone: e.target.checked })} />
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
                  <input type="checkbox" checked={who[key]} onChange={(e) => set("who", { ...who, [key]: e.target.checked })} />
                  <span>{t(label)}</span>
                </label>
              ))}
            </div>
            <div className="fgrid two" style={{ marginTop: 10 }}>
              <Field label={t("Youngest age served")} hint={t("Optional")}>
                <input type="number" min={0} max={120} value={who.age_min ?? ""} onChange={(e) => set("who", { ...who, age_min: e.target.value === "" ? null : Number(e.target.value) })} />
              </Field>
              <Field label={t("Oldest age served")} hint={t("Optional")}>
                <input type="number" min={0} max={120} value={who.age_max ?? ""} onChange={(e) => set("who", { ...who, age_max: e.target.value === "" ? null : Number(e.target.value) })} />
              </Field>
            </div>
            <CountyPicker label={t("Only for people who live in (optional)")} value={who.counties} onChange={(counties) => set("who", { ...who, counties })} />
          </div>
        )}
        <Field label={t("Anything else about who can come?")} hint={t("Optional")}>
          <input value={who.note ?? ""} maxLength={300} onChange={(e) => set("who", { ...who, note: e.target.value || null })} />
        </Field>
      </section>

      <section className={`provider-section${fix("cost")}`}>
        <h3>{t("Cost")}</h3>
        <div className="checks provider-radio-row" role="radiogroup" aria-label={t("Cost")}>
          {(
            [
              ["free", "Free"],
              ["sliding", "Sliding scale"],
              ["fee", "There's a fee"],
            ] as const
          ).map(([key, label]) => (
            <label key={key} className={`check ${value.cost.kind === key ? "on" : ""}`}>
              <input type="radio" name="req-cost" checked={value.cost.kind === key} onChange={() => set("cost", { ...value.cost, kind: key })} />
              <span>{t(label)}</span>
            </label>
          ))}
        </div>
        {value.cost.kind && value.cost.kind !== "free" && (
          <Field label={t("How much?")} hint={value.cost.kind === "sliding" ? t("Optional") : undefined}>
            <input value={value.cost.amount ?? ""} maxLength={100} onChange={(e) => set("cost", { ...value.cost, amount: e.target.value })} />
          </Field>
        )}
        {value.cost.kind === "fee" && freeKinds && <p className="note">{t("This kind of help is usually free, so a reviewer will ask about the fee.")}</p>}
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
  return {
    ...s,
    organization_name: blank(s.organization_name),
    address: blank(s.address),
    city: blank(s.city),
    postal_code: blank(s.postal_code),
    phone: blank(s.phone),
    website: blank(s.website),
    email: blank(s.email),
    hours: {
      ...s.hours,
      weekly: Object.fromEntries(Object.entries(s.hours.weekly).filter(([, r]) => (r ?? []).length > 0)),
    },
    cost: { ...s.cost, amount: blank(s.cost.amount) },
  };
}
