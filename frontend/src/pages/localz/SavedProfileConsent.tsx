import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Modal } from "../../components/ui/Modal";
import { grantSavedProfileConsent, type SavedProfileState } from "../../lib/savedProfile";

/** The consent screen before anything is saved to an account: its own
 * step, never bundled with signing up, in plain words, unticked by default.
 * What it says is a promise - change it and bump POLICY_VERSION
 * (backend/resources/saved_profile.py), which asks everyone again. */
const POINTS: [string, string][] = [
  [
    "What's saved",
    "Only your answers to these questions: the age ranges of the people in your household, which of the listed situations apply, which kinds of services you want to see first, and the immigration-status setting. Never your name, address, income or anyone's immigration status.",
  ],
  ["Why", "So you can use the same answers on any device where you're signed in. Nothing else: no ads, no selling, no research."],
  [
    "Who can see it",
    "Only you. Not other guardians, even ones linked to the same children, and not schools. No page, report or tool in schoolz shows it to the people who run the site.",
  ],
  ["Where it's kept", "In our database in the United States, locked with its own encryption key. Our server unlocks it only to show it to you."],
  [
    "How long",
    "Until you delete it or delete your account. After that, a copy can stay in our encrypted backups for up to about 13 months, until they are replaced.",
  ],
  ["How to delete it", "One tap in Account, My services profile, or in the eligibility questions. It's deleted right away."],
];

export function SavedProfileConsent({
  policyVersion,
  onAgreed,
  onCancel,
}: {
  policyVersion: number;
  onAgreed: (state: SavedProfileState) => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const [ticked, setTicked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Unticked every time it opens (callers mount it only while open).

  const agree = async () => {
    setBusy(true);
    setError(null);
    try {
      onAgreed(await grantSavedProfileConsent(policyVersion));
    } catch {
      setError(t("That didn't work. Nothing was saved. Please try again."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open
      onClose={onCancel}
      title={t("Save your answers to your account?")}
      subtitle={t("Please read this first. Nothing is saved until you agree.")}
      footer={
        <>
          <button type="button" className="btn" onClick={onCancel} disabled={busy}>
            {t("Not now")}
          </button>
          <button type="button" className="btn btn-primary" onClick={agree} disabled={!ticked || busy}>
            {busy ? t("Saving…") : t("Save to my account")}
          </button>
        </>
      }
    >
      <div className="localz-fit-sheet">
        {POINTS.map(([head, body]) => (
          <div className="localz-fit-group" key={head}>
            <div className="localz-fit-switch-label">{t(head)}</div>
            <p className="localz-muted" style={{ margin: 0 }}>
              {t(body)}
            </p>
          </div>
        ))}
        {error && <div className="form-error">{error}</div>}
        <label className="localz-consent-check">
          <input type="checkbox" checked={ticked} onChange={(e) => setTicked(e.target.checked)} />
          <span>{t("I agree to save my answers to my account, as described above.")}</span>
        </label>
      </div>
    </Modal>
  );
}
