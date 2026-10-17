import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { IconCheck } from "../../components/icons";
import { Modal } from "../../components/ui/Modal";
import { Switch } from "../../components/ui/Switch";
import { useToast } from "../../components/ui/Toast";
import { useAuth } from "../../context/AuthContext";
import { type FitAnswers, forgetDevice, hasAnswers, saveFit, useLocalzFit } from "../../lib/localzFit";
import { consentIsCurrent, fetchSavedProfile, type SavedProfileState, saveSavedProfile } from "../../lib/savedProfile";
import { EMPTY_ANSWERS, FitQuestions } from "./FitQuestions";
import { SavedProfileConsent } from "./SavedProfileConsent";

/** "What am I eligible for?" - or, once answered, "Showing what fits you" -
 * and the sheet behind it. Every question is optional, nothing is required
 * to see listings, and the answers stay on this device (lib/localzFit.ts)
 * unless a signed-in visitor chooses to save them to their account, which
 * takes a consent screen first (SavedProfileConsent). */
export function FitButton() {
  const { t } = useTranslation();
  const toast = useToast();
  const { user } = useAuth();
  const saved = useLocalzFit();
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<FitAnswers>(EMPTY_ANSWERS);
  const [remember, setRemember] = useState(false);
  const [account, setAccount] = useState<SavedProfileState | null>(null);
  const [toAccount, setToAccount] = useState(false);
  const [consentFor, setConsentFor] = useState<FitAnswers | null>(null);

  const start = () => {
    setDraft(saved?.answers ?? EMPTY_ANSWERS);
    setRemember(saved?.remember ?? false);
    setToAccount(false);
    setOpen(true);
    if (user) {
      // Only when the sheet opens: a page view never asks for the profile.
      fetchSavedProfile()
        .then((s) => {
          setAccount(s);
          setToAccount(s.saved && consentIsCurrent(s));
        })
        .catch(() => setAccount(null));
    }
  };

  const toAccountNow = async (answers: FitAnswers) => {
    try {
      setAccount(await saveSavedProfile(answers));
      toast({ title: t("Saved to your account"), tone: "ok" });
    } catch {
      toast({ title: t("Couldn't save to your account"), description: t("Your answers are still used on this device."), tone: "bad" });
    }
  };

  const apply = () => {
    saveFit(draft, remember);
    setOpen(false);
    if (user && account?.available && toAccount && hasAnswers(draft)) {
      if (consentIsCurrent(account)) void toAccountNow(draft);
      else setConsentFor(draft);
    }
  };
  const clear = () => {
    saveFit(null);
    setDraft(EMPTY_ANSWERS);
    setOpen(false);
  };
  const forget = () => {
    forgetDevice();
    setRemember(false);
    toast({ title: t("Forgotten on this device"), tone: "ok" });
  };

  const accountAnswers = account && consentIsCurrent(account) ? account.answers : null;
  const reconsent = !!account?.saved && !consentIsCurrent(account);

  return (
    <>
      <button className={`btn localz-fit-btn${saved ? " on" : ""}`} onClick={start}>
        <IconCheck />
        {saved ? t("Showing what fits you · Edit") : t("What am I eligible for?")}
      </button>
      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title={t("What am I eligible for?")}
        subtitle={t("Answer any of these, or none. Listings that fit get a check mark and move to the top.")}
        footer={
          <>
            {saved && (
              <button type="button" className="btn ghost" onClick={clear}>
                {t("Clear my answers")}
              </button>
            )}
            <button type="button" className="btn btn-primary" onClick={apply}>
              {t("Show what fits me")}
            </button>
          </>
        }
      >
        <div className="localz-fit-sheet">
          {accountAnswers && (
            <div className="localz-fit-group localz-fit-switch">
              <div>
                <div className="localz-fit-switch-label">{t("You have answers saved to your account")}</div>
                <p className="localz-muted">{t("Use them here instead of starting over.")}</p>
              </div>
              <button type="button" className="btn sm" onClick={() => setDraft(accountAnswers)}>
                {t("Use my saved answers")}
              </button>
            </div>
          )}

          <FitQuestions draft={draft} setDraft={setDraft} />

          <div className="localz-fit-group localz-fit-switch">
            <div>
              <div className="localz-fit-switch-label">{t("Remember on this device")}</div>
              <p className="localz-muted">
                {remember
                  ? t("Kept on this phone or computer for 90 days, until you forget it here or use Quick exit. Anyone using it could see your answers.")
                  : t("Otherwise your answers are forgotten when you close this tab or use Quick exit.")}
              </p>
              {saved?.remember && (
                <button type="button" className="btn sm" onClick={forget}>
                  {t("Forget this device")}
                </button>
              )}
            </div>
            <Switch checked={remember} onChange={setRemember} label={t("Remember on this device")} />
          </div>

          {user && account?.available && (
            <div className="localz-fit-group localz-fit-switch">
              <div>
                <div className="localz-fit-switch-label">{t("Save to my account")}</div>
                <p className="localz-muted">
                  {reconsent
                    ? t("We've changed what's saved. Agree again to keep using your saved answers.")
                    : t("Use them on any device where you're signed in. Only you can see them.")}{" "}
                  <Link to="/account/saved-answers">{t("Manage")}</Link>
                </p>
              </div>
              <Switch checked={toAccount} onChange={setToAccount} label={t("Save to my account")} />
            </div>
          )}

          <p className="localz-where-privacy">
            {toAccount && user
              ? t("Localz matches your answers here, on your screen. A copy is kept in your account, encrypted, for you alone.")
              : t("Your answers never leave this device. Localz matches them here, on your screen.")}
          </p>
        </div>
      </Modal>
      {consentFor !== null && (
        <SavedProfileConsent
          policyVersion={account?.policy_version ?? 1}
          onCancel={() => setConsentFor(null)}
          onAgreed={(s) => {
            setAccount(s);
            const answers = consentFor;
            setConsentFor(null);
            void toAccountNow(answers);
          }}
        />
      )}
    </>
  );
}
