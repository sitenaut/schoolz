import { createContext, useContext, useState, type ReactNode } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../../context/AuthContext";
import { can } from "../../lib/permissions";
import type { Audience } from "./auditApi";

type AuditCtx = {
  /** Who the wording is for. Always "district" for a view-only user (the
   * server enforces the same). */
  audience: Audience;
  setAudience: (a: Audience) => void;
  canManage: boolean;
  /** Show action buttons: a manager looking at the internal view. The
   * district preview hides them, as a view-only user would see it. */
  showActions: boolean;
};

const Ctx = createContext<AuditCtx | null>(null);
const KEY = "schoolz_audit_audience";

function loadAudience(): Audience {
  try {
    return sessionStorage.getItem(KEY) === "district" ? "district" : "internal";
  } catch {
    return "internal";
  }
}

export function useAudit(): AuditCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAudit must be used within AuditShell");
  return ctx;
}

export function AuditProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const canManage = can(user, "audit.manage");
  const [chosen, setChosen] = useState<Audience>(loadAudience);
  const audience: Audience = canManage ? chosen : "district";
  const setAudience = (a: Audience) => {
    setChosen(a);
    try {
      sessionStorage.setItem(KEY, a);
    } catch {
      /* private mode */
    }
  };
  return <Ctx.Provider value={{ audience, setAudience, canManage, showActions: canManage && audience === "internal" }}>{children}</Ctx.Provider>;
}

export function AudienceToggle() {
  const { audience, setAudience, canManage } = useAudit();
  if (!canManage) return null;
  return (
    <div className="audit-audience no-print" role="group" aria-label="Wording">
      {(
        [
          ["internal", "Internal"],
          ["district", "As the district sees it"],
        ] as [Audience, string][]
      ).map(([a, label]) => (
        <button key={a} type="button" className={`btn sm ${audience === a ? "btn-primary" : ""}`} aria-pressed={audience === a} onClick={() => setAudience(a)}>
          {label}
        </button>
      ))}
    </div>
  );
}

/** Heading + "By school / By data point" tabs shared by the two overview screens. */
export function AuditTabs({ actions }: { actions?: ReactNode }) {
  return (
    <div className="audit-hd">
      <div className="audit-hd-l">
        <div className="ph-upper">Admin</div>
        <h1>Data audit</h1>
        <div className="tabs audit-tabs" role="tablist">
          <NavLink end to="/admin/audit" className={({ isActive }) => `tab ${isActive ? "active" : ""}`}>
            By school
          </NavLink>
          <NavLink to="/admin/audit/data-points" className={({ isActive }) => `tab ${isActive ? "active" : ""}`}>
            By data point
          </NavLink>
        </div>
      </div>
      <div className="audit-hd-a no-print">
        <AudienceToggle />
        {actions}
      </div>
    </div>
  );
}

export function AuditShell() {
  return (
    <AuditProvider>
      <Outlet />
    </AuditProvider>
  );
}
