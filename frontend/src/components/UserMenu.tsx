import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useAuth } from "../context/AuthContext";
import { IconLogout, IconSchool, IconUser } from "./icons";

/** The signed-in account button (the username; just an icon on phones) opens a
 * small menu: Account, My schools (phones only, where the header pill is
 * hidden) and Sign out. Sign-out used to live only at Account > Security > Sessions, which nobody could find;
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
      <button
        className="ghost userPill"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="menu"
        aria-label={user.username}
        title={user.username}
      >
        <IconUser />
        <span className="userPillName">{user.username}</span>
      </button>
      {open && (
        <div className="authPopover userMenu" role="menu" aria-label={user.username}>
          <Link to="/account" role="menuitem" onClick={() => setOpen(false)}>
            <IconUser /> {t("Account")}
          </Link>
          {/* The header's My schools pill is hidden on phones once signed in. */}
          <Link to="/start" role="menuitem" className="userMenuMySchools" onClick={() => setOpen(false)}>
            <IconSchool /> {t("My schools")}
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
