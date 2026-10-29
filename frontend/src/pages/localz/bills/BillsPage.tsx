import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { SeoHead } from "../../../components/SeoHead";
import { useAuth } from "../../../context/AuthContext";
import { type PublicBill, dollars, fetchBills, holdBill, shortDate } from "../../../lib/bills";
import { usePrerenderReady } from "../../../lib/prerenderReady";
import { Avatar, TERMS_VERSION, TermsBox, errorText, placeName } from "./shared";

/** /localz/bills - Neighborz: bills waiting for a neighbor, public and
 * anonymous. Holding one needs an account; paying it happens on the
 * utility's own site. */
export function BillsPage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const navigate = useNavigate();
  const [bills, setBills] = useState<PublicBill[] | null>(null);
  const [county, setCounty] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  // The bill whose "I'll pay this" was tapped: it asks for the terms first.
  const [confirming, setConfirming] = useState<string | null>(null);
  const [agreed, setAgreed] = useState(false);
  const [error, setError] = useState<{ id: string; text: string } | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchBills()
      .then((rows) => !cancelled && setBills(rows))
      .catch(() => !cancelled && setBills([]));
    return () => {
      cancelled = true;
    };
  }, []);
  usePrerenderReady(bills !== null);

  const counties = useMemo(() => [...new Set((bills ?? []).map((b) => b.county).filter((c): c is string => !!c))].sort(), [bills]);
  const shown = (bills ?? []).filter((b) => !county || b.county === county);

  const hold = async (bill: PublicBill) => {
    if (!user) {
      navigate(`/login?next=${encodeURIComponent("/localz/bills")}`);
      return;
    }
    if (confirming !== bill.id) {
      setConfirming(bill.id);
      setAgreed(false);
      setError(null);
      return;
    }
    setBusy(bill.id);
    setError(null);
    try {
      const held = await holdBill(bill.id, TERMS_VERSION);
      navigate(`/localz/bills/hold/${held.id}`);
    } catch (err) {
      setError({ id: bill.id, text: errorText(t, err) });
      setBusy(null);
    }
  };

  return (
    <div className="bills">
      <SeoHead
        title={t("Neighborz: neighbors paying each other's utility bills · Localz")}
        description={t("Pay a neighbor's PSE&G bill straight to PSE&G, or ask for help with yours. Anonymous both ways.")}
        path="/localz/bills"
      />
      <h2 className="localz-title">{t("Neighborz")}</h2>
      <p className="localz-lede">{t("Neighbors paying each other's utility bills, straight to the utility. Nobody learns who anyone is.")}</p>

      <div className="bills-actions">
        <Link className="btn btn-primary" to="/localz/bills/mine?post=1">
          {t("Get help with a bill")}
        </Link>
        {user && (
          <Link className="btn" to="/localz/bills/mine">
            {t("My Neighborz")}
          </Link>
        )}
      </div>

      <details className="bills-how">
        <summary>{t("How it works")}</summary>
        <ol>
          <li>{t("Someone posts a bill. You see an avatar, the amount, the town and the due date. Nothing else.")}</li>
          <li>{t("Tap \"I'll pay this\" (you'll need an account). It's yours for 24 hours.")}</li>
          <li>{t("Pay PSE&G as a guest, on their site or by phone, with the account number and ZIP code we show you.")}</li>
          <li>{t("Enter PSE&G's confirmation number here. Your neighbor checks that it arrived.")}</li>
        </ol>
        <p>{t("We never handle money. Your payment goes straight to the utility.")}</p>
      </details>

      {counties.length > 1 && (
        <div className="chips" role="group" aria-label={t("County")}>
          <button type="button" className="chip" aria-pressed={county === null} onClick={() => setCounty(null)}>
            {t("All")}
          </button>
          {counties.map((c) => (
            <button type="button" className="chip" key={c} aria-pressed={county === c} onClick={() => setCounty(c)}>
              {t("{{county}} County", { county: c })}
            </button>
          ))}
        </div>
      )}

      {bills === null ? (
        <p className="localz-lede">{t("Loading…")}</p>
      ) : shown.length === 0 ? (
        <p className="bills-empty">{t("No bills are waiting right now. Check back soon.")}</p>
      ) : (
        <ul className="bills-list">
          {shown.map((b) => (
            <li className={`bills-card ${b.state}`} key={b.id}>
              <Avatar name={b.avatar} size={52} />
              <div className="bills-card-body">
                <div className="bills-amount">{dollars(b.amount_cents)}</div>
                <div className="bills-meta">
                  {[b.utility_name, placeName(t, b)].filter(Boolean).join(" · ")}
                </div>
                <div className="bills-meta">
                  {b.due_date && <span>{t("Due {{date}}", { date: shortDate(b.due_date) })}</span>}
                  {b.shutoff_notice && <span className="bills-shutoff">{t("Shutoff notice")}</span>}
                </div>
                {confirming === b.id && (
                  <div className="bills-confirm">
                    <p className="bills-small">
                      {t("It's yours for 24 hours. We'll show you the account number and ZIP code to pay PSE&G as a guest.")}
                    </p>
                    <TermsBox checked={agreed} onChange={setAgreed} />
                  </div>
                )}
                {error?.id === b.id && <p className="bills-error">{error.text}</p>}
              </div>
              <div className="bills-card-side">
                {b.state === "open" ? (
                  confirming === b.id ? (
                    <>
                      <button type="button" className="btn btn-primary" disabled={busy !== null || !agreed} onClick={() => hold(b)}>
                        {busy === b.id ? t("One moment…") : t("Hold it for me")}
                      </button>
                      <button type="button" className="btn" disabled={busy !== null} onClick={() => setConfirming(null)}>
                        {t("Cancel")}
                      </button>
                    </>
                  ) : (
                    <button type="button" className="btn btn-primary" disabled={busy !== null} onClick={() => hold(b)}>
                      {t("I'll pay this")}
                    </button>
                  )
                ) : b.state === "being_paid" ? (
                  <span className="bills-state">{t("Someone is paying this")}</span>
                ) : (
                  <span className="bills-state paid">{t("Paid")}</span>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}

      <p className="localz-footnote">
        {t("Paying someone's bill is a gift to a person, not a donation to a charity, so it isn't tax-deductible. Keep PSE&G's confirmation number and your receipt for your own records.")}
      </p>
      <p className="localz-footnote">
        <Link to="/localz/bills/terms">{t("Neighborz terms")}</Link>
        {" · "}
        {t("Town names:")} <a href="https://www.geonames.org/">GeoNames</a>, <a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>
      </p>
    </div>
  );
}
