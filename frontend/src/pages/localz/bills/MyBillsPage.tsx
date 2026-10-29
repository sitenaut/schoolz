import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { Helmet } from "react-helmet-async";
import {
  type Gift,
  type Mine,
  type Posted,
  answerBill,
  dollars,
  fetchMine,
  shortDate,
  thankGiver,
  withdrawBill,
} from "../../../lib/bills";
import { OtherHelp } from "./OtherHelp";
import { PostBillFlow } from "./PostBillFlow";
import { Avatar, EMOJIS, errorText, placeName, timeLeft } from "./shared";

/** /localz/bills/mine - both sides of Neighborz on one page, so browser
 * history on a shared device can't tell someone asking for help from
 * someone giving it. */
export function MyBillsPage() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const [mine, setMine] = useState<Mine | null>(null);
  const [error, setError] = useState<string | null>(null);
  const posting = params.get("post") === "1";

  const load = useCallback(() => {
    fetchMine()
      .then(setMine)
      .catch((err) => setError(errorText(t, err)));
  }, [t]);
  useEffect(load, [load]);

  const open = mine?.posted.find((p) => ["held", "available", "claimed", "reported", "disputed"].includes(p.status));
  const hasOpen = !!open;
  const setPosting = (on: boolean) => setParams(on ? { post: "1" } : {}, { replace: true });

  return (
    <div className="bills">
      {/* A neutral tab title: a shared device shouldn't say what this page is. */}
      <Helmet>
        <title>Localz</title>
      </Helmet>
      <Link to="/localz/bills" className="localz-back-link">
        {t("‹ All bills")}
      </Link>
      <h2 className="localz-title">{t("My Neighborz")}</h2>
      {error && <p className="bills-error">{error}</p>}

      {mine === null ? (
        !error && <p className="localz-lede">{t("Loading…")}</p>
      ) : (
        <>
          {posting && !hasOpen ? (
            <PostBillFlow
              onPosted={() => {
                setPosting(false);
                load();
              }}
              onCancel={() => setPosting(false)}
            />
          ) : (
            !hasOpen && (
              <div className="bills-actions">
                <button type="button" className="btn btn-primary" onClick={() => setPosting(true)}>
                  {t("Get help with a bill")}
                </button>
              </div>
            )
          )}

          {mine.posted.length > 0 && (
            <section>
              <h3 className="bills-section">{t("Bills you posted")}</h3>
              <ul className="bills-list">
                {mine.posted.map((p) => (
                  <PostedRow key={p.id} bill={p} onChange={load} />
                ))}
              </ul>
            </section>
          )}

          {open && open.status !== "reported" && (
            <section>
              <h3 className="bills-section">{t("Other help while you wait")}</h3>
              <p className="bills-small">{t("A neighbor may pick up your bill, but there's no promise. These programs can help too.")}</p>
              <OtherHelp county={open.county} limit={5} />
            </section>
          )}

          <section>
            <h3 className="bills-section">{t("Bills you're paying or have paid")}</h3>
            {mine.hold_blocker === "account_too_new" && <p className="bills-small">{t("New accounts can hold a bill after a day.")}</p>}
            {mine.hold_blocker === "paused" && <p className="bills-small">{t("Holding bills is paused on your account.")}</p>}
            {mine.hold_blocker === "too_many_holds" && <p className="bills-small">{t("You've held a few bills today. Try again tomorrow.")}</p>}
            {mine.gifts.length === 0 ? (
              <p className="bills-small">
                {t("None yet.")} <Link to="/localz/bills">{t("See bills waiting for a neighbor")}</Link>
              </p>
            ) : (
              <ul className="bills-list">
                {mine.gifts.map((g) => (
                  <GiftRow key={g.hold_id} gift={g} />
                ))}
              </ul>
            )}
          </section>
        </>
      )}
    </div>
  );
}

function postedText(t: TFunction, p: Posted): string {
  switch (p.status) {
    case "held":
      return t("We're checking your bill before it's listed.");
    case "available":
      return t("Waiting for a neighbor.");
    case "claimed":
      return t("Someone is paying this now.");
    case "reported":
      return t("A neighbor says they paid. Check your PSE&G account: did the payment arrive?");
    case "disputed":
      return t("Thanks for telling us. We're looking into it.");
    case "paid":
      return t("Paid.");
    case "withdrawn":
      return t("You took this down.");
    case "rejected":
      return t("We couldn't list this bill.");
    case "expired":
      return t("No one picked this up in 30 days. You can post it again.");
  }
}

