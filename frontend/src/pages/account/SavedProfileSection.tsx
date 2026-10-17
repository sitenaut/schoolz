import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { IconEdit, IconLock, IconTrash } from "../../components/icons";
import { Badge } from "../../components/ui/Badge";
import { ConfirmDialog } from "../../components/ui/ConfirmDialog";
import { Modal } from "../../components/ui/Modal";
import { SectionCard } from "../../components/ui/SectionCard";
import { useToast } from "../../components/ui/Toast";
import { LOCALE } from "../../lib/i18n";
import { type FitAnswers, forgetDevice, hasAnswers, useLocalzFit } from "../../lib/localzFit";
import { consentIsCurrent, deleteSavedProfile, fetchSavedProfile, type SavedProfileState, saveSavedProfile } from "../../lib/savedProfile";
import { AGE_LABELS, EMPTY_ANSWERS, FOCUS_LABELS, FitQuestions, NEED_LABELS } from "../localz/FitQuestions";
import { SavedProfileConsent } from "../localz/SavedProfileConsent";

function day(iso: string | null): string {
  return iso ? new Date(iso).toLocaleDateString(LOCALE, { month: "long", day: "numeric", year: "numeric" }) : "";
}

/** Account, "My services profile": the Localz answers saved to this
 * account, in plain words, with edit, one-tap delete and the consent
 * behind it. Only the owner ever sees this (backend/routers/saved_profile.py). */
