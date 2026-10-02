import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useAuth } from "../context/AuthContext";
import { IconLogout } from "./icons";
import { ConfirmDialog } from "./ui/ConfirmDialog";

/** Sign-out used to live only at Account > Security > Sessions, with no
 * entry in the main nav - a findability gap reported directly ("i can't
 * find a log out button"). The username keeps its old behavior (a plain
 * link to /account); a separate icon button confirms before signing out,
 * since it's one tap away from every page now rather than buried in a
 * settings tab. */
export function UserMenu() {
  const { t } = useTranslation();
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);

  if (!user) return null;

  const doLogout = async () => {
    setBusy(true);
    await logout();
    navigate("/", { replace: true });
  };

  return (
    <>
      <Link to="/account" className="ghost">
        {user.username}
      </Link>
      <button
        className="btn icon"
        title={t("Sign out")}
        aria-label={t("Sign out")}
        onClick={() => setConfirming(true)}
      >
        <IconLogout />
      </button>
      <ConfirmDialog
        open={confirming}
        title={t("Sign out?")}
        description={t("You'll need to sign in again to see your account and children.")}
        confirmLabel={t("Sign out")}
        busy={busy}
        onConfirm={doLogout}
        onCancel={() => setConfirming(false)}
      />
    </>
  );
}
