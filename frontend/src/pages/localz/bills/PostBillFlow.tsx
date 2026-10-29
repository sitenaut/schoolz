import { type FormEvent, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { type Draft, dollars, parseDollars, postBill, shortDate, uploadBill } from "../../../lib/bills";
import { AVATAR_KEYS, Avatar, errorText } from "./shared";

type Step = "intro" | "upload" | "check";

/** Posting a bill: other help first (a suggestion, not a gate), then the
 * upload, then checking what was read, an avatar, and saying out loud who
 * sees what. */
export function PostBillFlow({ onPosted, onCancel }: { onPosted: () => void; onCancel: () => void }) {
  const { t } = useTranslation();
  const [step, setStep] = useState<Step>("intro");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [account, setAccount] = useState("");
  const [zip, setZip] = useState("");
  const [amount, setAmount] = useState("");
  const [avatar, setAvatar] = useState<string | null>(null);
  const [understood, setUnderstood] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const upload = async (file: File | undefined) => {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const read = await uploadBill(file);
      setDraft(read);
      setAccount(read.account_number ?? "");
      setZip(read.service_zip ?? "");
      setAmount(((read.amount_due_cents ? Math.min(read.amount_due_cents, read.max_ask_cents) : read.max_ask_cents) / 100).toFixed(2));
      setStep("check");
    } catch (err) {
      setError(errorText(t, err));
    } finally {
      setBusy(false);
    }
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!draft) return;
    const cents = parseDollars(amount);
    if (cents === null || cents > draft.max_ask_cents || cents < 500) {
      setError(t("Ask for between $5 and {{max}}.", { max: dollars(draft.max_ask_cents) }));
      return;
    }
    if (!avatar) {
      setError(t("Pick an avatar."));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await postBill(draft.id, { account_number: account, service_zip: zip, amount_cents: cents, avatar, understood });
      onPosted();
    } catch (err) {
      setError(errorText(t, err));
      setBusy(false);
    }
  };

  if (step === "intro") {
    return (
      <section className="bills-flow">
        <h3>{t("Before you post")}</h3>
        <p>{t("Programs like USF, LIHEAP, NJ SHARES and PAGE can pay more than one bill, and PSE&G offers payment plans. They're worth a look first.")}</p>
        <div className="bills-actions">
          <Link className="btn" to="/localz/housing-bills">
            {t("See help with bills")}
          </Link>
          <button type="button" className="btn btn-primary" onClick={() => setStep("upload")}>
            {t("Continue")}
          </button>
          <button type="button" className="btn" onClick={onCancel}>
            {t("Cancel")}
          </button>
        </div>
      </section>
    );
  }

  if (step === "upload") {
    return (
      <section className="bills-flow">
        <h3>{t("Your PSE&G bill")}</h3>
        <p>{t("Take a photo of your bill, or choose the PDF. We'll read the account number, ZIP code, amount and due date from it for you to check.")}</p>
        <label className={`btn btn-primary bills-file ${busy ? "busy" : ""}`}>
          {busy ? t("Reading your bill…") : t("Choose a photo or PDF")}
          <input type="file" accept="image/*,application/pdf" disabled={busy} onChange={(e) => upload(e.target.files?.[0])} />
        </label>
        {error && <p className="bills-error">{error}</p>}
        <p className="bills-small">
          {t("An AI service (Anthropic) reads the bill to fill in the details. The photo is deleted once your bill is listed, or sooner if it can't be.")}
        </p>
        <button type="button" className="btn" onClick={onCancel}>
          {t("Cancel")}
        </button>
      </section>
    );
  }

  if (draft?.refused) {
    return (
      <section className="bills-flow">
        <h3>{t("We couldn't use this file")}</h3>
        <p>
          {draft.refused === "utility_not_supported"
            ? t("Neighborz takes PSE&G bills for now. Other utilities are coming.")
            : t("This doesn't look like a utility bill. Try a clear photo of the whole first page.")}
        </p>
        <button type="button" className="btn btn-primary" onClick={() => setStep("upload")}>
          {t("Try another file")}
        </button>
      </section>
    );
  }

  return (
    <form className="bills-flow" onSubmit={submit}>
      <h3>{t("Check what we read")}</h3>
      <p>{t("Compare these with your bill. If you change the account number or ZIP code, someone checks it against your bill before it's listed.")}</p>
      <label className="bills-field">
        <span>{t("Account number")}</span>
        <input value={account} onChange={(e) => setAccount(e.target.value)} inputMode="numeric" autoComplete="off" maxLength={40} required />
      </label>
      <label className="bills-field">
        <span>{t("ZIP code where the service is")}</span>
        <input value={zip} onChange={(e) => setZip(e.target.value)} inputMode="numeric" autoComplete="off" maxLength={10} required />
      </label>
      <dl className="bills-facts">
        <dt>{t("Amount due")}</dt>
        <dd>{draft?.amount_due_cents ? dollars(draft.amount_due_cents) : t("Couldn't read it")}</dd>
        {draft?.due_date && (
          <>
            <dt>{t("Due date")}</dt>
            <dd>{shortDate(draft.due_date)}</dd>
          </>
        )}
        {draft?.shutoff_notice && (
          <>
            <dt>{t("Shutoff notice")}</dt>
            <dd>{t("Yes")}</dd>
          </>
        )}
      </dl>
      <label className="bills-field">
        <span>{t("How much to ask for")}</span>
        <input value={amount} onChange={(e) => setAmount(e.target.value)} inputMode="decimal" autoComplete="off" required />
        <small>{t("Up to {{max}}. One neighbor pays the whole amount.", { max: dollars(draft?.max_ask_cents) })}</small>
      </label>

      <fieldset className="bills-avatars">
        <legend>{t("Pick an avatar for your listing")}</legend>
        {AVATAR_KEYS.map((key) => (
          <label key={key} className={`bills-avatar-pick ${avatar === key ? "picked" : ""}`}>
            <input type="radio" name="avatar" value={key} checked={avatar === key} onChange={() => setAvatar(key)} />
            <Avatar name={key} size={44} />
          </label>
        ))}
      </fieldset>

      <label className="bills-understand">
        <input type="checkbox" checked={understood} onChange={(e) => setUnderstood(e.target.checked)} />
        <span>
          {t("I understand: the person who pays will see my account number and ZIP code. That's all PSE&G needs. They won't see my name or address, and I won't see theirs.")}
        </span>
      </label>
      {error && <p className="bills-error">{error}</p>}
      <div className="bills-actions">
        <button type="submit" className="btn btn-primary" disabled={busy || !understood}>
          {busy ? t("One moment…") : t("Post my bill")}
        </button>
        <button type="button" className="btn" onClick={onCancel}>
          {t("Cancel")}
        </button>
      </div>
    </form>
  );
}