export function SavedProfileSection() {
  const { t } = useTranslation();
  const toast = useToast();
  const device = useLocalzFit();
  const [state, setState] = useState<SavedProfileState | null>(null);
  const [failed, setFailed] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<FitAnswers>(EMPTY_ANSWERS);
  const [consentFor, setConsentFor] = useState<FitAnswers | "review" | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetchSavedProfile()
      .then(setState)
      .catch(() => setFailed(true));
  }, []);

  const save = async (answers: FitAnswers) => {
    setBusy(true);
    try {
      setState(await saveSavedProfile(answers));
      setEditing(false);
      toast({ title: t("Saved to your account"), tone: "ok" });
    } catch {
      toast({ title: t("Couldn't save to your account"), tone: "bad" });
    } finally {
      setBusy(false);
    }
  };

  const submitEdit = () => {
    if (consentIsCurrent(state)) void save(draft);
    else {
      setEditing(false);
      setConsentFor(draft);
    }
  };

  const doDelete = async () => {
    setBusy(true);
    try {
      await deleteSavedProfile();
      setState(await fetchSavedProfile());
      setConfirmDelete(false);
      toast({ title: t("Your saved answers are deleted"), tone: "ok" });
    } catch {
      toast({ title: t("Couldn't delete. Please try again."), tone: "bad" });
    } finally {
      setBusy(false);
    }
  };

  const answers = state?.answers ?? null;
  const current = consentIsCurrent(state);
  const lines: [string, string][] = answers
    ? [
        ["Ages in your household", answers.ages.map((b) => t(AGE_LABELS[b])).join(", ")],
        ["Applies to you or your household", answers.has.map((n) => t(NEED_LABELS[n])).join(", ")],
        ["Services that focus on", answers.focus.map((f) => t(FOCUS_LABELS[f])).join(", ")],
        ["Programs that don't ask about immigration status", answers.noStatusFirst ? t("Shown first") : t("Not turned on")],
      ]
    : [];

  return (
    <>
      <SectionCard
        title={t("My services profile")}
        description={t("Your answers to Localz's eligibility questions, saved so you can use them wherever you're signed in. Only you can see them.")}
        icon={<IconLock />}
        actions={
          state?.available &&
          !(state.saved && !current) && (
            <button
              className="btn sm"
              onClick={() => {
                setDraft(answers ?? EMPTY_ANSWERS);
                setEditing(true);
              }}
            >
              <IconEdit /> {answers ? t("Edit") : t("Add answers")}
            </button>
          )
        }
      >
        {failed ? (
          <p className="note">{t("Couldn't load your saved answers. Please try again later.")}</p>
        ) : state === null ? (
          <p className="note">{t("Loading…")}</p>
        ) : !state.available && !state.saved ? (
          <div className="empty">{t("Saving answers to your account isn't available right now.")}</div>
        ) : state.saved && !current ? (
          <div className="info-row">
            <div className="txt">
              <b>{t("We've changed what's saved")}</b>
              <small>{t("Read what's changed and agree again to keep using your saved answers, or delete them.")}</small>
            </div>
            <button className="btn sm" onClick={() => setConsentFor("review")}>
              {t("Review")}
            </button>
          </div>
        ) : !answers ? (
          <div className="empty">
            {t("Nothing saved. In Localz, open “What am I eligible for?” and turn on “Save to my account”, or add answers here.")}
          </div>
        ) : (
          <>
            {lines.map(([label, value]) => (
              <div className="info-row" key={label}>
                <div className="txt">
                  <small>{t(label)}</small>
                  <b>{value || t("Nothing chosen")}</b>
                </div>
              </div>
            ))}
            <p className="note" style={{ marginTop: 8 }}>
              {t("Last changed {{date}}.", { date: day(state.updated_at) })}
            </p>
          </>
        )}
      </SectionCard>

      {state && (state.saved || state.consent) && (
        <SectionCard title={t("Consent")} description={t("What you agreed to, and how to take it back.")} icon={<IconLock />}>
          <div className="info-row">
            <div className="txt">
              <b>{state.consent ? t("You agreed on {{date}}", { date: day(state.consent.granted_at) }) : t("Not agreed")}</b>
              <small>{t("Deleting your saved answers also withdraws your consent. Both happen right away.")}</small>
            </div>
            <Badge tone={current ? "ok" : "warn"}>{current ? t("Current") : t("Needs review")}</Badge>
          </div>
          <div className="danger-row">
            <div>
              <b>{t("Delete my saved answers")}</b>
              <small>
                {t("Removes them from your account at once. A copy can stay in our encrypted backups for up to about 13 months, until they are replaced.")}
              </small>
            </div>
            <button className="btn solid-danger" onClick={() => setConfirmDelete(true)}>
              <IconTrash /> {t("Delete")}
            </button>
          </div>
        </SectionCard>
      )}

      {device?.remember && (
        <SectionCard title={t("On this device")} description={t("Answers remembered in this browser, separate from your account.")} icon={<IconLock />}>
          <div className="danger-row">
            <div>
              <b>{t("Remembered on this device")}</b>
              <small>{t("Kept in this browser for 90 days. Anyone using it could see them.")}</small>
            </div>
            <button
              className="btn"
              onClick={() => {
                forgetDevice();
                toast({ title: t("Forgotten on this device"), tone: "ok" });
              }}
            >
              {t("Forget this device")}
            </button>
          </div>
        </SectionCard>
      )}

      <Modal
        open={editing}
        onClose={() => setEditing(false)}
        title={t("My services profile")}
        subtitle={t("Answer any of these, or none. Saving with nothing chosen deletes your saved answers.")}
        footer={
          <>
            <button type="button" className="btn" onClick={() => setEditing(false)} disabled={busy}>
              {t("Cancel")}
            </button>
            <button type="button" className="btn btn-primary" onClick={submitEdit} disabled={busy || (!hasAnswers(draft) && !state?.saved)}>
              {t("Save")}
            </button>
          </>
        }
      >
        <div className="localz-fit-sheet">
          <FitQuestions draft={draft} setDraft={setDraft} />
        </div>
      </Modal>

      {consentFor !== null && (
        <SavedProfileConsent
          policyVersion={state?.policy_version ?? 1}
          onCancel={() => setConsentFor(null)}
          onAgreed={(s) => {
            setState(s);
            const pending = consentFor;
            setConsentFor(null);
            if (pending !== "review") void save(pending);
          }}
        />
      )}

      <ConfirmDialog
        open={confirmDelete}
        title={t("Delete your saved answers?")}
        description={t("They're removed from your account right away, and your consent is withdrawn. This can't be undone.")}
        confirmLabel={t("Delete")}
        cancelLabel={t("Cancel")}
        danger
        busy={busy}
        onConfirm={doDelete}
        onCancel={() => setConfirmDelete(false)}
      />
    </>
  );
}