function PostedRow({ bill, onChange }: { bill: Posted; onChange: () => void }) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmWithdraw, setConfirmWithdraw] = useState(false);

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      onChange();
    } catch (err) {
      setError(errorText(t, err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <li className="bills-card">
      <Avatar name={bill.avatar} size={44} />
      <div className="bills-card-body">
        <div className="bills-amount">{dollars(bill.amount_cents)}</div>
        <div className="bills-meta">
          {[bill.utility_name, placeName(t, bill), bill.due_date ? t("Due {{date}}", { date: shortDate(bill.due_date) }) : null].filter(Boolean).join(" · ")}
        </div>
        <p className="bills-status">{postedText(t, bill)}</p>
        {bill.can_answer && (
          <div className="bills-actions">
            <button type="button" className="btn btn-primary" disabled={busy} onClick={() => act(() => answerBill(bill.id, "paid"))}>
              {t("Yes, it arrived")}
            </button>
            <button type="button" className="btn" disabled={busy} onClick={() => act(() => answerBill(bill.id, "not_yet"))}>
              {t("Not yet")}
            </button>
          </div>
        )}
        {bill.can_thank && (
          <div className="bills-thanks" role="group" aria-label={t("Send a thank-you")}>
            <span>{t("Send a thank-you:")}</span>
            {Object.entries(EMOJIS).map(([key, emoji]) => (
              <button type="button" key={key} className="bills-emoji" disabled={busy} onClick={() => act(() => thankGiver(bill.id, key))}>
                {emoji}
              </button>
            ))}
          </div>
        )}
        {bill.thanks && <p className="bills-small">{t("You sent {{emoji}}", { emoji: EMOJIS[bill.thanks] ?? "" })}</p>}
        {bill.can_withdraw &&
          (confirmWithdraw ? (
            <div className="bills-actions">
              <button type="button" className="btn btn-danger" disabled={busy} onClick={() => act(() => withdrawBill(bill.id))}>
                {t("Take it down")}
              </button>
              <button type="button" className="btn" onClick={() => setConfirmWithdraw(false)}>
                {t("Keep it up")}
              </button>
            </div>
          ) : (
            <button type="button" className="btn bills-link" onClick={() => setConfirmWithdraw(true)}>
              {t("Take this bill down")}
            </button>
          ))}
        {error && <p className="bills-error">{error}</p>}
      </div>
    </li>
  );
}

function giftText(t: TFunction, g: Gift): string {
  switch (g.status) {
    case "active":
      return t("You're holding this. {{left}}.", { left: timeLeft(t, g.expires_at) });
    case "reported":
      return t("Waiting for your neighbor to confirm it arrived.");
    case "confirmed":
      return t("Paid. Thank you!");
    case "disputed":
      return t("Your neighbor says it hasn't arrived yet. We're looking into it.");
    case "struck":
      return t("We couldn't confirm this payment.");
    default:
      return "";
  }
}

function GiftRow({ gift }: { gift: Gift }) {
  const { t } = useTranslation();
  return (
    <li className="bills-card">
      <Avatar name={gift.avatar} size={44} />
      <div className="bills-card-body">
        <div className="bills-amount">{dollars(gift.paid_cents ?? gift.amount_cents)}</div>
        <div className="bills-meta">
          {[gift.utility_name, placeName(t, gift), gift.paid_on ? t("Paid {{date}}", { date: shortDate(gift.paid_on) }) : null].filter(Boolean).join(" · ")}
        </div>
        <p className="bills-status">{giftText(t, gift)}</p>
        {gift.confirmation_number && (
          <p className="bills-small">
            {t("Confirmation number")}: <code>{gift.confirmation_number}</code>
          </p>
        )}
        {gift.thanks && <p className="bills-thanked">{t("Your neighbor sent {{emoji}}", { emoji: EMOJIS[gift.thanks] ?? "" })}</p>}
        {gift.status === "active" && (
          <Link className="btn btn-primary" to={`/localz/bills/hold/${gift.hold_id}`}>
            {t("Continue to payment")}
          </Link>
        )}
      </div>
    </li>
  );
}
