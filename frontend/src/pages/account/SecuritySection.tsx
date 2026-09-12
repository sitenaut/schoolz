import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { IS_SUPABASE_AUTH } from "../../authConfig";
import { IconAlert, IconLock, IconLogout, IconShield } from "../../components/icons";
import { Badge } from "../../components/ui/Badge";
import { ConfirmDialog } from "../../components/ui/ConfirmDialog";
import { Field } from "../../components/ui/Field";
import { SectionCard } from "../../components/ui/SectionCard";
import { useToast } from "../../components/ui/Toast";
import { useAuth } from "../../context/AuthContext";
import { changePassword, deleteAccount } from "../../lib/account";
import { trackEvent } from "../../lib/track";

export function SecuritySection() {
  const { user, logout } = useAuth();
  const toast = useToast();
  const navigate = useNavigate();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [pwBusy, setPwBusy] = useState(false);
  const [pwError, setPwError] = useState<string | null>(null);
  const [pwDone, setPwDone] = useState(false);
  const [delOpen, setDelOpen] = useState(false);
  const [delTyped, setDelTyped] = useState("");
  const [delPassword, setDelPassword] = useState("");
  const [delBusy, setDelBusy] = useState(false);
  const [delError, setDelError] = useState<string | null>(null);

  if (!user) return null;
  const hasPassword = user.sign_in_method !== "google";
  const needsCurrent = !IS_SUPABASE_AUTH;
  const mismatch = confirm.length > 0 && next !== confirm;
  const canSubmit = next.length >= 8 && next === confirm && (!needsCurrent || current.length > 0) && !pwBusy;

  const submitPassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setPwBusy(true);
    setPwError(null);
    setPwDone(false);
    try {
      await changePassword(current, next);
      setCurrent("");
      setNext("");
      setConfirm("");
      setPwDone(true);
      toast({ title: "Password updated", tone: "ok" });
    } catch (err) {
      setPwError(err instanceof Error ? err.message : "Could not change password");
    } finally {
      setPwBusy(false);
    }
  };

  const doDelete = async () => {
    setDelBusy(true);
    setDelError(null);
    try {
      await deleteAccount(needsCurrent && hasPassword ? delPassword : null);
      trackEvent("action", { action: "account_delete", method: "settings" });
      await logout();
      toast({ title: "Your account has been deleted", description: "Sorry to see you go.", tone: "ok" });
      navigate("/", { replace: true });
    } catch (err) {
      setDelError(err instanceof Error ? err.message : "Could not delete account");
      setDelBusy(false);
    }
  };

  return (
    <>
      <SectionCard title="Password" description={hasPassword ? "Choose something you don't use anywhere else." : "This account signs in with Google."} icon={<IconLock />}>
        {hasPassword ? (
          <form onSubmit={submitPassword}>
            {pwError && <div className="form-error">{pwError}</div>}
            {pwDone && <div className="form-ok">Password changed. Use the new one next time you sign in.</div>}
            <div className="fgrid two">
              {needsCurrent && (
                <Field label="Current password" className="span2">
                  <input type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} required />
                </Field>
              )}
              <Field label="New password" hint="At least 8 characters.">
                <input type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} minLength={8} required />
              </Field>
              <Field label="Confirm new password" error={mismatch ? "Passwords don't match" : undefined}>
                <input type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} minLength={8} required />
              </Field>
            </div>
            <div className="sc-ft" style={{ marginTop: 4 }}>
              <button className="btn btn-primary" type="submit" disabled={!canSubmit}>
                {pwBusy ? "Updating…" : "Update password"}
              </button>
            </div>
          </form>
        ) : (
          <div className="info-row">
            <span className="ico">
              <IconShield />
            </span>
            <div className="txt">
              <b>Signed in with Google</b>
              <small>There's no schoolz password to change - manage your password in your Google account.</small>
            </div>
          </div>
        )}
      </SectionCard>

      <SectionCard title="Sessions" description="Where you're signed in." icon={<IconShield />}>
        <div className="info-row">
          <span className="ico">
            <IconShield />
          </span>
          <div className="txt">
            <b>This device</b>
            <small>{IS_SUPABASE_AUTH ? "Session managed by Supabase Auth" : "Local session token"}</small>
          </div>
          <Badge tone="ok" dot>
            Active
          </Badge>
          <button
            className="btn sm"
            onClick={async () => {
              await logout();
              navigate("/", { replace: true });
            }}
          >
            <IconLogout /> Sign out
          </button>
        </div>
      </SectionCard>

      <SectionCard title="Danger zone" description="Irreversible. Take a breath first." icon={<IconAlert />} danger>
        <div className="danger-row">
          <div>
            <b>Delete this account</b>
            <small>
              Removes your profile, your links to your children, invites you sent, notifications, and any connected Gmail account and its scanners.
              Shared records (the children themselves, schools, newsletters) stay for other guardians.
            </small>
          </div>
          <button className="btn solid-danger" onClick={() => setDelOpen(true)}>
            Delete account
          </button>
        </div>
      </SectionCard>

      <ConfirmDialog
        open={delOpen}
        title="Delete your account?"
        description="This cannot be undone. Type DELETE to confirm."
        confirmLabel="Permanently delete"
        danger
        busy={delBusy}
        disabled={delTyped !== "DELETE" || (needsCurrent && hasPassword && !delPassword)}
        onConfirm={doDelete}
        onCancel={() => {
          setDelOpen(false);
          setDelTyped("");
          setDelPassword("");
          setDelError(null);
        }}
      >
        {delError && <div className="form-error">{delError}</div>}
        <Field label="Type DELETE">
          <input value={delTyped} onChange={(e) => setDelTyped(e.target.value)} autoComplete="off" />
        </Field>
        {needsCurrent && hasPassword && (
          <Field label="Your password">
            <input type="password" value={delPassword} onChange={(e) => setDelPassword(e.target.value)} autoComplete="current-password" />
          </Field>
        )}
      </ConfirmDialog>
    </>
  );
}
