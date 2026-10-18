import { type FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { BOT_CHECK_ENABLED, BotCheck } from "../../../components/BotCheck";
import { SeoHead } from "../../../components/SeoHead";
import { Field } from "../../../components/ui/Field";
import { type FilterOption, FilterSelect } from "../../../components/ui/FilterSelect";
import { PhoneInput } from "../../../components/ui/PhoneInput";
import { useAuth } from "../../../context/AuthContext";
import { usePrerenderReady } from "../../../lib/prerenderReady";
import { sendInquiry, validPhone } from "../../../lib/providerPortal";

/** /localz/providers - "List your program": how listing works, the way in
 * for a signed-in provider, and "Ask to be listed" for anyone who'd rather
 * we call them (no account). */
export function ProvidersPage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  usePrerenderReady(true);

  return (
    <div className="provider-page">
      <SeoHead
        title={t("List your program · Localz")}
        description={t("Run a food pantry, shelter, clinic or another program? List it on Localz for free and keep your hours up to date.")}
        path="/localz/providers"
      />
      <h2 className="localz-title">{t("List your program")}</h2>
      <p className="localz-lede">
        {t("Run a food pantry, shelter, clinic or another program for people who need help? List it on Localz for free, and keep your hours and closures up to date yourself.")}
      </p>

      <ol className="provider-steps">
        <li>{t("Tell us about your program: what you provide, where, when, and who can come.")}</li>
        <li>{t("We check every listing before it goes live. We'll call the number you listed to confirm it's you. We usually review within 3 business days.")}</li>
        <li>{t("Once it's approved, you can post closures, this week's hours and alerts, and they show right away.")}</li>
      </ol>
      <p className="note">
        {t("Confidential locations, like domestic violence shelters: we never publish your address. Your listing shows your phone and \"Location shared after you call\".")}
      </p>

      <div className="provider-cta">
        {user ? (
          <>
            <Link className="btn btn-primary" to="/localz/providers/requests/new">
              {t("Start your listing")}
            </Link>
            <Link className="btn" to="/localz/providers/portal">
              {t("Your listings and requests")}
            </Link>
          </>
        ) : (
          <Link className="btn btn-primary" to={`/login?next=${encodeURIComponent("/localz/providers/portal")}`}>
            {t("Sign in or create an account to start")}
          </Link>
        )}
      </div>

      <InquiryForm />
    </div>
  );
}

const OTHER_TOWN = "__other__";

