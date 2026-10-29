import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { SeoHead } from "../../../components/SeoHead";
import { usePrerenderReady } from "../../../lib/prerenderReady";

/** /localz/bills/terms - what a requester agrees to on every post and a
 * giver on every hold (TermsBox; the row keeps the version). When the
 * meaning changes, bump TERMS_VERSION in shared.tsx and the server's
 * catalog.py together, so everyone agrees to the new text before their
 * next post or hold. A draft for counsel to review before launch
 * (docs/NEIGHBORZ_DESIGN.md, build order 0); translated, with the English
 * text the one that counts. */
const SECTIONS: { title: string; points: string[]; lead?: string }[] = [
  {
    title: "1. What Neighborz is, and what it isn't",
    points: [
      "Neighborz is a free listing board. Someone posts a utility bill, and a neighbor can choose to pay it straight to the utility.",
      "We never receive, hold, send or handle money. A payment goes from the person paying directly to the utility, on the utility's own website or phone line, under the utility's own terms.",
      "We are not a charity, a bank, a lender, a payment service or a utility, and we don't act for any utility. Neighborz isn't affiliated with or endorsed by PSE&G or any other utility. Their names are used only to say which bills can be posted.",
      "We don't promise that any bill will be paid, paid on time or paid at all, or that a payment will stop a shutoff.",
    ],
  },
  {
    title: "2. Who can use it",
    points: [
      "You must be 18 or older and have an account. Browsing the list doesn't need either.",
      "A bill you post must be for a home in New Jersey that you live in, on an account that is yours or your household's.",
    ],
  },
  {
    title: "3. If you post a bill",
    points: [
      "What you post is true: a real, current bill for your own home, not changed in any way.",
      "A gift is a gift. If someone pays, you owe them nothing, and nobody may ask you for anything in return. If anyone asks you for money, information or a favor because of Neighborz, tell us.",
      "Keep dealing with your utility yourself. Posting doesn't pause a due date or a shutoff. Keep paying what you can, ask the utility about payment plans and shutoff protections, and apply for the assistance programs listed in Localz. They are your best protection; Neighborz is an extra.",
      "The person who holds your bill sees its account number and service ZIP code, because that's what the utility needs to take a guest payment. We don't show them your name or address. The utility's own payment page may show them something about the account; we don't control that page.",
      "A payment can be reversed by the payer's bank or card company, for example when a card was stolen. The amount is then owed to the utility again, and we can't stop that or make up for it.",
      "Answer honestly when we ask whether a payment arrived.",
      "You can take your bill down at any time before it's paid.",
    ],
  },
  {
    title: "4. If you hold and pay a bill",
    points: [
      "Paying is a voluntary gift from you to a person. It isn't a donation to us or to a charity, and it isn't tax-deductible.",
      "Pay only with your own money, from your own card or bank account, for the exact amount listed, directly to the utility.",
      "Use the account number and ZIP code only to make this one payment. Don't copy, keep or share them, or use them for anything else.",
      "Report only a payment you actually made, with the utility's real confirmation number.",
      "A payment is between you and the utility. We can't cancel, refund or redirect it, and we can't see what the utility did with it. If something goes wrong, contact the utility or your bank. Any fee the utility or its payment service charges is between you and them.",
      "If you can't pay after all, let the bill go so someone else can.",
    ],
  },
  {
    title: "5. Anonymous, both ways",
    points: [
      "Don't try to find out who the other person is, contact them, or tell them who you are. No messages pass between you, by design: the person helped can send one emoji from a fixed set, and that's all.",
    ],
  },
  {
    title: "6. Not allowed",
    points: [
      "Posting someone else's bill, a business account, or a fake, changed or old bill.",
      "Paying with a card, account or money that isn't yours to give.",
      "Holding bills to collect account numbers, using more than one account to get around the limits, harassment, fraud, money laundering, or anything else illegal.",
      "We may take down a bill, end a hold, or pause or close an account. When we believe the law has been broken or someone is at risk, we may share what we have with the utility or the authorities.",
    ],
  },
  {
    title: "7. No promises from us",
    points: [
      "Neighborz is provided free, \"as is\" and \"as available\". An automated (AI) service reads uploaded bills and we run some checks, but we don't verify anyone's identity, need or honesty, and we don't verify payments: we rely on what people tell us.",
      "As far as New Jersey law allows, we make no promises (warranties) that Neighborz will be available, free of errors, or right for any purpose.",
    ],
  },
  {
    title: "8. Waiver and release of liability",
    lead: "By agreeing to these terms, you understand and accept that:",
    points: [
      "Paying a stranger's bill, and having a stranger pay yours, carry risks. A payment may never be made, may be late, may be applied wrongly by the utility, or may be reversed. A shutoff may still happen. Someone may misuse information or break these terms.",
      "You take those risks on yourself, by your own choice.",
      "As far as New Jersey law allows, you release schoolz and the people who run it from all claims, losses and damages arising from: a payment that is made, not made, late, misapplied or reversed; a shutoff, late fee or anything else a utility does; anything another person using Neighborz does or doesn't do; and your use of Neighborz.",
      "This release doesn't cover our own gross negligence, willful misconduct or intent to harm, or anything else New Jersey law doesn't allow to be released.",
    ],
  },
  {
    title: "9. Limit on our liability",
    points: [
      "As far as New Jersey law allows, we aren't liable for indirect, incidental, special, consequential or punitive damages, and our total liability to you for anything to do with Neighborz is limited to $100. The exceptions in section 8 apply here too.",
    ],
  },
  {
    title: "10. You're responsible for what you do",
    points: [
      "If you break these terms or the law while using Neighborz (for example, by posting someone else's bill or paying with a card that isn't yours), you agree to cover the losses and reasonable costs that causes us, as far as New Jersey law allows.",
    ],
  },
  {
    title: "11. Your information",
    points: [
      "The privacy page explains what Neighborz stores and for how long. In short: the account number and ZIP code are encrypted, shown only to the one person holding the bill, and erased 30 days after the bill closes. A photo of a bill is kept only until it's listed or turned down, and a reviewer may look at it.",
    ],
  },
  {
    title: "12. Changes",
    points: [
      "We may change these terms. The date at the top will change, and you'll be asked to agree again before your next post or hold. We may also change, pause or end Neighborz at any time.",
    ],
  },
  {
    title: "13. New Jersey law",
    points: [
      "New Jersey law governs these terms. Nothing in them takes away a right you have under New Jersey law that can't be waived.",
      "These terms are translated so you can read them in your language. If a translation and the English differ, the English version applies.",
    ],
  },
];

