import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useAuth } from "../context/AuthContext";
import { IconLogout, IconUser } from "./icons";

/** The signed-in username opens a small menu: Account, and Sign out. Sign-out
 * used to live only at Account > Security > Sessions, which nobody could find;
 * a standalone icon beside the name (#158) replaced an earlier dropdown, and
 * this is the dropdown again by request - a menu item is already a deliberate
 * tap, so there's no separate confirm step. Same anchored-popover pattern as
 * AuthPopover for the signed-out state. */
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
      <button className="ghost" onClick={() => setOpen((v) => !v)} aria-expanded={open} aria-haspopup="menu">
        {user.username}
      </button>
      {open && (
        <div className="authPopover userMenu" role="menu" aria-label={user.username}>
          <Link to="/account" role="menuitem" onClick={() => setOpen(false)}>
            <IconUser /> {t("Account")}
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
