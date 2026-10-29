import { type FormEvent, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Helmet } from "react-helmet-async";
import { IconCopy } from "../../../components/icons";
import { type Hold, dollars, fetchHold, parseDollars, releaseHold, reportPaid, shortDate, todayIso } from "../../../lib/bills";
import { Avatar, EMOJIS, errorText, timeLeft } from "./shared";

/** /localz/bills/hold/:holdId - what the utility's guest payment needs,
 * shown only to the giver holding the bill and only while they hold it;
 * then "I paid it" with PSE&G's confirmation number. */
export function HoldPage() {
  const { t } = useTranslation();
  const { holdId = "" } = useParams();
  const navigate = useNavigate();
  const [hold, setHold] = useState<Hold | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmation, setConfirmation] = useState("");
  const [paid, setPaid] = useState("");
  const [paidOn, setPaidOn] = useState(todayIso());
  const [busy, setBusy] = useState(false);
  const [, tick] = useState(0);

  useEffect(() => {
    fetchHold(holdId)
      .then((h) => {
        setHold(h);
        setPaid(((h.amount_cents ?? 0) / 100).toFixed(2));
      })
      .catch((err) => setError(errorText(t, err)));
  }, [holdId, t]);
  // Keep "time left" honest while the page is open.
  useEffect(() => {
    const timer = window.setInterval(() => tick((n) => n + 1), 60_000);
    return () => window.clearInterval(timer);
  }, []);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!hold) return;
    const cents = parseDollars(paid);
    if (cents === null) {
      setError(t("Enter the amount the bill asked for."));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setHold(await reportPaid(hold.id, { confirmation_number: confirmation.trim(), paid_cents: cents, paid_on: paidOn }));
    } catch (err) {
      setError(errorText(t, err));
    } finally {
      setBusy(false);
    }
  };

  const letGo = async () => {
    if (!hold) return;
    setBusy(true);
    try {
      await releaseHold(hold.id);
      navigate("/localz/bills");
    } catch (err) {
      setError(errorText(t, err));
      setBusy(false);
    }
  };

  return (
    <div className="bills">
      <Helmet>
        <title>Localz</title>
      </Helmet>
      <Link to="/localz/bills/mine" className="localz-back-link">
        {t("‹ My Neighborz")}
      </Link>
      {hold === null ? (
        error ? <p className="bills-error">{error}</p> : <p className="localz-lede">{t("Loading…")}</p>
      ) : (
        <>
          <div className="bills-hold-head">
            <Avatar name={hold.avatar} size={56} />
            <div>
              <h2 className="localz-title">{dollars(hold.amount_cents)}</h2>
              <div className="bills-meta">
                {[hold.utility_name, hold.county ? t("{{county}} County", { county: hold.county }) : null, hold.due_date ? t("Due {{date}}", { date: shortDate(hold.due_date) }) : null]
                  .filter(Boolean)
                  .join(" · ")}
              </div>
            </div>
          </div>

          {hold.status === "active" ? (
            <>
              <p className="bills-status">{t("This bill is yours to pay. {{left}}.", { left: timeLeft(t, hold.expires_at) })}</p>
              <section className="bills-flow">
                <h3>{t("Pay {{utility}} as a guest", { utility: hold.utility_name ?? "PSE&G" })}</h3>
                <dl className="bills-facts bills-pay">
                  <dt>{t("Account number")}</dt>
                  <dd>
                    <Copyable value={hold.account_number ?? ""} />
                  </dd>
                  <dt>{t("ZIP code")}</dt>
                  <dd>
                    <Copyable value={hold.service_zip ?? ""} />
                  </dd>
                  <dt>{t("Amount")}</dt>
                  <dd>{dollars(hold.amount_cents)}</dd>
                </dl>
                <ol className="bills-steps">
                  <li>
                    {hold.pay_url ? (
                      <a href={hold.pay_url} target="_blank" rel="noopener noreferrer">
                        {t("Open {{utility}}'s payment page", { utility: hold.utility_name ?? "PSE&G" })}
                      </a>
                    ) : (
                      t("Go to {{utility}}'s website", { utility: hold.utility_name ?? "PSE&G" })
                    )}
                    {hold.pay_phone && <> {t("or call {{phone}}", { phone: hold.pay_phone })}</>}
                    {"."}
                  </li>
                  <li>{t("Choose to pay without signing in (as a guest).")}</li>
                  <li>{t("Enter the account number, ZIP code and amount above. The utility may charge its own card fee.")}</li>
                  <li>{t("Write down the confirmation number it gives you, then enter it below.")}</li>
                </ol>
              </section>

              <form className="bills-flow" onSubmit={submit}>
                <h3>{t("I paid it")}</h3>
                <label className="bills-field">
                  <span>{t("Confirmation number")}</span>
                  <input
                    value={confirmation}
                    onChange={(e) => setConfirmation(e.target.value.replace(/\s/g, ""))}
                    autoComplete="off"
                    maxLength={30}
                    required
                  />
                  <small>{t("Letters, numbers and dashes. Only you see it.")}</small>
                </label>
                <label className="bills-field">
                  <span>{t("Amount you paid")}</span>
                  <input value={paid} onChange={(e) => setPaid(e.target.value)} inputMode="decimal" autoComplete="off" required />
                </label>
                <label className="bills-field">
                  <span>{t("Date you paid")}</span>
                  <input type="date" value={paidOn} max={todayIso()} onChange={(e) => setPaidOn(e.target.value)} required />
                </label>
                {error && <p className="bills-error">{error}</p>}
                <div className="bills-actions">
                  <button type="submit" className="btn btn-primary" disabled={busy}>
                    {busy ? t("One moment…") : t("Send")}
                  </button>
                  <button type="button" className="btn" disabled={busy} onClick={letGo}>
                    {t("I can't pay this after all")}
                  </button>
                </div>
              </form>
            </>
          ) : (
            <section className="bills-flow">
              <p className="bills-status">
                {hold.status === "reported"
                  ? t("Thank you! Your neighbor will check that the payment arrived.")
                  : hold.status === "confirmed"
                    ? t("Paid. Thank you!")
                    : hold.status === "disputed"
                      ? t("Your neighbor says it hasn't arrived yet. We're looking into it.")
                      : hold.status === "withdrawn"
                        ? t("Your neighbor took this bill down. Nothing more to do.")
                        : t("This hold has ended.")}
              </p>
              {hold.confirmation_number && (
                <p className="bills-small">
                  {t("Confirmation number")}: <code>{hold.confirmation_number}</code>
                </p>
              )}
              {hold.thanks && <p className="bills-thanked">{t("Your neighbor sent {{emoji}}", { emoji: EMOJIS[hold.thanks] ?? "" })}</p>}
            </section>
          )}
          <p className="localz-footnote">
            {t("Keep PSE&G's confirmation number and your bank or card receipt. Paying someone's bill is a gift to a person, so it isn't tax-deductible.")}
          </p>
        </>
      )}
    </div>
  );
}

function Copyable({ value }: { value: string }) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      /* no clipboard: the value is on screen to copy by hand */
    }
  };
  return (
    <span className="bills-copy">
      <code>{value}</code>
      <button type="button" className="btn icon" onClick={copy} aria-label={t("Copy")}>
        <IconCopy />
      </button>
      {copied && <span className="bills-small">{t("Copied")}</span>}
    </span>
  );
}