export function TermsPage() {
  const { t } = useTranslation();
  usePrerenderReady(true);
  return (
    <div className="bills bills-terms">
      <SeoHead
        title={t("Neighborz terms · Localz")}
        description={t("What you agree to when you post a bill on Neighborz or pay one, including the waiver and release of liability.")}
        path="/localz/bills/terms"
      />
      <Link to="/localz/bills" className="localz-back-link">
        {t("‹ All bills")}
      </Link>
      <h2 className="localz-title">{t("Neighborz terms")}</h2>
      <p className="note">{t("Last updated October 28, 2026.")}</p>
      <p>
        {t(
          "These terms apply when you post a bill on Neighborz or hold a bill to pay it. Ticking the box that says you agree makes them an agreement between you and schoolz (\"we\", \"us\"). They include a waiver and release of liability (section 8). If you don't agree, don't post or hold a bill.",
        )}
      </p>
      {SECTIONS.map((section) => (
        <section key={section.title}>
          <h3>{t(section.title)}</h3>
          {section.lead && <p>{t(section.lead)}</p>}
          <ul>
            {section.points.map((point) => (
              <li key={point}>{t(point)}</li>
            ))}
          </ul>
        </section>
      ))}
      <p>
        {t("Questions about these terms: write to the address on the privacy page.")} <Link to="/privacy">{t("Privacy & cookies")}</Link>
      </p>
    </div>
  );
}