function InquiryForm() {
  const { t } = useTranslation();
  const [form, setForm] = useState({ organization_name: "", first_name: "", last_name: "", phone: "", email: "", what_you_provide: "", town: "" });
  // Town is picked from New Jersey's towns (scripts/build_nj_towns.py),
  // loaded on this page only; "not listed" opens a box to type it.
  const [towns, setTowns] = useState<FilterOption[]>([]);
  const [townPick, setTownPick] = useState("");
  useEffect(() => {
    import("../../../lib/njTowns.json").then((m) => {
      const rows = m.default as unknown as [string, string][];
      const seen = new Map<string, number>();
      for (const [name] of rows) seen.set(name, (seen.get(name) ?? 0) + 1);
      setTowns(
        rows.map(([name, county]) => ({
          value: `${name}, ${county} County`,
          // Five Washingtons: once picked, the box has to say which one.
          label: (seen.get(name) ?? 0) > 1 ? `${name} (${county})` : name,
          hint: t("{{county}} County", { county }),
        })),
      );
    });
  }, [t]);
  const [website, setWebsite] = useState("");
  const [botToken, setBotToken] = useState<string | null>(null);
  const [botRound, setBotRound] = useState(0);
  const [botDown, setBotDown] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });

  // Said under the button, so a disabled button is never a mystery.
  const missing = [
    !form.organization_name.trim() && t("Organization name"),
    !form.first_name.trim() && t("First name"),
    !form.last_name.trim() && t("Last name"),
    !validPhone(form.phone) && t("a 10-digit phone number"),
    !form.town.trim() && t("Town"),
    !form.what_you_provide.trim() && t("What you provide"),
  ].filter(Boolean) as string[];
  const botPending = BOT_CHECK_ENABLED && !botToken && !botDown;
  const ready = missing.length === 0 && (!BOT_CHECK_ENABLED || botToken);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { first_name, last_name, ...rest } = form;
      await sendInquiry({
        ...rest,
        contact_name: `${first_name.trim()} ${last_name.trim()}`,
        email: form.email.trim() || null,
        website: website || null,
        bot_token: botToken,
      });
      setDone(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("Couldn't send this - please try again."));
      setBotRound((n) => n + 1);
      setBotToken(null);
    } finally {
      setBusy(false);
    }
  };

  if (done) {
    return (
      <section className="card provider-inquiry">
        <h3>{t("Thanks - we have your request")}</h3>
        <p>{t("We'll call you at {{phone}} to set up your listing.", { phone: form.phone })}</p>
      </section>
    );
  }

  return (
    <section className="card provider-inquiry">
      <h3>{t("Ask to be listed")}</h3>
      <p className="note">{t("Rather we set it up with you? Leave your details and we'll call you. No account needed.")}</p>
      <form onSubmit={submit}>
        {error && <div className="form-error">{error}</div>}
        <Field label={t("Organization name")}>
          <input value={form.organization_name} onChange={set("organization_name")} maxLength={200} required />
        </Field>
        <div className="fgrid two">
          <Field label={t("First name")}>
            <input value={form.first_name} onChange={set("first_name")} maxLength={100} autoComplete="given-name" required />
          </Field>
          <Field label={t("Last name")}>
            <input value={form.last_name} onChange={set("last_name")} maxLength={100} autoComplete="family-name" required />
          </Field>
          <Field label={t("Phone")}>
            <PhoneInput value={form.phone} onChange={(v) => setForm({ ...form, phone: v })} required />
          </Field>
          <Field label={t("Email")} hint={t("Optional")}>
            <input type="email" value={form.email} onChange={set("email")} maxLength={255} autoComplete="email" />
          </Field>
          <Field label={t("Town")}>
            <FilterSelect
              value={townPick}
              onChange={(v) => {
                setTownPick(v);
                setForm({ ...form, town: v === OTHER_TOWN ? "" : v });
              }}
              options={towns.length ? [...towns, { value: OTHER_TOWN, label: t("My town isn't listed") }] : []}
              placeholder={towns.length ? t("Pick your town") : t("Loading…")}
              filterPlaceholder={t("Type to find your town")}
              ariaLabel={t("Town")}
              disabled={!towns.length}
              required
            />
          </Field>
          {townPick === OTHER_TOWN && (
            <Field label={t("Your town")}>
              <input value={form.town} onChange={set("town")} maxLength={100} required />
            </Field>
          )}
        </div>
        <Field label={t("What you provide")}>
          <textarea rows={3} value={form.what_you_provide} onChange={set("what_you_provide")} maxLength={1000} required />
        </Field>
        {/* Honeypot: hidden from people and screen readers. */}
        <div aria-hidden="true" style={{ position: "absolute", left: "-10000px", width: 1, height: 1, overflow: "hidden" }}>
          <label>
            Website
            <input tabIndex={-1} autoComplete="off" value={website} onChange={(e) => setWebsite(e.target.value)} />
          </label>
        </div>
        {BOT_CHECK_ENABLED && <BotCheck onToken={setBotToken} onUnavailable={() => setBotDown(true)} resetKey={botRound} />}
        {botDown && !botToken && <p className="note">{t("The \"are you a person\" check didn't load. Reload the page to try again.")}</p>}
        <p className="note">{t("We use these details only to contact you about your listing. They're never shown publicly.")}</p>
        <button className="btn btn-primary" type="submit" disabled={!ready || busy}>
          {busy ? t("Sending…") : t("Ask to be listed")}
        </button>
        {missing.length > 0 ? (
          <p className="note">{t("Still needed: {{items}}", { items: missing.join(", ") })}</p>
        ) : botPending ? (
          <p className="note">{t("Last step: tick the box above to show you're a person.")}</p>
        ) : null}
      </form>
    </section>
  );
}
