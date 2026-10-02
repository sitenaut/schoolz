import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useAuth } from "../context/AuthContext";
import { IconLogout } from "./icons";

/** The top bar's signed-in username used to be a plain link to /account,
 * with sign-out buried inside Account > Security > Sessions - a real
 * findability gap (reported: "i can't find a log out button"). This gives
 * every page a one-click sign-out next to the account link, same anchored-
 * popover pattern as AuthPopover for the signed-out state. */
export function UserMenu() {
  const { t } = useTranslation();
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (!user) return null;

  return (
    <div className="authPopoverWrap" ref={ref}>
      <button className="ghost" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        {user.username}
      </button>
      {open && (
        <div className="authPopover userMenu" role="menu" aria-label={user.username}>
          <Link to="/account" role="menuitem" onClick={() => setOpen(false)}>
            {t("Account")}
          </Link>
          <button
            role="menuitem"
            onClick={async () => {
              setOpen(false);
              await logout();
              navigate("/", { replace: true });
            }}
          >
            <IconLogout /> {t("Sign out")}
          </button>
        </div>
      )}
    </div>
  );
}
